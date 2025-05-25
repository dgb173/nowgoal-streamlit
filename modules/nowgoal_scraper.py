# app.py (Archivo principal de Streamlit)
import streamlit as st
# Asegúrate de que los módulos estén en una carpeta 'modules' y que haya un __init__.py vacío en ella
from modules.nowgoal_scraper import display_nowgoal_scraper_ui, get_gsheets_client_and_sheet
from modules.other_feature import display_other_feature_ui # Si tienes este archivo

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

    # Menú lateral para las opciones
    st.sidebar.header("🛠️ Herramientas Disponibles")
    selected_tool = st.sidebar.radio(
        "Selecciona una herramienta:",
        ("1. Extractor de Datos de Nowgoal", "2. Otra Funcionalidad (Beta)", "3. Información General"),
        key="main_tool_selection"
    )

    # --- Gestión de Credenciales de Google Sheets (Centralizada) ---
    gsheets_credentials = None
    gsheets_sh_handle = None # Variable para almacenar el handle de la hoja

    # Intentar cargar las credenciales solo si es necesario para la primera opción
    if selected_tool == "1. Extractor de Datos de Nowgoal":
        try:
            if "gcp_service_account" in st.secrets:
                gsheets_credentials = st.secrets["gcp_service_account"]
                with st.spinner("⚙️ Estableciendo conexión con Google Sheets..."):
                    gc_client, gsheets_sh_handle_temp = get_gsheets_client_and_sheet(gsheets_credentials)

                if not gsheets_sh_handle_temp:
                    st.sidebar.error("❌ Error conectando a GSheets. Verifica secretos y conexión a internet de la app.")
                    st.error("No se pudo conectar a Google Sheets. El extractor no funcionará.")
                else:
                    st.sidebar.success("🔗 Conexión a Google Sheets establecida.")
                    gsheets_sh_handle = gsheets_sh_handle_temp
            else:
                st.sidebar.error("❗️ `gcp_service_account` NO encontrado en `st.secrets` de Streamlit Cloud.")
                st.error("Error de Configuración: Faltan las credenciales de Google Sheets. El extractor no funcionará.")

        except Exception as e:
            st.sidebar.error(f"🆘 Error al procesar credenciales: {str(e)[:100]}...")
            st.error(f"Un error ocurrió con las credenciales: {e}. El extractor no funcionará.")


    # --- Enrutamiento a la Herramienta Seleccionada ---
    if selected_tool == "1. Extractor de Datos de Nowgoal":
        if gsheets_sh_handle:
            # Aquí es donde llamas a la función que contiene la UI del scraper
            display_nowgoal_scraper_ui(gsheets_sh_handle) # Pasas el handle de la hoja
        else:
            st.warning("⚠️ La conexión a Google Sheets es necesaria para esta herramienta y no se pudo establecer o no se han configurado los secretos.")
            st.info("Por favor, asegúrate de que las credenciales `gcp_service_account` estén correctamente configuradas en los secretos de tu aplicación en Streamlit Cloud.")

    elif selected_tool == "2. Otra Funcionalidad (Beta)":
        # Aquí llamarías a la función de UI de tu otro módulo
        display_other_feature_ui() # Asumiendo que la tienes en modules/other_feature.py

    elif selected_tool == "3. Información General":
        st.header("ℹ️ Información General de la Aplicación")
        st.markdown("""
        ---
        ### 📚 Descripción
        Esta es una aplicación multi-herramienta que incluye:
        1.  Un potente **Extractor de Datos de Nowgoal** para análisis de partidos de fútbol.
        2.  Espacio para futuras funcionalidades.

        ### 🔐 Configuración de Credenciales (Google Sheets)
        Para que el **Extractor de Datos de Nowgoal** pueda escribir en tus Google Sheets, necesita credenciales de servicio.
        Configura los secretos en Streamlit Cloud (Sección "Secrets" de tu app) o en tu archivo local `.streamlit/secrets.toml` bajo la clave `gcp_service_account`.
        El contenido del secreto debe ser el TOML que hemos construido.
        ---
        Desarrollado con Streamlit y Python.
        """)

if __name__ == "__main__":
    main()
