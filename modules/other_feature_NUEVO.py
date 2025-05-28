# modules/other_feature_NUEVO.py (o como lo llames)
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
BASE_URL_OF = "https://live18.nowgoal25.com"
SELENIUM_TIMEOUT_SECONDS_OF = 20
SELENIUM_POLL_FREQUENCY_OF = 0.2

# --- FUNCIONES HELPER PARA PARSEO Y FORMATEO (SIN CAMBIOS) ---
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
        if not home or not away: return None
        return {'home': home, 'away': away, 'score': score_fmt, 'score_raw': score_raw,
                'ahLine': ah_line_fmt, 'ahLine_raw': ah_line_raw_text,
                'matchIndex': row_element.get('index'), 'vs': row_element.get('vs'),
                'league_id_hist': league_id_hist_attr}
    except Exception: return None

# --- FUNCIONES DE REQUESTS, SELENIUM, Y EXTRACCIÓN (SIN CAMBIOS) ---
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
            tds = row.find_all("td"); handicap_raw = "N/A"; HANDICAP_TD_IDX = 11 
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
            if len(tds) < 14: continue
            home_team_row_el = tds[2].find("a"); away_team_row_el = tds[4].find("a")
            if not home_team_row_el or not away_team_row_el: continue
            home_team_row_name = home_team_row_el.text.strip(); away_team_row_name = away_team_row_el.text.strip()
            team_is_home_in_row = main_team_name_in_table.lower() == home_team_row_name.lower()
            team_is_away_in_row = main_team_name_in_table.lower() == away_team_row_name.lower()
            if (is_home_game_filter and team_is_home_in_row) or (not is_home_game_filter and team_is_away_in_row):
                date_span = tds[1].find("span", {"name": "timeData"}); date = date_span.text.strip() if date_span else "N/A"
                score_class_re = re.compile(r"fscore_"); score_span = tds[3].find("span", class_=score_class_re); score = score_span.text.strip() if score_span else "N/A"
                handicap_cell = tds[11]; handicap_raw = handicap_cell.get("data-o", handicap_cell.text.strip()) 
                if not handicap_raw or handicap_raw.strip() == "-": handicap_raw = "N/A"
                else: handicap_raw = handicap_raw.strip()
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
        if len(tds) >= 11:
            odds_info["ah_home_cuota"] = tds[2].get_attribute("data-o") or tds[2].text.strip() or "N/A"
            odds_info["ah_linea_raw"] = tds[3].get_attribute("data-o") or tds[3].text.strip() or "N/A" 
            odds_info["ah_away_cuota"] = tds[4].get_attribute("data-o") or tds[4].text.strip() or "N/A"
            odds_info["goals_over_cuota"] = tds[8].get_attribute("data-o") or tds[8].text.strip() or "N/A"
            odds_info["goals_linea_raw"] = tds[9].get_attribute("data-o") or tds[9].text.strip() or "N/A" 
            odds_info["goals_under_cuota"] = tds[10].get_attribute("data-o") or tds[10].text.strip() or "N/A"
    except Exception: pass
    return odds_info

def extract_standings_data_from_h2h_page_of(h2h_soup, target_team_name_exact):
    data = {"name": target_team_name_exact, "ranking": "N/A", "total_pj": "N/A", "total_v": "N/A", "total_e": "N/A", "total_d": "N/A", "total_gf": "N/A", "total_gc": "N/A", "specific_pj": "N/A", "specific_v": "N/A", "specific_e": "N/A", "specific_d": "N/A", "specific_gf": "N/A", "specific_gc": "N/A", "specific_type": "N/A" }
    if not h2h_soup: return data
    standings_section = h2h_soup.find("div", id="porletP4"); 
    if not standings_section: return data
    team_table_soup = None; is_home_team_table_type = False
    home_div_standings = standings_section.find("div", class_="home-div")
    if home_div_standings:
        home_table_header = home_div_standings.find("tr", class_="team-home")
        if home_table_header and target_team_name_exact and target_team_name_exact.lower() in home_table_header.get_text().lower(): 
            team_table_soup = home_div_standings.find("table", class_="team-table-home"); is_home_team_table_type = True
            data["specific_type"] = home_div_standings.find("td", class_="bg1").text.strip() if home_div_standings.find("td", class_="bg1") else "En Casa"
    if not team_table_soup:
        guest_div_standings = standings_section.find("div", class_="guest-div")
        if guest_div_standings:
            guest_table_header = guest_div_standings.find("tr", class_="team-guest")
            if guest_table_header and target_team_name_exact and target_team_name_exact.lower() in guest_table_header.get_text().lower(): 
                team_table_soup = guest_div_standings.find("table", class_="team-table-guest"); is_home_team_table_type = False
                data["specific_type"] = guest_div_standings.find("td", class_="bg1").text.strip() if guest_div_standings.find("td", class_="bg1") else "Fuera"
    if not team_table_soup: return data
    header_row_found = team_table_soup.find("tr", class_=re.compile(r"team-(home|guest)")) 
    if header_row_found:
        link = header_row_found.find("a")
        if link:
            full_text = link.get_text(separator=" ", strip=True); name_match = re.search(r"]\s*(.*)", full_text); rank_match = re.search(r"\[(?:[^\]]+-)?(\d+)\]", full_text)
            if name_match: data["name"] = name_match.group(1).strip()
            if rank_match: data["ranking"] = rank_match.group(1)
        else: 
            header_text_no_link = header_row_found.get_text(separator=" ", strip=True); name_match_nl = re.search(r"]\s*(.*)", header_text_no_link)
            if name_match_nl: data["name"] = name_match_nl.group(1).strip()
            rank_match_nl = re.search(r"\[(?:[^\]]+-)?(\d+)\]", header_text_no_link)
            if rank_match_nl: data["ranking"] = rank_match_nl.group(1)
    ft_rows = []; current_section = None
    for row in team_table_soup.find_all("tr", align="center"): 
        th_cell = row.find("th");
        if th_cell:
            if "FT" in th_cell.get_text(strip=True): current_section = "FT"
            elif "HT" in th_cell.get_text(strip=True): break 
        if current_section == "FT":
            cells = row.find_all("td")
            if cells and len(cells) > 0 and cells[0].get_text(strip=True) in ["Total", "Home", "Away"]: ft_rows.append(cells)
    for cells in ft_rows:
        if len(cells) > 8: 
            row_type_text = cells[0].get_text(strip=True)
            pj, v, e, d, gf, gc = (cells[i].get_text(strip=True) for i in range(1, 7))
            pj=pj if pj else "N/A"; v=v if v else "N/A"; e=e if e else "N/A"; d=d if d else "N/A"; gf=gf if gf else "N/A"; gc=gc if gc else "N/A"
            if row_type_text=="Total": data["total_pj"],data["total_v"],data["total_e"],data["total_d"],data["total_gf"],data["total_gc"]=pj,v,e,d,gf,gc
            elif row_type_text=="Home" and is_home_team_table_type: data["specific_pj"],data["specific_v"],data["specific_e"],data["specific_d"],data["specific_gf"],data["specific_gc"]=pj,v,e,d,gf,gc
            elif row_type_text=="Away" and not is_home_team_table_type: data["specific_pj"],data["specific_v"],data["specific_e"],data["specific_d"],data["specific_gf"],data["specific_gc"]=pj,v,e,d,gf,gc
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
    h2h_general_match = filtered_h2h_list[0]
    ah6 = h2h_general_match.get('ahLine', '-') 
    res6 = h2h_general_match.get('score', '?*?'); res6_raw = h2h_general_match.get('score_raw', '?-?')
    h2h_local_specific_match = None
    for d_h2h in filtered_h2h_list:
        if d_h2h.get('home','').lower() == main_home_team_name.lower() and \
           d_h2h.get('away','').lower() == main_away_team_name.lower():
            h2h_local_specific_match = d_h2h; break
    if h2h_local_specific_match:
        ah1 = h2h_local_specific_match.get('ahLine', '-') 
        res1 = h2h_local_specific_match.get('score', '?*?'); res1_raw = h2h_local_specific_match.get('score_raw', '?-?')
    return ah1, res1, res1_raw, ah6, res6, res6_raw

def extract_comparative_match_of(soup_for_team_history, table_id_of_team_to_search, team_name_to_find_match_for, opponent_name_to_search, current_league_id, is_home_table):
    if not opponent_name_to_search or opponent_name_to_search == "N/A" or not team_name_to_find_match_for:
        return "-"
    table = soup_for_team_history.find("table", id=table_id_of_team_to_search)
    if not table: return "-"
    score_class_selector = 'fscore_1' if is_home_table else 'fscore_2'
    for row in table.find_all("tr", id=re.compile(rf"tr{table_id_of_team_to_search[-1]}_\d+")):
        details = get_match_details_from_row_of(row, score_class_selector=score_class_selector, source_table_type='hist')
        if not details: continue
        if current_league_id and details.get('league_id_hist') and details.get('league_id_hist') != str(current_league_id): continue
        home_hist = details.get('home','').lower(); away_hist = details.get('away','').lower()
        team_main_lower = team_name_to_find_match_for.lower(); opponent_lower = opponent_name_to_search.lower()
        if (team_main_lower == home_hist and opponent_lower == away_hist) or \
           (team_main_lower == away_hist and opponent_lower == home_hist):
            score = details.get('score', '?*?')
            ah_line_extracted = details.get('ahLine', '-')
            localia = 'H' if team_main_lower == home_hist else 'A'
            return f"{score}/{ah_line_extracted} {localia}".strip()
    return "-"

# --- STREAMLIT APP UI (Función principal) ---
def display_other_feature_ui():
    
    # --- INJECT CUSTOM CSS (COMPACT VERSION) ---
    st.markdown("""
        <style>
            body {
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                font-size: 0.8rem; /* REDUCED FONT SIZE */
            }
            .stApp { /* background-color: #f0f2f6; */ }
            .card {
                background-color: #ffffff;
                border: 1px solid #e1e4e8;
                border-radius: 5px; /* Slightly less rounded */
                padding: 8px 12px; /* REDUCED PADDING */
                margin-bottom: 8px; /* REDUCED MARGIN */
                box-shadow: 0 1px 3px rgba(0,0,0,0.05); /* Softer shadow */
            }
            .card-title {
                font-size: 0.95em; /* REDUCED TITLE */
                font-weight: 600;
                color: #007bff; /* Streamlit blue */
                margin-bottom: 5px; /* REDUCED MARGIN */
                border-bottom: 1px solid #007bff20;
                padding-bottom: 4px; /* REDUCED PADDING */
            }
            .card-subtitle {
                font-size: 0.85em; /* REDUCED SUBTITLE */
                font-weight: 500; color: #333;
                margin-top: 4px; margin-bottom: 2px;
            }
            /* Compact Metric Style (if st.metric is used) */
            div[data-testid="stMetric"] {
                background-color: #f8f9fa; border: 1px solid #dee2e6;
                border-radius: 4px; padding: 6px 8px; /* REDUCED PADDING */
                text-align: center; margin-bottom: 4px;
            }
            div[data-testid="stMetric"] label {
                font-size: 0.7em; /* REDUCED LABEL */
                color: #495057; font-weight: 500; margin-bottom: 1px;
            }
            div[data-testid="stMetric"] div[class*="stMetricValue"] { /* More generic selector for value */
                font-size: 1.1em; /* REDUCED VALUE */
                font-weight: bold; color: #212529; line-height: 1.1;
            }
            /* Custom styled spans for data points */
            .home-color { color: #007bff; font-weight: bold; }
            .away-color { color: #fd7e14; font-weight: bold; }
            .ah-value, .goals-value { 
                padding: 1px 5px; border-radius: 8px; 
                font-weight: bold; font-size: 0.75em; /* REDUCED */
            }
            .ah-value { background-color: #e6f3ff; color: #007bff; border: 1px solid #007bff30;}
            .goals-value { background-color: #ffebe6; color: #dc3545; border: 1px solid #dc354530;}
            .score-value { font-weight: bold; font-size: 0.9em; color: #28a745; } /* REDUCED */
            .data-highlight {
                font-family: 'Courier New', Courier, monospace;
                background-color: #e9ecef; padding: 1px 3px;
                border-radius: 3px; font-size: 0.75em; /* REDUCED */
            }
            /* Expander header styling */
            .st-emotion-cache-10trblm .st-emotion-cache-l9icx6 { /* Might need adjustment */
                font-size: 0.9em !important; /* REDUCED */
                font-weight: 600 !important; color: #0056b3 !important; 
                padding-top: 6px !important; padding-bottom: 6px !important;
            }
            .main-title {
                text-align: center; color: #343a40; font-size: 1.6em; /* REDUCED */
                font-weight: bold; margin-bottom: 4px; padding-bottom: 4px;
            }
            .sub-title {
                text-align: center; color: #007bff; font-size: 1.1em; /* REDUCED */
                font-weight: bold; margin-bottom: 8px;
            }
            .section-header {
                font-size: 1.1em; /* REDUCED */
                font-weight: 600; color: #17a2b8;
                margin-top: 10px; margin-bottom: 8px; /* REDUCED MARGINS */
                border-bottom: 1px solid #17a2b830; padding-bottom: 4px;
            }
            .stCaption { /* Make captions very small */
                font-size: 0.65rem !important; 
                margin-top: 0px !important; margin-bottom: 1px !important;
                line-height: 1.0 !important;
                color: #6c757d;
            }
            .stMarkdown p, .stMarkdown li { /* Reduce space in markdown */
                margin-bottom: 0.1rem !important; 
                line-height: 1.2;
            }
            .compact-metric-item {
                text-align: center; margin: 2px 4px; padding: 4px 6px; 
                background-color: #f0f0f0; border-radius: 3px; 
                min-width: 90px; display: inline-block; /* For wrapping */
                border: 1px solid #ddd;
            }
            .compact-metric-item small { font-size: 0.65em; display: block; color: #555; }
            .compact-metric-item strong { font-size: 0.9em; color: #333; }
        </style>
    """, unsafe_allow_html=True)

    st.sidebar.image("https://raw.githubusercontent.com/streamlit/docs/main/public/images/brand/streamlit-logo-secondary-colormark-darktext.svg", width=180)
    st.sidebar.title("⚙️ Config. Partido (OF)")
    main_match_id_str_input_of = st.sidebar.text_input(
        "🆔 ID Partido:", value="2696131", 
        help="ID numérico del partido.", key="other_feature_match_id_input_compact"
    )
    analizar_button_of = st.sidebar.button("🚀 Analizar (OF)", type="primary", use_container_width=True, key="other_feature_analizar_button_compact")

    results_container = st.container()
    placeholder_nodata = "-" # Shorter placeholder

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
                results_container.error("⚠️ ID no válido."); st.stop()
        if not main_match_id_to_process_of: 
            results_container.warning("⚠️ Ingresa ID."); st.stop()
        
        start_time_of = time.time()
        with results_container:
            with st.spinner("🔄 Cargando datos..."):
                main_page_url_h2h_view_of = f"/match/h2h-{main_match_id_to_process_of}"
                soup_main_h2h_page_of = fetch_soup_requests_of(main_page_url_h2h_view_of)
            if not soup_main_h2h_page_of:
                st.error(f"❌ No se pudo obtener H2H ({main_match_id_to_process_of})."); st.stop()

            mp_home_id_of, mp_away_id_of, mp_league_id_of, mp_home_name_from_script, mp_away_name_from_script, mp_league_name_of = get_team_league_info_from_script_of(soup_main_h2h_page_of)
            
            with st.spinner("📊 Clasificaciones..."):
                home_team_main_standings = extract_standings_data_from_h2h_page_of(soup_main_h2h_page_of, mp_home_name_from_script)
                away_team_main_standings = extract_standings_data_from_h2h_page_of(soup_main_h2h_page_of, mp_away_name_from_script)
            
            display_home_name = home_team_main_standings.get("name", mp_home_name_from_script) if home_team_main_standings.get("name", "N/A") != "N/A" else mp_home_name_from_script
            display_away_name = away_team_main_standings.get("name", mp_away_name_from_script) if away_team_main_standings.get("name", "N/A") != "N/A" else mp_away_name_from_script

            st.markdown(f"<p class='main-title'>Análisis Rápido (OF)</p>", unsafe_allow_html=True)
            st.markdown(f"<p class='sub-title'><span class='home-color'>{display_home_name or 'Local'}</span> vs <span class='away-color'>{display_away_name or 'Visitante'}</span></p>", unsafe_allow_html=True)
            st.markdown(f"<div style='text-align:center; font-size:0.75em; margin-bottom:10px;'>🏆 {mp_league_name_of or placeholder_nodata} (ID: {mp_league_id_of or placeholder_nodata}) | 🆔 <span class='data-highlight'>{main_match_id_to_process_of}</span></div>", unsafe_allow_html=True)
            
            # --- Clasificación Compacta ---
            st.markdown("<div class='card'>", unsafe_allow_html=True)
            st.markdown(f"<h4 class='card-title' style='text-align:center;'>📈 Clasificación</h4>", unsafe_allow_html=True)
            col_h_stand, col_a_stand = st.columns(2)
            with col_h_stand:
                st.markdown(f"<strong class='home-color'>{display_home_name or 'Local'}</strong>", unsafe_allow_html=True)
                if display_home_name and display_home_name != "N/A" and home_team_main_standings.get("name", "N/A") != "N/A":
                    hst = home_team_main_standings
                    st.markdown(f"<small>Rk: <span class='data-highlight'>{hst.get('ranking', '?')}</span> | Total: {hst.get('total_pj', '0')}PJ {hst.get('total_v', '0')}V-{hst.get('total_e', '0')}E-{hst.get('total_d', '0')}D ({hst.get('total_gf', '0')}-{hst.get('total_gc', '0')})</small>", unsafe_allow_html=True)
                    st.markdown(f"<small>{hst.get('specific_type','Casa')}: {hst.get('specific_pj', '0')}PJ {hst.get('specific_v', '0')}V-{hst.get('specific_e', '0')}E-{hst.get('specific_d', '0')}D ({hst.get('specific_gf', '0')}-{hst.get('specific_gc', '0')})</small>", unsafe_allow_html=True)
                else: st.caption(f"No disponible.")
            with col_a_stand:
                st.markdown(f"<strong class='away-color'>{display_away_name or 'Visitante'}</strong>", unsafe_allow_html=True)
                if display_away_name and display_away_name != "N/A" and away_team_main_standings.get("name", "N/A") != "N/A":
                    ast = away_team_main_standings
                    st.markdown(f"<small>Rk: <span class='data-highlight'>{ast.get('ranking', '?')}</span> | Total: {ast.get('total_pj', '0')}PJ {ast.get('total_v', '0')}V-{ast.get('total_e', '0')}E-{ast.get('total_d', '0')}D ({ast.get('total_gf', '0')}-{ast.get('total_gc', '0')})</small>", unsafe_allow_html=True)
                    st.markdown(f"<small>{ast.get('specific_type','Fuera')}: {ast.get('specific_pj', '0')}PJ {ast.get('specific_v', '0')}V-{ast.get('specific_e', '0')}E-{ast.get('specific_d', '0')}D ({ast.get('specific_gf', '0')}-{ast.get('specific_gc', '0')})</small>", unsafe_allow_html=True)
                else: st.caption(f"No disponible.")
            st.markdown("</div>", unsafe_allow_html=True)

            # --- Selenium dependent data ---
            main_match_odds_data_of = {}; last_home_match_in_league_of = None; last_away_match_in_league_of = None
            driver_actual_of = st.session_state.driver_other_feature; driver_of_needs_init = False
            if driver_actual_of is None: driver_of_needs_init = True
            else:
                try: _ = driver_actual_of.window_handles
                except WebDriverException: driver_of_needs_init = True # Assume dead
            if driver_of_needs_init:
                if driver_actual_of is not None:
                    try: driver_actual_of.quit()
                    except: pass
                with st.spinner("🚘 WebDriver..."): driver_actual_of = get_selenium_driver_of()
                st.session_state.driver_other_feature = driver_actual_of

            if driver_actual_of:
                try:
                    with st.spinner("⚙️ Selenium data..."):
                        driver_actual_of.get(f"{BASE_URL_OF}{main_page_url_h2h_view_of}") 
                        WebDriverWait(driver_actual_of, SELENIUM_TIMEOUT_SECONDS_OF).until(EC.presence_of_element_located((By.ID, "table_v1"))) 
                        time.sleep(0.5)
                        main_match_odds_data_of = get_main_match_odds_selenium_of(driver_actual_of)
                        if mp_home_id_of and mp_league_id_of and display_home_name and display_home_name != "N/A":
                             last_home_match_in_league_of = extract_last_match_in_league_of(driver_actual_of, "table_v1", display_home_name, mp_league_id_of, "input#cb_sos1[value='1']", is_home_game_filter=True)
                        if mp_away_id_of and mp_league_id_of and display_away_name and display_away_name != "N/A":
                            last_away_match_in_league_of = extract_last_match_in_league_of(driver_actual_of, "table_v2", display_away_name, mp_league_id_of, "input#cb_sos2[value='2']", is_home_game_filter=False)
                except Exception as e_main_sel_of: st.warning(f"❗ Error Selenium: {type(e_main_sel_of).__name__}")
            else: st.caption("❗ WebDriver no disp. para Cuotas/Últ.Partidos.")

            # --- col_data population (remains mostly the same logic) ---
            col_data = { "AH_H2H_V": "-", "AH_Act": "?", "Res_H2H_V": "?*?", "AH_L_H": "-", "Res_L_H": "?*?", "AH_V_A": "-", "Res_V_A": "?*?", "AH_H2H_G": "-", "Res_H2H_G": "?*?", "L_vs_UV_A": "-", "V_vs_UL_H": "-", "Stats_L": "N/A", "Stats_V": "N/A", "Fin": "?*?", "G_i": "?", "League": mp_league_name_of or "-", "match_id": str(main_match_id_to_process_of)}
            raw_ah_act = main_match_odds_data_of.get('ah_linea_raw', '?'); col_data["AH_Act"] = format_ah_as_decimal_string_of(raw_ah_act)
            raw_g_i = main_match_odds_data_of.get('goals_linea_raw', '?'); col_data["G_i"] = format_ah_as_decimal_string_of(raw_g_i)
            col_data["Fin"], _ = extract_final_score_of(soup_main_h2h_page_of)
            # Stats_L, Stats_V, AH_L_H, Res_L_H, AH_V_A, Res_V_A, H2H data, L_vs_UV_A, V_vs_UL_H are populated as before
            if home_team_main_standings.get("name", "N/A") != "N/A": hst = home_team_main_standings; col_data["Stats_L"] = (f"Rk:{hst.get('ranking','?')}|T:{hst.get('total_pj','0')}|{hst.get('total_v','0')}/{hst.get('total_e','0')}/{hst.get('total_d','0')}|{hst.get('total_gf','0')}-{hst.get('total_gc','0')}\nL:{hst.get('specific_pj','0')}|{hst.get('specific_v','0')}/{hst.get('specific_e','0')}/{hst.get('specific_d','0')}|{hst.get('specific_gf','0')}-{hst.get('specific_gc','0')}")
            if away_team_main_standings.get("name", "N/A") != "N/A": ast = away_team_main_standings; col_data["Stats_V"] = (f"Rk:{ast.get('ranking','?')}|T:{ast.get('total_pj','0')}|{ast.get('total_v','0')}/{ast.get('total_e','0')}/{ast.get('total_d','0')}|{ast.get('total_gf','0')}-{ast.get('total_gc','0')}\nV:{ast.get('specific_pj','0')}|{ast.get('specific_v','0')}/{ast.get('specific_e','0')}/{ast.get('specific_d','0')}|{ast.get('specific_gf','0')}-{ast.get('specific_gc','0')}")
            if last_home_match_in_league_of: col_data["AH_L_H"] = format_ah_as_decimal_string_of(last_home_match_in_league_of.get('handicap_line_raw', '-')); col_data["Res_L_H"] = last_home_match_in_league_of.get('score', '?*?').replace('-', '*')
            if last_away_match_in_league_of: col_data["AH_V_A"] = format_ah_as_decimal_string_of(last_away_match_in_league_of.get('handicap_line_raw', '-')); col_data["Res_V_A"] = last_away_match_in_league_of.get('score', '?*?').replace('-', '*')
            ah1_val, res1_val, _, ah6_val, res6_val, _ = extract_h2h_data_of(soup_main_h2h_page_of, display_home_name, display_away_name, mp_league_id_of); col_data["AH_H2H_V"] = ah1_val; col_data["Res_H2H_V"] = res1_val; col_data["AH_H2H_G"] = ah6_val; col_data["Res_H2H_G"] = res6_val
            last_away_opponent_for_home_hist = last_away_match_in_league_of.get('home_team') if last_away_match_in_league_of and display_home_name else None
            if last_away_opponent_for_home_hist and display_home_name != "N/A": col_data["L_vs_UV_A"] = extract_comparative_match_of(soup_main_h2h_page_of, "table_v1", display_home_name, last_away_opponent_for_home_hist, mp_league_id_of, is_home_table=True)
            last_home_opponent_for_away_hist = last_home_match_in_league_of.get('away_team') if last_home_match_in_league_of and display_away_name else None
            if last_home_opponent_for_away_hist and display_away_name != "N/A": col_data["V_vs_UL_H"] = extract_comparative_match_of(soup_main_h2h_page_of, "table_v2", display_away_name, last_home_opponent_for_away_hist, mp_league_id_of, is_home_table=False)

            # --- Cuotas y Marcador Final ---
            st.markdown("<div class='card'>", unsafe_allow_html=True)
            st.markdown(f"<h4 class='card-title' style='text-align:center;'>⚖️ Cuotas B365 & Marcador Final 🏁</h4>", unsafe_allow_html=True)
            odds_col1, odds_col2, odds_col3 = st.columns([2,2,1])
            with odds_col1:
                ah_line_fmt = format_ah_as_decimal_string_of(main_match_odds_data_of.get('ah_linea_raw','?'))
                st.markdown(f"""<small><b>AH:</b> <span class='data-highlight'>{main_match_odds_data_of.get('ah_home_cuota',placeholder_nodata)}</span>
                <span class='ah-value'>[{ah_line_fmt if ah_line_fmt != '?' else placeholder_nodata}]</span>
                <span class='data-highlight'>{main_match_odds_data_of.get('ah_away_cuota',placeholder_nodata)}</span></small>""", unsafe_allow_html=True)
            with odds_col2:
                goals_line_fmt = format_ah_as_decimal_string_of(main_match_odds_data_of.get('goals_linea_raw','?'))
                st.markdown(f"""<small><b>Goles:</b> <span class='data-highlight'>{main_match_odds_data_of.get('goals_over_cuota',placeholder_nodata)}</span>
                <span class='goals-value'>[{goals_line_fmt if goals_line_fmt != '?' else placeholder_nodata}]</span>
                <span class='data-highlight'>{main_match_odds_data_of.get('goals_under_cuota',placeholder_nodata)}</span></small>""", unsafe_allow_html=True)
            with odds_col3:
                final_score_display = col_data["Fin"].replace("*",":") if col_data["Fin"] != "?*?" else placeholder_nodata
                st.markdown(f"<small><b>Fin:</b> <span class='score-value'>{final_score_display}</span></small>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

            # --- Rendimiento Reciente y H2H Oponentes (Col3) ---
            st.markdown("<div class='card'>", unsafe_allow_html=True)
            st.markdown(f"<h4 class='card-title' style='text-align:center;'>⚡ Rendimiento Reciente & H2H Rivales Col3</h4>", unsafe_allow_html=True)
            rp_col1, rp_col2, rp_col3 = st.columns(3)
            with rp_col1:
                st.markdown(f"<h5 class='card-subtitle' style='font-size:0.8em;'><span class='home-color'>Últ. {display_home_name or 'Local'} (C)</span></h5>", unsafe_allow_html=True)
                if last_home_match_in_league_of: 
                    res = last_home_match_in_league_of
                    st.markdown(f"<small>vs {res['away_team']}: <span class='score-value'>{res['score'].replace('-',':')}</span> AH:<span class='ah-value'>{format_ah_as_decimal_string_of(res.get('handicap_line_raw','-'))}</span></small>", unsafe_allow_html=True)
                else: st.caption("No encontrado.")
            with rp_col2:
                st.markdown(f"<h5 class='card-subtitle' style='font-size:0.8em;'><span class='away-color'>Últ. {display_away_name or 'Visitante'} (F)</span></h5>", unsafe_allow_html=True)
                if last_away_match_in_league_of: 
                    res = last_away_match_in_league_of
                    st.markdown(f"<small>vs {res['home_team']}: <span class='score-value'>{res['score'].replace('-',':')}</span> AH:<span class='ah-value'>{format_ah_as_decimal_string_of(res.get('handicap_line_raw','-'))}</span></small>", unsafe_allow_html=True)
                else: st.caption("No encontrado.")
            with rp_col3:
                st.markdown(f"<h5 class='card-subtitle' style='font-size:0.8em;'>H2H Rivales Col3</h5>", unsafe_allow_html=True)
                rival_a_col3_name_display = rival_a_name_orig_col3 if rival_a_name_orig_col3 and rival_a_name_orig_col3 != "N/A" else (rival_a_id_orig_col3 or "Rival A")
                rival_b_col3_name_display = rival_b_name_orig_col3 if rival_b_name_orig_col3 and rival_b_name_orig_col3 != "N/A" else (rival_b_id_orig_col3 or "Rival B")
                details_h2h_col3_of = {"status": "error", "resultado": placeholder_nodata}
                if key_match_id_for_rival_a_h2h and rival_a_id_orig_col3 and rival_b_id_orig_col3 and driver_actual_of: 
                    with st.spinner(f"Buscando H2H Col3..."):
                        details_h2h_col3_of = get_h2h_details_for_original_logic_of(driver_actual_of, key_match_id_for_rival_a_h2h, rival_a_id_orig_col3, rival_b_id_orig_col3, rival_a_col3_name_display, rival_b_col3_name_display)
                if details_h2h_col3_of.get("status") == "found":
                    res_h2h = details_h2h_col3_of
                    st.markdown(f"<small>{res_h2h.get('h2h_home_team_name','H')} <span class='score-value'>{res_h2h.get('goles_home','?')}:{res_h2h.get('goles_away','?')}</span> {res_h2h.get('h2h_away_team_name','A')} (AH: <span class='ah-value'>{format_ah_as_decimal_string_of(res_h2h.get('handicap','-'))}</span>)</small>", unsafe_allow_html=True)
                else: st.caption(f"No encontrado.")
            st.markdown("</div>", unsafe_allow_html=True)
            
            # --- Hándicaps y Resultados Clave (Compact Metrics) ---
            st.markdown("<div class='card'>", unsafe_allow_html=True)
            st.markdown(f"<h4 class='card-title' style='text-align:center;'>📊 Datos Adicionales Clave</h4>", unsafe_allow_html=True)
            
            metrics_html = "<div style='display: flex; flex-wrap: wrap; justify-content: space-around;'>"
            data_points = [
                ("AH H2H (L)", col_data["AH_H2H_V"]), ("Res H2H (L)", col_data["Res_H2H_V"].replace("*",":")),
                ("AH Actual", col_data["AH_Act"]), ("Goles Ini.", col_data["G_i"]),
                ("AH Últ.L(C)", col_data["AH_L_H"]), ("Res Últ.L(C)", col_data["Res_L_H"].replace("*",":")),
                ("AH Últ.V(F)", col_data["AH_V_A"]), ("Res Últ.V(F)", col_data["Res_V_A"].replace("*",":")),
                ("AH H2H (G)", col_data["AH_H2H_G"]), ("Res H2H (G)", col_data["Res_H2H_G"].replace("*",":")),
            ]
            for label, value in data_points:
                value_display = value if value not in ["?", "-"] else placeholder_nodata
                metrics_html += f"""
                <div class='compact-metric-item'>
                    <small>{label}</small>
                    <strong>{value_display}</strong>
                </div>"""
            metrics_html += "</div>"
            st.markdown(metrics_html, unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

            # --- Comparativas Indirectas Compactas ---
            with st.expander("🔁 Comparativas Indirectas", expanded=False):
                st.markdown("<div class='card' style='padding: 5px;'>", unsafe_allow_html=True)
                comp_col1, comp_col2 = st.columns(2)
                with comp_col1:
                    st.markdown(f"<small><span class='home-color'>L</span> vs. Últ. Rival <span class='away-color'>V</span></small>", unsafe_allow_html=True)
                    comp_str_l = col_data.get('L_vs_UV_A', "-")
                    if comp_str_l and comp_str_l != "-":
                        parts = comp_str_l.split('/'); score_part = parts[0].replace('*',':').strip()
                        ah_loc_part = parts[1].strip() if len(parts)>1 else " "
                        ah_val_l = ah_loc_part.rsplit(' ',1)[0].strip(); loc_val_l = ah_loc_part.rsplit(' ',1)[-1].strip() if ' ' in ah_loc_part else ""
                        st.markdown(f"<small>Res: <span class='data-highlight'>{score_part or '?'}</span> AH: <span class='ah-value'>{format_ah_as_decimal_string_of(ah_val_l) or '?'}</span> Loc: <span class='data-highlight'>{loc_val_l or '?'}</span></small>", unsafe_allow_html=True)
                    else: st.caption("No disp.")
                with comp_col2:
                    st.markdown(f"<small><span class='away-color'>V</span> vs. Últ. Rival <span class='home-color'>L</span></small>", unsafe_allow_html=True)
                    comp_str_v = col_data.get('V_vs_UL_H', "-")
                    if comp_str_v and comp_str_v != "-":
                        parts = comp_str_v.split('/'); score_part = parts[0].replace('*',':').strip()
                        ah_loc_part = parts[1].strip() if len(parts)>1 else " "
                        ah_val_v = ah_loc_part.rsplit(' ',1)[0].strip(); loc_val_v = ah_loc_part.rsplit(' ',1)[-1].strip() if ' ' in ah_loc_part else ""
                        st.markdown(f"<small>Res: <span class='data-highlight'>{score_part or '?'}</span> AH: <span class='ah-value'>{format_ah_as_decimal_string_of(ah_val_v) or '?'}</span> Loc: <span class='data-highlight'>{loc_val_v or '?'}</span></small>", unsafe_allow_html=True)
                    else: st.caption("No disp.")
                st.markdown("</div>", unsafe_allow_html=True)

            with st.expander("📋 Stats Detalladas / Info", expanded=False):
                st.markdown("<div class='card' style='padding: 5px;'>", unsafe_allow_html=True)
                stats_col1,stats_col2=st.columns(2)
                with stats_col1: 
                    st.markdown(f"<small><strong>Stats <span class='home-color'>{display_home_name or 'Local'}</span>:</strong></small>", unsafe_allow_html=True)
                    st.text(col_data["Stats_L"])
                with stats_col2: 
                    st.markdown(f"<small><strong>Stats <span class='away-color'>{display_away_name or 'Visitante'}</span>:</strong></small>", unsafe_allow_html=True)
                    st.text(col_data["Stats_V"])
                st.markdown("---")
                key_match_id_for_rival_a_h2h, rival_a_id_orig_col3, rival_a_name_orig_col3 = get_rival_a_for_original_h2h_of(main_match_id_to_process_of) # Re-fetch for display
                match_id_rival_b_game_ref, rival_b_id_orig_col3, rival_b_name_orig_col3 = get_rival_b_for_original_h2h_of(main_match_id_to_process_of) # Re-fetch for display
                rival_a_col3_name_display = rival_a_name_orig_col3 if rival_a_name_orig_col3 and rival_a_name_orig_col3 != "N/A" else (rival_a_id_orig_col3 or "Rival A")
                rival_b_col3_name_display = rival_b_name_orig_col3 if rival_b_name_orig_col3 and rival_b_name_orig_col3 != "N/A" else (rival_b_id_orig_col3 or "Rival B")
                
                with st.spinner("Clasif. Rivales Col3..."): # Extracción diferida para no bloquear UI principal
                    rival_a_standings = {}; rival_b_standings = {}
                    if rival_a_name_orig_col3 and rival_a_name_orig_col3 != "N/A" and key_match_id_for_rival_a_h2h:
                        soup_rival_a_h2h_page = fetch_soup_requests_of(f"/match/h2h-{key_match_id_for_rival_a_h2h}")
                        if soup_rival_a_h2h_page: rival_a_standings = extract_standings_data_from_h2h_page_of(soup_rival_a_h2h_page, rival_a_name_orig_col3)
                    if rival_b_name_orig_col3 and rival_b_name_orig_col3 != "N/A" and match_id_rival_b_game_ref:
                        soup_rival_b_h2h_page = fetch_soup_requests_of(f"/match/h2h-{match_id_rival_b_game_ref}")
                        if soup_rival_b_h2h_page: rival_b_standings = extract_standings_data_from_h2h_page_of(soup_rival_b_h2h_page, rival_b_name_orig_col3)
                
                opp_stand_col1, opp_stand_col2 = st.columns(2)
                with opp_stand_col1:
                    name_a = rival_a_standings.get('name', rival_a_col3_name_display)
                    st.markdown(f"<small><strong>Clas. <span class='home-color'>{name_a}</span> (Col3):</strong></small>", unsafe_allow_html=True)
                    if rival_a_standings.get("name", "N/A") != "N/A": rst = rival_a_standings; st.caption(f"Rk:{rst.get('ranking','?')} T:{rst.get('total_pj')}|{rst.get('total_v')}/{rst.get('total_e')}/{rst.get('total_d')} G:{rst.get('total_gf')}-{rst.get('total_gc')} S:{rst.get('specific_pj')}|{rst.get('specific_v')}/{rst.get('specific_e')}/{rst.get('specific_d')} G:{rst.get('specific_gf')}-{rst.get('specific_gc')}")
                    else: st.caption("No disp.")
                with opp_stand_col2:
                    name_b = rival_b_standings.get('name', rival_b_col3_name_display)
                    st.markdown(f"<small><strong>Clas. <span class='away-color'>{name_b}</span> (Col3):</strong></small>", unsafe_allow_html=True)
                    if rival_b_standings.get("name", "N/A") != "N/A": rst = rival_b_standings; st.caption(f"Rk:{rst.get('ranking','?')} T:{rst.get('total_pj')}|{rst.get('total_v')}/{rst.get('total_e')}/{rst.get('total_d')} G:{rst.get('total_gf')}-{rst.get('total_gc')} S:{rst.get('specific_pj')}|{rst.get('specific_v')}/{rst.get('specific_e')}/{rst.get('specific_d')} G:{rst.get('specific_gf')}-{rst.get('specific_gc')}")
                    else: st.caption("No disp.")
                st.markdown("</div>", unsafe_allow_html=True)


            end_time_of = time.time()
            st.sidebar.success(f"⏱️ {end_time_of - start_time_of:.2f}s")
    else:
        results_container.info("✨ Ingresa ID y haz clic en 'Analizar (OF)' para la vista rápida.")

if __name__ == '__main__':
    st.set_page_config(layout="wide", page_title="Análisis Rápido (OF)", initial_sidebar_state="expanded")
    if 'driver_other_feature' not in st.session_state:
        st.session_state.driver_other_feature = None
    display_other_feature_ui()
