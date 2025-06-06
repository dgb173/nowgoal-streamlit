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
PLACEHOLDER_NODATA = "*(N/D)*" # Más corto y consistente
# Emojis para UI
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
ICO_CHART_UP = "📈" # Clasificación
ICO_LIGHTNING = "⚡️" # Rendimiento
ICO_LINK = "🔗" # Comparativas
ICO_SHIELD = "🔰" # H2H

# --- FUNCIONES HELPER PARA PARSEO Y FORMATEO (sin cambios) ---
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

# --- FUNCIONES DE ESTADÍSTICAS DE PROGRESIÓN (MODIFICADAS) ---
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
    # "Attacks" eliminado de stat_titles_of_interest
    stat_titles_of_interest = {
        "Shots": {"Home": "-", "Away": "-"}, "Shots on Goal": {"Home": "-", "Away": "-"},
        "Dangerous Attacks": {"Home": "-", "Away": "-"},
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

# Modificada para eliminar "Ataques" de la visualización
def display_match_progression_stats_view(match_id: str, home_team_name: str, away_team_name: str):
    stats_df = get_match_progression_stats_data(match_id)
    if stats_df is None:
        st.caption(f"{ICO_WARNING} Estadísticas de progresión no pudieron ser obtenidas (ID: {match_id}).")
        return
    if stats_df.empty:
        st.caption(f"{ICO_INFO} No se encontraron datos de progresión (ID: {match_id}).")
        return

    # "Ataques" eliminado de ordered_stats_display
    ordered_stats_display = {
        "Shots": "Disparos", "Shots on Goal": "Disparos a Puerta",
        "Dangerous Attacks": "Ataques Peligrosos"
    }
    
    st.markdown("<div class='progression-stats-card'>", unsafe_allow_html=True)
    st.markdown("---") 

    st.markdown(f"""
    <div class='progression-header'>
        <div class='progression-cell home-team-name'>{home_team_name or 'Local'}</div>
        <div class='progression-cell stat-name'>Estadística</div>
        <div class='progression-cell away-team-name'>{away_team_name or 'Visitante'}</div>
    </div>
    """, unsafe_allow_html=True)

    for stat_key_en, stat_name_es in ordered_stats_display.items():
        if stat_key_en in stats_df.index:
            home_val_str, away_val_str = stats_df.loc[stat_key_en, 'Casa'], stats_df.loc[stat_key_en, 'Fuera']
            try: home_val_num = int(home_val_str)
            except ValueError: home_val_num = 0
            try: away_val_num = int(away_val_str)
            except ValueError: away_val_num = 0
            
            home_color_class = "stat-higher" if home_val_num > away_val_num else ("stat-lower" if home_val_num < away_val_num else "stat-equal")
            away_color_class = "stat-higher" if away_val_num > home_val_num else ("stat-lower" if away_val_num < home_val_num else "stat-equal")

            st.markdown(f"""
            <div class='progression-row'>
                <div class='progression-cell home-value {home_color_class}'>{home_val_str}</div>
                <div class='progression-cell stat-name-value'>{stat_name_es}</div>
                <div class='progression-cell away-value {away_color_class}'>{away_val_str}</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div class='progression-row unavailable'>
                <div class='progression-cell home-value'>-</div>
                <div class='progression-cell stat-name-value'>{stat_name_es} (N/D)</div>
                <div class='progression-cell away-value'>-</div>
            </div>
            """, unsafe_allow_html=True)
    st.markdown("---")
    st.markdown("</div>", unsafe_allow_html=True)


def display_previous_match_progression_stats(title: str, match_id_str: str | None, home_name: str, away_name: str):
    if not match_id_str or match_id_str == "N/A" or not match_id_str.isdigit():
        st.caption(f"{ICO_INFO} _No ID para Est. Prog: {title}_") # Más corto
        return
    
    st.markdown(f"<p class='progression-title'>{ICO_EYE} <i>Est. Prog: {title}</i></p>", unsafe_allow_html=True)
    display_match_progression_stats_view(match_id_str, home_name, away_name)

# --- FUNCIONES DE EXTRACCIÓN DE DATOS DEL PARTIDO (Selenium y BeautifulSoup) (sin cambios en su lógica interna) ---
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
    except WebDriverException as e: st.error(f"{ICO_ERROR} Error inicializando Selenium driver (OF): {e}"); return None

def get_h2h_details_for_original_logic_of(driver_instance, key_match_id_for_h2h_url, rival_a_id, rival_b_id, rival_a_name="Rival A", rival_b_name="Rival B"):
    if not driver_instance: return {"status": "error", "resultado": f"{PLACEHOLDER_NODATA} (Driver no disponible H2H OF)"}
    if not key_match_id_for_h2h_url or not rival_a_id or not rival_b_id: return {"status": "error", "resultado": f"{PLACEHOLDER_NODATA} (IDs incompletos para H2H {rival_a_name} vs {rival_b_name})"}
    url_to_visit = f"{BASE_URL_OF}/match/h2h-{key_match_id_for_h2h_url}"
    try:
        driver_instance.get(url_to_visit)
        WebDriverWait(driver_instance, SELENIUM_TIMEOUT_SECONDS_OF, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.presence_of_element_located((By.ID, "table_v2")))
        time.sleep(0.7); soup_selenium = BeautifulSoup(driver_instance.page_source, "html.parser")
    except TimeoutException: return {"status": "error", "resultado": f"{PLACEHOLDER_NODATA} (Timeout esperando table_v2 en {url_to_visit})"}
    except Exception as e: return {"status": "error", "resultado": f"{PLACEHOLDER_NODATA} (Error Selenium en {url_to_visit}: {type(e).__name__})"}

    if not soup_selenium: return {"status": "error", "resultado": f"{PLACEHOLDER_NODATA} (Fallo soup Selenium H2H Original OF en {url_to_visit})"}
    table_to_search_h2h = soup_selenium.find("table", id="table_v2")
    if not table_to_search_h2h: return {"status": "error", "resultado": f"{PLACEHOLDER_NODATA} (Tabla v2 para H2H no encontrada en {url_to_visit})"}

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
    return {"status": "not_found", "resultado": f"H2H directo no encontrado para {rival_a_name} vs {rival_b_name} en historial (table_v2) de la página de ref. ({key_match_id_for_h2h_url})."}

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

            if (is_home_game_filter and team_is_home_in_row) or \
               (not is_home_game_filter and team_is_away_in_row):
                date_span = tds[1].find("span", {"name": "timeData"}); date_text = date_span.text.strip() if date_span else PLACEHOLDER_NODATA
                score_class_re = re.compile(r"fscore_"); score_span = tds[3].find("span", class_=score_class_re); score_text = score_span.text.strip() if score_span else PLACEHOLDER_NODATA
                handicap_cell = tds[11]; handicap_raw_text = handicap_cell.get("data-o", handicap_cell.text.strip())
                if not handicap_raw_text or handicap_raw_text.strip() == "-": handicap_raw_text = PLACEHOLDER_NODATA
                else: handicap_raw_text = handicap_raw_text.strip()
                match_id_last_game = row.get('index')
                return {"date": date_text, "home_team": home_team_row_name,
                        "away_team": away_team_row_name,"score": score_text,
                        "handicap_line_raw": handicap_raw_text,
                        "match_id": match_id_last_game}
        return None
    except Exception: return None

def get_main_match_odds_selenium_of(driver):
    odds_info = {"ah_home_cuota": PLACEHOLDER_NODATA, "ah_linea_raw": PLACEHOLDER_NODATA, "ah_away_cuota": PLACEHOLDER_NODATA, "goals_over_cuota": PLACEHOLDER_NODATA, "goals_linea_raw": PLACEHOLDER_NODATA, "goals_under_cuota": PLACEHOLDER_NODATA}
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
            data["specific_type"] = "Est. como Local (Liga)"
    if not team_table_soup:
        guest_div = standings_section.find("div", class_="guest-div")
        if guest_div:
            header_tr = guest_div.find("tr", class_="team-guest")
            if header_tr and header_tr.find("a") and target_team_name_exact.lower() in header_tr.find("a").get_text(strip=True).lower():
                team_table_soup = guest_div.find("table", class_="team-table-guest"); is_home_table_type = False
                data["specific_type"] = "Est. como Visitante (Liga)"
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
    h2h_gen_home_name, h2h_gen_away_name = "Local (H2H Gen)", "Visitante (H2H Gen)"

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
    match6_id = h2h_general_match.get('matchIndex'); h2h_gen_home_name = h2h_general_match.get('home', "Local (H2H Gen)"); h2h_gen_away_name = h2h_general_match.get('away', "Visitante (H2H Gen)")

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
    for row in table.find_all("tr", id=re.compile(rf"tr{table_id_of_team_to_search[-1]}_\d+")):
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

# --- STREAMLIT APP UI (Función principal con CSS refinado y "Attacks" eliminado) ---
def display_other_feature_ui():
    # CSS Refinado
    st.markdown(f"""
    <style>
        /* Fuentes y Colores Base */
        body {{ font-family: 'Inter', 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #F0F2F6; }}
        .main {{ padding: 1.2rem; }}

        /* Títulos y Encabezados */
        .main-title {{
            font-size: 2.3em; font-weight: 700; color: #172B4D; /* Azul más corporativo */
            text-align: center; margin-bottom: 0.5rem;
            text-shadow: 1px 1px 2px rgba(0,0,0,0.1);
        }}
        .match-subtitle {{
            font-size: 1.5em; text-align: center; color: #4A4A4A; /* Gris oscuro para contraste */
            margin-bottom: 1rem;
        }}
        .match-info-caption {{
            text-align: center; color: #5E6C84; /* Gris azulado medio */
            font-size: 0.9em; margin-bottom: 1.5rem; background-color: #F7F9FC;
            padding: 0.5rem; border-radius: 6px; border: 1px solid #DFE1E6;
        }}
        .match-info-caption strong {{ color: #172B4D; }}
        .match-info-caption .data-highlight {{ color: #DE350B; /* Rojo más oscuro */ }}

        .section-title {{
            font-size: 1.6em; font-weight: 600; color: #0052CC; /* Azul Atlassian */
            margin-top: 2rem; margin-bottom: 1rem;
            border-bottom: 3px solid #0052CC; padding-bottom: 0.5rem;
            display: flex; align-items: center;
        }}
        .section-title .icon {{ margin-right: 0.5rem; font-size: 1.2em;}}
        
        .card-header-title {{
            font-size: 1.2em; font-weight: 600; color: #172B4D;
            margin-bottom: 0.8rem; display: flex; align-items: center;
        }}
        .card-header-title .icon {{ margin-right: 0.4rem; color: #0052CC; }}

        /* Colores de Equipo y Marcadores (Consistentes) */
        .team-home-color {{ color: #0052CC; font-weight: 600; }} /* Azul Atlassian */
        .team-away-color {{ color: #FF8B00; font-weight: 600; }} /* Naranja Atlassian */
        
        .score-display-text {{ font-size: 1em; margin: 0.5rem 0;}}
        .score-value {{ font-size: 1.2em; font-weight: 700; color: #36B37E; /* Verde Atlassian */ margin: 0 0.3rem; }}
        .ah-value {{ font-weight: 600; color: #6554C0; /* Púrpura Atlassian */ font-size:1em;}}
        .placeholder-text {{ color: #7A869A; font-style: italic; font-size:0.9em;}}

        /* Tarjetas de Datos */
        .data-card {{
            background-color: #FFFFFF; border: 1px solid #DFE1E6; /* Borde gris claro Atlassian */
            border-radius: 8px; padding: 1.2rem; margin-bottom: 1.2rem;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1), 0 1px 2px rgba(0,0,0,0.06);
            transition: box-shadow 0.3s ease-in-out;
        }}
        .data-card:hover {{ box-shadow: 0 4px 8px rgba(0,0,0,0.12), 0 2px 4px rgba(0,0,0,0.08); }}
        .data-card p {{ margin-bottom: 0.4rem; line-height: 1.6; font-size: 0.95em; }}
        .data-card strong {{ font-weight: 600; color: #42526E; /* Gris oscuro Atlassian */}}
        .data-card .card-section-divider {{ margin-top: 0.8rem; margin-bottom: 0.8rem; border-top: 1px dashed #C1C7D0;}}

        /* Clasificación en Tarjetas */
        .standings-card .card-header-title {{ display: flex; align-items: center; justify-content: space-between;}}
        .standings-card .ranking-badge {{ background-color: #DEEBFF; color: #0747A6; padding: 0.25rem 0.5rem; border-radius: 12px; font-size: 0.85em; font-weight: 600; }}
        .standings-category-title {{ font-weight: 600; color: #505F79; margin-top: 1rem; margin-bottom: 0.3rem; font-size: 0.95em;}}
        .standings-stats span {{ margin-right: 0.8rem; }}
        .standings-stats strong {{ min-width: 30px; display: inline-block; }}

        /* Métricas Streamlit Personalizadas */
        .stMetric {{
            background-color: #FAFBFC; /* Ligeramente más claro que el fondo de la tarjeta */
            border: 1px solid #EBECF0;
            border-radius: 6px; padding: 0.8rem; text-align: center; margin-bottom: 0.8rem;
        }}
        .stMetric label {{font-size: 0.85em !important; color: #6B778C !important; font-weight: 500 !important; text-transform: uppercase; margin-bottom: 0.3rem !important; }}
        .stMetric .st-ae {{font-size: 1.6em !important; font-weight:600 !important; color: #0065FF !important;}} /* Valor principal, Azul Atlassian brillante */
        .stMetric .st-af {{font-size: 0.8em !important; color: #505F79 !important;}} /* Delta */

        /* Estadísticas de Progresión (Basado en la estructura anterior) */
        .progression-title {{ font-size: 1em; color: #505F79; margin-top: 1rem; margin-bottom: 0.3rem; text-align: left; font-style: italic;}}
        .progression-stats-card {{ background-color: #F4F5F7; border: 1px solid #DFE1E6; border-radius: 6px; padding: 0.8rem 1rem; margin-top: 0.5rem; }}
        .progression-header {{ display: flex; justify-content: space-between; font-weight: 600; color: #172B4D; padding-bottom: 0.5rem; border-bottom: 1px solid #C1C7D0; margin-bottom: 0.5rem; font-size: 0.9em;}}
        .progression-row {{ display: flex; justify-content: space-between; align-items: center; padding: 0.3rem 0; font-size: 0.9em; }}
        .progression-row.unavailable .stat-name-value {{ color: #7A869A; }}
        .progression-cell {{ flex-basis: 30%; text-align: center; }}
        .progression-cell.home-team-name {{ text-align: left; color: #0052CC; font-weight: 500;}}
        .progression-cell.away-team-name {{ text-align: right; color: #FF8B00; font-weight: 500;}}
        .progression-cell.stat-name, .progression-cell.stat-name-value {{ flex-basis: 40%; color: #42526E; }}
        .progression-cell.home-value, .progression-cell.away-value {{ font-weight: 600; font-size: 1em; }}
        .stat-higher {{ color: #00875A; /* Verde más oscuro Atlassian */ }}
        .stat-lower {{ color: #BF2600; /* Rojo oscuro Atlassian */ }}
        .stat-equal {{ color: #42526E; }}

        /* Expander */
        .stExpander {{ border: 1px solid #DFE1E6; border-radius: 6px; overflow: hidden; background-color: #fff; margin-bottom: 1rem;}}
        .stExpander summary {{ background-color: #F4F5F7 !important; padding-top: 0.6rem !important; padding-bottom: 0.6rem !important; padding-left: 1rem !important;}}
        /* Acceso directo al botón dentro del summary (puede ser frágil si Streamlit cambia su DOM) */
        .stExpander summary div[data-testid="stExpanderHeader"] {{ font-size: 1.1em !important; font-weight: 600 !important; color: #172B4D !important; }}
        .stExpander summary svg {{ fill: #42526E !important; }}
        .stExpander div[data-testid="stExpanderDetails"] {{ padding: 1rem; background-color: #FFFFFF; }}

        /* Barra lateral */
        div[data-testid="stSidebarUserContent"] {{ background-color: #F4F5F7; padding: 1.2rem; border-right: 1px solid #DFE1E6; }}
        div[data-testid="stSidebarUserContent"] .stButton button {{ background-color: #0052CC; color: white; border-radius: 4px; border: none; padding: 0.5rem 1rem;}}
        div[data-testid="stSidebarUserContent"] .stButton button:hover {{ background-color: #0065FF; }}
    </style>
    """, unsafe_allow_html=True)

    st.sidebar.image("https://raw.githubusercontent.com/streamlit/docs/main/public/images/brand/streamlit-logo-secondary-colormark-darktext.svg", width=180)
    st.sidebar.title(f"{ICO_GEAR} Configuración (OF)")
    main_match_id_str_input_of = st.sidebar.text_input(
        f"{ICO_ID} ID Partido Principal:", value="2696131",
        help="Pega el ID numérico del partido.", key="other_feature_match_id_input")
    analizar_button_of = st.sidebar.button(f"{ICO_ROCKET} Analizar Partido (OF)", type="primary", use_container_width=True, key="other_feature_analizar_button")

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
                results_container.error(f"{ICO_ERROR} El ID de partido ingresado no es válido."); st.stop()
        if not main_match_id_to_process_of:
            results_container.warning(f"{ICO_WARNING} Por favor, ingresa un ID de partido válido."); st.stop()

        start_time_of = time.time()
        with results_container, st.spinner(f"{ICO_CLOCK} Cargando datos y análisis... Por favor, espera."):
            main_page_url_h2h_view_of = f"/match/h2h-{main_match_id_to_process_of}"
            soup_main_h2h_page_of = fetch_soup_requests_of(main_page_url_h2h_view_of)
            if not soup_main_h2h_page_of:
                st.error(f"{ICO_ERROR} No se pudo obtener la página H2H para ID {main_match_id_to_process_of}."); st.stop()

            mp_home_id_of, mp_away_id_of, mp_league_id_of, mp_home_name_from_script, mp_away_name_from_script, mp_league_name_of = get_team_league_info_from_script_of(soup_main_h2h_page_of)
            home_team_main_standings = extract_standings_data_from_h2h_page_of(soup_main_h2h_page_of, mp_home_name_from_script)
            away_team_main_standings = extract_standings_data_from_h2h_page_of(soup_main_h2h_page_of, mp_away_name_from_script)
            
            display_home_name = home_team_main_standings.get("name") if home_team_main_standings.get("name") not in [PLACEHOLDER_NODATA, "N/A"] else mp_home_name_from_script or "Equipo Local"
            display_away_name = away_team_main_standings.get("name") if away_team_main_standings.get("name") not in [PLACEHOLDER_NODATA, "N/A"] else mp_away_name_from_script or "Equipo Visitante"

            st.markdown(f"<p class='main-title'>{ICO_STATS} Análisis Avanzado de Partido</p>", unsafe_allow_html=True)
            st.markdown(f"<p class='match-subtitle'><span class='team-home-color'>{display_home_name}</span> {ICO_VS} <span class='team-away-color'>{display_away_name}</span></p>", unsafe_allow_html=True)
            st.markdown(f"<p class='match-info-caption'>{ICO_LEAGUE} <strong>Liga:</strong> {mp_league_name_of or PLACEHOLDER_NODATA} (ID: {mp_league_id_of or PLACEHOLDER_NODATA})<br>{ICO_ID} <strong>Partido ID:</strong> <span class='data-highlight'>{main_match_id_to_process_of}</span></p>", unsafe_allow_html=True)
            
            # --- Clasificación ---
            st.markdown(f"<h2 class='section-title'><span class='icon'>{ICO_CHART_UP}</span>Clasificación en Liga</h2>", unsafe_allow_html=True)
            col_home_stand, col_away_stand = st.columns(2)

            def display_standings_card_styled(team_standings_data, team_display_name, team_color_class_css):
                name = team_standings_data.get("name", team_display_name)
                rank = team_standings_data.get("ranking", "-")
                
                with st.container():
                    st.markdown(f"<div class='data-card standings-card'>", unsafe_allow_html=True)
                    st.markdown(f"<h3 class='card-header-title {team_color_class_css}'><span class='icon'>{ICO_HOME if 'home' in team_color_class_css else ICO_AWAY}</span>{name} <span class='ranking-badge'>Rank: {rank}</span></h3>", unsafe_allow_html=True)
                    
                    st.markdown(f"<p class='standings-category-title'>Total en Liga:</p>", unsafe_allow_html=True)
                    st.markdown(f"<p class='standings-stats'><strong>PJ:</strong> {team_standings_data.get('total_pj', '-')} <span><strong>V:</strong> {team_standings_data.get('total_v', '-')}</span> <span><strong>E:</strong> {team_standings_data.get('total_e', '-')}</span> <span><strong>D:</strong> {team_standings_data.get('total_d', '-')}</span></p>", unsafe_allow_html=True)
                    st.markdown(f"<p class='standings-stats'><strong>GF:</strong> {team_standings_data.get('total_gf', '-')} <span><strong>GC:</strong> {team_standings_data.get('total_gc', '-')}</span></p>", unsafe_allow_html=True)
                    
                    st.markdown("<div class='card-section-divider'></div>", unsafe_allow_html=True)
                    
                    st.markdown(f"<p class='standings-category-title'>{team_standings_data.get('specific_type', 'Est. Específicas') or 'Est. Específicas'}:</p>", unsafe_allow_html=True)
                    st.markdown(f"<p class='standings-stats'><strong>PJ:</strong> {team_standings_data.get('specific_pj', '-')} <span><strong>V:</strong> {team_standings_data.get('specific_v', '-')}</span> <span><strong>E:</strong> {team_standings_data.get('specific_e', '-')}</span> <span><strong>D:</strong> {team_standings_data.get('specific_d', '-')}</span></p>", unsafe_allow_html=True)
                    st.markdown(f"<p class='standings-stats'><strong>GF:</strong> {team_standings_data.get('specific_gf', '-')} <span><strong>GC:</strong> {team_standings_data.get('specific_gc', '-')}</span></p>", unsafe_allow_html=True)
                    st.markdown("</div>", unsafe_allow_html=True)
            
            with col_home_stand:
                display_standings_card_styled(home_team_main_standings, display_home_name, "team-home-color")
            with col_away_stand:
                display_standings_card_styled(away_team_main_standings, display_away_name, "team-away-color")
            
            # --- Datos que dependen de Selenium (Driver, cuotas, últimos partidos, H2H indirecto) ---
            key_match_id_for_rival_a_h2h, rival_a_id_orig_col3, rival_a_name_orig_col3 = get_rival_a_for_original_h2h_of(main_match_id_to_process_of)
            match_id_rival_b_game_ref, rival_b_id_orig_col3, rival_b_name_orig_col3 = get_rival_b_for_original_h2h_of(main_match_id_to_process_of)

            main_match_odds_data_of = {}
            last_home_match_in_league_of = None
            last_away_match_in_league_of = None
            driver_actual_of = st.session_state.driver_other_feature
            driver_of_needs_init = driver_actual_of is None
            if not driver_of_needs_init:
                try: _ = driver_actual_of.window_handles
                except WebDriverException: driver_of_needs_init = True

            if driver_of_needs_init:
                if driver_actual_of is not None:
                    try: driver_actual_of.quit()
                    except: pass
                with st.spinner(f"{ICO_CLOCK} Inicializando WebDriver para datos adicionales..."):
                    driver_actual_of = get_selenium_driver_of()
                st.session_state.driver_other_feature = driver_actual_of

            if driver_actual_of:
                try:
                    driver_actual_of.get(f"{BASE_URL_OF}{main_page_url_h2h_view_of}")
                    WebDriverWait(driver_actual_of, SELENIUM_TIMEOUT_SECONDS_OF).until(EC.presence_of_element_located((By.ID, "table_v1")))
                    time.sleep(0.8) 
                    main_match_odds_data_of = get_main_match_odds_selenium_of(driver_actual_of)
                    if mp_home_id_of and mp_league_id_of and display_home_name != PLACEHOLDER_NODATA:
                         last_home_match_in_league_of = extract_last_match_in_league_of(driver_actual_of, "table_v1", display_home_name, mp_league_id_of, "input#cb_sos1[value='1']", True)
                    if mp_away_id_of and mp_league_id_of and display_away_name != PLACEHOLDER_NODATA:
                        last_away_match_in_league_of = extract_last_match_in_league_of(driver_actual_of, "table_v2", display_away_name, mp_league_id_of, "input#cb_sos2[value='2']", False)
                except Exception as e_main_sel_of: st.error(f"{ICO_ERROR} Error Selenium: {type(e_main_sel_of).__name__} - {e_main_sel_of}.")
            else: st.warning(f"{ICO_WARNING} WebDriver no disponible. Cuotas y últimos partidos filtrados podrían faltar.")

            col_data = { "Fin": "?:?", "AH_Act": "?", "G_i": "?"}
            col_data["Fin"], _ = extract_final_score_of(soup_main_h2h_page_of)
            col_data["AH_Act"] = format_ah_as_decimal_string_of(main_match_odds_data_of.get('ah_linea_raw', '?'))
            col_data["G_i"] = format_ah_as_decimal_string_of(main_match_odds_data_of.get('goals_linea_raw', '?'))
            
            ah1_val, res1_val, _, match1_id_h2h_v, \
            ah6_val, res6_val, _, match6_id_h2h_g, \
            h2h_gen_home_name, h2h_gen_away_name = extract_h2h_data_of(soup_main_h2h_page_of, display_home_name, display_away_name, mp_league_id_of)
            
            col_data["AH_H2H_V"], col_data["Res_H2H_V"] = ah1_val, res1_val
            col_data["AH_H2H_G"], col_data["Res_H2H_G"] = ah6_val, res6_val

            comp_data_L_vs_UV_A, comp_data_V_vs_UL_H = None, None
            if last_away_match_in_league_of and display_home_name != PLACEHOLDER_NODATA and last_away_match_in_league_of.get('home_team'):
                comp_data_L_vs_UV_A = extract_comparative_match_of(soup_main_h2h_page_of, "table_v1", display_home_name, last_away_match_in_league_of.get('home_team'), mp_league_id_of, True)
            if last_home_match_in_league_of and display_away_name != PLACEHOLDER_NODATA and last_home_match_in_league_of.get('away_team'):
                comp_data_V_vs_UL_H = extract_comparative_match_of(soup_main_h2h_page_of, "table_v2", display_away_name, last_home_match_in_league_of.get('away_team'), mp_league_id_of, False)

            # --- RENDERIZACIÓN DE LA UI - Sección de Cuotas y Marcador Principal ---
            st.markdown(f"<h2 class='section-title'><span class='icon'>{ICO_SCORE}</span>Partido Principal y Cuotas</h2>", unsafe_allow_html=True)
            with st.expander(f"{ICO_SCORE} Cuotas Iniciales (Bet365) y Marcador Final", expanded=True):
                st.markdown("<div class='data-card'>", unsafe_allow_html=True)
                final_score_display = col_data["Fin"] if col_data["Fin"] != "?:?" else PLACEHOLDER_NODATA
                
                m_col1, m_col2, m_col3 = st.columns(3)
                with m_col1: st.metric("🏁 Marcador Final", final_score_display)
                with m_col2: st.metric("⚖️ AH (Línea)", col_data["AH_Act"] if col_data["AH_Act"] != "?" else PLACEHOLDER_NODATA, help=f"Cuotas: {main_match_odds_data_of.get('ah_home_cuota','-')} / {main_match_odds_data_of.get('ah_away_cuota','-')}")
                with m_col3: st.metric("🥅 Goles (Línea)", col_data["G_i"] if col_data["G_i"] != "?" else PLACEHOLDER_NODATA, help=f"Cuotas Más/Menos: {main_match_odds_data_of.get('goals_over_cuota','-')} / {main_match_odds_data_of.get('goals_under_cuota','-')}")
                
                if final_score_display != PLACEHOLDER_NODATA :
                    display_previous_match_progression_stats(
                        f"Principal: {display_home_name} vs {display_away_name}",
                        str(main_match_id_to_process_of), display_home_name, display_away_name
                    )
                else: st.caption(f"{ICO_INFO} Estadísticas de progresión se mostrarán si el partido ha finalizado.")
                st.markdown("</div>", unsafe_allow_html=True)


            # --- Rendimiento Reciente y H2H Indirecto ---
            st.markdown(f"<h2 class='section-title'><span class='icon'>{ICO_LIGHTNING}</span>Rendimiento Reciente y H2H Rivales</h2>", unsafe_allow_html=True)
            rp_col1, rp_col2, rp_col3 = st.columns(3)

            def display_recent_match_card(column, title_html, match_data, team_name_for_placeholder):
                with column, st.container():
                    st.markdown("<div class='data-card'>", unsafe_allow_html=True)
                    st.markdown(f"<h3 class='card-header-title'>{title_html}</h3>", unsafe_allow_html=True)
                    if match_data:
                        res = match_data
                        st.markdown(f"<p class='score-display-text'><span class='team-home-color'>{res['home_team']}</span> <span class='score-value'>{res['score'].replace('-',':')}</span> <span class='team-away-color'>{res['away_team']}</span></p>", unsafe_allow_html=True)
                        formatted_ah = format_ah_as_decimal_string_of(res.get('handicap_line_raw','-'))
                        st.markdown(f"<p>{ICO_HANDICAP} <strong>AH:</strong> <span class='ah-value'>{formatted_ah if formatted_ah != '-' else PLACEHOLDER_NODATA}</span></p>", unsafe_allow_html=True)
                        st.caption(f"{ICO_CALENDAR} {res.get('date', PLACEHOLDER_NODATA)}")
                        display_previous_match_progression_stats(
                            f"{res.get('home_team','L')} vs {res.get('away_team','V')}",
                            res.get('match_id'), res.get('home_team','Local'), res.get('away_team','Visitante')
                        )
                    else: st.info(f"{ICO_INFO} No se encontró partido para {team_name_for_placeholder}.")
                    st.markdown("</div>", unsafe_allow_html=True)

            display_recent_match_card(rp_col1, f"{ICO_HOME} Último <span class='team-home-color'>{display_home_name}</span> (Casa)", last_home_match_in_league_of, display_home_name)
            display_recent_match_card(rp_col2, f"{ICO_AWAY} Último <span class='team-away-color'>{display_away_name}</span> (Fuera)", last_away_match_in_league_of, display_away_name)

            with rp_col3, st.container():
                st.markdown("<div class='data-card'>", unsafe_allow_html=True)
                st.markdown(f"<h3 class='card-header-title'><span class='icon'>{ICO_VS}</span>H2H Rivales (Col3)</h3>", unsafe_allow_html=True)
                details_h2h_col3_of = {"status": "error", "resultado": PLACEHOLDER_NODATA}
                if key_match_id_for_rival_a_h2h and rival_a_id_orig_col3 and rival_b_id_orig_col3 and driver_actual_of:
                    details_h2h_col3_of = get_h2h_details_for_original_logic_of(driver_actual_of, key_match_id_for_rival_a_h2h, rival_a_id_orig_col3, rival_b_id_orig_col3, rival_a_name_orig_col3, rival_b_name_orig_col3)

                if details_h2h_col3_of.get("status") == "found":
                    res_h2h = details_h2h_col3_of
                    h2h_home_name_col3 = res_h2h.get('h2h_home_team_name', 'Local H2H')
                    h2h_away_name_col3 = res_h2h.get('h2h_away_team_name', 'Visitante H2H')
                    st.markdown(f"<p class='score-display-text'><span class='team-home-color'>{h2h_home_name_col3}</span> <span class='score-value'>{res_h2h.get('goles_home', '?')}:{res_h2h.get('goles_away', '?')}</span> <span class='team-away-color'>{h2h_away_name_col3}</span></p>", unsafe_allow_html=True)
                    formatted_ah_h2h_col3 = format_ah_as_decimal_string_of(res_h2h.get('handicap','-'))
                    st.markdown(f"<p>{ICO_HANDICAP} <strong>AH:</strong> <span class='ah-value'>{formatted_ah_h2h_col3 if formatted_ah_h2h_col3 != '-' else PLACEHOLDER_NODATA}</span></p>", unsafe_allow_html=True)
                    display_previous_match_progression_stats(
                        f"H2H Col3: {h2h_home_name_col3} vs {h2h_away_name_col3}",
                        res_h2h.get('match_id'), h2h_home_name_col3, h2h_away_name_col3
                    )
                else: st.info(f"{ICO_INFO} {details_h2h_col3_of.get('resultado', f'H2H Col3 entre {rival_a_name_orig_col3 or 'RivalA'} y {rival_b_name_orig_col3 or 'RivalB'} no disponible.')}")
                st.markdown("</div>", unsafe_allow_html=True)
            
            # --- Comparativas y H2H Directos ---
            with st.expander(f"{ICO_LINK} Comparativas Indirectas Detalladas", expanded=False):
                st.markdown("<div class='data-card'>", unsafe_allow_html=True) # Data-card interno para consistencia
                comp_col1, comp_col2 = st.columns(2)
                with comp_col1:
                    st.markdown(f"<h5 class='card-header-title' style='font-size:1em;'><span class='team-home-color'>{display_home_name}</span> vs. <span class='team-away-color'>Últ. Rival de {display_away_name}</span></h5>", unsafe_allow_html=True)
                    if comp_data_L_vs_UV_A:
                        data = comp_data_L_vs_UV_A
                        score_part = data['score'].replace('*', ':').strip()
                        ah_val = data.get('ah_line', '-')
                        st.markdown(f"<p>{ICO_SCORE} <strong>Res:</strong> <span class='data-highlight'>{score_part or PLACEHOLDER_NODATA}</span> ({data.get('home_team')} vs {data.get('away_team')})</p>", unsafe_allow_html=True)
                        st.markdown(f"<p>{ICO_HANDICAP} <strong>AH:</strong> <span class='ah-value'>{format_ah_as_decimal_string_of(ah_val) or PLACEHOLDER_NODATA}</span></p>", unsafe_allow_html=True)
                        st.markdown(f"<p>🏟️ <strong>Localía '{display_home_name}':</strong> <span class='data-highlight'>{data.get('localia', PLACEHOLDER_NODATA)}</span></p>", unsafe_allow_html=True)
                        display_previous_match_progression_stats(
                            f"Comp: {data.get('home_team','L')} vs {data.get('away_team','V')}",
                            data.get('match_id'), data.get('home_team','Local'), data.get('away_team','Visitante')
                        )
                    else: st.info(f"{ICO_INFO} Comparativa no disponible.")

                with comp_col2:
                    st.markdown(f"<h5 class='card-header-title' style='font-size:1em;'><span class='team-away-color'>{display_away_name}</span> vs. <span class='team-home-color'>Últ. Rival de {display_home_name}</span></h5>", unsafe_allow_html=True)
                    if comp_data_V_vs_UL_H:
                        data = comp_data_V_vs_UL_H
                        score_part = data['score'].replace('*', ':').strip()
                        ah_val = data.get('ah_line', '-')
                        st.markdown(f"<p>{ICO_SCORE} <strong>Res:</strong> <span class='data-highlight'>{score_part or PLACEHOLDER_NODATA}</span> ({data.get('home_team')} vs {data.get('away_team')})</p>", unsafe_allow_html=True)
                        st.markdown(f"<p>{ICO_HANDICAP} <strong>AH:</strong> <span class='ah-value'>{format_ah_as_decimal_string_of(ah_val) or PLACEHOLDER_NODATA}</span></p>", unsafe_allow_html=True)
                        st.markdown(f"<p>🏟️ <strong>Localía '{display_away_name}':</strong> <span class='data-highlight'>{data.get('localia', PLACEHOLDER_NODATA)}</span></p>", unsafe_allow_html=True)
                        display_previous_match_progression_stats(
                            f"Comp: {data.get('home_team','L')} vs {data.get('away_team','V')}",
                            data.get('match_id'), data.get('home_team','Local'), data.get('away_team','Visitante')
                        )
                    else: st.info(f"{ICO_INFO} Comparativa no disponible.")
                st.markdown("</div>", unsafe_allow_html=True)
            
            with st.expander(f"{ICO_SHIELD} Hándicaps y Resultados Clave (H2H Directos)", expanded=False):
                st.markdown("<div class='data-card'>", unsafe_allow_html=True) # Data-card interno
                h2h_direct_col1, h2h_direct_col2 = st.columns(2)
                with h2h_direct_col1:
                    st.metric("AH H2H (Local en Casa)", col_data["AH_H2H_V"] if col_data["AH_H2H_V"] != '-' else PLACEHOLDER_NODATA)
                    st.metric("Res H2H (Local en Casa)", col_data["Res_H2H_V"] if col_data["Res_H2H_V"] != '?:?' else PLACEHOLDER_NODATA)
                    if match1_id_h2h_v:
                        display_previous_match_progression_stats(
                            f"H2H: {display_home_name} (Casa) vs {display_away_name}",
                            match1_id_h2h_v, display_home_name, display_away_name
                        )
                with h2h_direct_col2:
                    st.metric("AH H2H (General)", col_data["AH_H2H_G"] if col_data["AH_H2H_G"] != '-' else PLACEHOLDER_NODATA)
                    st.metric("Res H2H (General)", col_data["Res_H2H_G"] if col_data["Res_H2H_G"] != '?:?' else PLACEHOLDER_NODATA)
                    if match6_id_h2h_g:
                        display_previous_match_progression_stats(
                            f"H2H General: {h2h_gen_home_name} vs {h2h_gen_away_name}",
                            match6_id_h2h_g, h2h_gen_home_name, h2h_gen_away_name
                        )
                st.markdown("</div>", unsafe_allow_html=True)
            
            st.divider() # Un divisor final puede ser útil
            end_time_of = time.time()
            st.sidebar.success(f"🎉 Análisis en {end_time_of - start_time_of:.2f} seg.")
    else:
        results_container.info(f"{ICO_INFO} ¡Bienvenido! Ingresa un ID de partido y haz clic en 'Analizar Partido (OF)' para comenzar.")

if __name__ == '__main__':
    st.set_page_config(layout="wide", page_title="Análisis Avanzado (OF)", initial_sidebar_state="expanded")
    if 'driver_other_feature' not in st.session_state:
        st.session_state.driver_other_feature = None
    display_other_feature_ui()
