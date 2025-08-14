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
# ... (Mantén las importaciones y configuración global)

def get_match_details_from_row_of(row_element, score_class_selector='score', source_table_type='h2h'):
    try:
        cells = row_element.find_all('td')

        # índices fijos en table_v3
        home_idx, score_idx, away_idx = 2, 3, 4
        ah_idx = 11  # 12º <td> => índice 11

        if len(cells) <= ah_idx:
            return None

        league_id_hist_attr = row_element.get('name')
        match_id = row_element.get('index')
        vs_flag = row_element.get('vs')

        # --- fecha (texto visible del span[name=timeData]) ---
        date_span = cells[1].find('span', attrs={'name': 'timeData'})
        date_txt = date_span.get_text(strip=True) if date_span else ''

        # --- equipos ---
        def get_cell_txt(idx):
            a = cells[idx].find('a')
            return a.get_text(strip=True) if a else cells[idx].get_text(strip=True)

        home = get_cell_txt(home_idx)
        away = get_cell_txt(away_idx)
        if not home or not away:
            return None

        # --- marcador ---
        score_cell = cells[score_idx]
        score_span = score_cell.find('span', class_=lambda c: isinstance(c, str) and score_class_selector in c)
        score_raw_text = (score_span.get_text(strip=True) if score_span else score_cell.get_text(strip=True)) or ''
        m = re.search(r'(\d+)\s*-\s*(\d+)', score_raw_text)
        if m:
            score_raw = f"{m.group(1)}-{m.group(2)}"
            score_fmt = f"{m.group(1)}:{m.group(2)}"
        else:
            score_raw, score_fmt = '?-?', '?:?'

        # --- AH línea ---
        ah_cell = cells[ah_idx]
        ah_line_raw = (ah_cell.get('data-o') or ah_cell.text).strip()
        # si el <td> existe pero está vacío, lo dejamos como '-'
        ah_line_fmt = format_ah_as_decimal_string_of(ah_line_raw) if ah_line_raw not in ['', '-'] else '-'

        return {
            'date': date_txt,                 # <- importante para ordenar por “último”
            'home': home,
            'away': away,
            'score': score_fmt,
            'score_raw': score_raw,
            'ahLine': ah_line_fmt,
            'ahLine_raw': ah_line_raw if ah_line_raw else '-',
            'matchIndex': match_id,
            'vs': vs_flag,
            'league_id_hist': row_element.get('name')
        }
    except Exception:
        return None



#

# ... (Mantén el resto del código sin cambios)
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
            resp = session.get(url, timeout=10)
            resp.raise_for_status()
            # Usa lxml para mayor velocidad
            return BeautifulSoup(resp.text, "lxml")
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
        st.caption(f"ℹ️ _No hay ID de partido para obtener estadísticas de progresión para: {title}_")
        return
    st.markdown(f"###### 👁️ _Est. Progresión para: {title}_")
    display_match_progression_stats_view(match_id_str, home_name, away_name)
# --- FUNCIONES DE EXTRACCIÓN DE DATOS DEL PARTIDO (Selenium y BeautifulSoup) ---
def get_rival_a_for_original_h2h_of(soup_h2h_page):
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
def get_rival_b_for_original_h2h_of(soup_h2h_page):
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
        WebDriverWait(driver_instance, SELENIUM_TIMEOUT_SECONDS_OF).until(EC.presence_of_element_located((By.ID, "table_v2")))
        try:
            select_element = WebDriverWait(driver_instance, 5).until(EC.presence_of_element_located((By.ID, "hSelect_2")))
            table_v2_element = driver_instance.find_element(By.ID, "table_v2")
            Select(select_element).select_by_value("8")
            WebDriverWait(driver_instance, 10).until(EC.staleness_of(table_v2_element))
            WebDriverWait(driver_instance, 10).until(EC.presence_of_element_located((By.ID, "table_v2")))
        except (TimeoutException, NoSuchElementException):
            pass
        soup_selenium = BeautifulSoup(driver_instance.page_source, "html.parser")
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
    try:
        element = WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.presence_of_element_located((by, value)))
        WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.visibility_of(element))
        driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'center'});", element); time.sleep(0.3)
        try: WebDriverWait(driver, 2, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.element_to_be_clickable((by, value))).click()
        except (ElementClickInterceptedException, TimeoutException): driver.execute_script("arguments[0].click();", element)
        return True
    except Exception: return False
def extract_last_match_in_league_of(soup_de_la_pagina, table_css_id_str, main_team_name_in_table, league_id_filter_value, is_home_game_filter):
    """
    Versión optimizada que NO usa Selenium.
    Filtra los datos directamente desde el objeto soup de la página principal.
    """
    if not soup_de_la_pagina:
        return None

    table = soup_de_la_pagina.find("table", id=table_css_id_str)
    if not table:
        return None

    # Obtenemos TODOS los partidos y los ordenaremos por fecha para encontrar el último
    partidos_candidatos = []

    # Extraemos todos los detalles de las filas de una vez
    score_class_selector = 'fscore_1' if table_css_id_str == 'table_v1' else 'fscore_2'
    for row in table.find_all("tr", id=re.compile(rf"tr{table_css_id_str[-1]}_\d+")):
        details = get_match_details_from_row_of(row, score_class_selector=score_class_selector, source_table_type='hist')
        if not details:
            continue

        # 1. Filtro por Liga (si se proporciona)
        if league_id_filter_value and details.get("league_id_hist") != str(league_id_filter_value):
            continue

        # 2. Filtro por Localía (si el equipo es local o visitante)
        team_is_home_in_row = main_team_name_in_table.lower() in details.get('home', '').lower()
        team_is_away_in_row = main_team_name_in_table.lower() in details.get('away', '').lower()

        if (is_home_game_filter and team_is_home_in_row) or \
           (not is_home_game_filter and team_is_away_in_row):
            partidos_candidatos.append(details)

    if not partidos_candidatos:
        return None

    # 3. Ordenamos por fecha para encontrar el más reciente
    partidos_candidatos.sort(key=lambda x: _parse_date_ddmmyyyy(x.get('date', '')), reverse=True)

    ultimo_partido = partidos_candidatos[0]

    return {
        "date": ultimo_partido.get('date', 'N/A'),
        "home_team": ultimo_partido.get('home'),
        "away_team": ultimo_partido.get('away'),
        "score": ultimo_partido.get('score_raw', 'N/A').replace('-', ':'),
        "handicap_line_raw": ultimo_partido.get('ahLine_raw', 'N/A'),
        "match_id": ultimo_partido.get('matchIndex')
    }
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
        if header_tr and header_tr.find("a") and target_team_name_exact.lower() in header_tr.find("a").get_text(strip=True).lower():
            team_table_soup = home_div.find("table", class_="team-table-home")
            is_home_table_type = True
            data["specific_type"] = "Est. como Local (en Liga)"
    # If not found in home-div, check guest-div
    if not team_table_soup:
        guest_div = standings_section.find("div", class_="guest-div")
        if guest_div:
            header_tr = guest_div.find("tr", class_="team-guest")
            if header_tr and header_tr.find("a") and target_team_name_exact.lower() in header_tr.find("a").get_text(strip=True).lower():
                team_table_soup = guest_div.find("table", class_="team-table-guest")
                is_home_table_type = False
                data["specific_type"] = "Est. como Visitante (en Liga)"
    if not team_table_soup: return data # Team not found in either div
    # Extract name and ranking from the found table's header
    header_link = team_table_soup.find("tr", class_=re.compile(r"team-(home|guest)")).find("a")
    if header_link:
        full_text = header_link.get_text(separator=" ", strip=True)
        name_match = re.search(r"]\s*(.*)", full_text)
        rank_match = re.search(r"\[(?:[^\]]+-)?(\d+)\]", full_text)
        if name_match: data["name"] = name_match.group(1).strip()
        if rank_match: data["ranking"] = rank_match.group(1)
    # Extract stats (FT only)
    in_ft_section = False
    for row in team_table_soup.find_all("tr", align="center"):
        th_header = row.find("th")
        if th_header:
            if "FT" in th_header.get_text(strip=True):
                in_ft_section = True
                continue # Skip the FT header row itself
            elif "HT" in th_header.get_text(strip=True):
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
# MODIFICADO: Función para extraer el último partido en casa para un equipo específico
def extract_last_home_match_of(soup, team_name, current_league_id=None):
    """
    Extract the last home match for a specific team from the H2H table.

    Args:
        soup: BeautifulSoup object of the H2H page
        team_name: Name of the team to find the home match for
        current_league_id: Optional league ID to filter matches by league

    Returns:
        A dictionary containing the date, score, handicap line, and match ID of the last home match
    """
    h2h_table = soup.find("table", id="table_v3")
    if not h2h_table:
        return None

    # Find all rows in the table
    match_rows = h2h_table.find_all("tr", id=re.compile(r"tr3_\d+"))

    # Filter for rows where the team is the home team
    home_team_rows = []
    for row in match_rows:
        # Check if the team is the home team (has the class "team-home-f")
        home_team_cell = row.find('span', class_='team-home-f', text=team_name)
        if home_team_cell:
            details = get_match_details_from_row_of(row, score_class_selector='fscore_3', source_table_type='h2h')
            if details:
                home_team_rows.append(details)

    if not home_team_rows:
        return None

    # Sort by date (most recent first)
    def get_date(details):
        return _parse_date_ddmmyyyy(details.get('date', ''))

    home_team_rows.sort(key=get_date, reverse=True)

    most_recent_row = home_team_rows[0]

    # Extract the required information
    return {
        'date': most_recent_row.get('date', 'N/A'),
        'result': most_recent_row.get('score', 'N/A'),
        'result_raw': most_recent_row.get('score_raw', 'N/A'),
        'handicap_line': most_recent_row.get('ahLine', 'N/A'),
        'handicap_line_raw': most_recent_row.get('ahLine_raw', 'N/A'),
        'match_id': most_recent_row.get('matchIndex', 'N/A')
    }

# ... (Mantén el resto del código sin cambios)
def extract_final_score_of(soup):
    try:
        score_divs = soup.select('#mScore .end .score')
        if len(score_divs) == 2:
            hs = score_divs[0].text.strip(); aws = score_divs[1].text.strip()
            if hs.isdigit() and aws.isdigit(): return f"{hs}:{aws}", f"{hs}-{aws}", f"{hs}:{aws}" # MODIFICADO para usar ':'
    except Exception: pass
    return '?:?', '?-?', '?:?'
# MODIFICADO: para devolver nombres del H2H general
def _parse_date_ddmmyyyy(d: str) -> tuple:
    # Convierte "dd-mm-aaaa" a tupla (aaaa, mm, dd) para ordenar; si no, muy antiguo
    m = re.search(r'(\d{2})-(\d{2})-(\d{4})', d or '')
    if not m:
        return (1900, 1, 1)
    return (int(m.group(3)), int(m.group(2)), int(m.group(1)))

def extract_h2h_data_of(soup, main_home_team_name, main_away_team_name, current_league_id=None):
    """
    Devuelve:
      ah1, res1, res1_raw, match1_id,
      ah6, res6, res6_raw, match6_id,
      h2h_gen_home_name, h2h_gen_away_name

    - NO filtra por liga cuando current_league_id es None (recomendado).
    - El 'último partido en casa' del local se elige por fecha (más reciente).
    """
    ah1, res1, res1_raw, match1_id = '-', '?:?', '?-?', None
    ah6, res6, res6_raw, match6_id = '-', '?:?', '?-?', None
    h2h_gen_home_name, h2h_gen_away_name = "Local (H2H Gen)", "Visitante (H2H Gen)"

    if not soup or not main_home_team_name or not main_away_team_name:
        return ah1, res1, res1_raw, match1_id, ah6, res6, res6_raw, match6_id, h2h_gen_home_name, h2h_gen_away_name

    h2h_table = soup.find("table", id="table_v3")
    if not h2h_table:
        return ah1, res1, res1_raw, match1_id, ah6, res6, res6_raw, match6_id, h2h_gen_home_name, h2h_gen_away_name

    rows = h2h_table.find_all("tr", id=re.compile(r"tr3_\d+"))
    details_list = []
    for r in rows:
        d = get_match_details_from_row_of(r, score_class_selector='fscore_3', source_table_type='h2h')
        if not d:
            continue
        if current_league_id and d.get('league_id_hist') and d.get('league_id_hist') != str(current_league_id):
            # Si se pasa liga, filtra; si es None, NO filtra
            continue
        details_list.append(d)

    if not details_list:
        return ah1, res1, res1_raw, match1_id, ah6, res6, res6_raw, match6_id, h2h_gen_home_name, h2h_gen_away_name

    # H2H directo: local principal vs visitante principal
    for d in details_list:
        if d['home'].lower() == main_home_team_name.lower() and d['away'].lower() == main_away_team_name.lower():
            ah1 = d.get('ahLine', '-')
            res1 = d.get('score', '?:?')
            res1_raw = d.get('score_raw', '?-?')
            match1_id = d.get('matchIndex')
            break

    # Último partido (por fecha) donde el local principal jugó EN CASA (cualquier rival, cualquier liga si current_league_id=None)
    home_rows = [d for d in details_list if d['home'].lower() == main_home_team_name.lower()]
    if home_rows:
        home_rows.sort(key=lambda x: _parse_date_ddmmyyyy(x.get('date', '')), reverse=True)
        last_home = home_rows[0]
        ah6 = last_home.get('ahLine', '-')
        res6 = last_home.get('score', '?:?')
        res6_raw = last_home.get('score_raw', '?-?')
        match6_id = last_home.get('matchIndex')
        h2h_gen_home_name = last_home.get('home', h2h_gen_home_name)
        h2h_gen_away_name = last_home.get('away', h2h_gen_away_name)

    return ah1, res1, res1_raw, match1_id, ah6, res6, res6_raw, match6_id, h2h_gen_home_name, h2h_gen_away_name
def extract_comparative_match_of(soup_for_team_history, table_id_of_team_to_search, team_name_to_find_match_for, opponent_name_to_search, current_league_id, is_home_table):
    if not opponent_name_to_search or opponent_name_to_search == "N/A" or not team_name_to_find_match_for:
        return None
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
            score_val = details.get('score', '?:?')
            ah_line_extracted = details.get('ahLine', '-')
            localia_val = 'H' if team_main_lower == home_hist else 'A'
            return {
                "score": score_val,
                "ah_line": ah_line_extracted,
                "localia": localia_val,
                "home_team": details.get('home'),
                "away_team": details.get('away'),
                "match_id": details.get('matchIndex')
            }
    return None
# --- STREAMLIT APP UI (Función principal) ---
def display_other_feature_ui2():
    # ... (mantén tu bloque de CSS sin cambios)
    st.markdown("""
    <style>
        /* ... Tu CSS ... */
    </style>
    """, unsafe_allow_html=True)

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
        main_match_id_to_process_of = "".join(filter(str.isdigit, main_match_id_str_input_of))
        if not main_match_id_to_process_of:
            results_container.warning("⚠️ Por favor, ingresa un ID de partido válido."); st.stop()

        start_time_of = time.time()
        with results_container, st.spinner("🔄 Optimizando carga: extrayendo todos los datos en un solo paso..."):

            # --- LÓGICA DE SELENIUM MINIMIZADA ---
            driver_actual_of = st.session_state.get('driver_other_feature')
            # ... (la lógica de inicialización del driver está bien, la mantenemos) ...

            if driver_actual_of is None: # Simplificamos la comprobación
                 driver_actual_of = get_selenium_driver_of()
                 st.session_state.driver_other_feature = driver_actual_of

            if not driver_actual_of:
                st.error("❌ No se pudo inicializar el WebDriver. El análisis no puede continuar."); st.stop()

            soup_completo = None
            main_page_url_h2h_view_of = f"{BASE_URL_OF}/match/h2h-{main_match_id_to_process_of}"

            try:
                driver_actual_of.get(main_page_url_h2h_view_of)
                # Espera un elemento clave para asegurar que la página base está cargada
                WebDriverWait(driver_actual_of, 10).until(EC.presence_of_element_located((By.ID, "table_v1")))

                # Interacciones rápidas (si son necesarias)
                for select_id in ["hSelect_1", "hSelect_2", "hSelect_3"]:
                    try:
                        Select(WebDriverWait(driver_actual_of, 2).until(EC.presence_of_element_located((By.ID, select_id)))).select_by_value("8")
                        time.sleep(0.1) # Pequeña pausa para el refresco de JS
                    except TimeoutException:
                        continue # Si no encuentra un select, no es crítico

                # Extraemos el HTML UNA SOLA VEZ
                soup_completo = BeautifulSoup(driver_actual_of.page_source, "lxml")

            except Exception as e:
                st.error(f"❌ Error crítico durante la obtención de datos con Selenium: {e}"); st.stop()

            if not soup_completo:
                st.error("❌ No se pudo obtener el contenido de la página."); st.stop()

        with st.spinner("🧠 Procesando datos y realizando análisis en paralelo..."):
            # --- EXTRACCIÓN DE DATOS (AHORA MUCHO MÁS RÁPIDA) ---

            # Info principal (muy rápido)
            mp_home_id_of, mp_away_id_of, mp_league_id_of, mp_home_name_from_script, mp_away_name_from_script, mp_league_name_of = get_team_league_info_from_script_of(soup_completo)
            display_home_name = mp_home_name_from_script or "Equipo Local"
            display_away_name = mp_away_name_from_script or "Equipo Visitante"

            # Clasificación (rápido)
            home_team_main_standings = extract_standings_data_from_h2h_page_of(soup_completo, display_home_name)
            away_team_main_standings = extract_standings_data_from_h2h_page_of(soup_completo, display_away_name)

            key_match_id_for_rival_a_h2h, rival_a_id_orig_col3, rival_a_name_orig_col3 = get_rival_a_for_original_h2h_of(soup_completo)
            match_id_rival_b_game_ref, rival_b_id_orig_col3, rival_b_name_orig_col3 = get_rival_b_for_original_h2h_of(soup_completo)

            # Últimos partidos (AHORA SIN SELENIUM, MUY RÁPIDO)
            last_home_match_in_league_of = extract_last_match_in_league_of(soup_completo, "table_v1", display_home_name, mp_league_id_of, True)
            last_away_match_in_league_of = extract_last_match_in_league_of(soup_completo, "table_v2", display_away_name, mp_league_id_of, False)

            # H2H (rápido)
            ah1_val, res1_val, _, match1_id_h2h_v, \
            ah6_val, res6_val, _, match6_id_h2h_g, \
            h2h_gen_home_name, h2h_gen_away_name = extract_h2h_data_of(soup_completo, display_home_name, display_away_name, None)

            # Comparativas (rápido)
            comp_data_L_vs_UV_A = extract_comparative_match_of(soup_completo, "table_v1", display_home_name, (last_away_match_in_league_of or {}).get('home_team'), mp_league_id_of, True)
            comp_data_V_vs_UL_H = extract_comparative_match_of(soup_completo, "table_v2", display_away_name, (last_home_match_in_league_of or {}).get('away_team'), mp_league_id_of, False)

            main_match_odds_data_of = get_main_match_odds_selenium_of(driver_actual_of)

            col_data = { "Fin": "?*?", "AH_Act": "?", "G_i": "?"}
            col_data["Fin"], _, _ = extract_final_score_of(soup_completo)
            col_data["Fin"] = col_data["Fin"].replace("*",":")
            col_data["AH_Act"] = format_ah_as_decimal_string_of(main_match_odds_data_of.get('ah_linea_raw', '?'))
            col_data["G_i"] = format_ah_as_decimal_string_of(main_match_odds_data_of.get('goals_linea_raw', '?'))
            col_data["AH_H2H_V"], col_data["Res_H2H_V"] = ah1_val, res1_val
            col_data["AH_H2H_G"], col_data["Res_H2H_G"] = ah6_val, res6_val

            main_match_odds_data_of = get_main_match_odds_selenium_of(driver_actual_of)

            col_data = { "Fin": "?*?", "AH_Act": "?", "G_i": "?"}
            col_data["Fin"], _, _ = extract_final_score_of(soup_completo)
            col_data["Fin"] = col_data["Fin"].replace("*",":")
            col_data["AH_Act"] = format_ah_as_decimal_string_of(main_match_odds_data_of.get('ah_linea_raw', '?'))
            col_data["G_i"] = format_ah_as_decimal_string_of(main_match_odds_data_of.get('goals_linea_raw', '?'))
            col_data["AH_H2H_V"], col_data["Res_H2H_V"] = ah1_val, res1_val
            col_data["AH_H2H_G"], col_data["Res_H2H_G"] = ah6_val, res6_val

            # --- OPERACIONES LENTAS RESTANTES (EN PARALELO) ---
            match_ids_to_fetch_stats = {
                'last_home': (last_home_match_in_league_of.get('match_id') if last_home_match_in_league_of else None, (last_home_match_in_league_of or {}).get('home_team'), (last_home_match_in_league_of or {}).get('away_team')),
                'last_away': (last_away_match_in_league_of.get('match_id') if last_away_match_in_league_of else None, (last_away_match_in_league_of or {}).get('home_team'), (last_away_match_in_league_of or {}).get('away_team')),
                'h2h_v': (match1_id_h2h_v, display_home_name, display_away_name),
                'h2h_g': (match6_id_h2h_g, h2h_gen_home_name, h2h_gen_away_name),
                'comp_L': (comp_data_L_vs_UV_A.get('match_id') if comp_data_L_vs_UV_A else None, (comp_data_L_vs_UV_A or {}).get('home_team'), (comp_data_L_vs_UV_A or {}).get('away_team')),
                'comp_V': (comp_data_V_vs_UL_H.get('match_id') if comp_data_V_vs_UL_H else None, (comp_data_V_vs_UL_H or {}).get('home_team'), (comp_data_V_vs_UL_H or {}).get('away_team')),
            }

            stats_results = {}
            with ThreadPoolExecutor(max_workers=6) as executor:
                future_to_key = {executor.submit(get_match_progression_stats_data, details[0]): key for key, details in match_ids_to_fetch_stats.items() if details[0]}
                for future in future_to_key:
                    key = future_to_key[future]
                    try:
                        stats_results[key] = future.result()
                    except Exception:
                        stats_results[key] = None

            # --- RENDERIZACIÓN DE LA UI (SIN CAMBIOS, YA ES RÁPIDA) ---
            st.markdown("<h2 class='section-header'>🎯 Análisis Detallado del Partido</h2>", unsafe_allow_html=True)
            with st.expander("⚖️ Cuotas Iniciales (Bet365) y Marcador Final (Partido Principal)", expanded=True):
                final_score_display = col_data["Fin"] if col_data["Fin"] != "?:?" else PLACEHOLDER_NODATA
                st.metric("⚖️ AH (Línea Inicial)", col_data["AH_Act"] if col_data["AH_Act"] != "?" else PLACEHOLDER_NODATA)
                st.metric("🥅 Goles (Línea Inicial)", col_data["G_i"] if col_data["G_i"] != "?" else PLACEHOLDER_NODATA)
            st.markdown("<h3 class='section-header' style='font-size:1.5em; margin-top:30px;'>⚡ Rendimiento Reciente y H2H Indirecto</h3>", unsafe_allow_html=True)
            rp_col1, rp_col2, rp_col3 = st.columns(3)
            with rp_col1:
                st.markdown(f"<h4 class='card-title'>Último <span class='home-color'>{display_home_name}</span> (Casa)</h4>", unsafe_allow_html=True)
                if last_home_match_in_league_of:
                    res = last_home_match_in_league_of
                    st.markdown(f"🆚 <span class='away-color'>{res['away_team']}</span>", unsafe_allow_html=True)
                    st.markdown(f"<div style='margin-top: 8px; margin-bottom: 8px;'><span class='home-color'>{res['home_team']}</span> <span class='score-value'>{res['score'].replace('-',':')}</span> <span class='away-color'>{res['away_team']}</span></div>", unsafe_allow_html=True)
                    formatted_ah_lh = format_ah_as_decimal_string_of(res.get('handicap_line_raw','-'))
                    st.markdown(f"**AH:** <span class='ah-value'>{formatted_ah_lh if formatted_ah_lh != '-' else PLACEHOLDER_NODATA}</span>", unsafe_allow_html=True)
                    st.caption(f"📅 {res.get('date', 'N/A')}")
                    display_previous_match_progression_stats(
                        f"Últ. {res.get('home_team','L')} (C) vs {res.get('away_team','V')}",
                        res.get('match_id'), res.get('home_team','Local'), res.get('away_team','Visitante')
                    )
                else: st.info(f"No se encontró último partido en casa para {display_home_name}.")
            with rp_col2:
                st.markdown(f"<h4 class='card-title'>Último <span class='away-color'>{display_away_name}</span> (Fuera)</h4>", unsafe_allow_html=True)
                if last_away_match_in_league_of:
                    res = last_away_match_in_league_of
                    st.markdown(f"🆚 <span class='home-color'>{res['home_team']}</span>", unsafe_allow_html=True)
                    st.markdown(f"<div style='margin-top: 8px; margin-bottom: 8px;'><span class='home-color'>{res['home_team']}</span> <span class='score-value'>{res['score'].replace('-',':')}</span> <span class='away-color'>{res['away_team']}</span></div>", unsafe_allow_html=True)
                    formatted_ah_la = format_ah_as_decimal_string_of(res.get('handicap_line_raw','-'))
                    st.markdown(f"**AH:** <span class='ah-value'>{formatted_ah_la if formatted_ah_la != '-' else PLACEHOLDER_NODATA}</span>", unsafe_allow_html=True)
                    st.caption(f"📅 {res.get('date', 'N/A')}")
                    display_previous_match_progression_stats(
                        f"Últ. {res.get('away_team','V')} (F) vs {res.get('home_team','L')}",
                        res.get('match_id'), res.get('home_team','Local'), res.get('away_team','Visitante')
                    )
                else: st.info(f"No se encontró último partido fuera para {display_away_name}.")
            with rp_col3:
                st.markdown(f"<h4 class='card-title'>🆚 H2H Rivales (Col3)</h4>", unsafe_allow_html=True)
                details_h2h_col3_of = {"status": "error", "resultado": PLACEHOLDER_NODATA}
                if key_match_id_for_rival_a_h2h and rival_a_id_orig_col3 and rival_b_id_orig_col3 and driver_actual_of:
                    details_h2h_col3_of = get_h2h_details_for_original_logic_of(driver_actual_of, key_match_id_for_rival_a_h2h, rival_a_id_orig_col3, rival_b_id_orig_col3, rival_a_name_orig_col3, rival_b_name_orig_col3)
                if details_h2h_col3_of.get("status") == "found":
                    res_h2h = details_h2h_col3_of
                    h2h_home_name_col3 = res_h2h.get('h2h_home_team_name', 'Local H2H')
                    h2h_away_name_col3 = res_h2h.get('h2h_away_team_name', 'Visitante H2H')
                    st.markdown(f"<span class='home-color'>{h2h_home_name_col3}</span> <span class='score-value'>{res_h2h.get('goles_home', '?')}:{res_h2h.get('goles_away', '?')}</span> <span class='away-color'>{h2h_away_name_col3}</span>", unsafe_allow_html=True)
                    formatted_ah_h2h_col3 = format_ah_as_decimal_string_of(res_h2h.get('handicap','-'))
                    st.markdown(f"**AH:** <span class='ah-value'>{formatted_ah_h2h_col3 if formatted_ah_h2h_col3 != '-' else PLACEHOLDER_NODATA}</span>", unsafe_allow_html=True)
                    display_previous_match_progression_stats(
                        f"H2H Col3: {h2h_home_name_col3} vs {h2h_away_name_col3}",
                        res_h2h.get('match_id'), h2h_home_name_col3, h2h_away_name_col3
                    )
                else: st.info(details_h2h_col3_of.get('resultado', f"H2H Col3 entre {rival_a_name_orig_col3 or 'RivalA'} y {rival_b_name_orig_col3 or 'RivalB'} no encontrado."))
            st.divider()
            with st.expander("🔁 Comparativas Indirectas Detalladas", expanded=True):
                comp_col1, comp_col2 = st.columns(2)
                with comp_col1:
                    st.markdown(f"<h5 class='card-subtitle'><span class='home-color'>{display_home_name}</span> vs. <span class='away-color'>Últ. Rival de {display_away_name}</span></h5>", unsafe_allow_html=True)
                    if comp_data_L_vs_UV_A:
                        data = comp_data_L_vs_UV_A
                        score_part = data['score'].replace('*', ':').strip()
                        ah_val = data.get('ah_line', '-')
                        loc_val = data.get('localia', '-')
                        st.markdown(f"⚽ **Res:** <span class='data-highlight'>{score_part or PLACEHOLDER_NODATA}</span> ({data.get('home_team')} vs {data.get('away_team')})", unsafe_allow_html=True)
                        st.markdown(f"⚖️ **AH:** <span class='ah-value'>{format_ah_as_decimal_string_of(ah_val) or PLACEHOLDER_NODATA}</span>", unsafe_allow_html=True)
                        st.markdown(f"🏟️ **Localía de '{display_home_name}':** <span class='data-highlight'>{loc_val or PLACEHOLDER_NODATA}</span>", unsafe_allow_html=True)
                        display_previous_match_progression_stats(
                            f"Comp: {data.get('home_team','L')} vs {data.get('away_team','V')}",
                            data.get('match_id'), data.get('home_team','Local'), data.get('away_team','Visitante')
                        )
                    else: st.info(f"Comparativa '{display_home_name} vs Últ. Rival de {display_away_name}' no disponible.")
                with comp_col2:
                    st.markdown(f"<h5 class='card-subtitle'><span class='away-color'>{display_away_name}</span> vs. <span class='home-color'>Últ. Rival de {display_home_name}</span></h5>", unsafe_allow_html=True)
                    if comp_data_V_vs_UL_H:
                        data = comp_data_V_vs_UL_H
                        score_part = data['score'].replace('*', ':').strip()
                        ah_val = data.get('ah_line', '-')
                        loc_val = data.get('localia', '-')
                        st.markdown(f"⚽ **Res:** <span class='data-highlight'>{score_part or PLACEHOLDER_NODATA}</span> ({data.get('home_team')} vs {data.get('away_team')})", unsafe_allow_html=True)
                        st.markdown(f"⚖️ **AH:** <span class='ah-value'>{format_ah_as_decimal_string_of(ah_val) or PLACEHOLDER_NODATA}</span>", unsafe_allow_html=True)
                        st.markdown(f"🏟️ **Localía de '{display_away_name}':** <span class='data-highlight'>{loc_val or PLACEHOLDER_NODATA}</span>", unsafe_allow_html=True)
                        display_previous_match_progression_stats(
                            f"Comp: {data.get('home_team','L')} vs {data.get('away_team','V')}",
                            data.get('match_id'), data.get('home_team','Local'), data.get('away_team','Visitante')
                        )
                    else: st.info(f"Comparativa '{display_away_name} vs Últ. Rival de {display_home_name}' no disponible.")
            st.divider()
            with st.expander("🔰 Hándicaps y Resultados Clave (H2H Directos)", expanded=True):
                h2h_direct_col1, h2h_direct_col2 = st.columns(2)
                with h2h_direct_col1:
                    st.metric("AH H2H (Local en Casa)", col_data["AH_H2H_V"] if col_data["AH_H2H_V"] != '-' else PLACEHOLDER_NODATA)
                    st.metric("Res H2H (Local en Casa)", col_data["Res_H2H_V"].replace("*",":") if col_data["Res_H2H_V"] != '?:?' else PLACEHOLDER_NODATA)
                    if match1_id_h2h_v:
                        display_previous_match_progression_stats(
                            f"H2H: {display_home_name} (Casa) vs {display_away_name}",
                            match1_id_h2h_v, display_home_name, display_away_name
                        )
                with h2h_direct_col2:
                    st.metric("AH H2H (Últ. Partido en Casa)", col_data["AH_H2H_G"] if col_data["AH_H2H_G"] != '-' else PLACEHOLDER_NODATA)
                    st.metric("Res H2H (Últ. Partido en Casa)", col_data["Res_H2H_G"].replace("*",":") if col_data["Res_H2H_G"] != '?:?' else PLACEHOLDER_NODATA)
                    if match6_id_h2h_g:
                        display_previous_match_progression_stats(
                            f"H2H: {h2h_gen_home_name} vs {h2h_gen_away_name}",
                            match6_id_h2h_g, h2h_gen_home_name, h2h_gen_away_name
                        )
            st.divider()

            # --- NUEVA SECCIÓN: Resumen para Copiar ---
            st.markdown("<h2 class='section-header'>📋 Resumen de Datos para Copiar</h2>", unsafe_allow_html=True)

            summary_str = []
            summary_str.append(f"Análisis Partido: {display_home_name} vs {display_away_name} (ID: {main_match_id_to_process_of})")
            summary_str.append(f"Liga: {mp_league_name_of}")
            summary_str.append("="*30)

            summary_str.append("\n--- DATOS PRINCIPALES ---")
            summary_str.append(f"Marcador Final: {col_data.get('Fin', 'N/A')}")
            summary_str.append(f"AH (Inicial): {col_data.get('AH_Act', 'N/A')}")
            summary_str.append(f"Línea Goles (Inicial): {col_data.get('G_i', 'N/A')}")

            summary_str.append("\n--- CLASIFICACIÓN ---")
            summary_str.append(f"Local ({display_home_name}): Rank {home_team_main_standings.get('ranking', 'N/A')}")
            summary_str.append(f"  Total: PJ {home_team_main_standings.get('total_pj', 'N/A')}, V {home_team_main_standings.get('total_v', 'N/A')}, E {home_team_main_standings.get('total_e', 'N/A')}, D {home_team_main_standings.get('total_d', 'N/A')}, GF {home_team_main_standings.get('total_gf', 'N/A')}, GC {home_team_main_standings.get('total_gc', 'N/A')}")
            summary_str.append(f"  Específico: PJ {home_team_main_standings.get('specific_pj', 'N/A')}, V {home_team_main_standings.get('specific_v', 'N/A')}, E {home_team_main_standings.get('specific_e', 'N/A')}, D {home_team_main_standings.get('specific_d', 'N/A')}, GF {home_team_main_standings.get('specific_gf', 'N/A')}, GC {home_team_main_standings.get('specific_gc', 'N/A')}")
            summary_str.append(f"Visitante ({display_away_name}): Rank {away_team_main_standings.get('ranking', 'N/A')}")
            summary_str.append(f"  Total: PJ {away_team_main_standings.get('total_pj', 'N/A')}, V {away_team_main_standings.get('total_v', 'N/A')}, E {away_team_main_standings.get('total_e', 'N/A')}, D {away_team_main_standings.get('total_d', 'N/A')}, GF {away_team_main_standings.get('total_gf', 'N/A')}, GC {away_team_main_standings.get('total_gc', 'N/A')}")
            summary_str.append(f"  Específico: PJ {away_team_main_standings.get('specific_pj', 'N/A')}, V {away_team_main_standings.get('specific_v', 'N/A')}, E {away_team_main_standings.get('specific_e', 'N/A')}, D {away_team_main_standings.get('specific_d', 'N/A')}, GF {away_team_main_standings.get('specific_gf', 'N/A')}, GC {away_team_main_standings.get('specific_gc', 'N/A')}")

            summary_str.append("\n--- RENDIMIENTO RECIENTE ---")
            if last_home_match_in_league_of:
                lh = last_home_match_in_league_of
                summary_str.append(f"Último Local (Casa): {lh.get('home_team')} {lh.get('score', 'N/A')} {lh.get('away_team')} | AH: {format_ah_as_decimal_string_of(lh.get('handicap_line_raw','-'))}")
            if last_away_match_in_league_of:
                la = last_away_match_in_league_of
                summary_str.append(f"Último Visitante (Fuera): {la.get('home_team')} {la.get('score', 'N/A')} {la.get('away_team')} | AH: {format_ah_as_decimal_string_of(la.get('handicap_line_raw','-'))}")

            summary_str.append("\n--- H2H ---")
            summary_str.append(f"H2H Directo (Local en casa): {display_home_name} {col_data.get('Res_H2H_V', 'N/A')} {display_away_name} | AH: {col_data.get('AH_H2H_V', 'N/A')}")
            summary_str.append(f"H2H Último Local (Casa): {h2h_gen_home_name} {col_data.get('Res_H2H_G', 'N/A')} {h2h_gen_away_name} | AH: {col_data.get('AH_H2H_G', 'N/A')}")
            if details_h2h_col3_of.get("status") == "found":
                res_h2h = details_h2h_col3_of
                summary_str.append(f"H2H Rivales (Col3): {res_h2h.get('h2h_home_team_name', 'L')} {res_h2h.get('goles_home', '?')}:{res_h2h.get('goles_away', '?')} {res_h2h.get('h2h_away_team_name', 'V')} | AH: {format_ah_as_decimal_string_of(res_h2h.get('handicap','-'))}")

            summary_str.append("\n--- COMPARATIVAS INDIRECTAS ---")
            if comp_data_L_vs_UV_A:
                c = comp_data_L_vs_UV_A
                summary_str.append(f"Local vs Últ. Rival Visitante: {c.get('home_team')} {c.get('score', 'N/A')} {c.get('away_team')} | AH: {c.get('ah_line', 'N/A')}")
            if comp_data_V_vs_UL_H:
                c = comp_data_V_vs_UL_H
                summary_str.append(f"Visitante vs Últ. Rival Local: {c.get('home_team')} {c.get('score', 'N/A')} {c.get('away_team')} | AH: {c.get('ah_line', 'N/A')}")

            st.text_area("Copia y pega este resumen:", "\n".join(summary_str), height=300)

            end_time_of = time.time()
            st.sidebar.success(f"🎉 Análisis completado en {end_time_of - start_time_of:.2f} segundos.")

    else:
        results_container.info("✨ ¡Bienvenido! Ingresa un ID de partido y haz clic en 'Analizar Partido (OF)'.")
if __name__ == '__main__':
    st.set_page_config(layout="wide", page_title="Análisis Avanzado de Partidos (OF)", initial_sidebar_state="expanded")
    if 'driver_other_feature' not in st.session_state:
        st.session_state.driver_other_feature = None
    display_other_feature_ui2()
