# modules/other_feature.py
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

# --- CONFIGURACIÓN GLOBAL (renombrada para evitar conflictos) ---
BASE_URL_OF = "https://live18.nowgoal25.com"
SELENIUM_TIMEOUT_SECONDS_OF = 20
SELENIUM_POLL_FREQUENCY_OF = 0.2

# --- FUNCIONES DE REQUESTS (renombradas) ---
@st.cache_resource
def get_requests_session_of():
    session = requests.Session()
    retries_req = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    adapter_req = HTTPAdapter(max_retries=retries_req)
    session.mount("https://", adapter_req)
    session.mount("http://", adapter_req)
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36"})
    return session

@st.cache_data(ttl=3600)
def fetch_soup_requests_of(path, max_tries=3, delay=1):
    session = get_requests_session_of()
    url = f"{BASE_URL_OF}{path}"
    for attempt in range(1, max_tries + 1):
        try:
            resp = session.get(url, timeout=10)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except requests.RequestException:
            #st.sidebar.warning(f"Request failed for {url}, attempt {attempt}")
            if attempt == max_tries: return None
            time.sleep(delay * attempt)
    return None

# --- FUNCIONES PARA LÓGICA ORIGINAL DE H2H (Columna 3) (renombradas) ---
@st.cache_data(ttl=3600) 
def get_rival_a_for_original_h2h_of(main_match_id: int):
    soup_h2h_page = fetch_soup_requests_of(f"/match/h2h-{main_match_id}") 
    if not soup_h2h_page: return None, None, None
    table = soup_h2h_page.find("table", id="table_v1") # Historial del equipo LOCAL del main_match_id
    if not table: return None, None, None
    for row in table.find_all("tr", id=re.compile(r"tr1_\d+")):
        if row.get("vs") == "1": 
            match_id_of_rival_a_game = row.get("index") 
            if not match_id_of_rival_a_game: continue
            
            onclick_tags = row.find_all("a", onclick=re.compile(r"team\((\d+)\)"))
            if len(onclick_tags) > 1 : 
                main_home_team_name = "N/A"; main_home_id = "0"
                script_info_main_match = soup_h2h_page.find("script", string=re.compile(r"var _matchInfo ="))
                if script_info_main_match and script_info_main_match.string:
                    h_name_m = re.search(r"hName:\s*'([^']*)'", script_info_main_match.string)
                    if h_name_m: main_home_team_name = h_name_m.group(1).replace("\\'", "'")
                    h_id_m = re.search(r"hId:\s*parseInt\('(\d+)'\)", script_info_main_match.string)
                    if h_id_m: main_home_id = h_id_m.group(1)

                row_home_team_name_tag = onclick_tags[0]; row_away_team_name_tag = onclick_tags[1]
                rival_tag = None
                # Check if the main_home_id matches the ID in the onclick attribute or the name
                row_home_id_onclick = re.search(r"team\((\d+)\)", row_home_team_name_tag.get("onclick", ""))
                is_main_home_team_in_row_home_spot = (main_home_team_name == row_home_team_name_tag.text.strip()) or \
                                                     (row_home_id_onclick and main_home_id == row_home_id_onclick.group(1))
                
                if is_main_home_team_in_row_home_spot : 
                    rival_tag = row_away_team_name_tag 
                else: 
                    rival_tag = row_home_team_name_tag 
                
                rival_a_id_match = re.search(r"team\((\d+)\)", rival_tag.get("onclick", ""))
                rival_a_name = rival_tag.text.strip()

                if rival_a_id_match and rival_a_name:
                    return match_id_of_rival_a_game, rival_a_id_match.group(1), rival_a_name
    return None, None, None

@st.cache_data(ttl=3600)
def get_rival_b_for_original_h2h_of(main_match_id: int): 
    soup_h2h_page = fetch_soup_requests_of(f"/match/h2h-{main_match_id}") 
    if not soup_h2h_page: return None, None, None
    table = soup_h2h_page.find("table", id="table_v2") # Historial del equipo VISITANTE del main_match_id
    if not table: return None, None, None
    for row in table.find_all("tr", id=re.compile(r"tr2_\d+")):
        if row.get("vs") == "1": 
            match_id_of_rival_b_game = row.get("index")
            if not match_id_of_rival_b_game: continue

            onclick_tags = row.find_all("a", onclick=re.compile(r"team\((\d+)\)"))
            main_away_team_name = "N/A"; main_away_id = "0"
            script_info_main_match = soup_h2h_page.find("script", string=re.compile(r"var _matchInfo ="))
            if script_info_main_match and script_info_main_match.string:
                g_name_m = re.search(r"gName:\s*'([^']*)'", script_info_main_match.string)
                if g_name_m: main_away_team_name = g_name_m.group(1).replace("\\'", "'")
                g_id_m = re.search(r"gId:\s*parseInt\('(\d+)'\)", script_info_main_match.string)
                if g_id_m: main_away_id = g_id_m.group(1)
            
            rival_tag = None
            if len(onclick_tags) > 1: 
                row_home_team_name_tag = onclick_tags[0]; row_away_team_name_tag = onclick_tags[1]
                row_home_id_onclick_b = re.search(r"team\((\d+)\)", row_home_team_name_tag.get("onclick", ""))
                is_main_away_team_in_row_home_spot = (main_away_team_name == row_home_team_name_tag.text.strip()) or \
                                                       (row_home_id_onclick_b and main_away_id == row_home_id_onclick_b.group(1))
                if is_main_away_team_in_row_home_spot :
                    rival_tag = row_away_team_name_tag
                else: 
                    rival_tag = row_home_team_name_tag
            elif len(onclick_tags) == 1:
                 rival_tag = onclick_tags[0]

            if rival_tag:
                rival_b_id_match = re.search(r"team\((\d+)\)", rival_tag.get("onclick", ""))
                rival_b_name = rival_tag.text.strip()
                if rival_b_id_match and rival_b_name:
                    return match_id_of_rival_b_game, rival_b_id_match.group(1), rival_b_name
    return None, None, None

# --- FUNCIONES DE SELENIUM (renombradas) ---
@st.cache_resource 
def get_selenium_driver_of():
    options = ChromeOptions(); options.add_argument("--headless"); options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage"); options.add_argument("--disable-gpu")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36")
    options.add_argument('--blink-settings=imagesEnabled=false'); options.add_argument("--window-size=1920,1080")
    try:
        driver = webdriver.Chrome(options=options)
        return driver
    except WebDriverException as e:
        return None

def get_h2h_details_for_original_logic_of(driver_instance, match_id_to_check_h2h_on, actual_rival_a_id, actual_rival_a_name, actual_rival_b_id, actual_rival_b_name): 
    if not driver_instance: return {"status": "error", "resultado": f"Driver no disponible (H2H entre {actual_rival_a_name} y {actual_rival_b_name})"}
    if not match_id_to_check_h2h_on or not actual_rival_a_id or not actual_rival_b_id:
        return {"status": "error", "resultado": f"IDs incompletos para H2H (Buscando entre {actual_rival_a_name} y {actual_rival_b_name})"}

    url_to_visit = f"{BASE_URL_OF}/match/h2h-{match_id_to_check_h2h_on}"
    try:
        driver_instance.get(url_to_visit)
        WebDriverWait(driver_instance, SELENIUM_TIMEOUT_SECONDS_OF, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(
            EC.presence_of_element_located((By.ID, "table_v3")) 
        )
        time.sleep(0.8) 
        soup_selenium = BeautifulSoup(driver_instance.page_source, "html.parser")
    except TimeoutException:
        return {"status": "error", "resultado": f"Timeout esperando tabla H2H (v3) en {url_to_visit} (para H2H entre {actual_rival_a_name} y {actual_rival_b_name})"}
    except Exception as e:
        return {"status": "error", "resultado": f"Error Selenium al cargar {url_to_visit}: {type(e).__name__}"}

    if not soup_selenium: return {"status": "error", "resultado": f"Fallo al obtener soup de {url_to_visit}"}
    
    table_v3_h2h = soup_selenium.find("table", id="table_v3")
    if not table_v3_h2h: 
        return {"status": "error", "resultado": f"Tabla H2H (v3) no encontrada en {url_to_visit}"}

    for row in table_v3_h2h.find_all("tr", id=re.compile(r"tr3_\d+")):
        links = row.find_all("a", onclick=True)
        if len(links) < 2: continue
        
        h2h_row_home_id_match = re.search(r"team\((\d+)\)", links[0].get("onclick", ""))
        h2h_row_away_id_match = re.search(r"team\((\d+)\)", links[1].get("onclick", ""))
        
        if not h2h_row_home_id_match or not h2h_row_away_id_match: continue
        
        h2h_row_home_id = h2h_row_home_id_match.group(1)
        h2h_row_away_id = h2h_row_away_id_match.group(1)
        
        if {h2h_row_home_id, h2h_row_away_id} == {str(actual_rival_a_id), str(actual_rival_b_id)}:
            score_span = row.find("span", class_="fscore_3") 
            if not score_span or not score_span.text or "-" not in score_span.text: continue
            
            score_val = score_span.text.strip()
            g_h, g_a = score_val.split("-", 1)
            tds = row.find_all("td")
            handicap_val = "N/A"
            HANDICAP_TD_IDX = 11 
            if len(tds) > HANDICAP_TD_IDX:
                cell = tds[HANDICAP_TD_IDX]
                d_o = cell.get("data-o"); 
                handicap_val = d_o.strip() if d_o and d_o.strip() not in ["", "-"] else (cell.text.strip() if cell.text.strip() not in ["", "-"] else "N/A")
            
            rol_a_in_this_h2h = "H" if h2h_row_home_id == str(actual_rival_a_id) else "A"
            
            return {
                "status": "found", "goles_home": g_h.strip(), "goles_away": g_a.strip(),
                "handicap": handicap_val, "rol_rival_a": rol_a_in_this_h2h, 
                "h2h_home_team_name": links[0].text.strip(), "h2h_away_team_name": links[1].text.strip()
            }
            
    return {"status": "not_found", "resultado": f"H2H directo no encontrado para {actual_rival_a_name} vs {actual_rival_b_name} en tabla H2H de la página de ref. {match_id_to_check_h2h_on}."}


# ... (el resto de las funciones como get_team_league_info_from_script_of, click_element_robust_of, extract_last_match_in_league_of, get_main_match_odds_selenium_of, extract_standings_data_from_h2h_page_of permanecen igual) ...
# (Copiadas de la respuesta anterior para completitud, ya que no se indicó que tuvieran problemas)
def get_team_league_info_from_script_of(soup):
    home_id, away_id, league_id, home_name, away_name, league_name = (None,)*3 + ("N/A",)*3
    script_tag = soup.find("script", string=re.compile(r"var _matchInfo ="))
    if script_tag and script_tag.string:
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
        if h_name_m: home_name = h_name_m.group(1).replace("\\'", "'")
        if g_name_m: away_name = g_name_m.group(1).replace("\\'", "'")
        if l_name_m: league_name = l_name_m.group(1).replace("\\'", "'")
    return home_id, away_id, league_id, home_name, away_name, league_name

def click_element_robust_of(driver, by, value, timeout=7):
    try:
        element = WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(
            EC.presence_of_element_located((by, value)))
        WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(
            EC.visibility_of(element))
        driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'center'});", element)
        time.sleep(0.3)
        try:
            WebDriverWait(driver, 2, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(
                EC.element_to_be_clickable((by, value))).click()
        except (ElementClickInterceptedException, TimeoutException):
            driver.execute_script("arguments[0].click();", element)
        return True
    except Exception: return False

def extract_last_match_in_league_of(driver, table_css_id_str, main_team_name_in_table, league_id_filter_value,
                                 home_or_away_filter_css_selector, is_home_game_filter):
    try:
        league_checkbox_selector = f"input#checkboxleague{table_css_id_str[-1]}[value='{league_id_filter_value}']"
        if league_id_filter_value:
            click_element_robust_of(driver, By.CSS_SELECTOR, league_checkbox_selector)
            time.sleep(1.5)
        click_element_robust_of(driver, By.CSS_SELECTOR, home_or_away_filter_css_selector)
        time.sleep(1.5)
        page_source_updated = driver.page_source
        soup_updated = BeautifulSoup(page_source_updated, "html.parser")
        table = soup_updated.find("table", id=table_css_id_str)
        if not table: return None
        for row_idx, row in enumerate(table.find_all("tr", id=re.compile(rf"tr{table_css_id_str[-1]}_\d+"))):
            if row.get("style") and "display:none" in row.get("style","").lower(): continue
            if row_idx > 7: break
            if league_id_filter_value and row.get("name") != str(league_id_filter_value): continue
            tds = row.find_all("td")
            if len(tds) < 14: continue
            home_team_row_el = tds[2].find("a"); away_team_row_el = tds[4].find("a")
            if not home_team_row_el or not away_team_row_el: continue
            home_team_row_name = home_team_row_el.text.strip(); away_team_row_name = away_team_row_el.text.strip()
            team_is_home_in_row = main_team_name_in_table == home_team_row_name
            team_is_away_in_row = main_team_name_in_table == away_team_row_name
            if (is_home_game_filter and team_is_home_in_row) or \
               (not is_home_game_filter and team_is_away_in_row):
                date_span = tds[1].find("span", {"name": "timeData"}); date = date_span.text.strip() if date_span else "N/A"
                score_span = tds[3].find("span", class_=re.compile(r"fscore_")); score = score_span.text.strip() if score_span else "N/A"
                handicap_cell = tds[11]
                handicap = handicap_cell.get("data-o", handicap_cell.text.strip())
                if not handicap or handicap.strip() == "-": handicap = "N/A"
                else: handicap = handicap.strip()
                return {"date": date, "home_team": home_team_row_name, "away_team": away_team_row_name,"score": score, "handicap_line": handicap}
        return None
    except Exception: return None

def get_main_match_odds_selenium_of(driver):
    odds_info = {"ah_home_cuota": "N/A", "ah_linea": "N/A", "ah_away_cuota": "N/A", "goals_over_cuota": "N/A", "goals_linea": "N/A", "goals_under_cuota": "N/A"}
    try:
        live_compare_div = WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS_OF, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.presence_of_element_located((By.ID, "liveCompareDiv")))
        bet365_row_selector = "tr#tr_o_1_8[name='earlyOdds']"; bet365_row_selector_alt = "tr#tr_o_1_31[name='earlyOdds']"
        table_odds = live_compare_div.find_element(By.XPATH, ".//table[contains(@class, 'team-table-other')]")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", table_odds)
        time.sleep(0.5)
        bet365_early_odds_row = None
        try:
            bet365_early_odds_row = WebDriverWait(driver, 5, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.visibility_of_element_located((By.CSS_SELECTOR, bet365_row_selector)))
        except TimeoutException:
             bet365_early_odds_row = WebDriverWait(driver, 3, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.visibility_of_element_located((By.CSS_SELECTOR, bet365_row_selector_alt)))
        tds = bet365_early_odds_row.find_elements(By.TAG_NAME, "td")
        if len(tds) >= 11:
            odds_info["ah_home_cuota"] = tds[2].get_attribute("data-o") or tds[2].text.strip() or "N/A"
            odds_info["ah_linea"] = tds[3].get_attribute("data-o") or tds[3].text.strip() or "N/A"
            odds_info["ah_away_cuota"] = tds[4].get_attribute("data-o") or tds[4].text.strip() or "N/A"
            odds_info["goals_over_cuota"] = tds[8].get_attribute("data-o") or tds[8].text.strip() or "N/A"
            odds_info["goals_linea"] = tds[9].get_attribute("data-o") or tds[9].text.strip() or "N/A"
            odds_info["goals_under_cuota"] = tds[10].get_attribute("data-o") or tds[10].text.strip() or "N/A"
    except Exception: pass
    return odds_info

def extract_standings_data_from_h2h_page_of(h2h_soup, target_team_name_exact):
    data = {"name": target_team_name_exact, "ranking": "N/A", "total_pj": "N/A", "total_v": "N/A", "total_e": "N/A", "total_d": "N/A", "total_gf": "N/A", "total_gc": "N/A", "specific_pj": "N/A", "specific_v": "N/A", "specific_e": "N/A", "specific_d": "N/A", "specific_gf": "N/A", "specific_gc": "N/A", "specific_type": "N/A" }
    if not h2h_soup: return data
    standings_section = h2h_soup.find("div", id="porletP4")
    if not standings_section: return data
    team_table_soup = None; is_home_team_table_type = False
    home_div_standings = standings_section.find("div", class_="home-div")
    if home_div_standings:
        home_table_header = home_div_standings.find("tr", class_="team-home")
        if home_table_header and target_team_name_exact in home_table_header.get_text():
            team_table_soup = home_div_standings.find("table", class_="team-table-home")
            is_home_team_table_type = True; data["specific_type"] = "En Casa"
    if not team_table_soup:
        guest_div_standings = standings_section.find("div", class_="guest-div")
        if guest_div_standings:
            guest_table_header = guest_div_standings.find("tr", class_="team-guest")
            if guest_table_header and target_team_name_exact in guest_table_header.get_text():
                team_table_soup = guest_div_standings.find("table", class_="team-table-guest")
                is_home_team_table_type = False; data["specific_type"] = "Fuera"
    if not team_table_soup: return data
    header_row_found = team_table_soup.find("tr", class_=re.compile(r"team-(home|guest)"))
    if header_row_found:
        link = header_row_found.find("a")
        if link:
            full_text = link.get_text(separator=" ", strip=True) 
            name_match = re.search(r"]\s*(.*)", full_text); rank_match = re.search(r"\[(?:[^\]]+)-(\d+)\]", full_text)
            if name_match: data["name"] = name_match.group(1).strip()
            if rank_match: data["ranking"] = rank_match.group(1)
    ft_rows = []; current_section = None
    for row in team_table_soup.find_all("tr", align="center"):
        th_cell = row.find("th");
        if th_cell:
            if "FT" in th_cell.get_text(strip=True): current_section = "FT"
            elif "HT" in th_cell.get_text(strip=True): break 
        if current_section == "FT":
            cells = row.find_all("td")
            if cells: ft_rows.append(cells)
    for cells in ft_rows:
        if len(cells) > 8: 
            row_type_text = cells[0].get_text(strip=True)
            pj, v, e, d, gf, gc = (cells[i].get_text(strip=True) for i in range(1, 7))
            pj = pj if pj else "N/A"; v = v if v else "N/A"; e = e if e else "N/A"; d = d if d else "N/A"; gf = gf if gf else "N/A"; gc = gc if gc else "N/A"
            if row_type_text == "Total": data["total_pj"], data["total_v"], data["total_e"], data["total_d"], data["total_gf"], data["total_gc"] = pj, v, e, d, gf, gc
            elif row_type_text == "Home" and is_home_team_table_type: data["specific_pj"], data["specific_v"], data["specific_e"], data["specific_d"], data["specific_gf"], data["specific_gc"] = pj, v, e, d, gf, gc
            elif row_type_text == "Away" and not is_home_team_table_type: data["specific_pj"], data["specific_v"], data["specific_e"], data["specific_d"], data["specific_gf"], data["specific_gc"] = pj, v, e, d, gf, gc
    return data

# --- STREAMLIT APP UI (Función principal) ---
def display_other_feature_ui():
    st.header("📊 Estadísticas de Clasificación y Partidos (OF)")
    main_match_id_str_input_of = st.sidebar.text_input("🆔 ID Partido (Análisis OF):", value="2696131", help="Pega el ID del partido para análisis en Other Feature.", key="other_feature_match_id_input")
    analizar_button_of = st.sidebar.button("🚀 Analizar Partido (OF)", type="secondary", use_container_width=True, key="other_feature_analizar_button")

    if 'driver_other_feature' not in st.session_state: st.session_state.driver_other_feature = None

    if analizar_button_of:
        main_match_id_to_process_of = None
        if main_match_id_str_input_of:
            try:
                cleaned_id_str = "".join(filter(str.isdigit, main_match_id_str_input_of))
                if cleaned_id_str: main_match_id_to_process_of = int(cleaned_id_str)
            except ValueError: st.error("⚠️ ID de partido no válido (OF)."); st.stop()

        if not main_match_id_to_process_of: st.warning("⚠️ Ingresa un ID de partido válido (OF).")
        else:
            start_time_of = time.time()
            with st.spinner("Obteniendo datos generales y de clasificación (OF)..."):
                main_page_url_h2h_view_of = f"/match/h2h-{main_match_id_to_process_of}"
                soup_main_h2h_page_of = fetch_soup_requests_of(main_page_url_h2h_view_of)

            if not soup_main_h2h_page_of: st.error("No se pudo obtener la página H2H principal (OF). El análisis no puede continuar."); st.stop()

            mp_home_id_of, mp_away_id_of, mp_league_id_of, mp_home_name_from_script, mp_away_name_from_script, mp_league_name_of = get_team_league_info_from_script_of(soup_main_h2h_page_of)
            home_team_main_standings = extract_standings_data_from_h2h_page_of(soup_main_h2h_page_of, mp_home_name_from_script)
            away_team_main_standings = extract_standings_data_from_h2h_page_of(soup_main_h2h_page_of, mp_away_name_from_script)
            display_home_name = home_team_main_standings.get("name", mp_home_name_from_script); display_away_name = away_team_main_standings.get("name", mp_away_name_from_script)

            st.markdown(f"### 📋 {display_home_name or 'Local'} vs {display_away_name or 'Visitante'}"); st.caption(f"Liga: {mp_league_name_of or 'N/A'}")
            if display_home_name and display_home_name != "N/A":
                st.markdown(f"--- **{display_home_name} (Local Partido Principal)** ---")
                st.markdown(f"🏆 Rk: {home_team_main_standings.get('ranking', 'N/A')}")
                st.markdown(f"🌍 T: {home_team_main_standings.get('total_pj', 'N/A')}|{home_team_main_standings.get('total_v', 'N/A')}/{home_team_main_standings.get('total_e', 'N/A')}/{home_team_main_standings.get('total_d', 'N/A')}|{home_team_main_standings.get('total_gf', 'N/A')}-{home_team_main_standings.get('total_gc', 'N/A')}")
                st.markdown(f"🏠 {home_team_main_standings.get('specific_type','En Casa')}: {home_team_main_standings.get('specific_pj', 'N/A')}|{home_team_main_standings.get('specific_v', 'N/A')}/{home_team_main_standings.get('specific_e', 'N/A')}/{home_team_main_standings.get('specific_d', 'N/A')}|{home_team_main_standings.get('specific_gf', 'N/A')}-{home_team_main_standings.get('specific_gc', 'N/A')}")
            if display_away_name and display_away_name != "N/A":
                st.markdown(f"--- **{display_away_name} (Visitante Partido Principal)** ---")
                st.markdown(f"🏆 Rk: {away_team_main_standings.get('ranking', 'N/A')}")
                st.markdown(f"🌍 T: {away_team_main_standings.get('total_pj', 'N/A')}|{away_team_main_standings.get('total_v', 'N/A')}/{away_team_main_standings.get('total_e', 'N/A')}/{away_team_main_standings.get('total_d', 'N/A')}|{away_team_main_standings.get('total_gf', 'N/A')}-{away_team_main_standings.get('total_gc', 'N/A')}")
                st.markdown(f"✈️ {away_team_main_standings.get('specific_type','Fuera')}: {away_team_main_standings.get('specific_pj', 'N/A')}|{away_team_main_standings.get('specific_v', 'N/A')}/{away_team_main_standings.get('specific_e', 'N/A')}/{away_team_main_standings.get('specific_d', 'N/A')}|{away_team_main_standings.get('specific_gf', 'N/A')}-{away_team_main_standings.get('specific_gc', 'N/A')}")
            st.markdown("---")

            main_match_odds_data_of = {}; last_home_match_in_league_of = None; last_away_match_in_league_of = None
            match_id_rival_a_game, rival_a_id_orig_col3_of, rival_a_name_orig_col3_of = get_rival_a_for_original_h2h_of(main_match_id_to_process_of)
            match_id_rival_b_game, rival_b_id_orig_col3_of, rival_b_name_orig_col3_of = get_rival_b_for_original_h2h_of(main_match_id_to_process_of)
            rival_a_standings = {}; rival_b_standings = {}

            with st.spinner("Obteniendo clasificaciones de oponentes (OF)..."):
                if rival_a_name_orig_col3_of and rival_a_name_orig_col3_of != "N/A" and match_id_rival_a_game:
                    soup_rival_a_h2h_page = fetch_soup_requests_of(f"/match/h2h-{match_id_rival_a_game}")
                    if soup_rival_a_h2h_page: rival_a_standings = extract_standings_data_from_h2h_page_of(soup_rival_a_h2h_page, rival_a_name_orig_col3_of)
                if rival_b_name_orig_col3_of and rival_b_name_orig_col3_of != "N/A" and match_id_rival_b_game:
                    soup_rival_b_h2h_page = fetch_soup_requests_of(f"/match/h2h-{match_id_rival_b_game}")
                    if soup_rival_b_h2h_page: rival_b_standings = extract_standings_data_from_h2h_page_of(soup_rival_b_h2h_page, rival_b_name_orig_col3_of)

            driver_actual_of = st.session_state.driver_other_feature
            driver_of_needs_init = False
            if driver_actual_of is None: driver_of_needs_init = True
            else:
                try:
                    _ = driver_actual_of.window_handles
                    if hasattr(driver_actual_of, 'service') and driver_actual_of.service and not driver_actual_of.service.is_connectable(): driver_of_needs_init = True
                except WebDriverException: driver_of_needs_init = True
            if driver_of_needs_init:
                if driver_actual_of is not None:
                    try: driver_actual_of.quit()
                    except: pass
                with st.spinner("🚘 Inicializando WebDriver (OF)..."): driver_actual_of = get_selenium_driver_of()
                st.session_state.driver_other_feature = driver_actual_of

            if driver_actual_of:
                try:
                    with st.spinner("Accediendo a datos detallados con Selenium (OF)..."):
                        driver_actual_of.get(f"{BASE_URL_OF}{main_page_url_h2h_view_of}")
                        WebDriverWait(driver_actual_of, SELENIUM_TIMEOUT_SECONDS_OF).until(EC.presence_of_element_located((By.ID, "table_v1")))
                        time.sleep(1); main_match_odds_data_of = get_main_match_odds_selenium_of(driver_actual_of)
                        if mp_home_id_of and mp_league_id_of and display_home_name and display_home_name != "N/A":
                            last_home_match_in_league_of = extract_last_match_in_league_of(driver_actual_of, "table_v1", display_home_name, mp_league_id_of,"input#cb_sos1[value='1']", is_home_game_filter=True)
                        if mp_away_id_of and mp_league_id_of and display_away_name and display_away_name != "N/A":
                            last_away_match_in_league_of = extract_last_match_in_league_of(driver_actual_of, "table_v2", display_away_name, mp_league_id_of,"input#cb_sos2[value='2']", is_home_game_filter=False)
                except Exception as e_main_sel_of: st.error(f"Error Selenium en pág. principal (OF): {type(e_main_sel_of).__name__} - {str(e_main_sel_of)[:100]}")
            else: st.error("No se pudo iniciar driver Selenium para datos de página principal (OF).")

            st.markdown("#### Betting Odds Bet365 (Iniciales del Partido Principal OF)"); col_odds1_of, col_odds2_of = st.columns(2)
            with col_odds1_of: st.markdown(f"**H. Asiático (OF):** `{main_match_odds_data_of.get('ah_home_cuota','N/A')}` <span style='color:blue; font-weight:bold;'>[{main_match_odds_data_of.get('ah_linea','N/A')}]</span> `{main_match_odds_data_of.get('ah_away_cuota','N/A')}`", unsafe_allow_html=True)
            with col_odds2_of: st.markdown(f"**Línea Goles (OF):** `Ov {main_match_odds_data_of.get('goals_over_cuota','N/A')}` <span style='color:red; font-weight:bold;'>[{main_match_odds_data_of.get('goals_linea','N/A')}]</span> `Un {main_match_odds_data_of.get('goals_under_cuota','N/A')}`", unsafe_allow_html=True)
            st.markdown("---")
            st.markdown("### ⚔️ Análisis Detallado (OF) - Partidos Seleccionados"); col1of, col2of, col3of = st.columns(3)
            with col1of:
                st.markdown(f"##### <span style='color:#4CAF50;'>🏡 Último de {display_home_name or 'Local'} (OF)</span><br>(Casa, Misma Liga)", unsafe_allow_html=True)
                if last_home_match_in_league_of: res = last_home_match_in_league_of; st.markdown(f"{res['home_team']} **{res['score']}** {res['away_team']}"); st.markdown(f"**AH:** <span style='font-weight:bold;'>{res['handicap_line']}</span>", unsafe_allow_html=True); st.caption(f"{res['date']}")
                else: st.info("Último partido local no encontrado.")
            with col2of:
                st.markdown(f"##### <span style='color:#2196F3;'>✈️ Último de {display_away_name or 'Visitante'} (OF)</span><br>(Fuera, Misma Liga)", unsafe_allow_html=True)
                if last_away_match_in_league_of: res = last_away_match_in_league_of; st.markdown(f"{res['home_team']} **{res['score']}** {res['away_team']}"); st.markdown(f"**AH:** <span style='font-weight:bold;'>{res['handicap_line']}</span>", unsafe_allow_html=True); st.caption(f"{res['date']}")
                else: st.info("Último partido visitante no encontrado.")
            with col3of:
                st.markdown(f"##### <span style='color:#E65100;'>🆚 H2H Oponentes (OF)</span><br>(Método Original)", unsafe_allow_html=True)
                rival_a_col3_name_display = rival_a_name_orig_col3_of if rival_a_name_orig_col3_of and rival_a_name_orig_col3_of != "N/A" else (rival_a_id_orig_col3_of or "Rival A")
                rival_b_col3_name_display = rival_b_name_orig_col3_of if rival_b_name_orig_col3_of and rival_b_name_orig_col3_of != "N/A" else (rival_b_id_orig_col3_of or "Rival B")
                details_h2h_col3_of = {"status": "error", "resultado": "N/A (OF)"}
                if match_id_rival_a_game and rival_a_id_orig_col3_of and rival_b_id_orig_col3_of and driver_actual_of: 
                    with st.spinner(f"Buscando H2H: {rival_a_col3_name_display} vs {rival_b_col3_name_display}..."):
                        details_h2h_col3_of = get_h2h_details_for_original_logic_of(driver_actual_of, match_id_rival_a_game, rival_a_id_orig_col3_of, rival_a_col3_name_display, rival_b_id_orig_col3_of, rival_b_col3_name_display)
                if details_h2h_col3_of.get("status") == "found":
                    res_h2h = details_h2h_col3_of; st.markdown(f"<p style='font-size:0.9em;'><b>{res_h2h.get('h2h_home_team_name')}</b> {res_h2h.get('goles_home')} - {res_h2h.get('goles_away')} <b>{res_h2h.get('h2h_away_team_name')}</b> (AH: {res_h2h.get('handicap')})</p>", unsafe_allow_html=True)
                else: st.info(details_h2h_col3_of.get('resultado', f"H2H directo no encontrado para {rival_a_col3_name_display} vs {rival_b_col3_name_display}."))
                st.markdown("---")
                if rival_a_standings.get("name", "N/A") != "N/A":
                    st.markdown(f"**Clasif. {rival_a_standings.get('name', 'Rival A')}:**")
                    st.markdown(f"🏆 Rk: {rival_a_standings.get('ranking', 'N/A')}")
                    st.markdown(f"🌍 T: {rival_a_standings.get('total_pj', 'N/A')}|{rival_a_standings.get('total_v', 'N/A')}/{rival_a_standings.get('total_e', 'N/A')}/{rival_a_standings.get('total_d', 'N/A')}|{rival_a_standings.get('total_gf', 'N/A')}-{rival_a_standings.get('total_gc', 'N/A')}")
                    icon_specific_a = "🏠" if rival_a_standings.get('specific_type') == "En Casa" else "✈️"; st.markdown(f"{icon_specific_a} {rival_a_standings.get('specific_type','Stats')}: {rival_a_standings.get('specific_pj', 'N/A')}|{rival_a_standings.get('specific_v', 'N/A')}/{rival_a_standings.get('specific_e', 'N/A')}/{rival_a_standings.get('specific_d', 'N/A')}|{rival_a_standings.get('specific_gf', 'N/A')}-{rival_a_standings.get('specific_gc', 'N/A')}")
                else: st.caption(f"Standings no disponibles para {rival_a_col3_name_display}")
                st.markdown("---")
                if rival_b_standings.get("name", "N/A") != "N/A":
                    st.markdown(f"**Clasif. {rival_b_standings.get('name', 'Rival B')}:**")
                    st.markdown(f"🏆 Rk: {rival_b_standings.get('ranking', 'N/A')}")
                    st.markdown(f"🌍 T: {rival_b_standings.get('total_pj', 'N/A')}|{rival_b_standings.get('total_v', 'N/A')}/{rival_b_standings.get('total_e', 'N/A')}/{rival_b_standings.get('total_d', 'N/A')}|{rival_b_standings.get('total_gf', 'N/A')}-{rival_b_standings.get('total_gc', 'N/A')}")
                    icon_specific_b = "🏠" if rival_b_standings.get('specific_type') == "En Casa" else "✈️"; st.markdown(f"{icon_specific_b} {rival_b_standings.get('specific_type','Stats')}: {rival_b_standings.get('specific_pj', 'N/A')}|{rival_b_standings.get('specific_v', 'N/A')}/{rival_b_standings.get('specific_e', 'N/A')}/{rival_b_standings.get('specific_d', 'N/A')}|{rival_b_standings.get('specific_gf', 'N/A')}-{rival_b_standings.get('specific_gc', 'N/A')}")
                else: st.caption(f"Standings no disponibles para {rival_b_col3_name_display}")
            
            end_time_of = time.time(); st.markdown("---"); st.caption(f"⏱️ Tiempo total del análisis (OF): {end_time_of - start_time_of:.2f} segundos")
    else: st.info("✨ Ingresa un ID de partido en la barra lateral (OF) y haz clic en 'Analizar Partido (OF)' para comenzar.")
