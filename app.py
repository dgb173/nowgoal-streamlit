# app.py
import streamlit as st
import pandas as pd
from modules.nowgoal_scraper import display_nowgoal_scraper_ui, get_gsheets_client_and_sheet
from modules.other_feature_NUEVO import display_other_feature_ui
from modules.scrap import scrape_match_data # Importar la función de scraping
import logging

# Configurar logging (opcional)
# logger = logging.getLogger(__name__)
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# --- Configuración de la página e Interfaz de Streamlit ---
st.set_page_config(page_title="Resultados de Fútbol Scraper", layout="wide")

st.title("⚽📊 App de Análisis de Datos y Herramientas 📊⚽")
st.markdown("""
Bienvenido a la aplicación central. Usa el menú lateral para navegar entre las diferentes herramientas disponibles.
""")

st.sidebar.header("🛠️ Herramientas Disponibles")
selected_tool = st.sidebar.radio(
    "Selecciona una herramienta:",
    ("1. Extractor de Datos de Nowgoal", "2. Otra Funcionalidad (Beta)", "3. Scrapear Partidos (Nowgoal Live)"),
    key="main_tool_selection_final"
)

gsheets_sh_handle = None # Para la herramienta 1

def display_nowgoal_live_scraper_ui():
    """
    UI y lógica para el scraper de Nowgoal con URL fija.
    """
    st.subheader("🏆 Scraper de Partidos en Vivo de Nowgoal")
    
    fixed_url = "https://live18.nowgoal25.com/"
    st.markdown(f"**URL Fija para el scraping:** `{fixed_url}`")

    if 'nowgoal_live_df' not in st.session_state:
        st.session_state.nowgoal_live_df = pd.DataFrame()
    if 'nowgoal_live_scrape_attempted' not in st.session_state:
        st.session_state.nowgoal_live_scrape_attempted = False

    if st.button("🚀 Extraer Datos de Partidos Ahora", key="btn_nowgoal_live_scraper"):
        st.session_state.nowgoal_live_scrape_attempted = True
        with st.spinner(f"Accediendo a {fixed_url} y extrayendo datos... (esto puede tardar unos momentos)"):
            df_matches_new = scrape_match_data(fixed_url) 

        if df_matches_new is None:
            st.error("Ocurrió un error crítico durante el scraping (ej. timeout de Playwright, problema de red o la página no es accesible). Por favor, verifica los logs de Streamlit Cloud para más detalles (si es posible) o intenta más tarde.")
        elif isinstance(df_matches_new, pd.DataFrame):
            if not df_matches_new.empty:
                st.session_state.nowgoal_live_df = df_matches_new
                st.success(f"¡Scraping completado! Se encontraron {len(st.session_state.nowgoal_live_df)} partidos.")
            else: 
                st.info("Se accedió a la página, pero no se encontraron datos de partidos con la estructura esperada o la tabla estaba vacía. El sitio podría no tener partidos en este momento.")
                st.session_state.nowgoal_live_df = pd.DataFrame()
        else:
             st.error("El scraping devolvió un tipo de dato inesperado.")

    if not st.session_state.nowgoal_live_df.empty:
        st.dataframe(st.session_state.nowgoal_live_df, use_container_width=True, hide_index=True)
    elif st.session_state.nowgoal_live_scrape_attempted:
        st.info("No hay datos de partidos para mostrar. Intenta extraerlos de nuevo.")


# Lógica principal de la aplicación
if selected_tool == "1. Extractor de Datos de Nowgoal":
    # Esta sección asume que tienes las credenciales y funciones como antes
    st.sidebar.info("Esta herramienta requiere configuración de Google Sheets.")
    if "gcp_service_account" in st.secrets:
        gsheets_credentials = st.secrets["gcp_service_account"]
        # _, gsheets_sh_handle = get_gsheets_client_and_sheet(gsheets_credentials) # Descomentar si la función existe
        if gsheets_sh_handle: # Asumiendo que get_gsheets... define esto
             display_nowgoal_scraper_ui(gsheets_sh_handle) # Asumiendo que esta función existe
        else:
             st.error("No se pudo conectar a Google Sheets para el 'Extractor de Datos de Nowgoal'.")
    else:
        st.error("Error de Configuración: Faltan credenciales `gcp_service_account` para Google Sheets.")


elif selected_tool == "2. Otra Funcionalidad (Beta)":
    # Asumiendo que esta función existe
    display_other_feature_ui() 

elif selected_tool == "3. Scrapear Partidos (Nowgoal Live)":
    display_nowgoal_live_scraper_ui() # Llama a la nueva UI específica

st.markdown("---")
st.caption("Aplicación construida con Streamlit. Contactar para soporte.")
