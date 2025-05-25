# main_app.py
import streamlit as st
from modules.nowgoal_scraper import display_nowgoal_scraper_ui, get_gsheets_client_and_sheet # Importar la UI del scraper y el conector
from modules.other_feature import display_other_feature_ui # Importar la UI de la otra funcionalidad

def main():
    st.set_page_config(
        page_title="Nowgoal Data Scraper",
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
        ("1. Extractor de Datos de Nowgoal", "2. Otra Funcionalidad (Beta)", "3. Información General")
    )

    # --- Gestión de Credenciales de Google Sheets (Centralizada) ---
    gsheets_credentials = None
    gsheets_sh_handle = None
    try:
        if "gcp_service_account" in st.secrets:
            gsheets_credentials = st.secrets["gcp_service_account"]
            # Intentar conectar solo si se necesita una herramienta que use GSheets
            if selected_tool == "1. Extractor de Datos de Nowgoal":
                 with st.spinner("Estableciendo conexión con Google Sheets..."):
                    _, gsheets_sh_handle = get_gsheets_client_and_sheet(gsheets_credentials) # La función está en nowgoal_scraper
                 if not gsheets_sh_handle:
                    st.sidebar.error("Error conectando a GSheets. Verifica secretos y conexión.")
                    st.error("No se pudo conectar a Google Sheets. El extractor no funcionará.")
                    st.stop() # Detener si la conexión es crucial y falla
        else:
            # Mostrar error solo si la herramienta seleccionada requiere las credenciales
            if selected_tool == "1. Extractor de Datos de Nowgoal":
                st.sidebar.error("¡Credenciales de Google Sheets no configuradas en `st.secrets`!")
                st.error("Error: `gcp_service_account` no encontrado en `st.secrets`. El extractor no funcionará.")
                st.stop()

    except Exception as e: # Captura errores generales durante la carga de secretos o conexión inicial
        if selected_tool == "1. Extractor de Datos de Nowgoal":
            st.sidebar.error(f"Error al procesar credenciales: {e}")
            st.error(f"Un error ocurrió con las credenciales: {e}. El extractor no funcionará.")
            st.stop()


    # --- Enrutamiento a la Herramienta Seleccionada ---
    if selected_tool == "1. Extractor de Datos de Nowgoal":
        if gsheets_sh_handle: # Solo mostrar la UI si la conexión a GSheets fue exitosa
            display_nowgoal_scraper_ui(gsheets_sh_handle) # Pasar el handle de la hoja
        else:
            st.warning("La conexión a Google Sheets es necesaria para esta herramienta y no se pudo establecer.")

    elif selected_tool == "2. Otra Funcionalidad (Beta)":
        display_other_feature_ui()

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
        Configura los secretos en Streamlit Cloud o en tu archivo local `.streamlit/secrets.toml` bajo la clave `gcp_service_account`.

        Ejemplo de `secrets.toml`:
        ```toml
        [gcp_service_account]
        type = "service_account"
        project_id = "tu-proyecto-gcp"
        private_key_id = "tu_private_key_id"
        private_key = "-----BEGIN PRIVATE KEY-----\\n...\\n-----END PRIVATE KEY-----\\n"
        client_email = "tu-email-de-servicio@tu-proyecto-gcp.iam.gserviceaccount.com"
        # ... y el resto de campos
        ```
        **Importante:** Asegúrate de que `private_key` incluya los `\\n` para los saltos de línea.

        ---
        Desarrollado con ❤️ y Python.
        """)

if __name__ == "__main__":
    main()
