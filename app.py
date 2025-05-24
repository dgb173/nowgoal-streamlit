# streamlit_app_codigogithub_mejorado.py

import streamlit as st
import time
import requests
import re
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import math # Para formateo de hándicap
import os   # Para caché de webdriver-manager
import shutil # Para caché de webdriver-manager

# Importaciones de Selenium
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, ElementClickInterceptedException, NoSuchElementException, SessionNotCreatedException
from selenium.webdriver.chrome.service import Service as ChromeService


# --- CONFIGURACIÓN GLOBAL ---
BASE_URL = "https://live18.nowgoal25.com" # Usada por la mayoría de las funciones aquí
SELENIUM_TIMEOUT_SECONDS = 20 
SELENIUM_POLL_FREQUENCY = 0.2 

# --- FUNCIONES DE FORMATEO DE HÁNDICAP (Importadas) ---
@st.cache_data(show_spinner=False)
def parse_ah_to_number(ah_line_str: str): # (COPIA AQUÍ LA FUNCIÓN COMPLETA parse_ah_to_number)
    if not isinstance(ah_line_str, str): return None
    s = ah_line_str.strip().replace(' ', '')
    if not s or s in ['-', '?']: return None
    original_starts_with_minus = ah_line_str.strip().startswith('-')
    try:
        if '/' in s:
            parts = s.split('/')
            if len(parts) != 2: return None
            p1_str, p2_str = parts[0], parts[1]
            try: val1 = float(p1_str); val2 = float(p2_str)
            except ValueError: return None
            if val1 < 0 and not p2_str.startswith('-') and val2 > 0: val2 = -abs(val2)
            elif original_starts_with_minus and val1 == 0.0 and (p1_str=="0" or p1_str=="-0") and not p2_str.startswith('-') and val2 > 0: val2 = -abs(val2)
            return (val1 + val2) / 2.0
        else: return float(s)
    except ValueError: return None

@st.cache_data(show_spinner=False)
def format_ah_as_decimal_string(ah_line_str: str): # (COPIA AQUÍ LA FUNCIÓN COMPLETA format_ah_as_decimal_string)
    if not isinstance(ah_line_str, str) or not ah_line_str.strip() or ah_line_str.strip() in ['-', '?']:
        return ah_line_str.strip() if isinstance(ah_line_str, str) else '-'
    numeric_value = parse_ah_to_number(ah_line_str)
    if numeric_value is None: return ah_line_str.strip() if isinstance(ah_line_str, str) else '-'
    if numeric_value == 0.0: return "0"
    sign = -1 if numeric_value < 0 else 1
    abs_num = abs(numeric_value); parte_entera = math.floor(abs_num)
    parte_decimal_original = round(abs_num - parte_entera, 4)
    nueva_parte_decimal = parte_decimal_original; epsilon = 1e-9
    if abs(parte_decimal_original - 0.25) < epsilon: nueva_parte_decimal = 0.5
    elif abs(parte_decimal_original - 0.75) < epsilon: nueva_parte_decimal = 0.5
    if nueva_parte_decimal != 0.0 and nueva_parte_decimal != 0.5:
        if nueva_parte_decimal < 0.25: nueva_parte_decimal = 0.0
        elif nueva_parte_decimal < 0.75: nueva_parte_decimal = 0.5
        else: nueva_parte_decimal = 0.0; parte_entera +=1
    resultado_num_redondeado = parte_entera + nueva_parte_decimal
    final_value_signed = sign * resultado_num_redondeado
    if final_value_signed == 0.0: return "0"
    return str(int(round(final_value_signed))) if abs(final_value_signed - round(final_value_signed)) < epsilon else f"{final_value_signed:.1f}"


# --- FUNCIONES DE REQUESTS ---
@st.cache_resource 
def get_requests_session(): # Idéntica a tu original
    session = requests.Session()
    retries_req = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    adapter_req = HTTPAdapter(max_retries=retries_req)
    session.mount("https://", adapter_req); session.mount("http://", adapter_req)
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"})
    return session

@st.cache_data(ttl=3600, show_spinner=False) 
def fetch_soup_requests(path, max_tries=3, delay=1): # Idéntica a tu original
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

# --- FUNCIONES PARA LÓGICA ORIGINAL DE H2H (Columna 3) ---
@st.cache_data(ttl=3600, show_spinner=False)
def get_rival_a_for_original_h2h(main_match_id): # Idéntica a tu original
    soup = fetch_soup_requests(f"/match/h2h-{main_match_id}")
    if not soup: return None, None, None
    table = soup.find("table", id="table_v1")
    if not table: return None, None, None
    for row in table.find_all("tr", id=re.compile(r"tr1_\d+")):
        if row.get("vs") == "1":
            key_match_id_for_h2h_url = row.get("index") 
            if not key_match_id_for_h2h_url: continue
            onclicks = row.find_all("a", onclick=True)
            if len(onclicks) > 1 and onclicks[1].get("onclick"):
                rival_a_id_match = re.search(r"team\((\d+)\)", onclicks[1]["onclick"])
                rival_a_name = onclicks[1].text.strip()
                if rival_a_id_match and rival_a_name:
                    return key_match_id_for_h2h_url, rival_a_id_match.group(1), rival_a_name
    return None, None, None

@st.cache_data(ttl=3600, show_spinner=False)
def get_rival_b_for_original_h2h(main_match_id): # Idéntica a tu original
    soup = fetch_soup_requests(f"/match/h2h-{main_match_id}")
    if not soup: return None, None
    table = soup.find("table", id="table_v2") 
    if not table: return None, None
    for row in table.find_all("tr", id=re.compile(r"tr2_\d+")):
        if row.get("vs") == "1": 
            onclicks = row.find_all("a", onclick=True)
            if len(onclicks) > 0 and onclicks[0].get("onclick"): 
                rival_b_id_match = re.search(r"team\((\d+)\)", onclicks[0]["onclick"])
                rival_b_name = onclicks[0].text.strip() 
                if rival_b_id_match and rival_b_name:
                    return rival_b_id_match.group(1), rival_b_name
    return None, None

# --- FUNCIONES DE SELENIUM (DRIVER MEJORADO) ---
@st.cache_resource(show_spinner="Inicializando WebDriver...")
def get_selenium_driver_cached_for_this_script(): # Versión del driver que hemos estado depurando
    # (COPIA AQUÍ LA FUNCIÓN get_selenium_driver_cached que mejor te haya funcionado,
    #  preferiblemente la que forza la versión "120" con webdriver-manager y tiene fallback)
    st.write("--- (Este Script) INICIANDO get_selenium_driver_cached ---")
    options = ChromeOptions()
    options.add_argument("--headless"); options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage"); options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    options.add_argument('--blink-settings=imagesEnabled=false')
    prefs = {"profile.managed_default_content_settings.images": 2, "profile.default_content_setting_values.notifications": 2}
    options.add_experimental_option("prefs", prefs)
    driver = None
    try:
        st.write("✅ (Este Script) Intentando con `webdriver-manager`...")
        from webdriver_manager.chrome import ChromeDriverManager
        try:
            cache_path = os.path.join(os.path.expanduser("~"), ".wdm")
            if os.path.exists(cache_path): shutil.rmtree(cache_path)
        except Exception: pass
        chrome_driver_version_to_force = "120"
        st.write(f"ℹ️ (Este Script) Intentando instalar ChromeDriver ~{chrome_driver_version_to_force}...")
        driver_path = ChromeDriverManager(version=chrome_driver_version_to_force).install()
        if not os.path.exists(driver_path): raise FileNotFoundError(f"Driver no encontrado en {driver_path}")
        service = ChromeService(executable_path=driver_path)
        driver = webdriver.Chrome(service=service, options=options)
        st.success("✅ (Este Script) WebDriver con `webdriver-manager` (forzado) OK.")
        return driver
    except ImportError: st.error("❌ (Este Script) `webdriver-manager` no instalado.") ; return None
    except Exception as e_wdm: st.error(f"❌ (Este Script) Error con `webdriver-manager`: {e_wdm}")
    if driver is None:
        st.warning("⚠️ (Este Script) Fallback al ChromeDriver del PATH...")
        try:
            driver = webdriver.Chrome(options=options) 
            st.success("✅ (Este Script) WebDriver (del PATH) inicializado.")
            return driver 
        except Exception as e_path: st.error(f"❌ (Este Script) Error ChromeDriver del PATH: {e_path}")
    st.error("🔴 (Este Script) No se pudo iniciar Selenium.")
    return None


def get_h2h_details_for_original_logic(driver_instance, key_match_id_for_h2h_url, rival_a_id, rival_b_id):
    if not driver_instance: return {"status": "error", "resultado": "Driver no disponible (H2H Original)"}
    if not key_match_id_for_h2h_url or not rival_a_id or not rival_b_id:
        return {"status": "error", "resultado": "N/A (IDs incompletos para H2H Original)"}
    url = f"{BASE_URL}/match/h2h-{key_match_id_for_h2h_url}"
    try:
        driver_instance.get(url)
        WebDriverWait(driver_instance, SELENIUM_TIMEOUT_SECONDS, poll_frequency=SELENIUM_POLL_FREQUENCY).until(
            EC.presence_of_element_located((By.ID, "table_v2")) # Espera tabla v2 como en tu original
        )
        time.sleep(0.7) 
        soup_selenium = BeautifulSoup(driver_instance.page_source, "html.parser")
    except Exception as e: return {"status": "error", "resultado": f"N/A (Error Selenium H2H Original: {type(e).__name__})"}
    
    if not soup_selenium: return {"status": "error", "resultado": "N/A (Fallo soup Selenium H2H Original)"}
    table = soup_selenium.find("table", id="table_v2") 
    if not table: return {"status": "error", "resultado": "N/A (Tabla H2H Original (v2) no encontrada)"}

    for row in table.find_all("tr", id=re.compile(r"tr2_\d+")): 
        links = row.find_all("a", onclick=True)
        if len(links) < 2: continue
        h2h_rhid_m = re.search(r"team\((\d+)\)", links[0].get("onclick", "")) # Local del partido en la fila
        h2h_raid_m = re.search(r"team\((\d+)\)", links[1].get("onclick", "")) # Visitante del partido en la fila
        if not h2h_rhid_m or not h2h_raid_m: continue
        h2h_rhid, h2h_raid = h2h_rhid_m.group(1), h2h_raid_m.group(1)
        
        if {h2h_rhid, h2h_raid} == {str(rival_a_id), str(rival_b_id)}: # Compara con los IDs de los rivales que buscamos
            score_span = row.find("span", class_="fscore_2") 
            if not score_span or not score_span.text or "-" not in score_span.text: continue
            score_val = score_span.text.strip()
            g_h, g_a = score_val.split("-")
            tds = row.find_all("td")
            handicap_val_raw = "N/A"
            HANDICAP_TD_IDX = 11 
            if len(tds) > HANDICAP_TD_IDX:
                cell = tds[HANDICAP_TD_IDX]
                d_o = cell.get("data-o"); handicap_val_raw = d_o.strip() if d_o and d_o.strip() not in ["", "-"] else (cell.text.strip() if cell.text.strip() not in ["", "-"] else "N/A")
            
            handicap_formatted = format_ah_as_decimal_string(handicap_val_raw) # FORMATEO APLICADO
            
            rol_a = "A" if h2h_raid == str(rival_a_id) else "H" 
            return {
                "status": "found", "goles_home": g_h.strip(), "goles_away": g_a.strip(), 
                "handicap_raw": handicap_val_raw, "handicap_formatted": handicap_formatted, # AMBOS FORMATOS
                "rol_rival_a": rol_a, 
                "h2h_home_team_name": links[0].text.strip(), "h2h_away_team_name": links[1].text.strip()
            }
    return {"status": "not_found", "resultado": "N/A (H2H Original no encontrado en tabla v2)"}

# --- FUNCIONES PARA NUEVA LÓGICA (Col1 y Col2: Últimos Partidos en Liga, Cuotas del Partido Principal) ---
def get_team_league_info_from_script(soup): # Idéntica a tu original
    home_id, away_id, league_id, home_name, away_name, league_name = (None,)*3 + ("N/A",)*3
    script_tag = soup.find("script", string=re.compile(r"var _matchInfo ="))
    if script_tag:
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

def click_element_robust(driver, by, value, timeout=7): # Idéntica a tu original
    try:
        element = WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY).until(EC.presence_of_element_located((by, value)))
        WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY).until(EC.visibility_of(element) )
        driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'center'});", element); time.sleep(0.3)
        try:
            WebDriverWait(driver, 2, poll_frequency=SELENIUM_POLL_FREQUENCY).until(EC.element_to_be_clickable((by, value))).click()
        except (ElementClickInterceptedException, TimeoutException): driver.execute_script("arguments[0].click();", element)
        return True
    except Exception: return False

def extract_last_match_in_league(driver, table_css_id_str, main_team_name_in_table, league_id_filter_value, 
                                 home_or_away_filter_css_selector, is_home_game_filter):
    try:
        league_checkbox_selector = f"input#checkboxleague{table_css_id_str[-1]}[value='{league_id_filter_value}']"
        if not click_element_robust(driver, By.CSS_SELECTOR, league_checkbox_selector):
            st.toast(f"No se pudo clickear checkbox de liga para {table_css_id_str}", icon="⚠️")
            # return None # No retornar, intentar seguir sin filtro de liga si el checkbox no se pudo
        time.sleep(1.5) 
        if not click_element_robust(driver, By.CSS_SELECTOR, home_or_away_filter_css_selector):
            st.toast(f"No se pudo clickear filtro local/visitante para {table_css_id_str}", icon="⚠️")
            # return None # No retornar, tomar el general
        time.sleep(1.5) 

        page_source_updated = driver.page_source
        soup_updated = BeautifulSoup(page_source_updated, "html.parser")
        table = soup_updated.find("table", id=table_css_id_str)
        if not table: return None

        for row_idx, row in enumerate(table.find_all("tr", id=re.compile(rf"tr{table_css_id_str[-1]}_\d+"))):
            if row.get("style") and "display:none" in row.get("style"): continue 
            if row_idx > 7: break 
            
            # Permitir que pase si el filtro de liga no funcionó (row.get("name") puede no coincidir)
            # O si el ID de la liga es el correcto.
            is_correct_league = str(row.get("name")) == str(league_id_filter_value)

            tds = row.find_all("td")
            if len(tds) < 14: continue

            home_team_row_el = tds[2].find("a")
            away_team_row_el = tds[4].find("a")
            if not home_team_row_el or not away_team_row_el: continue
            
            home_team_row_name = home_team_row_el.text.strip()
            away_team_row_name = away_team_row_el.text.strip()

            team_is_home_in_row = main_team_name_in_table == home_team_row_name
            team_is_away_in_row = main_team_name_in_table == away_team_row_name

            # Verificar si el equipo principal jugó en el rol esperado (local/visitante)
            # Y si la liga es la correcta (si pudimos filtrar)
            if ( (is_home_game_filter and team_is_home_in_row) or \
                 (not is_home_game_filter and team_is_away_in_row) ) and is_correct_league:
                
                date_span = tds[1].find("span", {"name": "timeData"})
                date = date_span.text.strip() if date_span else "N/A"
                score_span = tds[3].find("span", class_=re.compile(r"fscore_")) 
                score = score_span.text.strip() if score_span else "N/A"
                
                handicap_cell = tds[11] 
                handicap_raw = handicap_cell.get("data-o", handicap_cell.text.strip())
                if not handicap_raw or handicap_raw == "-": handicap_raw = "N/A"
                
                handicap_formatted = format_ah_as_decimal_string(handicap_raw) # FORMATEO APLICADO

                return {
                    "date": date, "home_team": home_team_row_name, "away_team": away_team_row_name,
                    "score": score, "handicap_line_raw": handicap_raw, "handicap_line_formatted": handicap_formatted
                }
        return None # No se encontró un partido que cumpla todas las condiciones (incluida la liga)
    except Exception as e:
        st.toast(f"Error en extract_last_match_in_league: {e}", icon="🔥")
        return None

def get_main_match_odds_selenium(driver): # Idéntica a tu original
    odds_info = { "ah_home_cuota": "N/A", "ah_linea": "N/A", "ah_away_cuota": "N/A",
                  "goals_over_cuota": "N/A", "goals_linea": "N/A", "goals_under_cuota": "N/A"}
    try:
        live_compare_div = WebDriverWait(driver, 10, poll_frequency=SELENIUM_POLL_FREQUENCY).until(EC.presence_of_element_located((By.ID, "liveCompareDiv")))
        bet365_row_selector = "tr#tr_o_1_8[name='earlyOdds']"; bet365_row_selector_alt = "tr#tr_o_1_31[name='earlyOdds']" # Para Betfair como fallback
        
        try:
            bet365_early_odds_row = WebDriverWait(live_compare_div, 5, poll_frequency=SELENIUM_POLL_FREQUENCY).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, bet365_row_selector)) )
        except TimeoutException: # Probar con Betfair si Bet365 no está
            # st.toast("Cuotas Bet365 no encontradas, intentando Betfair...", icon="ℹ️")
            bet365_early_odds_row = WebDriverWait(live_compare_div, 3, poll_frequency=SELENIUM_POLL_FREQUENCY).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, bet365_row_selector_alt)) )

        tds = bet365_early_odds_row.find_elements(By.TAG_NAME, "td")
        if len(tds) >= 11: 
            odds_info["ah_home_cuota"] = tds[2].get_attribute("data-o") or tds[2].text.strip()
            odds_info["ah_linea"] = format_ah_as_decimal_string(tds[3].get_attribute("data-o") or tds[3].text.strip()) # FORMATEO APLICADO
            odds_info["ah_away_cuota"] = tds[4].get_attribute("data-o") or tds[4].text.strip()
            odds_info["goals_over_cuota"] = tds[8].get_attribute("data-o") or tds[8].text.strip()
            odds_info["goals_linea"] = format_ah_as_decimal_string(tds[9].get_attribute("data-o") or tds[9].text.strip()) # FORMATEO APLICADO
            odds_info["goals_under_cuota"] = tds[10].get_attribute("data-o") or tds[10].text.strip()
    except Exception as e:
        # st.toast(f"No se pudieron obtener cuotas: {e}", icon="⚠️")
        pass
    return odds_info

# --- STREAMLIT APP UI ---
# ... (UI adaptada de tu `codigogithub.txt` pero más visual y usando las funciones mejoradas) ...
st.set_page_config(page_title="Análisis Visual Avanzado H2H Nowgoal", layout="wide", initial_sidebar_state="expanded")
st.title("🏆 Análisis Visual Avanzado de Partidos - Nowgoal")

st.sidebar.image("https://nowgoal.com/img/logo.png", width=150) 
st.sidebar.header("Configuración")
main_match_id_str_input = st.sidebar.text_input(
    "🆔 ID del Partido Principal:", value="2778085", 
    help="Pega el ID del partido para el análisis completo.")
analizar_button = st.sidebar.button("🚀 Analizar Partido", type="primary", use_container_width=True)
st.sidebar.markdown("---")
st.sidebar.info("""
Esta app muestra:
- **Cuotas Iniciales** (Bet365/Betfair) del Partido Principal.
- **Últimos Partidos en Liga** del Local (en casa) y Visitante (fuera) con su H.A.
- **H2H de Oponentes Recientes**: Basado en los últimos oponentes generales (no necesariamente en liga) del equipo local del partido principal.
Hándicaps formateados a decimal (ej: 0, -1.5, 2.0).
""")

if 'driver_global' not in st.session_state: # Usar un nombre diferente para el driver global en sesión
    st.session_state.driver_global = None

if analizar_button:
    main_match_id_to_process = None
    if main_match_id_str_input:
        try:
            cleaned_id_str = "".join(filter(str.isdigit, main_match_id_str_input))
            if cleaned_id_str: main_match_id_to_process = int(cleaned_id_str)
        except ValueError: st.error("⚠️ ID de partido no válido."); st.stop()
    
    if not main_match_id_to_process:
        st.warning("⚠️ Ingresa un ID de partido válido.")
    else:
        # INICIALIZAR DRIVER (SI ES NECESARIO)
        if st.session_state.driver_global is None or not hasattr(st.session_state.driver_global, 'window_handles'):
            if st.session_state.driver_global is not None: # Si existía pero murió
                try: st.session_state.driver_global.quit()
                except: pass
            st.session_state.driver_global = get_selenium_driver_cached_for_this_script() # Usa la función de driver mejorada
        
        driver = st.session_state.driver_global # Usar el driver de la sesión

        if not driver:
            st.error("🔴 No se pudo iniciar Selenium. El análisis no puede continuar. Revisa los mensajes al inicio.")
        else:
            start_time = time.time()
            st.markdown(f"### 📋 Información del Partido Principal (ID: {main_match_id_to_process})")
            
            with st.spinner("Obteniendo información básica del partido principal (Requests)..."):
                main_page_url_h2h_view = f"/match/h2h-{main_match_id_to_process}"
                soup_main_h2h_page = fetch_soup_requests(main_page_url_h2h_view)
            
            mp_home_id, mp_away_id, mp_league_id, mp_home_name, mp_away_name, mp_league_name = (None,)*3 + ("N/A",)*3
            if soup_main_h2h_page:
                mp_home_id, mp_away_id, mp_league_id, mp_home_name, mp_away_name, mp_league_name = get_team_league_info_from_script(soup_main_h2h_page)
            else:
                st.error("No se pudo obtener información básica del partido principal con Requests. Algunas funciones pueden fallar.")

            col_mp_info1, col_mp_info2, col_mp_info3 = st.columns(3)
            with col_mp_info1: st.markdown(f"**Local:**<br><span style='font-size:1.1em; font-weight:bold;'>{mp_home_name or 'N/A'}</span> (ID: {mp_home_id or 'N/A'})", unsafe_allow_html=True)
            with col_mp_info2: st.markdown(f"**Visitante:**<br><span style='font-size:1.1em; font-weight:bold;'>{mp_away_name or 'N/A'}</span> (ID: {mp_away_id or 'N/A'})", unsafe_allow_html=True)
            with col_mp_info3: st.markdown(f"**Liga:**<br><span style='font-size:1.1em;'>{mp_league_name or 'N/A'}</span> (ID: {mp_league_id or 'N/A'})", unsafe_allow_html=True)
            
            main_match_odds_data = {}
            last_home_match_in_league = None 
            last_away_match_in_league = None
            
            with st.spinner("Obteniendo cuotas y últimos partidos en liga (Selenium)..."):
                # Esta página se usa para varias extracciones, así que la cargamos una vez aquí si es posible.
                try:
                    # st.write(f"⚙️ (Selenium) Accediendo a {BASE_URL}{main_page_url_h2h_view} para datos detallados...")
                    driver.get(f"{BASE_URL}{main_page_url_h2h_view}")
                    # Espera un elemento general para confirmar carga. Podría ser más específico.
                    WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS, poll_frequency=SELENIUM_POLL_FREQUENCY).until(
                        EC.presence_of_element_located((By.ID, "table_v1")) 
                    )
                    time.sleep(0.8) # Pausa para renderizado JS

                    main_match_odds_data = get_main_match_odds_selenium(driver)
                    
                    if mp_home_id and mp_league_id and mp_home_name: # Necesario para filtro de liga local
                        last_home_match_in_league = extract_last_match_in_league(
                            driver, "table_v1", mp_home_name, mp_league_id,
                            "input#cb_sos1", is_home_game_filter=True
                        )
                    else: st.toast("Faltan datos (Local/Liga) para filtrar último partido en casa.", icon="⚠️")
                    
                    # Necesario recargar o asegurar que los filtros no interfieran.
                    # Es más seguro si la función extract_last_match_in_league maneja sus propios filtros desde una página "limpia" o resetea.
                    # Por ahora, asumimos que la página está en un estado base después de obtener cuotas.
                    # O podemos re-navegar (puede ser más lento pero más seguro para aislar la extracción)
                    # driver.get(f"{BASE_URL}{main_page_url_h2h_view}") # Opcional: Re-navegar para resetear estado
                    # WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS).until(EC.presence_of_element_located((By.ID, "table_v2")))
                    # time.sleep(0.5)
                    if mp_away_id and mp_league_id and mp_away_name: # Necesario para filtro de liga visitante
                         last_away_match_in_league = extract_last_match_in_league(
                            driver, "table_v2", mp_away_name, mp_league_id,
                            "input#cb_sos2", is_home_game_filter=False
                        )
                    else: st.toast("Faltan datos (Visitante/Liga) para filtrar último partido fuera.", icon="⚠️")

                except Exception as e_main_page_sel:
                    st.error(f"Error general de Selenium en la página principal: {e_main_page_sel}")


            st.markdown("#### <span style='color:#FF9800;'>📊 Cuotas Bet365/Betfair (Iniciales del Partido Principal)</span>", unsafe_allow_html=True)
            col_odds1, col_odds2 = st.columns(2)
            cuota_style = "font-size:1.1em; padding: 5px; border-radius: 4px;"
            linea_style = "color:black; font-weight:bold; background-color:#E0E0E0; padding: 2px 6px; border-radius:3px;"

            with col_odds1:
                st.markdown(f"""**H. Asiático:** 
                <span style='{cuota_style}'>{main_match_odds_data.get('ah_home_cuota','-')}</span> 
                <span style='{linea_style}'>{main_match_odds_data.get('ah_linea','-')}</span> 
                <span style='{cuota_style}'>{main_match_odds_data.get('ah_away_cuota','-')}</span>""", unsafe_allow_html=True)
            with col_odds2:
                st.markdown(f"""**Línea Goles:** 
                <span style='{cuota_style}'>Ov {main_match_odds_data.get('goals_over_cuota','-')}</span> 
                <span style='{linea_style}'>{main_match_odds_data.get('goals_linea','-')}</span> 
                <span style='{cuota_style}'>Un {main_match_odds_data.get('goals_under_cuota','-')}</span>""", unsafe_allow_html=True)
            st.markdown("---")

            st.markdown("### ⚔️ Análisis Detallado de Últimos Partidos y H2H")
            col1_display, col2_display, col3_display = st.columns(3)

            with col1_display:
                st.markdown(f"##### <span style='color:#4CAF50;'>🏡 Último de {mp_home_name or 'Local'}</span><br>(Local, Misma Liga)", unsafe_allow_html=True)
                if last_home_match_in_league:
                    res = last_home_match_in_league
                    st.markdown(f"<div style='background-color:#F1F8E9; padding:10px; border-radius:5px;'>"
                                f"{res['home_team']} <strong style='color:#33691E;'>{res['score']}</strong> {res['away_team']}<br>"
                                f"**AH:** <span style='font-weight:bold; color:#689F38;'>{res.get('handicap_line_formatted','N/A')}</span> "
                                f"(Raw: {res.get('handicap_line_raw','N/A')})<br>"
                                f"<small><i>{res['date']}</i></small>"
                                f"</div>", unsafe_allow_html=True)
                else: st.info("No encontrado o error al filtrar.")
            
            with col2_display:
                st.markdown(f"##### <span style='color:#2196F3;'>✈️ Último de {mp_away_name or 'Visitante'}</span><br>(Visitante, Misma Liga)", unsafe_allow_html=True)
                if last_away_match_in_league:
                    res = last_away_match_in_league
                    st.markdown(f"<div style='background-color:#E3F2FD; padding:10px; border-radius:5px;'>"
                                f"{res['home_team']} <strong style='color:#0D47A1;'>{res['score']}</strong> {res['away_team']}<br>"
                                f"**AH:** <span style='font-weight:bold; color:#1976D2;'>{res.get('handicap_line_formatted','N/A')}</span> "
                                f"(Raw: {res.get('handicap_line_raw','N/A')})<br>"
                                f"<small><i>{res['date']}</i></small>"
                                f"</div>", unsafe_allow_html=True)
                else: st.info("No encontrado o error al filtrar.")

            with col3_display:
                st.markdown(f"##### <span style='color:#E65100;'>🆚 H2H Oponentes</span><br>(Últimos Oponentes Generales del Local del Partido Principal)", unsafe_allow_html=True)
                with st.spinner("Obteniendo H2H de oponentes (Requests + Selenium)..."):
                    key_h2h_url, rival_a_id, rival_a_name_disp = get_rival_a_for_original_h2h(main_match_id_to_process)
                    rival_b_id, rival_b_name_disp = get_rival_b_for_original_h2h(main_match_id_to_process)
                
                rival_a_display_name = rival_a_name_disp or (rival_a_id or "Rival A")
                rival_b_display_name = rival_b_name_disp or (rival_b_id or "Rival B")
                st.caption(f"Buscando H2H entre: **{rival_a_display_name}** y **{rival_b_display_name}**")

                details_h2h_col3 = {"status": "error", "resultado": "N/A"}
                if key_h2h_url and rival_a_id and rival_b_id:
                    with st.spinner(f"Cargando H2H con Selenium... (URL de ref.: h2h-{key_h2h_url})"):
                        details_h2h_col3 = get_h2h_details_for_original_logic(driver, key_h2h_url, rival_a_id, rival_b_id)
                
                if details_h2h_col3.get("status") == "found":
                    res_h2h = details_h2h_col3
                    # Determinar quién fue el local en el partido H2H encontrado
                    if res_h2h['rol_rival_a'] == 'H': # rival_a_id fue local
                        local_h2h = rival_a_display_name
                        visit_h2h = rival_b_display_name
                        score_h2h = f"{res_h2h['goles_home']}-{res_h2h['goles_away']}"
                    else: # rival_a_id fue visitante, por tanto rival_b_id fue local
                        local_h2h = rival_b_display_name
                        visit_h2h = rival_a_display_name
                        # El score siempre es LocalH2H - VisitanteH2H según la tabla de Nowgoal
                        score_h2h = f"{res_h2h['goles_home']}-{res_h2h['goles_away']}"


                    st.markdown(f"<div style='background-color:#FFF3E0; padding:10px; border-radius:5px;'>"
                                f"{local_h2h} <strong style='color:#E65100;'>{score_h2h}</strong> {visit_h2h}<br>"
                                f"**AH:** <span style='font-weight:bold; color:#EF6C00;'>{res_h2h.get('handicap_formatted','N/A')}</span> "
                                f"(Raw: {res_h2h.get('handicap_raw','N/A')})<br>"
                                f"<small><i>Rol de '{rival_a_display_name}' en este H2H: {res_h2h['rol_rival_a']}</i></small>"
                                f"</div>", unsafe_allow_html=True)
                else:
                    st.info(f"{details_h2h_col3.get('resultado', 'No disponible')}")
            
            end_time = time.time()
            st.markdown("---")
            st.caption(f"⏱️ Tiempo total del análisis (incl. WebDriver si se reinició): {end_time - start_time:.2f} segundos")
            
            # Considerar cerrar el driver aquí si no se va a reutilizar mucho en la misma sesión de usuario.
            # O dejarlo para que el @st.cache_resource lo maneje.
            # if driver: 
            #     driver.quit()
            #     st.session_state.driver_global = None
            #     st.toast("WebDriver cerrado.", icon="💤")

else:
    st.info("✨ Ingresa un ID de partido en la barra lateral y haz clic en 'Analizar Partido' para comenzar.")
