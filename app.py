# Fichero: main.py

import streamlit as st
from modules.datos import display_other_feature_ui
from modules.sheets_uploader import display_sheets_uploader_ui
# ¡Importamos el nuevo módulo y su función de UI!
from modules.handicap_analyzer import display_handicap_analyzer_ui


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
            # Hemos renombrado esta herramienta y añadido la nuestra
            "2. Analizador de Hándicap Asiático",
            "3. Carga de Rangos a Google Sheets"
        ),
        # Cambiamos la key para evitar conflictos si el usuario tenía algo guardado en caché
        key="main_tool_selection" 
    )


    # Mostrar la interfaz de usuario según la herramienta seleccionada
    if selected_tool == "1. Extractor de Datos de Nowgoal":
         display_other_feature_ui()
    elif selected_tool == "2. Analizador de Hándicap Asiático":
        # Llamamos a la función de la UI del nuevo módulo
        display_handicap_analyzer_ui()
    elif selected_tool == "3. Carga de Rangos a Google Sheets":
        display_sheets_uploader_ui()
    




if __name__ == "__main__":
    main()
