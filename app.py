# streamlit_app.py

import streamlit as st
import time
import requests
import re
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Importaciones de Selenium
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, ElementClickInterceptedException, NoSuchElementException

# --- CONFIGURACIÓN GLOBAL ---
BASE_URL = "https://live18.nowgoal25.com"
SELENIUM_TIMEOUT_SECONDS = 15 
SELENIUM_POLL_FREQUENCY = 0.2 

# --- FUNCIONES DE REQUESTS (get_requests_session, fetch_soup_requests) ---
@st.cache_resource 
def get_requests_session():
    session = requests.Session()
    retries_req = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    adapter_req = HTTPAdapter(max_retries=retries_req)
    session.mount("https://", adapter_req)
    session.mount("http://", adapter_req)
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36"})
    return session

@st.cache_data(ttl=3600) 
def fetch_soup_requests(path, max_tries=3, delay=1):
    session = get_requests_session()
    url = f"{BASE_URL}{path}"
    for attempt in range(1, max_tries + 1):
        try:
            resp = session.get(url, timeout=10)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except requests.RequestException:
            if attempt == max_tries:
                pass
                return None
            time.sleep(delay * attempt)
    return None

# --- FUNCIONES MODIFICADAS PARA OBTENER NOMBRES DE RIVALES ---
@st.cache_data(ttl=3600)
def get_last_home(match_id): # Devuelve (key_match_id, rival_id, rival_name)
    soup = fetch_soup_requests(f"/match/h2h-{match_id}")
    if not soup: return None, None, None
    table = soup.find("table", id="table_v1")
    if not table: return None, None, None
    for row in table.find_all("tr", id=re.compile(r"tr1_\d+")):
        if row.get("vs") == "1": 
            key_match_id = row.get("index") 
            if not key_match_id: continue
            tds = row.find_all("td")
            if len(tds) > 4:
                away_team_cell = tds[4] 
                away_team_link = away_team_cell.find("a", onclick=re.compile(r"team\(\d+\)"))
                if away_team_link:
                    rival_id_match = re.search(r"team\((\d+)\)", away_team_link["onclick"])
                    rival_name = away_team_link.text.strip()
                    if rival_id_match and rival_name:
                        return key_match_id, rival_id_match.group(1), rival_name
    return None, None, None

@st.cache_data(ttl=3600)
def get_last_away(match_id): # Devuelve (key_match_id, rival_id, rival_name)
    soup = fetch_soup_requests(f"/match/h2h-{match_id}")
    if not soup: return None, None, None
    table_home_history = soup.find("table", id="table_v1") 
    if not table_home_history: return None, None, None
    for row in table_home_history.find_all("tr", id=re.compile(r"tr1_\d+")):
        if row.get("vs") == "0": 
            key_match_id = row.get("index") 
            if not key_match_id: continue
            tds = row.find_all("td")
            if len(tds) > 2:
                home_team_cell = tds[2] 
                home_team_link = home_team_cell.find("a", onclick=re.compile(r"team\(\d+\)"))
                if home_team_link:
                    rival_id_match = re.search(r"team\((\d+)\)", home_team_link["onclick"])
                    rival_name = home_team_link.text.strip()
                    if rival_id_match and rival_name:
                        return key_match_id, rival_id_match.group(1), rival_name
    return None, None, None

# --- FUNCIONES DE SELENIUM (get_selenium_driver, get_h2h_details_selenium, get_team_league_info_from_script, click_element_robust, extract_last_match_in_league, get_main_match_odds_selenium) ---
# (Estas funciones se mantienen como en la respuesta anterior, asegúrate de tener las versiones más actualizadas de ellas aquí)
def get_selenium_driver():
    options = ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36")
    options.add_argument('--blink-settings=imagesEnabled=false')
    options.add_argument("--window-size=1920,1080")
    try:
        driver = webdriver.Chrome(options=options)
        return driver
    except WebDriverException as e:
        st.error(f"SELENIUM DRIVER ERROR: {e}")
        return None

def get_h2h_details_selenium(key_match_id, rival_a_id, rival_b_id):
    if not key_match_id or not rival_a_id or not rival_b_id:
        return {"status": "error", "resultado": "N/A (IDs incompletos para H2H)"}
    url = f"{BASE_URL}/match/h2h-{key_match_id}"
    driver = get_selenium_driver()
    if not driver: return {"status": "error", "resultado": "N/A (Fallo Selenium Driver)"}
    soup_selenium = None
    try:
        driver.get(url)
        WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS, poll_frequency=SELENIUM_POLL_FREQUENCY).until(
            EC.presence_of_element_located((By.ID, "table_v2")) 
        )
        time.sleep(0.7) 
        page_source = driver.page_source 
        soup_selenium = BeautifulSoup(page_source, "html.parser")
    except TimeoutException:
        return {"status": "error", "resultado": "N/A (Timeout Selenium H2H)"}
    except Exception as e:
        return {"status": "error", "resultado": f"N/A (Error Selenium H2H: {type(e).__name__})"}
    finally:
        if driver: driver.quit()

    if not soup_selenium: return {"status": "error", "resultado": "N/A (Fallo soup Selenium H2H)"}
    table = soup_selenium.find("table", id="table_v2") 
    if not table: return {"status": "error", "resultado": "N/A (Tabla H2H no encontrada en Selenium)"}

    for row in table.find_all("tr", id=re.compile(r"tr2_\d+")): 
        links = row.find_all("a", onclick=True)
        if len(links) < 2: continue
        home_id_match_search = re.search(r"team\((\d+)\)", links[0].get("onclick", ""))
        away_id_match_search = re.search(r"team\((\d+)\)", links[1].get("onclick", ""))
        if not home_id_match_search or not away_id_match_search: continue
        home_id_found_h2h = home_id_match_search.group(1)
        away_id_found_h2h = away_id_match_search.group(1)

        if {home_id_found_h2h, away_id_found_h2h} == {str(rival_a_id), str(rival_b_id)}:
            score_span = row.find("span", class_="fscore_2") 
            if not score_span or not score_span.text or "-" not in score_span.text: continue
            score = score_span.text.strip()
            goles_home_h2h, goles_away_h2h = score.split("-")
            tds = row.find_all("td")
            handicap = "N/A"
            HANDICAP_LINE_TD_INDEX_H2H_TABLE = 11 
            if len(tds) > HANDICAP_LINE_TD_INDEX_H2H_TABLE:
                celda_handicap = tds[HANDICAP_LINE_TD_INDEX_H2H_TABLE]
                data_o_valor = celda_handicap.get("data-o")
                if data_o_valor is not None and data_o_valor.strip() not in ["", "-"]:
                    handicap = data_o_valor.strip()
                else:
                    texto_celda = celda_handicap.text.strip()
                    if texto_celda not in ["", "-"]: handicap = texto_celda
            
            rol_rival_a_en_este_h2h = "A" if away_id_found_h2h == str(rival_a_id) else "H"
            # Nombres de los equipos en este H2H específico
            h2h_home_team_name = links[0].text.strip()
            h2h_away_team_name = links[1].text.strip()

            return {
                "status": "found",
                "goles_home": goles_home_h2h, 
                "goles_away": goles_away_h2h, 
                "handicap": handicap,
                "rol_rival_a": rol_rival_a_en_este_h2h, 
                "raw_string": f"{goles_home_h2h}*{goles_away_h2h}/{handicap} {rol_rival_a_en_este_h2h}",
                "h2h_home_team_name": h2h_home_team_name, # Añadido
                "h2h_away_team_name": h2h_away_team_name  # Añadido
            }
    return {"status": "not_found", "resultado": "N/A (H2H entre RivalA y RivalB no encontrado en tabla)"}


def get_team_league_info_from_script(soup):
    home_id, away_id, league_id = None, None, None
    home_name, away_name, league_name = "N/A", "N/A", "N/A"
    script_tag = soup.find("script", string=re.compile(r"var _matchInfo ="))
    if script_tag:
        script_content = script_tag.string
        h_id_m = re.search(r"hId:\s*parseInt\('(\d+)'\)", script_content)
        g_id_m = re.search(r"gId:\s*parseInt\('(\d+)'\)", script_content)
        sclass_id_m = re.search(r"sclassId:\s*parseInt\('(\d+)'\)", script_content)
        h_name_m = re.search(r"hName:\s*'([^']*)'", script_content)
        g_name_m = re.search(r"gName:\s*'([^']*)'", script_content)
        l_name_m = re.search(r"lName:\s*'([^']*)'", script_content)
        if h_id_m: home_id = h_id_m.group(1)
        if g_id_m: away_id = g_id_m.group(1)
        if sclass_id_m: league_id = sclass_id_m.group(1)
        if h_name_m: home_name = h_name_m.group(1)
        if g_name_m: away_name = g_name_m.group(1)
        if l_name_m: league_name = l_name_m.group(1)
    return home_id, away_id, league_id, home_name, away_name, league_name

def click_element_robust(driver, by, value, timeout=7):
    try:
        element = WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY).until(
            EC.presence_of_element_located((by, value))
        )
        WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY).until(
            EC.visibility_of(element) 
        )
        WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY).until(
            EC.element_to_be_clickable((by, value)) 
        )
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element) 
        time.sleep(0.5) 
        driver.execute_script("arguments[0].click();", element)
        return True
    except Exception: 
        return False

def extract_last_match_in_league(driver, table_css_id_str, main_team_name_in_table, league_id_filter_value, 
                                 home_or_away_filter_css_selector, is_home_game_filter):
    try:
        league_checkbox_selector = f"input#checkboxleague{table_css_id_str[-1]}[value='{league_id_filter_value}']"
        click_element_robust(driver, By.CSS_SELECTOR, league_checkbox_selector)
        time.sleep(2) 
        click_element_robust(driver, By.CSS_SELECTOR, home_or_away_filter_css_selector)
        time.sleep(2) 

        page_source_updated = driver.page_source
        soup_updated = BeautifulSoup(page_source_updated, "html.parser")
        table = soup_updated.find("table", id=table_css_id_str)
        if not table: return None

        for row_idx, row in enumerate(table.find_all("tr", id=re.compile(rf"tr{table_css_id_str[-1]}_\d+"))):
            if row.get("style") and "display:none" in row.get("style"): continue 
            if row_idx > 7: break 
            if row.get("name") != str(league_id_filter_value): continue 
            
            tds = row.find_all("td")
            if len(tds) < 14: continue

            home_team_row_el = tds[2].find("a")
            away_team_row_el = tds[4].find("a")
            if not home_team_row_el or not away_team_row_el: continue
            
            home_team_row_name = home_team_row_el.text.strip()
            away_team_row_name = away_team_row_el.text.strip()

            team_is_home_in_row = main_team_name_in_table == home_team_row_name
            team_is_away_in_row = main_team_name_in_table == away_team_row_name

            if (is_home_game_filter and not team_is_home_in_row) or \
               (not is_home_game_filter and not team_is_away_in_row):
                continue 

            date_span = tds[1].find("span", {"name": "timeData"})
            date = date_span.text.strip() if date_span else "N/A"
            score_span = tds[3].find("span", class_=re.compile(r"fscore_"))
            score = score_span.text.strip() if score_span else "N/A"
            
            handicap_cell = tds[11] 
            handicap = handicap_cell.get("data-o", handicap_cell.text.strip())
            if not handicap or handicap == "-": handicap = "N/A"
            
            return {
                "date": date, "home_team": home_team_row_name, "away_team": away_team_row_name,
                "score": score, "handicap_line": handicap,
            }
        return None
    except Exception:
        return None

def get_main_match_odds_selenium(driver):
    odds_info = {
        "ah_home_cuota": "N/A", "ah_linea": "N/A", "ah_away_cuota": "N/A",
        "goals_over_cuota": "N/A", "goals_linea": "N/A", "goals_under_cuota": "N/A"
    }
    try:
        live_compare_div = WebDriverWait(driver, 10, poll_frequency=SELENIUM_POLL_FREQUENCY).until(
            EC.presence_of_element_located((By.ID, "liveCompareDiv"))
        )
        bet365_row_selector = "tr#tr_o_1_8[name='earlyOdds']"
        table_odds = live_compare_div.find_element(By.XPATH, ".//table[contains(@class, 'team-table-other')]")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", table_odds)
        time.sleep(0.5)
        bet365_early_odds_row = WebDriverWait(driver, 5, poll_frequency=SELENIUM_POLL_FREQUENCY).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, bet365_row_selector))
        )
        tds = bet365_early_odds_row.find_elements(By.TAG_NAME, "td")
        if len(tds) >= 11:
            odds_info["ah_home_cuota"] = tds[2].get_attribute("data-o") or tds[2].text.strip()
            odds_info["ah_linea"] = tds[3].get_attribute("data-o") or tds[3].text.strip()
            odds_info["ah_away_cuota"] = tds[4].get_attribute("data-o") or tds[4].text.strip()
            odds_info["goals_over_cuota"] = tds[8].get_attribute("data-o") or tds[8].text.strip()
            odds_info["goals_linea"] = tds[9].get_attribute("data-o") or tds[9].text.strip()
            odds_info["goals_under_cuota"] = tds[10].get_attribute("data-o") or tds[10].text.strip()
    except Exception:
        pass
    return odds_info

# --- STREAMLIT APP UI ---
st.set_page_config(page_title="Análisis Visual H2H Nowgoal", layout="wide", initial_sidebar_state="expanded")
st.title("🏆 Análisis Visual de Partidos - Nowgoal")

st.sidebar.image("https://nowgoal.com/img/logo.png", width=150) 
st.sidebar.header("Configuración")

# --- CAMBIO A TEXT_INPUT PARA EL ID DEL PARTIDO ---
main_match_id_str = st.sidebar.text_input(
    "🆔 ID del Partido Principal:", value="2778085", 
    help="Pega el ID del partido para el análisis."
)
analizar_button = st.sidebar.button("🚀 Analizar Partido", type="primary", use_container_width=True)
st.sidebar.markdown("---")
st.sidebar.info("Muestra cuotas iniciales, últimos partidos en liga con H.A. y el H2H de oponentes.")

if analizar_button:
    main_match_id_input = None
    if main_match_id_str:
        try:
            # Intentar limpiar y convertir a entero
            cleaned_id_str = "".join(filter(str.isdigit, main_match_id_str))
            if cleaned_id_str:
                main_match_id_input = int(cleaned_id_str)
        except ValueError:
            st.error("⚠️ El ID del partido ingresado no es un número válido.")
            st.stop()
    
    if not main_match_id_input:
        st.warning("⚠️ Por favor, ingresa un ID de partido válido.")
    else:
        start_time = time.time()
        
        main_page_url_h2h = f"/match/h2h-{main_match_id_input}"
        soup_main_h2h = fetch_soup_requests(main_page_url_h2h)
        
        mp_home_id, mp_away_id, mp_league_id, mp_home_name, mp_away_name, mp_league_name = (None,)*6
        if soup_main_h2h:
            mp_home_id, mp_away_id, mp_league_id, mp_home_name, mp_away_name, mp_league_name = get_team_league_info_from_script(soup_main_h2h)
        
        st.markdown(f"### 📋 Info Partido Principal (ID: {main_match_id_input})")
        col_mp_info1, col_mp_info2 = st.columns(2)
        with col_mp_info1: st.markdown(f"**Local:** {mp_home_name or 'N/A'}")
        with col_mp_info2: st.markdown(f"**Visitante:** {mp_away_name or 'N/A'}")
        st.markdown(f"**Liga:** {mp_league_name or 'N/A'}")
        
        main_match_odds = {}
        last_home_in_league_info = None
        last_away_in_league_info = None
        
        selenium_driver_main_page = get_selenium_driver()
        if selenium_driver_main_page:
            try:
                selenium_driver_main_page.get(f"{BASE_URL}{main_page_url_h2h}")
                main_match_odds = get_main_match_odds_selenium(selenium_driver_main_page)
                
                if mp_home_id and mp_away_id and mp_league_id:
                    with st.spinner(f"Buscando último EN CASA en liga para {mp_home_name}..."):
                        last_home_in_league_info = extract_last_match_in_league(
                            selenium_driver_main_page, "table_v1", mp_home_name, mp_league_id,
                            "input#cb_sos1", is_home_game_filter=True
                        )
                    with st.spinner(f"Buscando último FUERA en liga para {mp_away_name}..."):
                        last_away_in_league_info = extract_last_match_in_league(
                            selenium_driver_main_page, "table_v2", mp_away_name, mp_league_id,
                            "input#cb_sos2", is_home_game_filter=False
                        )
                else:
                    st.warning("Faltan IDs de equipo/liga del partido principal para análisis de liga.", icon="⚠️")
            finally:
                 if selenium_driver_main_page: selenium_driver_main_page.quit()
        else:
            st.error("No se pudo iniciar driver Selenium para cuotas y análisis de liga.")

        st.markdown("#### Betting Odds Bet365 (Iniciales)")
        col_odds1, col_odds2 = st.columns(2)
        with col_odds1:
            st.markdown(f"**H. Asiático:** `{main_match_odds.get('ah_home_cuota','N/A')}` <span style='color:blue; font-weight:bold;'>[{main_match_odds.get('ah_linea','N/A')}]</span> `{main_match_odds.get('ah_away_cuota','N/A')}`", unsafe_allow_html=True)
        with col_odds2:
            st.markdown(f"**Línea Goles:** `Ov {main_match_odds.get('goals_over_cuota','N/A')}` <span style='color:red; font-weight:bold;'>[{main_match_odds.get('goals_linea','N/A')}]</span> `Un {main_match_odds.get('goals_under_cuota','N/A')}`", unsafe_allow_html=True)
        st.markdown("---")

        st.markdown("### ⚔️ Análisis Detallado")
        col1, col2, col3 = st.columns(3)

        with col1:
            st.markdown(f"##### <span style='color:#4CAF50;'>🏡 Último de {mp_home_name or 'Local'}</span><br>(Casa, Misma Liga)", unsafe_allow_html=True)
            if last_home_in_league_info:
                res = last_home_in_league_info
                st.markdown(f"{res['home_team']} **{res['score']}** {res['away_team']}")
                st.markdown(f"**AH:** <span style='font-weight:bold;'>{res['handicap_line']}</span>", unsafe_allow_html=True)
                st.caption(f"{res['date']}")
            else:
                st.info("No encontrado.")
        
        with col2:
            st.markdown(f"##### <span style='color:#2196F3;'>✈️ Último de {mp_away_name or 'Visitante'}</span><br>(Fuera, Misma Liga)", unsafe_allow_html=True)
            if last_away_in_league_info:
                res = last_away_in_league_info
                st.markdown(f"{res['home_team']} **{res['score']}** {res['away_team']}")
                st.markdown(f"**AH:** <span style='font-weight:bold;'>{res['handicap_line']}</span>", unsafe_allow_html=True)
                st.caption(f"{res['date']}")
            else:
                st.info("No encontrado.")

        with col3:
            st.markdown(f"##### <span style='color:#E65100;'>🆚 H2H Oponentes</span><br>(Método Original)", unsafe_allow_html=True)
            # --- LÓGICA H2H ORIGINAL CON NOMBRES ---
            key_h2h, rival_a_id, rival_a_name = get_last_home(main_match_id_input) # Ahora devuelve nombre
            _, rival_b_id, rival_b_name = get_last_away(main_match_id_input)       # Ahora devuelve nombre
            
            rival_a_display_name = rival_a_name if rival_a_name else (rival_a_id if rival_a_id else "Rival A")
            rival_b_display_name = rival_b_name if rival_b_name else (rival_b_id if rival_b_id else "Rival B")

            details_h2h_orig = {"status": "error", "resultado": "N/A"}
            if key_h2h and rival_a_id and rival_b_id:
                with st.spinner(f"H2H entre {rival_a_display_name} y {rival_b_display_name}..."):
                    details_h2h_orig = get_h2h_details_selenium(key_h2h, rival_a_id, rival_b_id)
            
            if details_h2h_orig.get("status") == "found":
                # Construir frase descriptiva
                res_h2h = details_h2h_orig
                h2h_home_name = res_h2h.get("h2h_home_team_name", "Local H2H")
                h2h_away_name = res_h2h.get("h2h_away_team_name", "Visitante H2H")
                g_home = int(res_h2h['goles_home'])
                g_away = int(res_h2h['goles_away'])
                
                desc_resultado = ""
                if g_home > g_away:
                    desc_resultado = f"{h2h_home_name} ganó a {h2h_away_name}"
                elif g_away > g_home:
                    desc_resultado = f"{h2h_away_name} ganó a {h2h_home_name}"
                else:
                    desc_resultado = f"Empate entre {h2h_home_name} y {h2h_away_name}"

                st.markdown(f"<p style='font-size:1.1em; font-weight:bold; color:#E65100;'>{desc_resultado} ({g_home}-{g_away})</p>", unsafe_allow_html=True)
                st.markdown(f"H.A.: {res_h2h['handicap']} | Rol de '{rival_a_display_name}' en H2H: {res_h2h['rol_rival_a']}")
                st.caption(f"H2H entre {rival_a_display_name} y {rival_b_display_name}")

            else:
                st.info(f"{details_h2h_orig.get('resultado', 'No disponible')}")
                st.caption(f"H2H entre {rival_a_display_name} y {rival_b_display_name}")
        
        end_time = time.time()
        st.markdown("---")
        st.caption(f"⏱️ Tiempo total del análisis: {end_time - start_time:.2f} segundos")
else:
    st.info("✨ Ingresa un ID de partido en la barra lateral y haz clic en 'Analizar Partido' para comenzar.")
