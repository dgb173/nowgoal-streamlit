# modules/nowgoal_scraper.py
import streamlit as st
import time
import requests
import re
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import math
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Mapping, Any # Quitada porque no se usa explícitamente en funciones gspread

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, ElementClickInterceptedException, NoSuchElementException, SessionNotCreatedException

# import gspread # Comentado si no lo usas directamente en este script ahora

# --- CONSTANTES GLOBALES DEL SCRAPER ---
BASE_URL = "https://live18.nowgoal25.com" # Confirmada de tu input
SELENIUM_TIMEOUT_SECONDS = 10 # Reducido para agilidad, puedes ajustarlo
SELENIUM_POLL_FREQUENCY = 0.1 # Más frecuente para esperas más cortas
# NOMBRE_SHEET = "Datos" # Comentado si gspread no se usa
# RETRY_DELAY_GSPREAD = 15 # Comentado

# --- FUNCIONES HELPER ---

@st.cache_resource(ttl=3600) # Cache por 1 hora
def get_requests_session():
    session = requests.Session()
    retries_req = Retry(total=3, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504])
    adapter_req = HTTPAdapter(max_retries=retries_req)
    session.mount("https://", adapter_req)
    session.mount("http://", adapter_req)
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"}) # User agent actualizado
    return session

@st.cache_data(ttl=90, show_spinner="Cargando HTML (R)...") # Cache para datos de requests, TTL 90s
def fetch_soup_requests(path, max_tries=2, delay=0.2): # Menos reintentos, menos delay
    session = get_requests_session()
    url = f"{BASE_URL}{path}"
    for attempt in range(1, max_tries + 1):
        try:
            resp = session.get(url, timeout=5) # Timeout agresivo
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except requests.RequestException:
            if attempt == max_tries: return None
            time.sleep(delay) # Delay simple
    return None

@st.cache_resource(show_spinner="WebDriver...")
def get_selenium_driver_cached():
    options = ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    # options.add_argument("--window-size=1280,720") # Tamaño más pequeño si no se interactúa visualmente
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")
    options.add_argument('--blink-settings=imagesEnabled=false') # No cargar imágenes
    options.add_argument('--disable-css-animation') # Deshabilitar animaciones CSS
    options.add_argument('--disable-extensions')
    options.add_argument('--disable-features=LazyFrameLoading')

    prefs = {
        "profile.managed_default_content_settings.images": 2,
        "profile.default_content_setting_values.notifications": 2,
        "profile.default_content_setting_values.popups": 2,
        "profile.default_content_setting_values.geolocation": 2,
        "profile.default_content_setting_values.media_stream":2,
        "javascript.enabled": True, # JS debe estar habilitado para que Selenium funcione como se espera
    }
    options.add_experimental_option("prefs", prefs)
    # Más opciones experimentales para velocidad
    options.add_experimental_option('excludeSwitches', ['enable-logging']) # Evitar logging innecesario
    options.set_page_load_strategy('eager') #  No esperar a que todos los recursos se carguen (puede ser normal o none)

    try:
        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(SELENIUM_TIMEOUT_SECONDS + 5) # Timeout para carga de página
        driver.implicitly_wait(2) # Implicit wait muy corto, priorizar explicit waits
        return driver
    except Exception as e:
        st.error(f"❌ WebDriver Init Error: {e}")
        return None

# (Tus funciones parse_ah_to_number y format_ah_as_decimal_string - deben estar definidas aquí)
@st.cache_data(show_spinner=False)
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
            try: val1, val2 = float(p1_str), float(p2_str)
            except ValueError: return None
            if val1 < 0 and not p2_str.startswith('-') and val2 > 0: val2 = -abs(val2)
            elif original_starts_with_minus and val1 == 0.0 and (p1_str=="0" or p1_str=="-0") and not p2_str.startswith('-') and val2 > 0: val2 = -abs(val2)
            return (val1 + val2) / 2.0
        else: return float(s)
    except ValueError: return None

@st.cache_data(show_spinner=False)
def format_ah_as_decimal_string(ah_line_str: str):
    if not isinstance(ah_line_str, str) or not ah_line_str.strip() or ah_line_str.strip() in ['-', '?']:
        return ah_line_str.strip() if isinstance(ah_line_str, str) else '-'
    numeric_value = parse_ah_to_number(ah_line_str)
    if numeric_value is None: return ah_line_str.strip() if isinstance(ah_line_str, str) else '-'
    if numeric_value == 0.0: return "0"
    sign = -1 if numeric_value < 0 else 1
    abs_num = abs(numeric_value)
    parte_entera, parte_decimal_original = math.floor(abs_num), round(abs_num - math.floor(abs_num), 4)
    nueva_parte_decimal, epsilon = parte_decimal_original, 1e-9
    if abs(parte_decimal_original - 0.25) < epsilon: nueva_parte_decimal = 0.25
    elif abs(parte_decimal_original - 0.75) < epsilon: nueva_parte_decimal = 0.75
    final_value_signed = sign * (parte_entera + nueva_parte_decimal)
    if final_value_signed == 0.0: return "0"
    if abs(final_value_signed - round(final_value_signed)) < epsilon: return str(int(round(final_value_signed)))
    else:
        if abs(final_value_signed - math.trunc(final_value_signed) - 0.25) < epsilon or \
           abs(final_value_signed - math.trunc(final_value_signed) - 0.75) < epsilon: return f"{final_value_signed:.2f}"
        else: return f"{final_value_signed:.1f}"

def get_team_league_info_from_script(soup):
    # ... (Tu función sin cambios, tal como la tenías)
    home_id, away_id, league_id = None, None, None
    home_name, away_name, league_name = "N/A", "N/A", "N/A"
    script_tag = soup.find("script", string=re.compile(r"var\s*_matchInfo\s*="))
    if script_tag and script_tag.string:
        script_content = script_tag.string
        h_id_m = re.search(r"hId:\s*parseInt\('(\d+)'\)", script_content)
        g_id_m = re.search(r"gId:\s*parseInt\('(\d+)'\)", script_content)
        sclass_id_m = re.search(r"sclassId:\s*parseInt\('(\d+)'\)", script_content)
        h_name_m = re.search(r"hName:\s*'([^']*)'", script_content)
        g_name_m = re.search(r"gName:\s*'([^']*)'", script_content)
        l_name_m = re.search(r"lName:\s*'([^']*)'", script_content)

        if h_id_m: home_id = h_id_m.group(1)
        if g_id_m: away_id = g_id_m.group(1)
        if sclass_id_m: league_id = sclass_id_m.group(1)
        if h_name_m: home_name = h_name_m.group(1).replace("\\'", "'")
        if g_name_m: away_name = g_name_m.group(1).replace("\\'", "'")
        if l_name_m: league_name = l_name_m.group(1).replace("\\'", "'")
    return home_id, away_id, league_id, home_name, away_name, league_name

def get_rival_a_for_original_h2h(main_match_id_str): # Recibe string para cache
    # ... (Tu función adaptada para usar `main_match_id_str`, tal como la tenías, pero llama a fetch_soup_requests)
    soup = fetch_soup_requests(f"/match/h2h-{main_match_id_str}") # USA MAIN_MATCH_ID_STR
    if not soup: return None, None, None
    table = soup.find("table", id="table_v1")
    if not table: return None, None, None
    for row in table.find_all("tr", id=re.compile(r"tr1_\d+")):
        if row.get("vs") == "1":
            key_match_id_for_h2h_url = row.get("index")
            if not key_match_id_for_h2h_url: continue
            onclick_tags = row.find_all("a", onclick=re.compile(r"team\((\d+)\)"))
            if len(onclick_tags) > 1:
                rival_a_tag = onclick_tags[1]
                rival_a_id_match_obj = re.search(r"team\((\d+)\)", rival_a_tag.get("onclick", ""))
                rival_a_name = rival_a_tag.text.strip()
                if rival_a_id_match_obj and rival_a_name:
                    return key_match_id_for_h2h_url, rival_a_id_match_obj.group(1), rival_a_name
    return None, None, None

def get_rival_b_for_original_h2h(main_match_id_str): # Recibe string
    # ... (Tu función adaptada para usar `main_match_id_str`, tal como la tenías)
    soup = fetch_soup_requests(f"/match/h2h-{main_match_id_str}") # USA MAIN_MATCH_ID_STR
    if not soup: return None, None
    table = soup.find("table", id="table_v2")
    if not table: return None, None
    for row in table.find_all("tr", id=re.compile(r"tr2_\d+")):
        if row.get("vs") == "1":
            onclick_tags = row.find_all("a", onclick=re.compile(r"team\((\d+)\)"))
            if len(onclick_tags) > 0:
                rival_b_tag = onclick_tags[0]
                rival_b_id_match_obj = re.search(r"team\((\d+)\)", rival_b_tag.get("onclick", ""))
                rival_b_name = rival_b_tag.text.strip()
                if rival_b_id_match_obj and rival_b_name:
                    return rival_b_id_match_obj.group(1), rival_b_name
    return None, None

def click_element_robust(driver, by, value, timeout=5): # Timeout reducido
    try:
        element = WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY).until(EC.presence_of_element_located((by, value)))
        WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY).until(EC.visibility_of(element))
        driver.execute_script("arguments[0].scrollIntoView({behavior: 'auto', block: 'center', inline: 'center'});", element)
        time.sleep(0.1) # Pausa mínima
        WebDriverWait(driver, 1, poll_frequency=0.05).until(EC.element_to_be_clickable((by, value))).click()
        return True
    except (ElementClickInterceptedException, TimeoutException):
        try:
            driver.execute_script("arguments[0].click();", element)
            return True
        except: return False
    except: return False

def extract_last_match_in_league(driver, table_css_id, team_name, league_id, filter_css, is_home):
    # ... (Tu función CON el match_id en el return, como se modificó antes, pero con timeouts ajustados)
    # Esta función depende críticamente de Selenium para los clics y la carga dinámica de la tabla filtrada.
    try:
        # Asegurarse de que los checkboxes de otras ligas (si existen) no estén activos o activar solo el de la liga deseada
        # Esta parte puede ser compleja si hay muchos checkboxes y requiere deseleccionar todos primero.
        # Por simplicidad aquí, asumimos que el click en la liga deseada es suficiente.
        if league_id:
            league_cb_selector = f"input#checkboxleague{table_css_id[-1]}[value='{league_id}']"
            click_element_robust(driver, By.CSS_SELECTOR, league_cb_selector) # Intentar clickear
            time.sleep(0.3) # Pausa para que se aplique el filtro de liga

        if not click_element_robust(driver, By.CSS_SELECTOR, filter_css): return None
        time.sleep(0.3) # Pausa para que se aplique el filtro local/visitante

        soup = BeautifulSoup(driver.page_source, "html.parser")
        table = soup.find("table", id=table_css_id)
        if not table: return None

        for idx, row in enumerate(table.find_all("tr", id=re.compile(rf"tr{table_css_id[-1]}_\d+"))):
            if row.get("style") and "display:none" in row.get("style", "").lower(): continue # Ignorar ocultas
            if idx > 4: break # Analizar solo los primeros 5 visibles para velocidad

            tds = row.find_all("td")
            if len(tds) < 14: continue
            
            home_t_el, away_t_el = tds[2].find("a"), tds[4].find("a")
            if not home_t_el or not away_t_el: continue
            home_t_name, away_t_name = home_t_el.text.strip(), away_t_el.text.strip()

            team_is_at_home_in_row = (team_name == home_t_name)
            team_is_away_in_row = (team_name == away_t_name)

            is_correct_league_row = True # Si no hay league_id, asumimos todas las ligas
            if league_id : is_correct_league_row = str(row.get("name")) == str(league_id)


            if ((is_home and team_is_at_home_in_row) or (not is_home and team_is_away_in_row)) and is_correct_league_row:
                match_id_val = None
                onclick_attr_val = row.get("onClick", "")
                match_id_search = re.search(r"goLive\('/match/live-(\d+)'\)", onclick_attr_val)
                if match_id_search: match_id_val = match_id_search.group(1)

                date_val = tds[1].find("span", {"name": "timeData"}).text.strip() if tds[1].find("span", {"name": "timeData"}) else "N/A"
                score_val = tds[3].find("span", class_=re.compile(r"fscore_")).text.strip() if tds[3].find("span", class_=re.compile(r"fscore_")) else "N/A"
                handicap_raw_val = tds[11].get("data-o", tds[11].text.strip())
                if not handicap_raw_val or handicap_raw_val.strip() == "-": handicap_raw_val = "N/A"
                
                return {"date": date_val, "home_team": home_t_name, "away_team": away_t_name,
                        "score": score_val, "handicap_line_raw": handicap_raw_val, 
                        "handicap_line_formatted": format_ah_as_decimal_string(handicap_raw_val), # Necesita tu función
                        "match_id": match_id_val}
        return None
    except: return None # Fallback general

def get_h2h_details_for_original_logic(driver, key_h2h_id, r_a_id, r_b_id):
    # ... (Tu función CON h2h_match_id, pero la navegación DEBE ser gestionada externamente o ser muy cuidadosa)
    # Esta función ahora espera que el driver esté en la URL correcta o la carga por sí misma.
    if not driver or not key_h2h_id or not r_a_id or not r_b_id:
        return {"status": "error", "resultado": "N/A (Args H2H incompletos)"}
    
    h2h_url = f"{BASE_URL}/match/h2h-{key_h2h_id}"
    try:
        if driver.current_url != h2h_url: # Solo cargar si es diferente
            driver.get(h2h_url)
            WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS -2, poll_frequency=SELENIUM_POLL_FREQUENCY).until( # -2s de timeout general
                EC.presence_of_element_located((By.ID, "table_v3")))
            time.sleep(0.2) # Pausa corta

        soup = BeautifulSoup(driver.page_source, "html.parser")
        table = soup.find("table", id="table_v3")
        if not table: return {"status": "error", "resultado": "N/A (Tabla v3 no encontrada)"}

        for row in table.find_all("tr", id=re.compile(r"tr3_\d+")):
            # ... (Lógica de parseo de tu función get_h2h_details..., asegurando devolver 'h2h_match_id')
            links = row.find_all("a", onclick=True);
            if len(links) < 2: continue
            row_h_id_obj = re.search(r"team\((\d+)\)", links[0].get("onclick", "")); row_h_id = row_h_id_obj.group(1) if row_h_id_obj else None
            row_a_id_obj = re.search(r"team\((\d+)\)", links[1].get("onclick", "")); row_a_id = row_a_id_obj.group(1) if row_a_id_obj else None
            if not row_h_id or not row_a_id: continue

            if {row_h_id, row_a_id} == {str(r_a_id), str(r_b_id)}:
                h2h_mid = None
                onclick_val = row.get("onClick", "")
                h2h_mid_search = re.search(r"goLive\('/match/live-(\d+)'\)", onclick_val)
                if h2h_mid_search: h2h_mid = h2h_mid_search.group(1)

                score_el = row.find("span", class_="fscore_3")
                if not score_el or not score_el.text or "-" not in score_el.text: continue
                score_txt = score_el.text.strip()
                g_h_val, g_a_val = score_txt.split("-", 1)

                td_elements = row.find_all("td")
                hc_raw = "N/A"
                if len(td_elements) > 11: # Índice 11
                    hc_cell_el = td_elements[11]
                    data_o_val = hc_cell_el.get("data-o")
                    hc_raw = data_o_val.strip() if data_o_val and data_o_val.strip() not in ["","-"] else (hc_cell_el.text.strip() if hc_cell_el.text.strip() not in ["","-"] else "N/A")
                
                rol_a_val = "H" if row_h_id == str(r_a_id) else "A"
                return {"status": "found", "goles_home_h2h_row": g_h_val, "goles_away_h2h_row": g_a_val,
                        "score_raw": score_txt, "handicap_raw": hc_raw, 
                        "handicap_formatted": format_ah_as_decimal_string(hc_raw), # Necesita tu función
                        "rol_rival_a_en_h2h": rol_a_val, "h2h_home_team_name": links[0].text.strip(),
                        "h2h_away_team_name": links[1].text.strip(), "h2h_match_id": h2h_mid}
        return {"status": "not_found", "resultado": "N/A (H2H Específico no encontrado)"}
    except Exception as e_h2h_sel:
        # print(f"SELENIUM H2H ERR: {e_h2h_sel}")
        return {"status": "error", "resultado": f"N/A (Err Selenium H2H: {str(e_h2h_sel)[:30]})"}


def get_main_match_odds_selenium(driver):
    # ... (Tu función sin cambios, pero asume que el driver ya está en la página H2H principal)
    odds_info = { "ah_home_cuota": "N/A", "ah_linea": "N/A", "ah_away_cuota": "N/A",
                  "goals_over_cuota": "N/A", "goals_linea": "N/A", "goals_under_cuota": "N/A"}
    try:
        # Esperar a que el contenedor de las cuotas de comparación esté presente
        # Asumimos que el driver ya está en la página correcta y ha cargado.
        live_compare_div = driver.find_element(By.ID, "liveCompareDiv") # Búsqueda directa si ya esperó antes
        
        bet365_row_selector = "tr#tr_o_1_8[name='earlyOdds']" 
        bet365_row_selector_alt = "tr#tr_o_1_31[name='earlyOdds']"
        bet365_early_odds_row = None
        
        try: bet365_early_odds_row = live_compare_div.find_element(By.CSS_SELECTOR, bet365_row_selector)
        except NoSuchElementException:
            try: bet365_early_odds_row = live_compare_div.find_element(By.CSS_SELECTOR, bet365_row_selector_alt)
            except NoSuchElementException: return odds_info

        tds_selenium = bet365_early_odds_row.find_elements(By.TAG_NAME, "td")

        if len(tds_selenium) >= 11:
            odds_info["ah_home_cuota"] = tds_selenium[2].get_attribute("data-o") or tds_selenium[2].text.strip() or "N/A"
            ah_linea_raw = tds_selenium[3].get_attribute("data-o") or tds_selenium[3].text.strip() or "N/A"
            odds_info["ah_linea"] = format_ah_as_decimal_string(ah_linea_raw) # Necesita tu función
            odds_info["ah_away_cuota"] = tds_selenium[4].get_attribute("data-o") or tds_selenium[4].text.strip() or "N/A"
            
            odds_info["goals_over_cuota"] = tds_selenium[8].get_attribute("data-o") or tds_selenium[8].text.strip() or "N/A"
            goals_linea_raw = tds_selenium[9].get_attribute("data-o") or tds_selenium[9].text.strip() or "N/A"
            odds_info["goals_linea"] = format_ah_as_decimal_string(goals_linea_raw) # Necesita tu función
            odds_info["goals_under_cuota"] = tds_selenium[10].get_attribute("data-o") or tds_selenium[10].text.strip() or "N/A"
    except: pass 
    return odds_info

def parse_tech_stats_from_soup(soup, match_id, description):
    # ... (Función que definimos antes para parsear teamTechDiv_detail)
    stats_data = {
        "Descripción Partido": description, "ID Partido": match_id if match_id else "N/A",
        "Tiros (L)": None, "Tiros (V)": None, "Tiros a Puerta (L)": None, "Tiros a Puerta (V)": None,
        "Ataques (L)": None, "Ataques (V)": None, "Ataques Peligrosos (L)": None, "Ataques Peligrosos (V)": None,
    }
    if not soup: return stats_data
    team_tech_div = soup.find("div", id="teamTechDiv_detail")
    if not team_tech_div: return stats_data
    stat_ul = team_tech_div.find("ul", class_="stat")
    if not stat_ul: return stats_data

    desired_stats_map = {
        "Shots": ("Tiros (L)", "Tiros (V)"), "Shots on Goal": ("Tiros a Puerta (L)", "Tiros a Puerta (V)"),
        "Attacks": ("Ataques (L)", "Ataques (V)"), "Dangerous Attacks": ("Ataques Peligrosos (L)", "Ataques Peligrosos (V)")
    }
    for li in stat_ul.find_all("li"):
        title_span = li.find("span", class_="stat-title")
        if title_span:
            stat_name = title_span.text.strip()
            if stat_name in desired_stats_map:
                home_k, away_k = desired_stats_map[stat_name]
                val_spans = li.find_all("span", class_="stat-c")
                if len(val_spans) >= 2:
                    try:
                        stats_data[home_k] = int(val_spans[0].text.strip())
                        stats_data[away_k] = int(val_spans[1].text.strip())
                    except (ValueError, TypeError): pass # Mantener None si no es int o el texto está vacío
    return stats_data

def extract_live_stats_via_requests(requests_session_local, match_info_dict):
    # ... (Función que definimos antes, usa parse_tech_stats_from_soup)
    match_iid_val = match_info_dict.get("id")
    description_val = match_info_dict.get("description", "N/A")
    
    default_data = { "Descripción Partido": description_val, "ID Partido": match_iid_val if match_iid_val else "N/A" }
    for k_stat in ["Tiros (L)", "Tiros (V)", "Tiros a Puerta (L)", "Tiros a Puerta (V)", "Ataques (L)", "Ataques (V)", "Ataques Peligrosos (L)", "Ataques Peligrosos (V)"]:
        default_data[k_stat] = None

    if not match_iid_val: return default_data

    url_stat = f"{BASE_URL}/match/live-{match_iid_val}"
    try:
        # Nota: requests_session_local es la sesión pasada desde el ThreadPoolExecutor
        resp_stat = requests_session_local.get(url_stat, timeout=3.5) # Timeout muy agresivo
        resp_stat.raise_for_status()
        soup_stat = BeautifulSoup(resp_stat.text, "html.parser")
        parsed_data = parse_tech_stats_from_soup(soup_stat, match_iid_val, description_val)
        # Chequeo simple para ver si se obtuvo algo, sino devolver default con Nones
        if any(v is not None for k,v in parsed_data.items() if k not in ["Descripción Partido", "ID Partido"]):
            return parsed_data
        return default_data # Si parse_tech_stats_from_soup no encontró nada
    except: return default_data # Cualquier error devuelve default


def get_match_specific_tech_stats_selenium(driver, match_id_val, description_val):
    # ... (Función que definimos antes, usa parse_tech_stats_from_soup)
    default_data = { "Descripción Partido": description_val, "ID Partido": match_id_val if match_id_val else "N/A" }
    for k_stat in ["Tiros (L)", "Tiros (V)", "Tiros a Puerta (L)", "Tiros a Puerta (V)", "Ataques (L)", "Ataques (V)", "Ataques Peligrosos (L)", "Ataques Peligrosos (V)"]:
        default_data[k_stat] = None

    if not match_id_val: return default_data

    url_stat_sel = f"{BASE_URL}/match/live-{match_id_val}"
    try:
        if driver.current_url != url_stat_sel: driver.get(url_stat_sel)
        # Espera específica y más corta
        WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS - 4, poll_frequency=SELENIUM_POLL_FREQUENCY).until(
            EC.presence_of_element_located((By.ID, "teamTechDiv_detail")))
        
        # Pequeña pausa extra OPCIONAL si el contenido tarda fracciones de segundo más
        # time.sleep(0.1) # DESCOMENTAR SOLO SI ES ESTRICTAMENTE NECESARIO
        
        soup_stat_sel = BeautifulSoup(driver.page_source, "html.parser")
        parsed_data = parse_tech_stats_from_soup(soup_stat_sel, match_id_val, description_val)
        if any(v is not None for k,v in parsed_data.items() if k not in ["Descripción Partido", "ID Partido"]):
            return parsed_data
        return default_data
    except: return default_data

# --- FUNCIÓN DE ESTILO PARA LA TABLA (BÁSICA) ---
def style_summary_table(df):
    # Esta función ahora devuelve un objeto Styler de Pandas.
    # La renderización exacta dependerá de la versión de Streamlit.
    def highlight_cols(s, props=''):
        return props if s.name in ["Tiros (L)", "Tiros (V)", "Tiros a Puerta (L)", "Tiros a Puerta (V)"] \
                        or s.name in ["Ataques (L)", "Ataques (V)", "Ataques Peligrosos (L)", "Ataques Peligrosos (V)"] else ''

    # Definir colores por grupo
    color_shots = 'background-color: #D6EAF8' # Azul pálido
    color_attacks = 'background-color: #D5F5E3' # Verde pálido

    # Crear un Styler object
    styled_df = df.style
    
    # Aplicar colores a columnas de Tiros
    shot_columns = [col for col in df.columns if "Tiros" in col or "Puerta" in col]
    if shot_columns:
        styled_df = styled_df.set_properties(subset=shot_columns, **{'background-color': '#D6EAF8', 'border': '1px solid lightgrey'})

    # Aplicar colores a columnas de Ataques
    attack_columns = [col for col in df.columns if "Ataques" in col or "Ataq." in col]
    if attack_columns:
        styled_df = styled_df.set_properties(subset=attack_columns, **{'background-color': '#D5F5E3', 'border': '1px solid lightgrey'})
    
    # Estilo general para el resto y cabeceras
    styled_df = styled_df.set_table_styles([
        {'selector': 'th', 'props': [('background-color', '#AED6F1'), ('font-weight', 'bold'), ('border', '1px solid black')]},
        {'selector': 'td', 'props': [('border', '1px solid lightgrey')]}
    ]).hide(axis="index") # Ocultar índice como solicitaste antes con hide_index=True
    
    return styled_df

# --- FUNCIÓN PRINCIPAL DE UI ---
def display_nowgoal_scraper_ui(): # Eliminado gsheet_sh_handle si no se usa
    st.set_page_config(layout="wide", page_title="Extractor Nowgoal Optimizado")
    st.title("⚡ Extractor y Analizador Nowgoal (Optimizado)")

    st.sidebar.header("Panel de Control")
    main_match_id_input = st.sidebar.text_input("🆔 ID Partido Principal:", value="2367900", key="main_id_optim") # ID de ejemplo
    analizar_btn = st.sidebar.button("🚀 Analizar Partido", type="primary", use_container_width=True)

    if 'selenium_driver' not in st.session_state:
        st.session_state.selenium_driver = None

    if analizar_btn:
        total_proc_start_time = time.time()
        valid_match_id = None
        if main_match_id_input:
            try: valid_match_id = str(int("".join(filter(str.isdigit, main_match_id_input))))
            except ValueError: st.error("ID de partido no válido."); st.stop()
        if not valid_match_id: st.warning("Ingrese un ID."); st.stop()

        # --- PASO 1: OBTENER DATOS INICIALES CON REQUESTS (RÁPIDO) ---
        with st.status("Fase 1: Datos iniciales (Requests)...", expanded=False) as status_req:
            soup_h2h_main = fetch_soup_requests(f"/match/h2h-{valid_match_id}")
            mp_h_id, mp_a_id, mp_l_id, mp_h_name, mp_a_name, mp_l_name = \
                get_team_league_info_from_script(soup_h2h_main) if soup_h2h_main else (None,)*3 + ("N/A",)*3
            
            key_h2h_op, r_a_op_id, r_a_op_name, r_b_op_id, r_b_op_name = \
                (None, None, "N/A", None, "N/A") # Defaults
            # Solo llamar si se obtuvo mp_h_id y mp_a_id para optimizar
            if mp_h_id and mp_a_id: # Estas funciones dependen del ID principal
                 key_h2h_op, r_a_op_id, r_a_op_name_raw = get_rival_a_for_original_h2h(valid_match_id)
                 r_a_op_name = r_a_op_name_raw if r_a_op_name_raw else "Rival A N/A"
                 r_b_op_id, r_b_op_name_raw = get_rival_b_for_original_h2h(valid_match_id)
                 r_b_op_name = r_b_op_name_raw if r_b_op_name_raw else "Rival B N/A"
            status_req.update(label="Fase 1 Completada!", state="complete")

        # --- PASO 2: INICIALIZAR/OBTENER DRIVER SELENIUM ---
        current_driver = st.session_state.selenium_driver
        # ... (lógica para (re)inicializar `current_driver` si es None o no responde) ...
        driver_needs_init_flag = False
        if current_driver is None: driver_needs_init_flag = True
        else:
            try: _ = current_driver.window_handles # Ping
            except WebDriverException: driver_needs_init_flag = True
        
        if driver_needs_init_flag:
            if current_driver:
                try: current_driver.quit()
                except: pass
            with st.spinner("Inicializando WebDriver..."):
                current_driver = get_selenium_driver_cached()
            st.session_state.selenium_driver = current_driver
        if not current_driver: st.error("Fallo al iniciar WebDriver."); st.stop()
        
        # --- PASO 3: OPERACIONES CON SELENIUM (MÍNIMAS) ---
        main_odds = {}
        last_h_match = None
        last_a_match = None
        h2h_op_details = {"status": "error"}

        with st.status("Fase 2: Datos principales (Selenium)...", expanded=False) as status_sel:
            # Navegación 1: H2H Principal
            h2h_main_url_nav = f"{BASE_URL}/match/h2h-{valid_match_id}"
            try:
                if current_driver.current_url != h2h_main_url_nav: current_driver.get(h2h_main_url_nav)
                # Esperar un elemento clave de esta página ANTES de extraer nada
                WebDriverWait(current_driver, SELENIUM_TIMEOUT_SECONDS, poll_frequency=SELENIUM_POLL_FREQUENCY).until(
                    EC.visibility_of_element_located((By.ID, "liveCompareDiv"))) # Por ejemplo, div de cuotas
                # time.sleep(0.1) # Opcional, brevísima pausa post-wait

                main_odds = get_main_match_odds_selenium(current_driver)
                if mp_h_id and mp_l_id and mp_h_name != "N/A":
                    last_h_match = extract_last_match_in_league(current_driver, "table_v1", mp_h_name, mp_l_id, "input#cb_sos1[value='1']", True)
                if mp_a_id and mp_l_id and mp_a_name != "N/A":
                    last_a_match = extract_last_match_in_league(current_driver, "table_v2", mp_a_name, mp_l_id, "input#cb_sos2[value='2']", False)
            except Exception as e_main_sel_page: status_sel.update(label=f"Error Selenium H2H Main: {str(e_main_sel_page)[:50]}", state="error")
            
            # Navegación 2 (Condicional): H2H Oponentes
            if key_h2h_op and r_a_op_id and r_b_op_id:
                # La función get_h2h_details_for_original_logic ahora maneja su propia navegación si es necesario
                h2h_op_details = get_h2h_details_for_original_logic(current_driver, key_h2h_op, r_a_op_id, r_b_op_id)
            status_sel.update(label="Fase 2 Completada!", state="complete")
        
        # --- PRESENTAR DATOS PRINCIPALES (COMO ANTES) ---
        st.subheader(f"Partido: {mp_h_name} vs {mp_a_name} (ID: {valid_match_id})")
        # ... (Presenta las cuotas, info de last_h_match, last_a_match, h2h_op_details de forma concisa)

        # --- PASO 4: TABLA DE ESTADÍSTICAS (HÍBRIDO REQUESTS + SELENIUM FALLBACK) ---
        st.subheader("📊 Resumen Estadísticas Clave")
        matches_for_stats = []
        matches_for_stats.append({"description": "P. Principal", "id": valid_match_id})
        if last_h_match and last_h_match.get("match_id"): matches_for_stats.append({"description": f"L: {mp_h_name[:12]}...", "id": last_h_match["match_id"]})
        if last_a_match and last_a_match.get("match_id"): matches_for_stats.append({"description": f"V: {mp_a_name[:12]}...", "id": last_a_match["match_id"]})
        if h2h_op_details.get("status") == "found" and h2h_op_details.get("h2h_match_id"): matches_for_stats.append({"description": "H2H Op.", "id": h2h_op_details["h2h_match_id"]})

        # Filtrar los que realmente tienen un ID para procesar
        valid_matches_to_process = [m for m in matches_for_stats if m.get("id")]
        
        stats_results_cache = {} # Guardar resultados aquí {match_id: stats_dict}

        if valid_matches_to_process:
            with st.spinner(f"Extrayendo estadísticas para {len(valid_matches_to_process)} partidos (Requests)...") as spinner_req_stats:
                local_requests_session = get_requests_session() # Nueva sesión para este pool
                with ThreadPoolExecutor(max_workers=min(len(valid_matches_to_process), 4)) as executor: # Máximo 4 workers
                    future_map_req = {executor.submit(extract_live_stats_via_requests, local_requests_session, match_d): match_d for match_d in valid_matches_to_process}
                    for i, future_item_req in enumerate(as_completed(future_map_req)):
                        match_dict_item = future_map_req[future_item_req]
                        match_id_item = match_dict_item["id"]
                        try:
                            stats_res = future_item_req.result()
                            # Si se obtuvo ALGO (no todos Nones), se considera válido por requests
                            if any(v is not None for k,v in stats_res.items() if k not in ["Descripción Partido", "ID Partido"]):
                                stats_results_cache[match_id_item] = stats_res
                            else: # Marcar para Selenium si requests no trajo datos sustanciales
                                stats_results_cache[match_id_item] = "SELENIUM_NEEDED"
                        except Exception:
                            stats_results_cache[match_id_item] = "SELENIUM_NEEDED" # Fallo, marcar
            
            with st.spinner(f"Completando estadísticas con Selenium (si es necesario)...") as spinner_sel_stats:
                for match_d_sel in valid_matches_to_process: # Iterar de nuevo para fallback
                    match_id_sel_check = match_d_sel["id"]
                    if stats_results_cache.get(match_id_sel_check) == "SELENIUM_NEEDED":
                        # print(f"SELENIUM FALLBACK FOR: {match_id_sel_check}")
                        sel_stats = get_match_specific_tech_stats_selenium(current_driver, match_id_sel_check, match_d_sel["description"])
                        stats_results_cache[match_id_sel_check] = sel_stats # Sobrescribir

        # Construir el DataFrame final para la tabla
        final_df_data = []
        for m_info_final in matches_for_stats: # Usar el orden original
            m_id_final = m_info_final.get("id")
            if m_id_final and m_id_final in stats_results_cache:
                final_df_data.append(stats_results_cache[m_id_final])
            elif m_id_final: # No estaba en cache, rellenar con Nones
                default_entry = { "Descripción Partido": m_info_final["description"], "ID Partido": m_id_final }
                for k_s_d in ["Tiros (L)", "Tiros (V)", "Tiros a Puerta (L)", "Tiros a Puerta (V)", "Ataques (L)", "Ataques (V)", "Ataques Peligrosos (L)", "Ataques Peligrosos (V)"]: default_entry[k_s_d] = None
                final_df_data.append(default_entry)
            elif not m_id_final: # No ID, rellenar con Nones
                default_entry_no_id = { "Descripción Partido": m_info_final["description"], "ID Partido": "N/A" }
                for k_s_d in ["Tiros (L)", "Tiros (V)", "Tiros a Puerta (L)", "Tiros a Puerta (V)", "Ataques (L)", "Ataques (V)", "Ataques Peligrosos (L)", "Ataques Peligrosos (V)"]: default_entry_no_id[k_s_d] = None
                final_df_data.append(default_entry_no_id)


        if final_df_data:
            summary_df = pd.DataFrame(final_df_data)
            # Rellenar NaNs con "N/A" para mejor visualización si son string, o 0 si son números (cuidado aquí)
            # summary_df = summary_df.fillna("N/A") # Podrías hacer esto o manejarlo en la extracción.
            styled_summary_df = style_summary_table(summary_df.copy()) # Aplicar tu función de estilo
            st.dataframe(styled_summary_df, use_container_width=True) # Quitado hide_index
        else:
            st.info("No se generaron datos para la tabla de resumen de estadísticas.")

        total_proc_end_time = time.time()
        st.sidebar.success(f"Análisis Completo: {total_proc_end_time - total_proc_start_time:.2f}s")
        # Considera cerrar el driver si no es una app de larga duración o para liberar recursos
        # if st.session_state.selenium_driver:
        #     st.session_state.selenium_driver.quit()
        #     st.session_state.selenium_driver = None

    else:
        st.info("➡️ Ingrese un ID de partido en la barra lateral y haga clic en 'Analizar'.")

if __name__ == '__main__':
    display_nowgoal_scraper_ui()
