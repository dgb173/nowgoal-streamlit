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
PLACEHOLDER_NODATA = "--"

# --- FUNCIONES DE PARSEO Y OBTENCIÓN DE DATOS (NO REQUIEREN CAMBIOS) ---
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
    if not match_id or not match_id.isdigit(): return None
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

# --- NUEVAS FUNCIONES DE VISUALIZACIÓN (CORREGIDAS Y COMPLETAS) ---

def get_clarity_css():
    """CSS enfocado en claridad, espaciado y legibilidad."""
    return """
    <style>
        :root { --home-color: #007bff; --away-color: #ff6347; --neutral-color: #6c757d; --bg-light: #f8f9fa; --border-color: #dee2e6; --text-dark: #212529; --text-light: #495057; }
        .section-container { background-color: var(--bg-light); border: 1px solid var(--border-color); border-radius: 8px; padding: 16px; margin-bottom: 20px; }
        .section-header { font-size: 1.5em; font-weight: bold; color: var(--text-dark); margin-bottom: 16px; border-bottom: 2px solid var(--home-color); padding-bottom: 8px; }
        .team-name-header { font-size: 1.2em; font-weight: bold; margin-bottom: 10px; }
        .home-color { color: var(--home-color); } .away-color { color: var(--away-color); }
        .ah-value { font-weight: 600; color: #6f42c1; }
        table.stats-table { width: 100%; border-collapse: collapse; }
        table.stats-table th, table.stats-table td { padding: 10px 8px; text-align: left; border-bottom: 1px solid var(--border-color); font-size: 0.95em; vertical-align: middle; }
        table.stats-table th { font-weight: bold; background-color: #e9ecef; }
        table.stats-table td.center-text { text-align: center; }
        table.stats-table .stat-value { font-weight: 600; font-size: 1.1em; }
        .standings-block p { margin: 0 0 5px 0; font-size: 0.95em; }
        .standings-block b { min-width: 60px; display: inline-block; }
        .main-header { text-align: center; margin-bottom: 24px; }
        .main-header .teams { font-size: 2.2em; font-weight: bold; }
        .main-header .league { font-size: 1em; color: var(--neutral-color); }
        .expander-subheader { font-size: 1.1em; font-weight: bold; color: #333; margin-top: 15px; margin-bottom: 5px;}
    </style>
    """

def display_standings_card(team_standings_data):
    rank = team_standings_data.get('ranking', PLACEHOLDER_NODATA)
    st.markdown(f"#### Clasificación (Rank: {rank})")
    st.markdown(f"""
    <div class='standings-block'>
        <p><b>Total:</b> PJ:{team_standings_data.get('total_pj', '-')} | V-E-D: {team_standings_data.get('total_v', '-')}-{team_standings_data.get('total_e', '-')}-{team_standings_data.get('total_d', '-')} | GF:GC: {team_standings_data.get('total_gf', '-')}:{team_standings_data.get('total_gc', '-')}</p>
        <p><b>{team_standings_data.get('specific_type', 'Específico')}:</b> PJ:{team_standings_data.get('specific_pj', '-')} | V-E-D: {team_standings_data.get('specific_v', '-')}-{team_standings_data.get('specific_e', '-')}-{team_standings_data.get('specific_d', '-')} | GF:GC: {team_standings_data.get('specific_gf', '-')}:{team_standings_data.get('specific_gc', '-')}</p>
    </div>
    """, unsafe_allow_html=True)

def display_comparison_table(home_data, away_data, rivals_data, display_home_name, display_away_name):
    def get_stat(df, stat, team_key): return df.loc[stat, team_key] if df is not None and stat in df.index else PLACEHOLDER_NODATA

    home_match, away_match = home_data or {}, away_data or {}
    rivals_match = rivals_data if rivals_data.get('status') == 'found' else {}
    
    home_stats_df, away_stats_df, rivals_stats_df = (get_match_progression_stats_data(m.get('match_id')) for m in [home_match, away_match, rivals_match])
    
    stats_map = { "Shots": "Disparos", "Shots on Goal": "Disparos a Puerta", "Attacks": "Ataques", "Dangerous Attacks": "Ataques Peligrosos"}
    
    html = "<table class='stats-table'><thead><tr><th>Métrica</th>"
    html += f"<th class='center-text'>Último <span class='home-color'>{display_home_name[:10]} (C)</span></th>"
    html += f"<th class='center-text'>Último <span class='away-color'>{display_away_name[:10]} (F)</span></th>"
    html += "<th class='center-text'>H2H Rivales</th></tr></thead><tbody>"
    
    html += f"<tr><td><b>Rival</b></td><td class='center-text away-color'>{home_match.get('away_team', PLACEHOLDER_NODATA)}</td><td class='center-text home-color'>{away_match.get('home_team', PLACEHOLDER_NODATA)}</td><td class='center-text'>{rivals_match.get('h2h_home_team_name', '--')} vs {rivals_match.get('h2h_away_team_name', '--')}</td></tr>"
    html += f"<tr><td><b>Resultado</b></td><td class='center-text stat-value'>{home_match.get('score', '?:?').replace('-', ':')}</td><td class='center-text stat-value'>{away_match.get('score', '?:?').replace('-', ':')}</td><td class='center-text stat-value'>{rivals_match.get('goles_home', '?')}:{rivals_match.get('goles_away', '?')}</td></tr>"
    html += f"<tr><td><b>Hándicap (AH)</b></td><td class='center-text ah-value'>{format_ah_as_decimal_string_of(home_match.get('handicap_line_raw', '-'))}</td><td class='center-text ah-value'>{format_ah_as_decimal_string_of(away_match.get('handicap_line_raw', '-'))}</td><td class='center-text ah-value'>{format_ah_as_decimal_string_of(rivals_match.get('handicap', '-'))}</td></tr>"

    for key, name in stats_map.items():
        # Correctly identify team vs rival stats for home team's last match
        team_is_home_in_home_match = display_home_name.lower() == home_match.get('home_team', '').lower()
        stat_home_team, stat_home_rival = (get_stat(home_stats_df, key, 'Casa'), get_stat(home_stats_df, key, 'Fuera')) if team_is_home_in_home_match else (get_stat(home_stats_df, key, 'Fuera'), get_stat(home_stats_df, key, 'Casa'))

        # Correctly identify team vs rival stats for away team's last match
        team_is_home_in_away_match = display_away_name.lower() == away_match.get('home_team', '').lower()
        stat_away_team, stat_away_rival = (get_stat(away_stats_df, key, 'Casa'), get_stat(away_stats_df, key, 'Fuera')) if team_is_home_in_away_match else (get_stat(away_stats_df, key, 'Fuera'), get_stat(away_stats_df, key, 'Casa'))

        stat_rivals_home, stat_rivals_away = get_stat(rivals_stats_df, key, 'Casa'), get_stat(rivals_stats_df, key, 'Fuera')
        
        html += f"<tr><td><b>{name}</b></td><td class='center-text'><span class='home-color'>{stat_home_team}</span> vs {stat_home_rival}</td><td class='center-text'><span class='away-color'>{stat_away_team}</span> vs {stat_away_rival}</td><td class='center-text'>{stat_rivals_home} vs {stat_rivals_away}</td></tr>"
    
    html += "</tbody></table>"
    st.markdown(html, unsafe_allow_html=True)

def display_details_expander(h2h_data, odds_data, comp_data_L, comp_data_V, display_home_name, display_away_name):
    with st.expander("Ver Detalles Adicionales (H2H, Cuotas, Comparativas)"):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("<div class='expander-subheader'>H2H Directo y Cuotas</div>", unsafe_allow_html=True)
            st.metric("🏁 Marcador Final (Partido)", odds_data.get("Fin", "Pendiente"))
            st.metric("⚖️ AH Inicial (Partido)", odds_data.get("AH_Act", PLACEHOLDER_NODATA))
            st.metric("🥅 Goles Inicial (Partido)", odds_data.get("G_i", PLACEHOLDER_NODATA))
            st.metric("🏠 Res H2H (Local en Casa)", h2h_data['Res_H2H_V'].replace("*",":"), f"AH: {h2h_data['AH_H2H_V']}")
            st.metric("🌍 Res H2H (General)", h2h_data['Res_H2H_G'].replace("*",":"), f"AH: {h2h_data['AH_H2H_G']}")

        with col2:
            st.markdown("<div class='expander-subheader'>Comparativas Indirectas</div>", unsafe_allow_html=True)
            st.write(f"**<span class='home-color'>{display_home_name}</span> vs. Últ. Rival de <span class='away-color'>{display_away_name}</span>**", unsafe_allow_html=True)
            if comp_data_L:
                st.markdown(f"Resultado: **{comp_data_L.get('score', '?')}** | AH: **{format_ah_as_decimal_string_of(comp_data_L.get('ah_line', '-'))}**", unsafe_allow_html=True)
            else:
                st.caption("No disponible.")
            
            st.write(f"**<span class='away-color'>{display_away_name}</span> vs. Últ. Rival de <span class='home-color'>{display_home_name}</span>**", unsafe_allow_html=True)
            if comp_data_V:
                st.markdown(f"Resultado: **{comp_data_V.get('score', '?')}** | AH: **{format_ah_as_decimal_string_of(comp_data_V.get('ah_line', '-'))}**", unsafe_allow_html=True)
            else:
                st.caption("No disponible.")
            

def display_other_feature_ui():
    st.sidebar.title("⚙️ Configuración del Partido")
    main_match_id_str = st.sidebar.text_input("🆔 ID Partido Principal:", "2696131", help="Pega el ID numérico del partido.")
    analizar_button = st.sidebar.button("🚀 Analizar Partido", type="primary", use_container_width=True)

    if 'driver_other_feature' not in st.session_state: st.session_state.driver_other_feature = None
    if not analizar_button: st.info("✨ Ingresa un ID de partido y haz clic en 'Analizar'."); return

    main_match_id = int("".join(filter(str.isdigit, main_match_id_str))) if main_match_id_str.isdigit() else None
    if not main_match_id: st.error("⚠️ ID de partido no válido."); st.stop()

    with st.spinner("🔄 Obteniendo y procesando datos..."):
        soup_main = fetch_soup_requests_of(f"/match/h2h-{main_match_id}")
        if not soup_main: st.error("❌ No se pudo obtener la página H2H."); st.stop()
        
        # --- Extracción de Datos ---
        ids_names = get_team_league_info_from_script_of(soup_main)
        mp_league_id, mp_home_name, mp_away_name = ids_names[2], ids_names[3], ids_names[4]
        home_standings = extract_standings_data_from_h2h_page_of(soup_main, mp_home_name)
        away_standings = extract_standings_data_from_h2h_page_of(soup_main, mp_away_name)
        display_home_name, display_away_name = home_standings.get("name"), away_standings.get("name")
        
        final_score, _ = extract_final_score_of(soup_main)
        h2h_direct = extract_h2h_data_of(soup_main, display_home_name, display_away_name, mp_league_id)
        
        if st.session_state.driver_other_feature is None or not hasattr(st.session_state.driver_other_feature, 'service') or not st.session_state.driver_other_feature.service.is_connectable():
            st.session_state.driver_other_feature = get_selenium_driver_of()
        
        driver = st.session_state.driver_other_feature
        last_home_match, last_away_match, h2h_rivals, odds_data = None, None, {}, {}
        if driver:
            try:
                driver.get(f"{BASE_URL_OF}/match/h2h-{main_match_id}")
                WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.ID, "table_v1")))
                odds_data = get_main_match_odds_selenium_of(driver)
                last_home_match = extract_last_match_in_league_of(driver, "table_v1", display_home_name, mp_league_id, "input#cb_sos1[value='1']", True)
                last_away_match = extract_last_match_in_league_of(driver, "table_v2", display_away_name, mp_league_id, "input#cb_sos2[value='2']", False)
                rival_a, rival_b = get_rival_a_for_original_h2h_of(main_match_id), get_rival_b_for_original_h2h_of(main_match_id)
                if rival_a and rival_b: h2h_rivals = get_h2h_details_for_original_logic_of(driver, rival_a[0], rival_a[1], rival_b[1], rival_a[2], rival_b[2])
            except Exception as e: st.warning(f"❗ Error de Selenium: {e}")

        comp_data_L = extract_comparative_match_of(soup_main, "table_v1", display_home_name, (last_away_match or {}).get('home_team'), mp_league_id, True)
        comp_data_V = extract_comparative_match_of(soup_main, "table_v2", display_away_name, (last_home_match or {}).get('away_team'), mp_league_id, False)

    # --- RENDERIZACIÓN DE LA UI ---
    st.markdown(get_clarity_css(), unsafe_allow_html=True)
    st.markdown(f"<div class='main-header'><div class='teams'><span class='home-color'>{display_home_name}</span> vs <span class='away-color'>{display_away_name}</span></div><div class='league'>🏆 {ids_names[5]} | Partido ID: {main_match_id}</div></div>", unsafe_allow_html=True)
    
    with st.container():
        st.markdown("<div class='section-container'><div class='section-header'>📈 Clasificación</div>", unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"<div class='team-name-header home-color'>{display_home_name}</div>", unsafe_allow_html=True)
            display_standings_card(home_standings)
        with col2:
            st.markdown(f"<div class='team-name-header away-color'>{display_away_name}</div>", unsafe_allow_html=True)
            display_standings_card(away_standings)
        st.markdown("</div>", unsafe_allow_html=True)
    
    with st.container():
        st.markdown("<div class='section-container'><div class='section-header'>📊 Comparativa de Partidos Clave</div>", unsafe_allow_html=True)
        display_comparison_table(last_home_match, last_away_match, h2h_rivals, display_home_name, display_away_name)
        st.markdown("</div>", unsafe_allow_html=True)
    
    # Empaquetar datos para el expander
    h2h_dict = {'Res_H2H_V': h2h_direct[1], 'AH_H2H_V': h2h_direct[0], 'Res_H2H_G': h2h_direct[5], 'AH_H2H_G': h2h_direct[4]}
    odds_dict = {'Fin': final_score, 'AH_Act': format_ah_as_decimal_string_of(odds_data.get('ah_linea_raw')), 'G_i': format_ah_as_decimal_string_of(odds_data.get('goals_linea_raw'))}
    display_details_expander(h2h_dict, odds_dict, comp_data_L, comp_data_V, display_home_name, display_away_name)


if __name__ == '__main__':
    st.set_page_config(layout="wide", page_title="Análisis de Partidos", initial_sidebar_state="expanded")
    display_other_feature_ui()
