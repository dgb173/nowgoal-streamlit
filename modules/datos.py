# modules/datos.py
import streamlit as st
import time
import requests
import re
import math
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd
import threading # Añadido para el ejemplo de concurrencia

# Importaciones de Selenium
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, ElementClickInterceptedException, NoSuchElementException

# --- CONFIGURACIÓN GLOBAL ---
BASE_URL_OF = "https://live18.nowgoal25.com"
SELENIUM_TIMEOUT_SECONDS_OF = 15 # Ajustado de la sugerencia anterior
SELENIUM_POLL_FREQUENCY_OF = 0.4 # Ajustado de la sugerencia anterior
PLACEHOLDER_NODATA = "---" # Placeholder más corto

# --- FUNCIONES HELPER PARA PARSEO Y FORMATEO ---
def parse_ah_to_number_of(ah_line_str: str):
    if not isinstance(ah_line_str, str): return None
    s = ah_line_str.strip().replace(' ', '')
    if not s or s in ['-', '?']: return None
    original_starts_with_minus = ah_line_str.strip().startswith('-')
    try:
        if '/' in s:
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
        else:
            return float(s)
    except ValueError:
        return None

def format_ah_as_decimal_string_of(ah_line_str: str, for_sheets=False):
    if not isinstance(ah_line_str, str) or not ah_line_str.strip() or ah_line_str.strip() in ['-', '?']:
        return ah_line_str.strip() if isinstance(ah_line_str, str) and ah_line_str.strip() in ['-','?'] else PLACEHOLDER_NODATA # Usar nuevo placeholder

    numeric_value = parse_ah_to_number_of(ah_line_str)
    if numeric_value is None:
        return ah_line_str.strip() if ah_line_str.strip() in ['-','?'] else PLACEHOLDER_NODATA # Usar nuevo placeholder

    if numeric_value == 0.0: return "0"

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
        if len(cells) < 12: return None
        league_id_hist_attr = row_element.get('name')
        home_idx, score_idx, away_idx, ah_idx = 2, 3, 4, 11
        home_tag = cells[home_idx].find('a'); home = home_tag.text.strip() if home_tag else cells[home_idx].text.strip()
        away_tag = cells[away_idx].find('a'); away = away_tag.text.strip() if away_tag else cells[away_idx].text.strip()
        score_cell_content = cells[score_idx].text.strip()
        score_span = cells[score_idx].find('span', class_=lambda x: x and score_class_selector in x)
        score_raw_text = score_span.text.strip() if score_span else score_cell_content
        score_m = re.match(r'(\d+-\d+)', score_raw_text); score_raw = score_m.group(1) if score_m else '?-?'
        score_fmt = score_raw.replace('-', ':') if score_raw != '?-?' else '?:?'
        ah_line_raw_text = cells[ah_idx].text.strip()
        ah_line_fmt = format_ah_as_decimal_string_of(ah_line_raw_text)
        match_id = row_element.get('index')
        if not home or not away: return None
        return {'home': home, 'away': away, 'score': score_fmt, 'score_raw': score_raw,
                'ahLine': ah_line_fmt, 'ahLine_raw': ah_line_raw_text,
                'matchIndex': match_id, 'vs': row_element.get('vs'),
                'league_id_hist': league_id_hist_attr}
    except Exception: return None

# --- SESIÓN Y FETCHING ---
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
        except requests.RequestException as e:
            # st.error(f"Request failed for {url}: {e}") # Debug
            if attempt == max_tries: return None
            time.sleep(delay * attempt)
    return None

# --- FUNCIONES DE ESTADÍSTICAS DE PROGRESIÓN (MODIFICADAS PARA NO ANIDAR EXPANDERS) ---
@st.cache_data(ttl=7200)
def get_match_progression_stats_data_simplified(match_id: str) -> pd.DataFrame | None: # MODIFICADO el nombre y contenido
    base_url_live = "https://live18.nowgoal25.com/match/live-"
    full_url = f"{base_url_live}{match_id}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
        "Accept-Encoding": "gzip, deflate, br", "Accept-Language": "en-US,en;q=0.9", "DNT": "1",
        "Connection": "keep-alive", "Upgrade-Insecure-Requests": "1",
    }
    # MODIFICADO: Solo las estadísticas de interés
    stat_titles_of_interest = {
        "Shots": {"Home": PLACEHOLDER_NODATA, "Away": PLACEHOLDER_NODATA},
        "Shots on Goal": {"Home": PLACEHOLDER_NODATA, "Away": PLACEHOLDER_NODATA},
        "Dangerous Attacks": {"Home": PLACEHOLDER_NODATA, "Away": PLACEHOLDER_NODATA},
    }
    try:
        response = requests.get(full_url, headers=headers, timeout=10) # Timeout reducido
        response.raise_for_status()
        html_content = response.text
        soup = BeautifulSoup(html_content, 'lxml')
        team_tech_div = soup.find('div', id='teamTechDiv_detail')
        if team_tech_div:
            stat_list = team_tech_div.find('ul', class_='stat')
            if stat_list:
                for li in stat_list.find_all('li'):
                    title_span = li.find('span', class_='stat-title')
                    if title_span:
                        stat_title = title_span.get_text(strip=True)
                        if stat_title in stat_titles_of_interest:
                            values = li.find_all('span', class_='stat-c')
                            if len(values) == 2:
                                stat_titles_of_interest[stat_title]["Home"] = values[0].get_text(strip=True) or PLACEHOLDER_NODATA
                                stat_titles_of_interest[stat_title]["Away"] = values[1].get_text(strip=True) or PLACEHOLDER_NODATA
    except Exception: # Silencioso para no romper UI si una stat falla
        return None
    
    table_rows = []
    for name, vals in stat_titles_of_interest.items():
        table_rows.append({"Estadistica_EN": name, "Casa": vals['Home'], "Fuera": vals['Away']})

    df = pd.DataFrame(table_rows)
    return df.set_index("Estadistica_EN") if not df.empty else df


# --- FUNCIONES DE EXTRACCIÓN DE DATOS DEL PARTIDO (Selenium y BeautifulSoup) ---
# (Resto de funciones de extracción: get_rival_a_for_original_h2h_of, get_rival_b_for_original_h2h_of, 
#  get_selenium_driver_of, get_h2h_details_for_original_logic_of, get_team_league_info_from_script_of,
#  click_element_robust_of, extract_last_match_in_league_of, get_main_match_odds_selenium_of,
#  extract_standings_data_from_h2h_page_of, extract_final_score_of, extract_h2h_data_of,
#  extract_comparative_match_of SE MANTIENEN IGUAL QUE EN TU ÚLTIMA VERSIÓN FUNCIONAL)

# ... (COPIA AQUÍ TODAS LAS FUNCIONES DE EXTRACCIÓN DESDE get_rival_a_for_original_h2h_of HASTA extract_comparative_match_of)
# Asegúrate de que la indentación y la sintaxis sean correctas
# (Función get_selenium_driver_of se mantiene)
@st.cache_resource
def get_selenium_driver_of():
    options = ChromeOptions(); options.add_argument("--headless"); options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage"); options.add_argument("--disable-gpu")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36")
    options.add_argument('--blink-settings=imagesEnabled=false'); options.add_argument("--window-size=1920,1080")
    try: return webdriver.Chrome(options=options)
    except WebDriverException as e: st.error(f"Error inicializando Selenium driver (OF): {e}"); return None

@st.cache_data(ttl=3600)
def get_rival_a_for_original_h2h_of(main_match_id: int): # Asegúrate que esté aquí
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
def get_rival_b_for_original_h2h_of(main_match_id: int): # Asegúrate que esté aquí
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

def get_h2h_details_for_original_logic_of(driver_instance, key_match_id_for_h2h_url, rival_a_id, rival_b_id, rival_a_name="Rival A", rival_b_name="Rival B"):
    if not driver_instance: return {"status": "error", "resultado": "N/A (Driver no disponible H2H OF)"}
    if not key_match_id_for_h2h_url or not rival_a_id or not rival_b_id: return {"status": "error", "resultado": f"N/A (IDs incompletos para H2H {rival_a_name} vs {rival_b_name})"}
    url_to_visit = f"{BASE_URL_OF}/match/h2h-{key_match_id_for_h2h_url}"
    try:
        current_url = driver_instance.current_url
        if key_match_id_for_h2h_url not in current_url : # Evita recargar si ya está en una página similar (optimización ligera)
            driver_instance.get(url_to_visit)
        WebDriverWait(driver_instance, SELENIUM_TIMEOUT_SECONDS_OF, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.presence_of_element_located((By.ID, "table_v2")))
        time.sleep(0.3) # Reducido
        soup_selenium = BeautifulSoup(driver_instance.page_source, "html.parser")
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
            if not score_span or not score_span.text or "-" not in score_span.text: continue # o '-'
            score_val = score_span.text.strip().split("(")[0].strip(); g_h, g_a = score_val.split("-", 1) # o '-'
            tds = row.find_all("td"); handicap_raw = PLACEHOLDER_NODATA; HANDICAP_TD_IDX = 11
            if len(tds) > HANDICAP_TD_IDX:
                cell = tds[HANDICAP_TD_IDX]; d_o = cell.get("data-o")
                handicap_raw = d_o.strip() if d_o and d_o.strip() not in ["", "-"] else (cell.text.strip() if cell.text.strip() not in ["", "-"] else PLACEHOLDER_NODATA)

            match_id_h2h_rivals = row.get('index')
            rol_a_in_this_h2h = "H" if h2h_row_home_id == str(rival_a_id) else "A"

            return {"status": "found", "goles_home": g_h.strip(), "goles_away": g_a.strip(),
                    "handicap": handicap_raw, "rol_rival_a": rol_a_in_this_h2h,
                    "h2h_home_team_name": links[0].text.strip(),
                    "h2h_away_team_name": links[1].text.strip(),
                    "match_id": match_id_h2h_rivals}
    return {"status": "not_found", "resultado": f"H2H ({rival_a_name} vs {rival_b_name}) no encontrado."}


def get_team_league_info_from_script_of(soup):
    home_id, away_id, league_id, home_name, away_name, league_name = (None,)*3 + (PLACEHOLDER_NODATA,)*3
    script_tag = soup.find("script", string=re.compile(r"var _matchInfo ="))
    if script_tag and script_tag.string:
        script_content = script_tag.string
        h_id_m = re.search(r"hId:\s*parseInt\('(\d+)'\)", script_content); g_id_m = re.search(r"gId:\s*parseInt\('(\d+)'\)", script_content)
        sclass_id_m = re.search(r"sclassId:\s*parseInt\('(\d+)'\)", script_content); h_name_m = re.search(r"hName:\s*'([^']*)'", script_content)
        g_name_m = re.search(r"gName:\s*'([^']*)'", script_content); l_name_m = re.search(r"lName:\s*'([^']*)'", script_content)
        if h_id_m: home_id = h_id_m.group(1)
        if g_id_m: away_id = g_id_m.group(1)
        if sclass_id_m: league_id = sclass_id_m.group(1)
        if h_name_m: home_name = h_name_m.group(1).replace("\\'", "'") or PLACEHOLDER_NODATA
        if g_name_m: away_name = g_name_m.group(1).replace("\\'", "'") or PLACEHOLDER_NODATA
        if l_name_m: league_name = l_name_m.group(1).replace("\\'", "'") or PLACEHOLDER_NODATA
    return home_id, away_id, league_id, home_name, away_name, league_name

def click_element_robust_of(driver, by, value, timeout=5): # Timeout reducido para clics
    try:
        element = WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.presence_of_element_located((by, value)))
        # WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.visibility_of(element)) # A veces visibility falla aunque sea clickeable
        driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'center'});", element); time.sleep(0.15) # sleep reducido
        WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.element_to_be_clickable((by, value))).click()
        return True
    except (ElementClickInterceptedException, TimeoutException):
        try:
            # st.sidebar.warning(f"Click interceptado, intentando JS click en {value}")
            driver.execute_script("arguments[0].click();", element) # Fallback
            return True
        except Exception: return False # Fallo JS click
    except Exception: return False

def extract_last_match_in_league_of(driver, table_css_id_str, main_team_name_in_table, league_id_filter_value, home_or_away_filter_css_selector, is_home_game_filter):
    try:
        # Los clics de filtro se vuelven más críticos. WebDriverWait dentro de click_element_robust_of debe ser suficiente.
        # Quitando sleeps explícitos aquí.
        if league_id_filter_value:
            league_checkbox_selector = f"input#checkboxleague{table_css_id_str[-1]}[value='{league_id_filter_value}']"
            if not click_element_robust_of(driver, By.CSS_SELECTOR, league_checkbox_selector): return None
            time.sleep(0.2) # Pequeña pausa para que JS actualice tabla
            
        if not click_element_robust_of(driver, By.CSS_SELECTOR, home_or_away_filter_css_selector): return None
        time.sleep(0.2) # Pequeña pausa para que JS actualice tabla

        page_source_updated = driver.page_source; soup_updated = BeautifulSoup(page_source_updated, "html.parser")
        table = soup_updated.find("table", id=table_css_id_str)
        if not table: return None

        count_visible_rows = 0
        for row in table.find_all("tr", id=re.compile(rf"tr{table_css_id_str[-1]}_\d+")):
            if row.get("style") and "display:none" in row.get("style","").lower(): continue
            count_visible_rows +=1
            if count_visible_rows > 10: break # Limitar búsqueda
            
            # if league_id_filter_value and row.get("name") != str(league_id_filter_value): continue # Esta verificación podría ser redundante si JS oculta bien

            tds = row.find_all("td");
            if len(tds) < 14: continue

            home_team_row_el = tds[2].find("a"); away_team_row_el = tds[4].find("a")
            if not home_team_row_el or not away_team_row_el: continue

            home_team_row_name = home_team_row_el.text.strip(); away_team_row_name = away_team_row_el.text.strip()
            team_is_home_in_row = main_team_name_in_table.lower() == home_team_row_name.lower()
            team_is_away_in_row = main_team_name_in_table.lower() == away_team_row_name.lower()

            if (is_home_game_filter and team_is_home_in_row) or \
               (not is_home_game_filter and team_is_away_in_row):
                date_span = tds[1].find("span", {"name": "timeData"}); date_val = date_span.text.strip() if date_span else "N/A"
                score_class_re = re.compile(r"fscore_"); score_span_val = tds[3].find("span", class_=score_class_re); score_val = score_span_val.text.strip() if score_span_val else "N/A"
                handicap_cell = tds[11]; handicap_raw_val = handicap_cell.get("data-o", handicap_cell.text.strip())
                
                handicap_raw_val = handicap_raw_val.strip() if handicap_raw_val and handicap_raw_val.strip() not in ["", "-"] else PLACEHOLDER_NODATA
                match_id_val = row.get('index')
                
                return {"date": date_val, "home_team": home_team_row_name,
                        "away_team": away_team_row_name,"score": score_val,
                        "handicap_line_raw": handicap_raw_val,
                        "match_id": match_id_val}
        return None
    except Exception: # e
        # st.error(f"Error en extract_last_match_in_league_of: {e}")
        return None


def get_main_match_odds_selenium_of(driver):
    odds_info = {"ah_home_cuota": PLACEHOLDER_NODATA, "ah_linea_raw": PLACEHOLDER_NODATA, "ah_away_cuota": PLACEHOLDER_NODATA, 
                 "goals_over_cuota": PLACEHOLDER_NODATA, "goals_linea_raw": PLACEHOLDER_NODATA, "goals_under_cuota": PLACEHOLDER_NODATA}
    try:
        live_compare_div = WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS_OF - 5, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until( # Timeout menor para odds
            EC.presence_of_element_located((By.ID, "liveCompareDiv"))
        )
        
        # Buscar Bet365 por ID. Intentar con los más comunes primero.
        bet365_ids = ["tr_o_1_8", "tr_o_1_31", "tr_o_1_1_8", "tr_o_1_1_31"] # Ampliar si es necesario
        bet365_early_odds_row = None
        
        for b_id in bet365_ids:
            try:
                row_candidate = live_compare_div.find_element(By.CSS_SELECTOR, f"tr#{b_id}[name='earlyOdds']")
                if row_candidate.is_displayed(): # Comprobar si es visible
                    bet365_early_odds_row = row_candidate
                    break
            except NoSuchElementException:
                continue # Probar el siguiente ID
        
        if not bet365_early_odds_row:
             # st.sidebar.warning("Fila Bet365 (earlyOdds) no encontrada.")
             return odds_info

        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", bet365_early_odds_row); time.sleep(0.1) # Scroll y pequeña pausa
        
        tds = bet365_early_odds_row.find_elements(By.TAG_NAME, "td")

        if len(tds) >= 11:
            odds_info["ah_home_cuota"] = tds[2].get_attribute("data-o") or tds[2].text.strip() or PLACEHOLDER_NODATA
            odds_info["ah_linea_raw"] = tds[3].get_attribute("data-o") or tds[3].text.strip() or PLACEHOLDER_NODATA
            odds_info["ah_away_cuota"] = tds[4].get_attribute("data-o") or tds[4].text.strip() or PLACEHOLDER_NODATA
            odds_info["goals_over_cuota"] = tds[8].get_attribute("data-o") or tds[8].text.strip() or PLACEHOLDER_NODATA
            odds_info["goals_linea_raw"] = tds[9].get_attribute("data-o") or tds[9].text.strip() or PLACEHOLDER_NODATA
            odds_info["goals_under_cuota"] = tds[10].get_attribute("data-o") or tds[10].text.strip() or PLACEHOLDER_NODATA
    except TimeoutException:
        # st.sidebar.warning("Timeout buscando 'liveCompareDiv' para cuotas.")
        pass # Fallo silencioso para no interrumpir todo el script
    except Exception: # e
        # st.sidebar.error(f"Error extrayendo cuotas: {e}")
        pass
    return odds_info

def extract_standings_data_from_h2h_page_of(h2h_soup, target_team_name_exact):
    data = {
        "name": target_team_name_exact, "ranking": PLACEHOLDER_NODATA,
        "total_pj": PLACEHOLDER_NODATA, "total_v": PLACEHOLDER_NODATA, "total_e": PLACEHOLDER_NODATA, "total_d": PLACEHOLDER_NODATA, "total_gf": PLACEHOLDER_NODATA, "total_gc": PLACEHOLDER_NODATA,
        "specific_pj": PLACEHOLDER_NODATA, "specific_v": PLACEHOLDER_NODATA, "specific_e": PLACEHOLDER_NODATA, "specific_d": PLACEHOLDER_NODATA, "specific_gf": PLACEHOLDER_NODATA, "specific_gc": PLACEHOLDER_NODATA,
        "specific_type": "N/A"
    }
    if not h2h_soup or not target_team_name_exact: return data

    standings_section = h2h_soup.find("div", id="porletP4")
    if not standings_section: return data

    team_table_soup = None
    is_home_table_type = False

    home_div = standings_section.find("div", class_="home-div")
    if home_div:
        header_tr = home_div.find("tr", class_="team-home")
        if header_tr and header_tr.find("a") and target_team_name_exact.lower() in header_tr.find("a").get_text(strip=True).lower():
            team_table_soup = home_div.find("table", class_="team-table-home")
            is_home_table_type = True
            data["specific_type"] = "Local (Liga)"

    if not team_table_soup:
        guest_div = standings_section.find("div", class_="guest-div")
        if guest_div:
            header_tr = guest_div.find("tr", class_="team-guest")
            if header_tr and header_tr.find("a") and target_team_name_exact.lower() in header_tr.find("a").get_text(strip=True).lower():
                team_table_soup = guest_div.find("table", class_="team-table-guest")
                is_home_table_type = False
                data["specific_type"] = "Visitante (Liga)"

    if not team_table_soup: return data

    header_link = team_table_soup.find("tr", class_=re.compile(r"team-(home|guest)")).find("a")
    if header_link:
        full_text = header_link.get_text(separator=" ", strip=True)
        name_match = re.search(r"]\s*(.*)", full_text)
        rank_match = re.search(r"\[(?:[^\]]+-)?(\d+)\]", full_text)
        if name_match: data["name"] = name_match.group(1).strip()
        if rank_match: data["ranking"] = rank_match.group(1)

    in_ft_section = False
    for row in team_table_soup.find_all("tr", align="center"):
        th_header = row.find("th")
        if th_header:
            if "FT" in th_header.get_text(strip=True): in_ft_section = True; continue
            elif "HT" in th_header.get_text(strip=True): in_ft_section = False; break
        if in_ft_section:
            cells = row.find_all("td")
            if not cells or len(cells) < 7: continue
            row_type_text_container = cells[0].find("span") if cells[0].find("span") else cells[0]
            row_type_text = row_type_text_container.get_text(strip=True)
            stats_values = [cell.get_text(strip=True) or PLACEHOLDER_NODATA for cell in cells[1:7]]
            pj, v, e, d, gf, gc = stats_values[:6]
            if row_type_text == "Total":
                data.update({"total_pj": pj, "total_v": v, "total_e": e, "total_d": d, "total_gf": gf, "total_gc": gc})
            elif (row_type_text == "Home" and is_home_table_type) or (row_type_text == "Away" and not is_home_table_type):
                data.update({"specific_pj": pj, "specific_v": v, "specific_e": e, "specific_d": d, "specific_gf": gf, "specific_gc": gc})
    return data


def extract_final_score_of(soup):
    try:
        score_divs = soup.select('#mScore .end .score')
        if len(score_divs) == 2:
            hs = score_divs[0].text.strip(); aws = score_divs[1].text.strip()
            if hs.isdigit() and aws.isdigit(): return f"{hs}:{aws}", f"{hs}-{aws}"
    except Exception: pass
    return '?:?', "?-?"


def extract_h2h_data_of(soup, main_home_team_name, main_away_team_name, current_league_id):
    ah1, res1, res1_raw, match1_id = PLACEHOLDER_NODATA, '?:?', '?-?', None
    ah6, res6, res6_raw, match6_id = PLACEHOLDER_NODATA, '?:?', '?-?', None
    h2h_gen_home_name, h2h_gen_away_name = "Local (H2H Gen)", "Visitante (H2H Gen)"

    h2h_table = soup.find("table", id="table_v3")
    if not h2h_table: return ah1, res1, res1_raw, match1_id, ah6, res6, res6_raw, match6_id, h2h_gen_home_name, h2h_gen_away_name

    filtered_h2h_list = []
    if not main_home_team_name or not main_away_team_name or main_home_team_name == PLACEHOLDER_NODATA:
        return ah1, res1, res1_raw, match1_id, ah6, res6, res6_raw, match6_id, h2h_gen_home_name, h2h_gen_away_name

    for row_h2h in h2h_table.find_all("tr", id=re.compile(r"tr3_\d+")):
        details = get_match_details_from_row_of(row_h2h, score_class_selector='fscore_3', source_table_type='h2h')
        if not details: continue
        if current_league_id and details.get('league_id_hist') and details.get('league_id_hist') != str(current_league_id): continue
        filtered_h2h_list.append(details)

    if not filtered_h2h_list: return ah1, res1, res1_raw, match1_id, ah6, res6, res6_raw, match6_id, h2h_gen_home_name, h2h_gen_away_name

    h2h_general_match = filtered_h2h_list[0]
    ah6 = h2h_general_match.get('ahLine', PLACEHOLDER_NODATA)
    res6 = h2h_general_match.get('score', '?:?'); res6_raw = h2h_general_match.get('score_raw', '?-?')
    match6_id = h2h_general_match.get('matchIndex')
    h2h_gen_home_name = h2h_general_match.get('home', "Local (H2H Gen)")
    h2h_gen_away_name = h2h_general_match.get('away', "Visitante (H2H Gen)")

    h2h_local_specific_match = None
    for d_h2h in filtered_h2h_list:
        if d_h2h.get('home','').lower() == main_home_team_name.lower() and \
           d_h2h.get('away','').lower() == main_away_team_name.lower():
            h2h_local_specific_match = d_h2h; break
    if h2h_local_specific_match:
        ah1 = h2h_local_specific_match.get('ahLine', PLACEHOLDER_NODATA)
        res1 = h2h_local_specific_match.get('score', '?:?'); res1_raw = h2h_local_specific_match.get('score_raw', '?-?')
        match1_id = h2h_local_specific_match.get('matchIndex')
    return ah1, res1, res1_raw, match1_id, ah6, res6, res6_raw, match6_id, h2h_gen_home_name, h2h_gen_away_name

def extract_comparative_match_of(soup_for_team_history, table_id_of_team_to_search, team_name_to_find_match_for, opponent_name_to_search, current_league_id, is_home_table):
    if not opponent_name_to_search or opponent_name_to_search == PLACEHOLDER_NODATA or not team_name_to_find_match_for or team_name_to_find_match_for == PLACEHOLDER_NODATA:
        return None
    table = soup_for_team_history.find("table", id=table_id_of_team_to_search)
    if not table: return None
    score_class_selector = 'fscore_1' if is_home_table else 'fscore_2'
    for row in table.find_all("tr", id=re.compile(rf"tr{table_id_of_team_to_search[-1]}_\d+")):
        details = get_match_details_from_row_of(row, score_class_selector=score_class_selector, source_table_type='hist')
        if not details: continue
        if current_league_id and details.get('league_id_hist') and details.get('league_id_hist') != str(current_league_id): continue
        home_hist = details.get('home','').lower(); away_hist = details.get('away','').lower()
        team_main_lower = team_name_to_find_match_for.lower(); opponent_lower = opponent_name_to_search.lower()
        if (team_main_lower == home_hist and opponent_lower == away_hist) or \
           (team_main_lower == away_hist and opponent_lower == home_hist):
            return {"score": details.get('score', '?:?'), "ah_line": details.get('ahLine', PLACEHOLDER_NODATA),
                    "localia": 'H' if team_main_lower == home_hist else 'A', "home_team": details.get('home'),
                    "away_team": details.get('away'), "match_id": details.get('matchIndex')}
    return None

# --- STREAMLIT APP UI (Función principal) ---

# NUEVA FUNCIÓN PARA TARJETAS DE PARTIDO COMPACTAS
def display_compact_match_card(title, date, home_team, away_team, score, ah_line_raw, match_id, container):
    with container:
        st.markdown(f"<div class='compact-card-title'>{title}</div>", unsafe_allow_html=True)
        
        score_parts = score.split(':') if ':' in score else score.split('-') # Manejar ambos separadores
        home_score, away_score = (score_parts[0].strip(), score_parts[1].strip()) if len(score_parts) == 2 else ('?', '?')

        score_html = f"""
        <div class='match-score-line'>
            <span class='team-name home'>{home_team or 'Local'}</span>
            <span class='score-box'>{home_score} - {away_score}</span>
            <span class='team-name away'>{away_team or 'Visitante'}</span>
        </div>
        """
        st.markdown(score_html, unsafe_allow_html=True)
        
        ah_formatted = format_ah_as_decimal_string_of(ah_line_raw)
        st.markdown(f"<div class='match-ah-date'><span>AH: <span class='ah-value-compact'>{ah_formatted}</span></span> <span>📅 {date or PLACEHOLDER_NODATA}</span></div>", unsafe_allow_html=True)

        if match_id and match_id.isdigit():
            stats_df = get_match_progression_stats_data_simplified(match_id)
            if stats_df is not None and not stats_df.empty:
                
                # Preparar datos para la tabla HTML de estadísticas
                stats_display_map = {
                    "Shots": "Disparos",
                    "Shots on Goal": "D. Puerta",
                    "Dangerous Attacks": "A. Pelig."
                }
                
                stats_html_rows = ""
                for stat_key_en, stat_name_es in stats_display_map.items():
                    if stat_key_en in stats_df.index:
                        h_val = stats_df.loc[stat_key_en, 'Casa']
                        a_val = stats_df.loc[stat_key_en, 'Fuera']
                        
                        h_val_num, a_val_num = 0,0
                        try: h_val_num = int(h_val)
                        except: pass
                        try: a_val_num = int(a_val)
                        except: pass

                        h_color, a_color = "stat-neutral", "stat-neutral"
                        if h_val_num > a_val_num: h_color = "stat-better"; a_color = "stat-worse"
                        elif a_val_num > h_val_num: a_color = "stat-better"; h_color = "stat-worse"
                        
                        stats_html_rows += f"""
                        <tr>
                            <td class='stat-home-val {h_color}'>{h_val}</td>
                            <td class='stat-name'>{stat_name_es}</td>
                            <td class='stat-away-val {a_color}'>{a_val}</td>
                        </tr>
                        """
                    else:
                         stats_html_rows += f"""
                        <tr>
                            <td class='stat-home-val stat-neutral'>{PLACEHOLDER_NODATA}</td>
                            <td class='stat-name'>{stat_name_es}</td>
                            <td class='stat-away-val stat-neutral'>{PLACEHOLDER_NODATA}</td>
                        </tr>
                        """
                if stats_html_rows:
                    st.markdown(f"<div class='stats-table-title'>Estadísticas de Progresión:</div><table class='compact-stats-table'>{stats_html_rows}</table>", unsafe_allow_html=True)
            elif match_id:
                st.caption(f"_No se pudieron obtener estadísticas de progresión para ID: {match_id}_")
        st.markdown("<div class='compact-card-divider'></div>", unsafe_allow_html=True)

def display_other_feature_ui():
    # CSS para una UI más compacta y visual
    st.markdown("""
    <style>
        body { font-size: 0.9rem; } /* Reducir tamaño de fuente base */
        .main-title { font-size: 1.8em; font-weight: bold; color: #1E90FF; text-align: center; margin-bottom: 2px; }
        .sub-title { font-size: 1.2em; text-align: center; margin-bottom: 10px; }
        .section-header { font-size: 1.3em; font-weight: bold; color: #4682B4; margin-top: 15px; margin-bottom: 8px; border-bottom: 1px solid #ADC8E6; padding-bottom: 3px;}
        .card-title { font-size: 1.1em; font-weight: bold; color: #333; margin-bottom: 5px; }
        .card-subtitle { font-size: 1em; font-weight: bold; color: #555; margin-top:10px; margin-bottom: 5px; }
        .home-color { color: #007bff; font-weight: bold; }
        .away-color { color: #fd7e14; font-weight: bold; }
        .data-highlight { font-weight: bold; color: #c00000; } /* Rojo más oscuro */
        
        /* Estilos para tabla de clasificación compacta */
        .standings-table-compact p { margin-bottom: 0.1rem; font-size: 0.85em; line-height: 1.3;}
        .standings-table-compact strong { min-width: 30px; display: inline-block; font-weight: normal; color: #555;}
        .standings-table-compact .team-name-rank {font-weight: bold; font-size: 1em; margin-bottom: 3px;}
        .standings-table-compact .category-title {font-weight: bold; font-size:0.9em; color: #333; margin-top: 4px; margin-bottom:1px;}
        
        /* Cuotas Iniciales */
        .odds-container .stMetric {padding: 8px; margin-bottom: 5px; background-color: #f8f9fa; border: 1px solid #dee2e6; border-radius: .25rem;}
        .odds-container .stMetric label {font-size: 0.8em !important; color: #495057 !important;}
        .odds-container .stMetric .st-ax {font-size: 1.2em !important;}

        /* Tarjeta de partido compacta */
        .compact-card-title { font-size: 1em; font-weight: bold; color: #2c3e50; margin-bottom: 5px; padding-bottom:3px; border-bottom: 1px dashed #bdc3c7;}
        .match-score-line { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; font-size:0.9em;}
        .match-score-line .team-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .match-score-line .team-name.home { text-align: left; color: #007bff;}
        .match-score-line .team-name.away { text-align: right; color: #fd7e14;}
        .match-score-line .score-box { 
            font-weight: bold; font-size: 1.1em; color: #ffffff; 
            background-color: #34495e; padding: 2px 8px; border-radius: 3px; margin: 0 8px;
            min-width: 50px; text-align: center;
        }
        .match-ah-date { font-size: 0.8em; color: #7f8c8d; display: flex; justify-content: space-between; margin-bottom: 5px;}
        .ah-value-compact { font-weight: bold; color: #8e44ad; }
        .compact-card-divider { height: 1px; background-color: #ecf0f1; margin-top: 8px; margin-bottom: 8px; }
        
        /* Tabla de estadísticas compacta */
        .stats-table-title {font-size: 0.8em; color: #555; margin-bottom: 2px; font-style:italic;}
        .compact-stats-table { width: 100%; font-size: 0.8em; border-collapse: collapse; margin-bottom: 5px;}
        .compact-stats-table td { padding: 1px 3px; text-align: center; }
        .compact-stats-table .stat-name { color: #34495e; width: 60%;}
        .compact-stats-table .stat-home-val, .compact-stats-table .stat-away-val { font-weight: bold; width: 20%; }
        .stat-better { color: #27ae60 !important; } /* Verde */
        .stat-worse { color: #c0392b !important; }  /* Rojo */
        .stat-neutral { color: #7f8c8d !important; } /* Gris */

        /* Ajustes generales Streamlit */
        .stButton>button {font-size: 0.9em; padding: 0.3em 0.8em;}
        .stTextInput input {font-size: 0.9em; padding: 0.4em 0.6em;}
        div[data-testid="stExpander"] div[role="button"] p { font-size: 1em; font-weight:bold; } /* Titulo Expander */

    </style>
    """, unsafe_allow_html=True)

    st.sidebar.image("https://raw.githubusercontent.com/streamlit/docs/main/public/images/brand/streamlit-logo-secondary-colormark-darktext.svg", width=180)
    st.sidebar.title("Config. Partido") # Título más corto
    main_match_id_str_input_of = st.sidebar.text_input(
        "ID Partido Principal:", value="2696131", # Mantener ID para testing
        help="Pega el ID numérico del partido que deseas analizar.", key="other_feature_match_id_input")
    
    # Botón de análisis en el sidebar
    analizar_button_of = st.sidebar.button("🚀 Analizar Partido", type="primary", use_container_width=True, key="other_feature_analizar_button")
    
    # Contenedor para resultados y spinner en el área principal
    results_container = st.empty() # Usar empty para reemplazar contenido

    if 'driver_other_feature' not in st.session_state:
        st.session_state.driver_other_feature = None

    if analizar_button_of:
        results_container.info("🔄 Cargando y analizando datos... Este proceso puede tardar unos segundos.")
        main_match_id_to_process_of = None
        if main_match_id_str_input_of:
            try:
                cleaned_id_str = "".join(filter(str.isdigit, main_match_id_str_input_of))
                if cleaned_id_str: main_match_id_to_process_of = int(cleaned_id_str)
            except ValueError:
                results_container.error("⚠️ ID de partido no válido."); st.stop()
        if not main_match_id_to_process_of:
            results_container.warning("⚠️ Ingresa un ID de partido válido."); st.stop()
        
        start_time_of = time.time()
        
        # --- Extracción de datos ---
        # Esta parte sigue siendo secuencial como en tu código original.
        # La paralelización es más compleja de lo que se puede hacer aquí rápidamente.
        
        main_page_url_h2h_view_of = f"/match/h2h-{main_match_id_to_process_of}"
        soup_main_h2h_page_of = fetch_soup_requests_of(main_page_url_h2h_view_of)
        if not soup_main_h2h_page_of:
            results_container.error(f"❌ No se pudo obtener la página H2H para ID {main_match_id_to_process_of}."); st.stop()

        mp_home_id_of, mp_away_id_of, mp_league_id_of, mp_home_name_from_script, mp_away_name_from_script, mp_league_name_of = get_team_league_info_from_script_of(soup_main_h2h_page_of)
        home_team_main_standings = extract_standings_data_from_h2h_page_of(soup_main_h2h_page_of, mp_home_name_from_script)
        away_team_main_standings = extract_standings_data_from_h2h_page_of(soup_main_h2h_page_of, mp_away_name_from_script)
        display_home_name = home_team_main_standings.get("name") if home_team_main_standings.get("name") != PLACEHOLDER_NODATA else mp_home_name_from_script or "Local"
        display_away_name = away_team_main_standings.get("name") if away_team_main_standings.get("name") != PLACEHOLDER_NODATA else mp_away_name_from_script or "Visitante"

        # Selenium driver init
        driver_actual_of = st.session_state.driver_other_feature
        driver_of_needs_init = driver_actual_of is None
        if not driver_of_needs_init:
            try:
                _ = driver_actual_of.window_handles
                if hasattr(driver_actual_of, 'service') and driver_actual_of.service and not driver_actual_of.service.is_connectable(): driver_of_needs_init = True
            except WebDriverException: driver_of_needs_init = True
        if driver_of_needs_init:
            if driver_actual_of is not None:
                try: driver_actual_of.quit()
                except: pass
            driver_actual_of = get_selenium_driver_of()
            st.session_state.driver_other_feature = driver_actual_of

        main_match_odds_data_of = {}
        last_home_match_in_league_of = None
        last_away_match_in_league_of = None
        details_h2h_col3_of = {"status": "error", "resultado": PLACEHOLDER_NODATA} # Inicializar

        if driver_actual_of:
            try:
                # Navegación principal y odds
                target_url_main_h2h = f"{BASE_URL_OF}{main_page_url_h2h_view_of}"
                if driver_actual_of.current_url != target_url_main_h2h:
                     driver_actual_of.get(target_url_main_h2h)
                WebDriverWait(driver_actual_of, SELENIUM_TIMEOUT_SECONDS_OF).until(EC.presence_of_element_located((By.ID, "table_v1")))
                time.sleep(0.2) 
                main_match_odds_data_of = get_main_match_odds_selenium_of(driver_actual_of)

                # Último partido local
                if mp_home_id_of and mp_league_id_of and display_home_name != PLACEHOLDER_NODATA:
                    if driver_actual_of.current_url != target_url_main_h2h: driver_actual_of.get(target_url_main_h2h) # Reset page
                    WebDriverWait(driver_actual_of, SELENIUM_TIMEOUT_SECONDS_OF).until(EC.presence_of_element_located((By.ID, "table_v1")))
                    last_home_match_in_league_of = extract_last_match_in_league_of(driver_actual_of, "table_v1", display_home_name, mp_league_id_of, "input#cb_sos1[value='1']", True)
                
                # Último partido visitante
                if mp_away_id_of and mp_league_id_of and display_away_name != PLACEHOLDER_NODATA:
                    if driver_actual_of.current_url != target_url_main_h2h: driver_actual_of.get(target_url_main_h2h) # Reset page
                    WebDriverWait(driver_actual_of, SELENIUM_TIMEOUT_SECONDS_OF).until(EC.presence_of_element_located((By.ID, "table_v2")))
                    last_away_match_in_league_of = extract_last_match_in_league_of(driver_actual_of, "table_v2", display_away_name, mp_league_id_of, "input#cb_sos2[value='2']", False)

                # H2H Rivales Col3 (esto implica nueva navegación)
                key_match_id_rival_a, rival_a_id, rival_a_name = get_rival_a_for_original_h2h_of(main_match_id_to_process_of) # Requests, puede ir antes de Selenium
                _, rival_b_id, rival_b_name = get_rival_b_for_original_h2h_of(main_match_id_to_process_of) # Requests
                if key_match_id_rival_a and rival_a_id and rival_b_id:
                     details_h2h_col3_of = get_h2h_details_for_original_logic_of(driver_actual_of, key_match_id_rival_a, rival_a_id, rival_b_id, rival_a_name, rival_b_name)

            except Exception as e_main_sel_of: 
                st.sidebar.error(f"❗ Error Selenium: {type(e_main_sel_of).__name__}.")
        else: st.sidebar.warning("❗ WebDriver no disponible. Funcionalidad Selenium limitada.")

        final_score_main, _ = extract_final_score_of(soup_main_h2h_page_of)
        ah1_val, res1_val, _, match1_id_h2h_v, \
        ah6_val, res6_val, _, match6_id_h2h_g, \
        h2h_gen_home_name, h2h_gen_away_name = extract_h2h_data_of(soup_main_h2h_page_of, display_home_name, display_away_name, mp_league_id_of)

        comp_data_L_vs_UV_A = None
        if last_away_match_in_league_of and display_home_name != PLACEHOLDER_NODATA and last_away_match_in_league_of.get('home_team'):
            comp_data_L_vs_UV_A = extract_comparative_match_of(soup_main_h2h_page_of, "table_v1", display_home_name, last_away_match_in_league_of.get('home_team'), mp_league_id_of, True)
        comp_data_V_vs_UL_H = None
        if last_home_match_in_league_of and display_away_name != PLACEHOLDER_NODATA and last_home_match_in_league_of.get('away_team'):
            comp_data_V_vs_UL_H = extract_comparative_match_of(soup_main_h2h_page_of, "table_v2", display_away_name, last_home_match_in_league_of.get('away_team'), mp_league_id_of, False)

        # ----- RENDERIZACIÓN DE LA UI -----
        with results_container.container(): # Reemplaza el spinner con el contenido
            st.markdown(f"<p class='main-title'>📊 Análisis Partido ⚽</p>", unsafe_allow_html=True) # Título más corto
            st.markdown(f"<p class='sub-title'><span class='home-color'>{display_home_name}</span> vs <span class='away-color'>{display_away_name}</span></p>", unsafe_allow_html=True)
            st.caption(f"🏆 {mp_league_name_of or PLACEHOLDER_NODATA} | 🆔 <span class='data-highlight'>{main_match_id_to_process_of}</span>", unsafe_allow_html=True)
            st.divider()

            # Sección de Clasificación y Cuotas principales
            col_clasif_1, col_clasif_2, col_odds = st.columns([2,2,1]) # Columna más estrecha para odds
            
            def display_standings_compact(col_container, team_standings_data, team_color_class):
                with col_container:
                    name = team_standings_data.get("name", "Equipo")
                    rank = team_standings_data.get("ranking", PLACEHOLDER_NODATA)
                    st.markdown(f"<div class='standings-table-compact {team_color_class}'><div class='team-name-rank'>{name} (Rank: {rank})</div>", unsafe_allow_html=True)
                    st.markdown(f"<div class='category-title'>Total Liga:</div>", unsafe_allow_html=True)
                    st.markdown(f"<p><strong>PJ:</strong>{team_standings_data.get('total_pj', '-')} <strong>V:</strong>{team_standings_data.get('total_v', '-')} <strong>E:</strong>{team_standings_data.get('total_e', '-')} <strong>D:</strong>{team_standings_data.get('total_d', '-')} | <strong>GF:</strong>{team_standings_data.get('total_gf', '-')} <strong>GC:</strong>{team_standings_data.get('total_gc', '-')}</p>", unsafe_allow_html=True)
                    specific_type = team_standings_data.get('specific_type', 'Específico')
                    st.markdown(f"<div class='category-title'>{specific_type}:</div>", unsafe_allow_html=True)
                    st.markdown(f"<p><strong>PJ:</strong>{team_standings_data.get('specific_pj', '-')} <strong>V:</strong>{team_standings_data.get('specific_v', '-')} <strong>E:</strong>{team_standings_data.get('specific_e', '-')} <strong>D:</strong>{team_standings_data.get('specific_d', '-')} | <strong>GF:</strong>{team_standings_data.get('specific_gf', '-')} <strong>GC:</strong>{team_standings_data.get('specific_gc', '-')}</p>", unsafe_allow_html=True)
                    st.markdown("</div>", unsafe_allow_html=True)

            display_standings_compact(col_clasif_1, home_team_main_standings, "home-color")
            display_standings_compact(col_clasif_2, away_team_main_standings, "away-color")

            with col_odds:
                st.markdown("<div class='odds-container'>", unsafe_allow_html=True)
                st.metric("🏁 Final", final_score_main if final_score_main != "?:?" else PLACEHOLDER_NODATA)
                ah_act_fmt = format_ah_as_decimal_string_of(main_match_odds_data_of.get('ah_linea_raw', '?'))
                st.metric("AH Act.", ah_act_fmt, f"{main_match_odds_data_of.get('ah_home_cuota','-')}/{main_match_odds_data_of.get('ah_away_cuota','-')}")
                g_i_fmt = format_ah_as_decimal_string_of(main_match_odds_data_of.get('goals_linea_raw', '?')) # Usa misma fn para formato decimal
                st.metric("Goles Act.", g_i_fmt, f"O:{main_match_odds_data_of.get('goals_over_cuota','-')} U:{main_match_odds_data_of.get('goals_under_cuota','-')}")
                st.markdown("</div>", unsafe_allow_html=True)
            
            st.divider()
            st.markdown("<h2 class='section-header'>⚡ Rendimiento Reciente y H2H Clave</h2>", unsafe_allow_html=True)
            
            # Usar 3 columnas para "Último Local", "Último Visitante", "H2H Rivales Col3"
            rp_col1, rp_col2, rp_col3 = st.columns(3)

            if last_home_match_in_league_of:
                res_lh = last_home_match_in_league_of
                display_compact_match_card(f"Último <span class='home-color'>{display_home_name}</span> (Casa)",
                                           res_lh.get('date'), res_lh.get('home_team'), res_lh.get('away_team'),
                                           res_lh.get('score'), res_lh.get('handicap_line_raw'), res_lh.get('match_id'),
                                           rp_col1)
            else: rp_col1.info(f"Sin datos para último partido de {display_home_name} (C).")

            if last_away_match_in_league_of:
                res_la = last_away_match_in_league_of
                display_compact_match_card(f"Último <span class='away-color'>{display_away_name}</span> (Fuera)",
                                           res_la.get('date'), res_la.get('home_team'), res_la.get('away_team'),
                                           res_la.get('score'), res_la.get('handicap_line_raw'), res_la.get('match_id'),
                                           rp_col2)
            else: rp_col2.info(f"Sin datos para último partido de {display_away_name} (F).")
            
            if details_h2h_col3_of.get("status") == "found":
                res_h2h_c3 = details_h2h_col3_of
                title_c3 = f"H2H <span class='home-color'>{res_h2h_c3.get('h2h_home_team_name', 'RivalA')}</span> vs <span class='away-color'>{res_h2h_c3.get('h2h_away_team_name', 'RivalB')}</span> (Col3)"
                display_compact_match_card(title_c3, "N/A", # No hay fecha para H2H Col3 normalmente
                                           res_h2h_c3.get('h2h_home_team_name'), res_h2h_c3.get('h2h_away_team_name'),
                                           f"{res_h2h_c3.get('goles_home','?')}:{res_h2h_c3.get('goles_away','?')}",
                                           res_h2h_c3.get('handicap'), res_h2h_c3.get('match_id'),
                                           rp_col3)
            else: rp_col3.info(details_h2h_col3_of.get('resultado', "H2H Rivales Col3 no disponible."))
            
            # Expander para Comparativas Indirectas y H2H Directos
            with st.expander("Detalles Adicionales: Comparativas y H2H Directos", expanded=False):
                col_comp1, col_comp2 = st.columns(2)
                col_h2h1, col_h2h2 = st.columns(2)

                if comp_data_L_vs_UV_A:
                    data_c = comp_data_L_vs_UV_A
                    title_comp1 = f"<span class='home-color'>{display_home_name}</span> vs Rival de <span class='away-color'>{display_away_name}</span> ({data_c.get('away_team') or 'Rival'})"
                    display_compact_match_card(title_comp1, "N/A", data_c.get('home_team'), data_c.get('away_team'),
                                               data_c.get('score'), data_c.get('ah_line'), data_c.get('match_id'), col_comp1)
                else: col_comp1.caption("Comparativa L vs UV A no disponible.")

                if comp_data_V_vs_UL_H:
                    data_c = comp_data_V_vs_UL_H
                    title_comp2 = f"<span class='away-color'>{display_away_name}</span> vs Rival de <span class='home-color'>{display_home_name}</span> ({data_c.get('home_team') or 'Rival'})"
                    display_compact_match_card(title_comp2, "N/A", data_c.get('home_team'), data_c.get('away_team'),
                                               data_c.get('score'), data_c.get('ah_line'), data_c.get('match_id'), col_comp2)
                else: col_comp2.caption("Comparativa V vs UL H no disponible.")

                # H2H Directos
                title_h2h_v = f"H2H: <span class='home-color'>{display_home_name}</span> (Casa) vs <span class='away-color'>{display_away_name}</span>"
                display_compact_match_card(title_h2h_v, "N/A", display_home_name, display_away_name, 
                                           res1_val, ah1_val, match1_id_h2h_v, col_h2h1)
                
                title_h2h_g = f"H2H General: <span class='home-color'>{h2h_gen_home_name}</span> vs <span class='away-color'>{h2h_gen_away_name}</span>"
                display_compact_match_card(title_h2h_g, "N/A", h2h_gen_home_name, h2h_gen_away_name, 
                                           res6_val, ah6_val, match6_id_h2h_g, col_h2h2)

        # Fuera del with del spinner/container para el mensaje de tiempo
        end_time_of = time.time()
        st.sidebar.success(f"Análisis: {end_time_of - start_time_of:.2f} seg.")

    else: # Si no se ha pulsado analizar aún
        results_container.info("✨ ¡Bienvenido! Ingresa un ID de partido y haz clic en 'Analizar Partido'.")

if __name__ == '__main__':
    st.set_page_config(layout="wide", page_title="Análisis Avanzado (OF)", initial_sidebar_state="expanded")
    # No es necesario `if 'driver_other_feature' not in st.session_state:` aquí, se maneja en `display_other_feature_ui`
    display_other_feature_ui()
