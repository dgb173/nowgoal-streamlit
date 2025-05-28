# app.py
import streamlit as st
import pandas as pd

# Asegúrate de que estos módulos y funciones existan y sean correctos
from modules.nowgoal_scraper import display_nowgoal_scraper_ui, get_gsheets_client_and_sheet
from modules.other_feature_NUEVO import display_other_feature_ui
from modules.scrap import scrape_match_data # Importar la función de scraping

import logging

# Configurar logging (opcional, pero recomendado para depuración)
# logger = logging.getLogger(__name__)
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# --- Configuración de la página e Interfaz de Streamlit ---
# ESTA ES LA ÚNICA Y CORRECTA UBICACIÓN PARA st.set_page_config
st.set_page_config(
    page_title="⚽📊 App de Análisis y Herramientas",
    layout="wide",
    page_icon="⚽", # Puedes poner un emoji o la URL de un favicon
    initial_sidebar_state="expanded",
    menu_items={
       'Get Help': 'https://www.example.com/help', # Cambia esto
       'Report a bug': "https://www.example.com/bug", # Cambia esto
       'About': "# App de Análisis de Datos y Herramientas Deportivas" # Cambia esto
    }
)

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
    if 'scraping_in_progress_live' not in st.session_state: # Nombre específico para esta herramienta
        st.session_state.scraping_in_progress_live = False

    if st.button("🚀 Extraer Datos de Partidos Ahora", key="btn_nowgoal_live_scraper", disabled=st.session_state.scraping_in_progress_live):
        st.session_state.nowgoal_live_scrape_attempted = True
        st.session_state.scraping_in_progress_live = True
        st.rerun() # Para actualizar el estado del botón inmediatamente

        with st.spinner(f"Accediendo a {fixed_url} y extrayendo datos... (esto puede tardar unos momentos)"):
            df_matches_new = scrape_match_data(fixed_url) # Asegúrate que esta función existe y es robusta

        st.session_state.scraping_in_progress_live = False

        if df_matches_new is None:
            st.error("Ocurrió un error crítico durante el scraping (ej. timeout, problema de red o la página no es accesible). Por favor, verifica los logs o intenta más tarde.")
            st.session_state.nowgoal_live_df = pd.DataFrame() # Asegurar que el df se limpia
        elif isinstance(df_matches_new, pd.DataFrame):
            if not df_matches_new.empty:
                st.session_state.nowgoal_live_df = df_matches_new
                st.success(f"¡Scraping completado! Se encontraron {len(st.session_state.nowgoal_live_df)} partidos.")
            else:
                st.info("Se accedió a la página, pero no se encontraron datos de partidos con la estructura esperada o la tabla estaba vacía. El sitio podría no tener partidos en este momento.")
                st.session_state.nowgoal_live_df = pd.DataFrame()
        else:
             st.error("El scraping devolvió un tipo de dato inesperado.")
        st.rerun() # Para mostrar los resultados o mensajes

    if not st.session_state.nowgoal_live_df.empty:
        st.dataframe(st.session_state.nowgoal_live_df, use_container_width=True, hide_index=True)
    elif st.session_state.nowgoal_live_scrape_attempted and not st.session_state.scraping_in_progress_live:
        st.info("No hay datos de partidos para mostrar. Intenta extraerlos de nuevo o verifica si hay partidos disponibles en la fuente.")


# Lógica principal de la aplicación
if selected_tool == "1. Extractor de Datos de Nowgoal":
    st.sidebar.info("Esta herramienta requiere configuración de Google Sheets.")
    gsheets_sh = None # Variable local para esta herramienta

    if "gcp_service_account" in st.secrets:
        gsheets_credentials = st.secrets["gcp_service_account"]
        try:
            # Asumiendo que get_gsheets_client_and_sheet devuelve (client, sheet_handle)
            # o lanza una excepción si falla.
            g_client, gsheets_sh = get_gsheets_client_and_sheet(gsheets_credentials)
            if gsheets_sh:
                st.success("Conexión a Google Sheets establecida.")
                display_nowgoal_scraper_ui(gsheets_sh) # Pasa el handle obtenido
            else:
                st.error("No se pudo obtener el handle de Google Sheets, aunque las credenciales existen. Verifica la función get_gsheets_client_and_sheet.")
        except Exception as e:
            st.error(f"Error al conectar o configurar Google Sheets: {e}")
            # logger.error(f"Error en get_gsheets_client_and_sheet: {e}", exc_info=True) # Si usas logging
    else:
        st.error("Error de Configuración: Faltan credenciales `gcp_service_account` para Google Sheets en los secretos de Streamlit.")
        st.info("Por favor, configura los secretos para habilitar esta funcionalidad.")


elif selected_tool == "2. Otra Funcionalidad (Beta)":
    # Esta función ya NO debe tener st.set_page_config() dentro de ella.
    display_other_feature_ui()

elif selected_tool == "3. Scrapear Partidos (Nowgoal Live)":
    display_nowgoal_live_scraper_ui()

st.markdown("---")
st.caption("Aplicación construida con Streamlit. Contactar para soporte.")
