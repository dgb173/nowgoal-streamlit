# modules/estudio.py
import streamlit as st
import time
import requests
import re
import math
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
# Importaciones de Selenium
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, ElementClickInterceptedException, NoSuchElementException

# --- CONFIGURACIÓN GLOBAL ---
BASE_URL_OF = "https://live18.nowgoal25.com"
SELENIUM_TIMEOUT_SECONDS_OF = 10 
SELENIUM_POLL_FREQUENCY_OF = 0.2
PLACEHOLDER_NODATA = "*(No disponible)*"

# --- FUNCIONES HELPER PARA PARSEO Y FORMATEO (LÓGICA CORREGIDA) ---
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
            val1 = float(p1_str)
            val2 = float(p2_str)
            if val1 < 0 and not p2_str.startswith('-') and val2 > 0:
                 val2 = -abs(val2)
            elif original_starts_with_minus and val1 == 0.0 and \
                 (p1_str == "0" or p1_str == "-0") and \
                 not p2_str.startswith('-') and val2 > 0:
                val2 = -abs(val2)
            return (val1 + val2) / 2.0
        else:
            return float(s)
    except (ValueError, IndexError):
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
        home_idx, score_idx, away_idx, ah_idx = 2, 3, 4, 11
        if len(cells) <= ah_idx: return None

        date_span = cells[1].find('span', attrs={'name': 'timeData'})
        date_txt = date_span.get_text(strip=True) if date_span else ''

        def get_cell_txt(idx):
            a = cells[idx].find('a')
            return a.get_text(strip=True) if a else cells[idx].get_text(strip=True)
        home, away = get_cell_txt(home_idx), get_cell_txt(away_idx)
        if not home or not away: return None

        score_cell = cells[score_idx]
        score_span = score_cell.find('span', class_=lambda c: isinstance(c, str) and score_class_selector in c)
        score_raw_text = (score_span.get_text(strip=True) if score_span else score_cell.get_text(strip=True)) or ''
        m = re.search(r'(\d+)\s*-\s*(\d+)', score_raw_text)
        score_raw, score_fmt = (f"{m.group(1)}-{m.group(2)}", f"{m.group(1)}:{m.group(2)}") if m else ('?-?', '?:?')

        ah_cell = cells[ah_idx]
        ah_line_raw = (ah_cell.get('data-o') or ah_cell.text).strip()
        ah_line_fmt = format_ah_as_decimal_string_of(ah_line_raw) if ah_line_raw not in ['', '-'] else '-'

        return {
            'date': date_txt, 'home': home, 'away': away, 'score': score_fmt,
            'score_raw': score_raw, 'ahLine': ah_line_fmt, 'ahLine_raw': ah_line_raw or '-',
            'matchIndex': row_element.get('index'), 'vs': row_element.get('vs'),
            'league_id_hist': row_element.get('name')
        }
    except Exception:
        return None

# --- SESIÓN Y FETCHING ---
@st.cache_resource
def get_requests_session_of():
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36"})
    return session

@st.cache_data(ttl=7200)
def get_match_progression_stats_data(match_id: str) -> pd.DataFrame | None:
    if not match_id or not match_id.isdigit(): return None
    url = f"https://live18.nowgoal25.com/match/live-{match_id}"
    try:
        session = get_requests_session_of()
        response = session.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'lxml')
        
        stat_titles = {"Shots": "-", "Shots on Goal": "-", "Attacks": "-", "Dangerous Attacks": "-"}
        team_tech_div = soup.find('div', id='teamTechDiv_detail')
        if team_tech_div and (stat_list := team_tech_div.find('ul', class_='stat')):
            for li in stat_list.find_all('li'):
                if (title_span := li.find('span', class_='stat-title')) and (stat_title := title_span.get_text(strip=True)) in stat_titles:
                    values = [v.get_text(strip=True) for v in li.find_all('span', class_='stat-c')]
                    if len(values) == 2:
                        stat_titles[stat_title] = {"Home": values[0], "Away": values[1]}
        
        table_rows = [{"Estadistica_EN": name, "Casa": vals.get('Home', '-'), "Fuera": vals.get('Away', '-')} for name, vals in stat_titles.items() if isinstance(vals, dict)]
        df = pd.DataFrame(table_rows)
        return df.set_index("Estadistica_EN") if not df.empty else df
    except requests.RequestException:
        return None

def display_match_progression_stats_view(match_id: str, home_team_name: str, away_team_name: str):
    stats_df = get_match_progression_stats_data(match_id)
    if stats_df is None or stats_df.empty:
        st.caption(f"No se encontraron datos de progresión para el partido ID: **{match_id}**.")
        return
    
    ordered_stats = {"Shots": "Disparos", "Shots on Goal": "Disparos a Puerta", "Attacks": "Ataques", "Dangerous Attacks": "Ataques Peligrosos"}
    st.markdown("---")
    col_h, col_s, col_a = st.columns([2, 3, 2])
    col_h.markdown(f"<p style='font-weight:bold; color: #007bff;'>{home_team_name or 'Local'}</p>", unsafe_allow_html=True)
    col_s.markdown("<p style='text-align:center; font-weight:bold;'>Estadística</p>", unsafe_allow_html=True)
    col_a.markdown(f"<p style='text-align:right; font-weight:bold; color: #fd7e14;'>{away_team_name or 'Visitante'}</p>", unsafe_allow_html=True)

    for stat_en, stat_es in ordered_stats.items():
        if stat_en in stats_df.index:
            home_val, away_val = stats_df.loc[stat_en, 'Casa'], stats_df.loc[stat_en, 'Fuera']
            try:
                home_num, away_num = int(home_val), int(away_val)
                home_color, away_color = ("green", "red") if home_num > away_num else (("red", "green") if away_num > home_num else ("black", "black"))
            except (ValueError, TypeError):
                home_color, away_color = "black", "black"
            
            c1, c2, c3 = st.columns([2, 3, 2])
            c1.markdown(f'<p style="font-size: 1.1em; font-weight:bold; color:{home_color};">{home_val}</p>', unsafe_allow_html=True)
            c2.markdown(f'<p style="text-align:center;">{stat_es}</p>', unsafe_allow_html=True)
            c3.markdown(f'<p style="text-align:right; font-size: 1.1em; font-weight:bold; color:{away_color};">{away_val}</p>', unsafe_allow_html=True)
    st.markdown("---")

def display_previous_match_progression_stats(title: str, match_id_str: str | None, home_name: str, away_name: str):
    if not match_id_str or not match_id_str.isdigit():
        st.caption(f"ℹ️ _ID no disponible para obtener estadísticas de: {title}_")
        return
    st.markdown(f"###### 👁️ _Est. Progresión para: {title}_")
    display_match_progression_stats_view(match_id_str, home_name, away_name)

# --- FUNCIONES DE EXTRACCIÓN DE DATOS (CORREGIDAS) ---
def get_rival_a_for_original_h2h_of(soup, league_id=None):
    if not soup or not (table := soup.find("table", id="table_v1")): return None, None, None
    for row in table.find_all("tr", id=re.compile(r"tr1_\d+")):
        if league_id and row.get("name") != str(league_id):
            continue
        if row.get("vs") == "1" and (key_id := row.get("index")):
            onclicks = row.find_all("a", onclick=True)
            if len(onclicks) > 1 and (rival_tag := onclicks[1]) and (rival_id_match := re.search(r"team\((\d+)\)", rival_tag.get("onclick", ""))):
                return key_id, rival_id_match.group(1), rival_tag.text.strip()
    return None, None, None

def get_rival_b_for_original_h2h_of(soup, league_id=None):
    if not soup or not (table := soup.find("table", id="table_v2")): return None, None, None
    for row in table.find_all("tr", id=re.compile(r"tr2_\d+")):
        if league_id and row.get("name") != str(league_id):
            continue
        if row.get("vs") == "1" and (key_id := row.get("index")):
            onclicks = row.find_all("a", onclick=True)
            if len(onclicks) > 0 and (rival_tag := onclicks[0]) and (rival_id_match := re.search(r"team\((\d+)\)", rival_tag.get("onclick", ""))):
                return key_id, rival_id_match.group(1), rival_tag.text.strip()
    return None, None, None

@st.cache_resource
def get_selenium_driver_of():
    options = ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36")
    options.add_argument('--blink-settings=imagesEnabled=false')
    options.add_argument("--window-size=1920,1080")
    try:
        return webdriver.Chrome(options=options)
    except WebDriverException as e:
        st.error(f"Error inicializando Selenium driver (OF): {e}")
        return None

def get_h2h_details_for_original_logic_of(driver, key_match_id, rival_a_id, rival_b_id, rival_a_name="Rival A", rival_b_name="Rival B"):
    if not all([driver, key_match_id, rival_a_id, rival_b_id]):
        return {"status": "error", "resultado": "N/A (Datos incompletos para H2H)"}
    url = f"{BASE_URL_OF}/match/h2h-{key_match_id}"
    try:
        driver.get(url)
        WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS_OF).until(EC.presence_of_element_located((By.ID, "table_v2")))
        try:
            select = Select(WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.ID, "hSelect_2"))))
            select.select_by_value("8")
            time.sleep(0.5) # Espera para refresco de JS
        except TimeoutException: pass
        soup = BeautifulSoup(driver.page_source, "lxml")
    except Exception as e:
        return {"status": "error", "resultado": f"N/A (Error Selenium en H2H Col3: {type(e).__name__})"}

    if not (table := soup.find("table", id="table_v2")):
        return {"status": "error", "resultado": "N/A (Tabla H2H Col3 no encontrada)"}

    for row in table.find_all("tr", id=re.compile(r"tr2_\d+")):
        links = row.find_all("a", onclick=True)
        if len(links) < 2: continue
        h_id_m = re.search(r"team\((\d+)\)", links[0].get("onclick", "")); a_id_m = re.search(r"team\((\d+)\)", links[1].get("onclick", ""))
        if not (h_id_m and a_id_m): continue
        h_id, a_id = h_id_m.group(1), a_id_m.group(1)

        if {h_id, a_id} == {str(rival_a_id), str(rival_b_id)}:
            if not (score_span := row.find("span", class_="fscore_2")) or "-" not in score_span.text: continue
            score = score_span.text.strip().split("(")[0].strip()
            g_h, g_a = score.split("-", 1)
            
            tds = row.find_all("td")
            handicap_raw = "N/A"
            if len(tds) > 11:
                cell = tds[11]
                handicap_raw = (cell.get("data-o") or cell.text).strip() or "N/A"

            return {
                "status": "found", "goles_home": g_h.strip(), "goles_away": g_a.strip(),
                "handicap": handicap_raw, "match_id": row.get('index'),
                "h2h_home_team_name": links[0].text.strip(), "h2h_away_team_name": links[1].text.strip()
            }
    return {"status": "not_found", "resultado": f"H2H directo no encontrado para {rival_a_name} vs {rival_b_name}."}

def get_team_league_info_from_script_of(soup):
    script_tag = soup.find("script", string=re.compile(r"var _matchInfo ="))
    if not (script_tag and script_tag.string): return (None,) * 3 + ("N/A",) * 3
    content = script_tag.string
    def find_val(pattern):
        match = re.search(pattern, content)
        return match.group(1).replace("\\'", "'") if match else None
    home_id = find_val(r"hId:\s*parseInt\('(\d+)'\)")
    away_id = find_val(r"gId:\s*parseInt\('(\d+)'\)")
    league_id = find_val(r"sclassId:\s*parseInt\('(\d+)'\)")
    home_name = find_val(r"hName:\s*'([^']*)'") or "N/A"
    away_name = find_val(r"gName:\s*'([^']*)'") or "N/A"
    league_name = find_val(r"lName:\s*'([^']*)'") or "N/A"
    return home_id, away_id, league_id, home_name, away_name, league_name

def _parse_date_ddmmyyyy(d: str) -> tuple:
    m = re.search(r'(\d{2})-(\d{2})-(\d{4})', d or '')
    return (int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else (1900, 1, 1)

def extract_last_match_in_league_of(soup, table_id, team_name, league_id, is_home_game):
    if not soup or not (table := soup.find("table", id=table_id)): return None
    
    candidate_matches = []
    score_selector = 'fscore_1' if is_home_game else 'fscore_2'
    for row in table.find_all("tr", id=re.compile(rf"tr{table_id[-1]}_\d+")):
        if not (details := get_match_details_from_row_of(row, score_class_selector=score_selector, source_table_type='hist')):
            continue
        if league_id and details.get("league_id_hist") != str(league_id):
            continue
        
        is_team_home = team_name.lower() in details.get('home', '').lower()
        is_team_away = team_name.lower() in details.get('away', '').lower()
        if (is_home_game and is_team_home) or (not is_home_game and is_team_away):
            candidate_matches.append(details)

    if not candidate_matches: return None
    candidate_matches.sort(key=lambda x: _parse_date_ddmmyyyy(x.get('date', '')), reverse=True)
    last_match = candidate_matches[0]

    return {
        "date": last_match.get('date', 'N/A'), "home_team": last_match.get('home'),
        "away_team": last_match.get('away'), "score": last_match.get('score_raw', 'N/A').replace('-', ':'),
        "handicap_line_raw": last_match.get('ahLine_raw', 'N/A'), "match_id": last_match.get('matchIndex')
    }

# --- NUEVA FUNCIÓN DE EXTRACCIÓN DE CUOTAS ---
def extract_bet365_initial_odds_of(soup):
    """
    Extrae un diccionario completo con las cuotas iniciales de Bet365 usando BeautifulSoup.
    """
    odds_info = {
        "ah_home_cuota": "N/A", "ah_linea_raw": "N/A", "ah_away_cuota": "N/A",
        "goals_over_cuota": "N/A", "goals_linea_raw": "N/A", "goals_under_cuota": "N/A"
    }
    if not soup:
        return odds_info

    # Busca la fila de Bet365 por sus posibles IDs
    bet365_row = soup.select_one("tr#tr_o_1_8[name='earlyOdds'], tr#tr_o_1_31[name='earlyOdds']")
    
    if not bet365_row:
        return odds_info

    tds = bet365_row.find_all("td")
    
    if len(tds) >= 11:
        # Extraer datos de Handicap Asiático
        odds_info["ah_home_cuota"] = tds[2].get("data-o", tds[2].text).strip()
        odds_info["ah_linea_raw"] = tds[3].get("data-o", tds[3].text).strip()
        odds_info["ah_away_cuota"] = tds[4].get("data-o", tds[4].text).strip()
        
        # Extraer datos de Goles (Over/Under)
        odds_info["goals_over_cuota"] = tds[8].get("data-o", tds[8].text).strip()
        odds_info["goals_linea_raw"] = tds[9].get("data-o", tds[9].text).strip()
        odds_info["goals_under_cuota"] = tds[10].get("data-o", tds[10].text).strip()
        
    return odds_info

def extract_standings_data_from_h2h_page_of(soup, team_name):
    data = {"name": team_name, "ranking": "N/A", "total_pj": "N/A", "total_v": "N/A", "total_e": "N/A", "total_d": "N/A", "total_gf": "N/A", "total_gc": "N/A", "specific_pj": "N/A", "specific_v": "N/A", "specific_e": "N/A", "specific_d": "N/A", "specific_gf": "N/A", "specific_gc": "N/A", "specific_type": "N/A"}
    if not soup or not team_name or not (standings_section := soup.find("div", id="porletP4")): return data

    team_table_soup, is_home_table = (None, False)
    if (home_div := standings_section.find("div", class_="home-div")) and (header := home_div.find("tr", class_="team-home")) and team_name.lower() in header.get_text(strip=True).lower():
        team_table_soup, is_home_table, data["specific_type"] = home_div.find("table"), True, "Est. como Local (en Liga)"
    elif (guest_div := standings_section.find("div", class_="guest-div")) and (header := guest_div.find("tr", class_="team-guest")) and team_name.lower() in header.get_text(strip=True).lower():
        team_table_soup, is_home_table, data["specific_type"] = guest_div.find("table"), False, "Est. como Visitante (en Liga)"
    if not team_table_soup: return data

    if (header_link := team_table_soup.find("tr", class_=re.compile(r"team-(home|guest)")).find("a")):
        full_text = header_link.get_text(separator=" ", strip=True)
        if (rank_match := re.search(r"\[(?:[^\]]+-)?(\d+)\]", full_text)): data["ranking"] = rank_match.group(1)

    in_ft = False
    for row in team_table_soup.find_all("tr", align="center"):
        if th := row.find("th"):
            in_ft = "FT" in th.get_text(strip=True)
            if "HT" in th.get_text(strip=True): break
            continue
        if in_ft and len(cells := row.find_all("td")) >= 7:
            row_type = (cells[0].find("span") or cells[0]).get_text(strip=True)
            stats = [cell.get_text(strip=True) or "N/A" for cell in cells[1:7]]
            pj, v, e, d, gf, gc = stats
            if row_type == "Total":
                data.update({"total_pj": pj, "total_v": v, "total_e": e, "total_d": d, "total_gf": gf, "total_gc": gc})
            elif (row_type == "Home" and is_home_table) or (row_type == "Away" and not is_home_table):
                data.update({"specific_pj": pj, "specific_v": v, "specific_e": e, "specific_d": d, "specific_gf": gf, "specific_gc": gc})
    return data

def extract_final_score_of(soup):
    try:
        scores = soup.select('#mScore .end .score')
        if len(scores) == 2 and scores[0].text.strip().isdigit() and scores[1].text.strip().isdigit():
            hs, aws = scores[0].text.strip(), scores[1].text.strip()
            return f"{hs}:{aws}", f"{hs}-{aws}"
    except Exception: pass
    return '?:?', '?-?'

def extract_h2h_data_of(soup, home_name, away_name, league_id=None):
    results = {'ah1': '-', 'res1': '?:?', 'res1_raw': '?-?', 'match1_id': None, 'ah6': '-', 'res6': '?:?', 'res6_raw': '?-?', 'match6_id': None, 'h2h_gen_home': "Local (H2H Gen)", 'h2h_gen_away': "Visitante (H2H Gen)"}
    if not soup or not home_name or not away_name or not (h2h_table := soup.find("table", id="table_v3")):
        return results

    all_matches = []
    for r in h2h_table.find_all("tr", id=re.compile(r"tr3_\d+")):
        if (d := get_match_details_from_row_of(r, score_class_selector='fscore_3', source_table_type='h2h')):
            if not league_id or (d.get('league_id_hist') and d.get('league_id_hist') == str(league_id)):
                all_matches.append(d)
    
    if not all_matches: return results
    all_matches.sort(key=lambda x: _parse_date_ddmmyyyy(x.get('date', '')), reverse=True)

    most_recent = all_matches[0]
    results.update({'ah6': most_recent.get('ahLine', '-'), 'res6': most_recent.get('score', '?:?'), 'res6_raw': most_recent.get('score_raw', '?-?'), 'match6_id': most_recent.get('matchIndex'), 'h2h_gen_home': most_recent.get('home'), 'h2h_gen_away': most_recent.get('away')})

    for d in all_matches:
        if d['home'].lower() == home_name.lower() and d['away'].lower() == away_name.lower():
            results.update({'ah1': d.get('ahLine', '-'), 'res1': d.get('score', '?:?'), 'res1_raw': d.get('score_raw', '?-?'), 'match1_id': d.get('matchIndex')})
            break
    return results

def extract_comparative_match_of(soup, table_id, main_team, opponent, league_id, is_home_table):
    if not opponent or opponent == "N/A" or not main_team or not (table := soup.find("table", id=table_id)): return None
    
    score_selector = 'fscore_1' if is_home_table else 'fscore_2'
    for row in table.find_all("tr", id=re.compile(rf"tr{table_id[-1]}_\d+")):
        if not (details := get_match_details_from_row_of(row, score_class_selector=score_selector, source_table_type='hist')): continue
        if league_id and details.get('league_id_hist') and details.get('league_id_hist') != str(league_id): continue
        
        h, a = details.get('home','').lower(), details.get('away','').lower()
        main, opp = main_team.lower(), opponent.lower()
        if (main == h and opp == a) or (main == a and opp == h):
            return {"score": details.get('score', '?:?'), "ah_line": details.get('ahLine', '-'), "localia": 'H' if main == h else 'A', "home_team": details.get('home'), "away_team": details.get('away'), "match_id": details.get('matchIndex')}
    return None

# --- STREAMLIT APP UI (Función principal) ---
def display_other_feature_ui2():
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

    query_params = st.query_params
    initial_match_id = query_params.get("match_id", ["2696131"])[0]
    main_match_id_str_input = st.sidebar.text_input("🆔 ID Partido Principal:", value=initial_match_id, help="Pega el ID numérico del partido.", key="other_feature_match_id_input")
    analizar_button = st.sidebar.button("🚀 Analizar Partido (OF)", type="primary", use_container_width=True)
    results_container = st.container()

    if 'driver_other_feature' not in st.session_state:
        st.session_state.driver_other_feature = None

    if analizar_button:
        results_container.empty()
        main_match_id = "".join(filter(str.isdigit, main_match_id_str_input))
        if not main_match_id:
            results_container.warning("⚠️ Por favor, ingresa un ID de partido válido."); st.stop()

        start_time = time.time()
        with results_container, st.spinner("🔄 Optimizando carga y extrayendo datos..."):
            driver = st.session_state.get('driver_other_feature') or get_selenium_driver_of()
            st.session_state.driver_other_feature = driver
            if not driver:
                st.error("❌ No se pudo inicializar el WebDriver. El análisis no puede continuar."); st.stop()

            main_page_url = f"{BASE_URL_OF}/match/h2h-{main_match_id}"
            try:
                driver.get(main_page_url)
                WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "table_v1")))
                for select_id in ["hSelect_1", "hSelect_2", "hSelect_3"]:
                    try:
                        Select(WebDriverWait(driver, 2).until(EC.presence_of_element_located((By.ID, select_id)))).select_by_value("8")
                        time.sleep(0.1)
                    except TimeoutException: continue
                soup_completo = BeautifulSoup(driver.page_source, "lxml")
            except Exception as e:
                st.error(f"❌ Error crítico durante la carga de la página: {e}"); st.stop()

            if not soup_completo:
                st.error("❌ No se pudo obtener el contenido de la página."); st.stop()

        with st.spinner("🧠 Procesando datos y realizando análisis en paralelo..."):
            home_id, away_id, league_id, home_name, away_name, _ = get_team_league_info_from_script_of(soup_completo)
            
            home_standings = extract_standings_data_from_h2h_page_of(soup_completo, home_name)
            away_standings = extract_standings_data_from_h2h_page_of(soup_completo, away_name)
            # --- LLAMADA CORREGIDA ---
            key_match_id_rival_a, rival_a_id, rival_a_name = get_rival_a_for_original_h2h_of(soup_completo, league_id)
            _, rival_b_id, rival_b_name = get_rival_b_for_original_h2h_of(soup_completo, league_id)
            last_home_match = extract_last_match_in_league_of(soup_completo, "table_v1", home_name, league_id, True)
            last_away_match = extract_last_match_in_league_of(soup_completo, "table_v2", away_name, league_id, False)
            h2h_data = extract_h2h_data_of(soup_completo, home_name, away_name, None)
            comp_L_vs_UV_A = extract_comparative_match_of(soup_completo, "table_v1", home_name, (last_away_match or {}).get('home_team'), league_id, True)
            comp_V_vs_UL_H = extract_comparative_match_of(soup_completo, "table_v2", away_name, (last_home_match or {}).get('away_team'), league_id, False)
            final_score, _ = extract_final_score_of(soup_completo)
            
            main_match_odds_data = extract_bet365_initial_odds_of(soup_completo)

            with ThreadPoolExecutor(max_workers=8) as executor:
                future_h2h_col3 = executor.submit(get_h2h_details_for_original_logic_of, driver, key_match_id_rival_a, rival_a_id, rival_b_id, rival_a_name, rival_b_name)
                details_h2h_col3 = future_h2h_col3.result()

            # --- RENDERIZACIÓN DE LA UI ---
            st.markdown(f"<h1 class='main-title'>Análisis de Partido Avanzado (OF)</h1>", unsafe_allow_html=True)
            st.markdown(f"<p class='sub-title'><span class='home-color'>{home_name}</span> vs <span class='away-color'>{away_name}</span></p>", unsafe_allow_html=True)

            with st.expander("📊 Clasificación en Liga", expanded=True):
                scol1, scol2 = st.columns(2)
                
                def display_standings(col, data, team_color_class):
                    with col:
                        st.markdown(f"<h4 class='card-title' style='text-align: center;'><span class='{team_color_class}'>{data['name']}</span></h4>", unsafe_allow_html=True)
                        if data and data['ranking'] != 'N/A':
                            st.markdown(f"<p style='text-align: center;'><strong>Posición:</strong> <span class='data-highlight'>{data['ranking']}</span></p>", unsafe_allow_html=True)
                            st.markdown("<h6>Estadísticas Totales</h6>", unsafe_allow_html=True)
                            st.markdown(f"**PJ:** {data['total_pj']} | **V-E-D:** {data['total_v']}-{data['total_e']}-{data['total_d']} | **GF:GC:** {data['total_gf']}:{data['total_gc']}")
                            st.markdown(f"<h6>{data.get('specific_type', 'Específicas')}</h6>", unsafe_allow_html=True)
                            st.markdown(f"**PJ:** {data['specific_pj']} | **V-E-D:** {data['specific_v']}-{data['specific_e']}-{data['specific_d']} | **GF:GC:** {data['specific_gf']}:{data['specific_gc']}")
                        else:
                            st.info("Datos de clasificación no disponibles.")

                display_standings(scol1, home_standings, "home-color")
                display_standings(scol2, away_standings, "away-color")

            st.markdown("<h2 class='section-header'>🎯 Análisis Detallado del Partido</h2>", unsafe_allow_html=True)
            
            with st.expander("⚖️ Cuotas Iniciales (Bet365) y Marcador Final", expanded=True):
                o_col1, o_col2 = st.columns(2)
               
                o_col1.metric(
                    "AH (Línea Inicial)",
                    format_ah_as_decimal_string_of(main_match_odds_data.get('ah_linea_raw', '?')) or PLACEHOLDER_NODATA)
                
                o_col2.metric(
                    "Goles (Línea Inicial)",
                    format_ah_as_decimal_string_of(main_match_odds_data.get('goals_linea_raw', '?')) or PLACEHOLDER_NODATA)


            st.markdown("<h3 class='section-header' style='font-size:1.5em; margin-top:30px;'>⚡ Rendimiento Reciente y H2H Indirecto</h3>", unsafe_allow_html=True)
            rp_col1, rp_col2, rp_col3 = st.columns(3)
            with rp_col1:
                st.markdown(f"<h4 class='card-title'>Último <span class='home-color'>{home_name}</span> (Casa)</h4>", unsafe_allow_html=True)
                if last_home_match:
                    res = last_home_match
                    st.markdown(f"<div style='margin: 8px 0;'><span class='home-color'>{res['home_team']}</span> <span class='score-value'>{res['score']}</span> <span class='away-color'>{res['away_team']}</span></div>", unsafe_allow_html=True)
                    st.markdown(f"**AH:** <span class='ah-value'>{format_ah_as_decimal_string_of(res.get('handicap_line_raw','-'))}</span>", unsafe_allow_html=True)
                    display_previous_match_progression_stats(f"Últ. {res.get('home_team','L')} vs {res.get('away_team','V')}", res.get('match_id'), res.get('home_team'), res.get('away_team'))
                else: st.info(f"No se encontró último partido en casa para {home_name}.")
            with rp_col2:
                st.markdown(f"<h4 class='card-title'>Último <span class='away-color'>{away_name}</span> (Fuera)</h4>", unsafe_allow_html=True)
                if last_away_match:
                    res = last_away_match
                    st.markdown(f"<div style='margin: 8px 0;'><span class='home-color'>{res['home_team']}</span> <span class='score-value'>{res['score']}</span> <span class='away-color'>{res['away_team']}</span></div>", unsafe_allow_html=True)
                    st.markdown(f"**AH:** <span class='ah-value'>{format_ah_as_decimal_string_of(res.get('handicap_line_raw','-'))}</span>", unsafe_allow_html=True)
                    display_previous_match_progression_stats(f"Últ. {res.get('away_team','V')} vs {res.get('home_team','L')}", res.get('match_id'), res.get('home_team'), res.get('away_team'))
                else: st.info(f"No se encontró último partido fuera para {away_name}.")
            with rp_col3:
                st.markdown(f"<h4 class='card-title'>🆚 H2H Rivales (Col3)</h4>", unsafe_allow_html=True)
                if details_h2h_col3.get("status") == "found":
                    res = details_h2h_col3
                    h_name, a_name = res.get('h2h_home_team_name'), res.get('h2h_away_team_name')
                    st.markdown(f"<span class='home-color'>{h_name}</span> <span class='score-value'>{res.get('goles_home', '?')}:{res.get('goles_away', '?')}</span> <span class='away-color'>{a_name}</span>", unsafe_allow_html=True)
                    st.markdown(f"**AH:** <span class='ah-value'>{format_ah_as_decimal_string_of(res.get('handicap','-'))}</span>", unsafe_allow_html=True)
                    display_previous_match_progression_stats(f"H2H Col3: {h_name} vs {a_name}", res.get('match_id'), h_name, a_name)
                else: st.info(details_h2h_col3.get('resultado', "No disponible."))

            st.divider()
            with st.expander("🔁 Comparativas Indirectas Detalladas", expanded=True):
                def display_comp(col, title_html, data, main_team_name):
                    with col:
                        st.markdown(f"<h5 class='card-subtitle'>{title_html}</h5>", unsafe_allow_html=True)
                        if data:
                            st.markdown(f"⚽ **Res:** <span class='data-highlight'>{data['score']}</span> ({data.get('home_team')} vs {data.get('away_team')})", unsafe_allow_html=True)
                            st.markdown(f"⚖️ **AH:** <span class='ah-value'>{format_ah_as_decimal_string_of(data.get('ah_line', '-'))}</span>", unsafe_allow_html=True)
                            st.markdown(f"🏟️ **Localía de '{main_team_name}':** <span class='data-highlight'>{data.get('localia', '-')}</span>", unsafe_allow_html=True)
                            display_previous_match_progression_stats(f"Comp: {data.get('home_team')} vs {data.get('away_team')}", data.get('match_id'), data.get('home_team'), data.get('away_team'))
                        else: st.info("Comparativa no disponible.")
                
                comp_col1, comp_col2 = st.columns(2)
                title1 = f"<span class='home-color'>{home_name}</span> vs. <span class='away-color'>Últ. Rival de {away_name}</span>"
                title2 = f"<span class='away-color'>{away_name}</span> vs. <span class='home-color'>Últ. Rival de {home_name}</span>"
                display_comp(comp_col1, title1, comp_L_vs_UV_A, home_name)
                display_comp(comp_col2, title2, comp_V_vs_UL_H, away_name)

            st.divider()
         with st.expander("🔰 Hándicaps y Resultados Clave (H2H Directos)", expanded=True):
                h2h_col1, h2h_col2 = st.columns(2)
                with h2h_col1:
                    st.metric("Ultimo partido entre los dos equipos en este estadio", h2h_data['ah1'] if h2h_data['ah1'] != '-' else PLACEHOLDER_NODATA)
                    st.metric("Resultado del ultimo partido entre los dos equipos en este estadio", h2h_data['res1'] if h2h_data['res1'] != '?:?' else PLACEHOLDER_NODATA)
                    if h2h_data['match1_id']:
                        display_previous_match_progression_stats(f"H2H: {home_name} (C) vs {away_name}", h2h_data['match1_id'], home_name, away_name)
                with h2h_col2:
                    st.metric("Ultimo Enfrentamiento entre ellos", h2h_data['ah6'] if h2h_data['ah6'] != '-' else PLACEHOLDER_NODATA)
                    st.metric("Resultado ultimo enfrentamiento entre ellos", h2h_data['res6'] if h2h_data['res6'] != '?:?' else PLACEHOLDER_NODATA)
                    if h2h_data['match6_id']:
                        display_previous_match_progression_stats(f"H2H Gen: {h2h_data['h2h_gen_home']} vs {h2h_data['h2h_gen_away']}", h2h_data['match6_id'], h2h_data['h2h_gen_home'], h2h_data['h2h_gen_away'])
            
            st.divider()
            st.sidebar.success(f"🎉 Análisis completado en {time.time() - start_time:.2f} segundos.")
    else:
        results_container.info("✨ ¡Bienvenido! Ingresa un ID de partido y haz clic en 'Analizar Partido (OF)'.")

if __name__ == '__main__':
    st.set_page_config(layout="wide", page_title="Análisis Avanzado de Partidos (OF)", initial_sidebar_state="expanded")
    display_other_feature_ui2()
