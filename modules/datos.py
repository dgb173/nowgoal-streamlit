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

# Importaciones de Selenium
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, ElementClickInterceptedException, NoSuchElementException

# --- CONFIGURACIÓN GLOBAL ---
BASE_URL_OF = "https://live18.nowgoal25.com"
SELENIUM_TIMEOUT_SECONDS_OF = 20
SELENIUM_POLL_FREQUENCY_OF = 0.2
PLACEHOLDER_NODATA = "*(No disponible)*"

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
        return ah_line_str.strip() if isinstance(ah_line_str, str) and ah_line_str.strip() in ['-','?'] else '-'

    numeric_value = parse_ah_to_number_of(ah_line_str)
    if numeric_value is None:
        return ah_line_str.strip() if ah_line_str.strip() in ['-','?'] else '-'

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
        cells = row_element.find_all(['td', 'th'])
        home_idx, score_idx, away_idx = 2, 3, 4
        
        home_tag = cells[home_idx].find('a')
        home = home_tag.text.strip() if home_tag else cells[home_idx].text.strip()

        away_tag = cells[away_idx].find('a')
        away = away_tag.text.strip() if away_tag else cells[away_idx].text.strip()

        score_span = cells[score_idx].find('span', class_=score_class_selector)
        score_raw = '?-?'
        if score_span:
            score_match = re.search(r'(\d+-\d+)', score_span.text)
            if score_match:
                score_raw = score_match.group(1)
        
        score_fmt = score_raw.replace('-', ':')
        match_id = row_element.get('index')

        ah_line_raw_text = '-'
        if source_table_type == 'h2h' and len(cells) > 13:
            ah_line_raw_text = cells[13].text.strip()
        elif source_table_type != 'h2h' and len(cells) > 11:
            ah_line_raw_text = cells[11].text.strip()

        ah_line_fmt = format_ah_as_decimal_string_of(ah_line_raw_text)

        if not home or not away or not match_id:
            return None

        return {
            'home': home, 'away': away, 'score': score_fmt, 'score_raw': score_raw,
            'ahLine': ah_line_fmt, 'ahLine_raw': ah_line_raw_text,
            'matchIndex': match_id, 'vs': row_element.get('vs'),
            'league_id_hist': row_element.get('name')
        }
    except Exception:
        return None

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
def get_match_progression_stats_data(match_id: str) -> pd.DataFrame | None:
    base_url_live = "https://live18.nowgoal25.com/match/live-"
    full_url = f"{base_url_live}{match_id}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36"}
    stat_titles_of_interest = {
        "Shots": {"Home": "-", "Away": "-"}, "Shots on Goal": {"Home": "-", "Away": "-"},
        "Attacks": {"Home": "-", "Away": "-"}, "Dangerous Attacks": {"Home": "-", "Away": "-"},
    }
    try:
        response = requests.get(full_url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'lxml')
        team_tech_div = soup.find('div', id='teamTechDiv_detail')
        if team_tech_div and (stat_list := team_tech_div.find('ul', class_='stat')):
            for li in stat_list.find_all('li'):
                if (title_span := li.find('span', class_='stat-title')) and (stat_title := title_span.get_text(strip=True)) in stat_titles_of_interest:
                    if len(values := li.find_all('span', class_='stat-c')) == 2:
                        stat_titles_of_interest[stat_title]["Home"] = values[0].get_text(strip=True)
                        stat_titles_of_interest[stat_title]["Away"] = values[1].get_text(strip=True)
    except: return None
    df = pd.DataFrame([{"Estadistica_EN": name, "Casa": vals['Home'], "Fuera": vals['Away']} for name, vals in stat_titles_of_interest.items()])
    return df.set_index("Estadistica_EN") if not df.empty else df

def display_match_progression_stats_view(match_id: str, home_team_name: str, away_team_name: str):
    stats_df = get_match_progression_stats_data(match_id)
    if stats_df is None or stats_df.empty:
        st.caption(f"_No se encontraron datos de progresión para el partido ID: {match_id}_")
        return

    ordered_stats_display = {
        "Shots": "Disparos", "Shots on Goal": "Disparos a Puerta",
        "Attacks": "Ataques", "Dangerous Attacks": "Ataques Peligrosos"
    }
    st.markdown("---")
    col_h_name, col_stat_name, col_a_name = st.columns([2, 3, 2])
    with col_h_name: st.markdown(f"<p style='font-weight:bold; color: #007bff;'>{home_team_name or 'Local'}</p>", unsafe_allow_html=True)
    with col_stat_name: st.markdown("<p style='text-align:center; font-weight:bold;'>Estadística</p>", unsafe_allow_html=True)
    with col_a_name: st.markdown(f"<p style='text-align:right; font-weight:bold; color: #fd7e14;'>{away_team_name or 'Visitante'}</p>", unsafe_allow_html=True)

    for stat_key_en, stat_name_es in ordered_stats_display.items():
        if stat_key_en in stats_df.index:
            home_val_str, away_val_str = stats_df.loc[stat_key_en, 'Casa'], stats_df.loc[stat_key_en, 'Fuera']
            try: home_val_num = int(home_val_str)
            except (ValueError, TypeError): home_val_num = 0
            try: away_val_num = int(away_val_str)
            except (ValueError, TypeError): away_val_num = 0
            
            home_color, away_color = ("green", "red") if home_val_num > away_val_num else (("red", "green") if away_val_num > home_val_num else ("black", "black"))

            c1, c2, c3 = st.columns([2, 3, 2])
            with c1: c1.markdown(f'<p style="font-size: 1.1em; font-weight:bold; color:{home_color};">{home_val_str}</p>', unsafe_allow_html=True)
            with c2: c2.markdown(f'<p style="text-align:center;">{stat_name_es}</p>', unsafe_allow_html=True)
            with c3: c3.markdown(f'<p style="text-align:right; font-size: 1.1em; font-weight:bold; color:{away_color};">{away_val_str}</p>', unsafe_allow_html=True)

def display_previous_match_progression_stats(title: str, match_id_str: str | None, home_name: str, away_name: str):
    if not match_id_str or not match_id_str.isdigit():
        return
    st.markdown(f"###### 👁️ _Est. Progresión para: {title}_")
    display_match_progression_stats_view(match_id_str, home_name, away_name)

# --- FUNCIONES DE EXTRACCIÓN DE DATOS DEL PARTIDO ---
@st.cache_data(ttl=3600)
def get_rival_a_for_original_h2h_of(main_match_id: int):
    soup_h2h_page = fetch_soup_requests_of(f"/match/h2h-{main_match_id}")
    if not soup_h2h_page or not (table := soup_h2h_page.find("table", id="table_v1")): return None, None, None
    for row in table.find_all("tr", id=re.compile(r"tr1_\d+")):
        if row.get("vs") == "1" and (key_match_id := row.get("index")):
            if (onclicks := row.find_all("a", onclick=True)) and len(onclicks) > 1 and onclicks[1].get("onclick"):
                rival_tag = onclicks[1]
                if (rival_a_id_match := re.search(r"team\((\d+)\)", rival_tag.get("onclick", ""))) and (rival_a_name := rival_tag.text.strip()):
                    return key_match_id, rival_a_id_match.group(1), rival_a_name
    return None, None, None

@st.cache_data(ttl=3600)
def get_rival_b_for_original_h2h_of(main_match_id: int):
    soup_h2h_page = fetch_soup_requests_of(f"/match/h2h-{main_match_id}")
    if not soup_h2h_page or not (table := soup_h2h_page.find("table", id="table_v2")): return None, None, None
    for row in table.find_all("tr", id=re.compile(r"tr2_\d+")):
        if row.get("vs") == "1" and (match_id := row.get("index")):
            if (onclicks := row.find_all("a", onclick=True)) and len(onclicks) > 0 and onclicks[0].get("onclick"):
                rival_tag = onclicks[0]
                if (rival_b_id_match := re.search(r"team\((\d+)\)", rival_tag.get("onclick", ""))) and (rival_b_name := rival_tag.text.strip()):
                    return match_id, rival_b_id_match.group(1), rival_b_name
    return None, None, None

@st.cache_resource
def get_selenium_driver_of():
    options = ChromeOptions(); options.add_argument("--headless"); options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage"); options.add_argument("--disable-gpu")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36")
    options.add_argument('--blink-settings=imagesEnabled=false'); options.add_argument("--window-size=1920,1080")
    try: return webdriver.Chrome(options=options)
    except WebDriverException as e: st.error(f"Error inicializando Selenium driver (OF): {e}"); return None

# --- FUNCIÓN H2H MEJORADA Y FLEXIBLE ---
# Esta función reemplaza a la antigua 'get_h2h_details_for_original_logic_of'
def get_h2h_details_of(driver_instance, key_match_id, rival_1_id, rival_2_id, rival_1_name="Rival 1", rival_2_name="Rival 2"):
    if not all([driver_instance, key_match_id, rival_1_id, rival_2_id]):
        return {"status": "error", "resultado": "N/A (Driver o IDs incompletos para H2H)"}

    url_to_visit = f"{BASE_URL_OF}/match/h2h-{key_match_id}"
    try:
        driver_instance.get(url_to_visit)
        WebDriverWait(driver_instance, SELENIUM_TIMEOUT_SECONDS_OF).until(EC.presence_of_element_located((By.ID, "table_v1")))
        time.sleep(0.7)
        soup_selenium = BeautifulSoup(driver_instance.page_source, "html.parser")
    except TimeoutException: return {"status": "error", "resultado": f"N/A (Timeout en {url_to_visit})"}
    except Exception as e: return {"status": "error", "resultado": f"N/A (Error Selenium en {url_to_visit}: {type(e).__name__})"}

    page_home_id, page_away_id, _, _, _, _ = get_team_league_info_from_script_of(soup_selenium)
    
    # Determina qué tabla de historial buscar (v1 para local, v2 para visitante)
    # y qué equipo buscar dentro de esa tabla.
    search_params = []
    if str(page_home_id) == str(rival_1_id): search_params.append(("table_v1", rival_2_id, rival_2_name))
    if str(page_away_id) == str(rival_1_id): search_params.append(("table_v2", rival_2_id, rival_2_name))
    if str(page_home_id) == str(rival_2_id): search_params.append(("table_v1", rival_1_id, rival_1_name))
    if str(page_away_id) == str(rival_2_id): search_params.append(("table_v2", rival_1_id, rival_1_name))

    if not search_params:
        return {"status": "not_found", "resultado": f"Rivales ({rival_1_name}, {rival_2_name}) no hallados en partido de ref. (ID: {key_match_id})."}

    # Itera sobre las posibles tablas a buscar para encontrar el H2H
    for table_id, opponent_id_to_find, _ in search_params:
        table_to_search = soup_selenium.find("table", id=table_id)
        if not table_to_search: continue

        table_num = table_id[-1]
        score_class_re = re.compile(rf"fscore_{table_num}")
        for row in table_to_search.find_all("tr", id=re.compile(rf"tr{table_num}_\d+")):
            links = row.find_all("a", onclick=True)
            if len(links) < 2: continue

            onclick_home, onclick_away = links[0].get("onclick", ""), links[1].get("onclick", "")
            h2h_row_home_id_m = re.search(r"loadTeam\('(\d+)'", onclick_home)
            h2h_row_away_id_m = re.search(r"loadTeam\('(\d+)'", onclick_away)

            if not h2h_row_home_id_m or not h2h_row_away_id_m: continue
            
            h2h_row_home_id, h2h_row_away_id = h2h_row_home_id_m.group(1), h2h_row_away_id_m.group(1)

            if {h2h_row_home_id, h2h_row_away_id} == {str(rival_1_id), str(rival_2_id)}:
                score_span = row.find("span", class_=score_class_re)
                if not score_span or "-" not in score_span.text: continue
                
                score_val = score_span.text.strip().split("(")[0].strip()
                g_h, g_a = score_val.split("-", 1)
                
                tds = row.find_all("td")
                handicap_raw = "N/A"
                if len(tds) > 11:
                    cell = tds[11]
                    d_o = cell.get("data-o")
                    handicap_raw = d_o.strip() if d_o and d_o.strip() else (cell.text.strip() if cell.text.strip() else "N/A")

                return {
                    "status": "found", "goles_home": g_h.strip(), "goles_away": g_a.strip(),
                    "handicap": handicap_raw, "h2h_home_team_name": links[0].text.strip(),
                    "h2h_away_team_name": links[1].text.strip(), "match_id": row.get('index')
                }

    return {"status": "not_found", "resultado": f"H2H no hallado para {rival_1_name} vs {rival_2_name}."}


def get_team_league_info_from_script_of(soup):
    home_id, away_id, league_id, home_name, away_name, league_name = (None,)*3 + ("N/A",)*3
    if (script_tag := soup.find("script", string=re.compile(r"var _matchInfo ="))) and script_tag.string:
        script_content = script_tag.string
        if (h_id_m := re.search(r"hId:\s*parseInt\('(\d+)'\)", script_content)): home_id = h_id_m.group(1)
        if (g_id_m := re.search(r"gId:\s*parseInt\('(\d+)'\)", script_content)): away_id = g_id_m.group(1)
        if (sclass_id_m := re.search(r"sclassId:\s*parseInt\('(\d+)'\)", script_content)): league_id = sclass_id_m.group(1)
        if (h_name_m := re.search(r"hName:\s*'([^']*)'", script_content)): home_name = h_name_m.group(1).replace("\\'", "'")
        if (g_name_m := re.search(r"gName:\s*'([^']*)'", script_content)): away_name = g_name_m.group(1).replace("\\'", "'")
        if (l_name_m := re.search(r"lName:\s*'([^']*)'", script_content)): league_name = l_name_m.group(1).replace("\\'", "'")
    return home_id, away_id, league_id, home_name, away_name, league_name

def click_element_robust_of(driver, by, value, timeout=7):
    try:
        element = WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.presence_of_element_located((by, value)))
        WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.visibility_of(element))
        driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'center'});", element); time.sleep(0.3)
        try: WebDriverWait(driver, 2, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.element_to_be_clickable((by, value))).click()
        except (ElementClickInterceptedException, TimeoutException): driver.execute_script("arguments[0].click();", element)
        return True
    except: return False


def extract_last_match_in_league_of(driver, table_css_id_str, main_team_name_in_table, league_id_filter_value, home_or_away_filter_css_selector, is_home_game_filter):
    try:
        if league_id_filter_value:
            click_element_robust_of(driver, By.CSS_SELECTOR, f"input#checkboxleague{table_css_id_str[-1]}[value='{league_id_filter_value}']"); time.sleep(1.0)
        click_element_robust_of(driver, By.CSS_SELECTOR, home_or_away_filter_css_selector); time.sleep(1.0)
        
        soup_updated = BeautifulSoup(driver.page_source, "html.parser")
        if not (table := soup_updated.find("table", id=table_css_id_str)): return None

        for row in table.find_all("tr", id=re.compile(rf"tr{table_css_id_str[-1]}_\d+")):
            if ("display:none" in row.get("style","").lower()) or (league_id_filter_value and row.get("name") != str(league_id_filter_value)): continue
            if len(tds := row.find_all("td")) < 14 or not (home_el := tds[2].find("a")) or not (away_el := tds[4].find("a")): continue

            home_name, away_name = home_el.text.strip(), away_el.text.strip()
            team_is_home = main_team_name_in_table.lower() == home_name.lower()
            team_is_away = main_team_name_in_table.lower() == away_name.lower()

            if (is_home_game_filter and team_is_home) or (not is_home_game_filter and team_is_away):
                score = (s.text.strip() if (s := tds[3].find("span", class_=re.compile(r"fscore_"))) else "N/A")
                handicap_raw = (d.strip() if (d := tds[11].get("data-o")) and d.strip() not in ["", "-"] else (t if (t:=tds[11].text.strip()) and t not in ["","-"] else "N/A"))
                return {"date": (d.text.strip() if (d := tds[1].find("span", {"name": "timeData"})) else "N/A"),
                        "home_team": home_name, "away_team": away_name, "score": score,
                        "handicap_line_raw": handicap_raw, "match_id": row.get('index')}
        return None
    except: return None

# --- FUNCIÓN CORREGIDA ---
def extract_last_match_overall_of(driver, table_css_id_str, main_team_name_in_table, league_id_filter_value):
    try:
        click_element_robust_of(driver, By.CSS_SELECTOR, f"input#cb_sos{table_css_id_str[-1]}[value='0']"); time.sleep(0.8)
        if league_id_filter_value:
            click_element_robust_of(driver, By.CSS_SELECTOR, f"input#checkboxleague{table_css_id_str[-1]}[value='{league_id_filter_value}']"); time.sleep(0.8)

        soup_updated = BeautifulSoup(driver.page_source, "html.parser")
        if not (table := soup_updated.find("table", id=table_css_id_str)): return None

        for row in table.find_all("tr", id=re.compile(rf"tr{table_css_id_str[-1]}_\d+")):
            if ("display:none" in row.get("style", "").lower()) or (league_id_filter_value and row.get("name") != str(league_id_filter_value)): continue
            if len(tds := row.find_all("td")) < 14 or not (home_el := tds[2].find("a")) or not (away_el := tds[4].find("a")): continue

            home_name, away_name = home_el.text.strip(), away_el.text.strip()

            if main_team_name_in_table.lower() in [home_name.lower(), away_name.lower()]:
                opponent_element = away_el if main_team_name_in_table.lower() == home_name.lower() else home_el
                opponent_name = opponent_element.text.strip()
                opponent_id = None
                if onclick_attr := opponent_element.get("onclick"):
                    # CORRECCIÓN: El patrón correcto en las tablas de historial es 'loadTeam'
                    if id_match := re.search(r"loadTeam\('(\d+)'", onclick_attr):
                        opponent_id = id_match.group(1)

                score = (s.text.strip() if (s := tds[3].find("span", class_=re.compile(r"fscore_"))) else "N/A")
                handicap_raw = (d.strip() if (d := tds[11].get("data-o")) and d.strip() not in ["", "-"] else (t if (t:=tds[11].text.strip()) and t not in ["","-"] else "N/A"))

                return {"date": (d.text.strip() if (d := tds[1].find("span", {"name": "timeData"})) else "N/A"),
                        "home_team": home_name, "away_team": away_name, "score": score,
                        "handicap_line_raw": handicap_raw, "match_id": row.get('index'),
                        "opponent_name": opponent_name, "opponent_id": opponent_id}
        return None
    except: return None


def get_main_match_odds_selenium_of(driver):
    odds_info = {"ah_home_cuota": "N/A", "ah_linea_raw": "N/A", "ah_away_cuota": "N/A", "goals_over_cuota": "N/A", "goals_linea_raw": "N/A", "goals_under_cuota": "N/A"}
    try:
        live_compare_div = WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS_OF).until(EC.presence_of_element_located((By.ID, "liveCompareDiv")))
        table_odds = live_compare_div.find_element(By.XPATH, ".//table[contains(@class, 'team-table-other')]")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", table_odds); time.sleep(0.5)
        
        bet365_row = None
        try: bet365_row = WebDriverWait(driver, 5).until(EC.visibility_of_element_located((By.CSS_SELECTOR, "tr#tr_o_1_8[name='earlyOdds']")))
        except TimeoutException:
            try: bet365_row = WebDriverWait(driver, 3).until(EC.visibility_of_element_located((By.CSS_SELECTOR, "tr#tr_o_1_31[name='earlyOdds']")))
            except TimeoutException: return odds_info

        if len(tds := bet365_row.find_elements(By.TAG_NAME, "td")) >= 11:
            odds_info["ah_home_cuota"] = tds[2].get_attribute("data-o") or tds[2].text.strip() or "N/A"
            odds_info["ah_linea_raw"] = tds[3].get_attribute("data-o") or tds[3].text.strip() or "N/A"
            odds_info["ah_away_cuota"] = tds[4].get_attribute("data-o") or tds[4].text.strip() or "N/A"
            odds_info["goals_over_cuota"] = tds[8].get_attribute("data-o") or tds[8].text.strip() or "N/A"
            odds_info["goals_linea_raw"] = tds[9].get_attribute("data-o") or tds[9].text.strip() or "N/A"
            odds_info["goals_under_cuota"] = tds[10].get_attribute("data-o") or tds[10].text.strip() or "N/A"
    except: pass
    return odds_info

def extract_standings_data_from_h2h_page_of(h2h_soup, target_team_name_exact):
    data = {"name": target_team_name_exact, "ranking": "N/A", "total_pj": "N/A", "total_v": "N/A", "total_e": "N/A", "total_d": "N/A", "total_gf": "N/A", "total_gc": "N/A", "specific_pj": "N/A", "specific_v": "N/A", "specific_e": "N/A", "specific_d": "N/A", "specific_gf": "N/A", "specific_gc": "N/A", "specific_type": "N/A"}
    if not h2h_soup or not target_team_name_exact or not (standings_section := h2h_soup.find("div", id="porletP4")): return data

    team_table_soup, is_home_table_type = None, False
    if (home_div := standings_section.find("div", class_="home-div")) and (header_tr := home_div.find("tr", class_="team-home")) and header_tr.find("a") and target_team_name_exact.lower() in header_tr.find("a").get_text(strip=True).lower():
        team_table_soup, is_home_table_type, data["specific_type"] = home_div.find("table", class_="team-table-home"), True, "Est. como Local (en Liga)"
    elif (guest_div := standings_section.find("div", class_="guest-div")) and (header_tr := guest_div.find("tr", class_="team-guest")) and header_tr.find("a") and target_team_name_exact.lower() in header_tr.find("a").get_text(strip=True).lower():
        team_table_soup, data["specific_type"] = guest_div.find("table", class_="team-table-guest"), "Est. como Visitante (en Liga)"

    if not team_table_soup: return data
    if (header_link := team_table_soup.find("tr", class_=re.compile(r"team-(home|guest)")).find("a")):
        full_text = header_link.get_text(separator=" ", strip=True)
        if (name_match := re.search(r"]\s*(.*)", full_text)): data["name"] = name_match.group(1).strip()
        if (rank_match := re.search(r"\[(?:[^\]]+-)?(\d+)\]", full_text)): data["ranking"] = rank_match.group(1)

    in_ft_section = False
    for row in team_table_soup.find_all("tr", align="center"):
        if (th_header := row.find("th")):
            in_ft_section = "FT" in th_header.get_text(strip=True)
            if not in_ft_section: break
            continue
        if in_ft_section and len(cells := row.find_all("td")) >= 7:
            row_type_text = (cells[0].find("span") or cells[0]).get_text(strip=True)
            pj, v, e, d, gf, gc = [cell.get_text(strip=True) or "N/A" for cell in cells[1:7]]
            if row_type_text == "Total": data.update({"total_pj": pj, "total_v": v, "total_e": e, "total_d": d, "total_gf": gf, "total_gc": gc})
            elif (row_type_text == "Home" and is_home_table_type) or (row_type_text == "Away" and not is_home_table_type):
                data.update({"specific_pj": pj, "specific_v": v, "specific_e": e, "specific_d": d, "specific_gf": gf, "specific_gc": gc})
    return data

def extract_final_score_of(soup):
    try:
        if len(score_divs := soup.select('#mScore .end .score')) == 2:
            hs, aws = score_divs[0].text.strip(), score_divs[1].text.strip()
            if hs.isdigit() and aws.isdigit(): return f"{hs}:{aws}", f"{hs}-{aws}"
    except: pass
    return '?:?', "?-?"

def extract_h2h_data_of(soup, main_home_team_name, main_away_team_name, current_league_id):
    defaults = ('-', '?:?', '?-?', None, '-', '?:?', '?-?', None, "Local (H2H Gen)", "Visitante (H2H Gen)")
    if not soup or not main_home_team_name or not main_away_team_name or not (h2h_table := soup.find("table", id="table_v3")):
        return defaults

    filtered_h2h_list = [d for row in h2h_table.find_all("tr", id=re.compile(r"tr3_\d+")) if (d := get_match_details_from_row_of(row, 'fscore_3', 'h2h')) and (not current_league_id or not d.get('league_id_hist') or d.get('league_id_hist') == str(current_league_id))]
    if not filtered_h2h_list: return defaults

    h2h_gen = filtered_h2h_list[0]
    h2h_local = next((d for d in filtered_h2h_list if d.get('home','').lower() == main_home_team_name.lower() and d.get('away','').lower() == main_away_team_name.lower()), None)
    
    ah1, res1, res1_raw, match1_id = (h2h_local.get(k,v) for k,v in {'ahLine':'-', 'score':'?:?', 'score_raw':'?-?', 'matchIndex':None}.items()) if h2h_local else ('-', '?:?', '?-?', None)
    ah6, res6, res6_raw, match6_id = (h2h_gen.get(k,v) for k,v in {'ahLine':'-', 'score':'?:?', 'score_raw':'?-?', 'matchIndex':None}.items())
    return ah1, res1, res1_raw, match1_id, ah6, res6, res6_raw, match6_id, h2h_gen.get('home'), h2h_gen.get('away')

def extract_comparative_match_of(soup_for_team_history, table_id_of_team_to_search, team_name_to_find_match_for, opponent_name_to_search, current_league_id, is_home_table):
    if not opponent_name_to_search or opponent_name_to_search == "N/A" or not team_name_to_find_match_for or not (table := soup_for_team_history.find("table", id=table_id_of_team_to_search)):
        return None

    score_class_selector = 'fscore_1' if is_home_table else 'fscore_2'
    for row in table.find_all("tr", id=re.compile(rf"tr{table_id_of_team_to_search[-1]}_\d+")):
        if not (details := get_match_details_from_row_of(row, score_class_selector, 'hist')): continue
        if current_league_id and details.get('league_id_hist') and details.get('league_id_hist') != str(current_league_id): continue

        home_hist, away_hist = details.get('home','').lower(), details.get('away','').lower()
        if {team_name_to_find_match_for.lower(), opponent_name_to_search.lower()} == {home_hist, away_hist}:
            return {"score": details.get('score', '?:?'), "ah_line": details.get('ahLine', '-'),
                    "localia": 'H' if team_name_to_find_match_for.lower() == home_hist else 'A',
                    "home_team": details.get('home'), "away_team": details.get('away'), "match_id": details.get('matchIndex')}
    return None

# --- STREAMLIT APP UI (Función principal) ---
def display_other_feature_ui():
    st.markdown("""
    <style>
        .main-title { font-size: 2.2em; font-weight: bold; color: #1E90FF; text-align: center; margin-bottom: 5px; }
        .sub-title { font-size: 1.6em; text-align: center; margin-bottom: 15px; }
        .section-header { font-size: 1.8em; font-weight: bold; color: #4682B4; margin-top: 25px; margin-bottom: 15px; border-bottom: 2px solid #4682B4; padding-bottom: 5px;}
        .card-title { font-size: 1.3em; font-weight: bold; color: #333; margin-bottom: 10px; }
        .card-subtitle { font-size: 1.1em; font-weight: bold; color: #555; margin-top:15px; margin-bottom: 8px; }
        .home-color { color: #007bff; font-weight: bold; }
        .away-color { color: #fd7e14; font-weight: bold; }
        .score-value { font-size: 1.1em; font-weight: bold; color: #28a745; margin: 0 5px; }
        .ah-value { font-weight: bold; color: #6f42c1; }
        .data-highlight { font-weight: bold; color: #dc3545; }
        .standings-table p { margin-bottom: 0.3rem; font-size: 0.95em;}
        .standings-table strong { min-width: 50px; display: inline-block; }
        .stMetric { border: 1px solid #ddd; border-radius: 5px; padding: 10px; margin-bottom:10px; background-color: #f9f9f9; }
        h6 {margin-top:10px; margin-bottom:5px; font-style:italic; color: #005A9C;}
    </style>
    """, unsafe_allow_html=True)

    st.sidebar.image("https://raw.githubusercontent.com/streamlit/docs/main/public/images/brand/streamlit-logo-secondary-colormark-darktext.svg", width=200)
    st.sidebar.title("⚙️ Configuración del Partido (OF)")
    main_match_id_str_input_of = st.sidebar.text_input("🆔 ID Partido Principal:", value="2591232", help="Pega el ID numérico del partido que deseas analizar.", key="other_feature_match_id_input")
    analizar_button_of = st.sidebar.button("🚀 Analizar Partido (OF)", type="primary", use_container_width=True, key="other_feature_analizar_button")

    results_container = st.container()
    if 'driver_other_feature' not in st.session_state:
        st.session_state.driver_other_feature = None

    if analizar_button_of:
        results_container.empty()
        main_match_id_to_process_of = int("".join(filter(str.isdigit, main_match_id_str_input_of))) if main_match_id_str_input_of.isdigit() else None
        if not main_match_id_to_process_of:
            results_container.error("⚠️ El ID de partido ingresado no es válido."); st.stop()

        start_time_of = time.time()
        with results_container, st.spinner("🔄 Cargando datos iniciales y análisis..."):
            main_page_url_h2h_view_of = f"/match/h2h-{main_match_id_to_process_of}"
            soup_main_h2h_page_of = fetch_soup_requests_of(main_page_url_h2h_view_of)
            if not soup_main_h2h_page_of:
                st.error(f"❌ No se pudo obtener la página H2H para ID {main_match_id_to_process_of}."); st.stop()

            mp_home_id_of, mp_away_id_of, mp_league_id_of, mp_home_name_from_script, mp_away_name_from_script, mp_league_name_of = get_team_league_info_from_script_of(soup_main_h2h_page_of)
            
            home_team_main_standings = extract_standings_data_from_h2h_page_of(soup_main_h2h_page_of, mp_home_name_from_script)
            away_team_main_standings = extract_standings_data_from_h2h_page_of(soup_main_h2h_page_of, mp_away_name_from_script)
            
            display_home_name = home_team_main_standings.get("name", "N/A") if home_team_main_standings.get("name") != "N/A" else mp_home_name_from_script
            display_away_name = away_team_main_standings.get("name", "N/A") if away_team_main_standings.get("name") != "N/A" else mp_away_name_from_script

            st.markdown(f"<p class='main-title'>📊 Análisis Avanzado de Partido (OF) ⚽</p>", unsafe_allow_html=True)
            st.markdown(f"<p class='sub-title'>🆚 <span class='home-color'>{display_home_name}</span> vs <span class='away-color'>{display_away_name}</span></p>", unsafe_allow_html=True)
            st.caption(f"🏆 **Liga:** {mp_league_name_of or PLACEHOLDER_NODATA} | 🆔 **Partido ID:** <span class='data-highlight'>{main_match_id_to_process_of}</span>", unsafe_allow_html=True)
            st.divider()

            st.markdown("<h2 class='section-header'>📈 Clasificación en Liga</h2>", unsafe_allow_html=True)
            col_home_stand, col_away_stand = st.columns(2)

            def display_standings_card(team_standings_data, team_display_name, team_color_class):
                st.markdown(f"<h3 class='card-title {team_color_class}'>{team_standings_data.get('name', team_display_name)} (Ranking: {team_standings_data.get('ranking', 'N/A')})</h3>", unsafe_allow_html=True)
                st.markdown(f"<div class='standings-table'><b>Total en Liga:</b><p><strong>PJ:</strong> {team_standings_data.get('total_pj', '-')}  <strong>V:</strong> {team_standings_data.get('total_v', '-')}  <strong>E:</strong> {team_standings_data.get('total_e', '-')}  <strong>D:</strong> {team_standings_data.get('total_d', '-')}</p><p><strong>GF:</strong> {team_standings_data.get('total_gf', '-')}  <strong>GC:</strong> {team_standings_data.get('total_gc', '-')}</p></div>", unsafe_allow_html=True)
                st.markdown(f"<div class='standings-table'><b>{team_standings_data.get('specific_type', 'Estadísticas Específicas')}:</b><p><strong>PJ:</strong> {team_standings_data.get('specific_pj', '-')}  <strong>V:</strong> {team_standings_data.get('specific_v', '-')}  <strong>E:</strong> {team_standings_data.get('specific_e', '-')}  <strong>D:</strong> {team_standings_data.get('specific_d', '-')}</p><p><strong>GF:</strong> {team_standings_data.get('specific_gf', '-')}  <strong>GC:</strong> {team_standings_data.get('specific_gc', '-')}</p></div>", unsafe_allow_html=True)

            with col_home_stand: display_standings_card(home_team_main_standings, display_home_name, "home-color")
            with col_away_stand: display_standings_card(away_team_main_standings, display_away_name, "away-color")
            st.divider()
            
            key_match_id_for_rival_a_h2h, rival_a_id_orig_col3, rival_a_name_orig_col3 = get_rival_a_for_original_h2h_of(main_match_id_to_process_of)
            match_id_rival_b_game_ref, rival_b_id_orig_col3, rival_b_name_orig_col3 = get_rival_b_for_original_h2h_of(main_match_id_to_process_of)

            driver_actual_of = st.session_state.driver_other_feature
            try:
                if driver_actual_of is None or (hasattr(driver_actual_of, 'service') and not driver_actual_of.service.is_connectable()):
                    if driver_actual_of: driver_actual_of.quit()
                    driver_actual_of = get_selenium_driver_of()
                    st.session_state.driver_other_feature = driver_actual_of
            except WebDriverException:
                driver_actual_of = get_selenium_driver_of()
                st.session_state.driver_other_feature = driver_actual_of

            main_match_odds_data_of, last_home_match_in_league_of, last_away_match_in_league_of, last_overall_home_team_match, last_overall_away_team_match = {}, None, None, None, None
            if driver_actual_of:
                try:
                    driver_actual_of.get(f"{BASE_URL_OF}{main_page_url_h2h_view_of}")
                    WebDriverWait(driver_actual_of, SELENIUM_TIMEOUT_SECONDS_OF).until(EC.presence_of_element_located((By.ID, "table_v1")))
                    time.sleep(0.8)
                    main_match_odds_data_of = get_main_match_odds_selenium_of(driver_actual_of)
                    if mp_home_id_of and mp_league_id_of:
                        last_home_match_in_league_of = extract_last_match_in_league_of(driver_actual_of, "table_v1", display_home_name, mp_league_id_of, "input#cb_sos1[value='1']", True)
                        last_overall_home_team_match = extract_last_match_overall_of(driver_actual_of, "table_v1", display_home_name, mp_league_id_of)
                    if mp_away_id_of and mp_league_id_of:
                        last_away_match_in_league_of = extract_last_match_in_league_of(driver_actual_of, "table_v2", display_away_name, mp_league_id_of, "input#cb_sos2[value='2']", False)
                        last_overall_away_team_match = extract_last_match_overall_of(driver_actual_of, "table_v2", display_away_name, mp_league_id_of)
                except Exception as e: st.error(f"❗ Error de Selenium: {e}")
            else: st.warning("❗ WebDriver no disponible. Funcionalidad limitada.")

            st.markdown("<h2 class='section-header'>🎯 Análisis Detallado del Partido</h2>", unsafe_allow_html=True)

            def render_match_card(title, data, team_color_class="home-color", opponent_color_class="away-color"):
                st.markdown(f"<h4 class='card-title'>{title}</h4>", unsafe_allow_html=True)
                if not data:
                    st.info(f"Datos no encontrados para esta sección.")
                    return
                
                is_home = data['home_team'].lower() == title.split('<span')[1].split('>')[1].split('<')[0].lower()
                opponent_name = data['away_team'] if is_home else data['home_team']
                
                st.markdown(f"🆚 <span class='{opponent_color_class}'>{opponent_name}</span>", unsafe_allow_html=True)
                st.markdown(f"<div style='margin-top: 8px; margin-bottom: 8px;'><span class='home-color'>{data['home_team']}</span> <span class='score-value'>{data['score'].replace('-',':')}</span> <span class='away-color'>{data['away_team']}</span></div>", unsafe_allow_html=True)
                st.markdown(f"**AH:** <span class='ah-value'>{format_ah_as_decimal_string_of(data.get('handicap_line_raw','-')) or PLACEHOLDER_NODATA}</span>", unsafe_allow_html=True)
                st.caption(f"📅 {data.get('date', 'N/A')}")
                display_previous_match_progression_stats(f"Ref: {data.get('home_team','L')} vs {data.get('away_team','V')}", data.get('match_id'), data.get('home_team'), data.get('away_team'))

            st.markdown("<h3 class='section-header' style='font-size:1.5em; margin-top:30px;'>⚡ Rendimiento Reciente (Local vs Visitante) y H2H Indirecto</h3>", unsafe_allow_html=True)
            rp_col1, rp_col2, rp_col3 = st.columns(3)
            with rp_col1: render_match_card(f"Último <span class='home-color'>{display_home_name}</span> (Casa)", last_home_match_in_league_of)
            with rp_col2: render_match_card(f"Último <span class='away-color'>{display_away_name}</span> (Fuera)", last_away_match_in_league_of, "away-color", "home-color")
            with rp_col3:
                st.markdown(f"<h4 class='card-title'>🆚 H2H Rivales Recientes</h4>", unsafe_allow_html=True)
                details_h2h_col3_of = get_h2h_details_of(driver_actual_of, key_match_id_for_rival_a_h2h, rival_a_id_orig_col3, rival_b_id_orig_col3, rival_a_name_orig_col3, rival_b_name_orig_col3) if all([key_match_id_for_rival_a_h2h, rival_a_id_orig_col3, rival_b_id_orig_col3, driver_actual_of]) else {"status": "error", "resultado": "Datos insuficientes."}
                if details_h2h_col3_of.get("status") == "found":
                    res = details_h2h_col3_of
                    st.markdown(f"<span class='home-color'>{res.get('h2h_home_team_name')}</span> <span class='score-value'>{res.get('goles_home', '?')}:{res.get('goles_away', '?')}</span> <span class='away-color'>{res.get('h2h_away_team_name')}</span>", unsafe_allow_html=True)
                    st.markdown(f"**AH:** <span class='ah-value'>{format_ah_as_decimal_string_of(res.get('handicap','-')) or PLACEHOLDER_NODATA}</span>", unsafe_allow_html=True)
                    display_previous_match_progression_stats(f"H2H Rivales: {res.get('h2h_home_team_name')} vs {res.get('h2h_away_team_name')}", res.get('match_id'), res.get('h2h_home_team_name'), res.get('h2h_away_team_name'))
                else: st.info(details_h2h_col3_of.get('resultado', "H2H no encontrado."))

            st.divider()
            
            # --- SECCIÓN GENERAL CORREGIDA ---
            st.markdown("<h3 class='section-header' style='font-size:1.5em; margin-top:30px;'>⚡ Rendimiento Último Partido (General) y H2H Indirecto</h3>", unsafe_allow_html=True)
            rp_gen_col1, rp_gen_col2, rp_gen_col3 = st.columns(3)
            with rp_gen_col1: render_match_card(f"Último General <span class='home-color'>{display_home_name}</span>", last_overall_home_team_match)
            with rp_gen_col2: render_match_card(f"Último General <span class='away-color'>{display_away_name}</span>", last_overall_away_team_match, "away-color", "home-color")
            with rp_gen_col3:
                st.markdown(f"<h4 class='card-title'>🆚 H2H Últimos Rivales</h4>", unsafe_allow_html=True)
                h2h_data = {}
                if last_overall_home_team_match and last_overall_away_team_match and driver_actual_of:
                    key_match = last_overall_home_team_match.get('match_id')
                    rival_a_id, rival_a_name = last_overall_home_team_match.get('opponent_id'), last_overall_home_team_match.get('opponent_name')
                    rival_b_id, rival_b_name = last_overall_away_team_match.get('opponent_id'), last_overall_away_team_match.get('opponent_name')
                    if all([key_match, rival_a_id, rival_b_id, rival_a_name, rival_b_name]):
                        h2h_data = get_h2h_details_of(driver_actual_of, key_match, rival_a_id, rival_b_id, rival_a_name, rival_b_name)
                    else: h2h_data = {"status": "error", "resultado": "Faltan IDs de rivales para buscar H2H."}
                
                if h2h_data.get("status") == "found":
                    res = h2h_data
                    st.markdown(f"<span class='home-color'>{res.get('h2h_home_team_name')}</span> <span class='score-value'>{res.get('goles_home', '?')}:{res.get('goles_away', '?')}</span> <span class='away-color'>{res.get('h2h_away_team_name')}</span>", unsafe_allow_html=True)
                    st.markdown(f"**AH:** <span class='ah-value'>{format_ah_as_decimal_string_of(res.get('handicap','-')) or PLACEHOLDER_NODATA}</span>", unsafe_allow_html=True)
                    display_previous_match_progression_stats(f"H2H Últimos Rivales: {res.get('h2h_home_team_name')} vs {res.get('h2h_away_team_name')}", res.get('match_id'), res.get('h2h_home_team_name'), res.get('h2h_away_team_name'))
                else: st.info(h2h_data.get('resultado', 'H2H no disponible.'))

            st.sidebar.success(f"🎉 Análisis completado en {time.time() - start_time_of:.2f} segundos.")
    else:
        results_container.info("✨ ¡Bienvenido! Ingresa un ID de partido y haz clic en 'Analizar Partido (OF)'.")

if __name__ == '__main__':
    st.set_page_config(layout="wide", page_title="Análisis Avanzado de Partidos (OF)", initial_sidebar_state="expanded")
    display_other_feature_ui()
