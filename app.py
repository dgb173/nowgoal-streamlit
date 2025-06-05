import streamlit as st
from modules.datos import display_other_feature_ui
from modules.match_stats_extractor import display_match_stats_extractor_ui # <--- ¡NUEVA IMPORTACIÓN AQUÍ!


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
        (
            "1. Extractor de Datos de Nowgoal",
            "2. Otra Funcionalidad (Beta)",
            "3. Scrapear datos",
            "4. Extractor de Estadísticas de Partido" # <--- ¡NUEVA OPCIÓN EN EL MENÚ!
        ),
        key="main_tool_selection_final"
    )

    gsheets_sh_handle = None

    # Lógica de conexión a Google Sheets (solo si se selecciona la primera opción)
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
                st.sidebar.error("❗️ `gcp_service_account` NO encontrado en `st.secrets`.")
                st.error("Error de Configuración: Faltan las credenciales de Google Sheets.")

        except Exception as e:
            st.sidebar.error(f"🆘 Error al procesar credenciales: {str(e)[:100]}...")
            st.error(f"Un error ocurrió con las credenciales: {e}.")

    # Mostrar la interfaz de usuario según la herramienta seleccionada
    if selected_tool == "1. Extractor de Datos de Nowgoal":
        display_other_feature_ui()
    
    elif selected_tool == "2. Datosm LIVE":
        display_match_stats_extractor_ui()



if __name__ == "__main__":
    main()
