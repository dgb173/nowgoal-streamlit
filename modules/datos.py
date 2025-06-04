# modules/other_feature_NUEVO.py

import streamlit as st
import time
import requests
import re
import math
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# IMPORTAR LA FUNCIÓN PARA LAS ESTADÍSTICAS DETALLADAS DE PARTIDO
from modules.match_stats_extractor import _get_match_stats_data 

# Importaciones de Selenium
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, ElementClickInterceptedException, NoSuchElementException

# --- CONFIGURACIÓN GLOBAL ---
BASE_URL_OF = "https://live18.nowgoal25.com" # Verifica que este sea el dominio correcto
SELENIUM_TIMEOUT_SECONDS_OF = 20
SELENIUM_POLL_FREQUENCY_OF = 0.2

# --- FUNCIONES HELPER PARA PARSEO Y FORMATEO (ADAPTADAS Y MODIFICADAS) ---
def parse_ah_to_number_of(ah_line_str: str):
    if not isinstance(ah_line_str, str): return None
    s = ah_line_str.strip().replace(' ', '')
    if not s or s in ['-', '?']: return None
    original_starts_with_minus = ah_line_str.strip().startswith('-')
    try:
        if '/' in s: # Formatos como "0.5/1", "-0/0.5"
            parts = s.split('/')
            if len(parts) != 2: return None
            p1_str, p2_str = parts[0], parts[1]
            try: val1 = float(p1_str)
            except ValueError: return None
            try: val2 = float(p2_str)
            except ValueError: return None
            if val1 < 0 and not p2_str.startswith('-') and val2 > 0:
                 val2 = -abs(val2)
            elif original_starts_with_minus and val1 == 0.0 and \
                 (p1_str == "0" or p1_str == "-0") and \
                 not p2_str.startswith('-') and val2 > 0:
                val2 = -abs(val2)
            return (val1 + val2) / 2.0
        else: # Formatos como "0.5", "-1"
            return float(s)
    except ValueError:
        return None

def format_ah_as_decimal_string_of(ah_line_str: str, for_sheets=False):
    if not isinstance(ah_line_str, str) or not ah_line_str.strip() or ah_line_str.strip() in ['-', '?']:
        return ah_line_str.strip() if isinstance(ah_line_str, str) and ah_line_str.strip() in ['-','?'] else '-'
    
    numeric_value = parse_ah_to_number_of(ah_line_str)
    if numeric_value is None:
        return ah_line_str.strip() if ah_line_str.strip() in ['-','?'] else '-'

    if numeric_value == 0.0:
        return "0"
    
    sign = -1 if numeric_value < 0 else 1
    abs_num = abs(numeric_value)
    mod_val = abs_num % 1
    
    if mod_val == 0.0: abs_rounded = abs_num
    elif mod_val == 0.25: abs_rounded = math.floor(abs_num) + 0.25
    elif mod_val == 0.5: abs_rounded = abs_num
    elif mod_val == 0.75: abs_rounded = math.floor(abs_num) + 0.75
    else: 
        if mod_val < 0.25: abs_rounded = math.floor(abs_num)
        elif mod_val < 0.75: abs_rounded = math.floor(abs_num) + 0.5
        else: abs_rounded = math.ceil(abs_num)

    final_value_signed = sign * abs_rounded

    if final_value_signed == 0.0: output_str = "0"
    elif abs(final_value_signed - round(final_value_signed, 0)) < 1e-9 : output_str = str(int(round(final_value_signed, 0)))
    elif abs(final_value_signed - (math.floor(final_value_signed) + 0.5)) < 1e-9: output_str = f"{final_value_signed:.1f}"
    elif abs(final_value_signed - (math.floor(final_value_signed) + 0.25)) < 1e-9 or \
         abs(final_value_signed - (math.floor(final_value_signed) + 0.75)) < 1e-9: output_str = f"{final_value_signed:.2f}".replace(".25", ".25").replace(".75", ".75")
    else: output_str = f"{final_value_signed:.2f}" 

    if for_sheets:
        return "'" + output_str.replace('.', ',') if output_str not in ['-','?'] else output_str
    return output_str

# MODIFICADA: Ahora devuelve el 'matchIndex' para poder usarlo en las estadísticas detalladas
def get_match_details_from_row_of(row_element, score_class_selector='score', source_table_type='h2h'):
    try:
        cells = row_element.find_all('td')
        if len(cells) < 12: return None
        league_id_hist_attr = row_element.get('name')
        home_idx, score_idx, away_idx, ah_idx = 2, 3, 4, 11
        home_tag = cells[home_idx].find('a'); home = home_tag.text.strip() if home_tag else cells[home_idx].text.strip()
        away_tag = cells[away_idx].find('a'); away = away_tag.text.strip() if away_tag else cells[away_idx].text.strip()
        score_cell_content = cells[score_idx].text.strip()
        score_span = cells[score_idx].find('span', class_=lambda x: x and score_class_selector in x)
        score_raw_text = score_span.text.strip() if score_span else score_cell_content
        score_m = re.match(r'(\d+-\d+)', score_raw_text); score_raw = score_m.group(1) if score_m else '?-?'
        score_fmt = score_raw.replace('-', '*') if score_raw != '?-?' else '?*?'
        ah_line_raw_text = cells[ah_idx].text.strip()
        ah_line_fmt = format_ah_as_decimal_string_of(ah_line_raw_text) 
        if not home or not away: return None
        
        # AÑADIDO: Extraer el matchIndex
        match_id_for_stats = row_element.get('index') 

        return {'home': home, 'away': away, 'score': score_fmt, 'score_raw': score_raw,
                'ahLine': ah_line_fmt, 'ahLine_raw': ah_line_raw_text,
                'matchIndex': row_element.get('index'), 'vs': row_element.get('vs'),
                'league_id_hist': league_id_hist_attr, 
                'match_id_for_stats': match_id_for_stats} # <--- MODIFICADO: AÑADIDO match_id_for_stats
    except Exception: return None

@st.cache_resource
def get_requests_session_of():
    session = requests.Session()
    retries_req = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    adapter_req = HTTPAdapter(max_retries=retries_req)
    session.mount("https://", adapter_req); session.mount("http://", adapter_req)
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36"})
    return session

@st.cache_data(ttl=3600)
def fetch_soup_requests_of(path, max_tries=3, delay=1):
    session = get_requests_session_of(); url = f"{BASE_URL_OF}{path}"
    for attempt in range(1, max_tries + 1):
        try:
            resp = session.get(url, timeout=10); resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except requests.RequestException:
            if attempt == max_tries: return None
            time.sleep(delay * attempt)
    return None

@st.cache_data(ttl=3600) 
def get_rival_a_for_original_h2h_of(main_match_id: int):
    soup_h2h_page = fetch_soup_requests_of(f"/match/h2h-{main_match_id}") 
    if not soup_h2h_page: return None, None, None
    table = soup_h2h_page.find("table", id="table_v1") 
    if not table: return None, None, None
    for row in table.find_all("tr", id=re.compile(r"tr1_\d+")):
        if row.get("vs") == "1": 
            key_match_id_for_h2h_url = row.get("index") 
            if not key_match_id_for_h2h_url: continue
            onclicks = row.find_all("a", onclick=True) 
            if len(onclicks) > 1 and onclicks[1].get("onclick"): 
                rival_tag = onclicks[1]; rival_a_id_match = re.search(r"team\((\d+)\)", rival_tag.get("onclick", ""))
                rival_a_name = rival_tag.text.strip()
                if rival_a_id_match and rival_a_name: return key_match_id_for_h2h_url, rival_a_id_match.group(1), rival_a_name
    return None, None, None

@st.cache_data(ttl=3600)
def get_rival_b_for_original_h2h_of(main_match_id: int):
    soup_h2h_page = fetch_soup_requests_of(f"/match/h2h-{main_match_id}") 
    if not soup_h2h_page: return None, None, None
    table = soup_h2h_page.find("table", id="table_v2") 
    if not table: return None, None, None
    for row in table.find_all("tr", id=re.compile(r"tr2_\d+")):
        if row.get("vs") == "1": 
            match_id_of_rival_b_game = row.get("index") 
            if not match_id_of_rival_b_game: continue
            onclicks = row.find_all("a", onclick=True) 
            if len(onclicks) > 0 and onclicks[0].get("onclick"): 
                rival_tag = onclicks[0]; rival_b_id_match = re.search(r"team\((\d+)\)", rival_tag.get("onclick", ""))
                rival_b_name = rival_tag.text.strip() 
                if rival_b_id_match and rival_b_name: return match_id_of_rival_b_game, rival_b_id_match.group(1), rival_b_name
    return None, None, None

@st.cache_resource 
def get_selenium_driver_of():
    options = ChromeOptions(); options.add_argument("--headless"); options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage"); options.add_argument("--disable-gpu")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36")
    options.add_argument('--blink-settings=imagesEnabled=false'); options.add_argument("--window-size=1920,1080")
    try: return webdriver.Chrome(options=options)
    except WebDriverException as e: st.error(f"Error inicializando Selenium driver (OF): {e}"); return None

# MODIFICADA: Ahora devuelve el 'match_id_for_stats'
def get_h2h_details_for_original_logic_of(driver_instance, key_match_id_for_h2h_url, rival_a_id, rival_b_id, rival_a_name="Rival A", rival_b_name="Rival B"):
    if not driver_instance: return {"status": "error", "resultado": "N/A (Driver no disponible H2H OF)"}
    if not key_match_id_for_h2h_url or not rival_a_id or not rival_b_id: return {"status": "error", "resultado": f"N/A (IDs incompletos para H2H {rival_a_name} vs {rival_b_name})"}
    url_to_visit = f"{BASE_URL_OF}/match/h2h-{key_match_id_for_h2h_url}"
    try:
        driver_instance.get(url_to_visit)
        WebDriverWait(driver_instance, SELENIUM_TIMEOUT_SECONDS_OF, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.presence_of_element_located((By.ID, "table_v2")))
        time.sleep(0.7); soup_selenium = BeautifulSoup(driver_instance.page_source, "html.parser")
    except TimeoutException: return {"status": "error", "resultado": f"N/A (Timeout esperando table_v2 en {url_to_visit})"}
    except Exception as e: return {"status": "error", "resultado": f"N/A (Error Selenium en {url_to_visit}: {type(e).__name__})"}
    if not soup_selenium: return {"status": "error", "resultado": f"N/A (Fallo soup Selenium H2H Original OF en {url_to_visit})"}
    table_to_search_h2h = soup_selenium.find("table", id="table_v2") 
    if not table_to_search_h2h: return {"status": "error", "resultado": f"N/A (Tabla v2 para H2H no encontrada en {url_to_visit})"}
    for row in table_to_search_h2h.find_all("tr", id=re.compile(r"tr2_\d+")): 
        links = row.find_all("a", onclick=True); 
        if len(links) < 2: continue
        h2h_row_home_id_m = re.search(r"team\((\d+)\)", links[0].get("onclick", "")); h2h_row_away_id_m = re.search(r"team\((\d+)\)", links[1].get("onclick", ""))
        if not h2h_row_home_id_m or not h2h_row_away_id_m: continue
        h2h_row_home_id = h2h_row_home_id_m.group(1); h2h_row_away_id = h2h_row_away_id_m.group(1)
        if {h2h_row_home_id, h2h_row_away_id} == {str(rival_a_id), str(rival_b_id)}:
            score_span = row.find("span", class_="fscore_2") 
            if not score_span or not score_span.text or "-" not in score_span.text: continue
            score_val = score_span.text.strip().split("(")[0].strip(); g_h, g_a = score_val.split("-", 1)
            tds = row.find_all("td"); handicap_raw = "N/A"; HANDICAP_TD_IDX = 11 
            if len(tds) > HANDICAP_TD_IDX:
                cell = tds[HANDICAP_TD_IDX]; d_o = cell.get("data-o") 
                handicap_raw = d_o.strip() if d_o and d_o.strip() not in ["", "-"] else (cell.text.strip() if cell.text.strip() not in ["", "-"] else "N/A")
            rol_a_in_this_h2h = "H" if h2h_row_home_id == str(rival_a_id) else "A"
            
            # AÑADIDO: match_id_for_stats
            match_id_for_stats = row.get("index") 

            return {"status": "found", "goles_home": g_h.strip(), "goles_away": g_a.strip(), "handicap": handicap_raw, 
                    "rol_rival_a": rol_a_in_this_h2h, "h2h_home_team_name": links[0].text.strip(), 
                    "h2h_away_team_name": links[1].text.strip(), 
                    "match_id_for_stats": match_id_for_stats} # <--- MODIFICADO
    return {"status": "not_found", "resultado": f"H2H directo no encontrado para {rival_a_name} vs {rival_b_name} en historial (table_v2) de la página de ref. ({key_match_id_for_h2h_url}).", "match_id_for_stats": None}

def get_team_league_info_from_script_of(soup):
    home_id, away_id, league_id, home_name, away_name, league_name = (None,)*3 + ("N/A",)*3
    script_tag = soup.find("script", string=re.compile(r"var _matchInfo ="))
    if script_tag and script_tag.string:
        script_content = script_tag.string
        h_id_m = re.search(r"hId:\s*parseInt\('(\d+)'\)", script_content); g_id_m = re.search(r"gId:\s*parseInt\('(\d+)'\)", script_content)
        sclass_id_m = re.search(r"sclassId:\s*parseInt\('(\d+)'\)", script_content); h_name_m = re.search(r"hName:\s*'([^']*)'", script_content)
        g_name_m = re.search(r"gName:\s*'([^']*)'", script_content); l_name_m = re.search(r"lName:\s*'([^']*)'", script_content)
        if h_id_m: home_id = h_id_m.group(1)
        if g_id_m: away_id = g_id_m.group(1)
        if sclass_id_m: league_id = sclass_id_m.group(1)
        if h_name_m: home_name = h_name_m.group(1).replace("\\'", "'")
        if g_name_m: away_name = g_name_m.group(1).replace("\\'", "'")
        if l_name_m: league_name = l_name_m.group(1).replace("\\'", "'")
    return home_id, away_id, league_id, home_name, away_name, league_name

def click_element_robust_of(driver, by, value, timeout=7):
    try:
        element = WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.presence_of_element_located((by, value)))
        WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.visibility_of(element))
        driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'center'});", element); time.sleep(0.3)
        try: WebDriverWait(driver, 2, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.element_to_be_clickable((by, value))).click()
        except (ElementClickInterceptedException, TimeoutException): driver.execute_script("arguments[0].click();", element)
        return True
    except Exception: return False

# MODIFICADA: Ahora devuelve el 'match_id_for_stats'
def extract_last_match_in_league_of(driver, table_css_id_str, main_team_name_in_table, league_id_filter_value, home_or_away_filter_css_selector, is_home_game_filter):
    try:
        if league_id_filter_value:
            league_checkbox_selector = f"input#checkboxleague{table_css_id_str[-1]}[value='{league_id_filter_value}']"
            click_element_robust_of(driver, By.CSS_SELECTOR, league_checkbox_selector); time.sleep(1.0)
        click_element_robust_of(driver, By.CSS_SELECTOR, home_or_away_filter_css_selector); time.sleep(1.0)
        page_source_updated = driver.page_source; soup_updated = BeautifulSoup(page_source_updated, "html.parser")
        table = soup_updated.find("table", id=table_css_id_str)
        if not table: return None
        count_visible_rows = 0
        for row in table.find_all("tr", id=re.compile(rf"tr{table_css_id_str[-1]}_\d+")):
            if row.get("style") and "display:none" in row.get("style","").lower(): continue
            count_visible_rows +=1
            if count_visible_rows > 10: break 
            if league_id_filter_value and row.get("name") != str(league_id_filter_value): continue
            tds = row.find_all("td"); 
            if len(tds) < 14: continue
            home_team_row_el = tds[2].find("a"); away_team_row_el = tds[4].find("a")
            if not home_team_row_el or not away_team_row_el: continue
            home_team_row_name = home_team_row_el.text.strip(); away_team_row_name = away_team_row_el.text.strip()
            team_is_home_in_row = main_team_name_in_table.lower() == home_team_row_name.lower()
            team_is_away_in_row = main_team_name_in_table.lower() == away_team_row_name.lower()
            if (is_home_game_filter and team_is_home_in_row) or (not is_home_game_filter and team_is_away_in_row):
                date_span = tds[1].find("span", {"name": "timeData"}); date = date_span.text.strip() if date_span else "N/A"
                score_class_re = re.compile(r"fscore_"); score_span = tds[3].find("span", class_=score_class_re); score = score_span.text.strip() if score_span else "N/A"
                handicap_cell = tds[11]; handicap_raw = handicap_cell.get("data-o", handicap_cell.text.strip()) 
                if not handicap_raw or handicap_raw.strip() == "-": handicap_raw = "N/A"
                else: handicap_raw = handicap_raw.strip()
                
                # AÑADIDO: match_id_for_stats
                match_id_for_stats = row.get("index")

                return {"date": date, "home_team": home_team_row_name, "away_team": away_team_row_name,
                        "score": score, "handicap_line_raw": handicap_raw, 
                        "match_id_for_stats": match_id_for_stats} # <--- MODIFICADO
        return None
    except Exception: return None

def get_main_match_odds_selenium_of(driver):
    odds_info = {"ah_home_cuota": "N/A", "ah_linea_raw": "N/A", "ah_away_cuota": "N/A", "goals_over_cuota": "N/A", "goals_linea_raw": "N/A", "goals_under_cuota": "N/A"}
    try:
        live_compare_div = WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS_OF, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.presence_of_element_located((By.ID, "liveCompareDiv")))
        bet365_row_selector = "tr#tr_o_1_8[name='earlyOdds']"; bet365_row_selector_alt = "tr#tr_o_1_31[name='earlyOdds']"
        table_odds = live_compare_div.find_element(By.XPATH, ".//table[contains(@class, 'team-table-other')]")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", table_odds); time.sleep(0.5)
        bet365_early_odds_row = None
        try: bet365_early_odds_row = WebDriverWait(driver, 5, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.visibility_of_element_located((By.CSS_SELECTOR, bet365_row_selector)))
        except TimeoutException: 
            try: bet365_early_odds_row = WebDriverWait(driver, 3, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.visibility_of_element_located((By.CSS_SELECTOR, bet365_row_selector_alt)))
            except TimeoutException: return odds_info
        tds = bet365_early_odds_row.find_elements(By.TAG_NAME, "td")
        if len(tds) >= 11:
            odds_info["ah_home_cuota"] = tds[2].get_attribute("data-o") or tds[2].text.strip() or "N/A"
            odds_info["ah_linea_raw"] = tds[3].get_attribute("data-o") or tds[3].text.strip() or "N/A" 
            odds_info["ah_away_cuota"] = tds[4].get_attribute("data-o") or tds[4].text.strip() or "N/A"
            odds_info["goals_over_cuota"] = tds[8].get_attribute("data-o") or tds[8].text.strip() or "N/A"
            odds_info["goals_linea_raw"] = tds[9].get_attribute("data-o") or tds[9].text.strip() or "N/A" 
            odds_info["goals_under_cuota"] = tds[10].get_attribute("data-o") or tds[10].text.strip() or "N/A"
    except Exception: pass
    return odds_info

def extract_standings_data_from_h2h_page_of(h2h_soup, target_team_name_exact):
    data = {"name": target_team_name_exact, "ranking": "N/A", "total_pj": "N/A", "total_v": "N/A", "total_e": "N/A", "total_d": "N/A", "total_gf": "N/A", "total_gc": "N/A", "specific_pj": "N/A", "specific_v": "N/A", "specific_e": "N/A", "specific_d": "N/A", "specific_gf": "N/A", "specific_gc": "N/A", "specific_type": "N/A" }
    if not h2h_soup: return data
    standings_section = h2h_soup.find("div", id="porletP4"); 
    if not standings_section: return data
    team_table_soup = None; is_home_team_table_type = False
    home_div_standings = standings_section.find("div", class_="home-div")
    if home_div_standings:
        home_table_header = home_div_standings.find("tr", class_="team-home")
        if home_table_header and target_team_name_exact and target_team_name_exact.lower() in home_table_header.get_text().lower(): 
            team_table_soup = home_div_standings.find("table", class_="team-table-home"); is_home_team_table_type = True
            data["specific_type"] = home_div_standings.find("td", class_="bg1").text.strip() if home_div_standings.find("td", class_="bg1") else "En Casa"
    if not team_table_soup:
        guest_div_standings = standings_section.find("div", class_="guest-div")
        if guest_div_standings:
            guest_table_header = guest_div_standings.find("tr", class_="team-guest")
            if guest_table_header and target_team_name_exact and target_team_name_exact.lower() in guest_table_header.get_text().lower(): 
                team_table_soup = guest_div_standings.find("table", class_="team-table-guest"); is_home_team_table_type = False
                data["specific_type"] = guest_div_standings.find("td", class_="bg1").text.strip() if guest_div_standings.find("td", class_="bg1") else "Fuera"
    if not team_table_soup: return data
    header_row_found = team_table_soup.find("tr", class_=re.compile(r"team-(home|guest)")) 
    if header_row_found:
        link = header_row_found.find("a")
        if link:
            full_text = link.get_text(separator=" ", strip=True); name_match = re.search(r"]\s*(.*)", full_text); rank_match = re.search(r"\[(?:[^\]]+-)?(\d+)\]", full_text)
            if name_match: data["name"] = name_match.group(1).strip()
            if rank_match: data["ranking"] = rank_match.group(1)
        else: 
            header_text_no_link = header_row_found.get_text(separator=" ", strip=True); name_match_nl = re.search(r"]\s*(.*)", header_text_no_link)
            if name_match_nl: data["name"] = name_match_nl.group(1).strip()
            rank_match_nl = re.search(r"\[(?:[^\]]+-)?(\d+)\]", header_text_no_link)
            if rank_match_nl: data["ranking"] = rank_match_nl.group(1)
    ft_rows = []; current_section = None
    for row in team_table_soup.find_all("tr", align="center"): 
        th_cell = row.find("th");
        if th_cell:
            if "FT" in th_cell.get_text(strip=True): current_section = "FT"
            elif "HT" in th_cell.get_text(strip=True): break 
        if current_section == "FT":
            cells = row.find_all("td")
            if cells and len(cells) > 0 and cells[0].get_text(strip=True) in ["Total", "Home", "Away"]: ft_rows.append(cells)
    for cells in ft_rows:
        if len(cells) > 8: 
            row_type_text = cells[0].get_text(strip=True)
            pj, v, e, d, gf, gc = (cells[i].get_text(strip=True) for i in range(1, 7))
            pj=pj if pj else "N/A"; v=v if v else "N/A"; e=e if e else "N/A"; d=d if d else "N/A"; gf=gf if gf else "N/A"; gc=gc if gc else "N/A"
            if row_type_text=="Total": data["total_pj"],data["total_v"],data["total_e"],data["total_d"],data["total_gf"],data["total_gc"]=pj,v,e,d,gf,gc
            elif row_type_text=="Home" and is_home_team_table_type: data["specific_pj"],data["specific_v"],data["specific_e"],data["specific_d"],data["specific_gf"],data["specific_gc"]=pj,v,e,d,gf,gc
            elif row_type_text=="Away" and not is_home_team_table_type: data["specific_pj"],data["specific_v"],data["specific_e"],data["specific_d"],data["specific_gf"],data["specific_gc"]=pj,v,e,d,gf,gc
    return data

def extract_final_score_of(soup):
    try:
        score_divs = soup.select('#mScore .end .score') 
        if len(score_divs) == 2:
            hs = score_divs[0].text.strip(); aws = score_divs[1].text.strip()
            if hs.isdigit() and aws.isdigit(): return f"{hs}*{aws}", f"{hs}-{aws}"
    except Exception: pass
    return '?*?', "?-?"

# MODIFICADA: Ahora devuelve también los IDs de los partidos H2H encontrados
def extract_h2h_data_of(soup, main_home_team_name, main_away_team_name, current_league_id):
    ah1, res1, res1_raw, h2h1_match_id = '-', '?*?', '?-?', None
    ah6, res6, res6_raw, h2h6_match_id = '-', '?*?', '?-?', None
    h2h_table = soup.find("table", id="table_v3")
    if not h2h_table: return ah1, res1, res1_raw, h2h1_match_id, ah6, res6, res6_raw, h2h6_match_id
    filtered_h2h_list = []
    if not main_home_team_name or not main_away_team_name:
        return ah1, res1, res1_raw, h2h1_match_id, ah6, res6, res6_raw, h2h6_match_id

    for row_h2h in h2h_table.find_all("tr", id=re.compile(r"tr3_\d+")):
        # get_match_details_from_row_of ahora devuelve match_id_for_stats
        details = get_match_details_from_row_of(row_h2h, score_class_selector='fscore_3', source_table_type='h2h')
        if not details: continue
        if current_league_id and details.get('league_id_hist') and details.get('league_id_hist') != str(current_league_id): continue
        filtered_h2h_list.append(details)
    if not filtered_h2h_list: return ah1, res1, res1_raw, h2h1_match_id, ah6, res6, res6_raw, h2h6_match_id
    
    h2h_general_match = filtered_h2h_list[0]
    ah6 = h2h_general_match.get('ahLine', '-') 
    res6 = h2h_general_match.get('score', '?*?'); res6_raw = h2h_general_match.get('score_raw', '?-?')
    h2h6_match_id = h2h_general_match.get('match_id_for_stats') # <--- AÑADIDO: ID para el H2H general
    
    h2h_local_specific_match = None
    for d_h2h in filtered_h2h_list:
        if d_h2h.get('home','').lower() == main_home_team_name.lower() and \
           d_h2h.get('away','').lower() == main_away_team_name.lower():
            h2h_local_specific_match = d_h2h; break
    if h2h_local_specific_match:
        ah1 = h2h_local_specific_match.get('ahLine', '-') 
        res1 = h2h_local_specific_match.get('score', '?*?'); res1_raw = h2h_local_specific_match.get('score_raw', '?-?')
        h2h1_match_id = h2h_local_specific_match.get('match_id_for_stats') # <--- AÑADIDO: ID para el H2H específico
    
    return ah1, res1, res1_raw, h2h1_match_id, ah6, res6, res6_raw, h2h6_match_id # <--- MODIFICADO

def extract_comparative_match_of(soup_for_team_history, table_id_of_team_to_search, team_name_to_find_match_for, opponent_name_to_search, current_league_id, is_home_table):
    if not opponent_name_to_search or opponent_name_to_search == "N/A" or not team_name_to_find_match_for:
        return "-", None # <--- MODIFICADO: Añadido retorno para match_id
    table = soup_for_team_history.find("table", id=table_id_of_team_to_search)
    if not table: return "-", None # <--- MODIFICADO
    score_class_selector = 'fscore_1' if is_home_table else 'fscore_2'
    for row in table.find_all("tr", id=re.compile(rf"tr{table_id_of_team_to_search[-1]}_\d+")):
        # get_match_details_from_row_of ahora devuelve match_id_for_stats
        details = get_match_details_from_row_of(row, score_class_selector=score_class_selector, source_table_type='hist')
        if not details: continue
        if current_league_id and details.get('league_id_hist') and details.get('league_id_hist') != str(current_league_id): continue
        home_hist = details.get('home','').lower(); away_hist = details.get('away','').lower()
        team_main_lower = team_name_to_find_match_for.lower(); opponent_lower = opponent_name_to_search.lower()
        if (team_main_lower == home_hist and opponent_lower == away_hist) or \
           (team_main_lower == away_hist and opponent_lower == home_hist):
            score = details.get('score', '?*?')
            ah_line_extracted = details.get('ahLine', '-')
            localia = 'H' if team_main_lower == home_hist else 'A'
            match_id_for_stats = details.get('match_id_for_stats') # <--- AÑADIDO: Obtener el ID del partido comparado
            return f"{score}/{ah_line_extracted} {localia}".strip(), match_id_for_stats # <--- MODIFICADO: Retorna ID
    return "-", None # <--- MODIFICADO

# --- STREAMLIT APP UI (Función principal) ---
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

    st.sidebar.image("https://raw.githubusercontent.com/streamlit/docs/main/public/images/brand/streamlit-logo-secondary-colormark-darktext.svg", width=200)
    st.sidebar.title("⚙️ Configuración del Partido (OF)")
    main_match_id_str_input_of = st.sidebar.text_input(
        "🆔 ID Partido Principal:", 
        value="2696131", 
        help="Pega el ID numérico del partido que deseas analizar.", 
        key="other_feature_match_id_input"
    )
    analizar_button_of = st.sidebar.button("🚀 Analizar Partido (OF)", type="primary", use_container_width=True, key="other_feature_analizar_button")

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
                soup_main_h2h_page_of = fetch_soup_requests_of(main_page_url_h2h_view_of)
            if not soup_main_h2h_page_of:
                st.error(f"❌ No se pudo obtener la página H2H principal para el ID {main_match_id_to_process_of}. Verifica la conexión o el ID."); st.stop()

            mp_home_id_of, mp_away_id_of, mp_league_id_of, mp_home_name_from_script, mp_away_name_from_script, mp_league_name_of = get_team_league_info_from_script_of(soup_main_h2h_page_of)
            
            with st.spinner("📊 Extrayendo clasificaciones principales de los equipos..."):
                home_team_main_standings = extract_standings_data_from_h2h_page_of(soup_main_h2h_page_of, mp_home_name_from_script)
                away_team_main_standings = extract_standings_data_from_h2h_page_of(soup_main_h2h_page_of, mp_away_name_from_script)
            
            display_home_name = home_team_main_standings.get("name", mp_home_name_from_script) if home_team_main_standings.get("name", "N/A") != "N/A" else mp_home_name_from_script
            display_away_name = away_team_main_standings.get("name", mp_away_name_from_script) if away_team_main_standings.get("name", "N/A") != "N/A" else mp_away_name_from_script

            st.markdown(f"<p class='main-title'>📊 Análisis Avanzado de Partido (OF) ⚽</p>", unsafe_allow_html=True)
            st.markdown(f"<p class='sub-title'>🆚 <span class='home-color'>{display_home_name or 'Equipo Local'}</span> vs <span class='away-color'>{display_away_name or 'Equipo Visitante'}</span></p>", unsafe_allow_html=True)
            st.caption(f"🏆 **Liga:** {mp_league_name_of or placeholder_nodata} (ID Liga: {mp_league_id_of or placeholder_nodata}) | 🆔 **Partido ID:** <span class='data-highlight'>{main_match_id_to_process_of}</span>", unsafe_allow_html=True)
            st.markdown("---")

            st.markdown("<h2 class='section-header'>📈 Clasificación General y Específica</h2>", unsafe_allow_html=True)
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
                st.markdown("</div>", unsafe_allow_html=True)
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
                st.markdown("</div>", unsafe_allow_html=True)
            
            key_match_id_for_rival_a_h2h, rival_a_id_orig_col3, rival_a_name_orig_col3 = get_rival_a_for_original_h2h_of(main_match_id_to_process_of)
            match_id_rival_b_game_ref, rival_b_id_orig_col3, rival_b_name_orig_col3 = get_rival_b_for_original_h2h_of(main_match_id_to_process_of)
            rival_a_standings = {}; rival_b_standings = {}
            with st.spinner("📊 Extrayendo clasificaciones de oponentes indirectos (Col3)..."):
                if rival_a_name_orig_col3 and rival_a_name_orig_col3 != "N/A" and key_match_id_for_rival_a_h2h:
                    soup_rival_a_h2h_page = fetch_soup_requests_of(f"/match/h2h-{key_match_id_for_rival_a_h2h}")
                    if soup_rival_a_h2h_page: rival_a_standings = extract_standings_data_from_h2h_page_of(soup_rival_a_h2h_page, rival_a_name_orig_col3)
                if rival_b_name_orig_col3 and rival_b_name_orig_col3 != "N/A" and match_id_rival_b_game_ref:
                    soup_rival_b_h2h_page = fetch_soup_requests_of(f"/match/h2h-{match_id_rival_b_game_ref}")
                    if soup_rival_b_h2h_page: rival_b_standings = extract_standings_data_from_h2h_page_of(soup_rival_b_h2h_page, rival_b_name_orig_col3)
            
            main_match_odds_data_of = {}; last_home_match_in_league_of = None; last_away_match_in_league_of = None
            h2h_col3_extra_stats_df = None # Nuevo para las stats del H2H de Col3
            h2h1_extra_stats_df = None # Nuevo para las stats del H2H V
            h2h6_extra_stats_df = None # Nuevo para las stats del H2H G
            
            driver_actual_of = st.session_state.driver_other_feature; driver_of_needs_init = False
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
                with st.spinner("🚘 Inicializando WebDriver para datos dinámicos (puede tardar)..."): driver_actual_of = get_selenium_driver_of()
                st.session_state.driver_other_feature = driver_actual_of

            if driver_actual_of:
                try:
                    with st.spinner("⚙️ Accediendo a datos dinámicos con Selenium (cuotas, últimos partidos, stats detalladas)..."):
                        driver_actual_of.get(f"{BASE_URL_OF}{main_page_url_h2h_view_of}") 
                        WebDriverWait(driver_actual_of, SELENIUM_TIMEOUT_SECONDS_OF).until(EC.presence_of_element_located((By.ID, "table_v1"))) 
                        time.sleep(0.8) # Pequeña pausa para asegurar carga completa de JS
                        main_match_odds_data_of = get_main_match_odds_selenium_of(driver_actual_of)
                        
                        if mp_home_id_of and mp_league_id_of and display_home_name and display_home_name != "N/A":
                             last_home_match_in_league_of = extract_last_match_in_league_of(driver_actual_of, "table_v1", display_home_name, mp_league_id_of, "input#cb_sos1[value='1']", is_home_game_filter=True)
                             if last_home_match_in_league_of and last_home_match_in_league_of.get('match_id_for_stats'):
                                 last_home_match_in_league_of['extra_stats'] = _get_match_stats_data(last_home_match_in_league_of['match_id_for_stats'])
                             else:
                                 last_home_match_in_league_of['extra_stats'] = pd.DataFrame() # DataFrame vacío
                        if mp_away_id_of and mp_league_id_of and display_away_name and display_away_name != "N/A":
                            last_away_match_in_league_of = extract_last_match_in_league_of(driver_actual_of, "table_v2", display_away_name, mp_league_id_of, "input#cb_sos2[value='2']", is_home_game_filter=False)
                            if last_away_match_in_league_of and last_away_match_in_league_of.get('match_id_for_stats'):
                                last_away_match_in_league_of['extra_stats'] = _get_match_stats_data(last_away_match_in_league_of['match_id_for_stats'])
                            else:
                                last_away_match_in_league_of['extra_stats'] = pd.DataFrame() # DataFrame vacío

                        # H2H Rivales (Col3)
                        details_h2h_col3_of = {"status": "error", "resultado": placeholder_nodata, "match_id_for_stats": None}
                        if key_match_id_for_rival_a_h2h and rival_a_id_orig_col3 and rival_b_id_orig_col3 and driver_actual_of: 
                            details_h2h_col3_of = get_h2h_details_for_original_logic_of(driver_actual_of, key_match_id_for_rival_a_h2h, rival_a_id_orig_col3, rival_b_id_orig_col3, rival_a_col3_name_display, rival_b_col3_name_display)
                            if details_h2h_col3_of.get("status") == "found" and details_h2h_col3_of.get('match_id_for_stats'):
                                h2h_col3_extra_stats_df = _get_match_stats_data(details_h2h_col3_of['match_id_for_stats'])
                            else:
                                h2h_col3_extra_stats_df = pd.DataFrame()

                except Exception as e_main_sel_of: st.error(f"❗ Error durante la extracción con Selenium: {type(e_main_sel_of).__name__}. Algunos datos podrían faltar.")
            else: st.warning("❗ WebDriver no disponible. No se podrán obtener cuotas iniciales ni últimos partidos filtrados por liga/localía ni estadísticas detalladas de esos partidos.")

            # --- Población de col_data ---
            col_data = { 
                "AH_H2H_V": "-", "AH_Act": "?", "Res_H2H_V": "?*?", "AH_L_H": "-", "Res_L_H": "?*?", 
                "AH_V_A": "-", "Res_V_A": "?*?", "AH_H2H_G": "-", "Res_H2H_G": "?*?", "L_vs_UV_A": "-", 
                "V_vs_UL_H": "-", "Stats_L": f"Estadísticas para {display_home_name or 'Local'}: N/A", 
                "Stats_V": f"Estadísticas para {display_away_name or 'Visitante'}: N/A", "Fin": "?*?", 
                "G_i": "?", "League": mp_league_name_of or placeholder_nodata, "match_id": str(main_match_id_to_process_of)
            }
            raw_ah_act = main_match_odds_data_of.get('ah_linea_raw', '?'); col_data["AH_Act"] = format_ah_as_decimal_string_of(raw_ah_act)
            raw_g_i = main_match_odds_data_of.get('goals_linea_raw', '?'); col_data["G_i"] = format_ah_as_decimal_string_of(raw_g_i)
            col_data["Fin"], _ = extract_final_score_of(soup_main_h2h_page_of)
            
            if home_team_main_standings.get("name", "N/A") != "N/A" and display_home_name != "N/A":
                hst = home_team_main_standings
                col_data["Stats_L"] = (f"🏅Rk:{hst.get('ranking',placeholder_nodata)} | 🏠{hst.get('specific_type','En Casa')}\n"
                                       f"🌍Total: {hst.get('total_pj','0')}PJ | {hst.get('total_v','0')}V/{hst.get('total_e','0')}E/{hst.get('total_d','0')}D | {hst.get('total_gf','0')}GF-{hst.get('total_gc','0')}GC\n"
                                       f"🏠Local: {hst.get('specific_pj','0')}PJ | {hst.get('specific_v','0')}V/{hst.get('specific_e','0')}E/{hst.get('specific_d','0')}D | {hst.get('specific_gf','0')}GF-{hst.get('specific_gc','0')}GC")
            if away_team_main_standings.get("name", "N/A") != "N/A" and display_away_name != "N/A":
                ast = away_team_main_standings
                col_data["Stats_V"] = (f"🏅Rk:{ast.get('ranking',placeholder_nodata)} | ✈️{ast.get('specific_type','Fuera')}\n"
                                       f"🌍Total: {ast.get('total_pj','0')}PJ | {ast.get('total_v','0')}V/{ast.get('total_e','0')}E/{ast.get('total_d','0')}D | {ast.get('total_gf','0')}GF-{ast.get('total_gc','0')}GC\n"
                                       f"✈️Visitante: {ast.get('specific_pj','0')}PJ | {ast.get('specific_v','0')}V/{ast.get('specific_e','0')}E/{ast.get('specific_d','0')}D | {ast.get('specific_gf','0')}GF-{ast.get('specific_gc','0')}GC")
            if last_home_match_in_league_of:
                col_data["AH_L_H"] = format_ah_as_decimal_string_of(last_home_match_in_league_of.get('handicap_line_raw', '-'))
                col_data["Res_L_H"] = last_home_match_in_league_of.get('score', '?*?').replace('-', '*')
            if last_away_match_in_league_of:
                col_data["AH_V_A"] = format_ah_as_decimal_string_of(last_away_match_in_league_of.get('handicap_line_raw', '-'))
                col_data["Res_V_A"] = last_away_match_in_league_of.get('score', '?*?').replace('-', '*')
            
            # Recuperamos los IDs de los partidos H2H
            ah1_val, res1_val, _, h2h1_match_id, ah6_val, res6_val, _, h2h6_match_id = extract_h2h_data_of(soup_main_h2h_page_of, display_home_name, display_away_name, mp_league_id_of)
            col_data["AH_H2H_V"] = ah1_val; col_data["Res_H2H_V"] = res1_val
            col_data["AH_H2H_G"] = ah6_val; col_data["Res_H2H_G"] = res6_val

            # Obtener estadísticas detalladas para los H2H directos
            if h2h1_match_id:
                h2h1_extra_stats_df = _get_match_stats_data(h2h1_match_id)
            if h2h6_match_id:
                h2h6_extra_stats_df = _get_match_stats_data(h2h6_match_id)

            last_away_opponent_for_home_hist = last_away_match_in_league_of.get('home_team') if last_away_match_in_league_of and display_home_name else None
            comp_str_l_val, comp_str_l_id = "-", None
            if last_away_opponent_for_home_hist and display_home_name != "N/A":
                comp_str_l_val, comp_str_l_id = extract_comparative_match_of(soup_main_h2h_page_of, "table_v1", display_home_name, last_away_opponent_for_home_hist, mp_league_id_of, is_home_table=True)
            col_data["L_vs_UV_A"] = comp_str_l_val
            comp_l_extra_stats_df = None
            if comp_str_l_id:
                comp_l_extra_stats_df = _get_match_stats_data(comp_str_l_id)
            
            last_home_opponent_for_away_hist = last_home_match_in_league_of.get('away_team') if last_home_match_in_league_of and display_away_name else None
            comp_str_v_val, comp_str_v_id = "-", None
            if last_home_opponent_for_away_hist and display_away_name != "N/A":
                comp_str_v_val, comp_str_v_id = extract_comparative_match_of(soup_main_h2h_page_of, "table_v2", display_away_name, last_home_opponent_for_away_hist, mp_league_id_of, is_home_table=False)
            col_data["V_vs_UL_H"] = comp_str_v_val
            comp_v_extra_stats_df = None
            if comp_str_v_id:
                comp_v_extra_stats_df = _get_match_stats_data(comp_str_v_id)
            # --- Fin población col_data ---

            st.markdown("---")
            st.markdown("<h2 class='section-header'>🎯 Análisis Detallado del Partido</h2>", unsafe_allow_html=True)
            
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
                st.markdown("</div>", unsafe_allow_html=True)

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
                    # AÑADIDO: Mostrar estadísticas detalladas
                    if res.get('extra_stats') is not None and not res['extra_stats'].empty:
                        st.markdown("<h5 class='card-subtitle'>Estadísticas de Ataque</h5>", unsafe_allow_html=True)
                        st.dataframe(res['extra_stats'].set_index('Estadística'), use_container_width=True)
                    else:
                        st.info("Estadísticas de ataque no disponibles para este partido.")
                else: st.info(f"No se encontró último partido en casa para {display_home_name or 'Local'} en esta liga.")
                st.markdown("</div>", unsafe_allow_html=True)
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
                    # AÑADIDO: Mostrar estadísticas detalladas
                    if res.get('extra_stats') is not None and not res['extra_stats'].empty:
                        st.markdown("<h5 class='card-subtitle'>Estadísticas de Ataque</h5>", unsafe_allow_html=True)
                        st.dataframe(res['extra_stats'].set_index('Estadística'), use_container_width=True)
                    else:
                        st.info("Estadísticas de ataque no disponibles para este partido.")
                else: st.info(f"No se encontró último partido fuera para {display_away_name or 'Visitante'} en esta liga.")
                st.markdown("</div>", unsafe_allow_html=True)
            with rp_col3:
 
                st.markdown(f"<h4 class='card-title'>🆚 H2H Rivales (Col3)</h4>", unsafe_allow_html=True)
                rival_a_col3_name_display = rival_a_name_orig_col3 if rival_a_name_orig_col3 and rival_a_name_orig_col3 != "N/A" else (rival_a_id_orig_col3 or "Rival A")
                rival_b_col3_name_display = rival_b_name_orig_col3 if rival_b_name_orig_col3 and rival_b_name_orig_col3 != "N/A" else (rival_b_id_orig_col3 or "Rival B")
                
                # detalles_h2h_col3_of ya se obtuvo y si se pudo, h2h_col3_extra_stats_df también
                if details_h2h_col3_of.get("status") == "found":
                    res_h2h = details_h2h_col3_of
                    h2h_home_name = res_h2h.get('h2h_home_team_name', 'Equipo Local H2H')
                    h2h_away_name = res_h2h.get('h2h_away_team_name', 'Equipo Visitante H2H')
                    st.markdown(f"<span class='home-color'>{h2h_home_name}</span> <span class='score-value'>{res_h2h.get('goles_home', '?')}:{res_h2h.get('goles_away', '?')}</span> <span class='away-color'>{h2h_away_name}</span>", unsafe_allow_html=True)
                    formatted_ah_h2h = format_ah_as_decimal_string_of(res_h2h.get('handicap','-'))
                    st.markdown(f"**AH:** <span class='ah-value'>{formatted_ah_h2h if formatted_ah_h2h != '-' else placeholder_nodata}</span>", unsafe_allow_html=True)
                    st.caption(f"Enfrentamiento directo entre <span class='home-color'>{rival_a_col3_name_display}</span> y <span class='away-color'>{rival_b_col3_name_display}</span>.", unsafe_allow_html=True)
                    # AÑADIDO: Mostrar estadísticas detalladas
                    if h2h_col3_extra_stats_df is not None and not h2h_col3_extra_stats_df.empty:
                        st.markdown("<h5 class='card-subtitle'>Estadísticas de Ataque</h5>", unsafe_allow_html=True)
                        st.dataframe(h2h_col3_extra_stats_df.set_index('Estadística'), use_container_width=True)
                    else:
                        st.info("Estadísticas de ataque no disponibles para este partido.")
                else: st.info(details_h2h_col3_of.get('resultado', f"H2H entre {rival_a_col3_name_display} y {rival_b_col3_name_display} no encontrado."))
                st.markdown("</div>", unsafe_allow_html=True)
            
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
                st.markdown("</div>", unsafe_allow_html=True)

            st.markdown("---")
            st.markdown("<h2 class='section-header'>📊 Datos Clave Adicionales</h2>", unsafe_allow_html=True)
            with st.expander("🔰 Hándicaps y Resultados Clave (Estilo Script Original)", expanded=True):
 
                st.markdown("<h4 class='card-subtitle'>Enfrentamientos Directos (H2H)</h4>", unsafe_allow_html=True)
                h2h_cols1, h2h_cols2, h2h_cols3 = st.columns(3)
                h2h_cols1.metric("AH H2H (Local en Casa)", col_data["AH_H2H_V"], help="Hándicap Asiático del último H2H con el equipo local actual jugando en casa.")
                h2h_cols2.metric("Res H2H (Local en Casa)", col_data["Res_H2H_V"].replace("*",":"), help="Resultado del último H2H con el equipo local actual jugando en casa.")
                h2h_cols3.metric("AH Actual Partido", col_data["AH_Act"], help="Hándicap Asiático inicial (Bet365) para este partido.")

                # AÑADIDO: Estadísticas detalladas para H2H (Local en Casa)
                if h2h1_extra_stats_df is not None and not h2h1_extra_stats_df.empty:
                    st.markdown("<h5 class='card-subtitle'>Estadísticas de Ataque (H2H Específico)</h5>", unsafe_allow_html=True)
                    st.dataframe(h2h1_extra_stats_df.set_index('Estadística'), use_container_width=True)
                else:
                    st.info("Estadísticas de ataque no disponibles para este H2H específico.")

                h2h_g_cols1, h2h_g_cols2 = st.columns(2)
                h2h_g_cols1.metric("AH H2H (General)", col_data["AH_H2H_G"], help="Hándicap Asiático del H2H más reciente entre ambos equipos, sin importar localía.")
                h2h_g_cols2.metric("Res H2H (General)", col_data["Res_H2H_G"].replace("*",":"), help="Resultado del H2H más reciente entre ambos equipos.")
                
                # AÑADIDO: Estadísticas detalladas para H2H (General)
                if h2h6_extra_stats_df is not None and not h2h6_extra_stats_df.empty:
                    st.markdown("<h5 class='card-subtitle'>Estadísticas de Ataque (H2H General)</h5>", unsafe_allow_html=True)
                    st.dataframe(h2h6_extra_stats_df.set_index('Estadística'), use_container_width=True)
                else:
                    st.info("Estadísticas de ataque no disponibles para este H2H general.")
               
            
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
                        # AÑADIDO: Mostrar estadísticas detalladas
                        if comp_l_extra_stats_df is not None and not comp_l_extra_stats_df.empty:
                            st.markdown("<h5 class='card-subtitle'>Estadísticas de Ataque</h5>", unsafe_allow_html=True)
                            st.dataframe(comp_l_extra_stats_df.set_index('Estadística'), use_container_width=True)
                        else:
                            st.info("Estadísticas de ataque no disponibles para este partido comparado.")
                    else:
                        st.info("Comparativa L vs UV A no disponible.")

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
                        # AÑADIDO: Mostrar estadísticas detalladas
                        if comp_v_extra_stats_df is not None and not comp_v_extra_stats_df.empty:
                            st.markdown("<h5 class='card-subtitle'>Estadísticas de Ataque</h5>", unsafe_allow_html=True)
                            st.dataframe(comp_v_extra_stats_df.set_index('Estadística'), use_container_width=True)
                        else:
                            st.info("Estadísticas de ataque no disponibles para este partido comparado.")
                    else:
                        st.info("Comparativa V vs UL H no disponible.")
                st.markdown("</div>", unsafe_allow_html=True)

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
                st.markdown("</div>", unsafe_allow_html=True)

            with st.expander("ℹ️ Información General del Partido", expanded=False):
 
                info_col1,info_col2,info_col3=st.columns(3)
                info_col1.metric("Línea Goles Inicial",col_data["G_i"], help="Línea de goles Más/Menos (Over/Under) inicial ofrecida por Bet365.")
                info_col2.metric("Liga",col_data["League"], help="Nombre de la liga en la que se juega el partido.")
                info_col3.metric("ID Partido",col_data["match_id"], help="Identificador único del partido en la plataforma de origen.")
                st.markdown("</div>", unsafe_allow_html=True)

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
                <li><strong style='color:#28a745;'>¡NUEVO! Estadísticas de ataque (disparos, ataques peligrosos) para partidos históricos relevantes.</strong></li>
            </ul>
            <p><strong>Simplemente introduce el ID del partido y pulsa analizar.</strong></p>
        </div>
        """, unsafe_allow_html=True)


if __name__ == '__main__':
    st.set_page_config(layout="wide", page_title="Análisis Avanzado de Partidos (OF)", initial_sidebar_state="expanded")
    if 'driver_other_feature' not in st.session_state:
        st.session_state.driver_other_feature = None
    display_other_feature_ui()
