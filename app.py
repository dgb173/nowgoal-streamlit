# Fichero: app.py (CORREGIDO Y ACTUALIZADO)

import streamlit as st
from modules.datos import display_other_feature_ui
from modules.estudio import display_other_feature_ui2

from modules.kimi_chat import display_kimi_chat_ui
from modules.extractorids import display_scraper_ui  # <--- 1. IMPORTA LA NUEVA FUNCIÓN

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
    
    tool_options = (
        "Local Y Visitante",
        "Ids Proximos Partidos",
        "Chat con Kimi K2",
        "Entreno"
    )
    
    selected_tool = st.sidebar.radio(
        "Selecciona una herramienta:",
        tool_options,
        key="main_tool_selection" 
    )

    # Ahora las condiciones coincidirán perfectamente con las opciones
    if selected_tool == "Local Y Visitante":
        display_other_feature_ui()
    
    # 2. AÑADE ESTE BLOQUE ELIF PARA LA NUEVA HERRAMIENTA
    elif selected_tool == "Ids Proximos Partidos":
        display_scraper_ui() # Llama a la función de la interfaz del scraper
        
    elif selected_tool == "Chat con Kimi K2":
        display_kimi_chat_ui()
    elif selected_tool == "Entreno":
        display_other_feature_ui2()

if __name__ == "__main__":
    main()
