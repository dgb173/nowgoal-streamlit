import streamlit as st
from modules.nowgoal_scraper import display_nowgoal_scraper_ui, get_gsheets_client_and_sheet
from modules.scrap import scrape_match_data
from modules.other_feature_NUEVO import display_other_feature_ui

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
        ("1. Extractor de Datos de Nowgoal", "2. Otra Funcionalidad (Beta)", "3. Scrapear datos"), # <--- CAMBIO AQUÍ
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
                st.sidebar.error("❗️ `gcp_service_account` NO encontrado en `st.secrets`.")
                st.error("Error de Configuración: Faltan las credenciales de Google Sheets.")

        except Exception as e:
            st.sidebar.error(f"🆘 Error al procesar credenciales: {str(e)[:100]}...")
            st.error(f"Un error ocurrió con las credenciales: {e}.")

    # Este bloque if/elif/else debe estar al mismo nivel de indentación que el try/except anterior
    if selected_tool == "1. Extractor de Datos de Nowgoal":
        if gsheets_sh_handle:
            display_nowgoal_scraper_ui(gsheets_sh_handle)
        else:
            st.warning("⚠️ La conexión a Google Sheets es necesaria para esta herramienta y no se pudo establecer.")
            st.info("Asegúrate de que `gcp_service_account` esté configurado correctamente en los secretos de Streamlit.")

    elif selected_tool == "2. Otra Funcionalidad (Beta)":
        display_other_feature_ui()
    # CORRECCIÓN DE INDENTACIÓN y ahora coincide con el radio button
    elif selected_tool == "3. Scrapear datos": # <--- Debe coincidir exactamente con la opción del radio
        scrap()
    # Si tuvieras una opción "3. Información General", necesitarías un elif para ella también.
    # Por ejemplo, si decides añadirla como cuarta opción y quieres que haga algo:
    # elif selected_tool == "4. Información General":
    # st.info("Aquí iría la información general.")


if __name__ == "__main__":
    main()
