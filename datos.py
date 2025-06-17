import streamlit as st
from modules import datos as datos_module


def run_analyzer_app():
    st.set_page_config(layout="wide", page_title="Análisis de Partido")

    match_id_from_url = st.query_params.get("match_id")
    if match_id_from_url:
        st.session_state.auto_match_id = match_id_from_url
    datos_module.display_other_feature_ui()
    if not match_id_from_url:
        st.info("⬅️ Por favor, selecciona un partido desde el 'Panel de Control' para comenzar el análisis.")


if __name__ == '__main__':
    if 'driver_other_feature' not in st.session_state:
        st.session_state.driver_other_feature = None
    run_analyzer_app()
