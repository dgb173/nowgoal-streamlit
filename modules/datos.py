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
PLACEHOLDER_NODATA = "*-*"

# --- FUNCIONES DE PARSEO Y OBTENCIÓN DE DATOS (NO REQUIEREN CAMBIOS) ---
# (Tu código original de fetching y parsing está correcto y se mantiene)
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

@st.cache_data(ttl=7200)
def get_match_progression_stats_data(match_id: str) -> pd.DataFrame | None:
    base_url_live = "https://live18.nowgoal25.com/match/live-"
    full_url = f"{base_url_live}{match_id}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36"}
    stat_titles_of_interest = {"Shots": {"Home": "-", "Away": "-"}, "Shots on Goal": {"Home": "-", "Away": "-"}, "Attacks": {"Home": "-", "Away": "-"}, "Dangerous Attacks": {"Home": "-", "Away": "-"},}
    try:
        response = requests.get(full_url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'lxml')
        team_tech_div = soup.find('div', id='teamTechDiv_detail')
        if team_tech_div and (stat_list := team_tech_div.find('ul', class_='stat')):
            for li in stat_list.find_all('li'):
                if (title_span := li.find('span', class_='stat-title')) and (stat_title := title_span.get_text(strip=True)) in stat_titles_of_interest:
                    if (values := li.find_all('span', class_='stat-c')) and len(values) == 2:
                        stat_titles_of_interest[stat_title]["Home"] = values[0].get_text(strip=True)
                        stat_titles_of_interest[stat_title]["Away"] = values[1].get_text(strip=True)
    except: return None
    df = pd.DataFrame([{"Estadistica_EN": name, "Casa": vals['Home'], "Fuera": vals['Away']} for name, vals in stat_titles_of_interest.items()])
    return df.set_index("Estadistica_EN") if not df.empty else df

# (El resto de tus funciones de get/extract/fetch van aquí, sin cambios)
# ...
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
    options.add_argument("--disable-dev-shm-usage"); options.add_argument("--disable-gpu"); options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36"); options.add_argument('--blink-settings=imagesEnabled=false'); options.add_argument("--window-size=1920,1080")
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
        links = row.find_all("a", onclick=True)
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
            return {"status": "found", "goles_home": g_h.strip(), "goles_away": g_a.strip(),"handicap": handicap_raw, "rol_rival_a": rol_a_in_this_h2h, "h2h_home_team_name": links[0].text.strip(), "h2h_away_team_name": links[1].text.strip(), "match_id": match_id_h2h_rivals}
    return {"status": "not_found", "resultado": f"H2H directo no encontrado para {rival_a_name} vs {rival_b_name} en historial (table_v2) de la página de ref. ({key_match_id_for_h2h_url})."}
def get_team_league_info_from_script_of(soup):
    home_id, away_id, league_id, home_name, away_name, league_name = (None,)*3 + ("N/A",)*3
    script_tag = soup.find("script", string=re.compile(r"var _matchInfo ="))
    if script_tag and script_tag.string:
        script_content = script_tag.string
        h_id_m = re.search(r"hId:\s*parseInt\('(\d+)'\)", script_content); g_id_m = re.search(r"gId:\s*parseInt\('(\d+)'\)", script_content); sclass_id_m = re.search(r"sclassId:\s*parseInt\('(\d+)'\)", script_content); h_name_m = re.search(r"hName:\s*'([^']*)'", script_content); g_name_m = re.search(r"gName:\s*'([^']*)'", script_content); l_name_m = re.search(r"lName:\s*'([^']*)'", script_content)
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
        for row in table.find_all("tr", id=re.compile(rf"tr{table_css_id_str[-1]}_\d+")):
            if row.get("style") and "display:none" in row.get("style","").lower(): continue
            if league_id_filter_value and row.get("name") != str(league_id_filter_value): continue
            home_team_row_el = row.select_one("td:nth-of-type(3) a"); away_team_row_el = row.select_one("td:nth-of-type(5) a")
            if not home_team_row_el or not away_team_row_el: continue
            home_team_row_name = home_team_row_el.text.strip(); away_team_row_name = away_team_row_el.text.strip()
            if (is_home_game_filter and main_team_name_in_table.lower() == home_team_row_name.lower()) or \
               (not is_home_game_filter and main_team_name_in_table.lower() == away_team_row_name.lower()):
                date = (row.select_one("span[name='timeData']") or {}).text or "N/A"
                score = (row.select_one("span[class*='fscore_']") or {}).text or "N/A"
                handicap_cell = row.select_one("td:nth-of-type(12)"); handicap_raw = (handicap_cell.get("data-o", "") or handicap_cell.text).strip() or "N/A"
                return {"date": date, "home_team": home_team_row_name, "away_team": away_team_row_name, "score": score, "handicap_line_raw": handicap_raw, "match_id": row.get('index')}
        return None
    except Exception: return None
def get_main_match_odds_selenium_of(driver):
    odds_info = {"ah_home_cuota": "N/A", "ah_linea_raw": "N/A", "ah_away_cuota": "N/A", "goals_over_cuota": "N/A", "goals_linea_raw": "N/A", "goals_under_cuota": "N/A"}
    try:
        WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS_OF).until(EC.presence_of_element_located((By.ID, "liveCompareDiv")))
        for selector in ["tr#tr_o_1_8[name='earlyOdds']", "tr#tr_o_1_31[name='earlyOdds']"]:
            try:
                row = WebDriverWait(driver, 3).until(EC.visibility_of_element_located((By.CSS_SELECTOR, selector)))
                tds = row.find_elements(By.TAG_NAME, "td")
                if len(tds) >= 11:
                    odds_info.update({
                        "ah_home_cuota": tds[2].get_attribute("data-o") or tds[2].text.strip(), "ah_linea_raw": tds[3].get_attribute("data-o") or tds[3].text.strip(), "ah_away_cuota": tds[4].get_attribute("data-o") or tds[4].text.strip(),
                        "goals_over_cuota": tds[8].get_attribute("data-o") or tds[8].text.strip(), "goals_linea_raw": tds[9].get_attribute("data-o") or tds[9].text.strip(), "goals_under_cuota": tds[10].get_attribute("data-o") or tds[10].text.strip()
                    })
                    return odds_info
            except TimeoutException: continue
    except Exception: pass
    return odds_info
def extract_standings_data_from_h2h_page_of(h2h_soup, target_team_name_exact):
    data = {"name": target_team_name_exact, "ranking": "N/A", "total_pj": "N/A", "total_v": "N/A", "total_e": "N/A", "total_d": "N/A", "total_gf": "N/A", "total_gc": "N/A", "specific_pj": "N/A", "specific_v": "N/A", "specific_e": "N/A", "specific_d": "N/A", "specific_gf": "N/A", "specific_gc": "N/A", "specific_type": "N/A"}
    if not h2h_soup or not target_team_name_exact: return data
    standings_section = h2h_soup.find("div", id="porletP4")
    if not standings_section: return data
    for div_class, specific_type_name in [("home-div", "Local"), ("guest-div", "Visitante")]:
        team_div = standings_section.find("div", class_=div_class)
        if team_div and target_team_name_exact.lower() in team_div.get_text().lower():
            team_table_soup = team_div.find("table")
            data["specific_type"] = specific_type_name
            header_link = team_table_soup.find("tr", class_=re.compile(r"team-(home|guest)")).find("a")
            if header_link:
                full_text = header_link.get_text(separator=" ", strip=True)
                if (name_match := re.search(r"]\s*(.*)", full_text)): data["name"] = name_match.group(1).strip()
                if (rank_match := re.search(r"\[(?:[^\]]+-)?(\d+)\]", full_text)): data["ranking"] = rank_match.group(1)
            in_ft_section = False
            for row in team_table_soup.find_all("tr", align="center"):
                if (th := row.find("th")):
                    in_ft_section = "FT" in th.get_text()
                    continue
                if in_ft_section and (cells := row.find_all("td")) and len(cells) >= 7:
                    stats = [c.get_text(strip=True) or "N/A" for c in cells[1:7]]
                    row_type = (cells[0].find("span") or cells[0]).get_text(strip=True)
                    if row_type == "Total": data.update(zip(["total_pj", "total_v", "total_e", "total_d", "total_gf", "total_gc"], stats))
                    elif row_type in ["Home", "Away"]: data.update(zip(["specific_pj", "specific_v", "specific_e", "specific_d", "specific_gf", "specific_gc"], stats))
            return data
    return data
def extract_final_score_of(soup):
    try:
        if (score_divs := soup.select('#mScore .end .score')) and len(score_divs) == 2 and score_divs[0].text.strip().isdigit() and score_divs[1].text.strip().isdigit():
            return f"{score_divs[0].text.strip()}:{score_divs[1].text.strip()}", f"{score_divs[0].text.strip()}-{score_divs[1].text.strip()}"
    except Exception: pass
    return '?:?', "?-?"
def extract_h2h_data_of(soup, main_home_team_name, main_away_team_name, current_league_id):
    results = {'ah1': '-', 'res1': '?:?', 'match1_id': None, 'ah6': '-', 'res6': '?:?', 'match6_id': None, 'h2h_gen_home_name': "Local", 'h2h_gen_away_name': "Visitante"}
    h2h_table = soup.find("table", id="table_v3")
    if not h2h_table or not main_home_team_name or not main_away_team_name: return results.values()
    filtered_h2h_list = [d for r in h2h_table.find_all("tr", id=re.compile(r"tr3_\d+")) if (d := get_match_details_from_row_of(r, 'fscore_3')) and (not current_league_id or d.get('league_id_hist') == str(current_league_id))]
    if not filtered_h2h_list: return results.values()
    h2h_gen = filtered_h2h_list[0]
    results.update({'ah6': h2h_gen.get('ahLine', '-'), 'res6': h2h_gen.get('score', '?:?'), 'match6_id': h2h_gen.get('matchIndex'), 'h2h_gen_home_name': h2h_gen.get('home'), 'h2h_gen_away_name': h2h_gen.get('away')})
    for d in filtered_h2h_list:
        if d.get('home','').lower() == main_home_team_name.lower() and d.get('away','').lower() == main_away_team_name.lower():
            results.update({'ah1': d.get('ahLine', '-'), 'res1': d.get('score', '?:?'), 'match1_id': d.get('matchIndex')}); break
    return results['ah1'], results['res1'], "", results['match1_id'], results['ah6'], results['res6'], "", results['match6_id'], results['h2h_gen_home_name'], results['h2h_gen_away_name']
def extract_comparative_match_of(soup_for_team_history, table_id, team_name, opponent_name, league_id, is_home_table):
    if not opponent_name or opponent_name == "N/A" or not team_name: return None
    if not (table := soup_for_team_history.find("table", id=table_id)): return None
    score_class = 'fscore_1' if is_home_table else 'fscore_2'
    for row in table.find_all("tr", id=re.compile(rf"tr{table_id[-1]}_\d+")):
        if (details := get_match_details_from_row_of(row, score_class)) and (not league_id or details.get('league_id_hist') == str(league_id)):
            if {details.get('home','').lower(), details.get('away','').lower()} == {team_name.lower(), opponent_name.lower()}:
                return {"score": details.get('score'), "ah_line": details.get('ahLine'), "localia": 'H' if team_name.lower() == details.get('home','').lower() else 'A', "home_team": details.get('home'), "away_team": details.get('away'), "match_id": details.get('matchIndex')}
    return None

# --- INICIO DE LAS NUEVAS FUNCIONES DE VISUALIZACIÓN (CORREGIDAS) ---

def get_custom_css():
    """Devuelve el bloque de CSS para el nuevo diseño del dashboard."""
    return """
    <style>
        :root { --home-color: #007bff; --away-color: #fd7e14; --neutral-color: #6c757d; --win-color: #28a745; --lose-color: #dc3545; --bg-color: #f8f9fa; --border-color: #dee2e6; }
        .data-card { background-color: var(--bg-color); border: 1px solid var(--border-color); border-radius: 8px; padding: 12px; margin-bottom: 12px; height: 100%; }
        .data-card h3 { font-size: 1.1em; margin-top: 0; margin-bottom: 8px; padding-bottom: 5px; border-bottom: 2px solid var(--border-color); display: flex; align-items: center; }
        .data-card h3 .icon { margin-right: 8px; }
        .data-card p { font-size: 0.9em; margin: 0 0 4px 0; line-height: 1.4; }
        .stats-table { width: 100%; border-collapse: collapse; }
        .stats-table th, .stats-table td { font-size: 0.85em; padding: 4px 2px; text-align: center; border-bottom: 1px solid #eee; }
        .stats-table .stat-name { text-align: left; font-weight: bold; }
        .stats-table .bar-container { width: 100%; height: 12px; background-color: #e9ecef; border-radius: 3px; overflow: hidden; border: 1px solid #ccc; }
        .stats-table .bar { height: 100%; background-color: var(--home-color); }
        .stats-table .home-val, .stats-table .away-val { font-weight: bold; width: 20px; }
        .home-color { color: var(--home-color); } .away-color { color: var(--away-color); } .score-value { font-size: 1.1em; font-weight: bold; margin: 0 5px; color: #333; } .ah-value { font-weight: bold; color: #6f42c1; }
        .match-header { text-align: center; margin-bottom: 1rem; }
        .match-header .team-name { font-size: 1.8em; font-weight: bold; }
        .match-header .vs { font-size: 1.5em; color: var(--neutral-color); margin: 0 1rem; }
        .match-header .league-info { font-size: 0.9em; color: var(--neutral-color); margin-top: -5px; }
    </style>
    """

def display_progression_stats_card(title: str, stats_df: pd.DataFrame, home_team_name: str, away_team_name: str):
    """Muestra una tarjeta con las estadísticas de progresión y las barras de comparación."""
    with st.container():
        st.markdown('<div class="data-card">', unsafe_allow_html=True)
        if stats_df is None or stats_df.empty:
            st.markdown(f"**📊 {title}**\n- _No hay datos de progresión disponibles._", unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)
            return

        st.markdown(f"**📊 {title}**", unsafe_allow_html=True)
        html = f"<table class='stats-table'><tr><th class='stat-name'>Est.</th><th class='home-val'>{home_team_name[:3]}</th><th>Dominio</th><th class='away-val'>{away_team_name[:3]}</th></tr>"
        ordered_stats_display = {"Shots": "Disparos", "Shots on Goal": "A Puerta", "Attacks": "Ataques", "Dangerous Attacks": "Peligrosos"}
        
        for stat_key_en, stat_name_es in ordered_stats_display.items():
            if stat_key_en in stats_df.index:
                home_val_str, away_val_str = stats_df.loc[stat_key_en, 'Casa'], stats_df.loc[stat_key_en, 'Fuera']
                home_val, away_val = (int(v) if v.isdigit() else 0 for v in [home_val_str, away_val_str])
                home_perc = (home_val / (home_val + away_val) * 100) if (home_val + away_val) > 0 else 50
                home_color, away_color = ("var(--win-color)", "var(--lose-color)") if home_val > away_val else (("var(--lose-color)", "var(--win-color)") if away_val > home_val else ("#333", "#333"))
                html += f"<tr><td class='stat-name'>{stat_name_es}</td><td class='home-val' style='color:{home_color}'>{home_val_str}</td><td><div class='bar-container'><div class='bar' style='width: {home_perc}%;'></div></div></td><td class='away-val' style='color:{away_color}'>{away_val_str}</td></tr>"
        html += "</table>"
        st.markdown(html, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)


def display_team_card(team_standings_data, last_match_data, is_home_team):
    """Muestra una tarjeta completa para un equipo (local o visitante)."""
    team_color_class = "home-color" if is_home_team else "away-color"
    team_display_name = team_standings_data.get("name", "Equipo")
    
    st.markdown(f"""
    <div class="data-card">
        <h3><span class="{team_color_class}">{team_display_name}</span></h3>
        <p><b>📈 Ranking:</b> {team_standings_data.get('ranking', PLACEHOLDER_NODATA)}</p>
        <hr style="margin: 5px 0;">
        <p><b>Clasificación (Total):</b><br>PJ: {team_standings_data.get('total_pj', '-')} | V-E-D: {team_standings_data.get('total_v', '-')}-{team_standings_data.get('total_e', '-')}-{team_standings_data.get('total_d', '-')} | GF:GC: {team_standings_data.get('total_gf', '-')}:{team_standings_data.get('total_gc', '-')}</p>
        <br>
        <p><b>Clasificación ({team_standings_data.get('specific_type', 'Específica')}):</b><br>PJ: {team_standings_data.get('specific_pj', '-')} | V-E-D: {team_standings_data.get('specific_v', '-')}-{team_standings_data.get('specific_e', '-')}-{team_standings_data.get('specific_d', '-')} | GF:GC: {team_standings_data.get('specific_gf', '-')}:{team_standings_data.get('specific_gc', '-')}</p>
        <hr style="margin: 10px 0;">
        <p><b>⚡ Último Partido (Liga, {team_standings_data.get('specific_type', 'Específica')}):</b></p>
    </div>
    """, unsafe_allow_html=True)
    
    if last_match_data:
        res = last_match_data
        opponent_name = res['away_team'] if is_home_team else res['home_team']
        opponent_color = "away-color" if is_home_team else "home-color"
        st.markdown(f"""
        <div style="font-size:0.9em; margin-top:-28px; padding: 0 12px;">
            <p>vs <span class="{opponent_color}">{opponent_name}</span></p>
            <p><span class="home-color">{res['home_team']}</span> <span class="score-value">{res['score'].replace('-',':')}</span> <span class="away-color">{res['away_team']}</span></p>
            <p><b>AH:</b> <span class="ah-value">{format_ah_as_decimal_string_of(res.get('handicap_line_raw','-'))}</span> | 📅 {res.get('date', 'N/A')}</p>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"<div style='font-size:0.9em; margin-top:-28px; padding: 0 12px;'><p>_No se encontró último partido._</p></div>", unsafe_allow_html=True)

# --- FUNCIÓN PRINCIPAL DE LA UI (TOTALMENTE REESCRITA Y CORREGIDA) ---
def display_other_feature_ui():
    st.sidebar.image("https://raw.githubusercontent.com/streamlit/docs/main/public/images/brand/streamlit-logo-secondary-colormark-darktext.svg", width=200)
    st.sidebar.title("⚙️ Configuración del Partido")
    main_match_id_str_input_of = st.sidebar.text_input("🆔 ID Partido Principal:", value="2696131", help="Pega el ID numérico del partido.", key="of_id_input")
    analizar_button_of = st.sidebar.button("🚀 Analizar Partido", type="primary", use_container_width=True, key="of_analizar_button")

    if 'driver_other_feature' not in st.session_state: st.session_state.driver_other_feature = None

    if not analizar_button_of:
        st.info("✨ ¡Bienvenido! Ingresa un ID de partido y haz clic en 'Analizar Partido'.")
        return

    main_match_id_to_process_of = int("".join(filter(str.isdigit, main_match_id_str_input_of))) if main_match_id_str_input_of.isdigit() else None
    if not main_match_id_to_process_of:
        st.error("⚠️ El ID de partido ingresado no es válido."); st.stop()

    start_time_of = time.time()
    with st.spinner("🔄 Cargando y analizando todos los datos..."):
        # --- OBTENCIÓN DE DATOS ---
        soup_main = fetch_soup_requests_of(f"/match/h2h-{main_match_id_to_process_of}")
        if not soup_main: st.error("❌ No se pudo obtener la página H2H."); st.stop()

        mp_ids_names = get_team_league_info_from_script_of(soup_main)
        home_standings = extract_standings_data_from_h2h_page_of(soup_main, mp_ids_names[3])
        away_standings = extract_standings_data_from_h2h_page_of(soup_main, mp_ids_names[4])
        display_home_name, display_away_name = home_standings.get("name"), away_standings.get("name")

        rival_a_info = get_rival_a_for_original_h2h_of(main_match_id_to_process_of) or (None, None, None)
        rival_b_info = get_rival_b_for_original_h2h_of(main_match_id_to_process_of) or (None, None, None)

        if st.session_state.driver_other_feature is None or not st.session_state.driver_other_feature.service.is_connectable():
            if st.session_state.driver_other_feature: st.session_state.driver_other_feature.quit()
            st.session_state.driver_other_feature = get_selenium_driver_of()
        
        odds, last_home_match, last_away_match, h2h_rivals = {}, None, None, {}
        if driver := st.session_state.driver_other_feature:
            try:
                driver.get(f"{BASE_URL_OF}/match/h2h-{main_match_id_to_process_of}")
                WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.ID, "table_v1")))
                odds = get_main_match_odds_selenium_of(driver)
                last_home_match = extract_last_match_in_league_of(driver, "table_v1", display_home_name, mp_ids_names[2], "input#cb_sos1[value='1']", True)
                last_away_match = extract_last_match_in_league_of(driver, "table_v2", display_away_name, mp_ids_names[2], "input#cb_sos2[value='2']", False)
                if all(rival_a_info) and all(rival_b_info):
                    h2h_rivals = get_h2h_details_for_original_logic_of(driver, rival_a_info[0], rival_a_info[1], rival_b_info[1], rival_a_info[2], rival_b_info[2])
            except Exception as e: st.warning(f"❗ Error Selenium: {e}")
        else: st.warning("❗ WebDriver no disponible. Algunos datos faltarán.")

        h2h_data = extract_h2h_data_of(soup_main, display_home_name, display_away_name, mp_ids_names[2])
        final_score, _ = extract_final_score_of(soup_main)

        # --- RENDERIZACIÓN DEL DASHBOARD ---
        st.markdown(get_custom_css(), unsafe_allow_html=True)
        st.markdown(f"""
        <div class="match-header">
            <div><span class="team-name home-color">{display_home_name}</span><span class="vs">vs</span><span class="team-name away-color">{display_away_name}</span></div>
            <div class="league-info">🏆 {mp_ids_names[5]} (ID: {mp_ids_names[2]}) | 🆔 Partido: {main_match_id_to_process_of}</div>
        </div>
        """, unsafe_allow_html=True)
        
        col_home, col_center, col_away = st.columns([2.5, 1.7, 2.5], gap="medium")

        with col_home: display_team_card(home_standings, last_home_match, True)
        with col_away: display_team_card(away_standings, last_away_match, False)
        
        with col_center:
            st.markdown('<div class="data-card"><h3><span class="icon">⚖️</span>Cuotas / H2H</h3>' +
                f"<p><b>🏁 Final:</b> <span class='score-value'>{final_score if final_score != '?:?' else 'Pendiente'}</span></p>" +
                f"<p><b>AH Inicial:</b> <span class='ah-value'>{format_ah_as_decimal_string_of(odds.get('ah_linea_raw', '?'))}</span></p>" +
                f"<p><b>Goles Inicial:</b> <span class='ah-value'>{format_ah_as_decimal_string_of(odds.get('goals_linea_raw', '?'))}</span></p>" +
                '<hr style="margin: 5px 0;">' +
                f"<p><b>H2H (Local en casa):</b><br>{h2h_data[1] if h2h_data[1]!='?:?' else '-'} | AH: <span class='ah-value'>{h2h_data[0] if h2h_data[0]!='-' else '-'}</span></p>" +
                f"<p><b>H2H (Último General):</b><br>{h2h_data[5] if h2h_data[5]!='?:?' else '-'} | AH: <span class='ah-value'>{h2h_data[4] if h2h_data[4]!='-' else '-'}</span></p>" +
                '<hr style="margin: 10px 0;"><h3><span class="icon">🔀</span>H2H Rivales</h3>', unsafe_allow_html=True)
            if h2h_rivals.get("status") == "found":
                st.markdown(f"<p><span class='home-color'>{h2h_rivals.get('h2h_home_team_name')}</span> <b class='score_value'>{h2h_rivals.get('goles_home', '?')}:{h2h_rivals.get('goles_away', '?')}</b> <span class='away-color'>{h2h_rivals.get('h2h_away_team_name')}</span></p>" +
                            f"<p><b>AH:</b> <span class='ah-value'>{format_ah_as_decimal_string_of(h2h_rivals.get('handicap','-'))}</span></p>", unsafe_allow_html=True)
            else:
                st.markdown(f"<p style='font-size:0.8em'>_No encontrado._</p>", unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

        st.divider()
        st.markdown("<h2 style='text-align:center; font-size:1.5em; margin-bottom:1rem;'>⚡ Análisis Comparativo de Estadísticas de Progresión</h2>", unsafe_allow_html=True)
        
        s_col1, s_col2, s_col3 = st.columns(3)
        with s_col1:
            df = get_match_progression_stats_data(last_home_match['match_id']) if last_home_match else None
            display_progression_stats_card(f"Últ. {display_home_name} (C)", df, (last_home_match or {}).get('home_team', 'L'), (last_home_match or {}).get('away_team', 'V'))
        with s_col2:
            df = get_match_progression_stats_data(last_away_match['match_id']) if last_away_match else None
            display_progression_stats_card(f"Últ. {display_away_name} (F)", df, (last_away_match or {}).get('home_team', 'L'), (last_away_match or {}).get('away_team', 'V'))
        with s_col3:
            df = get_match_progression_stats_data(h2h_rivals['match_id']) if h2h_rivals.get("status") == "found" else None
            display_progression_stats_card("H2H Rivales", df, (h2h_rivals or {}).get('h2h_home_team_name', 'L'), (h2h_rivals or {}).get('h2h_away_team_name', 'V'))

        st.sidebar.success(f"🎉 Análisis completado en {time.time() - start_time_of:.2f} s.")

if __name__ == '__main__':
    st.set_page_config(layout="wide", page_title="Análisis de Partidos", initial_sidebar_state="expanded")
    display_other_feature_ui()
