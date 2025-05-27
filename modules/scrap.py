# modules/other_feature_NUEVO.py
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
BASE_URL_OF = "https://live18.nowgoal25.com" # Verifica que este sea el dominio correcto
# Para URLs dentro de la función `formatDate` JS de la página, como 'football.nowgoal25.com'.
# Ahora se maneja para la función `format_date_for_display_of`.
SELENIUM_TIMEOUT_SECONDS_OF = 20
SELENIUM_POLL_FREQUENCY_OF = 0.2

# --- ESTILOS CSS PERSONALIZADOS ---
def apply_custom_css_of():
    st.markdown("""
        <style>
            /* Reducir tamaño de fuente general */
            html, body, [class*="st-"], .stApp {
                font-size: 13.5px; /* Ajusta este valor según necesites */
            }
            /* Encabezados más pequeños */
            h1 { font-size: 26px; }
            h2 { font-size: 22px; }
            h3 { font-size: 18px; }
            h4 { font-size: 16px; }
            h5 { font-size: 14px; }
            h6 { font-size: 13px; }

            /* Texto de los st.metric */
            .stMetric > div:nth-child(1) > div:nth-child(1) { font-size: 1.1rem; } /* Label */
            .stMetric > div:nth-child(1) > div:nth-child(2) { font-size: 1.3rem; } /* Value */
            
            /* Leyendas (caption) un poco más pequeñas si es necesario */
            .stCaption {
                font-size: 0.8rem; /* 12px si el base es 15px */
            }
            
            /* Espaciado y márgenes en contenedores/columnas */
            .stVerticalBlock, .stHorizontalBlock {
                 gap: 0.5rem !important; /* Reduce el espacio entre elementos en columnas/contenedores */
            }
            
            /* Mejorar el espaciado dentro de los expanders */
            .streamlit-expanderHeader {
                font-size: 1.1rem; /* Un poco más grande para el título del expander */
                padding: 0.5rem 0.75rem !important;
            }
            .streamlit-expanderContent {
                padding: 0.5rem 0.75rem !important;
            }
            
            /* Estilos para el dashboard */
            .dashboard-metric-container {
                padding: 8px;
                border-radius: 5px;
                background-color: #f9f9f9; /* Un fondo suave para cada métrica */
                text-align: center;
                margin-bottom: 5px; /* Espacio debajo de cada métrica */
            }
            .dashboard-metric-label {
                font-size: 0.8em;
                font-weight: bold;
                color: #555;
                margin-bottom: 3px;
            }
            .dashboard-metric-value {
                font-size: 1.1em;
                font-weight: bold;
                color: #333;
            }
            .dashboard-metric-help {
                font-size: 0.7em;
                color: #777;
                margin-top: 2px;
            }
            .team-name-display { /* Para nombres de equipo en el dashboard */
                font-weight: bold;
                font-size: 1.05em;
                color: #007bff; /* Azul para nombres de equipo */
                display: block; /* Para asegurar que toma el ancho y centra el texto */
                margin-bottom: 5px;
            }
            
        </style>
    """, unsafe_allow_html=True)

# --- FUNCIONES HELPER PARA PARSEO Y FORMATEO (ADAPTADAS) ---
def parse_ah_to_number_of(ah_line_str: str):
    if not isinstance(ah_line_str, str): return None
    s = ah_line_str.strip().replace(' ', '')
    if not s or s in ['-', '?','N/A', 'PK']: return None #PK sometimes means 0 for AH
    
    original_value_was_zero_text = s.lower() == "0" # Catch "0" before it becomes 0.0

    try:
        if '/' in s:
            parts = s.split('/')
            if len(parts) != 2: return None
            p1_str, p2_str = parts[0], parts[1]
            
            # Manejo especial para "0/-0.5" y similares
            val1 = float(p1__str) if p1_str != "-0" else 0.0 
            val2 = float(p2_str) if p2_str != "-0" else 0.0

            # Si uno es 0 y el otro negativo, el promedio debe ser negativo
            # Ej: 0/-0.5 -> -0.25.  -0/0.5 -> 0.25 (menos común, pero debe dar promedio)
            if (val1 == 0 and val2 < 0):
                return (val1 + val2) / 2.0 
            if (val2 == 0 and val1 < 0): # ej. -0.5/0
                return (val1 + val2) / 2.0
            # Ej: -0/-0.5 => -0.25. Correcto.
            # Ej: 0.5/1 => 0.75. Correcto.
            # Ej: -0.5/-1 => -0.75. Correcto.
            return (val1 + val2) / 2.0
        else:
            if s.lower() == 'pk': return 0.0 # Tratar 'PK' como 0
            return float(s)
    except ValueError:
        return None

def format_ah_as_decimal_string_of(ah_line_str: str, for_sheets=False):
    if not isinstance(ah_line_str, str) or not ah_line_str.strip() or ah_line_str.strip().lower() in ['-', '?', 'n/a', 'pk']:
        if isinstance(ah_line_str, str) and ah_line_str.strip().lower() == 'pk': return "0" # Tratar PK como 0
        return ah_line_str.strip() if isinstance(ah_line_str, str) and ah_line_str.strip() in ['-','?', 'N/A'] else '-'
    
    numeric_value = parse_ah_to_number_of(ah_line_str)
    if numeric_value is None:
        return ah_line_str.strip() if ah_line_str.strip() in ['-','?', 'N/A'] else '-'

    if numeric_value == 0.0:
        return "0"
    
    sign = -1 if numeric_value < 0 else 1
    abs_num = abs(numeric_value)
    
    # El hándicap asiático se mueve en cuartos (0, 0.25, 0.5, 0.75, 1)
    # Redondeamos al cuarto más cercano.
    # Multiplicamos por 4, redondeamos al entero más cercano, y dividimos por 4.
    abs_rounded = round(abs_num * 4) / 4.0
    
    final_value_signed = sign * abs_rounded

    if final_value_signed == 0.0:
        output_str = "0"
    elif abs_rounded % 1 == 0: # Es un entero X.0
        output_str = str(int(final_value_signed))
    elif abs_rounded % 0.5 == 0: # Es X.5
        output_str = f"{final_value_signed:.1f}"
    else: # Es X.25 o X.75
        output_str = f"{final_value_signed:.2f}"

    if for_sheets:
        return "'" + output_str.replace('.', ',') if output_str not in ['-','?', 'N/A'] else output_str
    return output_str


def get_match_details_from_row_of(row_element, score_class_selector='score', source_table_type='h2h'):
    try:
        cells = row_element.find_all('td')
        if len(cells) < 12: return None
        
        league_name_raw = cells[0].text.strip() if cells[0] else "N/A"
        date_span = cells[1].find("span", {"name": "timeData"})
        date_raw = date_span.text.strip() if date_span else "N/A"

        league_id_hist_attr = row_element.get('name')
        home_idx, score_idx, away_idx, ah_idx = 2, 3, 4, 11 # Suponiendo AH está en la 12ava celda (índice 11)
        
        home_tag = cells[home_idx].find('a'); home = home_tag.text.strip() if home_tag else cells[home_idx].text.strip()
        away_tag = cells[away_idx].find('a'); away = away_tag.text.strip() if away_tag else cells[away_idx].text.strip()
        
        score_cell_content = cells[score_idx].text.strip()
        score_span = cells[score_idx].find('span', class_=lambda x: x and score_class_selector in x)
        score_raw_text = score_span.text.strip() if score_span else score_cell_content
        
        score_m = re.match(r'(\d+-\d+)', score_raw_text); score_raw_final = score_m.group(1) if score_m else '?-?'
        score_fmt_final = score_raw_final.replace('-', ':') if score_raw_final != '?-?' else '?*:*'
        
        # Hándicap: Intentar desde data-o, luego texto de celda. Para AH principal de H2H (Col3) e Historial.
        ah_line_raw_text_data_o = cells[ah_idx].get("data-o") # Usado para AH "en vivo" en tablas de historial y col3
        ah_line_raw_text_cell = cells[ah_idx].text.strip()
        
        # Priorizar data-o si existe y no es solo '-', de lo contrario usar el texto de la celda.
        ah_line_raw_final = ah_line_raw_text_data_o if ah_line_raw_text_data_o and ah_line_raw_text_data_o.strip() not in ['','-'] else ah_line_raw_text_cell
        if not ah_line_raw_final or ah_line_raw_final.strip() in ['','-']: ah_line_raw_final = "N/A"

        ah_line_fmt_final = format_ah_as_decimal_string_of(ah_line_raw_final) 
        
        if not home or not away: return None
        return {
            'home': home, 'away': away, 'score': score_fmt_final, 'score_raw': score_raw_final,
            'ahLine': ah_line_fmt_final, 'ahLine_raw': ah_line_raw_final, # ahLine ya está formateado
            'matchIndex': row_element.get('index'), 'vs': row_element.get('vs'),
            'league_id_hist': league_id_hist_attr, 'league_name_hist': league_name_raw,
            'date_hist': date_raw
        }
    except Exception as e:
        # st.warning(f"Error en get_match_details_from_row_of: {e} en fila: {row_element.prettify()[:200]}") # Para depuración
        return None

# --- FUNCIONES DE REQUESTS, SELENIUM, Y EXTRACCIÓN (Adaptadas o sin cambios significativos) ---
@st.cache_resource
def get_requests_session_of():
    session = requests.Session()
    retries_req = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    adapter_req = HTTPAdapter(max_retries=retries_req)
    session.mount("https://", adapter_req); session.mount("http://", adapter_req)
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36"})
    return session

@st.cache_data(ttl=3600, show_spinner=False)
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

@st.cache_data(ttl=3600, show_spinner=False) 
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

@st.cache_data(ttl=3600, show_spinner=False)
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
    # ... (Sin cambios significativos en la lógica, pero el AH devuelto es RAW) ...
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
                cell = tds[HANDICAP_TD_IDX]; 
                # Intenta 'data-o' primero, luego el texto de la celda.
                d_o = cell.get("data-o") 
                handicap_raw = d_o.strip() if d_o and d_o.strip() not in ["", "-"] else (cell.text.strip() if cell.text.strip() not in ["", "-"] else "N/A")
            
            rol_a_in_this_h2h = "H" if h2h_row_home_id == str(rival_a_id) else "A"
            return {"status": "found", "goles_home": g_h.strip(), "goles_away": g_a.strip(), 
                    "handicap_raw": handicap_raw, "rol_rival_a": rol_a_in_this_h2h, 
                    "h2h_home_team_name": links[0].text.strip(), "h2h_away_team_name": links[1].text.strip()}
    return {"status": "not_found", "resultado": f"H2H directo no encontrado para {rival_a_name} vs {rival_b_name}."}

def get_team_league_info_from_script_of(soup):
    home_id, away_id, league_id, home_name, away_name, league_name = (None,)*3 + ("N/A",)*3
    script_tag = soup.find("script", string=re.compile(r"var _matchInfo ="))
    if script_tag and script_tag.string:
        script_content = script_tag.string
        h_id_m = re.search(r"hId:\s*parseInt\('(\d+)'\)", script_content); g_id_m = re.search(r"gId:\s*parseInt\('(\d+)'\)", script_content)
        sclass_id_m = re.search(r"sclassId:\s*parseInt\('(\d+)'\)", script_content); h_name_m = re.search(r"hName:\s*'([^']*)'", script_content)
        g_name_m = re.search(r"gName:\s*'([^']*)'", script_content); l_name_m = re.search(r"lNameES:\s*'([^']*)'", script_content) # lNameES o lName
        if not l_name_m: l_name_m = re.search(r"lName:\s*'([^']*)'", script_content)


        if h_id_m: home_id = h_id_m.group(1)
        if g_id_m: away_id = g_id_m.group(1)
        if sclass_id_m: league_id = sclass_id_m.group(1)
        if h_name_m: home_name = h_name_m.group(1).replace("\\'", "'")
        if g_name_m: away_name = g_name_m.group(1).replace("\\'", "'")
        if l_name_m: league_name = l_name_m.group(1).replace("\\'", "'")
    return home_id, away_id, league_id, home_name, away_name, league_name

def click_element_robust_of(driver, by, value, timeout=7):
    # ... (sin cambios) ...
    try:
        element = WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.presence_of_element_located((by, value)))
        WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.visibility_of(element))
        driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'center'});", element); time.sleep(0.3)
        try: WebDriverWait(driver, 2, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.element_to_be_clickable((by, value))).click()
        except (ElementClickInterceptedException, TimeoutException): driver.execute_script("arguments[0].click();", element)
        return True
    except Exception: return False

def extract_last_match_in_league_of(driver, table_css_id_str, main_team_name_in_table, league_id_filter_value, home_or_away_filter_css_selector, is_home_game_filter):
    # ... (Devuelve handicap_raw) ...
    try:
        if league_id_filter_value:
            # La clase "on" en el label indica si ya está seleccionado. Solo click si NO está "on"
            # Para el filtro de liga, se hace toggle, así que solo click si el estado no es el deseado (pero es más simple clickear siempre)
            league_checkbox_label_selector = f"label[for='checkboxleague{table_css_id_str[-1]}']"
            
            # Click robusto en el label asociado al checkbox
            league_checkbox_to_click = None
            try:
                league_checkbox_to_click = WebDriverWait(driver, 3, poll_frequency=0.1).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, league_checkbox_label_selector))
                )
                if league_checkbox_to_click:
                     # Comprobamos si ya está checkeado el filtro de liga. Solo clickeamos si no lo está.
                     # (O podemos clickear siempre para hacer toggle y si está seleccionado, deseleccionarlo, y volver a seleccionarlo)
                     # Simplificamos a clickear siempre
                    click_element_robust_of(driver, By.CSS_SELECTOR, league_checkbox_label_selector); time.sleep(1.0)
            except: pass # No crítico si no se encuentra para click inicial
        
        # Para Home/Away, igual: click si no está activo, o clickear siempre para toggle.
        home_away_checkbox_label_selector = home_or_away_filter_css_selector.replace("input#","label[for='").replace("']","']") # Asume que el label tiene for=ID_checkbox

        click_element_robust_of(driver, By.CSS_SELECTOR, home_away_checkbox_label_selector); time.sleep(1.0)

        # Después de aplicar filtros, re-leer la fuente
        page_source_updated = driver.page_source; soup_updated = BeautifulSoup(page_source_updated, "html.parser")
        table = soup_updated.find("table", id=table_css_id_str)
        if not table: return None
        
        count_visible_rows = 0
        for row in table.find_all("tr", id=re.compile(rf"tr{table_css_id_str[-1]}_\d+")):
            if row.get("style") and "display:none" in row.get("style","").lower(): continue # Saltar filas ocultas por JS
            count_visible_rows +=1
            if count_visible_rows > 10: break # Limitar el número de filas visibles a procesar
            
            if league_id_filter_value and row.get("name") != str(league_id_filter_value): continue # Filtro de liga por el atributo 'name' en la TR
            
            tds = row.find_all("td"); 
            if len(tds) < 12: continue # Asegurar suficientes celdas
            
            home_team_row_el = tds[2].find("a"); away_team_row_el = tds[4].find("a")
            if not home_team_row_el or not away_team_row_el: continue
            
            home_team_row_name = home_team_row_el.text.strip(); away_team_row_name = away_team_row_el.text.strip()
            
            team_is_home_in_row = main_team_name_in_table.lower() == home_team_row_name.lower()
            team_is_away_in_row = main_team_name_in_table.lower() == away_team_row_name.lower()

            # Validar que el equipo principal esté jugando como se espera (local en casa, visitante fuera)
            if (is_home_game_filter and team_is_home_in_row) or \
               (not is_home_game_filter and team_is_away_in_row):
                
                date_span = tds[1].find("span", {"name": "timeData"}); date_raw = date_span.text.strip() if date_span else "N/A"
                
                score_class_re = re.compile(r"fscore_"); score_span = tds[3].find("span", class_=score_class_re)
                score_raw = score_span.text.strip().split("(")[0].strip() if score_span else "N/A"

                # Extracción de hándicap de la celda 12 (índice 11)
                handicap_cell_idx = 11 
                handicap_raw_from_cell = "N/A"
                if len(tds) > handicap_cell_idx:
                    h_cell = tds[handicap_cell_idx]
                    # Intentar obtener de 'data-o' primero, luego el texto
                    handicap_raw_from_cell_data_o = h_cell.get("data-o")
                    handicap_raw_from_cell_text = h_cell.text.strip()
                    handicap_raw_from_cell = handicap_raw_from_cell_data_o if handicap_raw_from_cell_data_o and handicap_raw_from_cell_data_o.strip() not in ['','-'] else handicap_raw_from_cell_text
                    if not handicap_raw_from_cell or handicap_raw_from_cell.strip() in ['','-']: handicap_raw_from_cell = "N/A"

                return {
                    "date": date_raw, 
                    "home_team": home_team_row_name, 
                    "away_team": away_team_row_name,
                    "score": score_raw, # Resultado RAW como "2-1"
                    "handicap_line_raw": handicap_raw_from_cell # Devuelve RAW
                }
        return None # No se encontró partido que cumpla los criterios
    except Exception as e_sel:
        # st.warning(f"Excepción en extract_last_match: {e_sel}")
        return None

def get_main_match_odds_selenium_of(driver):
    # ... (Devuelve *_raw para líneas de AH y Goles) ...
    odds_info = {"ah_home_cuota": "N/A", "ah_linea_raw": "N/A", "ah_away_cuota": "N/A", "goals_over_cuota": "N/A", "goals_linea_raw": "N/A", "goals_under_cuota": "N/A"}
    try:
        # Esperar que la sección de comparación de odds esté presente
        live_compare_div = WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS_OF, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.presence_of_element_located((By.ID, "liveCompareDiv")))
        
        # Selectores para Bet365 y Sbobet como fallback (o la que prefieras)
        primary_odds_selector = "tr#tr_o_1_8[name='earlyOdds']" # Bet365
        fallback_odds_selector = "tr#tr_o_1_31[name='earlyOdds']" # Sbobet

        # Scroll a la tabla de odds para asegurar visibilidad
        table_odds_element = live_compare_div.find_element(By.XPATH, ".//table[contains(@class, 'team-table-other')]")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", table_odds_element); time.sleep(0.5)

        selected_odds_row_element = None
        try:
            # Intenta con el selector primario
            selected_odds_row_element = WebDriverWait(driver, 5, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, primary_odds_selector))
            )
        except TimeoutException:
            try:
                # Si falla, intenta con el selector de fallback
                selected_odds_row_element = WebDriverWait(driver, 3, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, fallback_odds_selector))
                )
            except TimeoutException:
                 # st.warning("No se encontró la fila de odds de Bet365 ni Sbobet (early).")
                return odds_info # Retorna N/A si ninguna se encuentra

        tds_odds = selected_odds_row_element.find_elements(By.TAG_NAME, "td")
        
        if len(tds_odds) >= 11: # Asegurar que hay suficientes celdas
            # Asian Handicap Odds: Home (idx 2), AH (idx 3), Away (idx 4)
            odds_info["ah_home_cuota"] = tds_odds[2].get_attribute("data-o") or tds_odds[2].text.strip() or "N/A"
            odds_info["ah_linea_raw"] = tds_odds[3].get_attribute("data-o") or tds_odds[3].text.strip() or "N/A" # RAW
            odds_info["ah_away_cuota"] = tds_odds[4].get_attribute("data-o") or tds_odds[4].text.strip() or "N/A"
            
            # Over/Under Odds: Over (idx 8), Goals (idx 9), Under (idx 10)
            odds_info["goals_over_cuota"] = tds_odds[8].get_attribute("data-o") or tds_odds[8].text.strip() or "N/A"
            odds_info["goals_linea_raw"] = tds_odds[9].get_attribute("data-o") or tds_odds[9].text.strip() or "N/A" # RAW
            odds_info["goals_under_cuota"] = tds_odds[10].get_attribute("data-o") or tds_odds[10].text.strip() or "N/A"
            
    except Exception as e_odds:
        # st.warning(f"Error extrayendo odds: {e_odds}")
        pass # Retorna los N/A por defecto
    return odds_info

def extract_standings_data_from_h2h_page_of(h2h_soup, target_team_name_exact):
    # ... (sin cambios) ...
    data = {"name": target_team_name_exact, "ranking": "N/A", "total_pj": "N/A", "total_v": "N/A", "total_e": "N/A", "total_d": "N/A", "total_gf": "N/A", "total_gc": "N/A", "specific_pj": "N/A", "specific_v": "N/A", "specific_e": "N/A", "specific_d": "N/A", "specific_gf": "N/A", "specific_gc": "N/A", "specific_type": "N/A" }
    if not h2h_soup: return data
    standings_section = h2h_soup.find("div", id="porletP4"); 
    if not standings_section: return data
    team_table_soup = None; is_home_team_table_type = False
    home_div_standings = standings_section.find("div", class_="home-div")
    if home_div_standings:
        home_table_header_text_element = home_div_standings.find("tr", class_="team-home")
        if home_table_header_text_element and target_team_name_exact and target_team_name_exact.lower() in home_table_header_text_element.get_text(strip=True).lower():
            team_table_soup = home_div_standings.find("table", class_="team-table-home"); is_home_team_table_type = True
            span_home_text_element = home_div_standings.find("span", class_="team-home-f") # Para tipo específico 'Home'
            data["specific_type"] = span_home_text_element.text.strip() if span_home_text_element else "En Casa"
            
    if not team_table_soup:
        guest_div_standings = standings_section.find("div", class_="guest-div")
        if guest_div_standings:
            guest_table_header_text_element = guest_div_standings.find("tr", class_="team-guest")
            if guest_table_header_text_element and target_team_name_exact and target_team_name_exact.lower() in guest_table_header_text_element.get_text(strip=True).lower():
                team_table_soup = guest_div_standings.find("table", class_="team-table-guest"); is_home_team_table_type = False
                span_away_text_element = guest_div_standings.find("span", class_="team-away-f") # Para tipo específico 'Away'
                data["specific_type"] = span_away_text_element.text.strip() if span_away_text_element else "Fuera"
                
    if not team_table_soup: return data

    header_row_found = team_table_soup.find("tr", class_=re.compile(r"team-(home|guest)")) 
    if header_row_found:
        link = header_row_found.find("a")
        full_header_text = link.get_text(separator=" ", strip=True) if link else header_row_found.get_text(separator=" ", strip=True)
        
        # Ajustar regex para nombres de equipo que pueden tener corchetes o guiones dentro del nombre
        # Ej: [ITA D1-3] Equipo Nombre [Extra]
        name_match = re.search(r"]\s*(.*?)(?:\s*\[|\s*$)", full_header_text) # Toma todo después del corchete de ranking
        rank_match = re.search(r"\[(?:[^\]]+-)?(\d+)\]", full_header_text)

        if name_match: data["name"] = name_match.group(1).strip()
        if rank_match: data["ranking"] = rank_match.group(1)
        # Si 'name' no se pudo extraer del header, usar target_team_name_exact
        if data["name"] == "N/A" or not data["name"]: data["name"] = target_team_name_exact


    ft_rows = []; current_section_is_ft = False # Bandera para identificar si estamos en la sección FT
    for row in team_table_soup.find_all("tr", align="center"): 
        th_cell = row.find("th");
        if th_cell: # Es una fila de encabezado de sección (FT, HT)
            section_text = th_cell.get_text(strip=True)
            if "FT" in section_text: current_section_is_ft = True
            elif "HT" in section_text: current_section_is_ft = False # Salimos de la sección FT
            continue # No procesar la fila de encabezado como datos

        if current_section_is_ft: # Solo procesar si estamos dentro de la sección FT
            cells_data = row.find_all("td")
            if cells_data and len(cells_data) > 0 : 
                first_cell_text = cells_data[0].get_text(strip=True)
                if first_cell_text in ["Total", "Home", "Away", "Last 6"] or \
                   (cells_data[0].find("span", class_="team-home-f") and first_cell_text == "Home") or \
                   (cells_data[0].find("span", class_="team-away-f") and first_cell_text == "Away"):
                    ft_rows.append(cells_data)

    for cells_detail in ft_rows:
        if len(cells_detail) > 8: # Columnas: Tipo, PJ, V, E, D, GF, GC, Pts, Rank, Rate
            row_type_text_raw = cells_detail[0].get_text(strip=True) # "Total", "Home", "Away", "Last 6"
            
            pj, v, e, d, gf, gc = (cells_detail[i].get_text(strip=True) for i in range(1, 7)) # Columnas de PJ a GC
            pj=pj if pj else "N/A"; v=v if v else "N/A"; e=e if e else "N/A"; d=d if d else "N/A"; gf=gf if gf else "N/A"; gc=gc if gc else "N/A"
            
            if row_type_text_raw=="Total": data["total_pj"],data["total_v"],data["total_e"],data["total_d"],data["total_gf"],data["total_gc"]=pj,v,e,d,gf,gc
            # Para specific, solo tomar 'Home' si es la tabla del equipo local, y 'Away' si es la tabla del visitante.
            elif row_type_text_raw=="Home" and is_home_team_table_type: 
                data["specific_pj"],data["specific_v"],data["specific_e"],data["specific_d"],data["specific_gf"],data["specific_gc"]=pj,v,e,d,gf,gc
                data["specific_type"] = "En Casa"
            elif row_type_text_raw=="Away" and not is_home_team_table_type: 
                data["specific_pj"],data["specific_v"],data["specific_e"],data["specific_d"],data["specific_gf"],data["specific_gc"]=pj,v,e,d,gf,gc
                data["specific_type"] = "Fuera"
    return data

def extract_final_score_of(soup):
    # ... (sin cambios) ...
    try:
        score_divs = soup.select('#mScore .end .score') 
        if len(score_divs) == 2:
            hs = score_divs[0].text.strip(); aws = score_divs[1].text.strip()
            if hs.isdigit() and aws.isdigit(): return f"{hs}:{aws}", f"{hs}-{aws}" # Cambiado a dos puntos para display
    except Exception: pass
    return '?:?', "?-?" # Cambiado a dos puntos para display

def extract_h2h_data_of(soup, main_home_team_name, main_away_team_name, current_league_id):
    # ... (AH ya viene formateado de get_match_details_from_row_of) ...
    ah1, res1, res1_raw = '-', '?:?', '?-?'; ah6, res6, res6_raw = '-', '?:?', '?-?' # Usar ":"
    h2h_table = soup.find("table", id="table_v3")
    if not h2h_table: return ah1, res1, res1_raw, ah6, res6, res6_raw
    filtered_h2h_list = []
    if not main_home_team_name or not main_away_team_name:
        return ah1, res1, res1_raw, ah6, res6, res6_raw

    for row_h2h in h2h_table.find_all("tr", id=re.compile(r"tr3_\d+")):
        # Asegurarse que la fila es visible
        if row_h2h.get("style") and "display:none" in row_h2h.get("style","").lower():
            continue

        details = get_match_details_from_row_of(row_h2h, score_class_selector='fscore_3', source_table_type='h2h')
        if not details: continue
        if current_league_id and details.get('league_id_hist') and details.get('league_id_hist') != str(current_league_id): continue
        filtered_h2h_list.append(details)
        
    if not filtered_h2h_list: return ah1, res1, res1_raw, ah6, res6, res6_raw
    
    # Para AH6 y Res6 (más reciente H2H general en misma liga o general si no hay en misma liga)
    h2h_general_match = filtered_h2h_list[0] # El primero de la lista filtrada (más reciente)
    ah6 = h2h_general_match.get('ahLine', '-') # Ya está formateado
    res6 = h2h_general_match.get('score', '?:?'); res6_raw = h2h_general_match.get('score_raw', '?-?')
    
    # Para AH1 y Res1 (más reciente H2H con main_home_team_name como local)
    h2h_local_specific_match = None
    for d_h2h in filtered_h2h_list:
        if d_h2h.get('home','').lower() == main_home_team_name.lower() and \
           d_h2h.get('away','').lower() == main_away_team_name.lower():
            h2h_local_specific_match = d_h2h; break
            
    if h2h_local_specific_match:
        ah1 = h2h_local_specific_match.get('ahLine', '-') # Ya está formateado
        res1 = h2h_local_specific_match.get('score', '?:?'); res1_raw = h2h_local_specific_match.get('score_raw', '?-?')
    return ah1, res1, res1_raw, ah6, res6, res6_raw


def extract_comparative_match_of(soup_for_team_history, table_id_of_team_to_search, team_name_to_find_match_for, opponent_name_to_search, current_league_id, is_home_table):
    # ... (AH ya viene formateado de get_match_details_from_row_of) ...
    if not opponent_name_to_search or opponent_name_to_search == "N/A" or not team_name_to_find_match_for:
        return "N/A" # O '-'
    table = soup_for_team_history.find("table", id=table_id_of_team_to_search)
    if not table: return "N/A"
    score_class_selector = 'fscore_1' if is_home_table else 'fscore_2'
    for row in table.find_all("tr", id=re.compile(rf"tr{table_id_of_team_to_search[-1]}_\d+")):
        if row.get("style") and "display:none" in row.get("style","").lower(): continue

        details = get_match_details_from_row_of(row, score_class_selector=score_class_selector, source_table_type='hist')
        if not details: continue
        if current_league_id and details.get('league_id_hist') and details.get('league_id_hist') != str(current_league_id): continue
        
        home_hist = details.get('home','').lower(); away_hist = details.get('away','').lower()
        team_main_lower = team_name_to_find_match_for.lower(); opponent_lower = opponent_name_to_search.lower()
        
        if (team_main_lower == home_hist and opponent_lower == away_hist) or \
           (team_main_lower == away_hist and opponent_lower == home_hist):
            score = details.get('score', '?:?') # Formato "X:Y"
            ah_line_extracted = details.get('ahLine', '-') # Ya formateado
            
            localia_team_main = 'H' if team_main_lower == home_hist else 'A'
            return f"{score} / {ah_line_extracted} ({localia_team_main})" # Devolver con AH formateado
    return "N/A" # O '-'


# --- STREAMLIT APP UI (Función principal REESTRUCTURADA) ---
def display_other_feature_ui():
    apply_custom_css_of() # Aplicar CSS personalizado
    st.sidebar.title("⚙️ Configuración Partido (OF)")
    main_match_id_str_input_of = st.sidebar.text_input("🆔 ID Partido Principal:", value="2607237", help="Pega el ID del partido a analizar.", key="other_feature_match_id_input")
    analizar_button_of = st.sidebar.button("🚀 Analizar Partido (OF)", type="primary", use_container_width=True, key="other_feature_analizar_button")

    results_container = st.container()

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
                results_container.error("⚠️ ID de partido no válido (OF)."); st.stop()
        if not main_match_id_to_process_of: 
            results_container.warning("⚠️ Ingresa un ID de partido válido (OF)."); st.stop()
        
        start_time_of = time.time()
        with results_container:
            with st.spinner("🔄 Cargando datos iniciales..."):
                main_page_url_h2h_view_of = f"/match/h2h-{main_match_id_to_process_of}"
                soup_main_h2h_page_of = fetch_soup_requests_of(main_page_url_h2h_view_of)
            if not soup_main_h2h_page_of:
                st.error("❌ No se pudo obtener la página H2H principal."); st.stop()

            mp_home_id_of, mp_away_id_of, mp_league_id_of, mp_home_name_from_script, mp_away_name_from_script, mp_league_name_of = get_team_league_info_from_script_of(soup_main_h2h_page_of)
            
            home_team_main_standings_data = {}; away_team_main_standings_data = {}
            with st.spinner("📊 Extrayendo clasificaciones principales..."):
                home_team_main_standings_data = extract_standings_data_from_h2h_page_of(soup_main_h2h_page_of, mp_home_name_from_script)
                away_team_main_standings_data = extract_standings_data_from_h2h_page_of(soup_main_h2h_page_of, mp_away_name_from_script)
            
            display_home_name = home_team_main_standings_data.get("name", mp_home_name_from_script)
            display_away_name = away_team_main_standings_data.get("name", mp_away_name_from_script)
            if not display_home_name or display_home_name == "N/A": display_home_name = mp_home_name_from_script
            if not display_away_name or display_away_name == "N/A": display_away_name = mp_away_name_from_script


            st.markdown(f"<h2 style='text-align: center;'>🆚 {display_home_name or 'Local'} vs {display_away_name or 'Visitante'} 🆚</h2>", unsafe_allow_html=True)
            st.markdown(f"<p style='text-align: center; font-size:0.9em;'>🏆 {mp_league_name_of or 'N/A'} (ID: {mp_league_id_of or 'N/A'}) | 🗓️ Partido ID: {main_match_id_to_process_of}</p>", unsafe_allow_html=True)
            st.markdown("---")

            # --- INICIALIZACIÓN DE DATOS PARA EL DASHBOARD ---
            dashboard_data = {
                "AH Partido": {"val": "N/A", "help": "Hándicap Asiático del partido actual."},
                "Resultado Final": {"val": "N/A", "help": "Resultado final del partido actual (si disponible)."},
                "Línea Goles": {"val": "N/A", "help": "Línea de goles Over/Under del partido actual."},
                
                "H2H (Local) AH": {"val": "N/A", "help": f"Último H2H donde {display_home_name or 'Local'} jugó en casa vs {display_away_name or 'Visitante'}."},
                "H2H (Local) Res": {"val": "N/A"},
                "H2H (Gral) AH": {"val": "N/A", "help": f"Último H2H general entre {display_home_name or 'Local'} y {display_away_name or 'Visitante'}."},
                "H2H (Gral) Res": {"val": "N/A"},

                "Últ. Local (Casa) AH": {"val": "N/A", "help": f"Último partido de liga de {display_home_name or 'Local'} en casa."},
                "Últ. Local (Casa) Res": {"val": "N/A"},
                "Últ. Visitante (Fuera) AH": {"val": "N/A", "help": f"Último partido de liga de {display_away_name or 'Visitante'} como visitante."},
                "Últ. Visitante (Fuera) Res": {"val": "N/A"},

                "L vs ÚltRival V": {"val": "N/A", "help": f"{display_home_name or 'Local'} vs. último rival que {display_away_name or 'Visitante'} enfrentó como visitante en liga."},
                "V vs ÚltRival L": {"val": "N/A", "help": f"{display_away_name or 'Visitante'} vs. último rival que {display_home_name or 'Local'} enfrentó en casa en liga."}
            }

            # Selenium para Odds y Últimos Partidos
            main_match_odds_data_of = {}; last_home_match_in_league_of = None; last_away_match_in_league_of = None
            driver_actual_of = st.session_state.driver_other_feature; driver_of_needs_init = False
            if driver_actual_of is None: driver_of_needs_init = True
            else:
                try:
                    _ = driver_actual_of.window_handles
                    if hasattr(driver_actual_of, 'service') and driver_actual_of.service and not driver_actual_of.service.is_connectable(): driver_of_needs_init = True
                except WebDriverException: driver_of_needs_init = True
            
            if driver_of_needs_init:
                if driver_actual_of is not None:
                    try: driver_actual_of.quit()
                    except: pass
                with st.spinner("🚘 Inicializando WebDriver... (puede tardar)"): driver_actual_of = get_selenium_driver_of()
                st.session_state.driver_other_feature = driver_actual_of

            if driver_actual_of:
                try:
                    with st.spinner("⚙️ Accediendo a datos dinámicos con Selenium..."):
                        driver_actual_of.get(f"{BASE_URL_OF}{main_page_url_h2h_view_of}") 
                        WebDriverWait(driver_actual_of, SELENIUM_TIMEOUT_SECONDS_OF).until(EC.presence_of_element_located((By.ID, "table_v1"))) 
                        time.sleep(0.8) # Pausa adicional
                        main_match_odds_data_of = get_main_match_odds_selenium_of(driver_actual_of)
                        if mp_home_id_of and mp_league_id_of and display_home_name and display_home_name != "N/A":
                             last_home_match_in_league_of = extract_last_match_in_league_of(driver_actual_of, "table_v1", display_home_name, mp_league_id_of, "input#cb_sos1", is_home_game_filter=True) # Se usa ID del input
                        if mp_away_id_of and mp_league_id_of and display_away_name and display_away_name != "N/A":
                            last_away_match_in_league_of = extract_last_match_in_league_of(driver_actual_of, "table_v2", display_away_name, mp_league_id_of, "input#cb_sos2", is_home_game_filter=False) # Se usa ID del input
                except Exception as e_main_sel_of: st.error(f"❗ Error Selenium: {type(e_main_sel_of).__name__} - {e_main_sel_of}")
            else: st.warning("❗ WebDriver no disponible. Algunos datos (Odds, Últimos Partidos) pueden no cargarse.")


            # Poblar dashboard_data
            raw_ah_act = main_match_odds_data_of.get('ah_linea_raw', '?'); dashboard_data["AH Partido"]["val"] = format_ah_as_decimal_string_of(raw_ah_act)
            raw_g_i = main_match_odds_data_of.get('goals_linea_raw', '?'); dashboard_data["Línea Goles"]["val"] = format_ah_as_decimal_string_of(raw_g_i)
            dashboard_data["Resultado Final"]["val"], _ = extract_final_score_of(soup_main_h2h_page_of)

            ah1_val, res1_val, _, ah6_val, res6_val, _ = extract_h2h_data_of(soup_main_h2h_page_of, display_home_name, display_away_name, mp_league_id_of)
            dashboard_data["H2H (Local) AH"]["val"] = ah1_val; dashboard_data["H2H (Local) Res"]["val"] = res1_val
            dashboard_data["H2H (Gral) AH"]["val"] = ah6_val; dashboard_data["H2H (Gral) Res"]["val"] = res6_val

            if last_home_match_in_league_of:
                dashboard_data["Últ. Local (Casa) AH"]["val"] = format_ah_as_decimal_string_of(last_home_match_in_league_of.get('handicap_line_raw', '-'))
                dashboard_data["Últ. Local (Casa) Res"]["val"] = last_home_match_in_league_of.get('score', '?:?').replace('-', ':')
            if last_away_match_in_league_of:
                dashboard_data["Últ. Visitante (Fuera) AH"]["val"] = format_ah_as_decimal_string_of(last_away_match_in_league_of.get('handicap_line_raw', '-'))
                dashboard_data["Últ. Visitante (Fuera) Res"]["val"] = last_away_match_in_league_of.get('score', '?:?').replace('-', ':')

            # Para comparativas indirectas, necesitamos el nombre del rival del último partido
            home_rival_in_last_away_match = last_away_match_in_league_of.get('home_team') if last_away_match_in_league_of else None
            if home_rival_in_last_away_match and display_home_name != "N/A":
                dashboard_data["L vs ÚltRival V"]["val"] = extract_comparative_match_of(soup_main_h2h_page_of, "table_v1", display_home_name, home_rival_in_last_away_match, mp_league_id_of, is_home_table=True)

            away_rival_in_last_home_match = last_home_match_in_league_of.get('away_team') if last_home_match_in_league_of else None
            if away_rival_in_last_home_match and display_away_name != "N/A":
                dashboard_data["V vs ÚltRival L"]["val"] = extract_comparative_match_of(soup_main_h2h_page_of, "table_v2", display_away_name, away_rival_in_last_home_match, mp_league_id_of, is_home_table=False)

            # --- DISPLAY DASHBOARD ---
            st.markdown("#### 📊 Dashboard de Comparación Rápida")
            
            # Fila 1: Odds del Partido y Resultado Final
            col_pd1, col_pd2, col_pd3 = st.columns(3)
            with col_pd1: st.metric(label="AH Partido Actual", value=dashboard_data["AH Partido"]["val"], help=dashboard_data["AH Partido"]["help"])
            with col_pd2: st.metric(label="Resultado Final", value=dashboard_data["Resultado Final"]["val"], help=dashboard_data["Resultado Final"]["help"])
            with col_pd3: st.metric(label="Línea Goles Actual", value=dashboard_data["Línea Goles"]["val"], help=dashboard_data["Línea Goles"]["help"])
            
            st.markdown("---")
            
            # Fila 2: H2H (Local) y H2H (General)
            col_pd4, col_pd5, col_pd6, col_pd7 = st.columns(4)
            with col_pd4: st.metric(label=f"H2H (L) AH", value=dashboard_data["H2H (Local) AH"]["val"], help=dashboard_data["H2H (Local) AH"]["help"])
            with col_pd5: st.metric(label=f"H2H (L) Res", value=dashboard_data["H2H (Local) Res"]["val"])
            with col_pd6: st.metric(label="H2H (Gral) AH", value=dashboard_data["H2H (Gral) AH"]["val"], help=dashboard_data["H2H (Gral) AH"]["help"])
            with col_pd7: st.metric(label="H2H (Gral) Res", value=dashboard_data["H2H (Gral) Res"]["val"])

            st.markdown("---")
            
            # Fila 3: Últimos partidos y comparativas indirectas
            st.markdown(f"""
                <div style="display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 10px; margin-bottom:15px;">
                    <div class='dashboard-metric-container'>
                        <div class='team-name-display'>{display_home_name or 'Local'} (Casa)</div>
                        <div class='dashboard-metric-label'>Últ. AH Liga</div ><div class='dashboard-metric-value'>{dashboard_data["Últ. Local (Casa) AH"]["val"]}</div>
                        <div class='dashboard-metric-label'>Últ. Res Liga</div><div class='dashboard-metric-value'>{dashboard_data["Últ. Local (Casa) Res"]["val"]}</div>
                        <div class='dashboard-metric-help'>{dashboard_data["Últ. Local (Casa) AH"]["help"]}</div>
                    </div>
                    <div class='dashboard-metric-container'>
                        <div class='team-name-display'>{display_away_name or 'Visitante'} (Fuera)</div>
                        <div class='dashboard-metric-label'>Últ. AH Liga</div><div class='dashboard-metric-value'>{dashboard_data["Últ. Visitante (Fuera) AH"]["val"]}</div>
                        <div class='dashboard-metric-label'>Últ. Res Liga</div><div class='dashboard-metric-value'>{dashboard_data["Últ. Visitante (Fuera) Res"]["val"]}</div>
                        <div class='dashboard-metric-help'>{dashboard_data["Últ. Visitante (Fuera) AH"]["help"]}</div>
                    </div>
                    <div class='dashboard-metric-container'>
                        <div class='dashboard-metric-label'>L vs ÚltRival Visit.</div>
                        <div class='dashboard-metric-value'>{dashboard_data["L vs ÚltRival V"]["val"]}</div>
                        <div class='dashboard-metric-help'>{dashboard_data["L vs ÚltRival V"]["help"]}</div>
                    </div>
                    <div class='dashboard-metric-container'>
                        <div class='dashboard-metric-label'>V vs ÚltRival Local</div>
                        <div class='dashboard-metric-value'>{dashboard_data["V vs ÚltRival L"]["val"]}</div>
                        <div class='dashboard-metric-help'>{dashboard_data["V vs ÚltRival L"]["help"]}</div>
                    </div>
                </div>
            """, unsafe_allow_html=True)
            
            # --- FIN DISPLAY DASHBOARD ---
            
            st.markdown("---")
            st.subheader("ℹ️ Información Detallada Adicional")

            # Datos H2H con Col3 y Oponentes Col3
            key_match_id_for_rival_a_h2h, rival_a_id_orig_col3, rival_a_name_orig_col3 = get_rival_a_for_original_h2h_of(main_match_id_to_process_of)
            match_id_rival_b_game_ref, rival_b_id_orig_col3, rival_b_name_orig_col3 = get_rival_b_for_original_h2h_of(main_match_id_to_process_of)
            rival_a_standings = {}; rival_b_standings = {}
            with st.spinner("📊 Extrayendo info de oponentes H2H (Col3)..."):
                if rival_a_name_orig_col3 and rival_a_name_orig_col3 != "N/A" and key_match_id_for_rival_a_h2h:
                    soup_rival_a_h2h_page = fetch_soup_requests_of(f"/match/h2h-{key_match_id_for_rival_a_h2h}")
                    if soup_rival_a_h2h_page: rival_a_standings = extract_standings_data_from_h2h_page_of(soup_rival_a_h2h_page, rival_a_name_orig_col3)
                if rival_b_name_orig_col3 and rival_b_name_orig_col3 != "N/A" and match_id_rival_b_game_ref:
                    soup_rival_b_h2h_page = fetch_soup_requests_of(f"/match/h2h-{match_id_rival_b_game_ref}")
                    if soup_rival_b_h2h_page: rival_b_standings = extract_standings_data_from_h2h_page_of(soup_rival_b_h2h_page, rival_b_name_orig_col3)
            
            with st.expander(f"⚔️ H2H de Referencia (Columna 3): {rival_a_name_orig_col3 or 'RivalA'} vs {rival_b_name_orig_col3 or 'RivalB'}"):
                details_h2h_col3_of = {"status": "error", "resultado": "N/A"}
                if key_match_id_for_rival_a_h2h and rival_a_id_orig_col3 and rival_b_id_orig_col3 and driver_actual_of: 
                    with st.spinner(f"Buscando H2H Ref: {rival_a_name_orig_col3 or 'RivalA'} vs {rival_b_name_orig_col3 or 'RivalB'}..."):
                        details_h2h_col3_of = get_h2h_details_for_original_logic_of(driver_actual_of, key_match_id_for_rival_a_h2h, rival_a_id_orig_col3, rival_b_id_orig_col3, rival_a_name_orig_col3, rival_b_name_orig_col3)
                
                if details_h2h_col3_of.get("status") == "found":
                    res_h2h = details_h2h_col3_of
                    st.markdown(f"**{res_h2h.get('h2h_home_team_name')}** {res_h2h.get('goles_home')}:{res_h2h.get('goles_away')} **{res_h2h.get('h2h_away_team_name')}**")
                    st.markdown(f"(AH: {format_ah_as_decimal_string_of(res_h2h.get('handicap_raw','-'))})") # Formatear AH raw aquí
                else: st.caption(details_h2h_col3_of.get('resultado', "H2H de referencia no encontrado."))
                
                opp_stand_col1, opp_stand_col2 = st.columns(2)
                with opp_stand_col1:
                    st.markdown(f"###### Clasificación: {rival_a_standings.get('name', rival_a_name_orig_col3 or 'RivalA')}")
                    if rival_a_standings.get("name", "N/A") != "N/A": rst = rival_a_standings; st.caption(f"Rk: {rst.get('ranking','N/A')} | T: {rst.get('total_pj')}|{rst.get('total_v')}/{rst.get('total_e')}/{rst.get('total_d')}|{rst.get('total_gf')}-{rst.get('total_gc')}\n{rst.get('specific_type')}: {rst.get('specific_pj')}|{rst.get('specific_v')}/{rst.get('specific_e')}/{rst.get('specific_d')}|{rst.get('specific_gf')}-{rst.get('specific_gc')}")
                    else: st.caption("No disponible.")
                with opp_stand_col2:
                    st.markdown(f"###### Clasificación: {rival_b_standings.get('name', rival_b_name_orig_col3 or 'RivalB')}")
                    if rival_b_standings.get("name", "N/A") != "N/A": rst = rival_b_standings; st.caption(f"Rk: {rst.get('ranking','N/A')} | T: {rst.get('total_pj')}|{rst.get('total_v')}/{rst.get('total_e')}/{rst.get('total_d')}|{rst.get('total_gf')}-{rst.get('total_gc')}\n{rst.get('specific_type')}: {rst.get('specific_pj')}|{rst.get('specific_v')}/{rst.get('specific_e')}/{rst.get('specific_d')}|{rst.get('specific_gf')}-{rst.get('specific_gc')}")
                    else: st.caption("No disponible.")

            with st.expander("📈 Cuotas Detalladas (Bet365 Iniciales)", expanded=False):
                cuotas_markdown = f"""
                | Tipo            | Local Cuota | Línea/PK | Visitante Cuota |
                |-----------------|-------------|----------|-----------------|
                | **H. Asiático** | `{main_match_odds_data_of.get('ah_home_cuota','N/A')}` | `{format_ah_as_decimal_string_of(main_match_odds_data_of.get('ah_linea_raw','?'))}` | `{main_match_odds_data_of.get('ah_away_cuota','N/A')}` |
                | **Goles O/U**   | `Ov {main_match_odds_data_of.get('goals_over_cuota','N/A')}` | `{format_ah_as_decimal_string_of(main_match_odds_data_of.get('goals_linea_raw','?'))}` | `Un {main_match_odds_data_of.get('goals_under_cuota','N/A')}` |
                """
                st.markdown(cuotas_markdown, unsafe_allow_html=True)

            with st.expander("📋 Estadísticas Completas de Clasificación", expanded=False):
                col_home_stand_detail, col_away_stand_detail = st.columns(2)
                with col_home_stand_detail:
                    st.markdown(f"##### 🏠 {display_home_name or 'Local'}")
                    if display_home_name and display_home_name != "N/A" and home_team_main_standings_data.get("name", "N/A") != "N/A":
                        hst = home_team_main_standings_data
                        st.caption(f"- **Ranking Liga:** {hst.get('ranking', 'N/A')}")
                        st.caption(f"- **General (PJ|V-E-D|GF:GC):** {hst.get('total_pj', 'N/A')} | {hst.get('total_v', 'N/A')}-{hst.get('total_e', 'N/A')}-{hst.get('total_d', 'N/A')} | {hst.get('total_gf', 'N/A')}:{hst.get('total_gc', 'N/A')}")
                        st.caption(f"- **{hst.get('specific_type','En Casa')} (PJ|V-E-D|GF:GC):** {hst.get('specific_pj', 'N/A')} | {hst.get('specific_v', 'N/A')}-{hst.get('specific_e', 'N/A')}-{hst.get('specific_d', 'N/A')} | {hst.get('specific_gf', 'N/A')}:{hst.get('specific_gc', 'N/A')}")
                    else: st.caption(f"Clasificación no disponible para {display_home_name or 'Local'}.")
                with col_away_stand_detail:
                    st.markdown(f"##### ✈️ {display_away_name or 'Visitante'}")
                    if display_away_name and display_away_name != "N/A" and away_team_main_standings_data.get("name", "N/A") != "N/A":
                        ast = away_team_main_standings_data
                        st.caption(f"- **Ranking Liga:** {ast.get('ranking', 'N/A')}")
                        st.caption(f"- **General (PJ|V-E-D|GF:GC):** {ast.get('total_pj', 'N/A')} | {ast.get('total_v', 'N/A')}-{ast.get('total_e', 'N/A')}-{ast.get('total_d', 'N/A')} | {ast.get('total_gf', 'N/A')}:{ast.get('total_gc', 'N/A')}")
                        st.caption(f"- **{ast.get('specific_type','Fuera')} (PJ|V-E-D|GF:GC):** {ast.get('specific_pj', 'N/A')} | {ast.get('specific_v', 'N/A')}-{ast.get('specific_e', 'N/A')}-{ast.get('specific_d', 'N/A')} | {ast.get('specific_gf', 'N/A')}:{ast.get('specific_gc', 'N/A')}")
                    else: st.caption(f"Clasificación no disponible para {display_away_name or 'Visitante'}.")

            end_time_of = time.time(); st.sidebar.info(f"⏱️ Análisis completado en: {end_time_of - start_time_of:.2f}s")
    else:
        results_container.info("✨ Ingresa un ID y haz clic en 'Analizar Partido (OF)' para comenzar.")

if __name__ == '__main__':
    st.set_page_config(layout="wide", page_title="Análisis Avanzado OF", initial_sidebar_state="expanded")
    if 'driver_other_feature' not in st.session_state:
        st.session_state.driver_other_feature = None
    display_other_feature_ui()
