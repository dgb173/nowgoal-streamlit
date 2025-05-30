# modules/other_feature_module.py (o como lo llames)
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

def get_match_details_from_row_of(row_element, score_class_selector='score', source_table_type='h2h'):
    try:
        cells = row_element.find_all('td')
        
        # --- MODIFICACIÓN: Ajustar ah_idx y min_cells basado en source_table_type ---
        min_cells_required = 0
        if source_table_type == 'hist': # Para table_v1, table_v2 (historial de equipos)
            ah_idx = 5 # Asumimos que el HDP está en la 6ta celda (índice 5)
            # Columnas esperadas: Comp, Date, Home(2), Score(3), Away(4), HDP(5), ...
            # Necesitamos al menos 6 celdas para acceder al índice 5.
            min_cells_required = 6 
        elif source_table_type == 'h2h': # Para table_v3 (H2H directo)
            ah_idx = 11 # Mantenemos el índice 11
            min_cells_required = 12 # Necesitamos al menos 12 celdas para acceder al índice 11
        else: # Fallback o tipo desconocido
            ah_idx = 11 
            min_cells_required = 12

        if len(cells) < min_cells_required:
            # st.warning(f"Fila con {len(cells)} celdas en get_match_details_from_row_of (tipo: {source_table_type}), se esperaban >= {min_cells_required}.")
            return None
        # --- FIN DE LA MODIFICACIÓN ---
            
        league_id_hist_attr = row_element.get('name')
        # Índices de las celdas relevantes (estos pueden ser fijos si la estructura inicial es consistente)
        home_idx, score_idx, away_idx = 2, 3, 4

        home_tag = cells[home_idx].find('a')
        home = home_tag.text.strip() if home_tag else cells[home_idx].text.strip()
        
        away_tag = cells[away_idx].find('a')
        away = away_tag.text.strip() if away_tag else cells[away_idx].text.strip()
        
        score_cell_content = cells[score_idx].text.strip()
        score_span = cells[score_idx].find('span', class_=lambda x: x and score_class_selector in x)
        score_raw_text = score_span.text.strip() if score_span else score_cell_content
        
        score_m = re.match(r'(\d+-\d+)', score_raw_text)
        score_raw = score_m.group(1) if score_m else '?-?'
        score_fmt = score_raw.replace('-', '*') if score_raw != '?-?' else '?*?'
        
        ah_cell = cells[ah_idx] # Usar el ah_idx determinado dinámicamente
        ah_data_o = ah_cell.get("data-o")
        
        ah_line_raw_text = "-" # Valor por defecto si no se encuentra nada
        if ah_data_o and ah_data_o.strip() and ah_data_o.strip() not in ['-', '?']:
            ah_line_raw_text = ah_data_o.strip()
        else:
            cell_text = ah_cell.text.strip()
            if cell_text and cell_text not in ['-', '?']: # Solo usar cell_text si es algo más que '-' o '?'
                 ah_line_raw_text = cell_text
            # Si cell_text es '-' o '?', ah_line_raw_text permanecerá como el valor por defecto "-" o el texto de la celda si es '?'

        ah_line_fmt = format_ah_as_decimal_string_of(ah_line_raw_text) 
        
        if not home or not away: 
            return None
            
        return {
            'home': home, 'away': away, 
            'score': score_fmt, 'score_raw': score_raw,
            'ahLine': ah_line_fmt, 'ahLine_raw': ah_line_raw_text,
            'matchIndex': row_element.get('index'), 
            'vs': row_element.get('vs'),
            'league_id_hist': league_id_hist_attr
        }
    except IndexError:
        # Esto podría ocurrir si ah_idx está fuera de rango a pesar de la comprobación de min_cells_required
        # (aunque es menos probable con la comprobación).
        # st.error(f"IndexError en get_match_details_from_row_of (tipo: {source_table_type}, ah_idx: {ah_idx}, celdas: {len(cells)})")
        return None
    except Exception as e:
        # st.error(f"Excepción en get_match_details_from_row_of: {e}")
        return None

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
            tds = row.find_all("td"); handicap_raw = "N/A"; HANDICAP_TD_IDX = 11 # Este índice podría necesitar ser dinámico si la tabla varía
            if len(tds) > HANDICAP_TD_IDX:
                cell = tds[HANDICAP_TD_IDX]; d_o = cell.get("data-o") 
                handicap_raw = d_o.strip() if d_o and d_o.strip() not in ["", "-"] else (cell.text.strip() if cell.text.strip() not in ["", "-"] else "N/A")
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
            if len(tds) < 14: continue # Asegurar que hay suficientes celdas
            home_team_row_el = tds[2].find("a"); away_team_row_el = tds[4].find("a")
            if not home_team_row_el or not away_team_row_el: continue
            home_team_row_name = home_team_row_el.text.strip(); away_team_row_name = away_team_row_el.text.strip()
            team_is_home_in_row = main_team_name_in_table.lower() == home_team_row_name.lower()
            team_is_away_in_row = main_team_name_in_table.lower() == away_team_row_name.lower()
            if (is_home_game_filter and team_is_home_in_row) or (not is_home_game_filter and team_is_away_in_row):
                date_span = tds[1].find("span", {"name": "timeData"}); date = date_span.text.strip() if date_span else "N/A"
                score_class_re = re.compile(r"fscore_"); score_span = tds[3].find("span", class_=score_class_re); score = score_span.text.strip() if score_span else "N/A"
                
                handicap_cell_idx = 11 # Asumiendo que es el índice 11 para esta función específica
                if len(tds) > handicap_cell_idx:
                    handicap_cell = tds[handicap_cell_idx] 
                    handicap_data_o = handicap_cell.get("data-o")
                    if handicap_data_o and handicap_data_o.strip() and handicap_data_o.strip() not in ['-', '?']:
                        handicap_raw = handicap_data_o.strip()
                    else:
                        handicap_raw = handicap_cell.text.strip()
                    if not handicap_raw or handicap_raw == "-": handicap_raw = "N/A"
                else:
                    handicap_raw = "N/A"

                return {"date": date, "home_team": home_team_row_name, "away_team": away_team_row_name,"score": score, "handicap_line_raw": handicap_raw}
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
        if len(tds) >= 11: # Asegurar que hay suficientes celdas para los índices de cuotas
            # AH Odds: Home (idx 2), Line (idx 3), Away (idx 4)
            # Goals O/U Odds: Over (idx 8), Line (idx 9), Under (idx 10)
            odds_info["ah_home_cuota"] = tds[2].get_attribute("data-o") or tds[2].text.strip() or "N/A"
            odds_info["ah_linea_raw"] = tds[3].get_attribute("data-o") or tds[3].text.strip() or "N/A" 
            odds_info["ah_away_cuota"] = tds[4].get_attribute("data-o") or tds[4].text.strip() or "N/A"
            odds_info["goals_over_cuota"] = tds[8].get_attribute("data-o") or tds[8].text.strip() or "N/A"
            odds_info["goals_linea_raw"] = tds[9].get_attribute("data-o") or tds[9].text.strip() or "N/A" 
            odds_info["goals_under_cuota"] = tds[10].get_attribute("data-o") or tds[10].text.strip() or "N/A"
    except Exception: pass # Evitar que un error aquí detenga todo el script
    return odds_info

def extract_standings_data_from_h2h_page_of(h2h_soup, target_team_name_exact):
    # Initialize data dictionary with default "N/A" values and a status field
    data = {
        "name": target_team_name_exact, "ranking": "N/A", 
        "total_pj": "N/A", "total_v": "N/A", "total_e": "N/A", "total_d": "N/A", 
        "total_gf": "N/A", "total_gc": "N/A", 
        "specific_pj": "N/A", "specific_v": "N/A", "specific_e": "N/A", "specific_d": "N/A", 
        "specific_gf": "N/A", "specific_gc": "N/A", 
        "specific_type": "N/A",
        "standings_status": "Not processed" # Initial status
    }

    if not h2h_soup:
        data["standings_status"] = "Error: h2h_soup is None"
        return data

    # Try to find the main standings section, e.g., by id "porletP4"
    # This ID might change, or the structure might be different in new page versions.
    standings_section = h2h_soup.find("div", id="porletP4") 
    
    if not standings_section:
        data["standings_status"] = "Error: Standings section (e.g., div with id 'porletP4') not found."
        # You could try to find alternative sections here if the structure is known to change
        # For example: standings_section = h2h_soup.find("div", class_="new-standings-class")
        # If no alternative is found, return data with the error status.
        return data
    
    data["standings_status"] = "Standings section 'porletP4' found, processing..."
    team_table_soup = None
    is_home_team_table_type = False # Flag to know if we are parsing home team's "Home" stats or away team's "Away" stats

    # Try to find the specific div for the home team's standings
    home_div_standings = standings_section.find("div", class_="home-div")
    if home_div_standings:
        home_table_header = home_div_standings.find("tr", class_="team-home")
        # Check if the target team name is in the header of this home section
        if home_table_header and target_team_name_exact and target_team_name_exact.lower() in home_table_header.get_text().lower(): 
            team_table_soup = home_div_standings.find("table", class_="team-table-home")
            is_home_team_table_type = True
            # Get the specific type of standings (e.g., "En Casa", "Home")
            specific_type_cell = home_div_standings.find("td", class_="bg1")
            data["specific_type"] = specific_type_cell.text.strip() if specific_type_cell else "En Casa" # Default if not found

    # If not found in home-div, try guest-div (for the away team)
    if not team_table_soup:
        guest_div_standings = standings_section.find("div", class_="guest-div")
        if guest_div_standings:
            guest_table_header = guest_div_standings.find("tr", class_="team-guest")
            # Check if the target team name is in the header of this guest section
            if guest_table_header and target_team_name_exact and target_team_name_exact.lower() in guest_table_header.get_text().lower(): 
                team_table_soup = guest_div_standings.find("table", class_="team-table-guest")
                is_home_team_table_type = False # It's the away team's table
                # Get the specific type of standings (e.g., "Fuera", "Away")
                specific_type_cell = guest_div_standings.find("td", class_="bg1")
                data["specific_type"] = specific_type_cell.text.strip() if specific_type_cell else "Fuera" # Default if not found
    
    if not team_table_soup:
        data["standings_status"] = "Warning: Standings table for the target team not found within 'porletP4'."
        return data

    # Extract ranking and team name from the table header
    header_row_found = team_table_soup.find("tr", class_=re.compile(r"team-(home|guest)")) 
    if header_row_found:
        link = header_row_found.find("a") # Team name is often within an <a> tag
        if link:
            full_text = link.get_text(separator=" ", strip=True)
            # Regex to extract name (text after ']') and rank (number inside '[xxx-##]')
            name_match = re.search(r"]\s*(.*)", full_text)
            rank_match = re.search(r"\[(?:[^\]]+-)?(\d+)\]", full_text) # Handles formats like [ENG P-1] or [1]
            if name_match: data["name"] = name_match.group(1).strip()
            if rank_match: data["ranking"] = rank_match.group(1)
        else: 
            # Fallback if no <a> tag, try to get from the whole header text
            header_text_no_link = header_row_found.get_text(separator=" ", strip=True)
            name_match_nl = re.search(r"]\s*(.*)", header_text_no_link)
            if name_match_nl: data["name"] = name_match_nl.group(1).strip()
            rank_match_nl = re.search(r"\[(?:[^\]]+-)?(\d+)\]", header_text_no_link)
            if rank_match_nl: data["ranking"] = rank_match_nl.group(1)

    # Find rows containing "FT" (Full Time) statistics
    ft_rows_cells_list = []
    current_section_is_ft = False
    for row in team_table_soup.find_all("tr", align="center"): 
        th_cell = row.find("th") # Section headers like "FT", "HT" are usually in <th>
        if th_cell:
            th_text = th_cell.get_text(strip=True)
            if "FT" in th_text: 
                current_section_is_ft = True
            elif "HT" in th_text: # Stop if we reach Half Time stats, as we only want FT
                current_section_is_ft = False
                break 
        
        if current_section_is_ft:
            cells = row.find_all("td")
            # Valid stats rows usually start with "Total", "Home", or "Away" in the first cell
            if cells and len(cells) > 0 and cells[0].get_text(strip=True) in ["Total", "Home", "Away"]:
                ft_rows_cells_list.append(cells)

    if not ft_rows_cells_list:
        data["standings_status"] = "Warning: No Full-Time (FT) statistics rows found in the table."
        return data

    # Process the found FT statistics rows
    parsed_stats = False
    for cells_in_row in ft_rows_cells_list:
        if len(cells_in_row) > 8: # Expecting at least Type, PJ, V, E, D, GF, GC, Pts, % (9 cells)
            row_type_text = cells_in_row[0].get_text(strip=True)
            # Extract stats: PJ, V, E, D, GF, GC (Indices 1 to 6)
            # Ensure text is extracted and defaults to "N/A" if cell is empty
            stats_values = [(cells_in_row[i].get_text(strip=True) if cells_in_row[i].get_text(strip=True) else "N/A") for i in range(1, 7)]
            pj, v, e, d, gf, gc = stats_values

            if row_type_text == "Total":
                data["total_pj"], data["total_v"], data["total_e"], data["total_d"], data["total_gf"], data["total_gc"] = pj,v,e,d,gf,gc
                parsed_stats = True
            # Store specific stats (Home/Away) based on which table type we are parsing
            elif row_type_text == "Home" and is_home_team_table_type:
                data["specific_pj"],data["specific_v"],data["specific_e"],data["specific_d"],data["specific_gf"],data["specific_gc"] = pj,v,e,d,gf,gc
                parsed_stats = True
            elif row_type_text == "Away" and not is_home_team_table_type: # i.e., parsing guest_div and row is "Away"
                data["specific_pj"],data["specific_v"],data["specific_e"],data["specific_d"],data["specific_gf"],data["specific_gc"] = pj,v,e,d,gf,gc
                parsed_stats = True
    
    if parsed_stats:
        data["standings_status"] = "Success: Standings data extracted."
    else:
        data["standings_status"] = "Warning: Relevant statistics rows (Total/Home/Away) not found or parsed."
        
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
    if not main_home_team_name or not main_away_team_name:
        return ah1, res1, res1_raw, ah6, res6, res6_raw

    for row_h2h in h2h_table.find_all("tr", id=re.compile(r"tr3_\d+")):
        details = get_match_details_from_row_of(row_h2h, score_class_selector='fscore_3', source_table_type='h2h')
        if not details: continue
        if current_league_id and details.get('league_id_hist') and details.get('league_id_hist') != str(current_league_id): continue
        filtered_h2h_list.append(details)
    if not filtered_h2h_list: return ah1, res1, res1_raw, ah6, res6, res6_raw
    
    # Para AH6 y RES6 (General H2H), tomamos el primer partido de la lista filtrada (el más reciente)
    # sin importar quién fue local o visitante en ese partido específico.
    if filtered_h2h_list:
        h2h_general_match = filtered_h2h_list[0] # El más reciente H2H general
        ah6 = h2h_general_match.get('ahLine', '-') 
        res6 = h2h_general_match.get('score', '?*?'); res6_raw = h2h_general_match.get('score_raw', '?-?')
    
    # Para AH1 y RES1 (Local en Casa), buscamos el partido más reciente donde main_home_team_name fue LOCAL
    h2h_local_specific_match = None
    for d_h2h in filtered_h2h_list:
        # Comparamos ignorando mayúsculas/minúsculas
        if d_h2h.get('home','').lower() == main_home_team_name.lower() and \
           d_h2h.get('away','').lower() == main_away_team_name.lower():
            h2h_local_specific_match = d_h2h
            break # Encontramos el más reciente donde el equipo principal fue local
            
    if h2h_local_specific_match:
        ah1 = h2h_local_specific_match.get('ahLine', '-') 
        res1 = h2h_local_specific_match.get('score', '?*?'); res1_raw = h2h_local_specific_match.get('score_raw', '?-?')
    elif filtered_h2h_list: # Si no hay H2H con el equipo principal como local, AH1 y RES1 podrían quedar como '-' o tomar el general
        # Decisión de diseño: si no hay un H2H específico como local, ¿AH1/RES1 deben ser '-' o reflejar el general?
        # Por ahora, se quedan como '-' si no hay un partido específico como local.
        pass

    return ah1, res1, res1_raw, ah6, res6, res6_raw

def extract_comparative_match_of(soup_for_team_history, table_id_of_team_to_search, team_name_to_find_match_for, opponent_name_to_search, current_league_id, is_home_table):
    if not opponent_name_to_search or opponent_name_to_search == "N/A" or not team_name_to_find_match_for:
        return "-" # Devuelve solo el AH formateado o "-"
        
    table = soup_for_team_history.find("table", id=table_id_of_team_to_search)
    if not table: return "-"
    
    # Determinar el selector de clase para el score basado en si es tabla local o visitante
    # Esto es importante porque get_match_details_from_row_of usa este selector.
    score_class_selector = 'fscore_1' if is_home_table else 'fscore_2'
    
    for row in table.find_all("tr", id=re.compile(rf"tr{table_id_of_team_to_search[-1]}_\d+")):
        # Asegurarse de pasar el source_table_type correcto a get_match_details_from_row_of
        details = get_match_details_from_row_of(row, score_class_selector=score_class_selector, source_table_type='hist')
        if not details: continue
        
        # Filtrar por liga si se proporciona current_league_id
        if current_league_id and details.get('league_id_hist') and details.get('league_id_hist') != str(current_league_id):
            continue
            
        home_hist = details.get('home','').lower()
        away_hist = details.get('away','').lower()
        team_main_lower = team_name_to_find_match_for.lower()
        opponent_lower = opponent_name_to_search.lower()
        
        # Comprobar si el partido es entre el equipo principal y el oponente buscado
        is_match_of_interest = (team_main_lower == home_hist and opponent_lower == away_hist) or \
                               (team_main_lower == away_hist and opponent_lower == home_hist)
                               
        if is_match_of_interest:
            ah_line_extracted = details.get('ahLine', '-') # Este es el AH formateado
            return ah_line_extracted # Devolver solo el valor de AH formateado
            
    return "-" # Si no se encuentra el partido o el AH

# --- STREAMLIT APP UI (Función principal del módulo) ---
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

    st.markdown("<h2 class='sub-title'>Herramienta de Análisis OF</h2>", unsafe_allow_html=True)

    st.sidebar.image("https://raw.githubusercontent.com/streamlit/docs/main/public/images/brand/streamlit-logo-secondary-colormark-darktext.svg", width=200)
    st.sidebar.title("⚙️ Configuración del Partido (OF)")
    main_match_id_str_input_of = st.sidebar.text_input(
        "🆔 ID Partido Principal:", 
        value="2696131", # Ejemplo de ID, el usuario puede cambiarlo
        help="Pega el ID numérico del partido que deseas analizar.", 
        key="other_feature_match_id_input"
    )
    analizar_button_of = st.sidebar.button("🚀 Analizar Partido (OF)", type="primary", use_container_width=True)

    if analizar_button_of:
        if main_match_id_str_input_of.isdigit():
            match_id = int(main_match_id_str_input_of)
            
            st.markdown(f"<div class='card'><div class='card-title'>Análisis para el Partido ID: {match_id}</div>", unsafe_allow_html=True)
            
            status_placeholder = st.empty()
            results_placeholder = st.container()

            status_placeholder.info(f"🚀 Iniciando análisis para el partido ID: {match_id}...")
            
            driver = None # Inicializar driver a None
            try:
                # No necesitamos Selenium para la parte inicial si usamos requests para H2H
                # status_placeholder.info("🔄 Obteniendo driver de Selenium...")
                # driver = get_selenium_driver_of() # Solo obtener si es estrictamente necesario

                # if driver: # Quitado temporalmente, ya que fetch_soup_requests_of no lo necesita
                status_placeholder.info("✅ Accediendo a la página H2H del partido con Requests...")
                
                # 1. Obtener la página H2H usando requests (más rápido para el parseo inicial)
                h2h_page_path = f"/match/h2h-{match_id}"
                main_h2h_soup = fetch_soup_requests_of(h2h_page_path)

                if not main_h2h_soup:
                    status_placeholder.error(f"❌ No se pudo obtener la página H2H para el ID {match_id} con requests.")
                    results_placeholder.markdown("</div>", unsafe_allow_html=True) # Cerrar card
                    # if driver: driver.quit() # Asegurarse de cerrar si se abrió
                    return

                status_placeholder.info("🔍 Extrayendo información básica del partido desde la página H2H...")
                home_id, away_id, league_id, home_name, away_name, league_name = get_team_league_info_from_script_of(main_h2h_soup)
                
                if home_name == "N/A" or away_name == "N/A":
                    status_placeholder.warning(f"⚠️ No se pudieron extraer los nombres de los equipos de la página H2H. Verifique el ID del partido o intente con Selenium si es necesario.")
                    # Aquí se podría añadir un fallback a Selenium si Requests falla en obtener nombres
                    # Por ahora, se asume que si _matchInfo está, los nombres son correctos.
                    # Si no, el análisis podría detenerse o continuar con "N/A".
                    # Para este ejemplo, si no hay nombres, es difícil continuar con las comparativas.
                    if not driver: # Obtener driver solo si es necesario para el fallback
                        status_placeholder.info("🔄 Intentando obtener nombres con Selenium como fallback...")
                        driver = get_selenium_driver_of()
                    if driver:
                        live_page_url = f"{BASE_URL_OF}/match/live-{match_id}"
                        driver.get(live_page_url)
                        try:
                            WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS_OF).until(EC.presence_of_element_located((By.ID, "fbheader"))) # Esperar cabecera
                            live_soup_selenium = BeautifulSoup(driver.page_source, "html.parser")
                            home_id, away_id, league_id, home_name, away_name, league_name = get_team_league_info_from_script_of(live_soup_selenium)
                        except TimeoutException:
                            status_placeholder.error(f"❌ Timeout obteniendo página live con Selenium.")
                            home_name, away_name = "N/A", "N/A" # Resetear si falla
                    else:
                        status_placeholder.error("❌ Driver de Selenium no disponible para fallback.")
                        
                    if home_name == "N/A" or away_name == "N/A":
                        status_placeholder.error(f"❌ No se pudieron extraer los nombres de los equipos. Análisis detenido.")
                        results_placeholder.markdown("</div>", unsafe_allow_html=True) # Cerrar card
                        if driver: driver.quit()
                        return


                results_placeholder.markdown(f"**Partido:** <span class='home-color'>{home_name}</span> vs <span class='away-color'>{away_name}</span>", unsafe_allow_html=True)
                results_placeholder.markdown(f"**Liga:** {league_name} (ID: {league_id or 'N/A'})")
                results_placeholder.markdown(f"**ID Equipos:** Local ({home_id or 'N/A'}), Visitante ({away_id or 'N/A'})")
                results_placeholder.markdown("---")


                # 2. Extraer H2H directos (AH1, RES1, AH6, RES6) de main_h2h_soup
                status_placeholder.info(f"🆚 Extrayendo H2H directos entre {home_name} y {away_name}...")
                ah1, res1, res1_raw, ah6, res6, res6_raw = extract_h2h_data_of(main_h2h_soup, home_name, away_name, league_id)
                
                # Mostrar en expander "Hándicaps y Resultados Clave"
                with results_placeholder.expander("🔰 Hándicaps y Resultados Clave (Estilo Script Original)", expanded=True):
                    st.subheader("Enfrentamientos Directos (H2H)")
                    col_h2h1, col_h2h2 = st.columns(2)
                    col_h2h1.metric(label="AH H2H (Local en Casa)", value=ah1)
                    col_h2h2.metric(label="Res H2H (Local en Casa)", value=res1_raw.replace('-', ':') if res1_raw != "?-?" else "N/A") 
                    col_h2h3, col_h2h4 = st.columns(2)
                    col_h2h3.metric(label="AH H2H (General)", value=ah6)
                    col_h2h4.metric(label="Res H2H (General)", value=res6_raw.replace('-', ':') if res6_raw != "?-?" else "N/A")


                # 3. Obtener rivales para H2H indirecto y el ID del partido clave
                status_placeholder.info("🔗 Obteniendo rivales para H2H indirecto...")
                # Estas funciones usan fetch_soup_requests_of, no necesitan Selenium driver
                key_match_id_h2h_rival_a, rival_a_id, rival_a_name = get_rival_a_for_original_h2h_of(match_id) 
                key_match_id_h2h_rival_b, rival_b_id, rival_b_name = get_rival_b_for_original_h2h_of(match_id) 

                # Mostrar en expander "Comparativas Indirectas Detalladas"
                with results_placeholder.expander("🔍 Comparativas Indirectas Detalladas", expanded=True):
                    col_comp1, col_comp2 = st.columns(2)
                    
                    with col_comp1:
                        st.markdown(f"**<span class='home-color'>{home_name}</span> vs. Últ. Rival del <span class='away-color'>{away_name}</span>**", unsafe_allow_html=True)
                        if rival_b_name and rival_b_name != "N/A":
                            st.caption(f"Partido de {home_name} contra el último equipo al que se enfrentó {away_name} ({rival_b_name}).")
                            ah_comp_home_vs_rival_away = extract_comparative_match_of(main_h2h_soup, "table_v1", home_name, rival_b_name, league_id, is_home_table=True)
                            st.metric(label=f"AH ({home_name} vs {rival_b_name})", value=ah_comp_home_vs_rival_away)
                        else:
                            st.metric(label=f"AH (Partido Comparado)", value="-")
                            st.caption(f"No se encontró un rival común reciente para {away_name} o datos insuficientes.")

                    with col_comp2:
                        st.markdown(f"**<span class='away-color'>{away_name}</span> vs. Últ. Rival del <span class='home-color'>{home_name}</span>**", unsafe_allow_html=True)
                        if rival_a_name and rival_a_name != "N/A":
                            st.caption(f"Partido de {away_name} contra el último equipo al que se enfrentó {home_name} ({rival_a_name}).")
                            ah_comp_away_vs_rival_home = extract_comparative_match_of(main_h2h_soup, "table_v2", away_name, rival_a_name, league_id, is_home_table=False)
                            st.metric(label=f"AH ({away_name} vs {rival_a_name})", value=ah_comp_away_vs_rival_home)
                        else:
                            st.metric(label=f"AH (Partido Comparado)", value="-")
                            st.caption(f"No se encontró un rival común reciente para {home_name} o datos insuficientes.")
                
                status_placeholder.success("🎉 Análisis completado con la información disponible.")
                # else: # Corresponde al if driver inicial que fue comentado/quitado
                    # status_placeholder.error("❌ No se pudo inicializar el driver de Selenium donde era necesario.")
            except Exception as e:
                st.exception(e) 
                status_placeholder.error(f"❌ Error durante el análisis: {type(e).__name__} - {e}")
            finally:
                if driver: # Asegurarse de cerrar el driver si se llegó a inicializar
                    driver.quit()
            
            results_placeholder.markdown("</div>", unsafe_allow_html=True) # Cierre del card principal

        else:
            st.sidebar.error("Por favor, introduce un ID de partido numérico válido.")
    else:
        st.info("ℹ️ Introduce un ID de partido en la barra lateral y haz clic en 'Analizar Partido (OF)' para comenzar.")

# Opcional: para poder probar este módulo directamente
# if __name__ == "__main__":
#     st.set_page_config(layout="wide", page_title="Test Módulo OF")
#     display_other_feature_ui()
