# modules/nowgoal_scraper.py
import streamlit as st
import time
import requests
import re
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import math
import os
import shutil
from typing import Mapping, Any

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, ElementClickInterceptedException, NoSuchElementException, SessionNotCreatedException
from selenium.webdriver.chrome.service import Service as ChromeService

import gspread
import pandas as pd

# --- CONSTANTES GLOBALES DEL SCRAPER ---
BASE_URL = "https://live18.nowgoal25.com"
SELENIUM_TIMEOUT_SECONDS = 25
SELENIUM_POLL_FREQUENCY = 0.3
NOMBRE_SHEET = "Datos"
RETRY_DELAY_GSPREAD = 15

# --- FUNCIONES HELPER (GSheets, Parseo, Formato, Selenium Driver, etc.) ---

@st.cache_resource(ttl=3600)
def get_gsheets_client_and_sheet(_credentials_data: Mapping[str, Any]):
    actual_credentials_dict = dict(_credentials_data)
    retries = 3
    for attempt in range(retries):
        try:
            gc = gspread.service_account_from_dict(actual_credentials_dict)
            sh = gc.open(NOMBRE_SHEET)
            return gc, sh
        except Exception as e:
            st.sidebar.error(f"GSheets Conn {attempt+1} failed: {e}")
            if attempt < retries - 1:
                time.sleep(RETRY_DELAY_GSPREAD)
            else:
                return None, None

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
            try:
                val1 = float(p1_str)
                val2 = float(p2_str)
            except ValueError:
                return None
            if val1 < 0 and not p2_str.startswith('-') and val2 > 0:
                val2 = -abs(val2)
            elif original_starts_with_minus and val1 == 0.0 and (p1_str=="0" or p1_str=="-0") and not p2_str.startswith('-') and val2 > 0:
                val2 = -abs(val2)
            return (val1 + val2) / 2.0
        else:
            return float(s)
    except ValueError:
        return None

@st.cache_data(show_spinner=False)
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

    if abs(parte_decimal_original - 0.25) < epsilon:
        nueva_parte_decimal = 0.25 # No redondear a .5
    elif abs(parte_decimal_original - 0.75) < epsilon:
        nueva_parte_decimal = 0.75 # No redondear a .5

    resultado_num_final = parte_entera + nueva_parte_decimal
    final_value_signed = sign * resultado_num_final

    if final_value_signed == 0.0: return "0"

    # Comprobar si el número es efectivamente un entero después del ajuste
    if abs(final_value_signed - round(final_value_signed)) < epsilon:
        return str(int(round(final_value_signed)))
    else:
        # Si no es un entero, formatear a 1 o 2 decimales si es .25 o .75
        if abs(final_value_signed - math.trunc(final_value_signed) - 0.25) < epsilon or \
           abs(final_value_signed - math.trunc(final_value_signed) - 0.75) < epsilon:
            return f"{final_value_signed:.2f}" # e.g., 1.25, -0.75
        else: # para .0 o .5
             return f"{final_value_signed:.1f}" # e.g., 1.0, -0.5, 1.5

@st.cache_resource
def get_requests_session():
    session = requests.Session()
    retries_req = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    adapter_req = HTTPAdapter(max_retries=retries_req)
    session.mount("https://", adapter_req)
    session.mount("http://", adapter_req)
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"})
    return session

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_soup_requests(path, max_tries=3, delay=1):
    session = get_requests_session()
    url = f"{BASE_URL}{path}"
    for attempt in range(1, max_tries + 1):
        try:
            resp = session.get(url, timeout=10)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except requests.RequestException:
            if attempt == max_tries: return None
            time.sleep(delay * attempt)
    return None

@st.cache_data(ttl=3600, show_spinner=False)
def get_rival_a_for_original_h2h(main_match_id):
    soup = fetch_soup_requests(f"/match/h2h-{main_match_id}")
    if not soup: return None, None, None
    table = soup.find("table", id="table_v1")
    if not table: return None, None, None
    for row in table.find_all("tr", id=re.compile(r"tr1_\d+")):
        if row.get("vs") == "1": # Asegurar que es un partido 'VS' relevante
            key_match_id_for_h2h_url = row.get("index") # ID del partido del oponente que sirve para URL del H2H.
            if not key_match_id_for_h2h_url: continue

            onclick_tags = row.find_all("a", onclick=re.compile(r"team\((\d+)\)"))
            if len(onclick_tags) > 1: # El Rival A suele ser el segundo link de equipo
                rival_a_tag = onclick_tags[1] # El segundo link (índice 1)
                rival_a_id_match_obj = re.search(r"team\((\d+)\)", rival_a_tag.get("onclick", ""))
                rival_a_name = rival_a_tag.text.strip()
                if rival_a_id_match_obj and rival_a_name:
                    return key_match_id_for_h2h_url, rival_a_id_match_obj.group(1), rival_a_name
    return None, None, None

@st.cache_data(ttl=3600, show_spinner=False)
def get_rival_b_for_original_h2h(main_match_id):
    soup = fetch_soup_requests(f"/match/h2h-{main_match_id}")
    if not soup: return None, None
    table = soup.find("table", id="table_v2") # Tabla del equipo visitante del partido principal
    if not table: return None, None
    for row in table.find_all("tr", id=re.compile(r"tr2_\d+")):
        if row.get("vs") == "1": # Asegurar que es un partido 'VS' relevante
            onclick_tags = row.find_all("a", onclick=re.compile(r"team\((\d+)\)"))
            if len(onclick_tags) > 0: # El Rival B suele ser el primer link de equipo en esta tabla
                rival_b_tag = onclick_tags[0] # El primer link (índice 0)
                rival_b_id_match_obj = re.search(r"team\((\d+)\)", rival_b_tag.get("onclick", ""))
                rival_b_name = rival_b_tag.text.strip()
                if rival_b_id_match_obj and rival_b_name:
                    return rival_b_id_match_obj.group(1), rival_b_name
    return None, None

@st.cache_resource(show_spinner="Inicializando WebDriver...")
def get_selenium_driver_cached_for_this_script():
    options = ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    options.add_argument('--blink-settings=imagesEnabled=false') # Deshabilitar imágenes puede acelerar
    
    prefs = {
        "profile.managed_default_content_settings.images": 2, # No cargar imágenes
        "profile.default_content_setting_values.notifications": 2 # Bloquear notificaciones
    }
    options.add_experimental_option("prefs", prefs)
    
    try:
        # Para Streamlit Cloud, Chromedriver debería estar en el PATH si se instaló correctamente.
        # service = ChromeService() # Si Chromedriver está en PATH y es compatible
        driver = webdriver.Chrome(options=options) # Intenta inicializar sin service primero
        return driver
    except SessionNotCreatedException as e_session:
        st.error(f"❌ Error al crear sesión de WebDriver (SessionNotCreated): {e_session}. Asegúrate de que ChromeDriver y Google Chrome estén instalados y sean compatibles.")
    except WebDriverException as e_wd: # Error más genérico de WebDriver
        st.error(f"❌ Error de WebDriver: {e_wd}. Verifica la instalación de ChromeDriver/Chrome.")
    except Exception as e_env: # Otro error (ej. permisos)
        st.error(f"❌ Error general con ChromeDriver: {e_env}")
    return None

def get_h2h_details_for_original_logic(driver_instance, key_match_id_for_h2h_url, rival_a_id, rival_b_id):
    if not driver_instance: return {"status": "error", "resultado": "Driver no disponible (H2H Oponentes)"}
    if not key_match_id_for_h2h_url or not rival_a_id or not rival_b_id:
        return {"status": "error", "resultado": "N/A (IDs incompletos para H2H Oponentes)"}

    url_h2h_oponentes = f"{BASE_URL}/match/h2h-{key_match_id_for_h2h_url}"
    try:
        driver_instance.get(url_h2h_oponentes)
        WebDriverWait(driver_instance, SELENIUM_TIMEOUT_SECONDS, poll_frequency=SELENIUM_POLL_FREQUENCY).until(
            EC.presence_of_element_located((By.ID, "table_v3")) # Tabla de H2H entre oponentes
        )
        time.sleep(1.0) # Pequeña pausa para asegurar renderizado completo post-carga AJAX si existe.
        soup_selenium = BeautifulSoup(driver_instance.page_source, "html.parser")
    except TimeoutException:
        return {"status": "error", "resultado": f"N/A (Timeout esperando tabla H2H en {url_h2h_oponentes})"}
    except Exception as e:
        return {"status": "error", "resultado": f"N/A (Error Selenium H2H Oponentes: {type(e).__name__})"}

    if not soup_selenium:
        return {"status": "error", "resultado": "N/A (Fallo soup Selenium H2H Oponentes)"}

    table_h2h_general = soup_selenium.find("table", id="table_v3")
    if not table_h2h_general:
        return {"status": "error", "resultado": "N/A (Tabla H2H General (v3) no encontrada)"}

    for row in table_h2h_general.find_all("tr", id=re.compile(r"tr3_\d+")):
        links = row.find_all("a", onclick=True) # Links que identifican a los equipos
        if len(links) < 2: continue # Necesitamos dos links para los dos equipos

        h2h_home_team_id_match = re.search(r"team\((\d+)\)", links[0].get("onclick", ""))
        h2h_away_team_id_match = re.search(r"team\((\d+)\)", links[1].get("onclick", ""))

        if not h2h_home_team_id_match or not h2h_away_team_id_match: continue
        h2h_row_home_id = h2h_home_team_id_match.group(1)
        h2h_row_away_id = h2h_away_team_id_match.group(1)

        # Verificar si los equipos de esta fila son los rivales A y B que buscamos (en cualquier orden)
        if {h2h_row_home_id, h2h_row_away_id} == {str(rival_a_id), str(rival_b_id)}:
            h2h_match_id = None
            onclick_attr = row.get("onClick") or row.get("onclick", "")
            match_id_match = re.search(r"goLive\('/match/live-(\d+)'\)", onclick_attr)
            if match_id_match:
                h2h_match_id = match_id_match.group(1)

            score_span = row.find("span", class_="fscore_3") # El score dentro de la clase fscore_3
            if not score_span or not score_span.text or "-" not in score_span.text: continue
            
            score_val = score_span.text.strip()
            g_h, g_a = score_val.split("-", 1)

            tds = row.find_all("td")
            handicap_val_raw = "N/A"
            HANDICAP_TD_IDX_H2H_GENERAL = 11 # Índice de la celda de Handicap (ajustar si cambia el layout)
            
            if len(tds) > HANDICAP_TD_IDX_H2H_GENERAL:
                cell = tds[HANDICAP_TD_IDX_H2H_GENERAL]
                data_o_handicap = cell.get("data-o") # Valor en data-o es preferible
                handicap_val_raw = data_o_handicap.strip() if data_o_handicap and data_o_handicap.strip() not in ["", "-"] else (cell.text.strip() if cell.text.strip() not in ["", "-"] else "N/A")
            
            handicap_formatted = format_ah_as_decimal_string(handicap_val_raw)
            
            # Determinar el rol del "Rival A" original en este partido H2H
            rol_a_in_this_h2h = "H" if h2h_row_home_id == str(rival_a_id) else "A"

            return {"status": "found", "goles_home_h2h_row": g_h.strip(), "goles_away_h2h_row": g_a.strip(),
                    "score_raw": score_val, "handicap_raw": handicap_val_raw, "handicap_formatted": handicap_formatted,
                    "rol_rival_a_en_h2h": rol_a_in_this_h2h, "h2h_home_team_name": links[0].text.strip(),
                    "h2h_away_team_name": links[1].text.strip(),
                    "h2h_match_id": h2h_match_id}
    return {"status": "not_found", "resultado": "N/A (H2H entre Oponentes no encontrado en tabla v3)"}


def get_team_league_info_from_script(soup):
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

def click_element_robust(driver, by, value, timeout=7):
    try:
        element = WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY).until(
            EC.presence_of_element_located((by, value))
        )
        WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY).until(
            EC.visibility_of(element) 
        )
        # Scroll into view and give a tiny pause
        driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'center'});", element)
        time.sleep(0.3) # Pause for scrolling and UI update
        
        # Attempt click, if intercepted, fallback to JS click
        try:
            WebDriverWait(driver, 2, poll_frequency=SELENIUM_POLL_FREQUENCY).until(EC.element_to_be_clickable((by, value))).click()
        except (ElementClickInterceptedException, TimeoutException):
            st.toast(f"Click interceptado para {value}, usando JS click.", icon="🤏")
            driver.execute_script("arguments[0].click();", element)
        return True
    except Exception as e:
        # st.toast(f"No se pudo clickear {value}: {type(e).__name__}", icon="❌")
        return False

def extract_last_match_in_league(driver, table_css_id_str, main_team_name_in_table, league_id_filter_value,
                                home_or_away_filter_css_selector, is_home_game_filter):
    try:
        # Deseleccionar todas las ligas primero si es necesario (o solo seleccionar la deseada)
        # Para simplificar, asumimos que se activa el filtro de liga específico y de local/visitante.

        league_checkbox_selector = f"input#checkboxleague{table_css_id_str[-1]}[value='{league_id_filter_value}']"
        if league_id_filter_value: # Solo aplicar filtro de liga si se proporciona un ID de liga
            if not click_element_robust(driver, By.CSS_SELECTOR, league_checkbox_selector):
                st.toast(f"No se pudo clickear checkbox de liga ({league_id_filter_value}) para {table_css_id_str}", icon="⚠️")
                # No necesariamente fallar aquí, podría continuar sin filtro de liga si el checkbox no se encuentra o falla.
            time.sleep(1.5) # Pausa después de cambiar filtros

        # Aplicar filtro de Local o Visitante
        if not click_element_robust(driver, By.CSS_SELECTOR, home_or_away_filter_css_selector):
            st.toast(f"No se pudo clickear filtro local/visitante para {table_css_id_str}", icon="⚠️")
            return None # Si este filtro falla, los resultados no serán correctos
        time.sleep(1.5) # Pausa después de cambiar filtros

        page_source_updated = driver.page_source
        soup_updated = BeautifulSoup(page_source_updated, "html.parser")
        table = soup_updated.find("table", id=table_css_id_str)
        if not table: return None

        # Iterar sobre las filas VISIBLES después de aplicar filtros
        for row_idx, row in enumerate(table.find_all("tr", id=re.compile(rf"tr{table_css_id_str[-1]}_\d+"))):
            if row.get("style") and "display:none" in row.get("style", "").lower(): # Ignorar filas ocultas
                continue
            if row_idx > 7: break # Limitar búsqueda a los primeros ~8 partidos visibles para eficiencia

            tds = row.find_all("td")
            if len(tds) < 14: continue # Asegurar que la fila tiene suficientes celdas

            # Comprobar si el partido es de la liga correcta (si se especificó un filtro de liga)
            is_correct_league = True # Asumir que sí si no hay filtro o si el checkbox manejó el filtro
            if league_id_filter_value: # Doble chequeo si es posible
                 is_correct_league = str(row.get("name")) == str(league_id_filter_value)
            
            home_team_row_el = tds[2].find("a")
            away_team_row_el = tds[4].find("a")
            if not home_team_row_el or not away_team_row_el: continue

            home_team_row_name = home_team_row_el.text.strip()
            away_team_row_name = away_team_row_el.text.strip()

            # Determinar si el equipo principal es local o visitante en esta fila del historial
            team_is_home_in_row = (main_team_name_in_table == home_team_row_name)
            team_is_away_in_row = (main_team_name_in_table == away_team_row_name)
            
            # Comprobar si el rol del equipo principal en la fila coincide con el filtro (Local/Visitante) Y si es la liga correcta
            if ( (is_home_game_filter and team_is_home_in_row) or \
                 (not is_home_game_filter and team_is_away_in_row) ) and is_correct_league:
                
                match_id = None
                onclick_attr = row.get("onClick") or row.get("onclick", "")
                match_id_match = re.search(r"goLive\('/match/live-(\d+)'\)", onclick_attr)
                if match_id_match:
                    match_id = match_id_match.group(1)

                date_span = tds[1].find("span", {"name": "timeData"})
                date = date_span.text.strip() if date_span else "N/A"
                
                score_span = tds[3].find("span", class_=re.compile(r"fscore_")) # ej. fscore_1, fscore_2
                score = score_span.text.strip() if score_span else "N/A"
                
                handicap_cell = tds[11] # Celda de Handicap
                handicap_raw = handicap_cell.get("data-o", handicap_cell.text.strip()) # Preferir data-o
                if not handicap_raw or handicap_raw.strip() == "-": handicap_raw = "N/A"
                
                handicap_formatted = format_ah_as_decimal_string(handicap_raw)

                return {"date": date, "home_team": home_team_row_name, "away_team": away_team_row_name,
                        "score": score, "handicap_line_raw": handicap_raw, "handicap_line_formatted": handicap_formatted,
                        "match_id": match_id}
        return None # No se encontró partido que cumpla los criterios
    except Exception as e:
        # st.toast(f"Error extrayendo último partido: {type(e).__name__}", icon="❌")
        return None


# --- NUEVA FUNCIÓN: EXTRACTOR DE ESTADÍSTICAS TÉCNICAS ESPECÍFICAS DE UN PARTIDO ---
def get_match_specific_tech_stats_for_table(driver, match_iid, match_description=""):
    """Extrae estadísticas clave de un partido para mostrar en una tabla comparativa."""

    stats_url = f"{BASE_URL}/match/live-{match_iid}"
    stats_data = {
        "Descripción Partido": match_description,
        "ID Partido": match_iid if match_iid else "N/A",
        "Tiros (L)": None,
        "Tiros (V)": None,
        "Tiros a Puerta (L)": None,
        "Tiros a Puerta (V)": None,
        "Ataques (L)": None,
        "Ataques (V)": None,
        "Ataques Peligrosos (L)": None,
        "Ataques Peligrosos (V)": None,
    }

    if not match_iid:
        return stats_data

    try:
        driver.get(stats_url)
        WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS).until(
            EC.presence_of_element_located((By.ID, "teamTechDiv_detail"))
        )

        soup_selenium = BeautifulSoup(driver.page_source, "html.parser")
        team_tech_div = soup_selenium.find("div", id="teamTechDiv_detail")
        if not team_tech_div:
            return stats_data

        stat_ul = team_tech_div.find("ul", class_="stat")
        if not stat_ul:
            return stats_data

        desired_stats_mapping = {
            "Shots": ("Tiros (L)", "Tiros (V)"),
            "Shots on Goal": ("Tiros a Puerta (L)", "Tiros a Puerta (V)"),
            "Attacks": ("Ataques (L)", "Ataques (V)"),
            "Dangerous Attacks": ("Ataques Peligrosos (L)", "Ataques Peligrosos (V)"),
        }

        for li_element in stat_ul.find_all("li"):
            stat_title_span = li_element.find("span", class_="stat-title")
            if stat_title_span:
                stat_name = stat_title_span.text.strip()
                if stat_name in desired_stats_mapping:
                    home_key, away_key = desired_stats_mapping[stat_name]
                    stat_values_spans = li_element.find_all("span", class_="stat-c")
                    if len(stat_values_spans) >= 2:
                        home_val_str = stat_values_spans[0].text.strip()
                        away_val_str = stat_values_spans[1].text.strip()
                        try:
                            stats_data[home_key] = int(home_val_str)
                            stats_data[away_key] = int(away_val_str)
                        except ValueError:
                            pass

    except TimeoutException:
        pass
    except WebDriverException:
        pass
    except Exception:
        pass

    return stats_data


def display_comparative_stats_table(driver, main_match_id, mp_home_name, mp_away_name,
                                    last_home_match_in_league, last_away_match_in_league,
                                    details_h2h_col3):
    """Build and show a styled dataframe with key technical stats for several matches."""

    st.markdown("---")
    st.subheader("📊 Resumen de Estadísticas Clave por Partido")

    matches_to_analyze_stats = []

    # Partido Principal
    matches_to_analyze_stats.append({
        "description": "Partido Principal",
        "id": main_match_id,
        "name": f"{mp_home_name} vs {mp_away_name}"
    })

    # Último partido de local
    if last_home_match_in_league and last_home_match_in_league.get("match_id"):
        matches_to_analyze_stats.append({
            "description": f"Último Local {mp_home_name}",
            "id": last_home_match_in_league["match_id"],
            "name": f"{last_home_match_in_league['home_team']} vs {last_home_match_in_league['away_team']}"
        })
    else:
        matches_to_analyze_stats.append({"description": f"Último Local {mp_home_name}", "id": None, "name": "No Encontrado"})

    # Último partido de visitante
    if last_away_match_in_league and last_away_match_in_league.get("match_id"):
        matches_to_analyze_stats.append({
            "description": f"Último Visitante {mp_away_name}",
            "id": last_away_match_in_league["match_id"],
            "name": f"{last_away_match_in_league['home_team']} vs {last_away_match_in_league['away_team']}"
        })
    else:
        matches_to_analyze_stats.append({"description": f"Último Visitante {mp_away_name}", "id": None, "name": "No Encontrado"})

    # H2H
    if details_h2h_col3.get("status") == "found" and details_h2h_col3.get("h2h_match_id"):
        matches_to_analyze_stats.append({
            "description": f"H2H Oponentes ({details_h2h_col3.get('h2h_home_team_name','?')}-{details_h2h_col3.get('h2h_away_team_name','?')})",
            "id": details_h2h_col3["h2h_match_id"],
            "name": f"{details_h2h_col3.get('h2h_home_team_name','N/A')} vs {details_h2h_col3.get('h2h_away_team_name','N/A')}"
        })
    else:
        matches_to_analyze_stats.append({"description": "H2H Oponentes", "id": None, "name": "No Encontrado"})

    all_stats_for_table = []
    with st.spinner("Extrayendo estadísticas técnicas para la tabla comparativa..."):
        for match_info in matches_to_analyze_stats:
            stats = get_match_specific_tech_stats_for_table(driver, match_info["id"], match_info["description"])
            all_stats_for_table.append(stats)
            time.sleep(0.5)

    if all_stats_for_table:
        df_stats = pd.DataFrame(all_stats_for_table)

        def style_stats_table(df):
            color_shots = "#E0F7FA"
            color_attacks = "#E8F5E9"
            shots_cols = ["Tiros (L)", "Tiros (V)", "Tiros a Puerta (L)", "Tiros a Puerta (V)"]
            attacks_cols = ["Ataques (L)", "Ataques (V)", "Ataques Peligrosos (L)", "Ataques Peligrosos (V)"]

            styles = []
            for col in df.columns:
                if col in shots_cols:
                    styles.append({'selector': f'th.col_heading.col{df.columns.get_loc(col)}, td.col{df.columns.get_loc(col)}',
                                   'props': [('background-color', color_shots)]})
                elif col in attacks_cols:
                    styles.append({'selector': f'th.col_heading.col{df.columns.get_loc(col)}, td.col{df.columns.get_loc(col)}',
                                   'props': [('background-color', color_attacks)]})
            return styles

        st.dataframe(
            df_stats.style.set_table_styles(style_stats_table(df_stats)),
            use_container_width=True,
            hide_index=True,
        )
        st.caption("Los valores 'None' indican que la estadística no pudo ser extraída o no estaba disponible.")
    else:
        st.info("No se pudieron obtener las estadísticas técnicas para los partidos comparados.")



def get_main_match_odds_selenium(driver):
    odds_info = { "ah_home_cuota": "N/A", "ah_linea": "N/A", "ah_away_cuota": "N/A",
                  "goals_over_cuota": "N/A", "goals_linea": "N/A", "goals_under_cuota": "N/A"}
    try:
        # Esperar a que el contenedor de las cuotas de comparación esté presente
        live_compare_div = WebDriverWait(driver, 10, poll_frequency=SELENIUM_POLL_FREQUENCY).until(
            EC.presence_of_element_located((By.ID, "liveCompareDiv"))
        )
        
        # Selectores para la fila de Bet365 (puede variar entre ID 8 y 31)
        bet365_row_selector = "tr#tr_o_1_8[name='earlyOdds']" 
        bet365_row_selector_alt = "tr#tr_o_1_31[name='earlyOdds']" # Betfair u otro bookie si Bet365 no es el 8.
        bet365_early_odds_row = None
        
        try: # Probar primero con el selector principal (ID 8 para Bet365)
            bet365_early_odds_row = WebDriverWait(live_compare_div, 5, poll_frequency=SELENIUM_POLL_FREQUENCY).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, bet365_row_selector))
            )
        except TimeoutException: # Si falla, probar con el selector alternativo (ID 31)
            try:
                bet365_early_odds_row = WebDriverWait(live_compare_div, 3, poll_frequency=SELENIUM_POLL_FREQUENCY).until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, bet365_row_selector_alt))
                )
            except TimeoutException: # Si ambos fallan, no se encontraron las cuotas
                return odds_info 

        # Usar Selenium para extraer de la fila encontrada, ya que puede tener JS
        tds_selenium = bet365_early_odds_row.find_elements(By.TAG_NAME, "td")

        if len(tds_selenium) >= 11: # Asegurar que hay suficientes celdas
            odds_info["ah_home_cuota"] = tds_selenium[2].get_attribute("data-o") or tds_selenium[2].text.strip() or "N/A"
            ah_linea_raw = tds_selenium[3].get_attribute("data-o") or tds_selenium[3].text.strip() or "N/A"
            odds_info["ah_linea"] = format_ah_as_decimal_string(ah_linea_raw)
            odds_info["ah_away_cuota"] = tds_selenium[4].get_attribute("data-o") or tds_selenium[4].text.strip() or "N/A"
            
            odds_info["goals_over_cuota"] = tds_selenium[8].get_attribute("data-o") or tds_selenium[8].text.strip() or "N/A"
            goals_linea_raw = tds_selenium[9].get_attribute("data-o") or tds_selenium[9].text.strip() or "N/A"
            odds_info["goals_linea"] = format_ah_as_decimal_string(goals_linea_raw)
            odds_info["goals_under_cuota"] = tds_selenium[10].get_attribute("data-o") or tds_selenium[10].text.strip() or "N/A"
    except Exception:
        pass # Si hay cualquier error, devolver los valores N/A por defecto
    return odds_info

# --- FUNCIÓN PRINCIPAL DE UI Y LÓGICA DEL SCRAPER (LLAMADA DESDE APP.PY) ---
def display_nowgoal_scraper_ui(gsheet_sh_handle): # gsheet_sh_handle no se usa actualmente.
    st.header("🔎 Extractor y Analizador de Partidos Nowgoal (H2H Oponentes)")

    st.sidebar.subheader("Filtros del Extractor")
    main_match_id_str_input = st.sidebar.text_input(
        "🆔 ID del Partido Principal:", value="2778085", # Ejemplo por defecto
        help="Pega el ID del partido para el análisis completo.",
        key="nowgoal_main_match_id_input_final_v3" 
    )
    analizar_button = st.sidebar.button("🚀 Analizar Partido", type="primary", use_container_width=True, key="nowgoal_analizar_button_final_v3")

    if 'driver_global_app_h2h_oponentes' not in st.session_state:
        st.session_state.driver_global_app_h2h_oponentes = None

    if analizar_button:
        main_match_id_to_process = None
        if main_match_id_str_input:
            try:
                cleaned_id_str = "".join(filter(str.isdigit, main_match_id_str_input))
                if cleaned_id_str: main_match_id_to_process = int(cleaned_id_str)
            except ValueError: 
                st.error("⚠️ ID de partido no válido."); st.stop()

        if not main_match_id_to_process:
            st.warning("⚠️ Ingresa un ID de partido válido.")
        else:
            # Gestión del WebDriver
            driver_actual = st.session_state.driver_global_app_h2h_oponentes
            driver_needs_init = False
            if driver_actual is None:
                driver_needs_init = True
            else:
                try:
                    _ = driver_actual.window_handles # Comprobar si el driver está activo
                    if hasattr(driver_actual, 'service') and driver_actual.service and not driver_actual.service.is_connectable():
                       driver_needs_init = True # Recrear si el servicio no está conectable
                except WebDriverException: # Driver no responde o cerrado
                    driver_needs_init = True
            
            if driver_needs_init:
                if driver_actual is not None: # Si existe uno viejo, cerrarlo
                    try: driver_actual.quit()
                    except: pass
                with st.spinner("🚘 Inicializando WebDriver... (puede tardar)"):
                    driver_actual = get_selenium_driver_cached_for_this_script()
                st.session_state.driver_global_app_h2h_oponentes = driver_actual

            if not driver_actual: # Si después de intentar inicializar sigue sin estar disponible
                st.error("🔴 No se pudo iniciar Selenium. El análisis no puede continuar.")
            else:
                start_time_analysis = time.time()
                st.markdown(f"### 📋 Información del Partido Principal (ID: {main_match_id_to_process})")

                with st.spinner("Obteniendo información básica del partido (Requests)..."):
                    main_page_url_h2h_view = f"/match/h2h-{main_match_id_to_process}"
                    soup_main_h2h_page = fetch_soup_requests(main_page_url_h2h_view)

                mp_home_id, mp_away_id, mp_league_id, mp_home_name, mp_away_name, mp_league_name = (None,)*3 + ("N/A",)*3
                if soup_main_h2h_page:
                    mp_home_id, mp_away_id, mp_league_id, mp_home_name, mp_away_name, mp_league_name = get_team_league_info_from_script(soup_main_h2h_page)
                else:
                    st.error("No se pudo obtener información básica del partido principal con Requests.")

                col_mp_info1, col_mp_info2, col_mp_info3 = st.columns(3)
                with col_mp_info1: st.markdown(f"**Local:**<br><span style='font-size:1.1em; font-weight:bold;'>{mp_home_name or 'N/A'}</span> (ID: {mp_home_id or 'N/A'})", unsafe_allow_html=True)
                with col_mp_info2: st.markdown(f"**Visitante:**<br><span style='font-size:1.1em; font-weight:bold;'>{mp_away_name or 'N/A'}</span> (ID: {mp_away_id or 'N/A'})", unsafe_allow_html=True)
                with col_mp_info3: st.markdown(f"**Liga:**<br><span style='font-size:1.1em;'>{mp_league_name or 'N/A'}</span> (ID: {mp_league_id or 'N/A'})", unsafe_allow_html=True)

                main_match_odds_data = {}
                last_home_match_in_league = None
                last_away_match_in_league = None

                with st.spinner("Obteniendo cuotas y últimos partidos en liga (Selenium)..."):
                    try:
                        # Cargar página principal para filtros Selenium
                        driver_actual.get(f"{BASE_URL}{main_page_url_h2h_view}") 
                        WebDriverWait(driver_actual, SELENIUM_TIMEOUT_SECONDS, poll_frequency=SELENIUM_POLL_FREQUENCY).until(EC.presence_of_element_located((By.ID, "table_v1"))) # Esperar tabla de local
                        time.sleep(0.8) # Pequeña pausa
                        
                        main_match_odds_data = get_main_match_odds_selenium(driver_actual) # Obtener cuotas después de cargar
                        
                        if mp_home_id and mp_league_id and mp_home_name != "N/A":
                            last_home_match_in_league = extract_last_match_in_league(driver_actual, "table_v1", mp_home_name, mp_league_id, "input#cb_sos1[value='1']", is_home_game_filter=True)
                        
                        if mp_away_id and mp_league_id and mp_away_name != "N/A":
                            last_away_match_in_league = extract_last_match_in_league(driver_actual, "table_v2", mp_away_name, mp_league_id, "input#cb_sos2[value='2']", is_home_game_filter=False)
                    
                    except Exception as e_main_page_sel: 
                        st.error(f"Error Selenium en pág. principal: {type(e_main_page_sel).__name__} - {str(e_main_page_sel)[:100]}")

                st.markdown("#### <span style='color:#FF9800;'>📊 Cuotas Bet365/Betfair (Iniciales)</span>", unsafe_allow_html=True)
                col_odds1, col_odds2 = st.columns(2)
                cuota_style = "font-size:1.1em; padding: 5px; border-radius: 4px;"
                linea_style = "color:black; font-weight:bold; background-color:#E0E0E0; padding: 2px 6px; border-radius:3px;"
                with col_odds1: st.markdown(f"""**H. Asiático:** <span style='{cuota_style}'>{main_match_odds_data.get('ah_home_cuota','-')}</span> <span style='{linea_style}'>{main_match_odds_data.get('ah_linea','-')}</span> <span style='{cuota_style}'>{main_match_odds_data.get('ah_away_cuota','-')}</span>""", unsafe_allow_html=True)
                with col_odds2: st.markdown(f"""**Línea Goles:** <span style='{cuota_style}'>Ov {main_match_odds_data.get('goals_over_cuota','-')}</span> <span style='{linea_style}'>{main_match_odds_data.get('goals_linea','-')}</span> <span style='{cuota_style}'>Un {main_match_odds_data.get('goals_under_cuota','-')}</span>""", unsafe_allow_html=True)
                
                st.markdown("---")
                st.markdown("### ⚔️ Análisis Detallado de Últimos Partidos y H2H")
                col1_display, col2_display, col3_display = st.columns(3)

                with col1_display:
                    st.markdown(f"##### <span style='color:#4CAF50;'>🏡 Último de {mp_home_name or 'Local'}</span><br>(Local, Misma Liga)", unsafe_allow_html=True)
                    if last_home_match_in_league:
                        res = last_home_match_in_league
                        st.markdown(f"<div style='background-color:#F1F8E9; padding:10px; border-radius:5px;'>"
                                    f"{res['home_team']} <strong style='color:#33691E;'>{res['score']}</strong> {res['away_team']}<br>"
                                    f"**AH:** <span style='font-weight:bold; color:#689F38;'>{res.get('handicap_line_formatted','N/A')}</span> (Raw: {res.get('handicap_line_raw','N/A')})<br>"
                                    f"<small><i>{res['date']}</i></small></div>", unsafe_allow_html=True)
                    else: st.info("No encontrado o error (Local).")
                
                with col2_display:
                    st.markdown(f"##### <span style='color:#2196F3;'>✈️ Último de {mp_away_name or 'Visitante'}</span><br>(Visitante, Misma Liga)", unsafe_allow_html=True)
                    if last_away_match_in_league:
                        res = last_away_match_in_league
                        st.markdown(f"<div style='background-color:#E3F2FD; padding:10px; border-radius:5px;'>"
                                    f"{res['home_team']} <strong style='color:#0D47A1;'>{res['score']}</strong> {res['away_team']}<br>"
                                    f"**AH:** <span style='font-weight:bold; color:#1976D2;'>{res.get('handicap_line_formatted','N/A')}</span> (Raw: {res.get('handicap_line_raw','N/A')})<br>"
                                    f"<small><i>{res['date']}</i></small></div>", unsafe_allow_html=True)
                    else: st.info("No encontrado o error (Visitante).")

                with col3_display:
                    st.markdown(f"##### <span style='color:#E65100;'>🆚 H2H Oponentes</span><br>(Oponentes Recientes)", unsafe_allow_html=True)
                    key_h2h_url, rival_a_id, rival_a_name_disp = None, None, None
                    rival_b_id, rival_b_name_disp = None, None
                    
                    with st.spinner("Obteniendo datos para H2H de oponentes (Requests)..."):
                        if mp_home_id: # Usar el ID del local del partido principal para obtener su último oponente (Rival A)
                            key_h2h_url, rival_a_id, rival_a_name_disp = get_rival_a_for_original_h2h(main_match_id_to_process) # Usa el ID del partido principal.
                        if mp_away_id: # Usar el ID del visitante del partido principal para obtener su último oponente (Rival B)
                            rival_b_id, rival_b_name_disp = get_rival_b_for_original_h2h(main_match_id_to_process) # Usa el ID del partido principal.

                    rival_a_display_name = rival_a_name_disp if rival_a_name_disp and rival_a_name_disp != "N/A" else (rival_a_id or "Rival A")
                    rival_b_display_name = rival_b_name_disp if rival_b_name_disp and rival_b_name_disp != "N/A" else (rival_b_id or "Rival B")
                    st.caption(f"Buscando H2H entre: **{rival_a_display_name}** y **{rival_b_display_name}**")

                    details_h2h_col3 = {"status": "error", "resultado": "N/A (Datos iniciales insuficientes para H2H Oponentes)"}
                    if key_h2h_url and rival_a_id and rival_b_id: # Si tenemos todos los IDs necesarios
                        with st.spinner(f"Cargando H2H con Selenium..."):
                            details_h2h_col3 = get_h2h_details_for_original_logic(driver_actual, key_h2h_url, rival_a_id, rival_b_id)
                    
                    if details_h2h_col3.get("status") == "found":
                        res_h2h = details_h2h_col3
                        score_h2h_display = res_h2h.get('score_raw', '?-?')
                        local_h2h_name_display = res_h2h.get('h2h_home_team_name', 'Local H2H')
                        visit_h2h_name_display = res_h2h.get('h2h_away_team_name', 'Visitante H2H')
                        rol_rival_a_info = res_h2h.get('rol_rival_a_en_h2h', 'N/D')
                        st.markdown(f"<div style='background-color:#FFF3E0; padding:10px; border-radius:5px;'>"
                                    f"{local_h2h_name_display} <strong style='color:#E65100;'>{score_h2h_display}</strong> {visit_h2h_name_display}<br>"
                                    f"**AH:** <span style='font-weight:bold; color:#EF6C00;'>{res_h2h.get('handicap_formatted','N/A')}</span> (Raw: {res_h2h.get('handicap_raw','N/A')})<br>"
                                    f"<small><i>Rol de '{rival_a_display_name}' en este H2H: {rol_rival_a_info}</i></small></div>", unsafe_allow_html=True)
                    else: 
                        st.info(f"H2H Oponentes: {details_h2h_col3.get('resultado', 'No disponible')}")
                
                end_time_analysis = time.time()
                st.markdown("---")
                st.caption(f"⏱️ Tiempo total del análisis: {end_time_analysis - start_time_analysis:.2f} segundos")

                # --- NUEVA SECCIÓN DE TABLA COMPARATIVA ---
                display_comparative_stats_table(
                    driver_actual,
                    main_match_id_to_process,
                    mp_home_name,
                    mp_away_name,
                    last_home_match_in_league,
                    last_away_match_in_league,
                    details_h2h_col3,
                )
    else: 
        st.info("✨ Ingresa un ID de partido en la barra lateral y haz clic en 'Analizar Partido' para comenzar.")
        st.caption("Nota: La primera ejecución puede tardar más mientras se inicializa el WebDriver.")
