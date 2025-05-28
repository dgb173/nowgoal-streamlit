import streamlit as st
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import pandas as pd
import logging

# Configurar logging básico (descomentar para depuración local, no recomendado para Streamlit Cloud sin más configuración)
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# logger = logging.getLogger(__name__)

def scrape_match_data(url: str):
    # logger.info(f"Iniciando scrape para URL: {url}")
    match_list = []
    
    try:
        with sync_playwright() as p:
            # logger.info("Lanzando navegador Chromium...")
            browser = p.chromium.launch(
                headless=True,
                timeout=60000, # Timeout para el lanzamiento
                args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
            )
            page = browser.new_page()
            # logger.info(f"Navegando a {url}...")
            
            try:
                # wait_until puede ser 'load', 'domcontentloaded', 'networkidle'
                page.goto(url, timeout=90000, wait_until='domcontentloaded') 
            except PlaywrightTimeoutError:
                # logger.error(f"Timeout al cargar la página: {url}")
                st.error(f"Timeout al intentar cargar la página: {url}. La página podría ser muy lenta, estar bloqueando bots o no ser accesible.")
                browser.close()
                return None
            except Exception as e:
                # logger.error(f"Error al navegar a {url}: {e}")
                st.error(f"Error al navegar a {url}: {e}")
                browser.close()
                return None

            # Esperar a que la tabla principal de partidos (#table_live) y al menos una fila de partido (tr.tds[matchid]) estén presentes.
            try:
                page.wait_for_selector('#table_live tr.tds[matchid]', timeout=45000)
                # logger.info("Tabla de partidos y al menos una fila de partido encontrada.")
            except PlaywrightTimeoutError:
                # logger.warning("Timeout esperando por filas de partidos. La tabla '#table_live tr.tds[matchid]' podría estar vacía o tardando mucho en cargar.")
                st.info("No se encontraron partidos con la estructura esperada (tabla '#table_live' con filas '.tds[matchid]'). La página podría no tener partidos o su estructura ha cambiado.")
                browser.close()
                return pd.DataFrame() # Devuelve un DataFrame vacío

            match_rows = page.query_selector_all('#table_live tr.tds[matchid]')
            # logger.info(f"Encontradas {len(match_rows)} filas de partidos.")

            if not match_rows:
                st.info("Se accedió a la página y se encontró la tabla, pero no se encontraron filas de partidos con el selector 'tr.tds[matchid]'.")
                browser.close()
                return pd.DataFrame()

            for i, row in enumerate(match_rows):
                # logger.info(f"Procesando fila {i+1}...")
                match_id = row.get_attribute('matchid')
                if not match_id:
                    # logger.warning(f"Fila {i+1} no tiene matchid, saltando.")
                    continue

                time_val = "N/A"
                time_element_mt = row.query_selector(f'td#mt_{match_id}[name="timeData"]')
                if time_element_mt:
                    data_t = time_element_mt.get_attribute('data-t')
                    if data_t and ' ' in data_t: # Formato esperado "YYYY-MM-DD HH:MM:SS"
                        try:
                            time_val = data_t.split(" ")[1][:5] # Extrae "HH:MM"
                        except IndexError:
                            # logger.warning(f"Error al parsear data-t para match {match_id}: {data_t}")
                            time_val = data_t # Usar el valor como está si no se puede splitear
                    elif data_t: # Si data-t no es el formato completo pero existe.
                        time_val = data_t
                    else: # Si data-t no existe, intentar con el text_content de ese td.
                        time_val_text = time_element_mt.text_content().strip()
                        if time_val_text and ":" in time_val_text:
                            time_val = time_val_text
                # logger.info(f"Match ID {match_id} - Hora preliminar: {time_val}")
                
                home_team_name = "N/A"
                home_team_anchor = row.query_selector(f'td[id="ht_{match_id}"] > a[id="team1_{match_id}"]')
                if home_team_anchor:
                    home_team_name_full = home_team_anchor.text_content()
                    home_team_name = home_team_name_full.split('(N)')[0].strip() if home_team_name_full else "N/A"
                # logger.info(f"Match ID {match_id} - Equipo Local: {home_team_name}")

                away_team_name = "N/A"
                away_team_anchor = row.query_selector(f'td[id="gt_{match_id}"] > a[id="team2_{match_id}"]')
                if away_team_anchor:
                    away_team_name_full = away_team_anchor.text_content()
                    away_team_name = away_team_name_full.split('(N)')[0].strip() if away_team_name_full else "N/A"
                # logger.info(f"Match ID {match_id} - Equipo Visitante: {away_team_name}")
                
                score = "N/A"
                # El selector para el resultado es el <td> entre los nombres de los equipos. Suele tener la clase 'blue handpoint'
                # y contiene un <b> con el resultado.
                score_cell = row.query_selector('td.blue.handpoint > b') 
                if score_cell:
                    score_text = score_cell.text_content().strip()
                    if score_text and score_text != "-": # Si hay un resultado real.
                        score = score_text
                    elif score_text == "-":
                         score = "Por Jugar" # O "-", como prefieras
                else: # Si no hay <b>, intentar tomar el texto del td directamente (podría ser "-" si no ha empezado)
                    score_cell_fallback = row.query_selector('td.blue.handpoint')
                    if score_cell_fallback:
                        score_text_fallback = score_cell_fallback.text_content().strip()
                        score = score_text_fallback if score_text_fallback else "N/A"
                        if score == "-":
                            score = "Por Jugar"

                # logger.info(f"Match ID: {match_id}, Hora: {time_val}, Local: {home_team_name}, Resultado: {score}, Visitante: {away_team_name}")
                match_list.append({
                    "ID Partido": match_id,
                    "Hora": time_val,
                    "Equipo Local": home_team_name,
                    "Resultado": score,
                    "Equipo Visitante": away_team_name
                })
            
            browser.close()
            # logger.info("Navegador cerrado. Scraping completado.")
            return pd.DataFrame(match_list)

    except PlaywrightTimeoutError:
        # logger.error("Timeout general en Playwright durante el scrapeo.")
        st.error(f"Timeout general durante la operación de Playwright. El servidor podría estar sobrecargado, la web ser muy compleja o se cortó la conexión.")
        if 'browser' in locals() and browser.is_connected():
            browser.close()
        return None
    except Exception as e:
        # logger.error(f"Error general en Playwright: {e}", exc_info=True)
        st.error(f"Ocurrió un error inesperado durante el scraping: {e}")
        if 'browser' in locals() and browser.is_connected():
            browser.close()
        return None

# --- Interfaz de Streamlit ---
st.set_page_config(page_title="Resultados de Fútbol Scraper", layout="wide")
st.title("⚽ Resultados de Fútbol Scraper para Nowgoal")
st.markdown("""
Ingresa la URL de la página de Nowgoal (ej: `https://www.nowgoal.com/football/live` o una específica de resultados) 
que contiene la tabla de partidos con `id="table_live"`.
El scraper intentará extraer el ID del partido, hora, equipos y resultado.
**Nota:** Funciona mejor con URLs de partidos en vivo o próximas jornadas.
""")

url_input = st.text_input(
    "URL de Nowgoal:", 
    placeholder="Ej: https://www.nowgoal.com/football/live"
)

if 'partidos_df' not in st.session_state:
    st.session_state.partidos_df = pd.DataFrame()

if st.button("🔎 Extraer Información de Partidos", type="primary"):
    if not url_input:
        st.warning("Por favor, ingresa una URL.")
    elif not (url_input.startswith("http://") or url_input.startswith("https://")):
        st.warning("Por favor, ingresa una URL válida (ej: http:// o https://).")
    elif "nowgoal" not in url_input: # Una pequeña validación para guiar al usuario
        st.warning("Asegúrate de que la URL sea de un sitio Nowgoal compatible con la estructura de tabla esperada.")
    else:
        with st.spinner(f"Accediendo a {url_input} y extrayendo datos de partidos... (esto puede tardar unos momentos)"):
            df_matches_new = scrape_match_data(url_input)

        if df_matches_new is not None:
            if not df_matches_new.empty:
                st.session_state.partidos_df = df_matches_new
                st.success(f"¡Scraping de partidos completado! Se encontraron {len(st.session_state.partidos_df)} partidos.")
            elif isinstance(df_matches_new, pd.DataFrame) and df_matches_new.empty:
                 # No actualizar st.session_state.partidos_df si df_matches_new está vacío pero no es None
                st.info("Se accedió a la página, pero no se encontraron datos de partidos o la tabla estaba vacía. Mostrando resultados anteriores si existen.")
            # Si df_matches_new es None, scrape_match_data ya mostró un error
        # else: (si es None, el error ya fue mostrado)

if not st.session_state.partidos_df.empty:
    st.dataframe(st.session_state.partidos_df, use_container_width=True, hide_index=True)
elif url_input and not st.button("🔎 Extraer Información de Partidos", key="dummy_para_evitar_ejecucion_doble_en_ciertos_casos"): # Mostrar solo si se ha intentado buscar
    st.info("No hay datos de partidos para mostrar. Ingresa una URL y presiona el botón.")


st.markdown("---")
st.caption("Hecho con Streamlit y Playwright. Asegúrate de que los archivos `requirements.txt`, `packages.txt` y `setup.sh` estén correctamente configurados si despliegas en Streamlit Cloud.")
