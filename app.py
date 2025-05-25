# app**
*(Este archivo debería estar correcto, pero lo incluyo por completitud)*

```python
# app.py.py
import streamlit as st
from modules.nowgoal_scraper import display_nowgoal_scraper_ui, get_gsheets_client_and_sheet
from modules.other_feature import display_other_feature_ui (Archivo principal de Streamlit)
import streamlit as st
# Importar las funciones de UI de los módulos
from modules.nowgoal_scraper import display_nowgoal_scraper_ui, get_gsheets_client_and

def main():
    st.set_page_config(
        page_title="Nowgoal Data Sc_sheet
from modules.other_feature import display_other_feature_ui # Asumiendo que tienes esteraper & Tools",
        page_icon="⚽",
        layout="wide",
        initial_sidebar_ archivo

def main():
    st.set_page_config(
        page_title="Nowgoal Data Scraperstate="expanded"
    )

    st.title("⚽📊 App de Análisis de Datos y Herramientas & Tools",
        page_icon="⚽",
        layout="wide",
        initial_sidebar_state 📊⚽")
    st.markdown("Bienvenido. Usa el menú lateral para navegar.")

    st.sidebar.header="expanded"
    )

    st.title("⚽📊 App de Análisis de Datos y Herramientas ("🛠️ Herramientas")
    selected_tool = st.sidebar.radio(
        "Selecciona una herramienta:",📊⚽")
    st.markdown("""
    Bienvenido a la aplicación central. Usa el menú lateral para navegar entre las diferentes herramientas disponibles.
    """)

    st.sidebar.header("🛠️ Herramientas Disponibles")

        ("1. Extractor de Datos de Nowgoal", "2. Otra Funcionalidad (Beta)", "3. Información General"),
        key="main_tool_selection_final"
    )

    gsheets_sh_handle = None    selected_tool = st.sidebar.radio(
        "Selecciona una herramienta:",
        ("1. Extractor de Datos de Nowgoal", "2. Otra Funcionalidad (Beta)", "3. Información General"),
        key="main_tool_selection"
    )

    gsheets_credentials = None
    gs
    if selected_tool == "1. Extractor de Datos de Nowgoal":
        try:
            if "gcp_service_account" in st.secrets:
                gsheets_credentials = st.secrets["gcp_service_account"]
                with st.spinner("⚙️ Conectando a Google Sheets..."):
                    gc_client, gsheets_sh_handle_temp = get_gsheets_client_and_sheet(gsheets_sh_handle = None

    if selected_tool == "1. Extractor de Datos de Nowgoal":
        try:
            if "gcp_service_account" in st.secrets:
                gsheets_credentials = st.secrets["gcp_service_account"]
                with st.spinner("⚙️ Estableciendo conexión con Google Sheets..."):
                    gc_client, gsheets_sh_handle_temp = get_gsheets_client_and_sheet(gsheets_credentials)

                if not gsheets_sh_handle_tempheets_credentials)
                if gsheets_sh_handle_temp:
                    st.sidebar.success("🔗 Conexión a GSheets OK.")
                    gsheets_sh_handle = gsheets_sh_handle_temp
                else:
                    st.sidebar.error("❌ Error conectando a GSheets.")
                    st.error("No se pudo conectar a Google Sheets.")
            else:
                st.sidebar.error("❗️ `gcp_service_account` no encontrado en secretos.")
                st.error("Credenciales de Google Sheets no configuradas.")
        except Exception as:
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
            st.error(f e:
            st.sidebar.error(f"🆘 Error credenciales: {str(e)[:50]}...")
            st.error(f"Error con credenciales: {e}.")

    if selected_tool == "1. Extractor de Datos de Nowgoal":
        if gsheets_sh_handle:
            display_nowgoal_scraper_ui(gsheets_sh_handle) # gsheet_sh_handle puede no ser usado por esta UI específica
        else:
            st.warning("⚠️ Conexión a Google Sheets fallida o no configurada.")
    elif selected_tool == "2. Otra Funcionalidad (Beta)":
        display_other_feature_ui()
    elif selected_tool == "3. Información General":
        st."Un error ocurrió con las credenciales: {e}.")

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
        La `private_key` debe incluir los `\\n` tal como están en tu archivoheader("ℹ️ Información General"); st.markdown("Extractor de Datos de Nowgoal y más...")

if __name__ == "__main__":
    main()
