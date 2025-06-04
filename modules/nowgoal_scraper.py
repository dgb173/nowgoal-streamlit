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

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, ElementClickInterceptedException, NoSuchElementException, SessionNotCreatedException

# --- CONSTANTES GLOBALES DEL SCRAPER ---
BASE_URL = "https://live18.nowgoal25.com"
SELENIUM_GENERAL_TIMEOUT = 7 # Reducido aún más. Es agresivo.
SELENIUM_POLL_FREQ = 0.05     # Sondeo muy frecuente.
USER_AGENT_STRING = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36" # Agente de usuario actualizado

# --- FUNCIONES HELPER ---

@st.cache_resource(ttl=3600)
def get_requests_session():
    session = requests.Session()
    retries = Retry(total=2, backoff_factor=0.2, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": USER_AGENT_STRING})
    return session

@st.cache_data(ttl=60, show_spinner="HTML (R)...", max_entries=20) # TTL corto, pocas entradas en cache
def fetch_soup_requests(path):
    session = get_requests_session()
    url = f"{BASE_URL}{path}"
    try:
        resp = session.get(url, timeout=3.5) # Timeout muy agresivo para requests
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except: # Captura genérica, devuelve None si falla
        return None

@st.cache_resource(show_spinner="WebDriver...")
def get_selenium_driver_cached():
    options = ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-images") # Equivalente a imagesEnabled=false
    options.add_argument("--blink-settings=imagesEnabled=false")
    options.add_argument(f"user-agent={USER_AGENT_STRING}")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--log-level=3") # Solo errores fatales
    options.set_page_load_strategy('eager') # Carga lo esencial, no espera a subrecursos

    prefs = {
        "profile.managed_default_content_settings.images": 2,
        "profile.default_content_setting_values.notifications": 2,
        "profile.default_content_setting_values.popups": 2,
        "javascript.enabled": True, # Necesario para Selenium
        "profile.default_content_setting_values.plugins": 2, # Deshabilitar plugins si no son necesarios
        "profile.default_content_setting_values.stylesheets": 2 # Intentar deshabilitar CSS puede ser muy agresivo
    }
    options.add_experimental_option("prefs", prefs)
    options.add_experimental_option('excludeSwitches', ['enable-automation', 'enable-logging'])

    try:
        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(SELENIUM_GENERAL_TIMEOUT + 2) # Timeout un poco mayor para carga de página
        driver.implicitly_wait(0.5) # Implicit wait mínimo, priorizar explícito
        return driver
    except Exception as e:
        st.error(f"❌ WebDriver Init Error: {e}")
        return None

@st.cache_data(show_spinner=False, max_entries=100) # Cache para funciones de parseo
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

@st.cache_data(show_spinner=False, max_entries=100)
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

# --- FUNCIONES DE EXTRACCIÓN ESPECÍFICAS (MANTENER COMO LAS TENÍAS PERO ADAPTADAS A NUEVOS TIMEOUTS/CACHE) ---
@st.cache_data(ttl=60, show_spinner=False, max_entries=10)
def get_team_league_info_from_script_cached(main_match_id_str_cache): # Pasa string para que cache funcione
    soup = fetch_soup_requests(f"/match/h2h-{main_match_id_str_cache}")
    if not soup: return (None,)*3 + ("N/A",)*3
    # ... (Tu lógica de `get_team_league_info_from_script` interna)
    home_id, away_id, league_id = None, None, None
    home_name, away_name, league_name = "N/A", "N/A", "N/A"
    script_tag = soup.find("script", string=re.compile(r"var\s*_matchInfo\s*="))
    if script_tag and script_tag.string: # Asegurarse que no es None
        script_content = script_tag.string
        h_id_m = re.search(r"hId:\s*parseInt\('(\d+)'\)", script_content)
        g_id_m = re.search(r"gId:\s*parseInt\('(\d+)'\)", script_content)
        # ... (resto de tus regex y asignaciones)
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


@st.cache_data(ttl=60, show_spinner=False, max_entries=10)
def get_rivals_info_cached(main_match_id_str_rivals):
    # ... (Tu lógica combinada de get_rival_a y get_rival_b, pero usando `main_match_id_str_rivals`)
    key_h2h_url_rival, rival_a_id_rival, rival_a_name_rival = None, None, "N/A"
    rival_b_id_rival, rival_b_name_rival = None, "N/A"
    
    # Rival A
    soup_rival_a = fetch_soup_requests(f"/match/h2h-{main_match_id_str_rivals}") # Se puede optimizar si se pasa el soup ya cargado
    if soup_rival_a:
        table_v1 = soup_rival_a.find("table", id="table_v1")
        if table_v1:
            for row in table_v1.find_all("tr", id=re.compile(r"tr1_\d+")):
                if row.get("vs") == "1":
                    key_h2h_url_rival = row.get("index")
                    # ... (resto de lógica para rival A)
                    onclick_tags = row.find_all("a", onclick=re.compile(r"team\((\d+)\)"))
                    if len(onclick_tags) > 1:
                        rival_a_tag = onclick_tags[1]
                        rival_a_id_match_obj = re.search(r"team\((\d+)\)", rival_a_tag.get("onclick", ""))
                        rival_a_name_raw = rival_a_tag.text.strip()
                        if rival_a_id_match_obj and rival_a_name_raw:
                            rival_a_id_rival = rival_a_id_match_obj.group(1)
                            rival_a_name_rival = rival_a_name_raw
                            break # Encontrado Rival A
    
    # Rival B (reutilizar soup si es posible, o nueva fetch si la estructura lo requiere)
    soup_rival_b = soup_rival_a # Si los datos están en la misma página inicial
    # Si table_v2 se carga después o es diferente: soup_rival_b = fetch_soup_requests(f"/match/h2h-{main_match_id_str_rivals}")
    if soup_rival_b:
        table_v2 = soup_rival_b.find("table", id="table_v2")
        if table_v2:
            for row in table_v2.find_all("tr", id=re.compile(r"tr2_\d+")):
                if row.get("vs") == "1":
                    # ... (resto de lógica para rival B)
                    onclick_tags_b = row.find_all("a", onclick=re.compile(r"team\((\d+)\)"))
                    if len(onclick_tags_b) > 0:
                        rival_b_tag = onclick_tags_b[0]
                        rival_b_id_match_obj = re.search(r"team\((\d+)\)", rival_b_tag.get("onclick", ""))
                        rival_b_name_raw = rival_b_tag.text.strip()
                        if rival_b_id_match_obj and rival_b_name_raw:
                            rival_b_id_rival = rival_b_id_match_obj.group(1)
                            rival_b_name_rival = rival_b_name_raw
                            break # Encontrado Rival B

    return key_h2h_url_rival, rival_a_id_rival, rival_a_name_rival, rival_b_id_rival, rival_b_name_rival


def click_element_robust(driver, by, value, timeout=3): # Timeout más corto
    # ... (Tu función `click_element_robust` sin cambios mayores, pero usando el timeout ajustado)
    try:
        element = WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQ).until(EC.presence_of_element_located((by, value)))
        # WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQ).until(EC.visibility_of(element)) # Visibility puede ser más lento
        driver.execute_script("arguments[0].scrollIntoView({behavior: 'instant', block: 'center', inline: 'nearest'});", element)
        time.sleep(0.05) # Pausa mínima absoluta
        # Intenta el click directamente si está presente
        if EC.element_to_be_clickable((by, value))(driver): # Checkear clickeabilidad
             element.click()
             return True
        driver.execute_script("arguments[0].click();", element) # Fallback a JS click
        return True
    except: return False


def extract_last_match_in_league(driver, table_id, team_name, league_id, filter_selector, is_home_team):
    # ... (Tu función con `match_id` y optimizaciones de velocidad que implementamos antes)
    # Asegúrate que el `driver` ya está en la página H2H principal ANTES de llamar a esta función.
    try:
        if league_id:
            league_cb = f"input#checkboxleague{table_id[-1]}[value='{league_id}']"
            click_element_robust(driver, By.CSS_SELECTOR, league_cb) # Asume que esto filtra
            time.sleep(0.15) # Pausa muy corta para el filtro

        if not click_element_robust(driver, By.CSS_SELECTOR, filter_selector): return None
        time.sleep(0.15) # Pausa muy corta para el filtro

        soup = BeautifulSoup(driver.page_source, "html.parser") # Obtener soup DESPUÉS de clics
        target_table = soup.find("table", id=table_id)
        if not target_table: return None

        for i, row_el in enumerate(target_table.find_all("tr", id=re.compile(rf"tr{table_id[-1]}_\d+"))):
            if row_el.get("style") and "display:none" in row_el.get("style", "").lower(): continue
            if i > 3: break # Limitar a 4 partidos para velocidad

            tds_list = row_el.find_all("td")
            if len(tds_list) < 14: continue
            # ... (resto de tu lógica de parseo de la fila, incluyendo extracción del match_id)
            home_team_el, away_team_el = tds_list[2].find("a"), tds_list[4].find("a")
            if not home_team_el or not away_team_el: continue
            home_t_name_row, away_t_name_row = home_team_el.text.strip(), away_team_el.text.strip()

            team_is_home_this_row = (team_name == home_t_name_row)
            
            # Chequear si es la liga correcta (si se filtró)
            correct_league_this_row = True
            if league_id: correct_league_this_row = str(row_el.get("name")) == str(league_id)
            
            if ((is_home_team and team_is_home_this_row) or (not is_home_team and not team_is_home_this_row and team_name == away_t_name_row)) and correct_league_this_row :
                match_id_found = None
                onclick_attr_found = row_el.get("onClick", "")
                mid_search = re.search(r"goLive\('/match/live-(\d+)'\)", onclick_attr_found)
                if mid_search: match_id_found = mid_search.group(1)

                date_found = tds_list[1].find("span", {"name": "timeData"}).text.strip() if tds_list[1].find("span", {"name": "timeData"}) else "N/A"
                score_found = tds_list[3].find("span", class_=re.compile(r"fscore_")).text.strip() if tds_list[3].find("span", class_=re.compile(r"fscore_")) else "N/A"
                # ... (parseo del handicap)
                hc_raw_val = tds_list[11].get("data-o", tds_list[11].text.strip())
                if not hc_raw_val or hc_raw_val.strip() == "-": hc_raw_val = "N/A"


                return {"date": date_found, "home_team": home_t_name_row, "away_team": away_t_name_row,
                        "score": score_found, "handicap_line_raw": hc_raw_val, 
                        "handicap_line_formatted": format_ah_as_decimal_string(hc_raw_val),
                        "match_id": match_id_found}
        return None
    except: return None


def get_h2h_details_for_original_logic(driver, key_h2h_match_id, team_a_id, team_b_id):
    # ... (Tu función con `h2h_match_id`, asumiendo que driver.get se maneja fuera si es la misma pág, o aquí si es nueva)
    if not driver or not key_h2h_match_id or not team_a_id or not team_b_id:
        return {"status": "error", "resultado": "Args H2H incompletos"}

    target_h2h_url = f"{BASE_URL}/match/h2h-{key_h2h_match_id}"
    try:
        # Solo navegar si la URL actual del driver no es la que necesitamos para H2H Oponentes
        if driver.current_url != target_h2h_url:
            driver.get(target_h2h_url)
            # Espera corta y específica para la tabla v3
            WebDriverWait(driver, SELENIUM_GENERAL_TIMEOUT -1, poll_frequency=SELENIUM_POLL_FREQ).until(
                EC.visibility_of_element_located((By.ID, "table_v3"))
            )
            # NO time.sleep() adicional aquí
        
        soup = BeautifulSoup(driver.page_source, "html.parser")
        table = soup.find("table", id="table_v3")
        if not table: return {"status": "error", "resultado": "Tabla v3 no encontrada"}

        for row_h2h in table.find_all("tr", id=re.compile(r"tr3_\d+")):
            # ... (Tu lógica de parseo de la fila H2H incluyendo 'h2h_match_id')
            links_h2h = row_h2h.find_all("a", onclick=True)
            if len(links_h2h) < 2: continue
            # ... (Extracción segura de IDs de equipo de la fila) ...
            h_id_obj = re.search(r"team\((\d+)\)", links_h2h[0].get("onclick", "")); h_id_row = h_id_obj.group(1) if h_id_obj else None
            a_id_obj = re.search(r"team\((\d+)\)", links_h2h[1].get("onclick", "")); a_id_row = a_id_obj.group(1) if a_id_obj else None
            if not h_id_row or not a_id_row: continue

            if {h_id_row, a_id_row} == {str(team_a_id), str(team_b_id)}:
                match_id_h2h_row = None
                onclick_h2h = row_h2h.get("onClick", "")
                m_id_search_h2h = re.search(r"goLive\('/match/live-(\d+)'\)", onclick_h2h)
                if m_id_search_h2h: match_id_h2h_row = m_id_search_h2h.group(1)
                # ... (Parseo de score, handicap, etc.)
                score_el_h2h = row_h2h.find("span", class_="fscore_3")
                if not score_el_h2h or not score_el_h2h.text or "-" not in score_el_h2h.text: continue
                score_txt_h2h = score_el_h2h.text.strip()
                gh_h2h, ga_h2h = score_txt_h2h.split("-", 1)
                tds_h2h_list = row_h2h.find_all("td")
                # ... (parseo handicap) ...
                hc_val_raw_h2h = "N/A"
                if len(tds_h2h_list) > 11: # Índice 11
                    hc_cell = tds_h2h_list[11]
                    data_o = hc_cell.get("data-o")
                    hc_val_raw_h2h = data_o.strip() if data_o and data_o.strip() not in ["","-"] else (hc_cell.text.strip() if hc_cell.text.strip() not in ["","-"] else "N/A")


                return {"status": "found", "goles_home_h2h_row": gh_h2h, "goles_away_h2h_row": ga_h2h,
                        "score_raw": score_txt_h2h, "handicap_raw": hc_val_raw_h2h, 
                        "handicap_formatted": format_ah_as_decimal_string(hc_val_raw_h2h),
                        "rol_rival_a_en_h2h": "H" if h_id_row == str(team_a_id) else "A", 
                        "h2h_home_team_name": links_h2h[0].text.strip(),
                        "h2h_away_team_name": links_h2h[1].text.strip(), 
                        "h2h_match_id": match_id_h2h_row}
        return {"status": "not_found", "resultado": "H2H Op. Específico no hallado"}
    except Exception as e_get_h2h:
        # print(f"GET H2H ERR: {e_get_h2h}")
        return {"status": "error", "resultado": f"Err H2H Sel: {str(e_get_h2h)[:25]}"}


def get_main_match_odds_selenium(driver_odds):
    # ... (Tu función, pero el driver debe estar en la página correcta y el div #liveCompareDiv ya debe ser visible)
    odds_data = { "ah_home_cuota": "-", "ah_linea": "-", "ah_away_cuota": "-",
                  "goals_over_cuota": "-", "goals_linea": "-", "goals_under_cuota": "-"} # Default con guiones
    try:
        # No WebDriverWait aquí, se asume que el llamador ya esperó a que la página esté lista.
        # Simplemente busca los elementos.
        live_compare_container = driver_odds.find_element(By.ID, "liveCompareDiv")
        
        # Intenta con el ID 8 (Bet365), luego el ID 31 como fallback
        row_to_parse = None
        try: row_to_parse = live_compare_container.find_element(By.CSS_SELECTOR, "tr#tr_o_1_8[name='earlyOdds']")
        except NoSuchElementException:
            try: row_to_parse = live_compare_container.find_element(By.CSS_SELECTOR, "tr#tr_o_1_31[name='earlyOdds']")
            except NoSuchElementException: return odds_data # No se encontró fila

        tds_odds_list = row_to_parse.find_elements(By.TAG_NAME, "td")
        if len(tds_odds_list) >= 11:
            # ... (Lógica de parseo de cuotas, usando `format_ah_as_decimal_string`)
            odds_data["ah_home_cuota"] = tds_odds_list[2].get_attribute("data-o") or tds_odds_list[2].text.strip() or "-"
            ah_line_val_raw = tds_odds_list[3].get_attribute("data-o") or tds_odds_list[3].text.strip() or "-"
            odds_data["ah_linea"] = format_ah_as_decimal_string(ah_line_val_raw)
            # ... (resto de cuotas)
            odds_data["ah_away_cuota"] = tds_odds_list[4].get_attribute("data-o") or tds_odds_list[4].text.strip() or "-"
            odds_data["goals_over_cuota"] = tds_odds_list[8].get_attribute("data-o") or tds_odds_list[8].text.strip() or "-"
            g_line_val_raw = tds_odds_list[9].get_attribute("data-o") or tds_odds_list[9].text.strip() or "-"
            odds_data["goals_linea"] = format_ah_as_decimal_string(g_line_val_raw)
            odds_data["goals_under_cuota"] = tds_odds_list[10].get_attribute("data-o") or tds_odds_list[10].text.strip() or "-"

    except: pass # Si algo falla, devuelve los defaults
    return odds_data


# --- FUNCIONES PARA TABLA DE ESTADÍSTICAS (REQUESTS + SELENIUM FALLBACK) ---
# (Reutilizar `parse_tech_stats_from_soup`, `extract_live_stats_via_requests`, `get_match_specific_tech_stats_selenium`
#  tal como se definieron en el PASO 1 de la respuesta anterior (la larga con la optimización).
#  Asegúrate de que están aquí)

def parse_tech_stats_from_soup(soup_to_parse, match_id_stat, description_stat): # COPIADA DE LA RESPUESTA ANTERIOR
    stats_result = {
        "Descripción Partido": description_stat, "ID Partido": match_id_stat if match_id_stat else "N/A",
        "Tiros (L)": None, "Tiros (V)": None, "Tiros a Puerta (L)": None, "Tiros a Puerta (V)": None,
        "Ataques (L)": None, "Ataques (V)": None, "Ataques Peligrosos (L)": None, "Ataques Peligrosos (V)": None,
    }
    if not soup_to_parse: return stats_result
    tech_div_el = soup_to_parse.find("div", id="teamTechDiv_detail")
    if not tech_div_el: return stats_result
    ul_el = tech_div_el.find("ul", class_="stat")
    if not ul_el: return stats_result

    map_stats = {
        "Shots": ("Tiros (L)", "Tiros (V)"), "Shots on Goal": ("Tiros a Puerta (L)", "Tiros a Puerta (V)"),
        "Attacks": ("Ataques (L)", "Ataques (V)"), "Dangerous Attacks": ("Ataques Peligrosos (L)", "Ataques Peligrosos (V)")
    }
    for li_el_stat in ul_el.find_all("li"):
        title_el_stat = li_el_stat.find("span", class_="stat-title")
        if title_el_stat:
            name_stat = title_el_stat.text.strip()
            if name_stat in map_stats:
                home_key_stat, away_key_stat = map_stats[name_stat]
                val_spans_stat = li_el_stat.find_all("span", class_="stat-c")
                if len(val_spans_stat) >= 2:
                    try:
                        stats_result[home_key_stat] = int(val_spans_stat[0].text.strip())
                        stats_result[away_key_stat] = int(val_spans_stat[1].text.strip())
                    except: pass
    return stats_result

def extract_live_stats_via_requests(req_session, match_info_for_req): # COPIADA DE LA RESPUESTA ANTERIOR
    mid_req = match_info_for_req.get("id")
    desc_req = match_info_for_req.get("description", "N/A")
    default_res_req = { "Descripción Partido": desc_req, "ID Partido": mid_req if mid_req else "N/A" }
    # ... (rellenar default_res_req con Nones para las stats) ...
    for k_stat_def in ["Tiros (L)", "Tiros (V)", "Tiros a Puerta (L)", "Tiros a Puerta (V)", "Ataques (L)", "Ataques (V)", "Ataques Peligrosos (L)", "Ataques Peligrosos (V)"]:
        default_res_req[k_stat_def] = None

    if not mid_req: return default_res_req
    url_for_req = f"{BASE_URL}/match/live-{mid_req}"
    try:
        response_req = req_session.get(url_for_req, timeout=2.5) # Timeout aún más agresivo
        response_req.raise_for_status()
        soup_for_req = BeautifulSoup(response_req.text, "html.parser")
        if soup_for_req.find("div", id="teamTechDiv_detail"): # Si existe el div
            return parse_tech_stats_from_soup(soup_for_req, mid_req, desc_req)
        return default_res_req # No encontró el div
    except: return default_res_req

def get_match_specific_tech_stats_selenium(sel_driver, mid_sel, desc_sel): # COPIADA DE LA RESPUESTA ANTERIOR
    default_res_sel = { "Descripción Partido": desc_sel, "ID Partido": mid_sel if mid_sel else "N/A" }
    # ... (rellenar default_res_sel con Nones para las stats) ...
    for k_stat_def_sel in ["Tiros (L)", "Tiros (V)", "Tiros a Puerta (L)", "Tiros a Puerta (V)", "Ataques (L)", "Ataques (V)", "Ataques Peligrosos (L)", "Ataques Peligrosos (V)"]:
        default_res_sel[k_stat_def_sel] = None

    if not mid_sel: return default_res_sel
    url_for_sel = f"{BASE_URL}/match/live-{mid_sel}"
    try:
        if sel_driver.current_url != url_for_sel: sel_driver.get(url_for_sel)
        WebDriverWait(sel_driver, SELENIUM_GENERAL_TIMEOUT - 2, poll_frequency=SELENIUM_POLL_FREQ).until(
            EC.visibility_of_element_located((By.ID, "teamTechDiv_detail")))
        soup_for_sel = BeautifulSoup(sel_driver.page_source, "html.parser")
        return parse_tech_stats_from_soup(soup_for_sel, mid_sel, desc_sel)
    except: return default_res_sel


# --- FUNCIÓN PARA MOSTRAR TABLA INDIVIDUAL ---
def display_single_match_stats_table(driver_for_stats, match_id_stat_disp, desc_stat_disp, requests_session_stats): # COPIADA
    if not match_id_stat_disp:
        st.caption(f"Stats no disponibles para '{desc_stat_disp}' (sin ID).")
        return

    stats_df_content = None
    # Intento con Requests
    req_stats = extract_live_stats_via_requests(requests_session_stats, {"id": match_id_stat_disp, "description": desc_stat_disp})
    if any(v is not None for k,v in req_stats.items() if k not in ["Descripción Partido", "ID Partido"]): # Si obtuvo datos válidos
        stats_df_content = req_stats
    else: # Fallback a Selenium
        with st.spinner(f"Stats (S) para {desc_stat_disp[:15]}..."): # Spinner SOLO si usa Selenium
             stats_df_content = get_match_specific_tech_stats_selenium(driver_for_stats, match_id_stat_disp, desc_stat_disp)

    if stats_df_content:
        # Tabla HTML para colores
        cols = ["Tiros (L)", "Tiros (V)", "Tiros a Puerta (L)", "Tiros a Puerta (V)", 
                "Ataques (L)", "Ataques (V)", "Ataques Peligrosos (L)", "Ataques Peligrosos (V)"]
        html = "<table style='width: auto; border-collapse: collapse; margin-bottom: 10px; font-size:0.85em;'>"
        html += "<tr style='font-weight:bold;'>"
        for c in cols:
            bg = '#cfe2f3' if 'Tiros' in c else ('#d9ead3' if 'Ataques' in c else '#f3f3f3') # Colores pastel
            short_c = c.replace(' (L)',' L').replace(' (V)',' V').replace('Tiros a Puerta','T/P').replace('Ataques Peligrosos','Ataq.Pel.')
            html += f"<th style='border:1px solid #ccc; padding:4px 6px; background-color:{bg}; text-align:center;'>{short_c}</th>"
        html += "</tr><tr>"
        for c in cols:
            val = stats_df_content.get(c)
            disp_val = str(val) if pd.notna(val) else "-"
            bg_data = '#e7f0fa' if 'Tiros' in c else ('#eaf7e7' if 'Ataques' in c else 'white')
            html += f"<td style='border:1px solid #ccc; padding:4px 6px; text-align:center; background-color:{bg_data};'>{disp_val}</td>"
        html += "</tr></table>"
        st.markdown(html, unsafe_allow_html=True)
    else: st.caption(f"No se pudieron obtener stats para '{desc_stat_disp}'.")

# --- FUNCIÓN PRINCIPAL DE UI ---
def display_nowgoal_scraper_ui(): # COPIADA Y ADAPTADA
    st.set_page_config(layout="wide", page_title="Extractor NG V.FINALÍSIMA")
    st.title("⚡ Extractor Nowgoal (FINALÍSIMA)")

    st.sidebar.header("Control")
    main_match_id = st.sidebar.text_input("🆔 ID Partido Principal:", value="2367900", key="main_id_finalisima") # Usar un ID que funcione
    analyze_button = st.sidebar.button("🚀 Analizar", type="primary", use_container_width=True)

    if 'selenium_driver_instance' not in st.session_state:
        st.session_state.selenium_driver_instance = None

    if analyze_button:
        start_time_overall = time.time()
        # Validar ID
        match_id_to_process = None
        try: match_id_to_process = str(int("".join(filter(str.isdigit, main_match_id))))
        except: st.error("ID inválido."); st.stop()
        if not match_id_to_process: st.warning("Ingrese ID."); st.stop()
        
        # Sesión de Requests para la UI
        ui_req_session = get_requests_session()

        # Fase 1: Datos iniciales (requests)
        mp_h_id, mp_a_id, mp_l_id, mp_h_name, mp_a_name, mp_l_name = (None,)*3 + ("N/A",)*3
        key_h2h_op_val, r_a_id_val, r_a_name_val, r_b_id_val, r_b_name_val = (None, None, "N/A", None, "N/A")

        with st.spinner("Obteniendo datos base (Requests)..."):
            # Optimizando: Primero, obtener info de equipos y liga del partido principal
            mp_h_id, mp_a_id, mp_l_id, mp_h_name, mp_a_name, mp_l_name = \
                get_team_league_info_from_script_cached(match_id_to_process)
            
            # Luego, obtener info de rivales para H2H de oponentes
            if mp_h_id and mp_a_id: # Solo si tenemos los IDs del partido principal
                key_h2h_op_val, r_a_id_val, r_a_name_val, r_b_id_val, r_b_name_val = \
                    get_rivals_info_cached(match_id_to_process)


        # Fase 2: Driver Selenium
        driver = st.session_state.selenium_driver_instance
        # ... (Lógica para inicializar/reutilizar driver, como la tenías) ...
        driver_needs_init = False
        if driver is None: driver_needs_init = True
        else:
            try: _ = driver.current_url # Ping
            except WebDriverException: driver_needs_init = True
        
               if driver_needs_init_flag: # Asegúrate de que esta es la variable correcta que usaste
            if current_driver: # Usa la variable correcta para el driver
                try:
                    current_driver.quit()
                except:
                    pass
            with st.spinner("WebDriver inicializando..."):
                current_driver = get_selenium_driver_cached() # Usa la variable correcta para el driver
            st.session_state.selenium_driver_instance = current_driver # Actualiza el estado de la sesión


        # --- Expansores para cada sección ---
        main_h2h_page_url = f"{BASE_URL}/match/h2h-{match_id_to_process}"

        with st.expander(f"⚽ PARTIDO PRINCIPAL: {mp_h_name} vs {mp_a_name} (ID: {match_id_to_process})", expanded=True):
            st.markdown(f"**Liga:** {mp_l_name or 'N/A'}")
            odds_main = {}
            # Asegurar que el driver está en la página H2H principal para cuotas
            try:
                if driver.current_url != main_h2h_page_url: driver.get(main_h2h_page_url)
                WebDriverWait(driver, SELENIUM_GENERAL_TIMEOUT, poll_frequency=SELENIUM_POLL_FREQ).until(
                    EC.visibility_of_element_located((By.ID, "liveCompareDiv")))
                odds_main = get_main_match_odds_selenium(driver) # Ya no espera dentro
                c1, c2 = st.columns(2)
                c1.metric("AH", f"{odds_main.get('ah_linea','-')}", f"{odds_main.get('ah_home_cuota','-')} / {odds_main.get('ah_away_cuota','-')}")
                c2.metric("Goles", f"{odds_main.get('goals_linea','-')}", f"Ov {odds_main.get('goals_over_cuota','-')} / Un {odds_main.get('goals_under_cuota','-')}")
            except: st.caption("Cuotas no obtenidas para P. Principal.")
            
            display_single_match_stats_table(driver, match_id_to_process, "Estadísticas P. Principal", ui_req_session)

        # Último Local (necesita driver en main_h2h_page_url para filtros)
        last_h_info = None
        if mp_h_id and mp_l_id and mp_h_name != "N/A":
            with st.spinner(f"Último L. {mp_h_name[:10]}..."):
                if driver.current_url != main_h2h_page_url: driver.get(main_h2h_page_url) # Reasegurar página
                WebDriverWait(driver, SELENIUM_GENERAL_TIMEOUT, poll_frequency=SELENIUM_POLL_FREQ).until(EC.presence_of_element_located((By.ID,"table_v1")))
                last_h_info = extract_last_match_in_league(driver, "table_v1", mp_h_name, mp_l_id, "input#cb_sos1[value='1']", True)

        with st.expander(f"🏡 ÚLTIMO LOCAL: {mp_h_name or 'N/A'}", expanded=False):
            if last_h_info:
                st.markdown(f"{last_h_info.get('home_team','?')} **{last_h_info.get('score','?-?')}** {last_h_info.get('away_team','?')} (AH: {last_h_info.get('handicap_line_formatted','-')})")
                display_single_match_stats_table(driver, last_h_info.get("match_id"), f"Stats Últ. L. {mp_h_name}", ui_req_session)
            else: st.caption("No encontrado.")
        
        # Último Visitante
        last_a_info = None
        if mp_a_id and mp_l_id and mp_a_name != "N/A":
            with st.spinner(f"Último V. {mp_a_name[:10]}..."):
                if driver.current_url != main_h2h_page_url: driver.get(main_h2h_page_url) # Reasegurar página
                WebDriverWait(driver, SELENIUM_GENERAL_TIMEOUT, poll_frequency=SELENIUM_POLL_FREQ).until(EC.presence_of_element_located((By.ID,"table_v2")))
                last_a_info = extract_last_match_in_league(driver, "table_v2", mp_a_name, mp_l_id, "input#cb_sos2[value='2']", False)

        with st.expander(f"✈️ ÚLTIMO VISITANTE: {mp_a_name or 'N/A'}", expanded=False):
            if last_a_info:
                st.markdown(f"{last_a_info.get('home_team','?')} **{last_a_info.get('score','?-?')}** {last_a_info.get('away_team','?')} (AH: {last_a_info.get('handicap_line_formatted','-')})")
                display_single_match_stats_table(driver, last_a_info.get("match_id"), f"Stats Últ. V. {mp_a_name}", ui_req_session)
            else: st.caption("No encontrado.")

        # H2H Oponentes
        h2h_op_res = {"status": "error"}
        if key_h2h_op_val and r_a_id_val and r_b_id_val:
            with st.spinner("H2H Oponentes..."):
                h2h_op_res = get_h2h_details_for_original_logic(driver, key_h2h_op_val, r_a_id_val, r_b_id_val)

        with st.expander(f"🆚 H2H OPONENTES: ({r_a_name_val} vs {r_b_name_val})", expanded=False):
            if h2h_op_res.get("status") == "found":
                res = h2h_op_res
                st.markdown(f"{res.get('h2h_home_team_name','?')} **{res.get('score_raw','?-?')}** {res.get('h2h_away_team_name','?')} (AH: {res.get('handicap_formatted','-')})")
                display_single_match_stats_table(driver, res.get("h2h_match_id"), f"Stats H2H Op.", ui_req_session)
            else: st.caption(f"{h2h_op_res.get('resultado', 'No disponible')}")
        
        st.sidebar.metric("Tiempo Total", f"{time.time() - start_time_overall:.2f}s")
        st.success(f"Análisis Completo. ({time.time() - start_time_overall:.2f}s)")

    else:
        st.info("Introduce un ID y haz clic en 'Analizar'.")


if __name__ == '__main__':
    # Esto permite ejecutar el script directamente: `python nowgoal_scraper.py`
    display_nowgoal_scraper_ui()
