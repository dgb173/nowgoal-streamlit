# streamlit_app_enhanced_es.py

import streamlit as st
import time
import requests
import re
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import math # Para las funciones de formato de hándicap

# Importaciones de Selenium
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

# --- CONFIGURACIÓN GLOBAL ---
BASE_URL_STREAMLIT_H2H = "https://live18.nowgoal25.com" # Para la lógica de rivales H2H
BASE_URL_ELDEFINITIVO = "https://live16.nowgoal25.com" # Para la lógica de detalles del partido principal
SELENIUM_TIMEOUT_SECONDS = 20
SELENIUM_TIMEOUT_ELDEFINITIVO = 25 # Puede necesitar más tiempo para la página completa

# --- FUNCIONES DE FORMATEO DE HÁNDICAP (de Eldefinitivo.txt) ---
@st.cache_data(show_spinner=False) # Cachear para rendimiento
def parse_ah_to_number(ah_line_str: str):
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

@st.cache_data(show_spinner=False) # Cachear para rendimiento
def format_ah_as_decimal_string(ah_line_str: str):
    if not isinstance(ah_line_str, str) or not ah_line_str.strip() or ah_line_str.strip() in ['-', '?']:
        return ah_line_str.strip() if isinstance(ah_line_str, str) else '-'
    numeric_value = parse_ah_to_number(ah_line_str)
    if numeric_value is None:
        return ah_line_str.strip() if isinstance(ah_line_str, str) else '-'
    if numeric_value == 0.0: return "0"
    sign = -1 if numeric_value < 0 else 1
    abs_num = abs(numeric_value)
    parte_entera = math.floor(abs_num)
    parte_decimal_original = round(abs_num - parte_entera, 4)
    nueva_parte_decimal = parte_decimal_original
    epsilon = 1e-9
    if abs(parte_decimal_original - 0.25) < epsilon: nueva_parte_decimal = 0.5
    elif abs(parte_decimal_original - 0.75) < epsilon: nueva_parte_decimal = 0.5
    
    if nueva_parte_decimal != 0.0 and nueva_parte_decimal != 0.5:
        if nueva_parte_decimal < 0.25: nueva_parte_decimal = 0.0
        elif nueva_parte_decimal < 0.75: nueva_parte_decimal = 0.5
        else:
             nueva_parte_decimal = 0.0
             parte_entera +=1
    resultado_num_redondeado = parte_entera + nueva_parte_decimal
    final_value_signed = sign * resultado_num_redondeado
    if final_value_signed == 0.0: return "0"
    if abs(final_value_signed - round(final_value_signed)) < epsilon :
        return str(int(round(final_value_signed)))
    else:
        return f"{final_value_signed:.1f}"

# Configuración de la sesión de requests
@st.cache_resource
def get_requests_session():
    session = requests.Session()
    retries_req = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    adapter_req = HTTPAdapter(max_retries=retries_req)
    session.mount("https://", adapter_req)
    session.mount("http://", adapter_req)
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36"})
    return session

# --- FUNCIONES DE REQUESTS (para lógica H2H de rivales) ---
@st.cache_data(ttl=1800, show_spinner=False)
def fetch_soup_requests_h2h_rivals(path, max_tries=3, delay=1):
    session = get_requests_session()
    url = f"{BASE_URL_STREAMLIT_H2H}{path}"
    for attempt in range(1, max_tries + 1):
        try:
            resp = session.get(url, timeout=10)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except requests.RequestException as e:
            if attempt == max_tries:
                st.error(f"Error final de Requests obteniendo {url} para H2H de rivales: {e}")
                return None
            time.sleep(delay * attempt)
    return None

@st.cache_data(ttl=1800, show_spinner=False)
def get_last_home_streamlit(match_id):
    soup = fetch_soup_requests_h2h_rivals(f"/match/h2h-{match_id}")
    if not soup: return None, None, None, None
    table = soup.find("table", id="table_v1")
    home_team_name_tag = soup.select_one("div.home .sclassName a")
    home_team_name = home_team_name_tag.text.strip() if home_team_name_tag else "Equipo Local (Desconocido)"

    if not table: return home_team_name, None, None, None
    for row in table.find_all("tr", id=re.compile(r"tr1_\d+")):
        if row.get("vs") == "1":
            key_match_id = row.get("index")
            if not key_match_id: continue
            onclicks = row.find_all("a", onclick=True)
            if len(onclicks) > 1 and onclicks[1].get("onclick"):
                rival_a_id_match = re.search(r"team\((\d+)\)", onclicks[1]["onclick"])
                rival_a_name = onclicks[1].text.strip() if onclicks[1] else "Rival A (Desconocido)"
                if rival_a_id_match:
                    return home_team_name, key_match_id, rival_a_id_match.group(1), rival_a_name
    return home_team_name, None, None, None

@st.cache_data(ttl=1800, show_spinner=False)
def get_last_away_streamlit(match_id):
    soup = fetch_soup_requests_h2h_rivals(f"/match/h2h-{match_id}")
    if not soup: return None, None, None
    table = soup.find("table", id="table_v2")
    if not table: return None, None, None
    for row in table.find_all("tr", id=re.compile(r"tr2_\d+")):
        if row.get("vs") == "1":
            key_match_id = row.get("index")
            if not key_match_id: continue
            onclicks = row.find_all("a", onclick=True)
            if len(onclicks) > 0 and onclicks[0].get("onclick"):
                rival_b_id_match = re.search(r"team\((\d+)\)", onclicks[0]["onclick"])
                rival_b_name = onclicks[0].text.strip() if onclicks[0] else "Rival B (Desconocido)"
                if rival_b_id_match:
                    return key_match_id, rival_b_id_match.group(1), rival_b_name
    return None, None, None

# --- FUNCIONES DE SELENIUM (adaptadas y combinadas) ---
@st.cache_resource 
def get_selenium_driver_cached():
    options = ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36")
    options.add_argument('--blink-settings=imagesEnabled=false')
    prefs = {"profile.managed_default_content_settings.images": 2, "profile.default_content_setting_values.notifications": 2}
    options.add_experimental_option("prefs", prefs)
    try:
        try:
            from webdriver_manager.chrome import ChromeDriverManager
            from selenium.webdriver.chrome.service import Service as ChromeService
            driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)
        except ImportError:
            st.warning("webdriver-manager no encontrado. Intentando usar ChromeDriver desde el PATH.")
            driver = webdriver.Chrome(options=options)
        return driver
    except WebDriverException as e:
        st.error(f"ERROR CRÍTICO SELENIUM: No se pudo iniciar ChromeDriver. {e}")
        st.error("Asegúrate de que ChromeDriver (o chromium-chromedriver) esté instalado y sea accesible.")
        st.info("Si usas Streamlit Cloud, añade 'chromium-chromedriver' a tu packages.txt. Si es local, asegúrate que ChromeDriver esté en tu PATH o instala 'webdriver-manager'.")
        return None

def get_h2h_details_selenium_streamlit_logic(driver, key_match_id, rival_a_id, rival_b_id):
    if not driver: return {"status": "error", "resultado": "Driver no disponible"}
    if not key_match_id or not rival_a_id or not rival_b_id:
        return {"status": "error", "resultado": "N/A (IDs incompletos para H2H de rivales)"}
    url = f"{BASE_URL_STREAMLIT_H2H}/match/h2h-{key_match_id}"
    soup_selenium = None
    try:
        driver.get(url)
        WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS).until(EC.presence_of_element_located((By.ID, "table_v3")))
        time.sleep(0.75)
        page_source = driver.page_source
        soup_selenium = BeautifulSoup(page_source, "html.parser")
    except TimeoutException:
        try:
            page_source = driver.page_source
            soup_selenium = BeautifulSoup(page_source, "html.parser")
            if not soup_selenium.find("table", id=re.compile(r"table_v\d")):
                 return {"status": "error", "resultado": "N/A (Timeout en Selenium para H2H rivales y sin datos útiles)"}
        except Exception as e_after_timeout:
            st.error(f"Error obteniendo HTML después de Timeout para H2H de rivales: {e_after_timeout}")
            return {"status": "error", "resultado": "N/A (Timeout en Selenium para H2H rivales)"}
    except Exception as e:
        st.error(f"Error durante carga/parseo de Selenium para H2H de rivales en {url}: {e}")
        return {"status": "error", "resultado": f"N/A (Error Selenium: {type(e).__name__})"}

    if not soup_selenium: return {"status": "error", "resultado": "N/A (Fallo al obtener soup con Selenium para H2H rivales)"}
    tables_to_check = [{"id": "table_v3", "row_prefix": "tr3_", "score_class": "fscore_3"},
                       {"id": "table_v1", "row_prefix": "tr1_", "score_class": "fscore_1"},
                       {"id": "table_v2", "row_prefix": "tr2_", "score_class": "fscore_2"}]
    for table_info in tables_to_check:
        table = soup_selenium.find("table", id=table_info["id"])
        if not table: continue
        for row in table.find_all("tr", id=re.compile(rf"{table_info['row_prefix']}\d+")):
            links = row.find_all("a", onclick=True)
            if len(links) < 2: continue
            home_id_match_search = re.search(r"team\((\d+)\)", links[0].get("onclick", ""))
            away_id_match_search = re.search(r"team\((\d+)\)", links[1].get("onclick", ""))
            if not home_id_match_search or not away_id_match_search: continue
            home_id_found, away_id_found = home_id_match_search.group(1), away_id_match_search.group(1)
            if {home_id_found, away_id_found} == {str(rival_a_id), str(rival_b_id)}:
                score_span = row.find("span", class_=table_info["score_class"])
                if not score_span or not score_span.text or "-" not in score_span.text: continue
                score = score_span.text.strip(); 
                try: goles_home, goles_away = score.split("-")
                except ValueError: continue
                tds = row.find_all("td"); handicap_raw = "N/A"
                if len(tds) > 11:
                    celda_handicap = tds[11]
                    data_o_valor = celda_handicap.get("data-o")
                    if data_o_valor is not None and data_o_valor.strip() not in ["", "-"]: handicap_raw = data_o_valor.strip()
                    else:
                        texto_celda = celda_handicap.text.strip()
                        if texto_celda not in ["", "-"]: handicap_raw = texto_celda
                handicap_formatted = format_ah_as_decimal_string(handicap_raw)
                rol_rival_a = "H" if home_id_found == str(rival_a_id) else "A"
                return {"status": "found", "goles_home": goles_home.strip(), "goles_away": goles_away.strip(),
                        "handicap_raw": handicap_raw, "handicap_formatted": handicap_formatted,
                        "rol_rival_a": rol_rival_a,
                        "raw_string_formatted": f"{goles_home.strip()}*{goles_away.strip()}/{handicap_formatted} {rol_rival_a}"}
    return {"status": "not_found", "resultado": f"H2H entre rivales {rival_a_id} y {rival_b_id} no encontrado en {url}"}

# --- FUNCIONES PARA EXTRAER DETALLES DEL PARTIDO PRINCIPAL (Lógica de Eldefinitivo.txt) ---
def extract_main_match_details_definitivo(driver, main_match_id):
    if not driver: return {"status": "error", "message": "Driver no disponible para detalles del partido."}
    url = f"{BASE_URL_ELDEFINITIVO}/match/h2h-{main_match_id}"
    try:
        driver.get(url)
        WebDriverWait(driver, SELENIUM_TIMEOUT_ELDEFINITIVO).until(
             EC.any_of(EC.presence_of_element_located((By.CSS_SELECTOR, '#table_v3')),
                       EC.presence_of_element_located((By.CSS_SELECTOR, 'div.crumbs')),
                       EC.presence_of_element_located((By.CSS_SELECTOR, 'body[errorpage]'))))
        time.sleep(1)
        html = driver.page_source
        if "match not found" in html.lower() or "evento no encontrado" in html.lower() or \
           "the match is not found" in html.lower() or '<body errorpage' in html.lower():
            return {"status": "not_found", "message": f"Partido principal {main_match_id} no encontrado en {BASE_URL_ELDEFINITIVO}."}
        soup = BeautifulSoup(html, 'lxml')
    except TimeoutException:
        st.warning(f"Timeout obteniendo detalles para el partido principal {main_match_id} de {url}. Algunos datos podrían faltar.")
        try:
            html = driver.page_source
            soup = BeautifulSoup(html, 'lxml')
            if not soup.select_one('div.fbheader'):
                 return {"status": "error_timeout_no_data", "message": f"Timeout severo y sin datos para {main_match_id}."}
        except Exception as e_after_timeout:
            return {"status": "error_timeout", "message": f"Timeout y error posterior para {main_match_id}: {e_after_timeout}"}
    except Exception as e_load:
        return {"status": "error_load", "message": f"Error cargando detalles para {main_match_id}: {e_load}"}

    if soup is None: return {"status": "error_soup", "message": "No se pudo parsear la página de detalles del partido."}

    details = {"id": main_match_id, "status": "partial_data",
               "ah_h2h_v_main": "-", "ah_act_main": "-", "res_h2h_v_main": "?*?",
               "ah_l_h_main": "-", "res_l_h_main": "?*?", "ah_v_a_main": "-", "res_v_a_main": "?*?",
               "ah_h2h_g_main": "-", "res_h2h_g_main": "?*?", "l_vs_uv_a_main": "-", "v_vs_ul_h_main": "-",
               "stats_l_main": "N/A", "stats_v_main": "N/A", "fin_main": "?*?", "g_i_main": "-", "league_main": "N/A",
               "home_team_main": "Local Desc.", "away_team_main": "Visitante Desc.", "message": "Extracción iniciada."}
    try:
        home_name_tag = soup.select_one('div.fbheader div.home div.sclassName a') or soup.select_one('div.fbheader div.home div.sclassName')
        away_name_tag = soup.select_one('div.fbheader div.guest div.sclassName a') or soup.select_one('div.fbheader div.guest div.sclassName')
        details["home_team_main"] = home_name_tag.text.strip() if home_name_tag else "Local Desconocido"
        details["away_team_main"] = away_name_tag.text.strip() if away_name_tag else "Visitante Desconocido"
        league_tag = soup.select_one('div.crumbs a[href*="/leagueinfo/"]') or soup.select_one('span.LName span.nosclassLink')
        details["league_main"] = league_tag.text.strip() if league_tag else "Liga Desconocida"
        current_league_id = None
        if league_tag:
            href_val = league_tag.get('href', '')
            onclick_val = league_tag.get('onclick', '')
            id_match_href = re.search(r'leagueinfo/(\d+)', href_val)
            id_match_onclick = re.search(r'leagueinfo/(\d+)', onclick_val)
            if id_match_href: current_league_id = id_match_href.group(1)
            elif id_match_onclick: current_league_id = id_match_onclick.group(1)

        ah_raw_main, goals_raw_main = "?", "?"
        odds_row = soup.select_one('#liveCompareDiv #tr_o_1_8[name="earlyOdds"]') or \
                   soup.select_one('#liveCompareDiv #tr_o_1_31[name="earlyOdds"]') or \
                   soup.select_one('#tr_o_1_8[name="earlyOdds"]')
        if odds_row:
            cells = odds_row.find_all('td')
            if len(cells) > 3: ah_raw_main = cells[3].text.strip()
            if len(cells) > 9: goals_raw_main = cells[9].text.strip()
        details["ah_act_main"] = format_ah_as_decimal_string(ah_raw_main)
        details["g_i_main"] = format_ah_as_decimal_string(goals_raw_main)

        score_divs = soup.select('#mScore .end .score')
        if len(score_divs) == 2 and score_divs[0].text.strip().isdigit() and score_divs[1].text.strip().isdigit():
            details["fin_main"] = f"{score_divs[0].text.strip()}*{score_divs[1].text.strip()}"
        else:
            score_divs_live = soup.select('#mScore .result .score')
            if len(score_divs_live) == 2 and score_divs_live[0].text.strip().isdigit() and score_divs_live[1].text.strip().isdigit():
                 details["fin_main"] = f"{score_divs_live[0].text.strip()}*{score_divs_live[1].text.strip()} (En Vivo)"

        def get_match_details_from_row_definitivo(row_element, score_class_selector='score'):
            cells = row_element.find_all('td')
            if len(cells) < 12: return None
            home_tag = cells[2].find('a'); home = home_tag.text.strip() if home_tag else cells[2].text.strip()
            away_tag = cells[4].find('a'); away = away_tag.text.strip() if away_tag else cells[4].text.strip()
            score_span = cells[3].find('span', class_=lambda x: x and score_class_selector in x)
            score_raw = score_span.text.strip() if score_span else '?-?'
            score_fmt = score_raw.replace('-', '*') if score_raw != '?-?' else '?*?'
            ah_line_raw = cells[11].text.strip()
            ah_line_fmt = format_ah_as_decimal_string(ah_line_raw)
            league_id_hist = row_element.get('name')
            return {'home': home, 'away': away, 'score': score_fmt, 'ahLine': ah_line_fmt, 'league_id_hist': league_id_hist}

        table3 = soup.select_one('#table_v3')
        if table3:
            h2h_rows_main = table3.select('tr[id^="tr3_"]')
            for row_h2h in h2h_rows_main:
                data = get_match_details_from_row_definitivo(row_h2h, 'fscore_3')
                if not data: continue
                if current_league_id and data.get('league_id_hist') and data.get('league_id_hist') != current_league_id: continue
                if data['home'] == details["home_team_main"]:
                    details["ah_h2h_v_main"] = data['ahLine']
                    details["res_h2h_v_main"] = data['score']
                    break
            if details["res_h2h_v_main"] == "?*?" and h2h_rows_main:
                data = get_match_details_from_row_definitivo(h2h_rows_main[0], 'fscore_3')
                if data:
                    details["ah_h2h_g_main"] = data['ahLine']
                    details["res_h2h_g_main"] = data['score']
                    if details["res_h2h_v_main"] == "?*?":
                        details["ah_h2h_v_main"] = data['ahLine']
                        details["res_h2h_v_main"] = data['score']
        
        table1 = soup.select_one('#table_v1'); last_home_opp_name_for_comp = None
        if table1:
            home_hist_rows = table1.select('tr[id^="tr1_"]')
            for row_home_hist in home_hist_rows:
                if row_home_hist.get('vs') == '1':
                    data = get_match_details_from_row_definitivo(row_home_hist, 'fscore_1')
                    if not data: continue
                    if current_league_id and data.get('league_id_hist') and data.get('league_id_hist') != current_league_id: continue
                    if data['home'] == details["home_team_main"]:
                        details["ah_l_h_main"] = data['ahLine']
                        details["res_l_h_main"] = data['score']
                        last_home_opp_name_for_comp = data['away']
                        break
        
        table2 = soup.select_one('#table_v2'); last_away_opp_name_for_comp = None
        if table2:
            away_hist_rows = table2.select('tr[id^="tr2_"]')
            for row_away_hist in away_hist_rows:
                if row_away_hist.get('vs') == '1':
                    data = get_match_details_from_row_definitivo(row_away_hist, 'fscore_2')
                    if not data: continue
                    if current_league_id and data.get('league_id_hist') and data.get('league_id_hist') != current_league_id: continue
                    if data['away'] == details["away_team_main"]:
                        details["ah_v_a_main"] = data['ahLine']
                        details["res_v_a_main"] = data['score']
                        last_away_opp_name_for_comp = data['home']
                        break
        
        if details["home_team_main"] != "Local Desconocido" and last_away_opp_name_for_comp and table1:
            for row_comp in table1.select('tr[id^="tr1_"]'): # Reutiliza home_hist_rows
                data = get_match_details_from_row_definitivo(row_comp, 'fscore_1')
                if not data: continue
                if (data['home'] == details["home_team_main"] and data['away'] == last_away_opp_name_for_comp):
                    details["l_vs_uv_a_main"] = f"{data['score']}/{data['ahLine']} L" # Local jugó en Casa (H)
                    break
                elif (data['away'] == details["home_team_main"] and data['home'] == last_away_opp_name_for_comp):
                    details["l_vs_uv_a_main"] = f"{data['score']}/{data['ahLine']} V" # Local jugó como Visitante (A)
                    break
        
        if details["away_team_main"] != "Visitante Desconocido" and last_home_opp_name_for_comp and table2:
            for row_comp in table2.select('tr[id^="tr2_"]'): # Reutiliza away_hist_rows
                data = get_match_details_from_row_definitivo(row_comp, 'fscore_2')
                if not data: continue
                if (data['home'] == details["away_team_main"] and data['away'] == last_home_opp_name_for_comp):
                    details["v_vs_ul_h_main"] = f"{data['score']}/{data['ahLine']} L" # Visitante jugó en Casa (H)
                    break
                elif (data['away'] == details["away_team_main"] and data['home'] == last_home_opp_name_for_comp):
                    details["v_vs_ul_h_main"] = f"{data['score']}/{data['ahLine']} V" # Visitante jugó como Visitante (A)
                    break

        def safe_int_def(value, default=0):
            try: return int(str(value).strip()) if str(value).strip().isdigit() else default
            except: return default
        def extract_team_stats_from_summary_def(soup_obj, table_css_selector, is_home_team):
            stats_text = "N/A"; table = soup_obj.select_one(table_css_selector)
            if table:
                rows = table.find_all('tr'); total_row_idx, loc_aw_row_idx = -1, -1
                for i_r, r_content in enumerate(rows):
                    td_texts = [td.get_text(strip=True) for td in r_content.find_all('td')]
                    if any("Total" in s for s in td_texts): total_row_idx = i_r
                    elif is_home_team and any("Home" in s for s in td_texts): loc_aw_row_idx = i_r
                    elif not is_home_team and any("Away" in s for s in td_texts): loc_aw_row_idx = i_r
                s_total, s_loc_aw = {}, {}
                if total_row_idx != -1 and len(rows) > total_row_idx:
                    t_cells = rows[total_row_idx].find_all('td')
                    if len(t_cells) > 8:
                        s_total = {'m': safe_int_def(t_cells[1].text), 'w': safe_int_def(t_cells[2].text),
                                   'd': safe_int_def(t_cells[3].text), 'l': safe_int_def(t_cells[4].text),
                                   'gf': safe_int_def(t_cells[5].text), 'ga': safe_int_def(t_cells[6].text),
                                   'rank': t_cells[8].text.strip() if t_cells[8].text.strip().isdigit() else 'N/A'}
                if loc_aw_row_idx != -1 and len(rows) > loc_aw_row_idx:
                    la_cells = rows[loc_aw_row_idx].find_all('td')
                    if len(la_cells) > 6:
                         s_loc_aw = {'m': safe_int_def(la_cells[1].text), 'w': safe_int_def(la_cells[2].text),
                                   'd': safe_int_def(la_cells[3].text), 'l': safe_int_def(la_cells[4].text),
                                   'gf': safe_int_def(la_cells[5].text), 'ga': safe_int_def(la_cells[6].text)}
                stats_parts = []
                if s_total:
                    stats_parts.append(f"🏆Clasif.:{s_total.get('rank','N/A')}")
                    stats_parts.append(f"🌍Total: {s_total.get('m',0)}|{s_total.get('w',0)}/{s_total.get('d',0)}/{s_total.get('l',0)} ({s_total.get('gf',0)}-{s_total.get('ga',0)})")
                if s_loc_aw:
                    loc_label = "🏠Local:" if is_home_team else "✈️Visit.:"
                    stats_parts.append(f"{loc_label} {s_loc_aw.get('m',0)}|{s_loc_aw.get('w',0)}/{s_loc_aw.get('d',0)}/{s_loc_aw.get('l',0)} ({s_loc_aw.get('gf',0)}-{s_loc_aw.get('ga',0)})")
                if stats_parts: stats_text = "  ".join(stats_parts)
            return stats_text
        details["stats_l_main"] = extract_team_stats_from_summary_def(soup, 'table.team-table-home', True)
        details["stats_v_main"] = extract_team_stats_from_summary_def(soup, 'table.team-table-guest', False)
        details["status"] = "ok"; details["message"] = "Detalles del partido principal extraídos con éxito."
    except Exception as e_parse:
        st.error(f"Error parseando detalles del partido principal {main_match_id}: {e_parse}")
        details["message"] = f"Error en parseo: {e_parse}"
    return details

# --- STREAMLIT APP UI ---
st.set_page_config(page_title="Análisis H2H Nowgoal Extendido", layout="wide", initial_sidebar_state="expanded")
st.title("🎯 Analizador de Partidos Extendido - Nowgoal")
st.markdown("""
Esta aplicación combina dos análisis:
1.  Encuentra el H2H entre los **últimos oponentes** del equipo local del partido principal.
2.  Extrae **estadísticas detalladas y comparativas** del propio partido principal.
""")
st.sidebar.image("https://nowgoal.com/img/logo.png", width=150)
st.sidebar.header("Configuración del Análisis")
main_match_id_input = st.sidebar.number_input(
    "🆔 ID del Partido Principal:", value=2778543, min_value=1, step=1, format="%d",
    help="Ingresa el ID del partido para el cual quieres realizar ambos análisis.")
analizar_button = st.sidebar.button("🚀 Analizar Partido", type="primary", use_container_width=True)
st.sidebar.markdown("---")
st.sidebar.info("Los hándicaps se muestran en formato decimal (ej: 0, -0.5, 1.0). "
                "La extracción de datos puede tardar unos segundos, especialmente la primera vez.")

if 'driver' not in st.session_state: st.session_state.driver = None

if analizar_button:
    if not main_match_id_input:
        st.warning("⚠️ Por favor, ingresa un ID de partido válido.")
    else:
        st.header(f"📊 Resultados del Análisis para Partido ID: {main_match_id_input}")
        if st.session_state.driver is None:
            with st.spinner("Iniciando WebDriver de Selenium... (puede tardar la primera vez)"):
                st.session_state.driver = get_selenium_driver_cached()
        driver = st.session_state.driver
        if not driver:
            st.error("🔴 No se pudo iniciar Selenium. El análisis no puede continuar.")
        else:
            start_time_analysis = time.time()
            st.subheader("Análisis 1: H2H de Oponentes del Equipo Local")
            with st.spinner(f"Obteniendo Rival A y Rival B para el equipo local de {main_match_id_input}..."):
                home_team_name_main, key_home_id_rival_a_context, rival_a_id, rival_a_name = get_last_home_streamlit(main_match_id_input)
                _, rival_b_id, rival_b_name = get_last_away_streamlit(main_match_id_input)
            st.write(f"Equipo Local del Partido Principal ({main_match_id_input}): **{home_team_name_main or 'No encontrado'}**")
            col_rival1, col_rival2 = st.columns(2)
            with col_rival1:
                st.metric(label=f"🏠 Rival A (Último oponente EN CASA de {home_team_name_main or 'Local'})",
                          value=f"{rival_a_name or 'N/A'} (ID: {rival_a_id or 'N/A'})",
                          delta=f"Partido H2H de Ref.: {key_home_id_rival_a_context or 'N/A'}", delta_color="off")
            with col_rival2:
                st.metric(label=f"✈️ Rival B (Último oponente FUERA de {home_team_name_main or 'Local'})",
                          value=f"{rival_b_name or 'N/A'} (ID: {rival_b_id or 'N/A'})", delta_color="off")

            details_rival_h2h = {"status": "error", "resultado": "N/A"}
            if key_home_id_rival_a_context and rival_a_id and rival_b_id:
                if rival_a_id == rival_b_id:
                    st.info(f"ℹ️ Rival A y Rival B son el mismo equipo ({rival_a_name}). Se buscará H2H igualmente.")
                with st.spinner(f"Buscando H2H entre {rival_a_name or 'Rival A'} y {rival_b_name or 'Rival B'} usando Selenium..."):
                    details_rival_h2h = get_h2h_details_selenium_streamlit_logic(driver, key_home_id_rival_a_context, rival_a_id, rival_b_id)
            elif not key_home_id_rival_a_context or not rival_a_id: st.error("❌ No se pudo determinar Rival A o su partido clave para el H2H de oponentes.")
            elif not rival_b_id: st.error("❌ No se pudo determinar Rival B para el H2H de oponentes.")

            if details_rival_h2h.get("status") == "found":
                st.markdown(f"""
                <div style="background-color: #E3F2FD; padding: 15px; border-radius: 8px; text-align: center; margin-bottom:15px; border: 1px solid #90CAF9;">
                    <h4 style="color: #1565C0; margin-bottom: 5px;">Resultado H2H: {rival_a_name or 'Rival A'} vs {rival_b_name or 'Rival B'}</h4>
                    <p style="font-size: 1.8em; font-weight: bold; color: #0D47A1; margin-top:0px; margin-bottom: 5px;">{details_rival_h2h['raw_string_formatted']}</p>
                    <p style="font-size: 0.9em; color: #424242;">(Formato: GolesLocal*GolesVisitante/Hándicap RolDeRivalA)</p>
                    <p style="font-size: 0.8em; color: #757575;">Hándicap Original (sin formatear): {details_rival_h2h['handicap_raw']}</p>
                </div>""", unsafe_allow_html=True)
            else: st.error(f"❌ H2H de Oponentes: {details_rival_h2h.get('resultado', 'Error desconocido')}")
            st.markdown("---")

            st.subheader(f"Análisis 2: Detalles del Partido Principal ID {main_match_id_input}")
            with st.spinner(f"Extrayendo detalles completos para el partido {main_match_id_input} usando Selenium..."):
                main_match_data = extract_main_match_details_definitivo(driver, main_match_id_input)

            if main_match_data.get("status") == "ok" or main_match_data.get("status") == "partial_data":
                st.success(f"✅ {main_match_data.get('message', 'Datos extraídos.')}")
                m = main_match_data
                st.markdown(f"""#### Información del Partido: {m.get('home_team_main','N/A')} vs {m.get('away_team_main','N/A')}
                **Liga:** {m.get('league_main','N/A')} | **ID:** {m.get('id','N/A')} | **Resultado Actual/Final:** {m.get('fin_main','N/A')}""")
                
                st.markdown("##### Líneas Principales del Partido")
                col_lineas1, col_lineas2 = st.columns(2)
                with col_lineas1: st.metric("Hándicap Asiático (Actual)", m.get('ah_act_main','N/A'))
                with col_lineas2: st.metric("Goles Más/Menos (Actual)", m.get('g_i_main','N/A'))

                st.markdown("##### Comparativas Históricas (Partido Principal)")
                c1, c2, c3 = st.columns(Spec=[0.35,0.3,0.35]) # Ajuste de ancho
                with c1:
                    st.markdown(f"**H2H (vs {m.get('away_team_main','Visitante')})**")
                    st.caption(f"Local: `{m.get('res_h2h_v_main','N/A')}` AH: `{m.get('ah_h2h_v_main','N/A')}`")
                    st.caption(f"Global: `{m.get('res_h2h_g_main','N/A')}` AH: `{m.get('ah_h2h_g_main','N/A')}`")
                with c2:
                    st.markdown(f"**Último de {m.get('home_team_main','Local')} (Local)**")
                    st.caption(f"Res: `{m.get('res_l_h_main','N/A')}` AH: `{m.get('ah_l_h_main','N/A')}`")
                with c3:
                    st.markdown(f"**Último de {m.get('away_team_main','Visitante')} (Visitante)**")
                    st.caption(f"Res: `{m.get('res_v_a_main','N/A')}` AH: `{m.get('ah_v_a_main','N/A')}`")

                st.markdown("##### H2H Cruzados (vs Oponentes Recientes)")
                cc1, cc2 = st.columns(2)
                with cc1: st.info(f"**{m.get('home_team_main','Local')}** vs Últ. Riv. Visitante: `{m.get('l_vs_uv_a_main','N/A')}`")
                with cc2: st.info(f"**{m.get('away_team_main','Visitante')}** vs Últ. Riv. Local: `{m.get('v_vs_ul_h_main','N/A')}`")
                
                st.markdown("##### Estadísticas de Equipos (Total / Local o Visitante)")
                exp_stats_l = st.expander(f"Estadísticas de {m.get('home_team_main','Local')}", expanded=False)
                exp_stats_l.text_area("", value=m.get('stats_l_main','N/A'), height=80,label_visibility="collapsed", disabled=True)
                exp_stats_v = st.expander(f"Estadísticas de {m.get('away_team_main','Visitante')}", expanded=False)
                exp_stats_v.text_area("", value=m.get('stats_v_main','N/A'), height=80,label_visibility="collapsed", disabled=True)

            elif main_match_data.get("status") == "not_found": st.error(f"❌ No se encontraron datos para el partido principal {main_match_id_input} en {BASE_URL_ELDEFINITIVO}.")
            else: st.error(f"❌ Error obteniendo detalles del partido principal: {main_match_data.get('message', 'Error desconocido')}")
            st.caption(f"⏱️ Tiempo total del análisis: {time.time() - start_time_analysis:.2f} segundos")
            st.markdown("---")
else:
    st.info("✨ Ingresa un ID de partido en la barra lateral y haz clic en 'Analizar Partido' para comenzar.")
