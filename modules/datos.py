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
SELENIUM_TIMEOUT_SECONDS_OF = 15 # Reducido
SELENIUM_POLL_FREQUENCY_OF = 0.2
PLACEHOLDER_NODATA = "N/D" # Más corto
# Emojis
ICO_CALENDAR = "📅"
ICO_SCORE = "⚽"
ICO_HANDICAP = "⚖️"
ICO_HOME = "🏠"
ICO_AWAY = "✈️"
ICO_LEAGUE = "🏆"
ICO_ID = "🆔"
ICO_STATS = "📊"
ICO_CLOCK = "⏱️"
ICO_ERROR = "❌"
ICO_WARNING = "⚠️"
ICO_INFO = "ℹ️"
ICO_EYE = "👁️"
ICO_ROCKET = "🚀"
ICO_GEAR = "⚙️"
ICO_VS = "🆚"
ICO_CHART = "📈"
ICO_LIGHTNING = "⚡"
ICO_LINK = "🔗"
ICO_FLAG = "🏁"

# --- FUNCIONES HELPER (sin cambios en su lógica interna) ---
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

# --- SESIÓN Y FETCHING (sin cambios) ---
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

# --- ESTADÍSTICAS DE PROGRESIÓN (Lógica sin cambios, presentación ajustada en UI) ---
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

def display_compact_match_progression_stats(match_id: str, home_team_name: str, away_team_name: str):
    stats_df = get_match_progression_stats_data(match_id)
    if stats_df is None or stats_df.empty:
        st.caption(f"{ICO_INFO} Sin datos de progresión.")
        return

    ordered_stats_display = {
        "Shots on Goal": "TP", # Tiros Puerta
        "Dangerous Attacks": "AP"  # Ataques Peligrosos
    }
    
    html_stats = "<div class='compact-progression-stats'>"
    # Truncar nombres de equipo para ahorrar espacio
    home_name_short = (home_team_name or "Loc")[:7]
    away_name_short = (away_team_name or "Vis")[:7]
    html_stats += f"<div class='compact-prog-row header'><span class='team-h'>{home_name_short}</span><span>Stat</span><span class='team-a'>{away_name_short}</span></div>"
    
    for stat_key_en, stat_name_es_short in ordered_stats_display.items():
        if stat_key_en in stats_df.index:
            home_val = stats_df.loc[stat_key_en, 'Casa']
            away_val = stats_df.loc[stat_key_en, 'Fuera']
            html_stats += f"<div class='compact-prog-row'><span class='val-h'>{home_val}</span><span class='stat-label'>{stat_name_es_short}</span><span class='val-a'>{away_val}</span></div>"
        else:
            html_stats += f"<div class='compact-prog-row'><span class='val-h'>-</span><span class='stat-label'>{stat_name_es_short}</span><span class='val-a'>-</span></div>"
    html_stats += "</div>"
    st.markdown(html_stats, unsafe_allow_html=True)


# --- FUNCIONES DE EXTRACCIÓN (Lógica sin cambios, se adaptan a PLACEHOLDER_NODATA y tiempos reducidos) ---
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
    options.add_argument("--disable-dev-shm-usage"); options.add_argument("--disable-gpu"); options.add_argument("--window-size=1200,800") # Más pequeño
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36")
    options.add_argument('--blink-settings=imagesEnabled=false')
    try: return webdriver.Chrome(options=options)
    except WebDriverException as e: st.error(f"{ICO_ERROR} Sel: {e}"); return None

def get_h2h_details_for_original_logic_of(driver_instance, key_match_id_for_h2h_url, rival_a_id, rival_b_id, rival_a_name="Rival A", rival_b_name="Rival B"):
    if not driver_instance: return {"status": "error", "resultado": f"{PLACEHOLDER_NODATA} (NoDrv H2H)"}
    if not key_match_id_for_h2h_url or not rival_a_id or not rival_b_id: return {"status": "error", "resultado": f"{PLACEHOLDER_NODATA} (IDs H2H)"}
    url_to_visit = f"{BASE_URL_OF}/match/h2h-{key_match_id_for_h2h_url}"
    try:
        driver_instance.get(url_to_visit)
        WebDriverWait(driver_instance, SELENIUM_TIMEOUT_SECONDS_OF, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.presence_of_element_located((By.ID, "table_v2")))
        time.sleep(0.4); # Reducido
        soup_selenium = BeautifulSoup(driver_instance.page_source, "html.parser")
    except TimeoutException: return {"status": "error", "resultado": f"{PLACEHOLDER_NODATA} (TOut H2H URL)"}
    except Exception as e: return {"status": "error", "resultado": f"{PLACEHOLDER_NODATA} (ErrSelH2H: {type(e).__name__})"}

    if not soup_selenium: return {"status": "error", "resultado": f"{PLACEHOLDER_NODATA} (NoSoupSelH2H)"}
    table_to_search_h2h = soup_selenium.find("table", id="table_v2")
    if not table_to_search_h2h: return {"status": "error", "resultado": f"{PLACEHOLDER_NODATA} (NoTbl_v2 H2H)"}

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
    return {"status": "not_found", "resultado": f"{rival_a_name[:6]}-{rival_b_name[:6]} H2H NF"}


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
        if h_name_m: home_name = h_name_m.group(1).replace("\\'", "'")
        if g_name_m: away_name = g_name_m.group(1).replace("\\'", "'")
        if l_name_m: league_name = l_name_m.group(1).replace("\\'", "'")
    return home_id, away_id, league_id, home_name, away_name, league_name

def click_element_robust_of(driver, by, value, timeout=4): # Reducido
    try:
        element = WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.presence_of_element_located((by, value)))
        WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.visibility_of(element))
        driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'center'});", element); time.sleep(0.15) # Reducido
        try: WebDriverWait(driver, 0.8, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.element_to_be_clickable((by, value))).click() # Reducido
        except (ElementClickInterceptedException, TimeoutException): driver.execute_script("arguments[0].click();", element)
        return True
    except Exception: return False

def extract_last_match_in_league_of(driver, table_css_id_str, main_team_name_in_table, league_id_filter_value, home_or_away_filter_css_selector, is_home_game_filter):
    try:
        if league_id_filter_value:
            league_checkbox_selector = f"input#checkboxleague{table_css_id_str[-1]}[value='{league_id_filter_value}']"
            click_element_robust_of(driver, By.CSS_SELECTOR, league_checkbox_selector); time.sleep(0.3) # Reducido
        click_element_robust_of(driver, By.CSS_SELECTOR, home_or_away_filter_css_selector); time.sleep(0.3) # Reducido
        page_source_updated = driver.page_source; soup_updated = BeautifulSoup(page_source_updated, "html.parser")
        table = soup_updated.find("table", id=table_css_id_str)
        if not table: return None

        count_visible_rows = 0
        for row in table.find_all("tr", id=re.compile(rf"tr{table_css_id_str[-1]}_\d+")):
            if row.get("style") and "display:none" in row.get("style","").lower(): continue
            count_visible_rows +=1
            if count_visible_rows > 3: break # Muy reducido
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
                date_span = tds[1].find("span", {"name": "timeData"}); date_text = date_span.text.strip() if date_span else PLACEHOLDER_NODATA
                score_class_re = re.compile(r"fscore_"); score_span = tds[3].find("span", class_=score_class_re); score_text = score_span.text.strip() if score_span else PLACEHOLDER_NODATA
                handicap_cell = tds[11]; handicap_raw_text = handicap_cell.get("data-o", handicap_cell.text.strip())
                if not handicap_raw_text or handicap_raw_text.strip() == "-": handicap_raw_text = PLACEHOLDER_NODATA
                else: handicap_raw_text = handicap_raw_text.strip()
                match_id_last = row.get('index')
                return {"date": date_text, "home_team": home_team_row_name,
                        "away_team": away_team_row_name,"score": score_text,
                        "handicap_line_raw": handicap_raw_text,
                        "match_id": match_id_last}
        return None
    except Exception: return None

def get_main_match_odds_selenium_of(driver):
    odds_info = {"ah_home_cuota": PLACEHOLDER_NODATA, "ah_linea_raw": PLACEHOLDER_NODATA, "ah_away_cuota": PLACEHOLDER_NODATA, "goals_over_cuota": PLACEHOLDER_NODATA, "goals_linea_raw": PLACEHOLDER_NODATA, "goals_under_cuota": PLACEHOLDER_NODATA}
    try:
        live_compare_div = WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS_OF - 8, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.presence_of_element_located((By.ID, "liveCompareDiv"))) # Reducido drásticamente
        bet365_row_selector = "tr#tr_o_1_8[name='earlyOdds']"; bet365_row_selector_alt = "tr#tr_o_1_31[name='earlyOdds']"
        # No scroll, asumimos que es visible si la tabla lo es
        bet365_early_odds_row = None
        try: bet365_early_odds_row = WebDriverWait(driver, 2, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.visibility_of_element_located((By.CSS_SELECTOR, bet365_row_selector))) # Reducido
        except TimeoutException:
            try: bet365_early_odds_row = WebDriverWait(driver, 1, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.visibility_of_element_located((By.CSS_SELECTOR, bet365_row_selector_alt))) # Reducido
            except TimeoutException: return odds_info
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
        "name": target_team_name_exact, "ranking": PLACEHOLDER_NODATA,
        "total_pj": PLACEHOLDER_NODATA, "total_v": PLACEHOLDER_NODATA, "total_e": PLACEHOLDER_NODATA, "total_d": PLACEHOLDER_NODATA, "total_gf": PLACEHOLDER_NODATA, "total_gc": PLACEHOLDER_NODATA,
        "specific_pj": PLACEHOLDER_NODATA, "specific_v": PLACEHOLDER_NODATA, "specific_e": PLACEHOLDER_NODATA, "specific_d": PLACEHOLDER_NODATA, "specific_gf": PLACEHOLDER_NODATA, "specific_gc": PLACEHOLDER_NODATA,
        "specific_type": "N/A"}
    if not h2h_soup or not target_team_name_exact: return data
    standings_section = h2h_soup.find("div", id="porletP4")
    if not standings_section: return data
    team_table_soup = None; is_home_table_type = False
    home_div = standings_section.find("div", class_="home-div")
    if home_div:
        header_tr = home_div.find("tr", class_="team-home")
        if header_tr and header_tr.find("a") and target_team_name_exact.lower() in header_tr.find("a").get_text(strip=True).lower():
            team_table_soup = home_div.find("table", class_="team-table-home"); is_home_table_type = True
            data["specific_type"] = "L" # Local
    if not team_table_soup:
        guest_div = standings_section.find("div", class_="guest-div")
        if guest_div:
            header_tr = guest_div.find("tr", class_="team-guest")
            if header_tr and header_tr.find("a") and target_team_name_exact.lower() in header_tr.find("a").get_text(strip=True).lower():
                team_table_soup = guest_div.find("table", class_="team-table-guest"); is_home_table_type = False
                data["specific_type"] = "V" # Visitante
    if not team_table_soup: return data
    header_link = team_table_soup.find("tr", class_=re.compile(r"team-(home|guest)")).find("a")
    if header_link:
        full_text = header_link.get_text(separator=" ", strip=True)
        name_match = re.search(r"]\s*(.*)", full_text); rank_match = re.search(r"\[(?:[^\]]+-)?(\d+)\]", full_text)
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
    ah1, res1, res1_raw, match1_id = '-', '?:?', '?-?', None
    ah6, res6, res6_raw, match6_id = '-', '?:?', '?-?', None
    h2h_gen_home_name, h2h_gen_away_name = "L(H2HGen)", "V(H2HGen)" # Más corto

    h2h_table = soup.find("table", id="table_v3")
    if not h2h_table: return ah1, res1, res1_raw, match1_id, ah6, res6, res6_raw, match6_id, h2h_gen_home_name, h2h_gen_away_name
    filtered_h2h_list = []
    if not main_home_team_name or not main_away_team_name:
        return ah1, res1, res1_raw, match1_id, ah6, res6, res6_raw, match6_id, h2h_gen_home_name, h2h_gen_away_name

    for row_h2h in h2h_table.find_all("tr", id=re.compile(r"tr3_\d+")):
        details = get_match_details_from_row_of(row_h2h, score_class_selector='fscore_3', source_table_type='h2h')
        if not details: continue
        if current_league_id and details.get('league_id_hist') and details.get('league_id_hist') != str(current_league_id): continue
        filtered_h2h_list.append(details)

    if not filtered_h2h_list: return ah1, res1, res1_raw, match1_id, ah6, res6, res6_raw, match6_id, h2h_gen_home_name, h2h_gen_away_name

    h2h_general_match = filtered_h2h_list[0]
    ah6 = h2h_general_match.get('ahLine', '-'); res6 = h2h_general_match.get('score', '?:?'); res6_raw = h2h_general_match.get('score_raw', '?-?')
    match6_id = h2h_general_match.get('matchIndex'); h2h_gen_home_name = h2h_general_match.get('home', "L(H2HGen)"); h2h_gen_away_name = h2h_general_match.get('away', "V(H2HGen)")

    h2h_local_specific_match = None
    for d_h2h in filtered_h2h_list:
        if d_h2h.get('home','').lower() == main_home_team_name.lower() and \
           d_h2h.get('away','').lower() == main_away_team_name.lower():
            h2h_local_specific_match = d_h2h; break
    if h2h_local_specific_match:
        ah1 = h2h_local_specific_match.get('ahLine', '-'); res1 = h2h_local_specific_match.get('score', '?:?'); res1_raw = h2h_local_specific_match.get('score_raw', '?-?')
        match1_id = h2h_local_specific_match.get('matchIndex')
    return ah1, res1, res1_raw, match1_id, ah6, res6, res6_raw, match6_id, h2h_gen_home_name, h2h_gen_away_name

def extract_comparative_match_of(soup_for_team_history, table_id_of_team_to_search, team_name_to_find_match_for, opponent_name_to_search, current_league_id, is_home_table):
    if not opponent_name_to_search or opponent_name_to_search == PLACEHOLDER_NODATA or not team_name_to_find_match_for: return None
    table = soup_for_team_history.find("table", id=table_id_of_team_to_search)
    if not table: return None
    score_class_selector = 'fscore_1' if is_home_table else 'fscore_2'
    for row in table.find_all("tr", id=re.compile(rf"tr{table_id_of_team_to_search[-1]}_\d+")): # Solo el primero que encuentre
        details = get_match_details_from_row_of(row, score_class_selector=score_class_selector, source_table_type='hist')
        if not details: continue
        if current_league_id and details.get('league_id_hist') and details.get('league_id_hist') != str(current_league_id): continue
        home_hist = details.get('home','').lower(); away_hist = details.get('away','').lower()
        team_main_lower = team_name_to_find_match_for.lower(); opponent_lower = opponent_name_to_search.lower()
        if (team_main_lower == home_hist and opponent_lower == away_hist) or \
           (team_main_lower == away_hist and opponent_lower == home_hist):
            score_val = details.get('score', '?:?'); ah_line_extracted = details.get('ahLine', '-')
            localia_val = 'H' if team_main_lower == home_hist else 'A'
            return {"score": score_val, "ah_line": ah_line_extracted, "localia": localia_val,
                    "home_team": details.get('home'), "away_team": details.get('away'),
                    "match_id": details.get('matchIndex')}
    return None

# --- STREAMLIT APP UI (Función principal ultra-compacta) ---
def display_other_feature_ui():
    st.markdown(f"""
    <style>
        /* Reset básico y Fuentes */
        body {{ margin: 0; padding: 0; font-family: 'Roboto Condensed', 'Arial Narrow', sans-serif; background-color: #F4F6F8; font-size: 12px; }}
        .main {{ padding: 0.3rem !important; }}
        button, input, select, textarea {{ font-family: 'Roboto Condensed', 'Arial Narrow', sans-serif !important; font-size: 12px !important; }}
        h1,h2,h3,h4,h5,h6 {{ margin:0; padding:0; line-height:1.2;}}

        /* Encabezado Principal */
        .main-header {{ text-align: center; margin-bottom: 5px; padding: 4px; background-color: #E8F0F3; border-radius: 4px;}}
        .main-header .title {{ font-size: 1.3em; font-weight: 700; color: #2C3E50; margin: 0; }}
        .main-header .info {{ font-size: 0.8em; color: #566573; margin: 0; }}
        
        /* Contenedores de Sección (data-blocks) */
        .data-block {{ background-color: #FFFFFF; border: 1px solid #D6DBDF; border-radius: 4px; padding: 6px; margin-bottom: 5px; box-shadow: 0 1px 2px rgba(0,0,0,0.05); }}
        .data-block .block-title {{ font-size: 0.9em; font-weight: 600; color: #34495E; margin: 0 0 4px 0; padding-bottom: 2px; border-bottom: 1px solid #EAECEE; display: flex; align-items: center;}}
        .data-block .block-title .icon {{margin-right: 4px;}}
        .data-block p {{ margin: 2px 0; font-size: 0.85em; line-height:1.3; }}

        /* Equipos y Marcadores */
        .team-home {{ color: #2980B9; font-weight: 500; }}
        .team-away {{ color: #E67E22; font-weight: 500; }}
        .score-box {{ font-size: 1em; font-weight: 600; color: #27AE60; padding: 0 3px; }}
        .ah-chip {{ font-weight: 500; color: #884EA0; background-color: #F5EEF8; padding: 1px 4px; border-radius: 6px; font-size: 0.75em; display:inline-block; margin-left:3px;}}
        .data-value {{ font-weight: 500; }}
        .placeholder {{ color: #95A5A6; font-style: italic; font-size:0.8em;}}
        .small-caption {{ font-size: 0.7em; color: #7F8C8D; display: block; margin-top:0px; }}

        /* Métricas Streamlit */
        .stMetric {{ padding: 3px 5px !important; border-radius: 3px !important; background-color: #FBFCFC !important; border: 1px solid #EAEDED !important; margin-bottom: 3px !important;}}
        .stMetric label {{font-size: 0.7em !important; font-weight: 500 !important; color: #707B7C !important; margin-bottom: 0px !important; line-height: 1 !important; text-transform: uppercase;}}
        .stMetric .st-ae {{font-size: 1em !important; font-weight: 600 !important; color: #1E8449 !important; line-height: 1.1 !important; padding:0 !important;}}
        .stMetric .st-af {{font-size: 0.65em !important; color: #99A3A4 !important; line-height: 1 !important; padding:0 !important;}}

        /* Clasificación Compacta */
        .standings-col p {{ margin:0; }}
        .standings-team-name {{ font-size: 0.85em; display:block; margin-bottom:1px;}}
        .standings-rank {{ font-size: 0.8em; font-weight: 600; background-color: #EBF5FB; color: #2C3E50; padding: 1px 3px; border-radius: 3px; margin-left:3px;}}
        .standings-data-line {{ font-size: 0.75em; color: #616A6B; white-space:nowrap;}}
        .standings-data-line strong {{color: #4D5656;}}
        .standings-data-line .separator {{ margin: 0 2px; color: #BDC3C7;}}

        /* Partidos Recientes / H2H Compactos */
        .recent-match-card {{ padding: 4px; }} /* Mini card para cada partido reciente */
        .recent-match-card .match-title {{ font-size:0.8em; font-weight:500; margin-bottom:2px; display:flex; align-items:center; }}
        .recent-match-card .match-title .icon {{margin-right:3px;}}
        .recent-match-card p {{ margin: 1px 0 !important; font-size: 0.8em !important; line-height: 1.2; display: flex; justify-content: space-between; align-items: center;}}
        .recent-match-card .teams-score span {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 60px; display:inline-block;}} /* Truncar nombres largos */

        /* Stats Progresión Compactas */
        .compact-progression-stats {{ font-size: 0.75em; margin-top:3px; }}
        .compact-prog-row {{ display: grid; grid-template-columns: 1fr auto 1fr; gap: 3px; padding: 1px 0; border-bottom: 1px dotted #F2F3F4; }}
        .compact-prog-row.header {{ font-weight: 500; color: #34495E;}}
        .compact-prog-row .team-h, .compact-prog-row .val-h {{ text-align: left; }}
        .compact-prog-row .team-a, .compact-prog-row .val-a {{ text-align: right; }}
        .compact-prog-row .stat-label {{ text-align: center; color: #626567; }}
        
        /* Expander Compacto */
        .stExpander {{ margin-bottom: 5px !important; border: 1px solid #D6DBDF !important; border-radius: 3px !important;}}
        .stExpander header {{ background-color: #F2F4F4 !important; padding: 3px 6px !important; min-height: auto !important;}}
        .stExpander header button {{ font-size: 0.85em !important; font-weight: 500 !important; color: #34495E !important; padding: 0 !important;}}
        .stExpander div[data-testid="stExpanderDetails"] {{ padding: 4px 6px !important; background-color: #FBFCFC; }}
        .stExpander div[data-testid="stExpanderDetails"] h6 {{font-size:0.8em; margin-bottom:2px; color:#5D6D7E; font-weight:500;}}
        .stExpander div[data-testid="stExpanderDetails"] p {{font-size:0.75em; margin:1px 0;}}


        /* Barra lateral Compacta */
        div[data-testid="stSidebarUserContent"] {{ padding: 8px !important; background-color: #EAECEE;}}
        div[data-testid="stSidebarUserContent"] h3 {{font-size:1.1em; margin-bottom:5px;}}
        div[data-testid="stSidebarUserContent"] .stButton button {{ background-color: #2471A3; font-size:0.85em !important; padding: 3px 6px !important; border-radius:3px;}}
        div[data-testid="stSidebarUserContent"] .stTextInput label {{font-size: 0.85em !important; margin-bottom:1px !important;}}
        div[data-testid="stSidebarUserContent"] .stTextInput input {{padding: 3px 5px !important; font-size:0.85em !important;}}

    </style>
    """, unsafe_allow_html=True)

    # --- Sidebar ---
    st.sidebar.image("https://raw.githubusercontent.com/streamlit/docs/main/public/images/brand/streamlit-logo-secondary-colormark-darktext.svg", width=120)
    st.sidebar.markdown(f"### {ICO_GEAR} Config (OF)")
    main_match_id_str_input_of = st.sidebar.text_input(f"{ICO_ID} ID Partido:", value="2696131", key="other_feature_match_id_input_super_compact")
    analizar_button_of = st.sidebar.button(f"{ICO_ROCKET} Analizar", type="primary", use_container_width=True, key="other_feature_analizar_button_super_compact")

    results_container = st.container()
    if 'driver_other_feature' not in st.session_state: st.session_state.driver_other_feature = None

    if analizar_button_of:
        results_container.empty() # Limpiar resultados previos
        main_match_id_to_process_of = None
        try:
            main_match_id_to_process_of = int("".join(filter(str.isdigit, main_match_id_str_input_of)))
        except ValueError:
            results_container.error(f"{ICO_ERROR} ID Inválido."); st.stop()
        if not main_match_id_to_process_of:
            results_container.warning(f"{ICO_WARNING} Ingresa ID."); st.stop()

        start_time_of = time.time()
        # Mover spinner aquí para cubrir más operaciones de carga inicial
        with results_container, st.spinner(f"{ICO_CLOCK} Procesando..."):
            main_page_url_h2h_view_of = f"/match/h2h-{main_match_id_to_process_of}"
            soup_main_h2h_page_of = fetch_soup_requests_of(main_page_url_h2h_view_of)
            if not soup_main_h2h_page_of:
                st.error(f"{ICO_ERROR} Fallo H2H {main_match_id_to_process_of}."); st.stop()

            mp_home_id_of, mp_away_id_of, mp_league_id_of, mp_home_name_from_script, mp_away_name_from_script, mp_league_name_of = get_team_league_info_from_script_of(soup_main_h2h_page_of)
            home_team_main_standings = extract_standings_data_from_h2h_page_of(soup_main_h2h_page_of, mp_home_name_from_script)
            away_team_main_standings = extract_standings_data_from_h2h_page_of(soup_main_h2h_page_of, mp_away_name_from_script)
            display_home_name = home_team_main_standings.get("name") if home_team_main_standings.get("name") not in [PLACEHOLDER_NODATA, "N/A"] else mp_home_name_from_script or "Local"
            display_away_name = away_team_main_standings.get("name") if away_team_main_standings.get("name") not in [PLACEHOLDER_NODATA, "N/A"] else mp_away_name_from_script or "Visitante"
            
            # --- Encabezado del Partido ---
            st.markdown(f"""
            <div class='main-header'>
                <p class='title'><span class='team-home'>{display_home_name}</span> {ICO_VS} <span class='team-away'>{display_away_name}</span></p>
                <p class='info'>{ICO_LEAGUE} {(mp_league_name_of or PLACEHOLDER_NODATA)[:25]} | {ICO_ID} {main_match_id_to_process_of}</p>
            </div>
            """, unsafe_allow_html=True)

            # --- Datos que dependen de Selenium (cargar de forma condicional o con placeholders) ---
            main_match_odds_data_of = {}
            last_home_match_in_league_of, last_away_match_in_league_of = None, None
            details_h2h_col3_of = {"status": "error", "resultado": PLACEHOLDER_NODATA}
            key_match_id_for_rival_a_h2h, rival_a_id_orig_col3, rival_a_name_orig_col3 = (None,) * 3
            match_id_rival_b_game_ref, rival_b_id_orig_col3, rival_b_name_orig_col3 = (None,) * 3
            
            # Solo inicializar Selenium si no se pueden obtener datos cruciales de otra forma o si se necesita para algo prioritario
            # Por ahora, las cuotas son lo más dependiente de Selenium que se muestra en la vista principal
            driver_actual_of = st.session_state.driver_other_feature
            driver_of_needs_init = driver_actual_of is None
            if not driver_of_needs_init:
                try: _ = driver_actual_of.window_handles
                except WebDriverException: driver_of_needs_init = True
            
            if driver_of_needs_init:
                if driver_actual_of is not None:
                    try: driver_actual_of.quit()
                    except: pass
                driver_actual_of = get_selenium_driver_of() # Podría mostrar un spinner más pequeño aquí
                st.session_state.driver_other_feature = driver_actual_of

            if driver_actual_of:
                try:
                    driver_actual_of.get(f"{BASE_URL_OF}{main_page_url_h2h_view_of}") # Ir a la página base una vez
                    WebDriverWait(driver_actual_of, SELENIUM_TIMEOUT_SECONDS_OF -5).until(EC.presence_of_element_located((By.ID, "table_v1"))) # Espera básica
                    time.sleep(0.3)
                    main_match_odds_data_of = get_main_match_odds_selenium_of(driver_actual_of)
                    # La extracción de "last_home_match..." y "h2h_col3..." se puede hacer aquí si se mantienen en la vista principal,
                    # o diferirlas para los expanders si se mueven allí completamente.
                    # Por compacidad, las dejo fuera de la carga inicial aquí y se llamarán si el expander se abre.
                except Exception as e_sel_init: st.caption(f"{ICO_ERROR} SelInit: {type(e_sel_init).__name__}", unsafe_allow_html=True)
            else: st.caption(f"{ICO_WARNING} No WebDriver", unsafe_allow_html=True)


            # --- Preparación de datos (los que no dependen de Selenium inmediato) ---
            final_score, _ = extract_final_score_of(soup_main_h2h_page_of)
            ah_act = format_ah_as_decimal_string_of(main_match_odds_data_of.get('ah_linea_raw', '?'))
            goals_line = format_ah_as_decimal_string_of(main_match_odds_data_of.get('goals_linea_raw', '?'))

            # Datos para expanders (H2H directos del partido)
            ah1_val, res1_val, _, match1_id_h2h_v, \
            ah6_val, res6_val, _, match6_id_h2h_g, \
            h2h_gen_home_name, h2h_gen_away_name = extract_h2h_data_of(soup_main_h2h_page_of, display_home_name, display_away_name, mp_league_id_of)


            # --- PRIMERA FILA DE BLOQUES: Clasificación y Cuotas/Marcador Principal ---
            main_row1_col1, main_row1_col2 = st.columns([6,4]) # Ajustar ratio

            with main_row1_col1: # Clasificación
                st.markdown("<div class='data-block'><h4 class='block-title'><span class='icon'>" + ICO_CHART + "</span>Clasificación</h4>", unsafe_allow_html=True)
                s_col1, s_col2 = st.columns(2)
                def display_super_compact_standings(column, data, team_name_original, role_color_class):
                    with column:
                        name = (data.get("name", team_name_original) or "Equipo")[:12] # Truncar nombre
                        rank = data.get("ranking", "-")
                        html = f"<p class='standings-team-name {role_color_class}'>{name} <span class='standings-rank'>{rank}</span></p>"
                        html += f"<p class='standings-data-line'><strong>Total:</strong> PJ {data.get('total_pj', '-')} <span class='separator'>|</span> V{data.get('total_v', '-')},E{data.get('total_e', '-')},D{data.get('total_d', '-')} <span class='separator'>|</span> {data.get('total_gf', '-')}:{data.get('total_gc', '-')}</p>"
                        spec_type_short = (data.get('specific_type', 'Esp') or "Esp")[:3]
                        html += f"<p class='standings-data-line'><strong>{spec_type_short}.:</strong> PJ {data.get('specific_pj', '-')} <span class='separator'>|</span> V{data.get('specific_v', '-')},E{data.get('specific_e', '-')},D{data.get('specific_d', '-')} <span class='separator'>|</span> {data.get('specific_gf', '-')}:{data.get('specific_gc', '-')}</p>"
                        st.markdown(html, unsafe_allow_html=True)

                display_super_compact_standings(s_col1, home_team_main_standings, display_home_name, "team-home")
                display_super_compact_standings(s_col2, away_team_main_standings, display_away_name, "team-away")
                st.markdown("</div>", unsafe_allow_html=True)

            with main_row1_col2: # Cuotas y Marcador Principal
                st.markdown("<div class='data-block'><h4 class='block-title'><span class='icon'>" + ICO_FLAG + "</span>Principal</h4>", unsafe_allow_html=True)
                metric_cols = st.columns(3)
                with metric_cols[0]: st.metric("Final", final_score if final_score != "?:?" else PLACEHOLDER_NODATA)
                with metric_cols[1]: st.metric("AH", ah_act if ah_act != "?" else PLACEHOLDER_NODATA) # help eliminado por espacio
                with metric_cols[2]: st.metric("Goles", goals_line if goals_line != "?" else PLACEHOLDER_NODATA) # help eliminado

                if final_score != "?:?" and final_score != PLACEHOLDER_NODATA:
                     with st.expander(f"{ICO_STATS} Stats Prog.", expanded=False): # Muy compacto
                        display_compact_match_progression_stats(str(main_match_id_to_process_of), display_home_name, display_away_name)
                st.markdown("</div>", unsafe_allow_html=True)

            # --- SEGUNDA FILA DE BLOQUES: Rendimiento Reciente (si Selenium está disponible y carga rápido) ---
            # Para la compacidad extrema, esta sección puede estar en un expander también, o simplificarse aún más.
            # Por ahora, se mantiene pero su contenido es condicional y más compacto.
            if driver_actual_of: # Solo intentar si el driver está OK
                 with st.expander(f"{ICO_LIGHTNING} Rendimiento Reciente y H2H Rivales (Detalles)", expanded=False):
                    st.markdown("<div class='data-block'>", unsafe_allow_html=True) # Data-block interno
                    # Carga de datos de Selenium aquí, solo si se expande, para mejorar carga inicial
                    if 'last_home_match_in_league_of' not in st.session_state or st.session_state.current_match_id_processed != main_match_id_to_process_of:
                        if mp_home_id_of and mp_league_id_of and display_home_name != PLACEHOLDER_NODATA:
                            st.session_state.last_home_match_in_league_of = extract_last_match_in_league_of(driver_actual_of, "table_v1", display_home_name, mp_league_id_of, "input#cb_sos1[value='1']", True)
                        if mp_away_id_of and mp_league_id_of and display_away_name != PLACEHOLDER_NODATA:
                            st.session_state.last_away_match_in_league_of = extract_last_match_in_league_of(driver_actual_of, "table_v2", display_away_name, mp_league_id_of, "input#cb_sos2[value='2']", False)
                        
                        key_match_id_for_rival_a_h2h, rival_a_id_orig_col3, rival_a_name_orig_col3 = get_rival_a_for_original_h2h_of(main_match_id_to_process_of)
                        match_id_rival_b_game_ref, rival_b_id_orig_col3, rival_b_name_orig_col3 = get_rival_b_for_original_h2h_of(main_match_id_to_process_of)
                        if key_match_id_for_rival_a_h2h and rival_a_id_orig_col3 and rival_b_id_orig_col3:
                            st.session_state.details_h2h_col3_of = get_h2h_details_for_original_logic_of(driver_actual_of, key_match_id_for_rival_a_h2h, rival_a_id_orig_col3, rival_b_id_orig_col3, rival_a_name_orig_col3, rival_b_name_orig_col3)
                        else:
                            st.session_state.details_h2h_col3_of = {"status": "error", "resultado": PLACEHOLDER_NODATA}
                        st.session_state.current_match_id_processed = main_match_id_to_process_of # Marcar que se procesó para este ID

                    r_col1, r_col2, r_col3 = st.columns(3)
                    def display_super_compact_recent_match(column, title, match_data, team_name_placeholder, role_icon=""):
                        with column:
                            st.markdown(f"<div class='recent-match-card'><p class='match-title'><span class='icon'>{role_icon}</span>{title}</p>", unsafe_allow_html=True)
                            if match_data:
                                res = match_data
                                home_t_short = (res['home_team'] or "L")[:7]
                                away_t_short = (res['away_team'] or "V")[:7]
                                score_display = f"<span class='team-home'>{home_t_short}</span><span class='score-box'>{res['score'].replace('-',':')}</span><span class='team-away'>{away_t_short}</span>"
                                ah_display = format_ah_as_decimal_string_of(res.get('handicap_line_raw','-'))
                                st.markdown(f"<p class='teams-score'>{score_display}</p>", unsafe_allow_html=True)
                                st.markdown(f"<p>{ICO_HANDICAP} <span class='ah-chip'>{ah_display if ah_display != '-' else PLACEHOLDER_NODATA}</span><span class='small-caption'>{ICO_CALENDAR} {(res.get('date', PLACEHOLDER_NODATA) or '')[:10]}</span></p>", unsafe_allow_html=True)
                            else:
                                st.markdown(f"<p class='placeholder'>No datos {team_name_placeholder[:7]}</p>", unsafe_allow_html=True)
                            st.markdown("</div>", unsafe_allow_html=True)

                    display_super_compact_recent_match(r_col1, f"Últ. {display_home_name[:3]}", st.session_state.get('last_home_match_in_league_of'), display_home_name, ICO_HOME)
                    display_super_compact_recent_match(r_col2, f"Últ. {display_away_name[:3]}", st.session_state.get('last_away_match_in_league_of'), display_away_name, ICO_AWAY)
                    
                    with r_col3:
                        st.markdown(f"<div class='recent-match-card'><p class='match-title'><span class='icon'>{ICO_VS}</span>H2H Riv.</p>", unsafe_allow_html=True)
                        h2h_data_to_show = st.session_state.get('details_h2h_col3_of', {"status": "error", "resultado": PLACEHOLDER_NODATA})
                        if h2h_data_to_show.get("status") == "found":
                            res_h2h = h2h_data_to_show
                            h_name = (res_h2h.get('h2h_home_team_name', 'Loc') or "Loc")[:7]
                            a_name = (res_h2h.get('h2h_away_team_name', 'Vis') or "Vis")[:7]
                            score_h2h = f"{res_h2h.get('goles_home', '?')}:{res_h2h.get('goles_away', '?')}"
                            score_display = f"<span class='team-home'>{h_name}</span><span class='score-box'>{score_h2h}</span><span class='team-away'>{a_name}</span>"
                            ah_h2h = format_ah_as_decimal_string_of(res_h2h.get('handicap','-'))
                            st.markdown(f"<p class='teams-score'>{score_display}</p>", unsafe_allow_html=True)
                            st.markdown(f"<p>{ICO_HANDICAP} <span class='ah-chip'>{ah_h2h if ah_h2h != '-' else PLACEHOLDER_NODATA}</span></p>", unsafe_allow_html=True)
                        else:
                            st.markdown(f"<p class='placeholder'>{h2h_data_to_show.get('resultado', 'N/D H2H Riv.')}</p>", unsafe_allow_html=True)
                        st.markdown("</div>", unsafe_allow_html=True)
                    st.markdown("</div>", unsafe_allow_html=True) # Fin data-block interno


            # --- SECCIONES ADICIONALES EN EXPANDERS (cerrados por defecto) ---
            with st.expander(f"{ICO_LINK} Comparativas y H2H Directo Partido (Detalles Adicionales)", expanded=False):
                # Un data-block puede ser útil aquí también si hay mucho contenido
                # Comparativas indirectas (requieren datos de Selenium)
                # La carga de estos datos también podría diferirse hasta que se abra el expander
                # Por ahora, se asume que 'last_home/away_match_in_league_of' ya se cargaron si el expander de rendimiento se abrió.

                comp_data_L_vs_UV_A, comp_data_V_vs_UL_H = None, None
                if driver_actual_of: # Solo si el driver está activo
                    last_home_match_from_state = st.session_state.get('last_home_match_in_league_of')
                    last_away_match_from_state = st.session_state.get('last_away_match_in_league_of')

                    if last_away_match_from_state and display_home_name != PLACEHOLDER_NODATA and last_away_match_from_state.get('home_team'):
                        comp_data_L_vs_UV_A = extract_comparative_match_of(soup_main_h2h_page_of, "table_v1", display_home_name, last_away_match_from_state.get('home_team'), mp_league_id_of, True)
                    if last_home_match_from_state and display_away_name != PLACEHOLDER_NODATA and last_home_match_from_state.get('away_team'):
                        comp_data_V_vs_UL_H = extract_comparative_match_of(soup_main_h2h_page_of, "table_v2", display_away_name, last_home_match_from_state.get('away_team'), mp_league_id_of, False)
                
                st.markdown("<h6>Comparativas Indirectas:</h6>", unsafe_allow_html=True)
                ci_col1, ci_col2 = st.columns(2)
                with ci_col1:
                    st.markdown(f"<p>{ICO_HOME[:1]} vs ÚltRival{ICO_AWAY[:1]}</p>", unsafe_allow_html=True)
                    if comp_data_L_vs_UV_A:
                        d = comp_data_L_vs_UV_A; st.markdown(f"<p>{(d.get('home_team','L')or'L')[:7]} {d['score']} {(d.get('away_team','V')or'V')[:7]} <span class='ah-chip'>{format_ah_as_decimal_string_of(d.get('ah_line', '-'))}</span> L:{d.get('localia', '-')}</p>", unsafe_allow_html=True)
                    else: st.caption(PLACEHOLDER_NODATA)
                with ci_col2:
                    st.markdown(f"<p>{ICO_AWAY[:1]} vs ÚltRival{ICO_HOME[:1]}</p>", unsafe_allow_html=True)
                    if comp_data_V_vs_UL_H:
                        d = comp_data_V_vs_UL_H; st.markdown(f"<p>{(d.get('home_team','L')or'L')[:7]} {d['score']} {(d.get('away_team','V')or'V')[:7]} <span class='ah-chip'>{format_ah_as_decimal_string_of(d.get('ah_line', '-'))}</span> L:{d.get('localia', '-')}</p>", unsafe_allow_html=True)
                    else: st.caption(PLACEHOLDER_NODATA)
                
                st.markdown("<hr style='margin:3px 0;'>", unsafe_allow_html=True)
                st.markdown(f"<h6>H2H Directo (Partido):</h6>", unsafe_allow_html=True)
                h2h_d_col1, h2h_d_col2 = st.columns(2)
                with h2h_d_col1:
                    st.metric("AH H2H (L)", ah1_val if ah1_val != '-' else PLACEHOLDER_NODATA, label_visibility="collapsed") # Label más corto
                    st.metric("Res H2H (L)", res1_val if res1_val != '?:?' else PLACEHOLDER_NODATA, label_visibility="collapsed")
                with h2h_d_col2:
                    st.metric("AH H2H (Gen)", ah6_val if ah6_val != '-' else PLACEHOLDER_NODATA, label_visibility="collapsed")
                    st.metric("Res H2H (Gen)", res6_val if res6_val != '?:?' else PLACEHOLDER_NODATA, label_visibility="collapsed")
            
            end_time_of = time.time()
            st.sidebar.success(f"{ICO_CLOCK} {end_time_of - start_time_of:.1f}s")
    else:
        results_container.info(f"{ICO_INFO} Ingresa ID y Analizar para ver datos.")

if __name__ == '__main__':
    st.set_page_config(layout="wide", page_title="Análisis OF Ultra-Compacto", initial_sidebar_state="expanded")
    # Inicializar claves de session_state que se usarán para diferir cargas de Selenium
    if 'last_home_match_in_league_of' not in st.session_state: st.session_state.last_home_match_in_league_of = None
    if 'last_away_match_in_league_of' not in st.session_state: st.session_state.last_away_match_in_league_of = None
    if 'details_h2h_col3_of' not in st.session_state: st.session_state.details_h2h_col3_of = None
    if 'current_match_id_processed' not in st.session_state: st.session_state.current_match_id_processed = None # Para saber si refrescar datos de Selenium

    display_other_feature_ui()
