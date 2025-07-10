# Fichero: modules/datos.py (Versión FINAL corregida)

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

# --- FUNCIONES HELPER (SIN CAMBIOS) ---
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

# --- FUNCIONES DE EXTRACCIÓN Y UI (SIN CAMBIOS HASTA display_other_feature_ui) ---
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
                        stat_titles_of_interest[stat_title].update({"Home": values[0].get_text(strip=True), "Away": values[1].get_text(strip=True)})
    except Exception: return None
    table_rows = [{"Estadistica_EN": name, "Casa": vals['Home'], "Fuera": vals['Away']} for name, vals in stat_titles_of_interest.items()]
    df = pd.DataFrame(table_rows)
    return df.set_index("Estadistica_EN") if not df.empty else df

def display_match_progression_stats_view(match_id: str, home_team_name: str, away_team_name: str):
    stats_df = get_match_progression_stats_data(match_id)
    if stats_df is None or stats_df.empty:
        st.caption(f"No se encontraron datos de progresión para el partido ID: **{match_id}**.")
        return
    ordered_stats_display = {"Shots": "Disparos", "Shots on Goal": "Disparos a Puerta", "Attacks": "Ataques", "Dangerous Attacks": "Ataques Peligrosos"}
    st.markdown("---")
    col_h_name, col_stat_name, col_a_name = st.columns([2, 3, 2])
    col_h_name.markdown(f"<p style='font-weight:bold; color: #007bff;'>{home_team_name or 'Local'}</p>", unsafe_allow_html=True)
    col_stat_name.markdown("<p style='text-align:center; font-weight:bold;'>Estadística</p>", unsafe_allow_html=True)
    col_a_name.markdown(f"<p style='text-align:right; font-weight:bold; color: #fd7e14;'>{away_team_name or 'Visitante'}</p>", unsafe_allow_html=True)
    for stat_key_en, stat_name_es in ordered_stats_display.items():
        if stat_key_en in stats_df.index:
            home_val_str, away_val_str = stats_df.loc[stat_key_en, 'Casa'], stats_df.loc[stat_key_en, 'Fuera']
            try: home_val_num = int(home_val_str)
            except (ValueError, TypeError): home_val_num = 0
            try: away_val_num = int(away_val_str)
            except (ValueError, TypeError): away_val_num = 0
            home_color, away_color = ("green", "red") if home_val_num > away_val_num else (("red", "green") if away_val_num > home_val_num else ("black", "black"))
            c1, c2, c3 = st.columns([2, 3, 2])
            c1.markdown(f'<p style="font-size: 1.1em; font-weight:bold; color:{home_color};">{home_val_str}</p>', unsafe_allow_html=True)
            c2.markdown(f'<p style="text-align:center;">{stat_name_es}</p>', unsafe_allow_html=True)
            c3.markdown(f'<p style="text-align:right; font-size: 1.1em; font-weight:bold; color:{away_color};">{away_val_str}</p>', unsafe_allow_html=True)
        else:
            c1, c2, c3 = st.columns([2, 3, 2]); c2.markdown(f'<p style="text-align:center; color:grey;">{stat_name_es} (no disp.)</p>', unsafe_allow_html=True)
    st.markdown("---")

def display_previous_match_progression_stats(title: str, match_id_str: str | None, home_name: str, away_name: str):
    if not match_id_str or not isinstance(match_id_str, str) or not match_id_str.isdigit():
        st.caption(f"ℹ️ _ID inválido para obtener estadísticas de progresión para: {title}_")
        return
    st.markdown(f"###### 👁️ _Est. Progresión para: {title}_")
    display_match_progression_stats_view(match_id_str, home_name, away_name)

@st.cache_data(ttl=3600)
def get_rival_a_for_original_h2h_of(main_match_id: int):
    soup_h2h_page = fetch_soup_requests_of(f"/match/h2h-{main_match_id}")
    if soup_h2h_page and (table := soup_h2h_page.find("table", id="table_v1")):
        for row in table.find_all("tr", id=re.compile(r"tr1_\d+")):
            if row.get("vs") == "1" and (key_match_id_for_h2h_url := row.get("index")):
                if (onclicks := row.find_all("a", onclick=True)) and len(onclicks) > 1 and onclicks[1].get("onclick"):
                    rival_tag = onclicks[1]
                    if (rival_a_id_match := re.search(r"team\((\d+)\)", rival_tag.get("onclick", ""))) and (rival_a_name := rival_tag.text.strip()):
                        return key_match_id_for_h2h_url, rival_a_id_match.group(1), rival_a_name
    return None, None, None

@st.cache_data(ttl=3600)
def get_rival_b_for_original_h2h_of(main_match_id: int):
    soup_h2h_page = fetch_soup_requests_of(f"/match/h2h-{main_match_id}")
    if soup_h2h_page and (table := soup_h2h_page.find("table", id="table_v2")):
        for row in table.find_all("tr", id=re.compile(r"tr2_\d+")):
            if row.get("vs") == "1" and (match_id_of_rival_b_game := row.get("index")):
                if (onclicks := row.find_all("a", onclick=True)) and onclicks and onclicks[0].get("onclick"):
                    rival_tag = onclicks[0]
                    if (rival_b_id_match := re.search(r"team\((\d+)\)", rival_tag.get("onclick", ""))) and (rival_b_name := rival_tag.text.strip()):
                        return match_id_of_rival_b_game, rival_b_id_match.group(1), rival_b_name
    return None, None, None

@st.cache_resource
def get_selenium_driver_of():
    options = ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36")
    options.add_argument('--blink-settings=imagesEnabled=false')
    options.add_argument("--window-size=1920,1080")
    try:
        # Esto asume que estás en Streamlit Cloud y tienes `chromium-chromedriver` en packages.txt
        service = webdriver.chrome.service.Service(executable_path='/usr/bin/chromedriver')
        return webdriver.Chrome(service=service, options=options)
    except WebDriverException as e:
        st.error(f"Error inicializando Selenium driver (OF): {e}"); return None

def get_h2h_details_for_original_logic_of(driver_instance, key_match_id_for_h2h_url, rival_a_id, rival_b_id, rival_a_name="Rival A", rival_b_name="Rival B"):
    if not all([driver_instance, key_match_id_for_h2h_url, rival_a_id, rival_b_id]): return {"status": "error", "resultado": f"N/A (Datos incompletos para H2H)"}
    url_to_visit = f"{BASE_URL_OF}/match/h2h-{key_match_id_for_h2h_url}"
    try:
        driver_instance.get(url_to_visit)
        WebDriverWait(driver_instance, SELENIUM_TIMEOUT_SECONDS_OF).until(EC.presence_of_element_located((By.ID, "table_v2")))
        time.sleep(0.7)
        soup_selenium = BeautifulSoup(driver_instance.page_source, "html.parser")
        if not soup_selenium or not (table := soup_selenium.find("table", id="table_v2")): return {"status": "error", "resultado": f"N/A (Tabla H2H no encontrada)"}
        for row in table.find_all("tr", id=re.compile(r"tr2_\d+")):
            links = row.find_all("a", onclick=True)
            if len(links) >= 2 and (home_id_m := re.search(r"team\((\d+)\)", links[0].get("onclick",""))) and (away_id_m := re.search(r"team\((\d+)\)", links[1].get("onclick",""))):
                if {home_id_m.group(1), away_id_m.group(1)} == {str(rival_a_id), str(rival_b_id)}:
                    if (score_span := row.find("span", class_="fscore_2")) and "-" in score_span.text:
                        score_val = score_span.text.strip().split("(")[0].strip(); g_h, g_a = score_val.split("-", 1)
                        tds = row.find_all("td"); handicap_raw = tds[11].get("data-o", tds[11].text.strip()) or "N/A"
                        return {"status": "found", "goles_home": g_h.strip(), "goles_away": g_a.strip(), "handicap": handicap_raw, "h2h_home_team_name": links[0].text.strip(), "h2h_away_team_name": links[1].text.strip(), "match_id": row.get('index')}
    except Exception as e: return {"status": "error", "resultado": f"N/A (Error Selenium en {type(e).__name__})"}
    return {"status": "not_found", "resultado": f"H2H directo no encontrado para {rival_a_name} vs {rival_b_name}."}

def get_team_league_info_from_script_of(soup):
    script_tag = soup.find("script", string=re.compile(r"var _matchInfo\s*="))
    if script_tag and (script_content := script_tag.string):
        h_id = (m.group(1) for m in [re.search(r"hId:\s*parseInt\('(\d+)'\)", script_content)] if m)
        g_id = (m.group(1) for m in [re.search(r"gId:\s*parseInt\('(\d+)'\)", script_content)] if m)
        s_id = (m.group(1) for m in [re.search(r"sclassId:\s*parseInt\('(\d+)'\)", script_content)] if m)
        h_n = (m.group(1).replace("\\'", "'") for m in [re.search(r"hName:\s*'([^']*)'", script_content)] if m)
        g_n = (m.group(1).replace("\\'", "'") for m in [re.search(r"gName:\s*'([^']*)'", script_content)] if m)
        l_n = (m.group(1).replace("\\'", "'") for m in [re.search(r"lName:\s*'([^']*)'", script_content)] if m)
        return next(h_id, None), next(g_id, None), next(s_id, None), next(h_n, "N/A"), next(g_n, "N/A"), next(l_n, "N/A")
    return (None,) * 3 + ("N/A",) * 3

def click_element_robust_of(driver, by, value, timeout=7):
    try:
        element = WebDriverWait(driver, timeout).until(EC.visibility_of_element_located((by, value)))
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element); time.sleep(0.3)
        element.click()
        return True
    except:
        try: # Fallback a click con JS
            driver.execute_script("arguments[0].click();", driver.find_element(by, value))
            return True
        except: return False

def extract_last_match_in_league_of(driver, table_css_id_str, main_team_name, league_id_filter, home_or_away_selector, is_home_game_filter):
    try:
        if league_id_filter and not click_element_robust_of(driver, By.CSS_SELECTOR, f"input#checkboxleague{table_css_id_str[-1]}[value='{league_id_filter}']"): return None
        if not click_element_robust_of(driver, By.CSS_SELECTOR, home_or_away_selector): return None
        time.sleep(1.0)
        soup_updated = BeautifulSoup(driver.page_source, "html.parser")
        if not (table := soup_updated.find("table", id=table_css_id_str)): return None
        for row in table.find_all("tr", id=re.compile(rf"tr{table_css_id_str[-1]}_\d+")):
            if "display:none" not in row.get("style", "") and (not league_id_filter or row.get("name") == str(league_id_filter)):
                details = get_match_details_from_row_of(row, score_class_selector=f'fscore_{table_css_id_str[-1]}')
                if details:
                    is_correct_localia = (is_home_game_filter and main_team_name.lower() == details['home'].lower()) or \
                                         (not is_home_game_filter and main_team_name.lower() == details['away'].lower())
                    if is_correct_localia:
                        return {"date": row.find("td").text.strip(), **details}
    except Exception: return None
    return None
    
# --- (Otras funciones de extracción como get_main_match_odds, etc. se mantienen)
def get_main_match_odds_selenium_of(driver):
    odds_info = {"ah_home_cuota": "N/A", "ah_linea_raw": "N/A", "ah_away_cuota": "N/A", "goals_over_cuota": "N/A", "goals_linea_raw": "N/A", "goals_under_cuota": "N/A"}
    try:
        live_compare_div = WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS_OF).until(EC.presence_of_element_located((By.ID, "liveCompareDiv")))
        bet365_row_selector = "tr#tr_o_1_8[name='earlyOdds'], tr#tr_o_1_31[name='earlyOdds']"
        bet365_row = WebDriverWait(driver, 5).until(EC.visibility_of_element_located((By.CSS_SELECTOR, bet365_row_selector)))
        tds = bet365_row.find_elements(By.TAG_NAME, "td")
        if len(tds) >= 11:
            odds_info.update({
                "ah_home_cuota": tds[2].get_attribute("data-o") or "N/A", "ah_linea_raw": tds[3].get_attribute("data-o") or "N/A", "ah_away_cuota": tds[4].get_attribute("data-o") or "N/A",
                "goals_over_cuota": tds[8].get_attribute("data-o") or "N/A", "goals_linea_raw": tds[9].get_attribute("data-o") or "N/A", "goals_under_cuota": tds[10].get_attribute("data-o") or "N/A"
            })
    except: pass
    return odds_info

def extract_standings_data_from_h2h_page_of(h2h_soup, target_team_name_exact):
    data = {"name": target_team_name_exact, "ranking": "N/A", "total_pj": "N/A", "total_v": "N/A", "total_e": "N/A", "total_d": "N/A", "total_gf": "N/A", "total_gc": "N/A", "specific_pj": "N/A", "specific_v": "N/A", "specific_e": "N/A", "specific_d": "N/A", "specific_gf": "N/A", "specific_gc": "N/A", "specific_type": "N/A"}
    if not h2h_soup or not target_team_name_exact: return data
    standings_section = h2h_soup.find("div", id="porletP4")
    if not standings_section: return data
    for div_class, table_class, specific_type in [("home-div", "team-home", "Est. como Local"), ("guest-div", "team-guest", "Est. como Visitante")]:
        team_div = standings_section.find("div", class_=div_class)
        if team_div and (header := team_div.find("tr", class_=table_class)) and target_team_name_exact.lower() in header.get_text(strip=True).lower():
            team_table_soup = team_div.find("table")
            data["specific_type"] = specific_type
            if header_link := header.find("a"):
                full_text = header_link.get_text(separator=" ", strip=True)
                if rank_match := re.search(r"\[(?:[^\]]+-)?(\d+)\]", full_text): data["ranking"] = rank_match.group(1)
            in_ft = False
            for row in team_table_soup.find_all("tr", align="center"):
                if (th := row.find("th")) and "FT" in th.get_text(): in_ft = True
                elif th and "HT" in th.get_text(): break
                elif in_ft:
                    cells = row.find_all("td")
                    if len(cells) > 6:
                        row_type = cells[0].get_text(strip=True)
                        stats = [c.get_text(strip=True) or "N/A" for c in cells[1:7]]
                        if row_type == "Total": data.update(zip(["total_pj", "total_v", "total_e", "total_d", "total_gf", "total_gc"], stats))
                        elif row_type in ["Home", "Away"]: data.update(zip(["specific_pj", "specific_v", "specific_e", "specific_d", "specific_gf", "specific_gc"], stats))
            return data
    return data

def extract_final_score_of(soup):
    try:
        if score_divs := soup.select('#mScore .end .score'):
            if len(score_divs) == 2 and (hs := score_divs[0].text.strip()).isdigit() and (aws := score_divs[1].text.strip()).isdigit():
                return f"{hs}:{aws}", f"{hs}-{aws}"
    except: pass
    return '?:?', "?-?"

def extract_h2h_data_of(soup, main_home_team_name, main_away_team_name, current_league_id):
    data = {'ah1': '-', 'res1': '?:?', 'match1_id': None, 'ah6': '-', 'res6': '?:?', 'match6_id': None, 'h2h_gen_home_name': "N/A", 'h2h_gen_away_name': "N/A"}
    if not soup or not (h2h_table := soup.find("table", id="table_v3")): return tuple(data.values())
    filtered_list = [d for r in h2h_table.find_all("tr", id=re.compile(r"tr3_\d+")) if (d := get_match_details_from_row_of(r, 'fscore_3')) and (not current_league_id or not d.get('league_id_hist') or d.get('league_id_hist') == str(current_league_id))]
    if filtered_list:
        h2h_gen = filtered_list[0]
        data.update({'ah6': h2h_gen.get('ahLine', '-'), 'res6': h2h_gen.get('score', '?:?'), 'match6_id': h2h_gen.get('matchIndex'), 'h2h_gen_home_name': h2h_gen.get('home'), 'h2h_gen_away_name': h2h_gen.get('away')})
        h2h_spec = next((d for d in filtered_list if d.get('home','').lower() == main_home_team_name.lower() and d.get('away','').lower() == main_away_team_name.lower()), None)
        if h2h_spec: data.update({'ah1': h2h_spec.get('ahLine', '-'), 'res1': h2h_spec.get('score', '?:?'), 'match1_id': h2h_spec.get('matchIndex')})
    return tuple(data.values())

def extract_comparative_match_of(soup, table_id, team_name, opponent_name, league_id, is_home_table):
    if not all([soup, table_id, team_name, opponent_name]): return None
    table = soup.find("table", id=table_id)
    if not table: return None
    score_class = 'fscore_1' if is_home_table else 'fscore_2'
    for row in table.find_all("tr", id=re.compile(rf"tr{table_id[-1]}_\d+")):
        details = get_match_details_from_row_of(row, score_class)
        if details and (not league_id or not details.get('league_id_hist') or details.get('league_id_hist') == str(league_id)):
            home_lower, away_lower = details.get('home','').lower(), details.get('away','').lower()
            team_lower, opp_lower = team_name.lower(), opponent_name.lower()
            if (team_lower == home_lower and opp_lower == away_lower) or (team_lower == away_lower and opp_lower == home_lower):
                return {"score": details['score'], "ah_line": details['ahLine'], "localia": 'H' if team_lower == home_lower else 'A', "home_team": details['home'], "away_team": details['away'], "match_id": details['matchIndex']}
    return None

# --- STREAMLIT APP UI ---
def display_other_feature_ui():
    st.markdown("""<style>...</style>""", unsafe_allow_html=True)  # Tu CSS
    st.sidebar.image("https://raw.githubusercontent.com/streamlit/docs/main/public/images/brand/streamlit-logo-secondary-colormark-darktext.svg", width=200)
    st.sidebar.title("⚙️ Configuración del Partido (OF)")
    main_match_id_str_input_of = st.sidebar.text_input("🆔 ID Partido Principal:", "2696131", key="other_feature_match_id_input")
    analizar_button_of = st.sidebar.button("🚀 Analizar Partido (OF)", type="primary", use_container_width=True)

    if analizar_button_of:
        if not main_match_id_str_input_of or not main_match_id_str_input_of.isdigit():
            st.error("⚠️ El ID de partido ingresado no es válido."); st.stop()
        main_match_id_to_process_of = int(main_match_id_str_input_of)

        with st.spinner("🔄 Cargando y analizando datos... Por favor, espere."):
            start_time_of = time.time()
            # --- FASE 1: EXTRACCIÓN RÁPIDA (REQUESTS) ---
            soup_main = fetch_soup_requests_of(f"/match/h2h-{main_match_id_to_process_of}")
            if not soup_main:
                st.error(f"❌ No se pudo obtener la página H2H para ID {main_match_id_to_process_of}."); st.stop()

            home_id, away_id, league_id, home_name, away_name, league_name = get_team_league_info_from_script_of(soup_main)
            home_standings = extract_standings_data_from_h2h_page_of(soup_main, home_name)
            away_standings = extract_standings_data_from_h2h_page_of(soup_main, away_name)
            display_home_name = home_standings.get("name", home_name) or "Local"
            display_away_name = away_standings.get("name", away_name) or "Visitante"

            # --- FASE 2: EXTRACCIÓN LENTA (SELENIUM) ---
            driver = get_selenium_driver_of()
            main_odds, last_home_match, last_away_match, h2h_rivals_details = {}, None, None, {}
            if driver:
                try:
                    driver.get(f"{BASE_URL_OF}/match/h2h-{main_match_id_to_process_of}")
                    WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.ID, "table_v1")))
                    main_odds = get_main_match_odds_selenium_of(driver)
                    last_home_match = extract_last_match_in_league_of(driver, "table_v1", display_home_name, league_id, "input#cb_sos1", True)
                    last_away_match = extract_last_match_in_league_of(driver, "table_v2", display_away_name, league_id, "input#cb_sos2", False)
                    key_id_rival_a, rival_a_id, rival_a_name = get_rival_a_for_original_h2h_of(main_match_id_to_process_of)
                    key_id_rival_b, rival_b_id, rival_b_name = get_rival_b_for_original_h2h_of(main_match_id_to_process_of)
                    if all([key_id_rival_a, rival_a_id, rival_b_id]):
                        h2h_rivals_details = get_h2h_details_for_original_logic_of(driver, key_id_rival_a, rival_a_id, rival_b_id, rival_a_name, rival_b_name)
                except Exception as e:
                    st.warning(f"❗ Error de Selenium durante la extracción: {e}")

            # --- FASE 3: PROCESAMIENTO FINAL DE DATOS ---
            final_score, _ = extract_final_score_of(soup_main)
            ah1, res1, _, match1_id, ah6, res6, _, match6, gen_home, gen_away = extract_h2h_data_of(soup_main, display_home_name, display_away_name, league_id)
            comp_L_v_UVA = extract_comparative_match_of(soup_main, "table_v1", display_home_name, last_away_match.get('home_team') if last_away_match else None, league_id, True) if last_away_match else None
            comp_V_v_ULH = extract_comparative_match_of(soup_main, "table_v2", display_away_name, last_home_match.get('away_team') if last_home_match else None, league_id, False) if last_home_match else None
            
            # RENDERIZACIÓN DE UI (CON EL NUEVO DISEÑO)
            # Título y Clasificación
            st.markdown(f"<p class='main-title'>...</p>", unsafe_allow_html=True)
            #... tu código de clasificación ...

            # Sección Análisis Detallado
            with st.expander("⚖️ Cuotas Iniciales ..."):
                #...

            st.markdown("<h3 class='section-header' ...>⚡ Rendimiento Reciente ...</h3>")
            #... tu código de rendimiento reciente ...
            
            st.divider()
            
            # ---- CÓDIGO H2H MEJORADO INSERTADO AQUÍ ----
            with st.expander("🔰 Hándicaps y Resultados Clave (H2H Directos)", expanded=True):
                st.markdown("<h4 class='card-subtitle'>Último Enfrentamiento con Localía Actual</h4>", unsafe_allow_html=True)
                if res1 and res1 != '?:?':
                    with st.container(border=True):
                        st.markdown(f"**<span class='home-color'>{display_home_name}</span> vs <span class='away-color'>{display_away_name}</span>**", unsafe_allow_html=True)
                        st.markdown(f"### <span class='score-value'>{res1.replace('*',':')}</span>", unsafe_allow_html=True)
                        st.markdown(f"**Hándicap Asiático:** <span class='ah-value'>{ah1 if ah1 != '-' else PLACEHOLDER_NODATA}</span>", unsafe_allow_html=True)
                        if match1_id:
                            display_previous_match_progression_stats("Estadísticas de este partido:", match1_id, display_home_name, display_away_name)
                        else:
                            st.caption("_Estadísticas de progresión no disponibles (sin ID)._")
                else:
                    st.info(f"No se encontraron datos de un H2H anterior con {display_home_name} como local.")

                st.markdown("<hr style='margin: 25px 0;'>", unsafe_allow_html=True)

                st.markdown("<h4 class='card-subtitle'>Último Enfrentamiento General</h4>", unsafe_allow_html=True)
                if res6 and res6 != '?:?':
                    with st.container(border=True):
                        st.markdown(f"**<span class='home-color'>{gen_home}</span> vs <span class='away-color'>{gen_away}</span>**", unsafe_allow_html=True)
                        st.markdown(f"### <span class='score-value'>{res6.replace('*',':')}</span>", unsafe_allow_html=True)
                        st.markdown(f"**Hándicap Asiático:** <span class='ah-value'>{ah6 if ah6 != '-' else PLACEHOLDER_NODATA}</span>", unsafe_allow_html=True)
                        if match6:
                            display_previous_match_progression_stats("Estadísticas de este partido:", match6, gen_home, gen_away)
                        else:
                            st.caption("_Estadísticas de progresión no disponibles (sin ID)._")
                else:
                    st.info("No se encontraron datos del último H2H general.")
            
            st.divider()

            st.sidebar.success(f"🎉 Análisis completado en {time.time() - start_time_of:.2f} segundos.")

if __name__ == '__main__':
    st.set_page_config(layout="wide", page_title="Análisis Avanzado de Partidos (OF)")
    if 'driver_other_feature' not in st.session_state:
        st.session_state.driver_other_feature = None
    display_other_feature_ui()
