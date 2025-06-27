# modules/minimal_viz.py
import streamlit as st
import requests

from modules.datos import (
    fetch_soup_requests_of,
    get_team_league_info_from_script_of,
    extract_final_score_of,
    format_ah_as_decimal_string_of,
)

try:
    from modules.datos import get_selenium_driver_of, get_main_match_odds_selenium_of
except Exception:
    get_selenium_driver_of = None
    get_main_match_odds_selenium_of = None

API_URL = "https://api-inference.huggingface.co/models/google/flan-t5-base"


def fetch_ai_prediction(prompt: str) -> str:
    """Attempt to fetch a simple AI prediction using the HuggingFace inference API."""
    try:
        response = requests.post(API_URL, json={"inputs": prompt}, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list) and data:
                return data[0].get("generated_text", "")
            elif isinstance(data, dict) and "generated_text" in data:
                return data["generated_text"]
        return f"Error {response.status_code} al obtener prediccion"
    except Exception as e:
        return f"No se pudo obtener prediccion AI: {e}"


def display_minimal_page() -> None:
    st.markdown(
        """
        <style>
        .big-title {font-size:2.2em;font-weight:bold;text-align:center;margin-bottom:10px;}
        .data-box {border:1px solid #ddd;border-radius:5px;padding:10px;margin-bottom:10px;background:#f9f9f9;}
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("<p class='big-title'>Vista Minimal de Partido</p>", unsafe_allow_html=True)
    match_id = st.text_input("ID del partido", value="2696131")
    if st.button("Analizar", type="primary"):
        soup = fetch_soup_requests_of(f"/match/h2h-{match_id}")
        if not soup:
            st.error("No se pudo obtener datos del partido")
            return
        home_id, away_id, league_id, home_name, away_name, league_name = get_team_league_info_from_script_of(soup)
        score_display, score_raw = extract_final_score_of(soup)
        st.markdown(f"### {home_name} vs {away_name}")
        st.markdown(f"**Liga:** {league_name} (ID {league_id})")
        st.metric("Marcador Final", score_display)
        odds_data = {}
        if get_selenium_driver_of and get_main_match_odds_selenium_of:
            driver = get_selenium_driver_of()
            if driver:
                try:
                    driver.get(f"https://live18.nowgoal25.com/match/live-{match_id}")
                    odds_data = get_main_match_odds_selenium_of(driver)
                finally:
                    driver.quit()
        ah_line = format_ah_as_decimal_string_of(odds_data.get("ah_linea_raw", "?"))
        goals_line = format_ah_as_decimal_string_of(odds_data.get("goals_linea_raw", "?"))
        st.metric("AH inicial", ah_line)
        st.metric("Línea de Goles", goals_line)
        prompt = (
            f"Analiza el encuentro entre {home_name} y {away_name}. El marcador final fue {score_display}. "
            f"La línea AH fue {ah_line} y la línea de goles {goals_line}. "
            "¿Cuál sería el resultado más lógico si se volvieran a enfrentar?"
        )
        with st.spinner("Consultando IA gratuita..."):
            ai_answer = fetch_ai_prediction(prompt)
        st.subheader("Predicción de IA")
        st.write(ai_answer)

if __name__ == "__main__":
    st.set_page_config(layout="wide", page_title="Vista Minimal", initial_sidebar_state="expanded")
    display_minimal_page()
