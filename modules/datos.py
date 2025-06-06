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
# import threading # Quitado si no se usa activamente para paralelización compleja

# Importaciones de Selenium
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, ElementClickInterceptedException, NoSuchElementException

# --- CONFIGURACIÓN GLOBAL ---
BASE_URL_OF = "https://live18.nowgoal25.com"
SELENIUM_TIMEOUT_SECONDS_OF = 15 # Ajustado, prueba y modifica si es necesario
SELENIUM_POLL_FREQUENCY_OF = 0.4 # Ajustado
PLACEHOLDER_NODATA = "---" # Placeholder corto y limpio

# --- FUNCIONES HELPER PARA PARSEO Y FORMATEO ---
# (MANTENER TUS FUNCIONES parse_ah_to_number_of, format_ah_as_decimal_string_of, get_match_details_from_row_of)
# Asegúrate que get_match_details_from_row_of use ':' en score_fmt y maneje bien PLACEHOLDER_NODATA si es necesario
def parse_ah_to_number_of(ah_line_str: str):
    if not isinstance(ah_line_str, str): return None
    s = ah_line_str.strip().replace(' ', '')
    if not s or s in ['-', '?', PLACEHOLDER_NODATA]: return None # Añadir placeholder
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
    if not isinstance(ah_line_str, str) or not ah_line_str.strip() or ah_line_str.strip() in ['-', '?', PLACEHOLDER_NODATA]:
        return ah_line_str.strip() if isinstance(ah_line_str, str) and ah_line_str.strip() in ['-','?', PLACEHOLDER_NODATA] else PLACEHOLDER_NODATA

    numeric_value = parse_ah_to_number_of(ah_line_str)
    if numeric_value is None:
        return ah_line_str.strip() if ah_line_str.strip() in ['-','?', PLACEHOLDER_NODATA] else PLACEHOLDER_NODATA

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
        return "'" + output_str.replace('.', ',') if output_str not in ['-','?', PLACEHOLDER_NODATA] else output_str
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
        except requests.RequestException:
            if attempt == max_tries: return None
            time.sleep(delay * attempt)
    return None

# --- FUNCIONES DE ESTADÍSTICAS DE PROGRESIÓN ---
@st.cache_data(ttl=7200)
def get_match_progression_stats_data(match_id: str) -> pd.DataFrame | None: # Nombre original
    base_url_live = "https://live18.nowgoal25.com/match/live-"
    full_url = f"{base_url_live}{match_id}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    }
    # Estadísticas solicitadas
    stat_titles_of_interest = {
        "Shots": {"Home": PLACEHOLDER_NODATA, "Away": PLACEHOLDER_NODATA},
        "Shots on Goal": {"Home": PLACEHOLDER_NODATA, "Away": PLACEHOLDER_NODATA},
        "Dangerous Attacks": {"Home": PLACEHOLDER_NODATA, "Away": PLACEHOLDER_NODATA},
    }
    try:
        response = requests.get(full_url, headers=headers, timeout=10)
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
    except Exception: return None # Fallo silencioso para no romper UI

    table_rows = [{"Estadistica_EN": name, "Casa": vals['Home'], "Fuera": vals['Away']}
                  for name, vals in stat_titles_of_interest.items()]
    df = pd.DataFrame(table_rows)
    return df.set_index("Estadistica_EN") if not df.empty else df

# --- FUNCIONES DE EXTRACCIÓN DE DATOS DEL PARTIDO (Selenium y BeautifulSoup) ---
# (COPIA AQUÍ LAS FUNCIONES DE EXTRACCIÓN DE DATOS DESDE get_rival_a_for_original_h2h_of
#  HASTA extract_comparative_match_of, de tu VERSIÓN ANTERIOR FUNCIONAL (datos (1).py).
#  He incluido las que recuerdo que estaban, pero verifica que no falte ninguna.
#  ASEGÚRATE DE QUE USAN PLACEHOLDER_NODATA en lugar de "N/A" donde corresponda.)

@st.cache_resource
def get_selenium_driver_of():
    options = ChromeOptions(); options.add_argument("--headless"); options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage"); options.add_argument("--disable-gpu")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36")
    options.add_argument('--blink-settings=imagesEnabled=false'); options.add_argument("--window-size=1920,1080")
    try: return webdriver.Chrome(options=options)
    except WebDriverException as e: st.error(f"Error inicializando Selenium driver (OF): {e}"); return None

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

def get_h2h_details_for_original_logic_of(driver_instance, key_match_id_for_h2h_url, rival_a_id, rival_b_id, rival_a_name="Rival A", rival_b_name="Rival B"):
    if not driver_instance: return {"status": "error", "resultado": "N/A (Driver no disponible H2H OF)"} # Original N/A
    if not key_match_id_for_h2h_url or not rival_a_id or not rival_b_id: return {"status": "error", "resultado": f"N/A (IDs incompletos para H2H {rival_a_name} vs {rival_b_name})"}
    url_to_visit = f"{BASE_URL_OF}/match/h2h-{key_match_id_for_h2h_url}"
    try:
        if key_match_id_for_h2h_url not in driver_instance.current_url: # Optimización ligera
             driver_instance.get(url_to_visit)
        WebDriverWait(driver_instance, SELENIUM_TIMEOUT_SECONDS_OF, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.presence_of_element_located((By.ID, "table_v2")))
        time.sleep(0.3) # Reducido de 0.7
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
            if not score_span or not score_span.text or "-" not in score_span.text: continue
            score_val = score_span.text.strip().split("(")[0].strip(); g_h, g_a = score_val.split("-", 1)
            tds = row.find_all("td"); handicap_raw = PLACEHOLDER_NODATA; HANDICAP_TD_IDX = 11 # Usar PLACEHOLDER
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

def click_element_robust_of(driver, by, value, timeout=5): # Timeout reducido
    try:
        element = WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.presence_of_element_located((by, value)))
        driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'center'});", element); time.sleep(0.15) # Sleep reducido
        WebDriverWait(driver, 2, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.element_to_be_clickable((by, value))).click()
        return True
    except (ElementClickInterceptedException, TimeoutException):
        try: driver.execute_script("arguments[0].click();", element); return True
        except: return False
    except Exception: return False


def extract_last_match_in_league_of(driver, table_css_id_str, main_team_name_in_table, league_id_filter_value, home_or_away_filter_css_selector, is_home_game_filter):
    try:
        if league_id_filter_value:
            league_checkbox_selector = f"input#checkboxleague{table_css_id_str[-1]}[value='{league_id_filter_value}']"
            if not click_element_robust_of(driver, By.CSS_SELECTOR, league_checkbox_selector): return None
            time.sleep(0.2) # Pausa para JS
        
        if not click_element_robust_of(driver, By.CSS_SELECTOR, home_or_away_filter_css_selector): return None
        time.sleep(0.2) # Pausa para JS

        page_source_updated = driver.page_source; soup_updated = BeautifulSoup(page_source_updated, "html.parser")
        table = soup_updated.find("table", id=table_css_id_str)
        if not table: return None

        count_visible_rows = 0
        for row in table.find_all("tr", id=re.compile(rf"tr{table_css_id_str[-1]}_\d+")):
            if row.get("style") and "display:none" in row.get("style","").lower(): continue
            count_visible_rows +=1
            if count_visible_rows > 10: break
            
            tds = row.find_all("td");
            if len(tds) < 14: continue

            home_team_row_el = tds[2].find("a"); away_team_row_el = tds[4].find("a")
            if not home_team_row_el or not away_team_row_el: continue

            home_team_row_name = home_team_row_el.text.strip(); away_team_row_name = away_team_row_el.text.strip()
            if not main_team_name_in_table: continue # Evitar error si main_team_name es None
            team_is_home_in_row = main_team_name_in_table.lower() == home_team_row_name.lower()
            team_is_away_in_row = main_team_name_in_table.lower() == away_team_row_name.lower()

            if (is_home_game_filter and team_is_home_in_row) or \
               (not is_home_game_filter and team_is_away_in_row):
                date_span = tds[1].find("span", {"name": "timeData"}); date = date_span.text.strip() if date_span else PLACEHOLDER_NODATA
                score_class_re = re.compile(r"fscore_"); score_span = tds[3].find("span", class_=score_class_re); score = score_span.text.strip() if score_span else PLACEHOLDER_NODATA
                handicap_cell = tds[11]; handicap_raw = handicap_cell.get("data-o", handicap_cell.text.strip())
                
                if not handicap_raw or handicap_raw.strip() == "-": handicap_raw = PLACEHOLDER_NODATA
                else: handicap_raw = handicap_raw.strip()
                
                match_id_last_game = row.get('index')
                
                return {"date": date, "home_team": home_team_row_name,
                        "away_team": away_team_row_name,"score": score,
                        "handicap_line_raw": handicap_raw,
                        "match_id": match_id_last_game}
        return None
    except Exception: return None

def get_main_match_odds_selenium_of(driver):
    odds_info = {"ah_home_cuota": PLACEHOLDER_NODATA, "ah_linea_raw": PLACEHOLDER_NODATA, "ah_away_cuota": PLACEHOLDER_NODATA, 
                 "goals_over_cuota": PLACEHOLDER_NODATA, "goals_linea_raw": PLACEHOLDER_NODATA, "goals_under_cuota": PLACEHOLDER_NODATA}
    try:
        live_compare_div = WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS_OF - 5 , poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(
            EC.presence_of_element_located((By.ID, "liveCompareDiv"))
        )
        bet365_ids = ["tr_o_1_8", "tr_o_1_31", "tr_o_1_1_8", "tr_o_1_1_31"]
        bet365_early_odds_row = None
        for b_id in bet365_ids:
            try:
                row_candidate = live_compare_div.find_element(By.CSS_SELECTOR, f"tr#{b_id}[name='earlyOdds']")
                if row_candidate.is_displayed(): bet365_early_odds_row = row_candidate; break
            except NoSuchElementException: continue
        
        if not bet365_early_odds_row: return odds_info

        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", bet365_early_odds_row); time.sleep(0.1)
        
        tds = bet365_early_odds_row.find_elements(By.TAG_NAME, "td")
        if len(tds) >= 11:
            odds_info["ah_home_cuota"] = tds[2].get_attribute("data-o") or tds[2].text.strip() or PLACEHOLDER_NODATA
            odds_info["ah_linea_raw"] = tds[3].get_attribute("data-o") or tds[3].text.strip() or PLACEHOLDER_NODATA
            odds_info["ah_away_cuota"] = tds[4].get_attribute("data-o") or tds[4].text.strip() or PLACEHOLDER_NODATA
            odds_info["goals_over_cuota"] = tds[8].get_attribute("data-o") or tds[8].text.strip() or PLACEHOLDER_NODATA
            odds_info["goals_linea_raw"] = tds[9].get_attribute("data-o") or tds[9].text.strip() or PLACEHOLDER_NODATA
            odds_info["goals_under_cuota"] = tds[10].get_attribute("data-o") or tds[10].text.strip() or PLACEHOLDER_NODATA
    except Exception: pass
    return odds_info

def extract_standings_data_from_h2h_page_of(h2h_soup, target_team_name_exact):
    data = {
        "name": target_team_name_exact if target_team_name_exact else PLACEHOLDER_NODATA, 
        "ranking": PLACEHOLDER_NODATA,
        "total_pj": PLACEHOLDER_NODATA, "total_v": PLACEHOLDER_NODATA, "total_e": PLACEHOLDER_NODATA, "total_d": PLACEHOLDER_NODATA, "total_gf": PLACEHOLDER_NODATA, "total_gc": PLACEHOLDER_NODATA,
        "specific_pj": PLACEHOLDER_NODATA, "specific_v": PLACEHOLDER_NODATA, "specific_e": PLACEHOLDER_NODATA, "specific_d": PLACEHOLDER_NODATA, "specific_gf": PLACEHOLDER_NODATA, "specific_gc": PLACEHOLDER_NODATA,
        "specific_type": "N/A"
    }
    if not h2h_soup or not target_team_name_exact or target_team_name_exact == PLACEHOLDER_NODATA : return data

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
                is_home_table_type = False # Es visitante
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
        th_header = row.find("th");
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
            if row_type_text=="Total":
                data.update({"total_pj":pj,"total_v":v,"total_e":e,"total_d":d,"total_gf":gf,"total_gc":gc})
            elif (row_type_text=="Home" and is_home_table_type) or \
                 (row_type_text=="Away" and not is_home_table_type):
                data.update({"specific_pj":pj,"specific_v":v,"specific_e":e,"specific_d":d,"specific_gf":gf,"specific_gc":gc})
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
    if not main_home_team_name or not main_away_team_name or main_home_team_name == PLACEHOLDER_NODATA :
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
    if not opponent_name_to_search or opponent_name_to_search == PLACEHOLDER_NODATA or \
       not team_name_to_find_match_for or team_name_to_find_match_for == PLACEHOLDER_NODATA:
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
                    "localia": 'H' if team_main_lower == home_hist else 'A',
                    "home_team": details.get('home'), "away_team": details.get('away'), 
                    "match_id": details.get('matchIndex')}
    return None


# --- STREAMLIT APP UI (Función principal) ---
def display_other_feature_ui():
    st.markdown("""
    <style>
        body { font-size: 0.875rem; } /* Ligeramente más pequeño */
        .main-title { font-size: 1.6em; font-weight: bold; color: #007bff; text-align: center; margin-bottom: 0px; }
        .sub-title { font-size: 1.1em; text-align: center; margin-bottom: 10px; }
        .section-header { 
            font-size: 1.2em; font-weight: bold; color: #17a2b8; /* Cyan oscuro */
            margin-top: 15px; margin-bottom: 8px; 
            border-bottom: 2px solid #17a2b8; padding-bottom: 4px;
        }
        .home-color { color: #007bff; font-weight: bold; }
        .away-color { color: #fd7e14; font-weight: bold; }
        .data-highlight { font-weight: bold; color: #dc3545; }
        
        /* Contenedor General de tarjetas de partido */
        .match-cards-container { display: flex; flex-direction: column; gap: 10px; }

        /* Tarjeta de partido individual */
        .match-card { 
            border: 1px solid #ccc; border-radius: 5px; padding: 8px; 
            background-color: #fdfdfd; box-shadow: 2px 2px 5px rgba(0,0,0,0.05);
        }
        .match-card-title { font-size: 0.95em; font-weight: bold; color: #333; margin-bottom: 6px; text-align: center;}
        .match-info-line { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; font-size:0.9em;}
        .match-info-line .team-name { flex-basis: 38%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .match-info-line .team-name.home { text-align: left;}
        .match-info-line .team-name.away { text-align: right;}
        .match-info-line .score-box { 
            font-weight: bold; font-size: 1.1em; color: #fff; 
            background-color: #343a40; /* Gris oscuro */
            padding: 2px 8px; border-radius: 3px; margin: 0 5px;
            min-width: 50px; text-align: center; flex-basis: 15%;
        }
        .match-info-line .ah-value { font-weight: bold; color: #6f42c1; /* Púrpura */ flex-basis: 8%; text-align:center;}
        .match-date { font-size: 0.75em; color: #6c757d; text-align: center; margin-bottom: 6px; }
        
        .stats-table { width: 100%; font-size: 0.8em; border-collapse: collapse; margin-top: 4px;}
        .stats-table th { background-color: #e9ecef; padding: 2px 4px; border: 1px solid #dee2e6; text-align:center; color: #495057; font-weight:normal;}
        .stats-table td { padding: 2px 4px; border: 1px solid #dee2e6; text-align: center; }
        .stats-table .stat-home, .stats-table .stat-away { font-weight: bold; }
        .stat-better { background-color: #d4edda; color: #155724; } /* Verde claro */
        .stat-worse { background-color: #f8d7da; color: #721c24; } /* Rojo claro */
        .stat-neutral { background-color: #f8f9fa; }


        /* Clasificación */
        .standings-card { font-size: 0.85em; margin-bottom: 5px; padding: 6px; border: 1px solid #e0e0e0; border-radius: 4px; background-color: #f9f9f9;}
        .standings-card .team-name-rank {font-weight: bold; font-size: 1em; margin-bottom: 2px;}
        .standings-card .category-title {font-weight: bold; font-size:0.9em; color: #333; margin-top: 3px; margin-bottom:1px;}
        .standings-card p { margin-bottom: 0.1rem; line-height: 1.2;}
        .standings-card strong { font-weight: normal; color: #555; margin-right: 2px;}
        .standings-card span.stat-value { font-weight: bold; color: #000; margin-right: 5px;}

        /* Métricas Cuotas */
        .odds-metrics .stMetric {padding: 6px; margin-bottom: 4px; background-color: #f8f9fa; border-radius: .2rem; font-size:0.9em;}
        .odds-metrics .stMetric label {font-size: 0.8em !important; margin-bottom:0 !important;}
        .odds-metrics .stMetric .st-cq { font-size: 0.7em !important; } /* Delta value */
        .odds-metrics .stMetric div[data-testid="stMetricValue"] {font-size: 1.1em !important;}


        div[data-testid="stExpander"] div[role="button"] p { font-size: 1em; font-weight:bold; color: #0056b3;}
        .stCaption {font-size: 0.8em; color: #6c757d;}
        .stButton>button {font-size: 0.9em;}
    </style>
    """, unsafe_allow_html=True)

    st.sidebar.image("https://raw.githubusercontent.com/streamlit/docs/main/public/images/brand/streamlit-logo-secondary-colormark-darktext.svg", width=180)
    st.sidebar.title("Config. Partido")
    main_match_id_str_input_of = st.sidebar.text_input(
        "ID Partido Principal:", value="2696131",
        help="Pega el ID numérico del partido que deseas analizar.", key="other_feature_match_id_input_v2")
    analizar_button_of = st.sidebar.button("🚀 Analizar Partido", type="primary", use_container_width=True, key="other_feature_analizar_button_v2")

    results_placeholder = st.empty()

    if 'driver_other_feature' not in st.session_state:
        st.session_state.driver_other_feature = None

    if analizar_button_of:
        results_placeholder.info("🔄 Cargando y analizando datos...")
        main_match_id_to_process_of = None
        if main_match_id_str_input_of:
            try:
                cleaned_id_str = "".join(filter(str.isdigit, main_match_id_str_input_of))
                if cleaned_id_str: main_match_id_to_process_of = int(cleaned_id_str)
            except ValueError: results_placeholder.error("⚠️ ID de partido no válido."); st.stop()
        if not main_match_id_to_process_of: results_placeholder.warning("⚠️ Ingresa un ID de partido válido."); st.stop()
        
        start_time_of = time.time()
        
        # --- Obtención de Datos (Lógica de tu versión datos(1).py) ---
        main_page_url_h2h_view_of = f"/match/h2h-{main_match_id_to_process_of}"
        soup_main_h2h_page_of = fetch_soup_requests_of(main_page_url_h2h_view_of)
        if not soup_main_h2h_page_of:
            results_placeholder.error(f"❌ No se pudo obtener la página H2H para ID {main_match_id_to_process_of}."); st.stop()

        mp_home_id_of, mp_away_id_of, mp_league_id_of, mp_home_name_from_script, mp_away_name_from_script, mp_league_name_of = get_team_league_info_from_script_of(soup_main_h2h_page_of)
        home_team_main_standings = extract_standings_data_from_h2h_page_of(soup_main_h2h_page_of, mp_home_name_from_script)
        away_team_main_standings = extract_standings_data_from_h2h_page_of(soup_main_h2h_page_of, mp_away_name_from_script)
        
        display_home_name = home_team_main_standings.get("name") if home_team_main_standings.get("name", PLACEHOLDER_NODATA) != PLACEHOLDER_NODATA else mp_home_name_from_script or "Local"
        display_away_name = away_team_main_standings.get("name") if away_team_main_standings.get("name", PLACEHOLDER_NODATA) != PLACEHOLDER_NODATA else mp_away_name_from_script or "Visitante"

        # --- Selenium Driver y datos dinámicos ---
        driver_actual_of = st.session_state.driver_other_feature
        # (Lógica de inicialización del driver como en tu versión datos(1).py)
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
        details_h2h_col3_of = {"status": "error", "resultado": PLACEHOLDER_NODATA}

        if driver_actual_of:
            try:
                target_url = f"{BASE_URL_OF}{main_page_url_h2h_view_of}"
                if driver_actual_of.current_url != target_url : driver_actual_of.get(target_url)
                WebDriverWait(driver_actual_of, SELENIUM_TIMEOUT_SECONDS_OF).until(EC.presence_of_element_located((By.ID, "table_v1")))
                time.sleep(0.3) # Reducido
                
                main_match_odds_data_of = get_main_match_odds_selenium_of(driver_actual_of)
                
                if mp_home_id_of and mp_league_id_of and display_home_name != PLACEHOLDER_NODATA:
                    if driver_actual_of.current_url != target_url : driver_actual_of.get(target_url) # Reset
                    WebDriverWait(driver_actual_of, SELENIUM_TIMEOUT_SECONDS_OF).until(EC.presence_of_element_located((By.ID, "table_v1")))
                    last_home_match_in_league_of = extract_last_match_in_league_of(driver_actual_of, "table_v1", display_home_name, mp_league_id_of, "input#cb_sos1[value='1']", True)
                
                if mp_away_id_of and mp_league_id_of and display_away_name != PLACEHOLDER_NODATA:
                    if driver_actual_of.current_url != target_url : driver_actual_of.get(target_url) # Reset
                    WebDriverWait(driver_actual_of, SELENIUM_TIMEOUT_SECONDS_OF).until(EC.presence_of_element_located((By.ID, "table_v2")))
                    last_away_match_in_league_of = extract_last_match_in_league_of(driver_actual_of, "table_v2", display_away_name, mp_league_id_of, "input#cb_sos2[value='2']", False)
                
                # H2H Rivales Col3
                key_m_id, r_a_id, r_a_name = get_rival_a_for_original_h2h_of(main_match_id_to_process_of)
                _, r_b_id, r_b_name = get_rival_b_for_original_h2h_of(main_match_id_to_process_of)
                if key_m_id and r_a_id and r_b_id:
                    details_h2h_col3_of = get_h2h_details_for_original_logic_of(driver_actual_of, key_m_id, r_a_id, r_b_id, r_a_name, r_b_name)
            
            except Exception as e_main_sel_of: st.sidebar.error(f"❗ Error Selenium: {type(e_main_sel_of).__name__}.")
        else: st.sidebar.warning("❗ WebDriver no disponible.")

        # Datos del soup que no dependen de Selenium
        final_score_main_match, _ = extract_final_score_of(soup_main_h2h_page_of)
        ah1_val, res1_val, _, match1_id_h2h_v, ah6_val, res6_val, _, match6_id_h2h_g, \
        h2h_gen_home_name, h2h_gen_away_name = extract_h2h_data_of(soup_main_h2h_page_of, display_home_name, display_away_name, mp_league_id_of)

        comp_data_L_vs_UV_A = None
        if last_away_match_in_league_of and display_home_name != PLACEHOLDER_NODATA and last_away_match_in_league_of.get('home_team'):
            comp_data_L_vs_UV_A = extract_comparative_match_of(soup_main_h2h_page_of, "table_v1", display_home_name, last_away_match_in_league_of.get('home_team'), mp_league_id_of, True)
        comp_data_V_vs_UL_H = None
        if last_home_match_in_league_of and display_away_name != PLACEHOLDER_NODATA and last_home_match_in_league_of.get('away_team'):
            comp_data_V_vs_UL_H = extract_comparative_match_of(soup_main_h2h_page_of, "table_v2", display_away_name, last_home_match_in_league_of.get('away_team'), mp_league_id_of, False)


        # Nueva función para generar la tarjeta de partido con estadísticas integradas
        def render_match_analysis_card(title_html, date_str, home_team_name, away_team_name, score_str, ah_raw_str, match_id_str):
            card_html = f"<div class='match-card'><div class='match-card-title'>{title_html}</div>"
            
            # Línea de información del partido (equipos, resultado, AH)
            score_to_display = score_str.replace('-', ':') if score_str and '-' in score_str else (score_str or '?:?')
            s_parts = score_to_display.split(':')
            h_s, a_s = (s_parts[0], s_parts[1]) if len(s_parts)==2 else ('?','?')

            ah_formatted = format_ah_as_decimal_string_of(ah_raw_str)

            card_html += f"""
            <div class='match-info-line'>
                <span class='team-name home'>{home_team_name or 'Local'}</span>
                <span class='score-box'>{h_s} - {a_s}</span>
                <span class='ah-value'>{ah_formatted}</span>
                <span class='team-name away'>{away_team_name or 'Visitante'}</span>
            </div>
            """
            if date_str and date_str != PLACEHOLDER_NODATA:
                card_html += f"<div class='match-date'>📅 {date_str}</div>"

            # Tabla de Estadísticas de Progresión
            if match_id_str and match_id_str.isdigit():
                stats_df = get_match_progression_stats_data(match_id_str) # Usa la función de obtención de datos
                if stats_df is not None and not stats_df.empty:
                    stats_map = {
                        "Shots": "Disparos", "Shots on Goal": "D.Puerta", "Dangerous Attacks": "A.Pelig."
                    }
                    stats_table_html = "<table class='stats-table'><tr><th>Local</th><th>Estadística</th><th>Visitante</th></tr>"
                    for stat_key, stat_label in stats_map.items():
                        if stat_key in stats_df.index:
                            h_val = stats_df.loc[stat_key, 'Casa']
                            a_val = stats_df.loc[stat_key, 'Fuera']
                            h_val_num, a_val_num = 0, 0
                            try: h_val_num = int(h_val) if h_val != PLACEHOLDER_NODATA else 0
                            except: pass
                            try: a_val_num = int(a_val) if a_val != PLACEHOLDER_NODATA else 0
                            except: pass
                            
                            h_class = "stat-neutral"
                            a_class = "stat-neutral"
                            if h_val_num > a_val_num: h_class = "stat-better"; a_class = "stat-worse"
                            elif a_val_num > h_val_num: a_class = "stat-better"; h_class = "stat-worse"
                            
                            stats_table_html += f"<tr><td class='stat-home {h_class}'>{h_val}</td><td>{stat_label}</td><td class='stat-away {a_class}'>{a_val}</td></tr>"
                        else:
                             stats_table_html += f"<tr><td class='stat-home stat-neutral'>{PLACEHOLDER_NODATA}</td><td>{stat_label}</td><td class='stat-away stat-neutral'>{PLACEHOLDER_NODATA}</td></tr>"
                    stats_table_html += "</table>"
                    card_html += stats_table_html
                elif match_id_str : # Si hay ID pero no datos, indicar
                    card_html += f"<p class='stCaption' style='text-align:center; font-size:0.75em;'>Est. Progresión no disponibles para ID {match_id_str}.</p>"
            
            card_html += "</div>" # Cierre de match-card
            st.markdown(card_html, unsafe_allow_html=True)


        with results_placeholder.container(): # Reemplaza el spinner con el contenido
            st.markdown(f"<p class='main-title'>📊 Análisis Partido</p>", unsafe_allow_html=True)
            st.markdown(f"<p class='sub-title'><span class='home-color'>{display_home_name}</span> vs <span class='away-color'>{display_away_name}</span></p>", unsafe_allow_html=True)
            st.caption(f"🏆 {mp_league_name_of or PLACEHOLDER_NODATA} | 🆔 <span class='data-highlight'>{main_match_id_to_process_of}</span>")
            st.divider()

            # Sección Clasificación y Cuotas
            col_clasif_L, col_clasif_V, col_odds_main = st.columns([2,2,1])
            
            def display_standings_ui_card(col, data, color_class_name):
                with col:
                    st.markdown(f"<div class='standings-card {color_class_name}'>", unsafe_allow_html=True)
                    st.markdown(f"<div class='team-name-rank'>{data.get('name', 'Equipo')} (Rank: <span class='stat-value'>{data.get('ranking', '--')}</span>)</div>", unsafe_allow_html=True)
                    st.markdown(f"<div class='category-title'>Total Liga:</div>", unsafe_allow_html=True)
                    st.markdown(f"<p><strong>PJ:</strong><span class='stat-value'>{data.get('total_pj','-')}</span> <strong>V:</strong><span class='stat-value'>{data.get('total_v','-')}</span> <strong>E:</strong><span class='stat-value'>{data.get('total_e','-')}</span> <strong>D:</strong><span class='stat-value'>{data.get('total_d','-')}</span> G(<span class='stat-value'>{data.get('total_gf','-')}</span>:<span class='stat-value'>{data.get('total_gc','-')}</span>)</p>", unsafe_allow_html=True)
                    st.markdown(f"<div class='category-title'>{data.get('specific_type', 'Específico')}:</div>", unsafe_allow_html=True)
                    st.markdown(f"<p><strong>PJ:</strong><span class='stat-value'>{data.get('specific_pj','-')}</span> <strong>V:</strong><span class='stat-value'>{data.get('specific_v','-')}</span> <strong>E:</strong><span class='stat-value'>{data.get('specific_e','-')}</span> <strong>D:</strong><span class='stat-value'>{data.get('specific_d','-')}</span> G(<span class='stat-value'>{data.get('specific_gf','-')}</span>:<span class='stat-value'>{data.get('specific_gc','-')}</span>)</p>", unsafe_allow_html=True)
                    st.markdown("</div>", unsafe_allow_html=True)

            display_standings_ui_card(col_clasif_L, home_team_main_standings, "home-color")
            display_standings_ui_card(col_clasif_V, away_team_main_standings, "away-color")
            
            with col_odds_main:
                st.markdown("<div class='odds-metrics'>", unsafe_allow_html=True)
                st.metric("🏁 Final", final_score_main_match if final_score_main_match != "?:?" else PLACEHOLDER_NODATA)
                ah_act_val = format_ah_as_decimal_string_of(main_match_odds_data_of.get('ah_linea_raw', '?'))
                st.metric("AH Act.", ah_act_val, delta=f"{main_match_odds_data_of.get('ah_home_cuota','-')}/{main_match_odds_data_of.get('ah_away_cuota','-')}", delta_color="off")
                g_i_val = format_ah_as_decimal_string_of(main_match_odds_data_of.get('goals_linea_raw', '?'))
                st.metric("Goles Act.", g_i_val, delta=f"O:{main_match_odds_data_of.get('goals_over_cuota','-')} U:{main_match_odds_data_of.get('goals_under_cuota','-')}", delta_color="off")
                st.markdown("</div>", unsafe_allow_html=True)
                if final_score_main_match != "?:?" and final_score_main_match != PLACEHOLDER_NODATA:
                    render_match_analysis_card("", "", display_home_name, display_away_name, final_score_main_match, PLACEHOLDER_NODATA, str(main_match_id_to_process_of))


            st.markdown("<h2 class='section-header'>⚡ Rendimiento y Contexto H2H</h2>", unsafe_allow_html=True)
            
            cols_recent_h2h = st.columns(3)
            with cols_recent_h2h[0]:
                if last_home_match_in_league_of:
                    res_lh = last_home_match_in_league_of
                    render_match_analysis_card(f"Últ. <span class='home-color'>{display_home_name}</span> (C)", res_lh.get('date'), 
                                               res_lh.get('home_team'), res_lh.get('away_team'), res_lh.get('score'), 
                                               res_lh.get('handicap_line_raw'), res_lh.get('match_id'))
                else: st.caption(f"Últ. {display_home_name} (C) no encontrado.")
            
            with cols_recent_h2h[1]:
                if last_away_match_in_league_of:
                    res_la = last_away_match_in_league_of
                    render_match_analysis_card(f"Últ. <span class='away-color'>{display_away_name}</span> (F)", res_la.get('date'), 
                                               res_la.get('home_team'), res_la.get('away_team'), res_la.get('score'), 
                                               res_la.get('handicap_line_raw'), res_la.get('match_id'))
                else: st.caption(f"Últ. {display_away_name} (F) no encontrado.")

            with cols_recent_h2h[2]:
                if details_h2h_col3_of.get("status") == "found":
                    res_h2h_c3 = details_h2h_col3_of
                    h_name = res_h2h_c3.get('h2h_home_team_name', 'RivalA')
                    a_name = res_h2h_c3.get('h2h_away_team_name', 'RivalB')
                    render_match_analysis_card(f"H2H <span class='home-color'>{h_name}</span> vs <span class='away-color'>{a_name}</span>", PLACEHOLDER_NODATA,
                                               h_name, a_name, f"{res_h2h_c3.get('goles_home','?')}:{res_h2h_c3.get('goles_away','?')}", 
                                               res_h2h_c3.get('handicap'), res_h2h_c3.get('match_id'))
                else: st.caption(details_h2h_col3_of.get('resultado', "H2H Rivales Col3 no disponible."))

            with st.expander("Detalles Adicionales: Comparativas y H2H Directos", expanded=False):
                col_exp_1, col_exp_2 = st.columns(2)
                with col_exp_1:
                    st.markdown("<div class='match-cards-container'>", unsafe_allow_html=True) # Contenedor para espaciado
                    if comp_data_L_vs_UV_A:
                        d_comp = comp_data_L_vs_UV_A
                        render_match_analysis_card(f"<span class='home-color'>{display_home_name}</span> vs Rival Visit.", PLACEHOLDER_NODATA,
                                                   d_comp.get('home_team'), d_comp.get('away_team'), d_comp.get('score'), 
                                                   d_comp.get('ah_line'), d_comp.get('match_id'))
                    else: st.caption("Comp. L vs UV A no disp.")
                    
                    render_match_analysis_card(f"H2H: <span class='home-color'>{display_home_name}</span> (C) vs <span class='away-color'>{display_away_name}</span>", PLACEHOLDER_NODATA,
                                               display_home_name, display_away_name, res1_val, ah1_val, match1_id_h2h_v)
                    st.markdown("</div>", unsafe_allow_html=True)

                with col_exp_2:
                    st.markdown("<div class='match-cards-container'>", unsafe_allow_html=True)
                    if comp_data_V_vs_UL_H:
                        d_comp = comp_data_V_vs_UL_H
                        render_match_analysis_card(f"<span class='away-color'>{display_away_name}</span> vs Rival Local", PLACEHOLDER_NODATA,
                                                   d_comp.get('home_team'), d_comp.get('away_team'), d_comp.get('score'),
                                                   d_comp.get('ah_line'), d_comp.get('match_id'))
                    else: st.caption("Comp. V vs UL H no disp.")

                    render_match_analysis_card(f"H2H General: <span class='home-color'>{h2h_gen_home_name}</span> vs <span class='away-color'>{h2h_gen_away_name}</span>", PLACEHOLDER_NODATA,
                                               h2h_gen_home_name, h2h_gen_away_name, res6_val, ah6_val, match6_id_h2h_g)
                    st.markdown("</div>", unsafe_allow_html=True)
        
        end_time_of = time.time()
        st.sidebar.success(f"Análisis: {end_time_of - start_time_of:.2f} seg.")
    else:
        results_placeholder.info("✨ ¡Bienvenido! Ingresa un ID de partido y haz clic en 'Analizar Partido'.")

if __name__ == '__main__':
    st.set_page_config(layout="wide", page_title="Análisis Partidos (OF)", initial_sidebar_state="expanded")
    display_other_feature_ui()
