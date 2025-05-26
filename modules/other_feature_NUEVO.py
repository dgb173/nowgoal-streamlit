# modules/other_feature_NUEVO.py (o como lo llames)
import streamlit as st
import time
import requests
import re
import math
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
BASE_URL_OF = "https://live18.nowgoal25.com" # Verifica que este sea el dominio correcto
SELENIUM_TIMEOUT_SECONDS_OF = 20
SELENIUM_POLL_FREQUENCY_OF = 0.2

# --- FUNCIONES HELPER PARA PARSEO Y FORMATEO (ADAPTADAS) ---
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
            # Lógica para manejar signos correctamente en formatos como "-0/0.5" o "0/-0.5"
            if val1 < 0 and not p2_str.startswith('-') and val2 > 0: # ej: -0.5/1
                 val2 = -abs(val2) # Implícito -0.5 / -1, pero raro; más común es -0.5/-1
            elif original_starts_with_minus and val1 == 0.0 and \
                 (p1_str == "0" or p1_str == "-0") and \
                 not p2_str.startswith('-') and val2 > 0: # ej: -0/0.5 (debe ser 0 y -0.5)
                val2 = -abs(val2)
            return (val1 + val2) / 2.0
        else: # Formatos como "0.5", "-1"
            return float(s)
    except ValueError:
        return None

def format_ah_as_decimal_string_of(ah_line_str: str, for_sheets=False):
    # Devuelve el string formateado (ej: "-0.5", "1", "0") o '-' si no es parseable/válido.
    if not isinstance(ah_line_str, str) or not ah_line_str.strip() or ah_line_str.strip() in ['-', '?']:
        return ah_line_str.strip() if isinstance(ah_line_str, str) and ah_line_str.strip() in ['-','?'] else '-'
    
    numeric_value = parse_ah_to_number_of(ah_line_str)
    if numeric_value is None: # No se pudo parsear a número
        # Si el string original era algo como "Par" o un texto, lo devolvemos tal cual si no es solo un guion
        # Pero para la app, queremos que si no es un número válido, sea '-' o '?'
        return ah_line_str.strip() if ah_line_str.strip() in ['-','?'] else '-'


    if numeric_value == 0.0:
        return "0"
    
    # Redondeo estándar a X.0 o X.5
    sign = -1 if numeric_value < 0 else 1
    abs_num = abs(numeric_value)
    mod_val = abs_num % 1 # Parte decimal
    
    if mod_val == 0.0: # Ya es X.0
        abs_rounded = abs_num
    elif mod_val == 0.25: # X.25
        abs_rounded = math.floor(abs_num) + 0.25
    elif mod_val == 0.5: # Ya es X.5
        abs_rounded = abs_num
    elif mod_val == 0.75: # X.75
        abs_rounded = math.floor(abs_num) + 0.75
    # Si el redondeo es más simple (siempre a .0 o .5 más cercano)
    # elif mod_val < 0.25: abs_rounded = math.floor(abs_num)      # X.0
    # elif mod_val < 0.75: abs_rounded = math.floor(abs_num) + 0.5  # X.5
    # else: abs_rounded = math.ceil(abs_num)                     # (X+1).0
    else: # Para casos como X.1, X.3, redondear al X.0 o X.5 más cercano
        if mod_val < 0.25: abs_rounded = math.floor(abs_num)
        elif mod_val < 0.75: abs_rounded = math.floor(abs_num) + 0.5
        else: abs_rounded = math.ceil(abs_num)

    final_value_signed = sign * abs_rounded

    if final_value_signed == 0.0: # Re-chequeo
        output_str = "0"
    elif abs(final_value_signed - round(final_value_signed, 0)) < 1e-9 : # Es un entero
        output_str = str(int(round(final_value_signed, 0)))
    elif abs(final_value_signed - (math.floor(final_value_signed) + 0.5)) < 1e-9: # Es X.5
        output_str = f"{final_value_signed:.1f}"
    elif abs(final_value_signed - (math.floor(final_value_signed) + 0.25)) < 1e-9 or \
         abs(final_value_signed - (math.floor(final_value_signed) + 0.75)) < 1e-9: # Es X.25 o X.75
        output_str = f"{final_value_signed:.2f}".replace(".25", ".25").replace(".75", ".75") # Asegurar dos decimales para .25/.75
    else: # Otros casos (poco comunes para AH)
        output_str = f"{final_value_signed:.2f}" 


    if for_sheets:
        return "'" + output_str.replace('.', ',') if output_str not in ['-','?'] else output_str
    return output_str

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
        # Aplicamos el formateo aquí mismo para asegurar consistencia
        ah_line_fmt = format_ah_as_decimal_string_of(ah_line_raw_text) 
        if not home or not away: return None
        return {'home': home, 'away': away, 'score': score_fmt, 'score_raw': score_raw,
                'ahLine': ah_line_fmt, 'ahLine_raw': ah_line_raw_text, # ahLine ya está formateado
                'matchIndex': row_element.get('index'), 'vs': row_element.get('vs'),
                'league_id_hist': league_id_hist_attr}
    except Exception: return None

# --- FUNCIONES DE REQUESTS, SELENIUM, Y EXTRACCIÓN (Completas) ---
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
            # El hándicap de esta función es RAW, se formateará en la UI si es necesario
            rol_a_in_this_h2h = "H" if h2h_row_home_id == str(rival_a_id) else "A"
            return {"status": "found", "goles_home": g_h.strip(), "goles_away": g_a.strip(), "handicap": handicap_raw, "rol_rival_a": rol_a_in_this_h2h, "h2h_home_team_name": links[0].text.strip(), "h2h_away_team_name": links[1].text.strip()}
    return {"status": "not_found", "resultado": f"H2H directo no encontrado para {rival_a_name} vs {rival_b_name} en historial (table_v2) de la página de ref. ({key_match_id_for_h2h_url})."}

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
                handicap_cell = tds[11]; handicap_raw = handicap_cell.get("data-o", handicap_cell.text.strip()) # RAW handicap
                if not handicap_raw or handicap_raw.strip() == "-": handicap_raw = "N/A"
                else: handicap_raw = handicap_raw.strip()
                return {"date": date, "home_team": home_team_row_name, "away_team": away_team_row_name,"score": score, "handicap_line_raw": handicap_raw} # Devuelve RAW
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
            odds_info["ah_linea_raw"] = tds[3].get_attribute("data-o") or tds[3].text.strip() or "N/A" # RAW
            odds_info["ah_away_cuota"] = tds[4].get_attribute("data-o") or tds[4].text.strip() or "N/A"
            odds_info["goals_over_cuota"] = tds[8].get_attribute("data-o") or tds[8].text.strip() or "N/A"
            odds_info["goals_linea_raw"] = tds[9].get_attribute("data-o") or tds[9].text.strip() or "N/A" # RAW
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
        if home_table_header and target_team_name_exact and target_team_name_exact.lower() in home_table_header.get_text().lower(): # Check for target_team_name_exact
            team_table_soup = home_div_standings.find("table", class_="team-table-home"); is_home_team_table_type = True
            data["specific_type"] = home_div_standings.find("td", class_="bg1").text.strip() if home_div_standings.find("td", class_="bg1") else "En Casa"
    if not team_table_soup:
        guest_div_standings = standings_section.find("div", class_="guest-div")
        if guest_div_standings:
            guest_table_header = guest_div_standings.find("tr", class_="team-guest")
            if guest_table_header and target_team_name_exact and target_team_name_exact.lower() in guest_table_header.get_text().lower(): # Check for target_team_name_exact
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

def extract_h2h_data_of(soup, main_home_team_name, main_away_team_name, current_league_id):
    ah1, res1, res1_raw = '-', '?*?', '?-?'; ah6, res6, res6_raw = '-', '?*?', '?-?'
    h2h_table = soup.find("table", id="table_v3")
    if not h2h_table: return ah1, res1, res1_raw, ah6, res6, res6_raw
    filtered_h2h_list = []
    if not main_home_team_name or not main_away_team_name: # Evitar error si los nombres no están
        return ah1, res1, res1_raw, ah6, res6, res6_raw

    for row_h2h in h2h_table.find_all("tr", id=re.compile(r"tr3_\d+")):
        details = get_match_details_from_row_of(row_h2h, score_class_selector='fscore_3', source_table_type='h2h')
        if not details: continue
        if current_league_id and details.get('league_id_hist') and details.get('league_id_hist') != str(current_league_id): continue
        filtered_h2h_list.append(details)
    if not filtered_h2h_list: return ah1, res1, res1_raw, ah6, res6, res6_raw
    
    h2h_general_match = filtered_h2h_list[0]
    ah6 = h2h_general_match.get('ahLine', '-') # Ya está formateado
    res6 = h2h_general_match.get('score', '?*?'); res6_raw = h2h_general_match.get('score_raw', '?-?')
    
    h2h_local_specific_match = None
    for d_h2h in filtered_h2h_list:
        if d_h2h.get('home','').lower() == main_home_team_name.lower() and \
           d_h2h.get('away','').lower() == main_away_team_name.lower():
            h2h_local_specific_match = d_h2h; break
    if h2h_local_specific_match:
        ah1 = h2h_local_specific_match.get('ahLine', '-') # Ya está formateado
        res1 = h2h_local_specific_match.get('score', '?*?'); res1_raw = h2h_local_specific_match.get('score_raw', '?-?')
    return ah1, res1, res1_raw, ah6, res6, res6_raw

def extract_comparative_match_of(soup_for_team_history, table_id_of_team_to_search, team_name_to_find_match_for, opponent_name_to_search, current_league_id, is_home_table):
    if not opponent_name_to_search or opponent_name_to_search == "N/A" or not team_name_to_find_match_for:
        return "-"
    table = soup_for_team_history.find("table", id=table_id_of_team_to_search)
    if not table: return "-"
    score_class_selector = 'fscore_1' if is_home_table else 'fscore_2'
    for row in table.find_all("tr", id=re.compile(rf"tr{table_id_of_team_to_search[-1]}_\d+")):
        details = get_match_details_from_row_of(row, score_class_selector=score_class_selector, source_table_type='hist')
        if not details: continue
        if current_league_id and details.get('league_id_hist') and details.get('league_id_hist') != str(current_league_id): continue
        home_hist = details.get('home','').lower(); away_hist = details.get('away','').lower()
        team_main_lower = team_name_to_find_match_for.lower(); opponent_lower = opponent_name_to_search.lower()
        if (team_main_lower == home_hist and opponent_lower == away_hist) or \
           (team_main_lower == away_hist and opponent_lower == home_hist):
            score = details.get('score', '?*?')
            ah_line_extracted = details.get('ahLine', '-') # ahLine ya viene formateado desde get_match_details_from_row_of
            
            localia = 'H' if team_main_lower == home_hist else 'A'
            return f"{score}/{ah_line_extracted} {localia}".strip() # Devolver con AH formateado
    return "-"

# --- STREAMLIT APP UI (Función principal) ---
def display_other_feature_ui():
    st.sidebar.title("⚙️ Configuración Partido (OF)")
    main_match_id_str_input_of = st.sidebar.text_input("🆔 ID Partido Principal:", value="2696131", help="Pega el ID del partido a analizar.", key="other_feature_match_id_input")
    analizar_button_of = st.sidebar.button("🚀 Analizar Partido (OF)", type="primary", use_container_width=True, key="other_feature_analizar_button")

    results_container = st.container()

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
                results_container.error("⚠️ ID de partido no válido (OF)."); st.stop()
        if not main_match_id_to_process_of: 
            results_container.warning("⚠️ Ingresa un ID de partido válido (OF)."); st.stop()
        
        start_time_of = time.time()
        with results_container:
            with st.spinner("🔄 Cargando datos iniciales..."):
                main_page_url_h2h_view_of = f"/match/h2h-{main_match_id_to_process_of}"
                soup_main_h2h_page_of = fetch_soup_requests_of(main_page_url_h2h_view_of)
            if not soup_main_h2h_page_of:
                st.error("❌ No se pudo obtener la página H2H principal."); st.stop()

            mp_home_id_of, mp_away_id_of, mp_league_id_of, mp_home_name_from_script, mp_away_name_from_script, mp_league_name_of = get_team_league_info_from_script_of(soup_main_h2h_page_of)
            
            with st.spinner("📊 Extrayendo clasificaciones principales..."):
                home_team_main_standings = extract_standings_data_from_h2h_page_of(soup_main_h2h_page_of, mp_home_name_from_script)
                away_team_main_standings = extract_standings_data_from_h2h_page_of(soup_main_h2h_page_of, mp_away_name_from_script)
            
            display_home_name = home_team_main_standings.get("name", mp_home_name_from_script) if home_team_main_standings.get("name", "N/A") != "N/A" else mp_home_name_from_script
            display_away_name = away_team_main_standings.get("name", mp_away_name_from_script) if away_team_main_standings.get("name", "N/A") != "N/A" else mp_away_name_from_script

            st.markdown(f"## 🆚 **{display_home_name or 'Local'} vs {display_away_name or 'Visitante'}**")
            st.caption(f"🏆 **Liga:** {mp_league_name_of or 'N/A'} (ID: {mp_league_id_of or 'N/A'}) | 🗓️ **Partido ID:** {main_match_id_to_process_of}")
            st.markdown("---")

            col_home_stand, col_away_stand = st.columns(2)
            # ... (código de visualización de clasificación principal igual que antes) ...
            with col_home_stand:
                st.subheader(f"🏠 {display_home_name or 'Local'}")
                if display_home_name and display_home_name != "N/A" and home_team_main_standings.get("name", "N/A") != "N/A":
                    hst = home_team_main_standings
                    st.markdown(f"- **Ranking:** {hst.get('ranking', 'N/A')}\n"
                                f"- **Total:** {hst.get('total_pj', 'N/A')} PJ | {hst.get('total_v', 'N/A')}V-{hst.get('total_e', 'N/A')}E-{hst.get('total_d', 'N/A')}D | GF: {hst.get('total_gf', 'N/A')}, GC: {hst.get('total_gc', 'N/A')}\n"
                                f"- **{hst.get('specific_type','En Casa')}:** {hst.get('specific_pj', 'N/A')} PJ | {hst.get('specific_v', 'N/A')}V-{hst.get('specific_e', 'N/A')}E-{hst.get('specific_d', 'N/A')}D | GF: {hst.get('specific_gf', 'N/A')}, GC: {hst.get('specific_gc', 'N/A')}")
                else: st.info(f"Clasificación no disponible para {display_home_name or 'Local'}.")
            with col_away_stand:
                st.subheader(f"✈️ {display_away_name or 'Visitante'}")
                if display_away_name and display_away_name != "N/A" and away_team_main_standings.get("name", "N/A") != "N/A":
                    ast = away_team_main_standings
                    st.markdown(f"- **Ranking:** {ast.get('ranking', 'N/A')}\n"
                                f"- **Total:** {ast.get('total_pj', 'N/A')} PJ | {ast.get('total_v', 'N/A')}V-{ast.get('total_e', 'N/A')}E-{ast.get('total_d', 'N/A')}D | GF: {ast.get('total_gf', 'N/A')}, GC: {ast.get('total_gc', 'N/A')}\n"
                                f"- **{ast.get('specific_type','Fuera')}:** {ast.get('specific_pj', 'N/A')} PJ | {ast.get('specific_v', 'N/A')}V-{ast.get('specific_e', 'N/A')}E-{ast.get('specific_d', 'N/A')}D | GF: {ast.get('specific_gf', 'N/A')}, GC: {ast.get('specific_gc', 'N/A')}")
                else: st.info(f"Clasificación no disponible para {display_away_name or 'Visitante'}.")
            st.markdown("---")
            
            key_match_id_for_rival_a_h2h, rival_a_id_orig_col3, rival_a_name_orig_col3 = get_rival_a_for_original_h2h_of(main_match_id_to_process_of)
            match_id_rival_b_game_ref, rival_b_id_orig_col3, rival_b_name_orig_col3 = get_rival_b_for_original_h2h_of(main_match_id_to_process_of)
            rival_a_standings = {}; rival_b_standings = {}
            with st.spinner("📊 Extrayendo clasificaciones de oponentes H2H (Col3)..."): # ... (lógica igual)
                if rival_a_name_orig_col3 and rival_a_name_orig_col3 != "N/A" and key_match_id_for_rival_a_h2h:
                    soup_rival_a_h2h_page = fetch_soup_requests_of(f"/match/h2h-{key_match_id_for_rival_a_h2h}")
                    if soup_rival_a_h2h_page: rival_a_standings = extract_standings_data_from_h2h_page_of(soup_rival_a_h2h_page, rival_a_name_orig_col3)
                if rival_b_name_orig_col3 and rival_b_name_orig_col3 != "N/A" and match_id_rival_b_game_ref:
                    soup_rival_b_h2h_page = fetch_soup_requests_of(f"/match/h2h-{match_id_rival_b_game_ref}")
                    if soup_rival_b_h2h_page: rival_b_standings = extract_standings_data_from_h2h_page_of(soup_rival_b_h2h_page, rival_b_name_orig_col3)
            
            main_match_odds_data_of = {}; last_home_match_in_league_of = None; last_away_match_in_league_of = None
            driver_actual_of = st.session_state.driver_other_feature; driver_of_needs_init = False # ... (lógica de Selenium igual) ...
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
                with st.spinner("🚘 Inicializando WebDriver..."): driver_actual_of = get_selenium_driver_of()
                st.session_state.driver_other_feature = driver_actual_of

            if driver_actual_of:
                try:
                    with st.spinner("⚙️ Accediendo a datos con Selenium..."):
                        driver_actual_of.get(f"{BASE_URL_OF}{main_page_url_h2h_view_of}") 
                        WebDriverWait(driver_actual_of, SELENIUM_TIMEOUT_SECONDS_OF).until(EC.presence_of_element_located((By.ID, "table_v1"))) 
                        time.sleep(0.8)
                        main_match_odds_data_of = get_main_match_odds_selenium_of(driver_actual_of)
                        if mp_home_id_of and mp_league_id_of and display_home_name and display_home_name != "N/A":
                             last_home_match_in_league_of = extract_last_match_in_league_of(driver_actual_of, "table_v1", display_home_name, mp_league_id_of, "input#cb_sos1[value='1']", is_home_game_filter=True)
                        if mp_away_id_of and mp_league_id_of and display_away_name and display_away_name != "N/A":
                            last_away_match_in_league_of = extract_last_match_in_league_of(driver_actual_of, "table_v2", display_away_name, mp_league_id_of, "input#cb_sos2[value='2']", is_home_game_filter=False)
                except Exception as e_main_sel_of: st.error(f"❗ Error Selenium: {type(e_main_sel_of).__name__}")
            else: st.warning("❗ WebDriver no disponible para Odds/Últimos partidos.")

            col_data = { # ... (poblar col_data igual que antes) ...
                "AH_H2H_V": "-", "AH_Act": "?", "Res_H2H_V": "?*?", "AH_L_H": "-", "Res_L_H": "?*?", 
                "AH_V_A": "-", "Res_V_A": "?*?", "AH_H2H_G": "-", "Res_H2H_G": "?*?", "L_vs_UV_A": "-", 
                "V_vs_UL_H": "-", "Stats_L": "Stats L: N/A", "Stats_V": "Stats V: N/A", "Fin": "?*?", 
                "G_i": "?", "League": mp_league_name_of or "N/A", "match_id": str(main_match_id_to_process_of)
            }
            raw_ah_act = main_match_odds_data_of.get('ah_linea_raw', '?'); col_data["AH_Act"] = format_ah_as_decimal_string_of(raw_ah_act) # Usar _raw
            raw_g_i = main_match_odds_data_of.get('goals_linea_raw', '?'); col_data["G_i"] = format_ah_as_decimal_string_of(raw_g_i) # Usar _raw
            col_data["Fin"], _ = extract_final_score_of(soup_main_h2h_page_of)
            if home_team_main_standings.get("name", "N/A") != "N/A" and display_home_name != "N/A":
                hst = home_team_main_standings
                col_data["Stats_L"] = (f"🏆Rk:{hst.get('ranking','N/A')} 🏠{hst.get('specific_type','En Casa')}\n"
                                       f"🌍T:{hst.get('total_pj','N/A')}|{hst.get('total_v','N/A')}/{hst.get('total_e','N/A')}/{hst.get('total_d','N/A')}|{hst.get('total_gf','N/A')}-{hst.get('total_gc','N/A')}\n"
                                       f"🏡L:{hst.get('specific_pj','N/A')}|{hst.get('specific_v','N/A')}/{hst.get('specific_e','N/A')}/{hst.get('specific_d','N/A')}|{hst.get('specific_gf','N/A')}-{hst.get('specific_gc','N/A')}")
            if away_team_main_standings.get("name", "N/A") != "N/A" and display_away_name != "N/A":
                ast = away_team_main_standings
                col_data["Stats_V"] = (f"🏆Rk:{ast.get('ranking','N/A')} ✈️{ast.get('specific_type','Fuera')}\n"
                                       f"🌍T:{ast.get('total_pj','N/A')}|{ast.get('total_v','N/A')}/{ast.get('total_e','N/A')}/{ast.get('total_d','N/A')}|{ast.get('total_gf','N/A')}-{ast.get('total_gc','N/A')}\n"
                                       f"🛫V:{ast.get('specific_pj','N/A')}|{ast.get('specific_v','N/A')}/{ast.get('specific_e','N/A')}/{ast.get('specific_d','N/A')}|{ast.get('specific_gf','N/A')}-{ast.get('specific_gc','N/A')}")
            if last_home_match_in_league_of:
                col_data["AH_L_H"] = format_ah_as_decimal_string_of(last_home_match_in_league_of.get('handicap_line_raw', '-')) # Usar _raw
                col_data["Res_L_H"] = last_home_match_in_league_of.get('score', '?*?').replace('-', '*')
            if last_away_match_in_league_of:
                col_data["AH_V_A"] = format_ah_as_decimal_string_of(last_away_match_in_league_of.get('handicap_line_raw', '-')) # Usar _raw
                col_data["Res_V_A"] = last_away_match_in_league_of.get('score', '?*?').replace('-', '*')
            ah1_val, res1_val, _, ah6_val, res6_val, _ = extract_h2h_data_of(soup_main_h2h_page_of, display_home_name, display_away_name, mp_league_id_of)
            col_data["AH_H2H_V"] = ah1_val; col_data["Res_H2H_V"] = res1_val
            col_data["AH_H2H_G"] = ah6_val; col_data["Res_H2H_G"] = res6_val
            last_away_opponent_for_home_hist = last_away_match_in_league_of.get('home_team') if last_away_match_in_league_of and display_home_name else None
            if last_away_opponent_for_home_hist and display_home_name != "N/A":
                col_data["L_vs_UV_A"] = extract_comparative_match_of(soup_main_h2h_page_of, "table_v1", display_home_name, last_away_opponent_for_home_hist, mp_league_id_of, is_home_table=True)
            last_home_opponent_for_away_hist = last_home_match_in_league_of.get('away_team') if last_home_match_in_league_of and display_away_name else None
            if last_home_opponent_for_away_hist and display_away_name != "N/A":
                col_data["V_vs_UL_H"] = extract_comparative_match_of(soup_main_h2h_page_of, "table_v2", display_away_name, last_home_opponent_for_away_hist, mp_league_id_of, is_home_table=False)
            
            st.markdown("---"); st.header("🎯 Análisis Detallado del Partido")
            with st.expander("📈 Cuotas Bet365 (Iniciales)", expanded=True): # ... (visualización igual) ...
                odd_col1, odd_col2 = st.columns(2)
                with odd_col1: st.markdown(f"**H. Asiático:** `{main_match_odds_data_of.get('ah_home_cuota','N/A')}` <span style='color:#007bff; font-weight:bold;'>[{format_ah_as_decimal_string_of(main_match_odds_data_of.get('ah_linea_raw','?'))}]</span> `{main_match_odds_data_of.get('ah_away_cuota','N/A')}`", unsafe_allow_html=True)
                with odd_col2: st.markdown(f"**Línea Goles:** `Ov {main_match_odds_data_of.get('goals_over_cuota','N/A')}` <span style='color:#dc3545; font-weight:bold;'>[{format_ah_as_decimal_string_of(main_match_odds_data_of.get('goals_linea_raw','?'))}]</span> `Un {main_match_odds_data_of.get('goals_under_cuota','N/A')}`", unsafe_allow_html=True)
                st.metric(label="🏁 Marcador Final (si disponible)", value=col_data["Fin"].replace("*",":"))

            st.subheader("⚡ Rendimiento Reciente y Contexto H2H"); rp_col1, rp_col2, rp_col3 = st.columns(3) # ... (visualización igual) ...
            with rp_col1:
                st.markdown(f"##### 🏡 Últ. {display_home_name or 'Local'} (Casa)")
                if last_home_match_in_league_of: 
                    res = last_home_match_in_league_of
                    st.markdown(f"🆚 {res['away_team']}\n\n**{res['home_team']} {res['score'].replace('-',':')} {res['away_team']}**")
                    st.markdown(f"**AH:** <span style='font-weight:bold;'>{format_ah_as_decimal_string_of(res.get('handicap_line_raw','-'))}</span>", unsafe_allow_html=True) # Usar _raw
                    st.caption(f"📅 {res['date']}")
                else: st.info("No encontrado.")
            with rp_col2:
                st.markdown(f"##### ✈️ Últ. {display_away_name or 'Visitante'} (Fuera)")
                if last_away_match_in_league_of: 
                    res = last_away_match_in_league_of
                    st.markdown(f"🆚 {res['home_team']}\n\n**{res['home_team']} {res['score'].replace('-',':')} {res['away_team']}**")
                    st.markdown(f"**AH:** <span style='font-weight:bold;'>{format_ah_as_decimal_string_of(res.get('handicap_line_raw','-'))}</span>", unsafe_allow_html=True) # Usar _raw
                    st.caption(f"📅 {res['date']}")
                else: st.info("No encontrado.")
            with rp_col3:
                st.markdown(f"##### 🆚 H2H Oponentes (Col3)")
                rival_a_col3_name_display = rival_a_name_orig_col3 if rival_a_name_orig_col3 and rival_a_name_orig_col3 != "N/A" else (rival_a_id_orig_col3 or "Rival A")
                rival_b_col3_name_display = rival_b_name_orig_col3 if rival_b_name_orig_col3 and rival_b_name_orig_col3 != "N/A" else (rival_b_id_orig_col3 or "Rival B")
                details_h2h_col3_of = {"status": "error", "resultado": "N/A"}
                if key_match_id_for_rival_a_h2h and rival_a_id_orig_col3 and rival_b_id_orig_col3 and driver_actual_of: 
                    with st.spinner(f"Buscando H2H: {rival_a_col3_name_display} vs {rival_b_col3_name_display}..."):
                        details_h2h_col3_of = get_h2h_details_for_original_logic_of(driver_actual_of, key_match_id_for_rival_a_h2h, rival_a_id_orig_col3, rival_b_id_orig_col3, rival_a_col3_name_display, rival_b_col3_name_display)
                if details_h2h_col3_of.get("status") == "found":
                    res_h2h = details_h2h_col3_of
                    st.markdown(f"**{res_h2h.get('h2h_home_team_name')}** {res_h2h.get('goles_home')}:{res_h2h.get('goles_away')} **{res_h2h.get('h2h_away_team_name')}**")
                    st.markdown(f"(AH: {format_ah_as_decimal_string_of(res_h2h.get('handicap','-'))})") # Formatear aquí
                else: st.info(details_h2h_col3_of.get('resultado', f"H2H no encontrado."))
            
            with st.expander("🔎 Clasificación Oponentes (H2H Col3)"): # ... (visualización igual) ...
                opp_stand_col1, opp_stand_col2 = st.columns(2)
                with opp_stand_col1:
                    st.markdown(f"###### {rival_a_standings.get('name', rival_a_col3_name_display)}")
                    if rival_a_standings.get("name", "N/A") != "N/A": rst = rival_a_standings; st.caption(f"Rk: {rst.get('ranking','N/A')} | T: {rst.get('total_pj')}|{rst.get('total_v')}/{rst.get('total_e')}/{rst.get('total_d')}|{rst.get('total_gf')}-{rst.get('total_gc')}"); st.caption(f"{rst.get('specific_type')}: {rst.get('specific_pj')}|{rst.get('specific_v')}/{rst.get('specific_e')}/{rst.get('specific_d')}|{rst.get('specific_gf')}-{rst.get('specific_gc')}")
                    else: st.caption("No disponible.")
                with opp_stand_col2:
                    st.markdown(f"###### {rival_b_standings.get('name', rival_b_col3_name_display)}")
                    if rival_b_standings.get("name", "N/A") != "N/A": rst = rival_b_standings; st.caption(f"Rk: {rst.get('ranking','N/A')} | T: {rst.get('total_pj')}|{rst.get('total_v')}/{rst.get('total_e')}/{rst.get('total_d')}|{rst.get('total_gf')}-{rst.get('total_gc')}"); st.caption(f"{rst.get('specific_type')}: {rst.get('specific_pj')}|{rst.get('specific_v')}/{rst.get('specific_e')}/{rst.get('specific_d')}|{rst.get('specific_gf')}-{rst.get('specific_gc')}")
                    else: st.caption("No disponible.")

            st.markdown("---"); st.subheader("📊 Datos Adicionales (Estilo Script Original)")
            with st.expander("🔰 Hándicaps y Resultados Clave", expanded=True): # ... (visualización igual) ...
                m_col1, m_col2, m_col3 = st.columns(3); m_col1.metric("AH H2H (Local en Casa)", col_data["AH_H2H_V"]); m_col2.metric("AH Actual Partido", col_data["AH_Act"]); m_col3.metric("Res H2H (Local en Casa)", col_data["Res_H2H_V"].replace("*",":"))
                m_col4,m_col5,m_col6,m_col7=st.columns(4); m_col4.metric("AH Últ. Local (Casa)",col_data["AH_L_H"]); m_col5.metric("Res Últ. Local (Casa)",col_data["Res_L_H"].replace("*",":")); m_col6.metric("AH Últ. Visitante (Fuera)",col_data["AH_V_A"]); m_col7.metric("Res Últ. Visitante (Fuera)",col_data["Res_V_A"].replace("*",":"))
                m_col8, m_col9 = st.columns(2); m_col8.metric("AH H2H (General)", col_data["AH_H2H_G"]); m_col9.metric("Res H2H (General)", col_data["Res_H2H_G"].replace("*",":"))
            
            # --- SECCIÓN MEJORADA PARA COMPARATIVAS INDIRECTAS ---
            with st.expander("🔁 Comparativas Indirectas", expanded=True):
                comp_col1, comp_col2 = st.columns(2)
                placeholder_nodata = "*(No disponible)*"

                with comp_col1:
                    st.markdown(f"**<span style='color: #1E90FF;'>🏠 Local</span> vs. <span style='color: #FF4500;'>Últ. Rival del Visitante</span>** (cuando Visitante jugó Fuera)")
                    comp_str_l = col_data.get('L_vs_UV_A', "-")
                    if comp_str_l and comp_str_l != "-":
                        parts = comp_str_l.split('/')
                        score_part = parts[0].replace('*', ':').strip()
                        ah_loc_part = parts[1].strip() if len(parts) > 1 else " " 
                        
                        ah_val_l = ah_loc_part.rsplit(' ', 1)[0].strip()
                        loc_val_l = ah_loc_part.rsplit(' ', 1)[-1].strip() if ' ' in ah_loc_part else ""

                        st.markdown(f"⚽ **Resultado:** `{score_part if score_part else placeholder_nodata}`")
                        st.markdown(f"⚖️ **AH Partido Comparado:** `{format_ah_as_decimal_string_of(ah_val_l) if ah_val_l else placeholder_nodata}`")
                        st.markdown(f"🏟️ **Localía de 'Local' en ese partido:** `{loc_val_l if loc_val_l else placeholder_nodata}`")
                    else:
                        st.info("Comparativa no disponible.")

                with comp_col2:
                    st.markdown(f"**<span style='color: #FF4500;'>✈️ Visitante</span> vs. <span style='color: #1E90FF;'>Últ. Rival del Local</span>** (cuando Local jugó en Casa)")
                    comp_str_v = col_data.get('V_vs_UL_H', "-")
                    if comp_str_v and comp_str_v != "-":
                        parts = comp_str_v.split('/')
                        score_part = parts[0].replace('*', ':').strip()
                        ah_loc_part = parts[1].strip() if len(parts) > 1 else " "
                        
                        ah_val_v = ah_loc_part.rsplit(' ', 1)[0].strip()
                        loc_val_v = ah_loc_part.rsplit(' ', 1)[-1].strip() if ' ' in ah_loc_part else ""

                        st.markdown(f"⚽ **Resultado:** `{score_part if score_part else placeholder_nodata}`")
                        st.markdown(f"⚖️ **AH Partido Comparado:** `{format_ah_as_decimal_string_of(ah_val_v) if ah_val_v else placeholder_nodata}`")
                        st.markdown(f"🏟️ **Localía de 'Visitante' en ese partido:** `{loc_val_v if loc_val_v else placeholder_nodata}`")
                    else:
                        st.info("Comparativa no disponible.")
            # --- FIN SECCIÓN MEJORADA ---

            with st.expander("📋 Estadísticas Detalladas de Equipos"): # ... (visualización igual) ...
                stats_col1,stats_col2=st.columns(2)
                with stats_col1: st.markdown(f"**Estadísticas Local ({display_home_name or 'Local'}):**"); st.text(col_data["Stats_L"])
                with stats_col2: st.markdown(f"**Estadísticas Visitante ({display_away_name or 'Visitante'}):**"); st.text(col_data["Stats_V"])
            with st.expander("ℹ️ Información General del Partido"): # ... (visualización igual) ...
                info_col1,info_col2,info_col3=st.columns(3); info_col1.metric("Línea Goles Partido",col_data["G_i"]); info_col2.metric("Liga",col_data["League"]); info_col3.metric("ID Partido",col_data["match_id"])

            end_time_of = time.time(); st.sidebar.info(f"⏱️ Análisis: {end_time_of - start_time_of:.2f}s")
    else:
        results_container.info("✨ Ingresa un ID y haz clic en 'Analizar Partido (OF)' para comenzar.")

if __name__ == '__main__':
    st.set_page_config(layout="wide", page_title="OF Debug", initial_sidebar_state="expanded")
    if 'driver_other_feature' not in st.session_state:
        st.session_state.driver_other_feature = None
    display_other_feature_ui()
