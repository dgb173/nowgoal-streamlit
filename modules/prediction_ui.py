import streamlit as st
import pandas as pd
from storage.db import SessionLocal, engine, matches, predictions
from ml.predict import predict_league
import sqlalchemy as sa

def display_prediction_ui():
    st.header("Predicción AH – Motor ML (solo líneas)")
    st.caption("Convención: **línea negativa = favorito visitante**. El modelo no usa probabilidades, solo líneas/estadísticas técnicas.")

    tab_ids, tab_upload = st.tabs(["Pegar IDs", "Subir archivo"])

    match_ids = []

    def parse_ids(raw: str):
        if not raw: return []
        seps = [",",";","\n"," ","\t","|"]
        for s in seps: raw = raw.replace(s, ",")
        ids = [x.strip() for x in raw.split(",") if x.strip()]
        # quitar duplicados preservando orden
        seen = set(); out = []
        for i in ids:
            if i not in seen:
                out.append(i); seen.add(i)
        return out

    with tab_ids:
        raw = st.text_area("Pega aquí los match_id (separados por coma, punto y coma, espacios o saltos de línea):", height=120)
        if raw:
            match_ids = parse_ids(raw)
            st.write(f"IDs detectados: {len(match_ids)}")

    with tab_upload:
        up = st.file_uploader("Subir CSV/JSON con columna `match_id`", type=["csv","json"])
        if up is not None:
            try:
                if up.name.endswith(".csv"):
                    df_up = pd.read_csv(up)
                else:
                    df_up = pd.read_json(up)
                if "match_id" in df_up.columns:
                    # Sobrescribe los IDs del text_area si se sube un archivo
                    match_ids = df_up["match_id"].astype(str).tolist()
                    st.success(f"Leídos {len(match_ids)} IDs del archivo.")
                else:
                    st.error("No encuentro columna `match_id`.")
            except Exception as e:
                st.error(f"Error leyendo archivo: {e}")

    if st.button("Predecir AH"):
        if not match_ids:
            st.warning("Necesito al menos un `match_id`.")
        else:
            # Aquí: carga esos partidos desde tu DB o tu fuente actual
            # Ejemplo: supongamos que ya tienes la tabla matches rellena
            with st.spinner("Buscando partidos en la base de datos y generando predicciones..."):
                try:
                    with engine.connect() as conn:
                        df = pd.read_sql(sa.select(matches).where(matches.c.match_id.in_(match_ids)), conn)

                    if df.empty:
                        st.error("No encontré esos partidos en la base de datos.")
                    else:
                        leagues = df["league_id"].unique().tolist()
                        outs = []
                        for lg in leagues:
                            df_lg = df[df["league_id"]==lg].copy()
                            try:
                                pred = predict_league(df_lg, lg)
                                outs.append(pred)
                            except FileNotFoundError:
                                st.error(f"Falta modelo entrenado para liga '{lg}'. Por favor, vaya a la página 'Entrenar' y entrene el modelo para esta liga.")
                            except Exception as e:
                                st.error(f"Error prediciendo para la liga {lg}: {e}")

                        if outs:
                            res = pd.concat(outs, ignore_index=True)
                            st.dataframe(res)
                            # Opcional: guardar predicciones en la DB
                            # try:
                            #     res_to_db = res[['match_id', 'pred_cover_prob', 'pred_after_rules', 'decision', 'ah_recommendation']].copy()
                            #     res_to_db.to_sql('predictions', engine, if_exists='append', index=False) # Simplificado, para upsert se necesita más lógica
                            #     st.success("Predicciones guardadas en la base de datos.")
                            # except Exception as e:
                            #     st.error(f"No se pudieron guardar las predicciones: {e}")

                except Exception as e:
                    st.error(f"Ocurrió un error general: {e}")
