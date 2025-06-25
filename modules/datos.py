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
        st.caption(f"ℹ️ _No hay ID de partido para obtener estadísticas de progresión para: {title}_")
        return

    st.markdown(f"###### 👁️ _Est. Progresión para: {title}_")
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
            tds = row.find_all("td");
            HANDICAP_TD_IDX = 11
            handicap_raw = "N/A"
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
            if count_visible_rows > 10: break # Limitar a los 10 primeros partidos visibles para eficiencia
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

def get_main_match_odds_selenium_of(driver):
    odds_info = {"ah_home_cuota": "N/A", "ah_linea_raw": "N/A", "ah_away_cuota": "N/A", "goals_over_cuota": "N/A", "goals_linea_raw": "N/A", "goals_under_cuota": "N/A"}
    try:
        live_compare_div = WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS_OF, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.presence_of_element_located((By.ID, "liveCompareDiv")))
        bet365_row_selector = "tr#tr_o_1_8[name='earlyOdds']"; bet365_row_selector_alt = "tr#tr_o_1_31[name='earlyOdds']"
        
        # Buscar la tabla correcta que contenga las cuotas de interés
        # A veces está dentro de un div específico o es la primera tabla con ciertas clases
        table_odds = None
        try:
            # Intentar encontrar la tabla que usualmente contiene estas cuotas
            table_odds = live_compare_div.find_element(By.XPATH, ".//table[contains(@class, 'team-table-other')]") # O alguna clase más específica si se conoce
            if not table_odds:
                 # Fallback si la anterior no funciona, buscar una tabla genérica dentro del div
                 table_odds = live_compare_div.find_element(By.TAG_NAME, "table")
        except NoSuchElementException:
            try: table_odds = live_compare_div.find_element(By.TAG_NAME, "table")
            except NoSuchElementException: pass # Si no hay tabla, devolverá N/A

        if table_odds:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", table_odds); time.sleep(0.5)
            bet365_early_odds_row = None
            try: 
                bet365_early_odds_row = WebDriverWait(driver, 5, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.visibility_of_element_located((By.CSS_SELECTOR, bet365_row_selector)))
            except TimeoutException:
                try: 
                    bet365_early_odds_row = WebDriverWait(driver, 3, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.visibility_of_element_located((By.CSS_SELECTOR, bet365_row_selector_alt)))
                except TimeoutException: pass # Si no se encuentra la fila, simplemente se retorna N/A

            if bet365_early_odds_row:
                tds = bet365_early_odds_row.find_elements(By.TAG_NAME, "td")
                if len(tds) >= 11:
                    odds_info["ah_home_cuota"] = tds[2].get_attribute("data-o") or tds[2].text.strip() or "N/A"
                    odds_info["ah_linea_raw"] = tds[3].get_attribute("data-o") or tds[3].text.strip() or "N/A"
                    odds_info["ah_away_cuota"] = tds[4].get_attribute("data-o") or tds[4].text.strip() or "N/A"
                    odds_info["goals_over_cuota"] = tds[8].get_attribute("data-o") or tds[8].text.strip() or "N/A"
                    odds_info["goals_linea_raw"] = tds[9].get_attribute("data-o") or tds[9].text.strip() or "N/A"
                    odds_info["goals_under_cuota"] = tds[10].get_attribute("data-o") or tds[10].text.strip() or "N/A"
    except Exception: pass # Capturar cualquier error durante la extracción de cuotas
    return odds_info


# MODIFICADO: Función reescrita para parsear la nueva estructura HTML de clasificación
def extract_standings_data_from_h2h_page_of(h2h_soup, target_team_name_exact):
    data = {
        "name": target_team_name_exact, "ranking": "N/A",
        "total_pj": "N/A", "total_v": "N/A", "total_e": "N/A", "total_d": "N/A", "total_gf": "N/A", "total_gc": "N/A",
        "specific_pj": "N/A", "specific_v": "N/A", "specific_e": "N/A", "specific_d": "N/A", "specific_gf": "N/A", "specific_gc": "N/A",
        "specific_type": "N/A"
    }
    if not h2h_soup or not target_team_name_exact: return data

    standings_section = h2h_soup.find("div", id="porletP4")
    if not standings_section: return data

    team_table_soup = None
    is_home_table_type = False # True if target team is in home-div, False if in guest-div

    # Check home-div
    home_div = standings_section.find("div", class_="home-div")
    if home_div:
        header_tr = home_div.find("tr", class_="team-home")
        # Asegurarse de que el nombre del equipo coincida, permitiendo ligeras variaciones o usando part of match
        team_name_in_header = header_tr.find("a").get_text(strip=True) if header_tr and header_tr.find("a") else ""
        if target_team_name_exact.lower() in team_name_in_header.lower():
            team_table_soup = home_div.find("table", class_="team-table-home")
            is_home_table_type = True
            data["specific_type"] = "Est. como Local (en Liga)"

    # If not found in home-div, check guest-div
    if not team_table_soup:
        guest_div = standings_section.find("div", class_="guest-div")
        if guest_div:
            header_tr = guest_div.find("tr", class_="team-guest")
            team_name_in_header = header_tr.find("a").get_text(strip=True) if header_tr and header_tr.find("a") else ""
            if target_team_name_exact.lower() in team_name_in_header.lower():
                team_table_soup = guest_div.find("table", class_="team-table-guest")
                is_home_table_type = False
                data["specific_type"] = "Est. como Visitante (en Liga)"

    if not team_table_soup: return data # Team not found in either div

    # Extract name and ranking from the found table's header
    header_link = team_table_soup.find("tr", class_=re.compile(r"team-(home|guest)")).find("a")
    if header_link:
        full_text = header_link.get_text(separator=" ", strip=True)
        # El formato puede variar, pero usualmente es como "[1] Team Name" o "[1-X] Team Name"
        rank_match = re.search(r"\[(?:[^\]]+-)?(\d+)\]", full_text)
        # Capturar el nombre del equipo, que suele venir después del ranking
        name_match = re.search(r"\]\s*(.*)", full_text)

        if name_match: data["name"] = name_match.group(1).strip()
        if rank_match: data["ranking"] = rank_match.group(1)
        
    # Extract stats (FT only)
    in_ft_section = False
    for row in team_table_soup.find_all("tr", align="center"):
        th_header = row.find("th")
        if th_header:
            header_text = th_header.get_text(strip=True)
            if "FT" in header_text:
                in_ft_section = True
                continue # Skip the FT header row itself
            elif "HT" in header_text:
                in_ft_section = False # Stop processing if HT section is reached
                break

        if in_ft_section:
            cells = row.find_all("td")
            if not cells or len(cells) < 7: continue # Need at least Type, PJ, W, D, L, GF, GC

            row_type_text_container = cells[0].find("span") if cells[0].find("span") else cells[0]
            row_type_text = row_type_text_container.get_text(strip=True)

            # PJ, W, D, L, GF, GC (indices 1 to 6)
            stats_values = [cell.get_text(strip=True) or "N/A" for cell in cells[1:7]]
            pj, v, e, d, gf, gc = stats_values[:6]

            if row_type_text == "Total":
                data.update({
                    "total_pj": pj, "total_v": v, "total_e": e, "total_d": d,
                    "total_gf": gf, "total_gc": gc
                })
            elif (row_type_text == "Home" and is_home_table_type) or \
                 (row_type_text == "Away" and not is_home_table_type):
                data.update({
                    "specific_pj": pj, "specific_v": v, "specific_e": e, "specific_d": d,
                    "specific_gf": gf, "specific_gc": gc
                })
    return data

def extract_final_score_of(soup):
    try:
        # Busca el div que contiene la puntuación final, que usualmente está en #mScore y tiene clases como .end .score
        score_elements = soup.select('#mScore .end .score')
        if len(score_elements) == 2:
            hs = score_elements[0].text.strip(); aws = score_elements[1].text.strip()
            if hs.isdigit() and aws.isdigit(): return f"{hs}:{aws}", f"{hs}-{aws}" # Formato "X:Y" y "X-Y"
    except Exception: pass
    return '?:?', "?-?"

def extract_h2h_data_of(soup, main_home_team_name, main_away_team_name, current_league_id):
    ah1, res1, res1_raw, match1_id = '-', '?:?', '?-?', None # H2H Directo (Local vs Visitante)
    ah6, res6, res6_raw, match6_id = '-', '?:?', '?-?', None # H2H General
    h2h_gen_home_name, h2h_gen_away_name = "Local (H2H Gen)", "Visitante (H2H Gen)" # Placeholders

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

    # El primer partido de la tabla H2H general (table_v3) suele ser el "general"
    h2h_general_match = filtered_h2h_list[0]
    ah6 = h2h_general_match.get('ahLine', '-')
    res6 = h2h_general_match.get('score', '?:?'); res6_raw = h2h_general_match.get('score_raw', '?-?')
    match6_id = h2h_general_match.get('matchIndex')
    h2h_gen_home_name = h2h_general_match.get('home', "Local (H2H Gen)")
    h2h_gen_away_name = h2h_general_match.get('away', "Visitante (H2H Gen)")

    # Buscar el H2H directo específico entre los equipos principales
    h2h_local_specific_match = None
    for d_h2h in filtered_h2h_list:
        if d_h2h.get('home','').lower() == main_home_team_name.lower() and \
           d_h2h.get('away','').lower() == main_away_team_name.lower():
            h2h_local_specific_match = d_h2h; break

    if h2h_local_specific_match:
        ah1 = h2h_local_specific_match.get('ahLine', '-')
        res1 = h2h_local_specific_match.get('score', '?:?'); res1_raw = h2h_local_specific_match.get('score_raw', '?-?')
        match1_id = h2h_local_specific_match.get('matchIndex')

    return ah1, res1, res1_raw, match1_id, ah6, res6, res6_raw, match6_id, h2h_gen_home_name, h2h_gen_away_name

def extract_comparative_match_of(soup_for_team_history, table_id_of_team_to_search, team_name_to_find_match_for, opponent_name_to_search, current_league_id, is_home_table):
    if not opponent_name_to_search or opponent_name_to_search == "N/A" or not team_name_to_find_match_for:
        return None

    table = soup_for_team_history.find("table", id=table_id_of_team_to_search)
    if not table: return None

    # Determinar el selector de score_class basado en la tabla (table_v1 -> fscore_1, table_v2 -> fscore_2)
    score_class_selector = 'fscore_1' if 'v1' in table_id_of_team_to_search else 'fscore_2'

    for row in table.find_all("tr", id=re.compile(rf"tr{table_id_of_team_to_search[-1]}_\d+")):
        details = get_match_details_from_row_of(row, score_class_selector=score_class_selector, source_table_type='hist')
        if not details: continue
        if current_league_id and details.get('league_id_hist') and details.get('league_id_hist') != str(current_league_id): continue

        home_hist = details.get('home','').lower(); away_hist = details.get('away','').lower()
        team_main_lower = team_name_to_find_match_for.lower(); opponent_lower = opponent_name_to_search.lower()

        # Buscar si el partido involucra a nuestro equipo principal y al oponente
        if (team_main_lower == home_hist and opponent_lower == away_hist) or \
           (team_main_lower == away_hist and opponent_lower == home_hist):
            
            score_val = details.get('score', '?:?')
            ah_line_extracted = details.get('ahLine', '-')
            # Determinar la 'localía' del equipo principal en este partido comparativo
            loc_val = 'H' if team_main_lower == home_hist else 'A'

            return {
                "score": score_val,
                "ah_line": ah_line_extracted,
                "localia": loc_val,
                "home_team": details.get('home'),
                "away_team": details.get('away'),
                "match_id": details.get('matchIndex')
            }
    return None

# --- Helper para mostrar la tarjeta de clasificación ---
def display_standings_card(team_standings_data, team_display_name, team_color_class):
    if not team_standings_data or team_standings_data.get("name") == "N/A" and team_standings_data.get("ranking") == "N/A":
        st.info(f"No hay datos de clasificación disponibles para este equipo.")
        return

    name = team_standings_data.get("name", team_display_name)
    rank = team_standings_data.get("ranking", "N/A")
    st.markdown(f"<h3 class='card-title {team_color_class}'>{name} (Rank: {rank})</h3>", unsafe_allow_html=True)
    
    st.markdown("<div class='standings-table'>", unsafe_allow_html=True)
    st.markdown(f"<strong>Total Liga:</strong>")
    st.markdown(f"<p>PJ: {team_standings_data.get('total_pj', '-')} V: {team_standings_data.get('total_v', '-')} E: {team_standings_data.get('total_e', '-')} D: {team_standings_data.get('total_d', '-')}</p>", unsafe_allow_html=True)
    st.markdown(f"<p>GF: {team_standings_data.get('total_gf', '-')} GC: {team_standings_data.get('total_gc', '-')}</p>", unsafe_allow_html=True)
    
    # Mostrar estadísticas específicas (local/visitante) si están disponibles y son relevantes
    specific_type = team_standings_data.get('specific_type', 'Estadísticas Específicas')
    if team_standings_data.get('specific_pj', '-') != 'N/A':
        st.markdown(f"<strong>{specific_type}:</strong>")
        st.markdown(f"<p>PJ: {team_standings_data.get('specific_pj', '-')} V: {team_standings_data.get('specific_v', '-')} E: {team_standings_data.get('specific_e', '-')} D: {team_standings_data.get('specific_d', '-')}</p>", unsafe_allow_html=True)
        st.markdown(f"<p>GF: {team_standings_data.get('specific_gf', '-')} GC: {team_standings_data.get('specific_gc', '-')}</p>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


# --- STREAMLIT APP UI (Función principal modificada) ---
def display_other_feature_ui():
    # --- CONFIGURACIÓN DE PÁGINA Y ESTILOS ---
    st.set_page_config(
        layout="wide", # Usa todo el ancho de la pantalla
        page_title="Análisis Avanzado de Partidos (OF)",
        initial_sidebar_state="expanded"
    )

    # --- ESTILOS CSS MEJORADOS PARA MENOS SCROLL Y MÁS VISUALIDAD ---
    st.markdown("""
    <style>
        /* Estilos generales */
        .main-title { font-size: 2.3em; font-weight: bold; color: #1E90FF; text-align: center; margin-bottom: 5px; }
        .sub-title { font-size: 1.7em; text-align: center; margin-bottom: 15px; color: #4682B4;}
        .section-header { font-size: 1.8em; font-weight: bold; color: #4682B4; margin-top: 25px; margin-bottom: 15px; border-bottom: 2px solid #4682B4; padding-bottom: 5px;}
        .card-title { font-size: 1.4em; font-weight: bold; color: #333; margin-bottom: 10px; }
        .card-subtitle { font-size: 1.1em; font-weight: bold; color: #555; margin-top:15px; margin-bottom: 8px; }
        .home-color { color: #007bff; font-weight: bold; } /* Azul para local */
        .away-color { color: #fd7e14; font-weight: bold; } /* Naranja para visitante */
        .score-value { font-size: 1.2em; font-weight: bold; color: #28a745; margin: 0 5px; } /* Verde para marcador */
        .ah-value { font-weight: bold; color: #6f42c1; } /* Púrpura para AH */
        .data-highlight { font-weight: bold; color: #dc3545; } /* Rojo para datos destacados */
        .standings-table p { margin-bottom: 0.3rem; font-size: 0.95em;}
        .standings-table strong { min-width: 50px; display: inline-block; }
        .stMetric { border: 1px solid #ddd; border-radius: 5px; padding: 10px; margin-bottom:10px; background-color: #f9f9f9; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
        .stMetric label {font-size: 0.9em !important; color: #555 !important;}
        .stMetric .st-ax {font-size: 1.7em !important; font-weight:bold;}
        h6 {margin-top:10px; margin-bottom:5px; font-style:italic; color: #005A9C;}
        
        /* Contenedor principal para la cabecera del partido */
        .match-header-container {
            background-color: #e7f3fe; /* Azul muy claro */
            padding: 15px 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 4px 8px rgba(0,0,0,0.1);
        }
        
        /* Contenedor para métricas clave en fila */
        .key-metrics-row {
            display: flex;
            justify-content: space-around; /* Distribuye el espacio */
            align-items: center;
            flex-wrap: wrap; /* Permite que se apilen si no caben */
            margin-bottom: 20px;
        }
        .key-metric-item {
            flex: 1; /* Cada métrica ocupa espacio disponible */
            min-width: 180px; /* Ancho mínimo antes de apilar */
            margin: 0 10px; /* Espacio entre ítems */
            text-align: center;
        }
        .key-metric-item .stMetric { margin-bottom: 0; } /* Eliminar margen inferior dentro de la fila */
        
        /* Mejorar la visualización de expanders */
        .stExpander > div:first-child { /* El título del expander */
            background-color: #f0f8ff; /* Azul pálido para el título */
            padding: 8px 15px;
            border-radius: 5px;
            font-weight: bold;
        }
        .stExpander[data-baseweb="expander"] div[data-testid="stExpanderContent"] {
            padding: 15px; /* Añadir padding interno al contenido expandido */
        }

        /* Para asegurar que los contenedores de columnas no se estiren demasiado en móvil si son muchos */
        @media (max-width: 768px) {
            .key-metrics-row {
                flex-direction: column; /* Apila las métricas en móvil */
                align-items: stretch;
            }
            .key-metric-item {
                margin: 5px 0; /* Espacio vertical entre métricas apiladas */
                min-width: unset;
            }
        }
    </style>
    """, unsafe_allow_html=True)

    # --- LADO IZQUIERDO (SIDEBAR) ---
    st.sidebar.image("https://raw.githubusercontent.com/streamlit/docs/main/public/images/brand/streamlit-logo-secondary-colormark-darktext.svg", width=200)
    st.sidebar.title("⚙️ Configuración del Partido (OF)")
    main_match_id_str_input_of = st.sidebar.text_input(
        "🆔 ID Partido Principal:", value="2696131",
        help="Pega el ID numérico del partido que deseas analizar.", key="other_feature_match_id_input")
    analizar_button_of = st.sidebar.button("🚀 Analizar Partido (OF)", type="primary", use_container_width=True, key="other_feature_analizar_button")

    results_container = st.container()
    # Gestionar el driver de Selenium en el estado de la sesión para reutilizarlo
    if 'driver_other_feature' not in st.session_state:
        st.session_state.driver_other_feature = None

    if analizar_button_of:
        results_container.empty() # Limpiar resultados anteriores
        main_match_id_to_process_of = None
        if main_match_id_str_input_of:
            try:
                # Limpiar el ID: quitar espacios, letras, etc.
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
                st.error(f"❌ No se pudo obtener la página H2H para ID {main_match_id_to_process_of}. Inténtalo de nuevo más tarde."); st.stop()

            # Extraer información básica del partido
            mp_home_id_of, mp_away_id_of, mp_league_id_of, mp_home_name_from_script, mp_away_name_from_script, mp_league_name_of = get_team_league_info_from_script_of(soup_main_h2h_page_of)
            
            # Obtener datos de clasificación para ambos equipos
            home_team_main_standings = extract_standings_data_from_h2h_page_of(soup_main_h2h_page_of, mp_home_name_from_script)
            away_team_main_standings = extract_standings_data_from_h2h_page_of(soup_main_h2h_page_of, mp_away_name_from_script)
            
            # Determinar nombres a mostrar, dando prioridad a los de la clasificación si están disponibles
            display_home_name = home_team_main_standings.get("name", "N/A") if home_team_main_standings.get("name") != "N/A" else mp_home_name_from_script or "Equipo Local"
            display_away_name = away_team_main_standings.get("name", "N/A") if away_team_main_standings.get("name") != "N/A" else mp_away_name_from_script or "Equipo Visitante"

            # --- CABECERA DEL PARTIDO ---
            with st.container():
                st.markdown("<div class='match-header-container'>", unsafe_allow_html=True)
                col_header_title, col_header_details = st.columns([2, 3]) # Dividir espacio para título y detalles
                
                with col_header_title:
                    st.markdown(f"<p class='main-title'>⚽ Análisis Partido</p>", unsafe_allow_html=True)
                
                with col_header_details:
                    st.markdown(f"<p class='sub-title'><strong>{display_home_name}</strong> vs <strong class='away-color'>{display_away_name}</strong></p>", unsafe_allow_html=True)
                    st.markdown(f"🏆 **Liga:** {mp_league_name_of or PLACEHOLDER_NODATA} | 🆔 **ID Partido:** <span class='data-highlight'>{main_match_id_to_process_of}</span>", unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)
            
            st.divider()

            # --- MÉTRICAS CLAVE DEL PARTIDO (EN FILA) ---
            st.markdown("<h2 class='section-header'>📊 Resumen Clave</h2>", unsafe_allow_html=True)
            
            # Preparar datos para métricas clave
            col_data = { "Fin": "?:?", "AH_Act": "?", "G_i": "?", "AH_H2H_V": "-", "Res_H2H_V": "?:?", "AH_H2H_G": "-", "Res_H2H_G": "?:?"}
            col_data["Fin"], _ = extract_final_score_of(soup_main_h2h_page_of)
            col_data["Fin"] = col_data["Fin"].replace("*",":") # Asegurar formato con ':'
            
            # Gestionar el driver de Selenium para obtener cuotas
            driver_actual_of = st.session_state.driver_other_feature
            driver_of_needs_init = driver_actual_of is None # Bandera para inicializar si no existe
            if not driver_of_needs_init:
                try: # Comprobar si el driver sigue conectado
                    _ = driver_actual_of.window_handles
                    if hasattr(driver_actual_of, 'service') and driver_actual_of.service and not driver_actual_of.service.is_connectable(): driver_of_needs_init = True
                except WebDriverException: driver_of_needs_init = True # Si hay excepción, el driver no está usable

            main_match_odds_data_of = {}
            if driver_of_needs_init:
                if driver_actual_of is not None: # Si existía pero está roto, cerrarlo
                    try: driver_actual_of.quit()
                    except: pass
                driver_actual_of = get_selenium_driver_of() # Obtener un nuevo driver
                st.session_state.driver_other_feature = driver_actual_of # Guardarlo en el estado

            if driver_actual_of: # Si tenemos un driver válido
                try:
                    driver_actual_of.get(f"{BASE_URL_OF}{main_page_url_h2h_view_of}")
                    # Esperar a que la sección de cuotas cargue para evitar errores
                    WebDriverWait(driver_actual_of, SELENIUM_TIMEOUT_SECONDS_OF).until(EC.presence_of_element_located((By.ID, "liveCompareDiv")))
                    time.sleep(0.8) # Pequeña pausa para asegurar carga completa de elementos en la página
                    main_match_odds_data_of = get_main_match_odds_selenium_of(driver_actual_of)
                except Exception as e_main_sel_of: 
                    st.warning(f"❗ No se pudieron cargar cuotas para el partido principal: {type(e_main_sel_of).__name__}.")
                    main_match_odds_data_of = {} # Asegurar que esté vacío si hay error
            else:
                st.warning("❗ WebDriver no disponible. Cuotas y otros datos dinámicos podrían faltar.")

            # Procesar cuotas y H2H para las métricas clave
            col_data["AH_Act"] = format_ah_as_decimal_string_of(main_match_odds_data_of.get('ah_linea_raw', '?'))
            col_data["G_i"] = format_ah_as_decimal_string_of(main_match_odds_data_of.get('goals_linea_raw', '?'))
            
            ah1_val, res1_val, _, match1_id_h2h_v, \
            ah6_val, res6_val, _, match6_id_h2h_g, \
            h2h_gen_home_name, h2h_gen_away_name = extract_h2h_data_of(soup_main_h2h_page_of, display_home_name, display_away_name, mp_league_id_of)
            
            col_data["AH_H2H_V"], col_data["Res_H2H_V"] = ah1_val, res1_val.replace("*",":") # Asegurar formato X:Y
            col_data["AH_H2H_G"], col_data["Res_H2H_G"] = ah6_val, res6_val.replace("*",":")

            # --- Renderizar las MÉTICAS CLAVE usando st.columns ---
            with st.container():
                with st.columns(4) as key_metrics_cols: # 4 columnas para 4 métricas clave
                    # --- Col 1: Marcador Final ---
                    with key_metrics_cols[0]:
                        final_score_display = col_data["Fin"] if col_data["Fin"] != "?:?" else PLACEHOLDER_NODATA
                        st.metric("🏁 Marcador Final", final_score_display)
                    
                    # --- Col 2: AH Principal (con cuotas) ---
                    with key_metrics_cols[1]:
                        ah_act_display = col_data["AH_Act"] if col_data["AH_Act"] != "?" else PLACEHOLDER_NODATA
                        home_odds_ah = main_match_odds_data_of.get('ah_home_cuota','-')
                        away_odds_ah = main_match_odds_data_of.get('ah_away_cuota','-')
                        # Mostrando línea AH y cuotas principales en la descripción de la métrica
                        st.metric("⚖️ AH Principal", ah_act_display, f"Casa: {home_odds_ah} / Fuera: {away_odds_ah}")
                        
                    # --- Col 3: Línea de Goles (con cuotas) ---
                    with key_metrics_cols[2]:
                        goals_line_display = col_data["G_i"] if col_data["G_i"] != "?" else PLACEHOLDER_NODATA
                        over_odds_goals = main_match_odds_data_of.get('goals_over_cuota','-')
                        under_odds_goals = main_match_odds_data_of.get('goals_under_cuota','-')
                        st.metric("🥅 Goles (Línea)", goals_line_display, f"Más: {over_odds_goals} / Menos: {under_odds_goals}")
                        
                    # --- Col 4: H2H General Resumen ---
                    with key_metrics_cols[3]:
                        h2h_res_general = col_data["Res_H2H_G"] if col_data["Res_H2H_G"] != '?:?' else PLACEHOLDER_NODATA
                        st.metric("🆚 H2H G. Res.", h2h_res_general, col_data["AH_H2H_G"] if col_data["AH_H2H_G"] != '-' else "AH: -")
            
            st.divider()

            # --- SECCIÓN DE CONTEXTO: CLASIFICACIÓN Y FORMA RECIENTE ---
            st.markdown("<h2 class='section-header'>🌍 Contexto del Partido</h2>", unsafe_allow_html=True)
            
            col_context_1, col_context_2 = st.columns(2) # Columnas para clasificación y forma reciente

            # --- Columna 1: Clasificación ---
            with col_context_1:
                st.markdown(f"<h3 class='card-title'><span class='home-color'>Clasificación {display_home_name}</span></h3>", unsafe_allow_html=True)
                display_standings_card(home_team_main_standings, display_home_name, "home-color")
                
                st.markdown(f"<h3 class='card-title'><span class='away-color'>Clasificación {display_away_name}</span></h3>", unsafe_allow_html=True)
                display_standings_card(away_team_main_standings, display_away_name, "away-color")

            # --- Columna 2: Forma Reciente ---
            with col_context_2:
                st.markdown(f"<h3 class='card-title'><span class='home-color'>Últ. {display_home_name} (Casa)</span></h3>", unsafe_allow_html=True)
                last_home_match_in_league_of = None
                # Extraer último partido de casa para el equipo local
                if mp_home_id_of and mp_league_id_of and display_home_name != "N/A":
                     last_home_match_in_league_of = extract_last_match_in_league_of(driver_actual_of, "table_v1", display_home_name, mp_league_id_of, "input#cb_sos1[value='1']", True)
                
                if last_home_match_in_league_of:
                    res = last_home_match_in_league_of
                    st.markdown(f"<div style='margin-top: 8px; margin-bottom: 8px;'><span class='home-color'>{res['home_team']}</span> <span class='score-value'>{res['score'].replace('-',':')}</span> <span class='away-color'>{res['away_team']}</span></div>", unsafe_allow_html=True)
                    formatted_ah_lh = format_ah_as_decimal_string_of(res.get('handicap_line_raw','-'))
                    st.markdown(f"**AH:** <span class='ah-value'>{formatted_ah_lh if formatted_ah_lh != '-' else PLACEHOLDER_NODATA}</span>", unsafe_allow_html=True)
                    st.caption(f"📅 {res.get('date', 'N/A')}")
                else: st.info(f"No se encontró último partido en casa para {display_home_name}.")

                st.markdown(f"<h3 class='card-title'><span class='away-color'>Últ. {display_away_name} (Fuera)</span></h3>", unsafe_allow_html=True)
                last_away_match_in_league_of = None
                # Extraer último partido de visita para el equipo visitante
                if mp_away_id_of and mp_league_id_of and display_away_name != "N/A":
                    last_away_match_in_league_of = extract_last_match_in_league_of(driver_actual_of, "table_v2", display_away_name, mp_league_id_of, "input#cb_sos2[value='2']", False)
                
                if last_away_match_in_league_of:
                    res = last_away_match_in_league_of
                    st.markdown(f"<div style='margin-top: 8px; margin-bottom: 8px;'><span class='home-color'>{res['home_team']}</span> <span class='score-value'>{res['score'].replace('-',':')}</span> <span class='away-color'>{res['away_team']}</span></div>", unsafe_allow_html=True)
                    formatted_ah_la = format_ah_as_decimal_string_of(res.get('handicap_line_raw','-'))
                    st.markdown(f"**AH:** <span class='ah-value'>{formatted_ah_la if formatted_ah_la != '-' else PLACEHOLDER_NODATA}</span>", unsafe_allow_html=True)
                    st.caption(f"📅 {res.get('date', 'N/A')}")
                else: st.info(f"No se encontró último partido fuera para {display_away_name}.")
            
            st.divider()

            # --- DETALLES EN EXPANDERS (para no saturar la vista principal) ---
            
            # Expander 1: Cuotas, Marcador y Progresión Partido Principal
            with st.expander("⚖️ Cuotas, Marcador y Progresión Partido Principal", expanded=False):
                st.markdown(f"<h4 class='card-title'>Cuotas y Marcador Detallado</h4>", unsafe_allow_html=True)
                # Mostrar métricas principales de cuotas si están disponibles
                if main_match_odds_data_of:
                    st.metric("AH (Línea Inicial)", col_data["AH_Act"] if col_data["AH_Act"] != "?" else PLACEHOLDER_NODATA,
                              f"Casa: {main_match_odds_data_of.get('ah_home_cuota','-')} / Fuera: {main_match_odds_data_of.get('ah_away_cuota','-')}")
                    st.metric("Goles (Línea Inicial)", col_data["G_i"] if col_data["G_i"] != "?" else PLACEHOLDER_NODATA,
                              f"Más: {main_match_odds_data_of.get('goals_over_cuota','-')} / Menos: {main_match_odds_data_of.get('goals_under_cuota','-')}")
                else:
                    st.info("Cuotas no disponibles para el partido principal.")

                # Mostrar estadísticas de progresión si el partido ha finalizado
                if col_data["Fin"] != PLACEHOLDER_NODATA:
                    display_previous_match_progression_stats(
                        f"Progreso: {display_home_name} vs {display_away_name}",
                        str(main_match_id_to_process_of), display_home_name, display_away_name
                    )
                else:
                    st.caption("Estadísticas de progresión se mostrarán si el partido ha finalizado.")

            # Expander 2: Comparativas Indirectas
            with st.expander("🔁 Comparativas Indirectas (vs Rivales Recientes)", expanded=False):
                # Extraer datos para comparativas indirectas
                comp_data_L_vs_UV_A = None
                if last_away_match_in_league_of and display_home_name != "N/A" and last_away_match_in_league_of.get('home_team'):
                    comp_data_L_vs_UV_A = extract_comparative_match_of(soup_main_h2h_page_of, "table_v1", display_home_name, last_away_match_in_league_of.get('home_team'), mp_league_id_of, True)

                comp_data_V_vs_UL_H = None
                if last_home_match_in_league_of and display_away_name != "N/A" and last_home_match_in_league_of.get('away_team'):
                    comp_data_V_vs_UL_H = extract_comparative_match_of(soup_main_h2h_page_of, "table_v2", display_away_name, last_home_match_in_league_of.get('away_team'), mp_league_id_of, False)

                col_comp_1, col_comp_2 = st.columns(2)
                with col_comp_1:
                    st.markdown(f"<h5 class='card-subtitle'><span class='home-color'>{display_home_name}</span> vs. <span class='away-color'>Últ. Rival de {display_away_name}</span></h5>", unsafe_allow_html=True)
                    if comp_data_L_vs_UV_A:
                        data = comp_data_L_vs_UV_A
                        score_part = data.get('score','?:?').replace('*', ':').strip() # Asegurar formato score
                        ah_val = data.get('ah_line', '-')
                        loc_val = data.get('localia', '-')
                        st.markdown(f"⚽ **Res:** <span class='data-highlight'>{score_part or PLACEHOLDER_NODATA}</span> ({data.get('home_team')} vs {data.get('away_team')})", unsafe_allow_html=True)
                        st.markdown(f"⚖️ **AH:** <span class='ah-value'>{format_ah_as_decimal_string_of(ah_val) or PLACEHOLDER_NODATA}</span>", unsafe_allow_html=True)
                        st.markdown(f"🏟️ **Localía de '{display_home_name}':** <span class='data-highlight'>{loc_val or PLACEHOLDER_NODATA}</span>", unsafe_allow_html=True)
                        # Mostrar progreso para esta comparativa si el partido tiene ID
                        display_previous_match_progression_stats(
                            f"Comp: {data.get('home_team','L')} vs {data.get('away_team','V')}",
                            data.get('match_id'), data.get('home_team','Local'), data.get('away_team','Visitante')
                        )
                    else: st.info(f"Comparativa '{display_home_name} vs Últ. Rival de {display_away_name}' no disponible.")

                with col_comp_2:
                    st.markdown(f"<h5 class='card-subtitle'><span class='away-color'>{display_away_name}</span> vs. <span class='home-color'>Últ. Rival de {display_home_name}</span></h5>", unsafe_allow_html=True)
                    if comp_data_V_vs_UL_H:
                        data = comp_data_V_vs_UL_H
                        score_part = data.get('score','?:?').replace('*', ':').strip() # Asegurar formato score
                        ah_val = data.get('ah_line', '-')
                        loc_val = data.get('localia', '-')
                        st.markdown(f"⚽ **Res:** <span class='data-highlight'>{score_part or PLACEHOLDER_NODATA}</span> ({data.get('home_team')} vs {data.get('away_team')})", unsafe_allow_html=True)
                        st.markdown(f"⚖️ **AH:** <span class='ah-value'>{format_ah_as_decimal_string_of(ah_val) or PLACEHOLDER_NODATA}</span>", unsafe_allow_html=True)
                        st.markdown(f"🏟️ **Localía de '{display_away_name}':** <span class='data-highlight'>{loc_val or PLACEHOLDER_NODATA}</span>", unsafe_allow_html=True)
                        # Mostrar progreso para esta comparativa si el partido tiene ID
                        display_previous_match_progression_stats(
                            f"Comp: {data.get('home_team','L')} vs {data.get('away_team','V')}",
                            data.get('match_id'), data.get('home_team','Local'), data.get('away_team','Visitante')
                        )
                    else: st.info(f"Comparativa '{display_away_name} vs Últ. Rival de {display_home_name}' no disponible.")

            # Expander 3: H2H Directos
            with st.expander("🔰 Hándicaps y Resultados Clave (H2H Directos)", expanded=False):
                # Obtener IDs para H2H Col3 (rivales A y B)
                key_match_id_for_rival_a_h2h, rival_a_id_orig_col3, rival_a_name_orig_col3 = get_rival_a_for_original_h2h_of(main_match_id_to_process_of)
                match_id_rival_b_game_ref, rival_b_id_orig_col3, rival_b_name_orig_col3 = get_rival_b_for_original_h2h_of(main_match_id_to_process_of)

                # Extraer detalles del H2H de la Columna 3
                details_h2h_col3_of = {"status": "error", "resultado": PLACEHOLDER_NODATA}
                if key_match_id_for_rival_a_h2h and rival_a_id_orig_col3 and rival_b_id_orig_col3 and driver_actual_of:
                    details_h2h_col3_of = get_h2h_details_for_original_logic_of(driver_actual_of, key_match_id_for_rival_a_h2h, rival_a_id_orig_col3, rival_b_id_orig_col3, rival_a_name_orig_col3, rival_b_name_orig_col3)

                h2h_direct_col1, h2h_direct_col2 = st.columns(2) # Columnas para H2H directo y general
                with h2h_direct_col1:
                    st.markdown(f"<h5 class='card-subtitle'><span class='home-color'>{display_home_name}</span> (Cara a cara en casa)</h5>", unsafe_allow_html=True)
                    st.metric("AH H2H", col_data["AH_H2H_V"] if col_data["AH_H2H_V"] != '-' else PLACEHOLDER_NODATA)
                    st.metric("Res H2H", col_data["Res_H2H_V"] if col_data["Res_H2H_V"] != '?:?' else PLACEHOLDER_NODATA)
                    if match1_id_h2h_v: # Si se encontró ID de partido
                        display_previous_match_progression_stats(
                            f"H2H Directo: {display_home_name} vs {display_away_name}",
                            match1_id_h2h_v, display_home_name, display_away_name
                        )
                    else: st.info("No hay H2H directo específico para este enfrentamiento en casa.")

                with h2h_direct_col2:
                    st.markdown(f"<h5 class='card-subtitle'><span class='home-color'>H2H General</span> ({h2h_gen_home_name} vs {h2h_gen_away_name})</h5>", unsafe_allow_html=True)
                    st.metric("AH H2H G.", col_data["AH_H2H_G"] if col_data["AH_H2H_G"] != '-' else PLACEHOLDER_NODATA)
                    st.metric("Res H2H G.", col_data["Res_H2H_G"] if col_data["Res_H2H_G"] != '?:?' else PLACEHOLDER_NODATA)
                    if match6_id_h2h_g: # Si se encontró ID de partido
                        display_previous_match_progression_stats(
                            f"H2H General: {h2h_gen_home_name} vs {h2h_gen_away_name}",
                            match6_id_h2h_g, h2h_gen_home_name, h2h_gen_away_name
                        )
                    else: st.info("No hay datos H2H generales disponibles.")
            
            st.divider()

            # --- Sección de Estadísticas de Progresión (solo si el partido ha finalizado) ---
            if col_data["Fin"] != PLACEHOLDER_NODATA:
                st.markdown("<h2 class='section-header'>⚡ Estadísticas de Progresión (Partido Finalizado)</h2>", unsafe_allow_html=True)
                display_previous_match_progression_stats(
                    f"Progreso: {display_home_name} vs {display_away_name}",
                    str(main_match_id_to_process_of), display_home_name, display_away_name
                )
            else:
                 st.info("Las estadísticas de progresión solo están disponibles para partidos finalizados.")

            # Mensaje de éxito en la barra lateral
            end_time_of = time.time()
            st.sidebar.success(f"🎉 Análisis completado en {end_time_of - start_time_of:.2f} segundos.")
            
    else: # Mensaje inicial si no se ha presionado el botón de analizar
        results_container.info("✨ ¡Bienvenido! Ingresa un ID de partido y haz clic en 'Analizar Partido (OF)'.")

# Bloque principal para ejecutar la aplicación
if __name__ == '__main__':
    display_other_feature_ui()
