import streamlit as st
import pandas as pd
from storage.db import engine, matches
from ml.train import train_league
import sqlalchemy as sa

def display_training_ui():
    st.header("Entrenar modelos por liga (TimeSeriesSplit)")

    try:
        # supón que ya has poblado `matches` con históricos (con goles reales)
        with st.spinner("Cargando datos históricos desde la base de datos..."):
            with engine.connect() as conn:
                df_all = pd.read_sql(sa.select(matches), conn)

        if df_all.empty:
            st.warning("La tabla 'matches' en la base de datos está vacía. No hay datos para entrenar.")
            st.info("Asegúrate de poblar la base de datos usando un script que llame a la función `upsert_matches` en `storage/db.py`.")
            return

        ligas = sorted(df_all["league_id"].dropna().unique().tolist())
        if not ligas:
            st.warning("No se encontraron 'league_id' en los datos. No se puede entrenar.")
            return

        sel = st.multiselect("Elige ligas a reentrenar", ligas)

        if st.button("Entrenar"):
            if not sel:
                st.warning("Por favor, selecciona al menos una liga para entrenar.")
                return

            progress_bar = st.progress(0)
            total_leagues = len(sel)

            for i, lg in enumerate(sel):
                st.write(f"---")
                st.write(f"Entrenando liga: **{lg}** ({i+1}/{total_leagues})")
                with st.spinner(f"Procesando y entrenando {lg}..."):
                    try:
                        # Filtrar datos con resultados para entrenar
                        df_league_train = df_all[df_all['league_id'] == lg].copy()
                        if df_league_train['home_goals'].isna().all() or df_league_train['away_goals'].isna().all():
                             st.error(f"Error entrenando {lg}: No hay datos de resultados (goles) para esta liga.")
                             continue

                        score = train_league(df_all, lg) # Pasamos todo el df para que train_league filtre
                        st.success(f"✅ Liga {lg}: entrenamiento OK (score medio calibrado ~ {score:.3f})")
                    except Exception as e:
                        st.error(f"❌ Error entrenando {lg}: {e}")

                progress_bar.progress((i + 1) / total_leagues)
            st.write("---")
            st.success("¡Proceso de entrenamiento completado para las ligas seleccionadas!")

    except Exception as e:
        st.error(f"No se pudo conectar o leer de la base de datos: {e}")
        st.info("Asegúrate de que el archivo 'data/ah.db' exista y sea accesible. Se crea automáticamente al ejecutar `storage/db.py` por primera vez.")
