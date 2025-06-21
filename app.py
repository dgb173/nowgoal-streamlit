import streamlit as st
from modules.datos import display_other_feature_ui


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
            "2. Extractor de Estadísticas de Partido" # <--- ¡NUEVA OPCIÓN EN EL MENÚ!
        ),
        key="main_tool_selection_final"
    )


    # Mostrar la interfaz de usuario según la herramienta seleccionada
    if selected_tool == "1. Extractor de Datos de Nowgoal":
         display_other_feature_ui()
    elif selected_tool == "2. Extractor de Estadísticas de Partido":
        display_match_stats_extractor_ui()
    




if __name__ == "__main__":
    main()
