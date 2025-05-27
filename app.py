# app.py (o como lo llames)
import streamlit as st
from modules.nowgoal_scraper import display_nowgoal_scraper_ui, get_gsheets_client_and_sheet
from modules.scrap import scrap # Asumiendo que tienes este archivo y función
from modules.other_feature_NUEVO import display_other_feature_ui # Cambia esta línea

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
        ("1. Extractor de Datos de Nowgoal", "2. Otra Funcionalidad (Beta)", "3. Información General"),
        key="main_tool_selection_final" # Usando una de las claves que tenías
    )

    gsheets_sh_handle = None # Inicializamos fuera del bloque try

    if selected_tool == "1. Extractor de Datos de Nowgoal":
        try:
            if "gcp_service_account" in st.secrets:
                gsheets_credentials = st.secrets["gcp_service_account"]
                with st.spinner("⚙️ Estableciendo conexión con Google Sheets..."):
                    # Asumo que get_gsheets_client_and_sheet devuelve (client, sheet_handle)
                    # y solo necesitas el sheet_handle aquí.
                    # También asumo que toma las credenciales como argumento.
                    _, gsheets_sh_handle_temp = get_gsheets_client_and_sheet(gsheets_credentials)

                if not gsheets_sh_handle_temp: # Si la conexión falló
                    st.sidebar.error("❌ Error conectando a GSheets. Verifica secretos y conexión.")
                    st.error("No se pudo conectar a Google Sheets. El extractor no funcionará.")
                    # gsheets_sh_handle permanece como None
                else:
                    st.sidebar.success("🔗 Conexión a Google Sheets establecida.")
                    gsheets_sh_handle = gsheets_sh_handle_temp
            else:
                st.sidebar.error("❗️ `gcp_service_account` NO encontrado en `st.secrets`.")
                st.error("Error de Configuración: Faltan las credenciales de Google Sheets.")
                # gsheets_sh_handle permanece como None

        except Exception as e:
            st.sidebar.error(f"🆘 Error al procesar credenciales: {str(e)[:100]}...")
            st.error(f"Un error ocurrió con las credenciales: {e}.")
            # gsheets_sh_handle permanece como None

    # Este bloque if/elif/else debe estar al mismo nivel de indentación que el try/except anterior
    if selected_tool == "1. Extractor de Datos de Nowgoal":
        if gsheets_sh_handle:
            display_nowgoal_scraper_ui(gsheets_sh_handle)
        else:
            # El mensaje de error ya se mostró arriba, pero podemos añadir una advertencia general.
            st.warning("⚠️ La conexión a Google Sheets es necesaria para esta herramienta y no se pudo establecer.")
            st.info("Asegúrate de que `gcp_service_account` esté configurado correctamente en los secretos de Streamlit.")

    elif selected_tool == "2. Otra Funcionalidad (Beta)":
        display_other_feature_ui()
         elif selected_tool == "3.Scrapear datos":
        scrap()

    

if __name__ == "__main__":
    main()
