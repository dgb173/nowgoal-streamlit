# app.py (Archivo principal de Streamlit)
import streamlit as st
# Importar las funciones de UI de los módulos
from modules.nowgoal_scraper import display_nowgoal_scraper_ui, get_gsheets_client_and_sheet
from modules.other_feature import display_other_feature_ui

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

    gsheets_credentials = None
    gsheets_sh_handle = None

    if selected_tool == "1. Extractor de Datos de Nowgoal":
        try:
            if "gcp_service_account" in st.secrets:
                gsheets_credentials = st.secrets["gcp_service_account"]
                with st.spinner("⚙️ Estableciendo conexión con Google Sheets..."):
                    gc_client, gsheets_sh_handle_temp = get_gsheets_client_and_sheet(gsheets_credentials)

                if not gsheets_sh_handle_temp:
                    st.sidebar.error("❌ Error conectando a GSheets. Verifica secretos y conexión.")
                    st.error("No se pudo conectar a Google Sheets. El extractor no funcionará.")
                else:
                    st.sidebar.success("🔗 Conexión a Google Sheets establecida.")
                    gsheets_sh_handle = gsheets_sh_handle_temp
            else:
                st.sidebar.error("❗️ `gcp_service_account` NO encontrado en `st.secrets`.")
                st.error("Error de Configuración: Faltan las credenciales de Google Sheets.")

        except Exception as e:
            st.sidebar.error(f"🆘 Error al procesar credenciales: {str(e)[:100]}...")
            st.error(f"Un error ocurrió con las credenciales: {e}.")

    if selected_tool == "1. Extractor de Datos de Nowgoal":
        if gsheets_sh_handle:
            display_nowgoal_scraper_ui(gsheets_sh_handle)
        else:
            st.warning("⚠️ La conexión a Google Sheets es necesaria y no se pudo establecer.")
            st.info("Asegúrate de que `gcp_service_account` esté configurado en los secretos.")

    elif selected_tool == "2. Otra Funcionalidad (Beta)":
        display_other_feature_ui()

    elif selected_tool == "3. Información General":
        st.header("ℹ️ Información General de la Aplicación")
        st.markdown("""
        ---
        ### 📚 Descripción
        Esta aplicación incluye un **Extractor de Datos de Nowgoal** y espacio para futuras herramientas.

        ### 🔐 Configuración de Credenciales (Google Sheets)
        Para el Extractor de Datos, configura los secretos en Streamlit Cloud bajo la clave `gcp_service_account` con el formato TOML de tus credenciales de servicio de Google.
        La `private_key` debe incluir los `\\n` tal como están en tu archivo JSON.
        ---
        """)

if __name__ == "__main__":
    main()
