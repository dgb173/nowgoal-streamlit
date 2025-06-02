import streamlit as st
import time
# import re # Flake8 reported as unused

# Imports from our refactored modules
from .utils import format_ah_as_decimal_string_of # parse_ah_to_number_of is used by format_ah_as_decimal_string_of internally
from .data_fetcher import (
    fetch_soup_requests_of, 
    get_team_league_info_from_script_of,
    extract_standings_data_from_h2h_page_of, 
    get_rival_a_for_original_h2h_of,
    get_rival_b_for_original_h2h_of, 
    extract_final_score_of, 
    extract_h2h_data_of,
    extract_comparative_match_of,
    # BASE_URL_OF # Not directly used in UI, but by data_fetcher functions
)
from .selenium_manager import (
    get_selenium_driver_of, 
    get_h2h_details_for_original_logic_of,
    extract_last_match_in_league_of, 
    get_main_match_odds_selenium_of,
    prepare_h2h_page_for_scraping # New function for page loading
    # SELENIUM_TIMEOUT_SECONDS_OF, # Not directly used in UI
    # SELENIUM_POLL_FREQUENCY_OF # Not directly used in UI
)
# Selenium specific imports no longer needed directly in UI:
# from selenium.webdriver.common.by import By
# from selenium.webdriver.support.ui import WebDriverWait
# from selenium.webdriver.support import expected_conditions as EC
# from selenium.common.exceptions import WebDriverException


# --- Caching Strategy ---
# Cache data fetching functions
cached_fetch_soup_requests_of = st.cache_data(ttl=3600)(fetch_soup_requests_of)
# cached_get_team_league_info_from_script_of removed, will use direct call
cached_extract_standings_data_from_h2h_page_of = st.cache_data(ttl=3600)(extract_standings_data_from_h2h_page_of)
cached_get_rival_a_for_original_h2h_of = st.cache_data(ttl=3600)(get_rival_a_for_original_h2h_of)
cached_get_rival_b_for_original_h2h_of = st.cache_data(ttl=3600)(get_rival_b_for_original_h2h_of)
cached_extract_final_score_of = st.cache_data(ttl=3600)(extract_final_score_of)
cached_extract_h2h_data_of = st.cache_data(ttl=3600)(extract_h2h_data_of)
cached_extract_comparative_match_of = st.cache_data(ttl=3600)(extract_comparative_match_of)

# Cache Selenium driver instance
cached_get_selenium_driver_of = st.cache_resource(get_selenium_driver_of)

# Cache Selenium functions that make their own requests or long operations if possible
# For get_h2h_details_for_original_logic_of, extract_last_match_in_league_of, get_main_match_odds_selenium_of
# These take a driver, so direct st.cache_data might be tricky if the driver object isn't hashable or changes.
# For now, we will call them with the cached driver. If performance issues arise, further caching strategies for these can be explored.
# Let's assume for now that the primary slowness is driver init and page loads, not these actions themselves if the page is already loaded.

# --- UI Helper Functions (Initial Breakdown) ---

def _render_sidebar_and_get_input():
    st.sidebar.image("https://raw.githubusercontent.com/streamlit/docs/main/public/images/brand/streamlit-logo-secondary-colormark-darktext.svg", width=200)
    st.sidebar.title("⚙️ Configuración del Partido (OF)")
    main_match_id_str_input = st.sidebar.text_input(
        "🆔 ID Partido Principal:", 
        value="2696131", 
        help="Pega el ID numérico del partido que deseas analizar.", 
        key="other_feature_match_id_input" # Keep key for now, can be refactored later
    )
    analizar_button = st.sidebar.button("🚀 Analizar Partido (OF)", type="primary", use_container_width=True, key="other_feature_analizar_button")
    return main_match_id_str_input, analizar_button

def _render_header_and_team_info(main_match_id, home_name, away_name, league_name, league_id, placeholder):
    st.markdown(f"<p class='main-title'>📊 Análisis Avanzado de Partido (OF) ⚽</p>", unsafe_allow_html=True)
    st.markdown(f"<p class='sub-title'>🆚 <span class='home-color'>{home_name or 'Equipo Local'}</span> vs <span class='away-color'>{away_name or 'Equipo Visitante'}</span></p>", unsafe_allow_html=True)
    st.caption(f"🏆 **Liga:** {league_name or placeholder} (ID Liga: {league_id or placeholder}) | 🆔 **Partido ID:** <span class='data-highlight'>{main_match_id}</span>", unsafe_allow_html=True)
    st.markdown("---")

# --- STREAMLIT APP UI (Función principal, moved and refactored) ---
def display_other_feature_ui():
    
    # --- INJECT CUSTOM CSS ---
    st.markdown("""
        <style>
            /* General body and font */
            body {
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol";
            }
            .stApp {
                /* background-color: #f0f2f6; */ /* Light grey background for the whole app */
            }

            /* Card style for grouping information */
            .card {
                background-color: #ffffff;
                border: 1px solid #e1e4e8; /* Softer border */
                border-radius: 8px; /* Rounded corners */
                padding: 20px;
                margin-bottom: 20px;
                box-shadow: 0 4px 8px rgba(0,0,0,0.05); /* Subtle shadow */
            }
            .card-title {
                font-size: 1.3em; /* Larger title */
                font-weight: 600; /* Semi-bold */
                color: #0a58ca; /* Primary blue */
                margin-bottom: 15px;
                border-bottom: 2px solid #0a58ca20; /* Light underline for title */
                padding-bottom: 10px;
            }
            .card-subtitle {
                font-size: 1em;
                font-weight: 500;
                color: #333;
                margin-top: 10px;
                margin-bottom: 5px;
            }

            /* Metric improvements */
            div[data-testid="stMetric"] {
                background-color: #f8f9fa; /* Light background for metric */
                border: 1px solid #dee2e6;
                border-radius: 6px;
                padding: 15px;
                text-align: center; /* Center metric content */
            }
            div[data-testid="stMetric"] label { /* Metric label */
                font-size: 0.95em;
                color: #495057; /* Darker grey for label */
                font-weight: 500;
            }
            div[data-testid="stMetric"] div.st-ae { /* Metric value container - might need adjustment based on Streamlit version */
                font-size: 1.6em;
                font-weight: bold;
                color: #212529; /* Dark color for value */
            }
            
            /* Custom styled spans for data points */
            .home-color { color: #007bff; font-weight: bold; } /* Blue for home */
            .away-color { color: #fd7e14; font-weight: bold; } /* Orange for away */
            .ah-value { 
                background-color: #e6f3ff; 
                color: #007bff; 
                padding: 3px 8px; 
                border-radius: 15px; /* Pill shape */
                font-weight: bold; 
                border: 1px solid #007bff30;
            }
            .goals-value { 
                background-color: #ffebe6; 
                color: #dc3545; 
                padding: 3px 8px; 
                border-radius: 15px; /* Pill shape */
                font-weight: bold; 
                border: 1px solid #dc354530;
            }
            .score-value {
                font-weight: bold;
                font-size: 1.1em;
                color: #28a745; /* Green for scores */
            }
            .data-highlight { /* General highlight for data snippets */
                font-family: 'Courier New', Courier, monospace;
                background-color: #e9ecef;
                padding: 2px 5px;
                border-radius: 4px;
                font-size: 0.95em;
            }
            
            /* Expander header styling */
            .st-emotion-cache-10trblm .st-emotion-cache-l9icx6 { /* Target expander header, might change with Streamlit versions */
                font-size: 1.15em !important;
                font-weight: 600 !important;
                color: #0056b3 !important; 
            }
            
            /* Main page title */
            .main-title {
                text-align: center;
                color: #343a40;
                font-size: 2.5em;
                font-weight: bold;
                margin-bottom: 10px;
                padding-bottom: 10px;
            }
            .sub-title {
                text-align: center;
                color: #007bff;
                font-size: 1.8em;
                font-weight: bold;
                margin-bottom: 15px;
            }
            .section-header {
                font-size: 1.7em;
                font-weight: 600;
                color: #17a2b8; /* Teal color for section headers */
                margin-top: 25px;
                margin-bottom: 15px;
                border-bottom: 2px solid #17a2b830;
                padding-bottom: 8px;
            }
        </style>
    """, unsafe_allow_html=True)

    main_match_id_str_input_of, analizar_button_of = _render_sidebar_and_get_input()

    results_container = st.container()
    placeholder_nodata = "*(No disponible)*"

    if 'driver_other_feature' not in st.session_state: 
        st.session_state.driver_other_feature = None

    if analizar_button_of:
        results_container.empty()
        main_match_id_to_process_of = None
        if main_match_id_str_input_of:
            try:
                cleaned_id_str = "".join(filter(str.isdigit, main_match_id_str_input_of))
                if cleaned_id_str: main_match_id_to_process_of = int(cleaned_id_str)
            except ValueError: 
                results_container.error("⚠️ El ID de partido ingresado no es válido. Debe ser numérico (OF)."); st.stop()
        if not main_match_id_to_process_of: 
            results_container.warning("⚠️ Por favor, ingresa un ID de partido válido para analizar (OF)."); st.stop()
        
        start_time_of = time.time()
        with results_container:
            with st.spinner("🔄 Cargando datos iniciales del partido..."):
                main_page_url_h2h_view_of = f"/match/h2h-{main_match_id_to_process_of}"
                soup_main_h2h_page_of = cached_fetch_soup_requests_of(main_page_url_h2h_view_of)
            
            if not soup_main_h2h_page_of:
                st.error(f"❌ No se pudo obtener la página H2H principal para el ID {main_match_id_to_process_of}. Verifica la conexión o el ID."); st.stop()

            # Call the original function directly, not the cached version
            mp_home_id_of, mp_away_id_of, mp_league_id_of, mp_home_name_from_script, mp_away_name_from_script, mp_league_name_of = get_team_league_info_from_script_of(soup_main_h2h_page_of)
            
            with st.spinner("📊 Extrayendo clasificaciones principales de los equipos..."):
                home_team_main_standings = cached_extract_standings_data_from_h2h_page_of(soup_main_h2h_page_of, mp_home_name_from_script)
                away_team_main_standings = cached_extract_standings_data_from_h2h_page_of(soup_main_h2h_page_of, mp_away_name_from_script)
            
            display_home_name = home_team_main_standings.get("name", mp_home_name_from_script) if home_team_main_standings.get("name", "N/A") != "N/A" else mp_home_name_from_script
            display_away_name = away_team_main_standings.get("name", mp_away_name_from_script) if away_team_main_standings.get("name", "N/A") != "N/A" else mp_away_name_from_script

            _render_header_and_team_info(main_match_id_to_process_of, display_home_name, display_away_name, mp_league_name_of, mp_league_id_of, placeholder_nodata)
            
            st.markdown("<h2 class='section-header'>📈 Clasificación General y Específica</h2>", unsafe_allow_html=True)
            # Further breakdown for this section can be done (e.g., _render_main_standings_section)
            col_home_stand, col_away_stand = st.columns(2)
            with col_home_stand:
                st.markdown(f"<h3 class='card-title'>🏠 {display_home_name or 'Equipo Local'}</h3>", unsafe_allow_html=True)
                if display_home_name and display_home_name != "N/A" and home_team_main_standings.get("name", "N/A") != "N/A":
                    hst = home_team_main_standings
                    st.markdown(f"**🏅 Ranking General:** <span class='data-highlight'>{hst.get('ranking', placeholder_nodata)}</span>", unsafe_allow_html=True)
                    st.markdown(f"**🌍 Total Liga:** <span class='data-highlight'>{hst.get('total_pj', '0')}</span> PJ | <span class='data-highlight'>{hst.get('total_v', '0')}V-{hst.get('total_e', '0')}E-{hst.get('total_d', '0')}D</span> | GF: <span class='data-highlight'>{hst.get('total_gf', '0')}</span>, GC: <span class='data-highlight'>{hst.get('total_gc', '0')}</span>", unsafe_allow_html=True)
                    st.caption("PJ: Partidos Jugados, V: Victorias, E: Empates, D: Derrotas, GF: Goles a Favor, GC: Goles en Contra (Total en la liga).")
                    st.markdown(f"**🏠 {hst.get('specific_type','Como Local')}:** <span class='data-highlight'>{hst.get('specific_pj', '0')}</span> PJ | <span class='data-highlight'>{hst.get('specific_v', '0')}V-{hst.get('specific_e', '0')}E-{hst.get('specific_d', '0')}D</span> | GF: <span class='data-highlight'>{hst.get('specific_gf', '0')}</span>, GC: <span class='data-highlight'>{hst.get('specific_gc', '0')}</span>", unsafe_allow_html=True)
                    st.caption(f"Estadísticas específicas del equipo jugando como {hst.get('specific_type','Local').lower()}.")
                else: st.info(f"Clasificación no disponible para {display_home_name or 'Equipo Local'}.")
                st.markdown("</div>", unsafe_allow_html=True) # End card
            with col_away_stand:
                st.markdown(f"<h3 class='card-title'>✈️ {display_away_name or 'Equipo Visitante'}</h3>", unsafe_allow_html=True)
                if display_away_name and display_away_name != "N/A" and away_team_main_standings.get("name", "N/A") != "N/A":
                    ast = away_team_main_standings
                    st.markdown(f"**🏅 Ranking General:** <span class='data-highlight'>{ast.get('ranking', placeholder_nodata)}</span>", unsafe_allow_html=True)
                    st.markdown(f"**🌍 Total Liga:** <span class='data-highlight'>{ast.get('total_pj', '0')}</span> PJ | <span class='data-highlight'>{ast.get('total_v', '0')}V-{ast.get('total_e', '0')}E-{ast.get('total_d', '0')}D</span> | GF: <span class='data-highlight'>{ast.get('total_gf', '0')}</span>, GC: <span class='data-highlight'>{ast.get('total_gc', '0')}</span>", unsafe_allow_html=True)
                    st.caption("PJ: Partidos Jugados, V: Victorias, E: Empates, D: Derrotas, GF: Goles a Favor, GC: Goles en Contra (Total en la liga).")
                    st.markdown(f"**✈️ {ast.get('specific_type','Como Visitante')}:** <span class='data-highlight'>{ast.get('specific_pj', '0')}</span> PJ | <span class='data-highlight'>{ast.get('specific_v', '0')}V-{ast.get('specific_e', '0')}E-{ast.get('specific_d', '0')}D</span> | GF: <span class='data-highlight'>{ast.get('specific_gf', '0')}</span>, GC: <span class='data-highlight'>{ast.get('specific_gc', '0')}</span>", unsafe_allow_html=True)
                    st.caption(f"Estadísticas específicas del equipo jugando como {ast.get('specific_type','Visitante').lower()}.")
                else: st.info(f"Clasificación no disponible para {display_away_name or 'Equipo Visitante'}.")
                st.markdown("</div>", unsafe_allow_html=True) # End card
            
            key_match_id_for_rival_a_h2h, rival_a_id_orig_col3, rival_a_name_orig_col3 = cached_get_rival_a_for_original_h2h_of(main_match_id_to_process_of)
            match_id_rival_b_game_ref, rival_b_id_orig_col3, rival_b_name_orig_col3 = cached_get_rival_b_for_original_h2h_of(main_match_id_to_process_of)
            rival_a_standings = {}; rival_b_standings = {}

            with st.spinner("📊 Extrayendo clasificaciones de oponentes indirectos (Col3)..."):
                if rival_a_name_orig_col3 and rival_a_name_orig_col3 != "N/A" and key_match_id_for_rival_a_h2h:
                    soup_rival_a_h2h_page = cached_fetch_soup_requests_of(f"/match/h2h-{key_match_id_for_rival_a_h2h}")
                    if soup_rival_a_h2h_page: rival_a_standings = cached_extract_standings_data_from_h2h_page_of(soup_rival_a_h2h_page, rival_a_name_orig_col3)
                if rival_b_name_orig_col3 and rival_b_name_orig_col3 != "N/A" and match_id_rival_b_game_ref:
                    soup_rival_b_h2h_page = cached_fetch_soup_requests_of(f"/match/h2h-{match_id_rival_b_game_ref}")
                    if soup_rival_b_h2h_page: rival_b_standings = cached_extract_standings_data_from_h2h_page_of(soup_rival_b_h2h_page, rival_b_name_orig_col3)
            
            main_match_odds_data_of = {}; last_home_match_in_league_of = None; last_away_match_in_league_of = None
            
            driver_actual_of = st.session_state.driver_other_feature
            driver_of_needs_init = driver_actual_of is None
            if not driver_of_needs_init:
                try:
                    _ = driver_actual_of.window_handles # Check if driver is still alive
                    if hasattr(driver_actual_of, 'service') and driver_actual_of.service and not driver_actual_of.service.is_connectable():
                        driver_of_needs_init = True
                except Exception: # Broad exception for any driver issue (e.g. WebDriverException if imported)
                    driver_of_needs_init = True
            
            if driver_of_needs_init:
                if driver_actual_of is not None:
                    try:
                        driver_actual_of.quit()
                    except Exception: # Broad exception for quit issues
                        pass
                with st.spinner("🚘 Inicializando WebDriver para datos dinámicos (puede tardar)..."): 
                    driver_actual_of = cached_get_selenium_driver_of()
                st.session_state.driver_other_feature = driver_actual_of

            if driver_actual_of:
                page_prepared_successfully = False
                with st.spinner("⚙️ Accediendo a datos dinámicos con Selenium (cuotas, últimos partidos)..."):
                    # Use the new function from selenium_manager to load page and wait
                    page_prepared_successfully = prepare_h2h_page_for_scraping(driver_actual_of, main_page_url_h2h_view_of)
                
                if page_prepared_successfully:
                    main_match_odds_data_of = get_main_match_odds_selenium_of(driver_actual_of)
                    if mp_home_id_of and mp_league_id_of and display_home_name and display_home_name != "N/A":
                        last_home_match_in_league_of = extract_last_match_in_league_of(driver_actual_of, "table_v1", display_home_name, mp_league_id_of, "input#cb_sos1[value='1']", is_home_game_filter=True)
                    if mp_away_id_of and mp_league_id_of and display_away_name and display_away_name != "N/A":
                        last_away_match_in_league_of = extract_last_match_in_league_of(driver_actual_of, "table_v2", display_away_name, mp_league_id_of, "input#cb_sos2[value='2']", is_home_game_filter=False)
                else:
                    st.error("❗ Fallo al preparar la página para extracción de datos con Selenium. Algunos datos podrían faltar.")
            else: 
                st.warning("❗ WebDriver no disponible. No se podrán obtener cuotas iniciales ni últimos partidos filtrados por liga/localía.")

            col_data = { 
                "AH_H2H_V": "-", "AH_Act": "?", "Res_H2H_V": "?*?", "AH_L_H": "-", "Res_L_H": "?*?", 
                "AH_V_A": "-", "Res_V_A": "?*?", "AH_H2H_G": "-", "Res_H2H_G": "?*?", "L_vs_UV_A": "-", 
                "V_vs_UL_H": "-", "Stats_L": f"Estadísticas para {display_home_name or 'Local'}: N/A", 
                "Stats_V": f"Estadísticas para {display_away_name or 'Visitante'}: N/A", "Fin": "?*?", 
                "G_i": "?", "League": mp_league_name_of or placeholder_nodata, "match_id": str(main_match_id_to_process_of)
            }
            # Ensure main_match_odds_data_of is defined before accessing it
            raw_ah_act = main_match_odds_data_of.get('ah_linea_raw', '?') if main_match_odds_data_of else '?'
            col_data["AH_Act"] = format_ah_as_decimal_string_of(raw_ah_act)
            raw_g_i = main_match_odds_data_of.get('goals_linea_raw', '?') if main_match_odds_data_of else '?'
            col_data["G_i"] = format_ah_as_decimal_string_of(raw_g_i)
            
            if soup_main_h2h_page_of : # Ensure soup_main_h2h_page_of is not None
                 col_data["Fin"], _ = cached_extract_final_score_of(soup_main_h2h_page_of)
            
            if home_team_main_standings and home_team_main_standings.get("name", "N/A") != "N/A" and display_home_name != "N/A":
                hst = home_team_main_standings
                hst = home_team_main_standings
                col_data["Stats_L"] = (f"🏅Rk:{hst.get('ranking',placeholder_nodata)} | 🏠{hst.get('specific_type','En Casa')}\n"
                                       f"🌍Total: {hst.get('total_pj','0')}PJ | {hst.get('total_v','0')}V/{hst.get('total_e','0')}E/{hst.get('total_d','0')}D | {hst.get('total_gf','0')}GF-{hst.get('total_gc','0')}GC\n"
                                       f"🏠Local: {hst.get('specific_pj','0')}PJ | {hst.get('specific_v','0')}V/{hst.get('specific_e','0')}E/{hst.get('specific_d','0')}D | {hst.get('specific_gf','0')}GF-{hst.get('specific_gc','0')}GC")
            if away_team_main_standings and away_team_main_standings.get("name", "N/A") != "N/A" and display_away_name != "N/A":
                ast = away_team_main_standings
                col_data["Stats_V"] = (f"🏅Rk:{ast.get('ranking',placeholder_nodata)} | ✈️{ast.get('specific_type','Fuera')}\n"
                                       f"🌍Total: {ast.get('total_pj','0')}PJ | {ast.get('total_v','0')}V/{ast.get('total_e','0')}E/{ast.get('total_d','0')}D | {ast.get('total_gf','0')}GF-{ast.get('total_gc','0')}GC\n"
                                       f"✈️Visitante: {ast.get('specific_pj','0')}PJ | {ast.get('specific_v','0')}V/{hst.get('specific_e','0')}E/{ast.get('specific_d','0')}D | {ast.get('specific_gf','0')}GF-{ast.get('specific_gc','0')}GC")
            if last_home_match_in_league_of:
                col_data["AH_L_H"] = format_ah_as_decimal_string_of(last_home_match_in_league_of.get('handicap_line_raw', '-'))
                col_data["Res_L_H"] = last_home_match_in_league_of.get('score', '?*?').replace('-', '*')
            if last_away_match_in_league_of:
                col_data["AH_V_A"] = format_ah_as_decimal_string_of(last_away_match_in_league_of.get('handicap_line_raw', '-'))
                col_data["Res_V_A"] = last_away_match_in_league_of.get('score', '?*?').replace('-', '*')
            
            if soup_main_h2h_page_of: # Ensure soup_main_h2h_page_of is not None for these calls
                ah1_val, res1_val, _, ah6_val, res6_val, _ = cached_extract_h2h_data_of(soup_main_h2h_page_of, display_home_name, display_away_name, mp_league_id_of)
                col_data["AH_H2H_V"] = ah1_val; col_data["Res_H2H_V"] = res1_val
                col_data["AH_H2H_G"] = ah6_val; col_data["Res_H2H_G"] = res6_val
            
                last_away_opponent_for_home_hist = last_away_match_in_league_of.get('home_team') if last_away_match_in_league_of and display_home_name else None
                if last_away_opponent_for_home_hist and display_home_name != "N/A":
                    col_data["L_vs_UV_A"] = cached_extract_comparative_match_of(soup_main_h2h_page_of, "table_v1", display_home_name, last_away_opponent_for_home_hist, mp_league_id_of, is_home_table=True)
            
                last_home_opponent_for_away_hist = last_home_match_in_league_of.get('away_team') if last_home_match_in_league_of and display_away_name else None
                if last_home_opponent_for_away_hist and display_away_name != "N/A":
                    col_data["V_vs_UL_H"] = cached_extract_comparative_match_of(soup_main_h2h_page_of, "table_v2", display_away_name, last_home_opponent_for_away_hist, mp_league_id_of, is_home_table=False)

            st.markdown("---")
            st.markdown("<h2 class='section-header'>🎯 Análisis Detallado del Partido</h2>", unsafe_allow_html=True)
            
            # Start of UI rendering sections - these will be further broken down
            with st.expander("⚖️ Cuotas Iniciales Bet365 y Marcador Final", expanded=False):
                st.markdown("<h4 class='card-subtitle'>Cuotas Iniciales (Bet365)</h4>", unsafe_allow_html=True)
                cuotas_col1, cuotas_col2 = st.columns(2)
                with cuotas_col1:
                    ah_line_fmt = format_ah_as_decimal_string_of(main_match_odds_data_of.get('ah_linea_raw','?'))
                    st.markdown(f"""
                        **H. Asiático (AH):** <span class='data-highlight'>{main_match_odds_data_of.get('ah_home_cuota',placeholder_nodata)}</span>
                        <span class='ah-value'>[{ah_line_fmt if ah_line_fmt != '?' else placeholder_nodata}]</span>
                        <span class='data-highlight'>{main_match_odds_data_of.get('ah_away_cuota',placeholder_nodata)}</span>
                    """, unsafe_allow_html=True)
                    st.caption("Cuota Local / Línea AH / Cuota Visitante.")
                with cuotas_col2:
                    goals_line_fmt = format_ah_as_decimal_string_of(main_match_odds_data_of.get('goals_linea_raw','?'))
                    st.markdown(f"""
                        **Línea Goles (O/U):** <span class='data-highlight'>Ov {main_match_odds_data_of.get('goals_over_cuota',placeholder_nodata)}</span>
                        <span class='goals-value'>[{goals_line_fmt if goals_line_fmt != '?' else placeholder_nodata}]</span>
                        <span class='data-highlight'>Un {main_match_odds_data_of.get('goals_under_cuota',placeholder_nodata)}</span>
                    """, unsafe_allow_html=True)
                    st.caption("Cuota Over / Línea Goles / Cuota Under.")
                
                st.markdown("<h4 class='card-subtitle' style='margin-top:15px;'>🏁 Marcador Final</h4>", unsafe_allow_html=True)
                final_score_display = col_data["Fin"].replace("*",":") if col_data["Fin"] != "?*?" else placeholder_nodata
                st.metric(label="Resultado Final del Partido", value=final_score_display, help="Marcador final del partido si ya ha concluido y está disponible.")
                st.markdown("</div>", unsafe_allow_html=True) # End card

            st.markdown("<h3 class='section-header' style='font-size:1.5em; margin-top:30px;'>⚡ Rendimiento Reciente y Contexto H2H (Indirecto)</h3>", unsafe_allow_html=True)
            rp_col1, rp_col2, rp_col3 = st.columns(3)
            with rp_col1:
                st.markdown(f"<h4 class='card-title'>Último <span class='home-color'>{display_home_name or 'Local'}</span> (Casa)</h4>", unsafe_allow_html=True)
                if last_home_match_in_league_of: 
                    res = last_home_match_in_league_of
                    st.markdown(f"🆚 <span class='away-color'>{res['away_team']}</span>", unsafe_allow_html=True)
                    st.markdown(f"<div style='margin-top: 8px; margin-bottom: 8px;'><span class='home-color'>{res['home_team']}</span> <span class='score-value'>{res['score'].replace('-',':')}</span> <span class='away-color'>{res['away_team']}</span></div>", unsafe_allow_html=True)
                    formatted_ah = format_ah_as_decimal_string_of(res.get('handicap_line_raw','-'))
                    st.markdown(f"**AH:** <span class='ah-value'>{formatted_ah if formatted_ah != '-' else placeholder_nodata}</span>", unsafe_allow_html=True)
                    st.caption(f"📅 {res['date']}")
                    st.caption("Último partido del equipo local jugado en casa en esta misma liga.")
                else: st.info(f"No se encontró último partido en casa para {display_home_name or 'Local'} en esta liga.")
                st.markdown("</div>", unsafe_allow_html=True) # End card
            with rp_col2:
                st.markdown(f"<h4 class='card-title'>Último <span class='away-color'>{display_away_name or 'Visitante'}</span> (Fuera)</h4>", unsafe_allow_html=True)
                if last_away_match_in_league_of: 
                    res = last_away_match_in_league_of
                    st.markdown(f"🆚 <span class='home-color'>{res['home_team']}</span>", unsafe_allow_html=True)
                    st.markdown(f"<div style='margin-top: 8px; margin-bottom: 8px;'><span class='home-color'>{res['home_team']}</span> <span class='score-value'>{res['score'].replace('-',':')}</span> <span class='away-color'>{res['away_team']}</span></div>", unsafe_allow_html=True)
                    formatted_ah = format_ah_as_decimal_string_of(res.get('handicap_line_raw','-'))
                    st.markdown(f"**AH:** <span class='ah-value'>{formatted_ah if formatted_ah != '-' else placeholder_nodata}</span>", unsafe_allow_html=True)
                    st.caption(f"📅 {res['date']}")
                    st.caption("Último partido del equipo visitante jugado fuera en esta misma liga.")
                else: st.info(f"No se encontró último partido fuera para {display_away_name or 'Visitante'} en esta liga.")
                st.markdown("</div>", unsafe_allow_html=True) # End card
            with rp_col3:
                st.markdown(f"<h4 class='card-title'>🆚 H2H Rivales (Col3)</h4>", unsafe_allow_html=True)
                rival_a_col3_name_display = rival_a_name_orig_col3 if rival_a_name_orig_col3 and rival_a_name_orig_col3 != "N/A" else (rival_a_id_orig_col3 or "Rival A")
                rival_b_col3_name_display = rival_b_name_orig_col3 if rival_b_name_orig_col3 and rival_b_name_orig_col3 != "N/A" else (rival_b_id_orig_col3 or "Rival B")
                details_h2h_col3_of = {"status": "error", "resultado": placeholder_nodata}
                if key_match_id_for_rival_a_h2h and rival_a_id_orig_col3 and rival_b_id_orig_col3 and driver_actual_of: 
                    with st.spinner(f"Buscando H2H: {rival_a_col3_name_display} vs {rival_b_col3_name_display}..."):
                        details_h2h_col3_of = get_h2h_details_for_original_logic_of(driver_actual_of, key_match_id_for_rival_a_h2h, rival_a_id_orig_col3, rival_b_id_orig_col3, rival_a_col3_name_display, rival_b_col3_name_display)
                
                if details_h2h_col3_of.get("status") == "found":
                    res_h2h = details_h2h_col3_of
                    h2h_home_name = res_h2h.get('h2h_home_team_name', 'Equipo Local H2H')
                    h2h_away_name = res_h2h.get('h2h_away_team_name', 'Equipo Visitante H2H')
                    st.markdown(f"<span class='home-color'>{h2h_home_name}</span> <span class='score-value'>{res_h2h.get('goles_home', '?')}:{res_h2h.get('goles_away', '?')}</span> <span class='away-color'>{h2h_away_name}</span>", unsafe_allow_html=True)
                    # The handicap is already formatted by get_h2h_details_for_original_logic_of
                    formatted_ah_h2h = res_h2h.get('handicap','-') 
                    st.markdown(f"**AH:** <span class='ah-value'>{formatted_ah_h2h if formatted_ah_h2h != '-' else placeholder_nodata}</span>", unsafe_allow_html=True)
                    st.caption(f"Enfrentamiento directo entre <span class='home-color'>{rival_a_col3_name_display}</span> y <span class='away-color'>{rival_b_col3_name_display}</span>.", unsafe_allow_html=True)
                else: st.info(details_h2h_col3_of.get('resultado', f"H2H entre {rival_a_col3_name_display} y {rival_b_col3_name_display} no encontrado."))
                st.markdown("</div>", unsafe_allow_html=True) # End card
            
            with st.expander("🔎 Clasificación Oponentes Indirectos (H2H Col3)", expanded=True):
                opp_stand_col1, opp_stand_col2 = st.columns(2)
                with opp_stand_col1:
                    name_a = rival_a_standings.get('name', rival_a_col3_name_display)
                    st.markdown(f"<h5 class='card-subtitle'><span class='home-color'>{name_a}</span></h5>", unsafe_allow_html=True)
                    if rival_a_standings.get("name", "N/A") != "N/A": 
                        rst = rival_a_standings
                        st.caption(f"🏅Rk: {rst.get('ranking',placeholder_nodata)} | 🌍T: {rst.get('total_pj','0')}PJ | {rst.get('total_v','0')}V/{rst.get('total_e','0')}E/{rst.get('total_d','0')}D | {rst.get('total_gf','0')}GF-{rst.get('total_gc','0')}GC")
                        st.caption(f"{rst.get('specific_type','Específico')}: {rst.get('specific_pj','0')}PJ | {rst.get('specific_v','0')}V/{rst.get('specific_e','0')}E/{rst.get('specific_d','0')}D | {rst.get('specific_gf','0')}GF-{rst.get('specific_gc','0')}GC")
                    else: st.caption(f"Clasificación no disponible para {name_a}.")
                with opp_stand_col2:
                    name_b = rival_b_standings.get('name', rival_b_col3_name_display)
                    st.markdown(f"<h5 class='card-subtitle'><span class='away-color'>{name_b}</span></h5>", unsafe_allow_html=True)
                    if rival_b_standings.get("name", "N/A") != "N/A": 
                        rst = rival_b_standings
                        st.caption(f"🏅Rk: {rst.get('ranking',placeholder_nodata)} | 🌍T: {rst.get('total_pj','0')}PJ | {rst.get('total_v','0')}V/{rst.get('total_e','0')}E/{rst.get('total_d','0')}D | {rst.get('total_gf','0')}GF-{rst.get('total_gc','0')}GC")
                        st.caption(f"{rst.get('specific_type','Específico')}: {rst.get('specific_pj','0')}PJ | {rst.get('specific_v','0')}V/{rst.get('specific_e','0')}E/{rst.get('specific_d','0')}D | {rst.get('specific_gf','0')}GF-{rst.get('specific_gc','0')}GC")
                    else: st.caption(f"Clasificación no disponible para {name_b}.")
                st.markdown("</div>", unsafe_allow_html=True) # End card

            st.markdown("---")
            st.markdown("<h2 class='section-header'>📊 Datos Clave Adicionales</h2>", unsafe_allow_html=True)
            with st.expander("🔰 Hándicaps y Resultados Clave (Estilo Script Original)", expanded=True):
                st.markdown("<h4 class='card-subtitle'>Enfrentamientos Directos (H2H)</h4>", unsafe_allow_html=True)
                h2h_cols1, h2h_cols2, h2h_cols3 = st.columns(3)
                h2h_cols1.metric("AH H2H (Local en Casa)", col_data["AH_H2H_V"], help="Hándicap Asiático del último H2H con el equipo local actual jugando en casa.")
                h2h_cols2.metric("Res H2H (Local en Casa)", col_data["Res_H2H_V"].replace("*",":"), help="Resultado del último H2H con el equipo local actual jugando en casa.")
                h2h_cols3.metric("AH Actual Partido", col_data["AH_Act"], help="Hándicap Asiático inicial (Bet365) para este partido.")

                h2h_g_cols1, h2h_g_cols2 = st.columns(2)
                h2h_g_cols1.metric("AH H2H (General)", col_data["AH_H2H_G"], help="Hándicap Asiático del H2H más reciente entre ambos equipos, sin importar localía.")
                h2h_g_cols2.metric("Res H2H (General)", col_data["Res_H2H_G"].replace("*",":"), help="Resultado del H2H más reciente entre ambos equipos.")
                st.markdown("</div>", unsafe_allow_html=True) # End card
            
            with st.expander("🔁 Comparativas Indirectas Detalladas", expanded=True):
                comp_col1, comp_col2 = st.columns(2)
                with comp_col1:
                    st.markdown(f"<h5 class='card-subtitle'><span class='home-color'>{display_home_name or 'Local'}</span> vs. <span class='away-color'>Últ. Rival del {display_away_name or 'Visitante'}</span></h5>", unsafe_allow_html=True)
                    st.caption(f"Partido de <span class='home-color'>{display_home_name or 'Local'}</span> contra el último equipo al que se enfrentó <span class='away-color'>{display_away_name or 'Visitante'}</span> (cuando <span class='away-color'>{display_away_name or 'Visitante'}</span> jugó fuera).", unsafe_allow_html=True)
                    comp_str_l = col_data.get('L_vs_UV_A', "-")
                    if comp_str_l and comp_str_l != "-":
                        parts = comp_str_l.split('/')
                        score_part = parts[0].replace('*', ':').strip()
                        ah_loc_part = parts[1].strip() if len(parts) > 1 else " " 
                        ah_val_l = ah_loc_part.rsplit(' ', 1)[0].strip()
                        loc_val_l = ah_loc_part.rsplit(' ', 1)[-1].strip() if ' ' in ah_loc_part else ""

                        st.markdown(f"⚽ **Resultado:** <span class='data-highlight'>{score_part if score_part else placeholder_nodata}</span>", unsafe_allow_html=True, help="Resultado del partido entre el Local y el último rival del Visitante.")
                        st.markdown(f"⚖️ **AH (Partido Comparado):** <span class='ah-value'>{format_ah_as_decimal_string_of(ah_val_l) if ah_val_l else placeholder_nodata}</span>", unsafe_allow_html=True, help="Hándicap de ese partido comparado.")
                        st.markdown(f"🏟️ **Localía de '{display_home_name or 'Local'}':** <span class='data-highlight'>{loc_val_l if loc_val_l else placeholder_nodata}</span>", unsafe_allow_html=True, help=f"Indica si '{display_home_name or 'Local'}' fue local (H) o visitante (A) en ese partido específico.")
                    else: st.info("Comparativa L vs UV A no disponible.")
                with comp_col2:
                    st.markdown(f"<h5 class='card-subtitle'><span class='away-color'>{display_away_name or 'Visitante'}</span> vs. <span class='home-color'>Últ. Rival del {display_home_name or 'Local'}</span></h5>", unsafe_allow_html=True)
                    st.caption(f"Partido de <span class='away-color'>{display_away_name or 'Visitante'}</span> contra el último equipo al que se enfrentó <span class='home-color'>{display_home_name or 'Local'}</span> (cuando <span class='home-color'>{display_home_name or 'Local'}</span> jugó en casa).", unsafe_allow_html=True)
                    comp_str_v = col_data.get('V_vs_UL_H', "-")
                    if comp_str_v and comp_str_v != "-":
                        parts = comp_str_v.split('/')
                        score_part = parts[0].replace('*', ':').strip()
                        ah_loc_part = parts[1].strip() if len(parts) > 1 else " "
                        ah_val_v = ah_loc_part.rsplit(' ', 1)[0].strip()
                        loc_val_v = ah_loc_part.rsplit(' ', 1)[-1].strip() if ' ' in ah_loc_part else ""

                        st.markdown(f"⚽ **Resultado:** <span class='data-highlight'>{score_part if score_part else placeholder_nodata}</span>", unsafe_allow_html=True, help="Resultado del partido entre el Visitante y el último rival del Local.")
                        st.markdown(f"⚖️ **AH (Partido Comparado):** <span class='ah-value'>{format_ah_as_decimal_string_of(ah_val_v) if ah_val_v else placeholder_nodata}</span>", unsafe_allow_html=True, help="Hándicap de ese partido comparado.")
                        st.markdown(f"🏟️ **Localía de '{display_away_name or 'Visitante'}':** <span class='data-highlight'>{loc_val_v if loc_val_v else placeholder_nodata}</span>", unsafe_allow_html=True, help=f"Indica si '{display_away_name or 'Visitante'}' fue local (H) o visitante (A) en ese partido específico.")
                    else: st.info("Comparativa V vs UL H no disponible.")
                st.markdown("</div>", unsafe_allow_html=True) # End card

            with st.expander("📋 Estadísticas Detalladas de Equipos (Resumen)", expanded=False):
                stats_col1,stats_col2=st.columns(2)
                with stats_col1: 
                    st.markdown(f"<h5 class='card-subtitle'>Estadísticas <span class='home-color'>{display_home_name or 'Local'}</span></h5>", unsafe_allow_html=True)
                    st.text(col_data["Stats_L"])
                    st.caption("Rk: Ranking, T: Total, L: Local/Específico, PJ: Partidos, V: Victorias, E: Empates, D: Derrotas, GF: Goles Favor, GC: Goles Contra.")
                with stats_col2: 
                    st.markdown(f"<h5 class='card-subtitle'>Estadísticas <span class='away-color'>{display_away_name or 'Visitante'}</span></h5>", unsafe_allow_html=True)
                    st.text(col_data["Stats_V"])
                    st.caption("Rk: Ranking, T: Total, V: Visitante/Específico, PJ: Partidos, V: Victorias, E: Empates, D: Derrotas, GF: Goles Favor, GC: Goles Contra.")
                st.markdown("</div>", unsafe_allow_html=True) # End card

            with st.expander("ℹ️ Información General del Partido", expanded=False):
                info_col1,info_col2,info_col3=st.columns(3)
                info_col1.metric("Línea Goles Inicial",col_data["G_i"], help="Línea de goles Más/Menos (Over/Under) inicial ofrecida por Bet365.")
                info_col2.metric("Liga",col_data["League"], help="Nombre de la liga en la que se juega el partido.")
                info_col3.metric("ID Partido",col_data["match_id"], help="Identificador único del partido en la plataforma de origen.")
                st.markdown("</div>", unsafe_allow_html=True) # End card

            end_time_of = time.time()
            st.sidebar.success(f"🎉 Análisis completado en {end_time_of - start_time_of:.2f} segundos.")
            st.sidebar.markdown("---")
            st.sidebar.markdown("Creado con ❤️ y Streamlit.")
    else:
        results_container.info("✨ ¡Bienvenido! Ingresa un ID de partido en la barra lateral y haz clic en 'Analizar Partido (OF)' para comenzar el análisis.")
        results_container.markdown("""
        <div class='card' style='text-align:center; margin-top: 20px;'>
            <h2 style='color: #007bff;'>¿Cómo funciona?</h2>
            <p>Esta herramienta extrae y procesa datos de partidos de fútbol para ofrecerte un análisis detallado, incluyendo:</p>
            <ul>
                <li>Clasificaciones de los equipos.</li>
                <li>Cuotas iniciales de Bet365.</li>
                <li>Rendimiento reciente y H2H.</li>
                <li>Comparativas indirectas y mucho más.</li>
            </ul>
            <p><strong>Simplemente introduce el ID del partido y pulsa analizar.</strong></p>
        </div>
        """, unsafe_allow_html=True)

# This is the entry point if this script is run directly.
# For a modular UI, this might not be strictly necessary if ui.py is always imported.
# However, it's good practice for potential standalone testing or if this script becomes the main app entry.
# def main():
# st.set_page_config(layout="wide", page_title="Análisis Avanzado de Partidos (OF)", initial_sidebar_state="expanded")
# if 'driver_other_feature' not in st.session_state:
# st.session_state.driver_other_feature = None
# display_other_feature_ui()

# if __name__ == '__main__':
# main()
