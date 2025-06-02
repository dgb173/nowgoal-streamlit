# This file will be the main entry point for the Streamlit application.
import streamlit as st

# Page configuration should ideally be the first Streamlit command
st.set_page_config(layout="wide", page_title="Análisis Avanzado de Partidos (OF)", initial_sidebar_state="expanded")

if __name__ == '__main__':
    # Import the UI function
    from .ui import display_other_feature_ui
    
    # Initialize session state for the driver if not already present
    # This is important if the UI relies on it being there.
    if 'driver_other_feature' not in st.session_state:
        st.session_state.driver_other_feature = None
        
    display_other_feature_ui()
