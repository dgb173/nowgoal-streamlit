import streamlit as st
from modules.prediction_ui import display_prediction_ui
from modules.training_ui import display_training_ui

def main():
    st.set_page_config(
        page_title="AH ML Pipeline",
        page_icon="⚽",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    st.sidebar.title("⚽ AH ML Pipeline")
    st.sidebar.markdown("---")
    st.sidebar.header("🛠️ Herramientas")
    
    tool_options = (
        "Predecir",
        "Entrenar"
    )
    
    selected_tool = st.sidebar.radio(
        "Selecciona una herramienta:",
        tool_options,
        key="main_tool_selection" 
    )

    st.sidebar.markdown("---")
    st.sidebar.info("Esta aplicación utiliza un modelo de Machine Learning para predecir resultados de Hándicap Asiático basado en datos históricos y reglas de negocio.")

    if selected_tool == "Predecir":
        display_prediction_ui()
    elif selected_tool == "Entrenar":
        display_training_ui()

if __name__ == "__main__":
    main()
