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

# --- FUNCIONES DE ESTADÍSTICAS DE PROGRESIÓN (MODIFICADAS PARA NO ANIDAR EXPANDERS) ---
@st.cache_data(ttl=7200)
def get_match_progression_stats_data(match_id: str) -> pd.DataFrame | None:
    base_url_live = "https://live18.nowgoal25.com/match/live-"
    full_url = f"{base_url_live}{match_id}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
        "Accept-Encoding": "gzip, deflate, br", "Accept-Language": "en-US,en;q=0.9", "DNT": "1",
        "Connection": "keep-alive", "Upgrade-Insecure-Requests": "1",
    }
    stat_titles_of_interest = {
        "Shots": {"Home": "-", "Away": "-"}, "Shots on Goal": {"Home": "-", "Away": "-"},
        "Attacks": {"Home": "-", "Away": "-"}, "Dangerous Attacks": {"Home": "-", "Away": "-"},
    }
    try:
        response = requests.get(full_url, headers=headers, timeout=15)
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
                                stat_titles_of_interest[stat_title]["Home"] = values[0].get_text(strip=True)
                                stat_titles_of_interest[stat_title]["Away"] = values[1].get_text(strip=True)
    except: return None
    table_rows = [{"Estadistica_EN": name, "Casa": vals['Home'], "Fuera": vals['Away']} for name, vals in stat_titles_of_interest.items()]
    df = pd.DataFrame(table_rows)
    return df.set_index("Estadistica_EN") if not df.empty else df

def display_match_progression_stats_view(match_id: str, home_team_name: str, away_team_name: str):
    stats_df = get_match_progression_stats_data(match_id)
    if stats_df is None:
        st.caption(f"Estadísticas de progresión no pudieron ser obtenidas para el partido ID: **{match_id}**.")
        return
    if stats_df.empty:
        st.caption(f"No se encontraron datos de progresión para el partido ID: **{match_id}**.")
        return

    ordered_stats_display = {
        "Shots": "Disparos", "Shots on Goal": "Disparos a Puerta",
        "Attacks": "Ataques", "Dangerous Attacks": "Ataques Peligrosos"
    }
    st.markdown("---") # Separador visual
    col_h_name, col_stat_name, col_a_name = st.columns([2, 3, 2])
    with col_h_name: st.markdown(f"<p style='font-weight:bold; color: #007bff;'>{home_team_name or 'Local'}</p>", unsafe_allow_html=True)
    with col_stat_name: st.markdown("<p style='text-align:center; font-weight:bold;'>Estadística</p>", unsafe_allow_html=True)
    with col_a_name: st.markdown(f"<p style='text-align:right; font-weight:bold; color: #fd7e14;'>{away_team_name or 'Visitante'}</p>", unsafe_allow_html=True)
    
    for stat_key_en, stat_name_es in ordered_stats_display.items():
        if stat_key_en in stats_df.index:
            home_val_str, away_val_str = stats_df.loc[stat_key_en, 'Casa'], stats_df.loc[stat_key_en, 'Fuera']
            try: home_val_num = int(home_val_str)
            except ValueError: home_val_num = 0
            try: away_val_num = int(away_val_str)
            except ValueError: away_val_num = 0
            home_color, away_color = ("green", "red") if home_val_num > away_val_num else (("red", "green") if away_val_num > home_val_num else ("black", "black"))
            
            c1, c2, c3 = st.columns([2, 3, 2])
            with c1: c1.markdown(f'<p style="font-size: 1.1em; font-weight:bold; color:{home_color};">{home_val_str}</p>', unsafe_allow_html=True)
            with c2: c2.markdown(f'<p style="text-align:center;">{stat_name_es}</p>', unsafe_allow_html=True)
            with c3: c3.markdown(f'<p style="text-align:right; font-size: 1.1em; font-weight:bold; color:{away_color};">{away_val_str}</p>', unsafe_allow_html=True)
        else:
            c1, c2, c3 = st.columns([2, 3, 2])
            with c1: c1.markdown('<p style="color:grey;">-</p>', unsafe_allow_html=True)
            with c2: c2.markdown(f'<p style="text-align:center; color:grey;">{stat_name_es} (no disp.)</p>', unsafe_allow_html=True)
            with c3: c3.markdown('<p style="text-align:right; color:grey;">-</p>', unsafe_allow_html=True)
    st.markdown("---")

def display_previous_match_progression_stats(title: str, match_id_str: str | None, home_name: str, away_name: str):
    if not match_id_str or match_id_str == "N/A" or not match_id_str.isdigit():
        return # No muestra nada si no hay ID válido
    
    # Usar un subtítulo o markdown en lugar de un expander anidado
    st.markdown(f"###### 👁️ _Est. Progresión para: {title}_") # Título más pequeño
    display_match_progression_stats_view(match_id_str, home_name, away_name)

# --- FUNCIONES DE EXTRACCIÓN DE DATOS DEL PARTIDO (Selenium y BeautifulSoup) ---
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
    # ... (código existente de la función)
    # Modificación: Asegurarse de devolver 'match_id' del partido H2H encontrado
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
            
            match_id_h2h_rivals = row.get('index') 
            rol_a_in_this_h2h = "H" if h2h_row_home_id == str(rival_a_id) else "A"
            
            return {"status": "found", "goles_home": g_h.strip(), "goles_away": g_a.strip(), 
                    "handicap": handicap_raw, "rol_rival_a": rol_a_in_this_h2h, 
                    "h2h_home_team_name": links[0].text.strip(), 
                    "h2h_away_team_name": links[1].text.strip(),
                    "match_id": match_id_h2h_rivals} 
                    
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
    # ... (código existente)
    try:
        element = WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.presence_of_element_located((by, value)))
        WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.visibility_of(element))
        driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'center'});", element); time.sleep(0.3)
        try: WebDriverWait(driver, 2, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.element_to_be_clickable((by, value))).click()
        except (ElementClickInterceptedException, TimeoutException): driver.execute_script("arguments[0].click();", element)
        return True
    except Exception: return False


def extract_last_match_in_league_of(driver, table_css_id_str, main_team_name_in_table, league_id_filter_value, home_or_away_filter_css_selector, is_home_game_filter):
    # ... (código existente)
    # Modificación: Asegurarse de devolver 'match_id'
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
            
            if (is_home_game_filter and team_is_home_in_row) or \
               (not is_home_game_filter and team_is_away_in_row):
                date_span = tds[1].find("span", {"name": "timeData"}); date = date_span.text.strip() if date_span else "N/A"
                score_class_re = re.compile(r"fscore_"); score_span = tds[3].find("span", class_=score_class_re); score = score_span.text.strip() if score_span else "N/A"
                handicap_cell = tds[11]; handicap_raw = handicap_cell.get("data-o", handicap_cell.text.strip()) 
                if not handicap_raw or handicap_raw.strip() == "-": handicap_raw = "N/A"
                else: handicap_raw = handicap_raw.strip()
                
                match_id_last_game = row.get('index')
                
                return {"date": date, "home_team": home_team_row_name, 
                        "away_team": away_team_row_name,"score": score, 
                        "handicap_line_raw": handicap_raw,
                        "match_id": match_id_last_game} 
        return None
    except Exception: return None

def get_main_match_odds_selenium_of(driver): # Sin cambios, parece ok
    # ... (código existente)
    odds_info = {"ah_home_cuota": "N/A", "ah_linea_raw": "N/A", "ah_away_cuota": "N/A", "goals_over_cuota": "N/A", "goals_linea_raw": "N/A", "goals_under_cuota": "N/A"}
    try:
        live_compare_div = WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS_OF, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.presence_of_element_located((By.ID, "liveCompareDiv")))
        bet365_row_selector = "tr#tr_o_1_8[name='earlyOdds']"; bet365_row_selector_alt = "tr#tr_o_1_31[name='earlyOdds']" # Considera más IDs si es necesario
        table_odds = live_compare_div.find_element(By.XPATH, ".//table[contains(@class, 'team-table-other')]") # Más robusto
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", table_odds); time.sleep(0.5) # Scroll
        bet365_early_odds_row = None
        try: bet365_early_odds_row = WebDriverWait(driver, 5, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.visibility_of_element_located((By.CSS_SELECTOR, bet365_row_selector)))
        except TimeoutException: 
            try: bet365_early_odds_row = WebDriverWait(driver, 3, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.visibility_of_element_located((By.CSS_SELECTOR, bet365_row_selector_alt)))
            except TimeoutException: return odds_info # No se encontró la fila de Bet365
        tds = bet365_early_odds_row.find_elements(By.TAG_NAME, "td")
        if len(tds) >= 11: # Asegurar que hay suficientes celdas
            odds_info["ah_home_cuota"] = tds[2].get_attribute("data-o") or tds[2].text.strip() or "N/A"
            odds_info["ah_linea_raw"] = tds[3].get_attribute("data-o") or tds[3].text.strip() or "N/A" 
            odds_info["ah_away_cuota"] = tds[4].get_attribute("data-o") or tds[4].text.strip() or "N/A"
            odds_info["goals_over_cuota"] = tds[8].get_attribute("data-o") or tds[8].text.strip() or "N/A"
            odds_info["goals_linea_raw"] = tds[9].get_attribute("data-o") or tds[9].text.strip() or "N/A" 
            odds_info["goals_under_cuota"] = tds[10].get_attribute("data-o") or tds[10].text.strip() or "N/A"
    except Exception: pass # Fallo silencioso para no interrumpir todo el script
    return odds_info


def extract_standings_data_from_h2h_page_of(h2h_soup, target_team_name_exact): # Sin cambios, parece ok
    # ... (código existente)
    data = {"name": target_team_name_exact, "ranking": "N/A", "total_pj": "N/A", "total_v": "N/A", "total_e": "N/A", "total_d": "N/A", "total_gf": "N/A", "total_gc": "N/A", "specific_pj": "N/A", "specific_v": "N/A", "specific_e": "N/A", "specific_d": "N/A", "specific_gf": "N/A", "specific_gc": "N/A", "specific_type": "N/A" }
    if not h2h_soup: return data
    standings_section = h2h_soup.find("div", id="porletP4"); 
    if not standings_section: return data
    team_table_soup = None; is_home_team_table_type = False # Para saber si buscar "Home" o "Away" en las filas FT
    # Intenta encontrar la tabla del equipo local
    home_div_standings = standings_section.find("div", class_="home-div")
    if home_div_standings:
        home_table_header = home_div_standings.find("tr", class_="team-home") # o clase que identifique el header del equipo
        if home_table_header and target_team_name_exact and target_team_name_exact.lower() in home_table_header.get_text().lower(): # Verifica si el nombre está en el header
            team_table_soup = home_div_standings.find("table", class_="team-table-home") # o la clase de la tabla
            is_home_team_table_type = True
            data["specific_type"] = home_div_standings.find("td", class_="bg1").text.strip() if home_div_standings.find("td", class_="bg1") else "En Casa"

    # Si no se encontró como local, intenta como visitante
    if not team_table_soup:
        guest_div_standings = standings_section.find("div", class_="guest-div")
        if guest_div_standings:
            guest_table_header = guest_div_standings.find("tr", class_="team-guest")
            if guest_table_header and target_team_name_exact and target_team_name_exact.lower() in guest_table_header.get_text().lower():
                team_table_soup = guest_div_standings.find("table", class_="team-table-guest")
                is_home_team_table_type = False # Es visitante
                data["specific_type"] = guest_div_standings.find("td", class_="bg1").text.strip() if guest_div_standings.find("td", class_="bg1") else "Fuera"
    
    if not team_table_soup: return data # No se encontró la tabla del equipo

    # Extraer ranking y nombre del header de la tabla encontrada
    header_row_found = team_table_soup.find("tr", class_=re.compile(r"team-(home|guest)")) # team-home o team-guest
    if header_row_found:
        link = header_row_found.find("a")
        if link: # Si el nombre está dentro de un <a>
            full_text = link.get_text(separator=" ", strip=True) # ej: "[NPL Victoria-6] Heidelberg Utd"
            name_match = re.search(r"]\s*(.*)", full_text) # Nombre después del bracket
            rank_match = re.search(r"\[(?:[^\]]+-)?(\d+)\]", full_text) # Ranking, ej: [6] o [SA-NPL-2]
            if name_match: data["name"] = name_match.group(1).strip()
            if rank_match: data["ranking"] = rank_match.group(1)
        else: # Si no hay <a>, tomar el texto directo (menos común)
            header_text_no_link = header_row_found.get_text(separator=" ", strip=True)
            name_match_nl = re.search(r"]\s*(.*)", header_text_no_link)
            if name_match_nl: data["name"] = name_match_nl.group(1).strip()
            rank_match_nl = re.search(r"\[(?:[^\]]+-)?(\d+)\]", header_text_no_link)
            if rank_match_nl: data["ranking"] = rank_match_nl.group(1)

    # Extraer datos de las filas (Total, Home/Away específico)
    ft_rows = []; current_section = None
    for row in team_table_soup.find_all("tr", align="center"): # Filas de datos suelen estar centradas
        th_cell = row.find("th");
        if th_cell: # Identificar sección FT o HT
            if "FT" in th_cell.get_text(strip=True): current_section = "FT"
            elif "HT" in th_cell.get_text(strip=True): break # No nos interesa HT
        
        if current_section == "FT":
            cells = row.find_all("td")
            # Las filas de interés son "Total", "Home", "Away"
            if cells and len(cells) > 0 and cells[0].get_text(strip=True) in ["Total", "Home", "Away"]:
                ft_rows.append(cells)

    for cells in ft_rows:
        if len(cells) > 8: # Típica fila de estadísticas (Tipo, PJ, V, E, D, GF, GC, Pts, GF/p, GC/p)
            row_type_text = cells[0].get_text(strip=True)
            pj, v, e, d, gf, gc = (cells[i].get_text(strip=True) for i in range(1, 7))
            # Asegurar que no sean None
            pj=pj if pj else "N/A"; v=v if v else "N/A"; e=e if e else "N/A"; d=d if d else "N/A"; gf=gf if gf else "N/A"; gc=gc if gc else "N/A"

            if row_type_text=="Total":
                data["total_pj"],data["total_v"],data["total_e"],data["total_d"],data["total_gf"],data["total_gc"]=pj,v,e,d,gf,gc
            elif row_type_text=="Home" and is_home_team_table_type: # Si estamos en la tabla "Home" y la fila es "Home"
                data["specific_pj"],data["specific_v"],data["specific_e"],data["specific_d"],data["specific_gf"],data["specific_gc"]=pj,v,e,d,gf,gc
            elif row_type_text=="Away" and not is_home_team_table_type: # Si estamos en la tabla "Away" y la fila es "Away"
                data["specific_pj"],data["specific_v"],data["specific_e"],data["specific_d"],data["specific_gf"],data["specific_gc"]=pj,v,e,d,gf,gc
    return data

def extract_final_score_of(soup): # Sin cambios, parece ok
    # ... (código existente)
    try:
        score_divs = soup.select('#mScore .end .score') # Selector CSS para los scores
        if len(score_divs) == 2:
            hs = score_divs[0].text.strip(); aws = score_divs[1].text.strip()
            if hs.isdigit() and aws.isdigit(): return f"{hs}*{aws}", f"{hs}-{aws}" # Formato "1*0", "1-0"
    except Exception: pass
    return '?*?', "?-?" # Placeholder si no se encuentra

def extract_h2h_data_of(soup, main_home_team_name, main_away_team_name, current_league_id):
    # ... (código existente)
    # Modificación: Devolver match_id para H2H local y general
    ah1, res1, res1_raw, match1_id = '-', '?*?', '?-?', None
    ah6, res6, res6_raw, match6_id = '-', '?*?', '?-?', None
    
    h2h_table = soup.find("table", id="table_v3")
    if not h2h_table: return ah1, res1, res1_raw, match1_id, ah6, res6, res6_raw, match6_id
    
    filtered_h2h_list = []
    if not main_home_team_name or not main_away_team_name: # Nombres necesarios para filtrar
        return ah1, res1, res1_raw, match1_id, ah6, res6, res6_raw, match6_id

    for row_h2h in h2h_table.find_all("tr", id=re.compile(r"tr3_\d+")):
        details = get_match_details_from_row_of(row_h2h, score_class_selector='fscore_3', source_table_type='h2h')
        if not details: continue
        # Filtrar por liga si es necesario
        if current_league_id and details.get('league_id_hist') and details.get('league_id_hist') != str(current_league_id): continue
        filtered_h2h_list.append(details)
        
    if not filtered_h2h_list: return ah1, res1, res1_raw, match1_id, ah6, res6, res6_raw, match6_id
    
    # H2H General (el más reciente, primer elemento de la lista filtrada)
    h2h_general_match = filtered_h2h_list[0] 
    ah6 = h2h_general_match.get('ahLine', '-') 
    res6 = h2h_general_match.get('score', '?*?'); res6_raw = h2h_general_match.get('score_raw', '?-?')
    match6_id = h2h_general_match.get('matchIndex')

    # H2H con el equipo local actual jugando en casa
    h2h_local_specific_match = None
    for d_h2h in filtered_h2h_list:
        if d_h2h.get('home','').lower() == main_home_team_name.lower() and \
           d_h2h.get('away','').lower() == main_away_team_name.lower():
            h2h_local_specific_match = d_h2h; break
            
    if h2h_local_specific_match:
        ah1 = h2h_local_specific_match.get('ahLine', '-') 
        res1 = h2h_local_specific_match.get('score', '?*?'); res1_raw = h2h_local_specific_match.get('score_raw', '?-?')
        match1_id = h2h_local_specific_match.get('matchIndex')
        
    return ah1, res1, res1_raw, match1_id, ah6, res6, res6_raw, match6_id


def extract_comparative_match_of(soup_for_team_history, table_id_of_team_to_search, team_name_to_find_match_for, opponent_name_to_search, current_league_id, is_home_table):
    # ... (código existente)
    # Modificación: Devolver diccionario con todos los datos, incluyendo match_id
    if not opponent_name_to_search or opponent_name_to_search == "N/A" or not team_name_to_find_match_for:
        return None 
        
    table = soup_for_team_history.find("table", id=table_id_of_team_to_search)
    if not table: return None
    
    score_class_selector = 'fscore_1' if is_home_table else 'fscore_2' # Diferente clase de score para tabla home y away
    
    for row in table.find_all("tr", id=re.compile(rf"tr{table_id_of_team_to_search[-1]}_\d+")):
        details = get_match_details_from_row_of(row, score_class_selector=score_class_selector, source_table_type='hist')
        if not details: continue
        # Filtrar por liga si es necesario
        if current_league_id and details.get('league_id_hist') and details.get('league_id_hist') != str(current_league_id): continue
        
        home_hist = details.get('home','').lower(); away_hist = details.get('away','').lower()
        team_main_lower = team_name_to_find_match_for.lower(); opponent_lower = opponent_name_to_search.lower()
        
        # Comprobar si el partido es entre los dos equipos buscados (en cualquier orden de local/visitante)
        if (team_main_lower == home_hist and opponent_lower == away_hist) or \
           (team_main_lower == away_hist and opponent_lower == home_hist):
            score_val = details.get('score', '?*?')
            ah_line_extracted = details.get('ahLine', '-')
            localia_val = 'H' if team_main_lower == home_hist else 'A' # Localía del team_name_to_find_match_for
            
            return {
                "score": score_val, 
                "ah_line": ah_line_extracted, 
                "localia": localia_val,
                "home_team": details.get('home'), 
                "away_team": details.get('away'), 
                "match_id": details.get('matchIndex') # ID del partido comparativo
            }
    return None

# --- STREAMLIT APP UI (Función principal) ---
def display_other_feature_ui():
    st.markdown("""<style> /* ... tus estilos CSS ... */ </style>""", unsafe_allow_html=True) # Estilos CSS

    st.sidebar.image("https://raw.githubusercontent.com/streamlit/docs/main/public/images/brand/streamlit-logo-secondary-colormark-darktext.svg", width=200)
    st.sidebar.title("⚙️ Configuración del Partido (OF)")
    main_match_id_str_input_of = st.sidebar.text_input(
        "🆔 ID Partido Principal:", value="2696131", 
        help="Pega el ID numérico del partido que deseas analizar.", key="other_feature_match_id_input")
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
                results_container.error("⚠️ El ID de partido ingresado no es válido."); st.stop()
        if not main_match_id_to_process_of: 
            results_container.warning("⚠️ Por favor, ingresa un ID de partido válido."); st.stop()
        
        start_time_of = time.time()
        with results_container, st.spinner("🔄 Cargando datos iniciales y análisis..."):
            main_page_url_h2h_view_of = f"/match/h2h-{main_match_id_to_process_of}"
            soup_main_h2h_page_of = fetch_soup_requests_of(main_page_url_h2h_view_of)
            if not soup_main_h2h_page_of:
                st.error(f"❌ No se pudo obtener la página H2H para ID {main_match_id_to_process_of}."); st.stop()

            mp_home_id_of, mp_away_id_of, mp_league_id_of, mp_home_name_from_script, mp_away_name_from_script, mp_league_name_of = get_team_league_info_from_script_of(soup_main_h2h_page_of)
            home_team_main_standings = extract_standings_data_from_h2h_page_of(soup_main_h2h_page_of, mp_home_name_from_script)
            away_team_main_standings = extract_standings_data_from_h2h_page_of(soup_main_h2h_page_of, mp_away_name_from_script)
            display_home_name = home_team_main_standings.get("name", mp_home_name_from_script) or "Equipo Local"
            display_away_name = away_team_main_standings.get("name", mp_away_name_from_script) or "Equipo Visitante"

            st.markdown(f"<p class='main-title'>📊 Análisis Avanzado de Partido (OF) ⚽</p>", unsafe_allow_html=True)
            st.markdown(f"<p class='sub-title'>🆚 <span class='home-color'>{display_home_name}</span> vs <span class='away-color'>{display_away_name}</span></p>", unsafe_allow_html=True)
            st.caption(f"🏆 **Liga:** {mp_league_name_of or PLACEHOLDER_NODATA} (ID Liga: {mp_league_id_of or PLACEHOLDER_NODATA}) | 🆔 **Partido ID:** <span class='data-highlight'>{main_match_id_to_process_of}</span>", unsafe_allow_html=True)
            st.markdown("---")

            st.markdown("<h2 class='section-header'>📈 Clasificación General y Específica</h2>", unsafe_allow_html=True)
            # ... (código para mostrar clasificaciones de equipos principales, sin cambios significativos aquí) ...
            col_home_stand, col_away_stand = st.columns(2)
            with col_home_stand: # Clasificación Local
                st.markdown(f"<h3 class='card-title'>🏠 {display_home_name}</h3>", unsafe_allow_html=True)
                # ... mostrar datos de hst ...
            with col_away_stand: # Clasificación Visitante
                st.markdown(f"<h3 class='card-title'>✈️ {display_away_name}</h3>", unsafe_allow_html=True)
                # ... mostrar datos de ast ...


            key_match_id_for_rival_a_h2h, rival_a_id_orig_col3, rival_a_name_orig_col3 = get_rival_a_for_original_h2h_of(main_match_id_to_process_of)
            match_id_rival_b_game_ref, rival_b_id_orig_col3, rival_b_name_orig_col3 = get_rival_b_for_original_h2h_of(main_match_id_to_process_of)
            # ... (obtener y mostrar clasificaciones de rivales A y B si existen) ...

            # --- Selenium Driver y datos dinámicos ---
            main_match_odds_data_of = {}
            last_home_match_in_league_of = None
            last_away_match_in_league_of = None
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

            if driver_actual_of:
                try:
                    driver_actual_of.get(f"{BASE_URL_OF}{main_page_url_h2h_view_of}") 
                    WebDriverWait(driver_actual_of, SELENIUM_TIMEOUT_SECONDS_OF).until(EC.presence_of_element_located((By.ID, "table_v1"))) 
                    time.sleep(0.8)
                    main_match_odds_data_of = get_main_match_odds_selenium_of(driver_actual_of)
                    if mp_home_id_of and mp_league_id_of and display_home_name != "N/A":
                         last_home_match_in_league_of = extract_last_match_in_league_of(driver_actual_of, "table_v1", display_home_name, mp_league_id_of, "input#cb_sos1[value='1']", True)
                    if mp_away_id_of and mp_league_id_of and display_away_name != "N/A":
                        last_away_match_in_league_of = extract_last_match_in_league_of(driver_actual_of, "table_v2", display_away_name, mp_league_id_of, "input#cb_sos2[value='2']", False)
                except Exception as e_main_sel_of: st.error(f"❗ Error Selenium: {type(e_main_sel_of).__name__}.")
            else: st.warning("❗ WebDriver no disponible. Cuotas y últimos partidos filtrados podrían faltar.")
            
            # --- Población de col_data (simplificado aquí, adaptar según necesidad) ---
            col_data = { "Fin": "?*?", "AH_Act": "?", "G_i": "?"} 
            col_data["Fin"], _ = extract_final_score_of(soup_main_h2h_page_of)
            col_data["AH_Act"] = format_ah_as_decimal_string_of(main_match_odds_data_of.get('ah_linea_raw', '?'))
            col_data["G_i"] = format_ah_as_decimal_string_of(main_match_odds_data_of.get('goals_linea_raw', '?'))

            # Partidos H2H directos
            ah1_val, res1_val, _, match1_id_h2h_v, ah6_val, res6_val, _, match6_id_h2h_g = extract_h2h_data_of(soup_main_h2h_page_of, display_home_name, display_away_name, mp_league_id_of)
            col_data["AH_H2H_V"], col_data["Res_H2H_V"] = ah1_val, res1_val
            col_data["AH_H2H_G"], col_data["Res_H2H_G"] = ah6_val, res6_val

            comp_data_L_vs_UV_A = None
            if last_away_match_in_league_of and display_home_name != "N/A":
                comp_data_L_vs_UV_A = extract_comparative_match_of(soup_main_h2h_page_of, "table_v1", display_home_name, last_away_match_in_league_of.get('home_team'), mp_league_id_of, True)

            comp_data_V_vs_UL_H = None
            if last_home_match_in_league_of and display_away_name != "N/A":
                comp_data_V_vs_UL_H = extract_comparative_match_of(soup_main_h2h_page_of, "table_v2", display_away_name, last_home_match_in_league_of.get('away_team'), mp_league_id_of, False)

            # --- RENDERIZACIÓN DE LA UI ---
            st.markdown("---")
            st.markdown("<h2 class='section-header'>🎯 Análisis Detallado del Partido</h2>", unsafe_allow_html=True)
            
            with st.expander("⚖️ Cuotas Iniciales Bet365 y Marcador Final (Partido Principal)", expanded=False):
                 # ... (mostrar cuotas y marcador final del partido principal) ...
                 pass

            st.markdown("<h3 class='section-header' style='font-size:1.5em; margin-top:30px;'>⚡ Rendimiento Reciente y Contexto H2H (Indirecto)</h3>", unsafe_allow_html=True)
            rp_col1, rp_col2, rp_col3 = st.columns(3)
            with rp_col1: # Último Local (Casa)
                st.markdown(f"<h4 class='card-title'>Último <span class='home-color'>{display_home_name}</span> (Casa)</h4>", unsafe_allow_html=True)
                if last_home_match_in_league_of: 
                    res = last_home_match_in_league_of
                    st.markdown(f"🆚 <span class='away-color'>{res['away_team']}</span>", unsafe_allow_html=True)
                    st.markdown(f"<div style='margin-top: 8px; margin-bottom: 8px;'><span class='home-color'>{res['home_team']}</span> <span class='score-value'>{res['score'].replace('-',':')}</span> <span class='away-color'>{res['away_team']}</span></div>", unsafe_allow_html=True)
                    formatted_ah_lh = format_ah_as_decimal_string_of(res.get('handicap_line_raw','-'))
                    st.markdown(f"**AH:** <span class='ah-value'>{formatted_ah_lh if formatted_ah_lh != '-' else PLACEHOLDER_NODATA}</span>", unsafe_allow_html=True)
                    st.caption(f"📅 {res.get('date', 'N/A')}")
                    display_previous_match_progression_stats(
                        f"{res.get('home_team','L')} vs {res.get('away_team','V')}", 
                        res.get('match_id'), res.get('home_team','Local'), res.get('away_team','Visitante')
                    )
                else: st.info(f"No se encontró último partido en casa para {display_home_name}.")
            
            with rp_col2: # Último Visitante (Fuera)
                st.markdown(f"<h4 class='card-title'>Último <span class='away-color'>{display_away_name}</span> (Fuera)</h4>", unsafe_allow_html=True)
                if last_away_match_in_league_of: 
                    res = last_away_match_in_league_of
                    st.markdown(f"🆚 <span class='home-color'>{res['home_team']}</span>", unsafe_allow_html=True)
                    st.markdown(f"<div style='margin-top: 8px; margin-bottom: 8px;'><span class='home-color'>{res['home_team']}</span> <span class='score-value'>{res['score'].replace('-',':')}</span> <span class='away-color'>{res['away_team']}</span></div>", unsafe_allow_html=True)
                    formatted_ah_la = format_ah_as_decimal_string_of(res.get('handicap_line_raw','-'))
                    st.markdown(f"**AH:** <span class='ah-value'>{formatted_ah_la if formatted_ah_la != '-' else PLACEHOLDER_NODATA}</span>", unsafe_allow_html=True)
                    st.caption(f"📅 {res.get('date', 'N/A')}")
                    display_previous_match_progression_stats(
                        f"{res.get('home_team','L')} vs {res.get('away_team','V')}", 
                        res.get('match_id'), res.get('home_team','Local'), res.get('away_team','Visitante')
                    )
                else: st.info(f"No se encontró último partido fuera para {display_away_name}.")

            with rp_col3: # H2H Rivales (Col3)
                st.markdown(f"<h4 class='card-title'>🆚 H2H Rivales (Col3)</h4>", unsafe_allow_html=True)
                details_h2h_col3_of = {"status": "error", "resultado": PLACEHOLDER_NODATA}
                if key_match_id_for_rival_a_h2h and rival_a_id_orig_col3 and rival_b_id_orig_col3 and driver_actual_of:
                    details_h2h_col3_of = get_h2h_details_for_original_logic_of(driver_actual_of, key_match_id_for_rival_a_h2h, rival_a_id_orig_col3, rival_b_id_orig_col3, rival_a_name_orig_col3, rival_b_name_orig_col3)
                
                if details_h2h_col3_of.get("status") == "found":
                    res_h2h = details_h2h_col3_of
                    h2h_home_name = res_h2h.get('h2h_home_team_name', 'Local H2H')
                    h2h_away_name = res_h2h.get('h2h_away_team_name', 'Visitante H2H')
                    st.markdown(f"<span class='home-color'>{h2h_home_name}</span> <span class='score-value'>{res_h2h.get('goles_home', '?')}:{res_h2h.get('goles_away', '?')}</span> <span class='away-color'>{h2h_away_name}</span>", unsafe_allow_html=True)
                    formatted_ah_h2h_col3 = format_ah_as_decimal_string_of(res_h2h.get('handicap','-'))
                    st.markdown(f"**AH:** <span class='ah-value'>{formatted_ah_h2h_col3 if formatted_ah_h2h_col3 != '-' else PLACEHOLDER_NODATA}</span>", unsafe_allow_html=True)
                    display_previous_match_progression_stats(
                        f"H2H Col3: {h2h_home_name} vs {h2h_away_name}", 
                        res_h2h.get('match_id'), h2h_home_name, h2h_away_name
                    )
                else: st.info(details_h2h_col3_of.get('resultado', f"H2H Col3 entre {rival_a_name_orig_col3 or 'RivalA'} y {rival_b_name_orig_col3 or 'RivalB'} no encontrado."))

            with st.expander("🔁 Comparativas Indirectas Detalladas", expanded=True):
                comp_col1, comp_col2 = st.columns(2)
                with comp_col1: # L vs UV_A
                    st.markdown(f"<h5 class='card-subtitle'><span class='home-color'>{display_home_name}</span> vs. <span class='away-color'>Últ. Rival del {display_away_name}</span></h5>", unsafe_allow_html=True)
                    if comp_data_L_vs_UV_A:
                        data = comp_data_L_vs_UV_A
                        score_part = data['score'].replace('*', ':').strip()
                        ah_val = data.get('ah_line', '-')
                        loc_val = data.get('localia', '-')
                        st.markdown(f"⚽ **Resultado:** <span class='data-highlight'>{score_part or PLACEHOLDER_NODATA}</span>", unsafe_allow_html=True)
                        st.markdown(f"⚖️ **AH (Partido Comp.):** <span class='ah-value'>{format_ah_as_decimal_string_of(ah_val) or PLACEHOLDER_NODATA}</span>", unsafe_allow_html=True)
                        st.markdown(f"🏟️ **Localía de '{display_home_name}':** <span class='data-highlight'>{loc_val or PLACEHOLDER_NODATA}</span>", unsafe_allow_html=True)
                        display_previous_match_progression_stats(
                            f"Comp: {data.get('home_team','L')} vs {data.get('away_team','V')}",
                            data.get('match_id'), data.get('home_team','Local'), data.get('away_team','Visitante')
                        )
                    else: st.info("Comparativa L vs UV A no disponible.")

                with comp_col2: # V vs UL_H
                    st.markdown(f"<h5 class='card-subtitle'><span class='away-color'>{display_away_name}</span> vs. <span class='home-color'>Últ. Rival del {display_home_name}</span></h5>", unsafe_allow_html=True)
                    if comp_data_V_vs_UL_H:
                        data = comp_data_V_vs_UL_H
                        score_part = data['score'].replace('*', ':').strip()
                        ah_val = data.get('ah_line', '-')
                        loc_val = data.get('localia', '-')
                        st.markdown(f"⚽ **Resultado:** <span class='data-highlight'>{score_part or PLACEHOLDER_NODATA}</span>", unsafe_allow_html=True)
                        st.markdown(f"⚖️ **AH (Partido Comp.):** <span class='ah-value'>{format_ah_as_decimal_string_of(ah_val) or PLACEHOLDER_NODATA}</span>", unsafe_allow_html=True)
                        st.markdown(f"🏟️ **Localía de '{display_away_name}':** <span class='data-highlight'>{loc_val or PLACEHOLDER_NODATA}</span>", unsafe_allow_html=True)
                        display_previous_match_progression_stats(
                            f"Comp: {data.get('home_team','L')} vs {data.get('away_team','V')}",
                            data.get('match_id'), data.get('home_team','Local'), data.get('away_team','Visitante')
                        )
                    else: st.info("Comparativa V vs UL H no disponible.")
            
            with st.expander("🔰 Hándicaps y Resultados Clave (H2H Directos)", expanded=True):
                st.metric("AH H2H (Local en Casa)", col_data["AH_H2H_V"])
                st.metric("Res H2H (Local en Casa)", col_data["Res_H2H_V"].replace("*",":"))
                if match1_id_h2h_v:
                    display_previous_match_progression_stats(
                        f"H2H: {display_home_name} (Casa) vs {display_away_name}",
                        match1_id_h2h_v, display_home_name, display_away_name
                    )
                st.metric("AH H2H (General)", col_data["AH_H2H_G"])
                st.metric("Res H2H (General)", col_data["Res_H2H_G"].replace("*",":"))
                if match6_id_h2h_g:
                    # Para el H2H general, necesitamos saber quién fue local y visitante en ESE partido
                    # Esto es un poco más complejo si no tenemos los nombres exactos de ESE partido guardados.
                    # Por simplicidad, usaremos los nombres del partido principal, pero idealmente se extraerían del contexto del partido H2H general.
                    display_previous_match_progression_stats(
                        f"H2H General: ({match6_id_h2h_g})", # Título genérico si no tenemos nombres exactos
                        match6_id_h2h_g, "Equipo Local (H2H Gen)", "Equipo Visitante (H2H Gen)" # Nombres placeholder
                    )
            # ... (resto de la UI: Estadísticas detalladas de equipos, Info General del Partido) ...

            end_time_of = time.time()
            st.sidebar.success(f"🎉 Análisis completado en {end_time_of - start_time_of:.2f} segundos.")
    else:
        results_container.info("✨ ¡Bienvenido! Ingresa un ID de partido y haz clic en 'Analizar Partido (OF)'.")

if __name__ == '__main__':
    st.set_page_config(layout="wide", page_title="Análisis Avanzado de Partidos (OF)", initial_sidebar_state="expanded")
    if 'driver_other_feature' not in st.session_state:
        st.session_state.driver_other_feature = None
    display_other_feature_ui()
