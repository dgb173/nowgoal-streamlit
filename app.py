# app.py
import streamlit as st
import pandas as pd # Necesario para manejar DataFrames

# Asumiendo que estas funciones existen y funcionan como se espera en sus respectivos módulos
from modules.nowgoal_scraper import display_nowgoal_scraper_ui, get_gsheets_client_and_sheet
from modules.scrap import scrape_match_data # <- Importación de nuestra función de scraping
from modules.other_feature_NUEVO import display_other_feature_ui

def display_generic_scraper_ui():
    """
    Función para encapsular la UI y lógica del scraper genérico de partidos.
    """
    st.subheader("🛠️ Herramienta de Scraping de Partidos (tipo Nowgoal)")
    st.markdown("""
    Ingresa la URL de una página (ej. Nowgoal) que contenga una tabla de partidos
    con la estructura HTML esperada (tabla con `id="table_live"`, etc.)
    para extraer datos de los partidos listados.
    """)

    url_input_scraper = st.text_input(
        "URL para scrapear datos de partidos:",
        placeholder="Ej: https://live18.nowgoal25.com/",
        key="url_input_generic_scraper_tool3" # Clave única para este input
    )

    # Inicializar el DataFrame para esta herramienta en session_state si no existe
    if 'tool3_scraper_df' not in st.session_state:
        st.session_state.tool3_scraper_df = pd.DataFrame()
    if 'tool3_scrape_attempted' not in st.session_state:
        st.session_state.tool3_scrape_attempted = False


    if st.button("🔎 Extraer Datos de la URL", key="btn_generic_scraper_tool3"):
        st.session_state.tool3_scrape_attempted = True
        if not url_input_scraper:
            st.warning("Por favor, ingresa una URL para scrapear.")
        elif not (url_input_scraper.startswith("http://") or url_input_scraper.startswith("https://")):
            st.warning("Por favor, ingresa una URL válida (ej: http:// o https://).")
        else:
            with st.spinner(f"Accediendo a {url_input_scraper} y extrayendo datos..."):
                df_matches_new = scrape_match_data(url_input_scraper) # Usamos la función importada

            if df_matches_new is None:
                st.error("Ocurrió un error crítico durante el scraping (ej. timeout de Playwright, problema de red o la página no es accesible). Por favor, verifica la URL y tu conexión, o intenta más tarde.")
            elif isinstance(df_matches_new, pd.DataFrame):
                if not df_matches_new.empty:
                    st.session_state.tool3_scraper_df = df_matches_new
                    st.success(f"¡Scraping de partidos completado! Se encontraron {len(st.session_state.tool3_scraper_df)} partidos.")
                else:
                    st.info("Se accedió a la página, pero no se encontraron datos de partidos con la estructura esperada o la tabla estaba vacía.")
                    st.session_state.tool3_scraper_df = pd.DataFrame()
            else:
                 st.error("El scraping devolvió un tipo de dato inesperado.")

    if not st.session_state.tool3_scraper_df.empty:
        st.dataframe(st.session_state.tool3_scraper_df, use_container_width=True, hide_index=True)
    elif st.session_state.tool3_scrape_attempted:
        st.info("No hay datos de partidos para mostrar para esta URL. Ingresa una URL válida y presiona el botón.")


def main():
    st.set_page_config(
        page_title="Nowgoal Data Scraper & Tools",
        page_icon="⚽",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    st.title("⚽📊 App de Análisis de Datos y Herramientas 📊⚽")
    st.markdown("""
    Bienvenido a la aplicación central. Usa el menú lateral para navegar entre las diferentes herramientas disponibles.
    """)

    st.sidebar.header("🛠️ Herramientas Disponibles")
    selected_tool = st.sidebar.radio(
        "Selecciona una herramienta:",
        ("1. Extractor de Datos de Nowgoal", "2. Otra Funcionalidad (Beta)", "3. Scrapear datos"),
        key="main_tool_selection_final"
    )

    gsheets_sh_handle = None

    if selected_tool == "1. Extractor de Datos de Nowgoal":
        try:
            if "gcp_service_account" in st.secrets:
                gsheets_credentials = st.secrets["gcp_service_account"]
                with st.spinner("⚙️ Estableciendo conexión con Google Sheets..."):
                    _, gsheets_sh_handle_temp = get_gsheets_client_and_sheet(gsheets_credentials)

                if not gsheets_sh_handle_temp:
                    st.sidebar.error("❌ Error conectando a GSheets. Verifica secretos y conexión.")
                    st.error("No se pudo conectar a Google Sheets. El extractor no funcionará.")
                else:
                    st.sidebar.success("🔗 Conexión a Google Sheets establecida.")
                    gsheets_sh_handle = gsheets_sh_handle_temp
            else:
                # No mostrar error si el usuario no ha seleccionado esta herramienta.
                # Podrías querer una advertencia si `selected_tool` es el Extractor.
                if selected_tool == "1. Extractor de Datos de Nowgoal":
                    st.sidebar.error("❗️ `gcp_service_account` NO encontrado en `st.secrets`.")
                    st.error("Error de Configuración: Faltan las credenciales de Google Sheets para esta herramienta.")


        except Exception as e:
            st.sidebar.error(f"🆘 Error al procesar credenciales GSheets: {str(e)[:100]}...")
            st.error(f"Un error ocurrió con las credenciales de Google Sheets: {e}.")

    # Lógica para mostrar la herramienta seleccionada
    if selected_tool == "1. Extractor de Datos de Nowgoal":
        if gsheets_sh_handle:
            display_nowgoal_scraper_ui(gsheets_sh_handle)
        else:
            # Este mensaje se mostrará si la opción 1 está seleccionada pero gsheets_sh_handle no se pudo obtener
            st.warning("⚠️ La conexión a Google Sheets es necesaria para 'Extractor de Datos de Nowgoal' y no se pudo establecer.")
            st.info("Asegúrate de que `gcp_service_account` esté configurado correctamente en los secretos de Streamlit si deseas usar esta funcionalidad.")

    elif selected_tool == "2. Otra Funcionalidad (Beta)":
        display_other_feature_ui()
    
    elif selected_tool == "3. Scrapear datos":
        # Aquí llamamos a la función que contendrá la UI y lógica del scraper
        display_generic_scraper_ui()


if __name__ == "__main__":
    main()
