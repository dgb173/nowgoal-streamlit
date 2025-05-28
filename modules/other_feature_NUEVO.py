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
BASE_URL = "https://live18.nowgoal25.com" # Verifica que este sea el dominio correcto
SELENIUM_TIMEOUT_SECONDS = 20
SELENIUM_POLL_FREQUENCY = 0.2

# --- FUNCIONES HELPER PARA PARSEO Y FORMATEO ---
def parse_ah_to_number(ah_line_str: str) -> float | None:
    """Convierte una cadena de Hándicap Asiático (AH) a su valor numérico."""
    if not isinstance(ah_line_str, str) or not ah_line_str.strip() or ah_line_str.strip() in ['-', '?']:
        return None
    
    s = ah_line_str.strip().replace(' ', '')
    original_starts_with_minus = ah_line_str.strip().startswith('-')

    try:
        if '/' in s: # Formatos como "0.5/1", "-0/0.5"
            parts = s.split('/')
            if len(parts) != 2: return None
            val1_str, val2_str = parts[0], parts[1]
            try:
                val1 = float(val1_str)
                val2 = float(val2_str)
            except ValueError:
                return None
            
            # Ajuste específico para casos como "-0/0.5" donde el 0 implícito es -0.5
            if original_starts_with_minus and val1 == 0.0 and val2 > 0:
                val2 = -abs(val2)
            
            return (val1 + val2) / 2.0
        else: # Formatos como "0.5", "-1"
            return float(s)
    except ValueError:
        return None

def format_ah_as_decimal_string(ah_raw_input: str) -> str:
    """
    Formatea una línea de Hándicap Asiático raw (p.ej., '0.5/1', '-1')
    a un string decimal estándar (p.ej., '0.75', '-1.0', '0', '-0.5').
    """
    numeric_value = parse_ah_to_number(ah_raw_input)
    if numeric_value is None:
        return '-' # Default for unparseable/invalid

    # Cero siempre se representa como "0"
    if numeric_value == 0.0:
        return "0"

    # Determinar si el valor es .0, .5, .25 o .75 (o un entero) y formatear en consecuencia.
    # El abs_num se usa para simplificar el cálculo de la parte decimal sin preocuparse por el signo.
    sign = -1 if numeric_value < 0 else 1
    abs_num = abs(numeric_value)
    
    # Comprobar si es un entero (ej. 1.0, 2.0, -3.0)
    if abs(abs_num - round(abs_num, 0)) < 1e-9: # Compares 1.0 to round(1.0) or 1.9 to round(1.9)
        return str(int(round(numeric_value, 0)))
    
    # Comprobar si es X.5 (ej. 0.5, 1.5, -2.5)
    if abs(abs_num - (math.floor(abs_num) + 0.5)) < 1e-9:
        return f"{numeric_value:.1f}" # Formato con un decimal, p.ej. "0.5"
    
    # Para X.25 o X.75 (ej. 0.25, 1.75, -0.75)
    # Estas son las que necesitan 2 decimales explícitamente si el número no es exacto
    if abs(abs_num - (math.floor(abs_num) + 0.25)) < 1e-9 or \
       abs(abs_num - (math.floor(abs_num) + 0.75)) < 1e-9:
        return f"{numeric_value:.2f}" # Formato con dos decimales, p.ej. "0.25", "-0.75"

    # Si llega aquí, significa que parse_ah_to_number generó algo que no es exactamente .0, .5, .25, .75
    # En este caso, simplemente devolver una representación de dos decimales por seguridad,
    # aunque para AH "reales" no debería ocurrir si los valores base son siempre .25/.5/.75/.0
    return f"{numeric_value:.2f}"

def get_match_details_from_row(row_element, score_class_selector='score'):
    """Extrae detalles de partido (equipos, resultado, AH) de una fila de tabla."""
    try:
        cells = row_element.find_all('td')
        if len(cells) < 12: return None

        # Identificación de índices más clara (menos prone a errores si la tabla cambia)
        # Ojo: Estos índices pueden variar si la estructura HTML cambia, es una suposición basada en el código original.
        league_id_hist_attr = row_element.get('name') 
        home_idx, score_idx, away_idx, ah_idx = 2, 3, 4, 11

        home_tag = cells[home_idx].find('a')
        home_team = home_tag.text.strip() if home_tag else cells[home_idx].text.strip()
        
        away_tag = cells[away_idx].find('a')
        away_team = away_tag.text.strip() if away_tag else cells[away_idx].text.strip()
        
        score_span = cells[score_idx].find('span', class_=lambda x: x and score_class_selector in x)
        score_raw_text = score_span.text.strip() if score_span else cells[score_idx].text.strip()
        
        score_match = re.match(r'(\d+-\d+)', score_raw_text)
        score_raw = score_match.group(1) if score_match else '?-?'
        score_fmt = score_raw.replace('-', '*') if score_raw != '?-?' else '?*?' # '1-0' -> '1*0'

        ah_line_raw_text = cells[ah_idx].text.strip()
        ah_line_fmt = format_ah_as_decimal_string(ah_line_raw_text)
        
        if not home_team or not away_team: return None

        return {
            'home': home_team, 'away': away_team, 'score': score_fmt, 'score_raw': score_raw,
            'ahLine': ah_line_fmt, 'ahLine_raw': ah_line_raw_text, 
            'matchIndex': row_element.get('index'), 'vs': row_element.get('vs'),
            'league_id_hist': league_id_hist_attr
        }
    except Exception: 
        return None

# --- FUNCIONES DE REQUESTS (SIN DUPLICACIONES) ---
@st.cache_resource(ttl=3600)
def get_requests_session() -> requests.Session:
    """Crea y configura una sesión de requests con reintentos."""
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36"})
    return session

@st.cache_data(ttl=3600)
def fetch_soup_requests(path: str, max_tries: int = 3, delay: int = 1) -> BeautifulSoup | None:
    """
    Realiza una petición HTTP GET y devuelve un objeto BeautifulSoup.
    Retries en caso de error.
    """
    session = get_requests_session()
    url = f"{BASE_URL}{path}"
    for attempt in range(1, max_tries + 1):
        try:
            resp = session.get(url, timeout=10)
            resp.raise_for_status() # Lanza excepción para códigos de estado HTTP 4xx/5xx
            return BeautifulSoup(resp.text, "html.parser")
        except requests.RequestException:
            if attempt == max_tries:
                st.error(f"❌ Falló la petición a {url} después de {max_tries} intentos.")
                return None
            time.sleep(delay * attempt)
    return None

def get_rival_info_from_h2h_table(soup: BeautifulSoup, table_id: str, row_id_regex: str, link_index: int) -> tuple[str | None, str | None, str | None]:
    """
    Extrae ID y nombre del rival de las tablas de H2H (v1 o v2) en la página principal H2H.
    Esta función unifica la lógica de 'get_rival_a_...' y 'get_rival_b_...'.
    """
    table = soup.find("table", id=table_id)
    if not table: return None, None, None

    for row in table.find_all("tr", id=re.compile(row_id_regex)):
        if row.get("vs") == "1":
            key_match_id = row.get("index")
            if not key_match_id: continue

            onclicks = row.find_all("a", onclick=True)
            if len(onclicks) > link_index and onclicks[link_index].get("onclick"):
                rival_tag = onclicks[link_index]
                rival_id_match = re.search(r"team\((\d+)\)", rival_tag.get("onclick", ""))
                rival_name = rival_tag.text.strip()
                if rival_id_match and rival_name:
                    return key_match_id, rival_id_match.group(1), rival_name
    return None, None, None

# --- FUNCIONES DE SELENIUM (SIN DUPLICACIONES ESTRUCTURALES) ---
@st.cache_resource(ttl=3600) 
def get_selenium_driver() -> webdriver.Chrome | None:
    """Inicializa y devuelve una instancia de Selenium ChromeDriver."""
    options = ChromeOptions()
    options.add_argument("--headless") # Ejecución sin interfaz gráfica
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36")
    options.add_argument('--blink-settings=imagesEnabled=false') # Deshabilita la carga de imágenes
    options.add_argument("--window-size=1920,1080")
    options.add_argument('--disable-logging') # Disable Chrome logging
    options.add_argument('--log-level=3') # Suppress info/warning messages
    
    try:
        # Asegúrate de que el driver esté en tu PATH o especifica service_log_path='/dev/null' si es necesario.
        return webdriver.Chrome(options=options)
    except WebDriverException as e:
        st.error(f"❌ Error al inicializar Selenium driver: {e}. Asegúrate de tener ChromeDriver instalado y en tu PATH.")
        return None

def click_element_robust(driver: webdriver.Chrome, by: By, value: str, timeout: int = 7) -> bool:
    """Intenta hacer clic en un elemento usando WebDriverWait y JS si es necesario."""
    try:
        element = WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY).until(
            EC.presence_of_element_located((by, value))
        )
        WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY).until(
            EC.visibility_of(element)
        )
        driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'center'});", element)
        time.sleep(0.3)
        try:
            WebDriverWait(driver, 2, poll_frequency=SELENIUM_POLL_FREQUENCY).until(EC.element_to_be_clickable((by, value))).click()
        except (ElementClickInterceptedException, TimeoutException):
            driver.execute_script("arguments[0].click();", element)
        return True
    except Exception:
        return False

# --- FUNCIONES DE EXTRACCIÓN DE DATOS ---
def get_h2h_details_for_rival_teams(driver_instance: webdriver.Chrome, key_match_id: str, rival_a_id: str, rival_b_id: str, rival_a_name: str = "Rival A", rival_b_name: str = "Rival B") -> dict:
    """
    Extrae los detalles de un enfrentamiento directo H2H específico de la sección 'Original H2H'.
    Busca un partido entre rival_a_id y rival_b_id en la tabla table_v2 de la página referenciada.
    """
    if not driver_instance: return {"status": "error", "message": "Driver no disponible."}
    if not key_match_id or not rival_a_id or not rival_b_id: return {"status": "error", "message": f"IDs incompletos para H2H {rival_a_name} vs {rival_b_name}."}

    url_to_visit = f"{BASE_URL}/match/h2h-{key_match_id}"
    try:
        driver_instance.get(url_to_visit)
        WebDriverWait(driver_instance, SELENIUM_TIMEOUT_SECONDS, poll_frequency=SELENIUM_POLL_FREQUENCY).until(
            EC.presence_of_element_located((By.ID, "table_v2"))
        )
        time.sleep(0.7) # Un pequeño sleep extra para asegurar la carga completa
        soup_selenium = BeautifulSoup(driver_instance.page_source, "html.parser")
    except TimeoutException:
        return {"status": "error", "message": f"Timeout esperando tabla en {url_to_visit}."}
    except Exception as e:
        return {"status": "error", "message": f"Error Selenium en {url_to_visit}: {type(e).__name__}."}

    if not soup_selenium: return {"status": "error", "message": f"Fallo en parseo de Selenium H2H en {url_to_visit}."}
    
    table_to_search_h2h = soup_selenium.find("table", id="table_v2")
    if not table_to_search_h2h: return {"status": "error", "message": f"Tabla 'v2' para H2H no encontrada en {url_to_visit}."}
    
    for row in table_to_search_h2h.find_all("tr", id=re.compile(r"tr2_\d+")):
        links = row.find_all("a", onclick=True)
        if len(links) < 2: continue

        h2h_row_home_id_match = re.search(r"team\((\d+)\)", links[0].get("onclick", ""))
        h2h_row_away_id_match = re.search(r"team\((\d+)\)", links[1].get("onclick", ""))

        if not h2h_row_home_id_match or not h2h_row_away_id_match: continue
        
        h2h_row_home_id = h2h_row_home_id_match.group(1)
        h2h_row_away_id = h2h_row_away_id_match.group(1)
        
        # Verificar si los IDs de los rivales coinciden con los del partido actual (independientemente del orden)
        if {h2h_row_home_id, h2h_row_away_id} == {str(rival_a_id), str(rival_b_id)}:
            score_span = row.find("span", class_="fscore_2")
            if not score_span or not score_span.text or "-" not in score_span.text: continue
            
            score_val_str = score_span.text.strip().split("(")[0].strip()
            goles_home, goles_away = score_val_str.split("-", 1)
            
            tds = row.find_all("td")
            handicap_raw = "N/A"
            HANDICAP_TD_IDX = 11 # Índice fijo del TD para el hándicap

            if len(tds) > HANDICAP_TD_IDX:
                cell = tds[HANDICAP_TD_IDX]
                data_o = cell.get("data-o")
                handicap_raw = data_o.strip() if data_o and data_o.strip() not in ["", "-"] else (cell.text.strip() if cell.text.strip() not in ["", "-"] else "N/A")
            
            # Determinar el rol de Rival A (local o visitante en este H2H encontrado)
            rol_rival_a = "H" if h2h_row_home_id == str(rival_a_id) else "A"
            
            return {
                "status": "found", 
                "goles_home": goles_home.strip(), 
                "goles_away": goles_away.strip(), 
                "handicap_raw": handicap_raw, # Retorna RAW, el formateo será en UI
                "rol_rival_a": rol_rival_a,
                "h2h_home_team_name": links[0].text.strip(),
                "h2h_away_team_name": links[1].text.strip()
            }
    return {"status": "not_found", "message": f"H2H directo no encontrado para {rival_a_name} vs {rival_b_name} en historial (table_v2)."}

def get_team_league_info_from_script(soup: BeautifulSoup) -> tuple[str, str, str, str, str, str]:
    """Extrae IDs y nombres de equipos y liga de un script JavaScript en la página."""
    home_id, away_id, league_id = (None,)*3
    home_name, away_name, league_name = ("N/A",)*3 # Default
    script_tag = soup.find("script", string=re.compile(r"var _matchInfo ="))
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

def extract_last_match_in_league(
    driver: webdriver.Chrome, 
    table_css_id: str, 
    main_team_name: str, 
    league_id_filter: str, 
    home_or_away_filter_css_selector: str, 
    is_main_team_home_in_history_filter: bool
) -> dict | None:
    """
    Extrae los datos del último partido del equipo principal en su liga,
    filtrando por si el equipo jugó en casa o fuera en ese partido.
    """
    try:
        # Hacer clic en el filtro de liga (si hay ID)
        if league_id_filter:
            league_checkbox_selector = f"input#checkboxleague{table_css_id[-1]}[value='{league_id_filter}']"
            click_element_robust(driver, By.CSS_SELECTOR, league_checkbox_selector)
            time.sleep(1.0) # Esperar la actualización de la tabla

        # Hacer clic en el filtro de local/visitante
        click_element_robust(driver, By.CSS_SELECTOR, home_or_away_filter_css_selector)
        time.sleep(1.0) # Esperar la actualización de la tabla
        
        page_source_updated = driver.page_source
        soup_updated = BeautifulSoup(page_source_updated, "html.parser")
        
        table = soup_updated.find("table", id=table_css_id)
        if not table: return None

        count_visible_rows = 0
        for row in table.find_all("tr", id=re.compile(rf"tr{table_css_id[-1]}_\d+")):
            if row.get("style") and "display:none" in row.get("style","").lower():
                continue # Saltar filas ocultas
            
            # Detenerse si ya hemos procesado suficientes filas visibles (optimización)
            count_visible_rows +=1
            if count_visible_rows > 15: break # Limitar a revisar 15 filas, asumir el último partido es una de ellas

            # Si hay filtro de liga, asegurar que la fila pertenece a la liga correcta.
            if league_id_filter and row.get("name") != str(league_id_filter): continue
            
            tds = row.find_all("td")
            if len(tds) < 14: continue # Asegurar que la fila tiene suficientes columnas

            home_team_row_el = tds[2].find("a")
            away_team_row_el = tds[4].find("a")
            
            if not home_team_row_el or not away_team_row_el: continue

            home_team_row_name = home_team_row_el.text.strip()
            away_team_row_name = away_team_row_el.text.strip()
            
            team_is_home_in_row = main_team_name.lower() == home_team_row_name.lower()
            team_is_away_in_row = main_team_name.lower() == away_team_row_name.lower()

            # Aplicar el filtro de local/visitante sobre el equipo principal
            if (is_main_team_home_in_history_filter and team_is_home_in_row) or \
               (not is_main_team_home_in_history_filter and team_is_away_in_row):
                
                date_span = tds[1].find("span", {"name": "timeData"})
                date_str = date_span.text.strip() if date_span else "N/A"
                
                score_class_re = re.compile(r"fscore_") # Captura fscore_1, fscore_2 etc.
                score_span = tds[3].find("span", class_=score_class_re)
                score_str = score_span.text.strip() if score_span else "N/A"
                
                handicap_cell = tds[11]
                handicap_raw = handicap_cell.get("data-o", handicap_cell.text.strip())
                handicap_raw = handicap_raw.strip() if handicap_raw and handicap_raw.strip() not in ["", "-"] else "N/A"
                
                return {
                    "date": date_str, 
                    "home_team": home_team_row_name, 
                    "away_team": away_team_row_name,
                    "score": score_str, # Ej: '2-1', '0-0'
                    "handicap_line_raw": handicap_raw # RAW hándicap, formatear para mostrar
                }
        return None # No se encontró ningún partido que coincida con los filtros
    except Exception as e:
        st.warning(f"❗ Error al extraer último partido en liga: {e}. Detalles del error: {type(e).__name__} en {__file__}:{e.__traceback__.tb_lineno}")
        return None

def get_main_match_odds_selenium(driver: webdriver.Chrome) -> dict:
    """Extrae las cuotas iniciales de Bet365 (AH y Goles) para el partido principal."""
    odds_info = {
        "ah_home_cuota": "N/A", "ah_linea_raw": "N/A", "ah_away_cuota": "N/A",
        "goals_over_cuota": "N/A", "goals_linea_raw": "N/A", "goals_under_cuota": "N/A"
    }
    try:
        live_compare_div = WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS, poll_frequency=SELENIUM_POLL_FREQUENCY).until(
            EC.presence_of_element_located((By.ID, "liveCompareDiv"))
        )
        # Selectores alternativos para la fila de Bet365, por si el ID cambia
        bet365_row_selector = "tr#tr_o_1_8[name='earlyOdds']"
        bet365_row_selector_alt = "tr#tr_o_1_31[name='earlyOdds']" # Otro ID común para Bet365
        
        table_odds = live_compare_div.find_element(By.XPATH, ".//table[contains(@class, 'team-table-other')]")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", table_odds)
        time.sleep(0.5)

        bet365_early_odds_row = None
        try: # Intentar selector primario
            bet365_early_odds_row = WebDriverWait(driver, 5, poll_frequency=SELENIUM_POLL_FREQUENCY).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, bet365_row_selector))
            )
        except TimeoutException: # Si no, intentar selector alternativo
            try:
                bet365_early_odds_row = WebDriverWait(driver, 3, poll_frequency=SELENIUM_POLL_FREQUENCY).until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, bet365_row_selector_alt))
                )
            except TimeoutException:
                return odds_info # Si ambos fallan, retornar N/A

        tds = bet365_early_odds_row.find_elements(By.TAG_NAME, "td")
        if len(tds) >= 11: # Asegurarse de que haya suficientes TDs para extraer las cuotas
            # AH Cuotas
            odds_info["ah_home_cuota"] = (tds[2].get_attribute("data-o") or tds[2].text.strip() or "N/A").strip()
            odds_info["ah_linea_raw"] = (tds[3].get_attribute("data-o") or tds[3].text.strip() or "N/A").strip()
            odds_info["ah_away_cuota"] = (tds[4].get_attribute("data-o") or tds[4].text.strip() or "N/A").strip()
            # Goles Cuotas
            odds_info["goals_over_cuota"] = (tds[8].get_attribute("data-o") or tds[8].text.strip() or "N/A").strip()
            odds_info["goals_linea_raw"] = (tds[9].get_attribute("data-o") or tds[9].text.strip() or "N/A").strip()
            odds_info["goals_under_cuota"] = (tds[10].get_attribute("data-o") or tds[10].text.strip() or "N/A").strip()
            
    except Exception as e:
        # Captura cualquier otro error, pero ya se intenta devolver info N/A si el elemento no está.
        st.warning(f"❗ Error al extraer cuotas con Selenium: {type(e).__name__}. Continuado...")
        pass # Mantener los valores N/A
    return odds_info

def extract_standings_data_from_h2h_page(h2h_soup: BeautifulSoup, target_team_name_exact: str) -> dict:
    """Extrae datos de clasificación (ranking, total, local/fuera) de un equipo."""
    # Estructura base para el resultado
    data = {
        "name": "N/A", "ranking": "N/A",
        "total_pj": "N/A", "total_v": "N/A", "total_e": "N/A", "total_d": "N/A", "total_gf": "N/A", "total_gc": "N/A",
        "specific_pj": "N/A", "specific_v": "N/A", "specific_e": "N/A", "specific_d": "N/A", "specific_gf": "N/A", "specific_gc": "N/A",
        "specific_type": "N/A" # "En Casa" o "Fuera"
    }
    if not h2h_soup or not target_team_name_exact: return data

    standings_section = h2h_soup.find("div", id="porletP4")
    if not standings_section: return data

    team_table_soup = None
    is_home_team_table_type = False

    # Intentar encontrar el equipo en la tabla local
    home_div_standings = standings_section.find("div", class_="home-div")
    if home_div_standings:
        # Busca el nombre del equipo dentro del header de la tabla para asegurar que es la correcta
        home_table_header = home_div_standings.find("tr", class_="team-home")
        if home_table_header and target_team_name_exact.lower() in home_table_header.get_text().lower():
            team_table_soup = home_div_standings.find("table", class_="team-table-home")
            is_home_team_table_type = True
            data["specific_type"] = home_div_standings.find("td", class_="bg1").text.strip() if home_div_standings.find("td", class_="bg1") else "En Casa"

    # Si no se encontró, intentar en la tabla visitante
    if not team_table_soup:
        guest_div_standings = standings_section.find("div", class_="guest-div")
        if guest_div_standings:
            guest_table_header = guest_div_standings.find("tr", class_="team-guest")
            if guest_table_header and target_team_name_exact.lower() in guest_table_header.get_text().lower():
                team_table_soup = guest_div_standings.find("table", class_="team-table-guest")
                is_home_team_table_type = False
                data["specific_type"] = guest_div_standings.find("td", class_="bg1").text.strip() if guest_div_standings.find("td", "bg1") else "Fuera"
    
    if not team_table_soup: return data # No se encontró la tabla de standings para este equipo.

    # Extraer nombre del equipo y ranking
    header_row_found = team_table_soup.find("tr", class_=re.compile(r"team-(home|guest)"))
    if header_row_found:
        link = header_row_found.find("a") # Puede estar dentro de un <a>
        text_content = link.get_text(separator=" ", strip=True) if link else header_row_found.get_text(separator=" ", strip=True)
        
        name_match = re.search(r"]\s*(.*)", text_content)
        rank_match = re.search(r"\[(?:[^\]]+-)?(\d+)\]", text_content)

        if name_match: data["name"] = name_match.group(1).strip()
        if rank_match: data["ranking"] = rank_match.group(1)
        
    ft_rows = [] # Filas de la tabla de clasificación de "Full Time" (FT)
    current_section = None # Para diferenciar FT, HT etc.

    for row in team_table_soup.find_all("tr", align="center"):
        th_cell = row.find("th")
        if th_cell:
            if "FT" in th_cell.get_text(strip=True): current_section = "FT"
            elif "HT" in th_cell.get_text(strip=True): break # Parar al llegar a Half Time
        
        if current_section == "FT":
            cells = row.find_all("td")
            if cells and len(cells) > 0 and cells[0].get_text(strip=True) in ["Total", "Home", "Away"]:
                ft_rows.append(cells)
    
    # Procesar las filas extraídas
    for cells in ft_rows:
        if len(cells) > 8: # Asegurar que hay suficientes columnas
            row_type_text = cells[0].get_text(strip=True)
            pj, v, e, d, gf, gc = (cells[i].get_text(strip=True) or "N/A" for i in range(1, 7)) # Pj, V, E, D, Gf, Gc

            if row_type_text == "Total":
                data["total_pj"], data["total_v"], data["total_e"], data["total_d"], data["total_gf"], data["total_gc"] = pj, v, e, d, gf, gc
            elif row_type_text == "Home" and is_home_team_table_type:
                data["specific_pj"], data["specific_v"], data["specific_e"], data["specific_d"], data["specific_gf"], data["specific_gc"] = pj, v, e, d, gf, gc
            elif row_type_text == "Away" and not is_home_team_table_type:
                data["specific_pj"], data["specific_v"], data["specific_e"], data["specific_d"], data["specific_gf"], data["specific_gc"] = pj, v, e, d, gf, gc
    
    # Asegurar que el nombre de la data refleje el nombre que se buscó o el que se encontró.
    # priorizamos el que se encontró en la tabla, si es distinto del default "N/A"
    data["name"] = data["name"] if data["name"] != "N/A" else target_team_name_exact

    return data

def extract_final_score(soup: BeautifulSoup) -> tuple[str, str]:
    """Extrae el marcador final del partido de la página H2H principal."""
    try:
        score_divs = soup.select('#mScore .end .score') # Selecciona divs con clase 'score' dentro de 'end' dentro de '#mScore'
        if len(score_divs) == 2:
            home_score_str = score_divs[0].text.strip()
            away_score_str = score_divs[1].text.strip()
            if home_score_str.isdigit() and away_score_str.isdigit():
                return f"{home_score_str}*{away_score_str}", f"{home_score_str}-{away_score_str}"
    except Exception:
        pass
    return '?*?', "?-?" # Valores por defecto

def extract_h2h_data(soup: BeautifulSoup, main_home_team_name: str, main_away_team_name: str, current_league_id: str) -> dict:
    """Extrae datos del H2H específico y general entre los equipos."""
    # Valores por defecto
    data = {
        'ah_h2h_exact_fmt': '-', 'score_h2h_exact_fmt': '?*?', 'score_h2h_exact_raw': '?-?',
        'ah_h2h_general_fmt': '-', 'score_h2h_general_fmt': '?*?', 'score_h2h_general_raw': '?-?'
    }

    h2h_table = soup.find("table", id="table_v3")
    if not h2h_table: return data

    filtered_h2h_list = []
    # Validación de nombres para evitar errores.
    if not main_home_team_name or not main_away_team_name: 
        return data

    for row_h2h in h2h_table.find_all("tr", id=re.compile(r"tr3_\d+")):
        # 'fscore_3' es la clase para el marcador en la tabla h2h_v3
        details = get_match_details_from_row(row_h2h, score_class_selector='fscore_3')
        if not details: continue
        # Filtro de liga
        if current_league_id and details.get('league_id_hist') and details.get('league_id_hist') != str(current_league_id):
            continue
        filtered_h2h_list.append(details)
    
    if not filtered_h2h_list: return data # No hay datos H2H para procesar

    # H2H General (siempre es el primero en la lista filtrada si hay)
    h2h_general_match = filtered_h2h_list[0]
    data['ah_h2h_general_fmt'] = h2h_general_match.get('ahLine', '-')
    data['score_h2h_general_fmt'] = h2h_general_match.get('score', '?*?')
    data['score_h2h_general_raw'] = h2h_general_match.get('score_raw', '?-?')
    
    # H2H Específico (local vs visitante exacto en casa del local)
    h2h_local_specific_match = None
    for h2h_detail in filtered_h2h_list:
        if h2h_detail.get('home','').lower() == main_home_team_name.lower() and \
           h2h_detail.get('away','').lower() == main_away_team_name.lower():
            h2h_local_specific_match = h2h_detail
            break # Encontrado el partido más reciente de H2H directo
            
    if h2h_local_specific_match:
        data['ah_h2h_exact_fmt'] = h2h_local_specific_match.get('ahLine', '-')
        data['score_h2h_exact_fmt'] = h2h_local_specific_match.get('score', '?*?')
        data['score_h2h_exact_raw'] = h2h_local_specific_match.get('score_raw', '?-?')
        
    return data

def extract_comparative_match(soup_for_team_history: BeautifulSoup, table_id_of_team_to_search: str, 
                             team_name_to_find_match_for: str, opponent_name_to_search: str, 
                             current_league_id: str, is_home_table: bool) -> dict | None:
    """
    Extrae el partido comparativo del historial de un equipo contra un oponente específico.
    Devuelve un diccionario con score, ahLine y localía si se encuentra.
    """
    if not opponent_name_to_search or opponent_name_to_search == "N/A" or not team_name_to_find_match_for:
        return None # Devuelve None si no hay oponentes o equipo principal válidos
    
    table = soup_for_team_history.find("table", id=table_id_of_team_to_search)
    if not table: return None

    # Ajustar el selector de clase de score basado en si es la tabla de Local (table_v1) o Visitante (table_v2)
    score_class_selector = 'fscore_1' if is_home_table else 'fscore_2'
    
    # Itera sobre las filas visibles del historial (tr1_xxx para v1, tr2_xxx para v2)
    for row in table.find_all("tr", id=re.compile(rf"tr{table_id_of_team_to_search[-1]}_\d+")):
        details = get_match_details_from_row(row, score_class_selector=score_class_selector)
        if not details: continue
        
        # Filtrar por liga si se proporciona un ID de liga
        if current_league_id and details.get('league_id_hist') and details.get('league_id_hist') != str(current_league_id):
            continue
            
        home_hist_lower = details.get('home','').lower()
        away_hist_lower = details.get('away','').lower()
        
        team_main_lower = team_name_to_find_match_for.lower()
        opponent_lower = opponent_name_to_search.lower()

        # Buscar el partido donde el equipo principal jugó contra el oponente (en cualquier rol)
        if (team_main_lower == home_hist_lower and opponent_lower == away_hist_lower) or \
           (team_main_lower == away_hist_lower and opponent_lower == home_hist_lower):
            
            score = details.get('score', '?*?')
            ah_line_extracted = details.get('ahLine', '-') # Ya está formateado
            localia = 'H' if team_main_lower == home_hist_lower else 'A' # ¿Jugó como local el equipo principal en ese partido?
            
            return {"score": score, "ah_line": ah_line_extracted, "localia": localia}
    
    return None # No se encontró un partido comparativo

# --- HELPER DE INTERFAZ DE STREAMLIT (DRY PRINCIPAL) ---

def _display_team_standings_section(st_col: st.delta_generator.DeltaGenerator, team_name: str, standings_data: dict):
    """Muestra la sección de clasificación de un equipo en una columna."""
    st_col.subheader(f"📊 {team_name}")
    if standings_data.get("name", "N/A") != "N/A": # Si se pudo obtener datos válidos
        sd = standings_data
        st_col.markdown(f"- **Ranking:** {sd.get('ranking', 'N/A')}\n"
                         f"- **Total:** {sd.get('total_pj', 'N/A')} PJ | {sd.get('total_v', 'N/A')}V-{sd.get('total_e', 'N/A')}E-{sd.get('total_d', 'N/A')}D | GF: {sd.get('total_gf', 'N/A')}, GC: {sd.get('total_gc', 'N/A')}\n"
                         f"- **{sd.get('specific_type','Posición')}:** {sd.get('specific_pj', 'N/A')} PJ | {sd.get('specific_v', 'N/A')}V-{sd.get('specific_e', 'N/A')}E-{sd.get('specific_d', 'N/A')}D | GF: {sd.get('specific_gf', 'N/A')}, GC: {sd.get('specific_gc', 'N/A')}")
    else:
        st_col.info(f"Clasificación no disponible para {team_name}.")

def _display_last_match_section(st_col: st.delta_generator.DeltaGenerator, team_type: str, match_data: dict, home_name: str, away_name: str):
    """Muestra los detalles del último partido en liga de un equipo."""
    team_name = home_name if team_type == 'home' else away_name
    st_col.markdown(f"##### {'🏡' if team_type == 'home' else '✈️'} Últ. {team_name} ({'Casa' if team_type == 'home' else 'Fuera'})")
    if match_data:
        res = match_data
        opponent_name = res['away_team'] if team_type == 'home' else res['home_team']
        st_col.markdown(f"**vs.** `{opponent_name}`\n\n**{res['home_team']}** `{res['score'].replace('-',':')}` **{res['away_team']}**")
        st_col.markdown(f"**AH:** <span style='font-weight:bold;'>`{format_ah_as_decimal_string(res.get('handicap_line_raw','-'))}`</span>", unsafe_allow_html=True)
        st_col.caption(f"📅 {res['date']}")
    else:
        st_col.info(f"No encontrado.")

def _display_h2h_col3_section(st_col: st.delta_generator.DeltaGenerator, driver: webdriver.Chrome, 
                                 key_match_id: str, rival_a_id: str, rival_b_id: str, rival_a_name: str, rival_b_name: str):
    """Muestra el resultado del H2H específico de la Columna 3."""
    st_col.markdown(f"##### ⚔️ H2H entre oponentes (Col3)")
    details_h2h = {"status": "error", "message": "N/A"}
    if key_match_id and rival_a_id and rival_b_id and driver:
        with st_col.status(f"Buscando H2H: `{rival_a_name}` vs `{rival_b_name}`...", expanded=False) as status:
            details_h2h = get_h2h_details_for_rival_teams(driver, key_match_id, rival_a_id, rival_b_id, rival_a_name, rival_b_name)
            if details_h2h.get("status") == "found":
                status.update(label=f"H2H de oponentes encontrado para `{rival_a_name}` vs `{rival_b_name}`", state="complete", icon="✅")
            else:
                status.update(label=f"H2H de oponentes no encontrado", state="error", icon="❌")
                st_col.warning(f"💡 Info: {details_h2h.get('message', 'N/A')}")

    if details_h2h.get("status") == "found":
        res_h2h = details_h2h
        st_col.markdown(f"**{res_h2h.get('h2h_home_team_name')}** `{res_h2h.get('goles_home')}:{res_h2h.get('goles_away')}` **{res_h2h.get('h2h_away_team_name')}**")
        st_col.markdown(f"(**AH:** `{format_ah_as_decimal_string(res_h2h.get('handicap_raw','-'))}`)") # Formatear aquí
    else:
        st_col.info(details_h2h.get('message', "H2H de oponentes no disponible."))

def _display_opponent_standings_expander(rival_a_standings: dict, rival_b_standings: dict, rival_a_name_display: str, rival_b_name_display: str):
    """Muestra la clasificación de los oponentes H2H en un expander."""
    with st.expander("🔎 Clasificación Oponentes (H2H Comparado)"):
        opp_stand_col1, opp_stand_col2 = st.columns(2)
        
        with opp_stand_col1:
            st.markdown(f"###### {rival_a_standings.get('name', rival_a_name_display)}")
            if rival_a_standings.get("name", "N/A") != "N/A":
                rst = rival_a_standings
                st.caption(f"🏆 Rk: {rst.get('ranking','N/A')}\n"
                           f"🌍 T: {rst.get('total_pj')}|{rst.get('total_v')}/{rst.get('total_e')}/{rst.get('total_d')}|{rst.get('total_gf')}-{rst.get('total_gc')}\n"
                           f"🏟️ {rst.get('specific_type')}: {rst.get('specific_pj')}|{rst.get('specific_v')}/{rst.get('specific_e')}/{rst.get('specific_d')}|{rst.get('specific_gf')}-{rst.get('specific_gc')}")
            else:
                st.caption("No disponible.")
        with opp_stand_col2:
            st.markdown(f"###### {rival_b_standings.get('name', rival_b_name_display)}")
            if rival_b_standings.get("name", "N/A") != "N/A":
                rst = rival_b_standings
                st.caption(f"🏆 Rk: {rst.get('ranking','N/A')}\n"
                           f"🌍 T: {rst.get('total_pj')}|{rst.get('total_v')}/{rst.get('total_e')}/{rst.get('total_d')}|{rst.get('total_gf')}-{rst.get('total_gc')}\n"
                           f"🏟️ {rst.get('specific_type')}: {rst.get('specific_pj')}|{rst.get('specific_v')}/{rst.get('specific_e')}/{rst.get('specific_d')}|{rst.get('specific_gf')}-{rst.get('specific_gc')}")
            else:
                st.caption("No disponible.")

def _display_indirect_comparative(st_col: st.delta_generator.DeltaGenerator, title: str, comparative_data: dict | None):
    """Muestra los resultados de una comparativa indirecta de forma clara."""
    st_col.markdown(title, unsafe_allow_html=True)
    if comparative_data:
        score_part = comparative_data['score'].replace('*', ':')
        ah_val = comparative_data['ah_line'] # Ya viene formateado
        loc_val = comparative_data['localia']
        st_col.markdown(f"⚽ **Resultado:** `{score_part or '(No disponible)'}`")
        st_col.markdown(f"⚖️ **AH Partido Comparado:** `{ah_val or '(No disponible)'}`")
        st_col.markdown(f"🏟️ **Localía en ese partido:** `{loc_val or '(No disponible)'}`")
    else:
        st_col.info("Comparativa no disponible.")

# --- STREAMLIT APP UI (Función principal limpia) ---
def display_other_feature_ui():
    st.set_page_config(layout="wide", page_title="⚽ Análisis Avanzado", initial_sidebar_state="expanded")
    st.title("⚽ Herramienta de Análisis de Partidos")
    st.markdown("Esta herramienta te permite obtener estadísticas detalladas y el contexto H2H para un partido específico de Nowgoal. 🎉")
    st.divider()

    st.sidebar.title("⚙️ Configuración del Partido")
    main_match_id_str_input = st.sidebar.text_input(
        "🆔 ID del Partido Principal:", 
        value="2696131", 
        help="Pega el ID numérico del partido que deseas analizar. Ej: `2696131`", 
        key="other_feature_match_id_input"
    )
    analizar_button = st.sidebar.button(
        "🚀 Analizar Partido", 
        type="primary", 
        use_container_width=True, 
        key="other_feature_analizar_button"
    )

    results_container = st.container()

    if 'selenium_driver_other_feature' not in st.session_state: 
        st.session_state.selenium_driver_other_feature = None

    if analizar_button:
        results_container.empty()
        match_id_to_process = None

        if main_match_id_str_input:
            try:
                # Limpiar la entrada, quitando todo lo que no sea dígito.
                cleaned_id_str = "".join(filter(str.isdigit, main_match_id_str_input))
                if cleaned_id_str: 
                    match_id_to_process = int(cleaned_id_str)
            except ValueError: 
                results_container.error("⚠️ ID de partido no válido. Por favor, introduce solo números."); st.stop()
        
        if not match_id_to_process: 
            results_container.warning("⚠️ Ingresa un ID de partido válido para comenzar el análisis."); st.stop()
        
        start_time = time.time()
        with results_container:
            # --- FASE 1: Obtención de Datos Iniciales y Básicos ---
            with st.status("Preparando análisis... Obteniendo datos iniciales...", expanded=True) as status_initial:
                main_page_url_h2h_view = f"/match/h2h-{match_id_to_process}"
                
                soup_main_h2h_page = fetch_soup_requests(main_page_url_h2h_view)
                if not soup_main_h2h_page:
                    status_initial.update(label="Error al cargar la página principal H2H", state="error", icon="❌")
                    st.error("❌ No se pudo obtener la página H2H principal. Verifica el ID del partido o la conectividad."); st.stop()
                
                mp_home_id, mp_away_id, mp_league_id, mp_home_name_script, mp_away_name_script, mp_league_name = get_team_league_info_from_script(soup_main_h2h_page)
                
                # Fetch Standing Data (puede ser desde el mismo soup)
                home_team_main_standings = extract_standings_data_from_h2h_page(soup_main_h2h_page, mp_home_name_script)
                away_team_main_standings = extract_standings_data_from_h2h_page(soup_main_h2h_page, mp_away_name_script)
                
                # Determinar los nombres a mostrar (priorizando los de la tabla de standings si están disponibles)
                display_home_name = home_team_main_standings.get("name", "N/A") if home_team_main_standings.get("name", "N/A") != "N/A" else mp_home_name_script
                display_away_name = away_team_main_standings.get("name", "N/A") if away_team_main_standings.get("name", "N/A") != "N/A" else mp_away_name_script

                # H2H Exacto y General entre los equipos del partido principal
                h2h_main_teams_data = extract_h2h_data(soup_main_h2h_page, display_home_name, display_away_name, mp_league_id)
                
                # Info para H2H de "Column 3" (rivales del H2H original del partido principal)
                # Unificar obtención de Rival A y Rival B en una sola función
                key_match_id_rival_a_h2h, rival_a_id_col3, rival_a_name_col3 = get_rival_info_from_h2h_table(soup_main_h2h_page, "table_v1", r"tr1_\d+", 1)
                match_id_rival_b_game_ref, rival_b_id_col3, rival_b_name_col3 = get_rival_info_from_h2h_table(soup_main_h2h_page, "table_v2", r"tr2_\d+", 0)
                
                # Extraer standings de los oponentes H2H (si se encontraron)
                rival_a_standings = {}
                if rival_a_name_col3 and rival_a_name_col3 != "N/A" and key_match_id_rival_a_h2h:
                    soup_rival_a_h2h_page = fetch_soup_requests(f"/match/h2h-{key_match_id_rival_a_h2h}")
                    if soup_rival_a_h2h_page:
                        rival_a_standings = extract_standings_data_from_h2h_page(soup_rival_a_h2h_page, rival_a_name_col3)
                
                rival_b_standings = {}
                if rival_b_name_col3 and rival_b_name_col3 != "N/A" and match_id_rival_b_game_ref:
                    soup_rival_b_h2h_page = fetch_soup_requests(f"/match/h2h-{match_id_rival_b_game_ref}")
                    if soup_rival_b_h2h_page:
                        rival_b_standings = extract_standings_data_from_h2h_page(soup_rival_b_h2h_page, rival_b_name_col3)

                status_initial.update(label="Datos iniciales y H2H extraídos. Iniciando Selenium para datos dinámicos...", state="running", icon="🛠️")

            # --- FASE 2: Extracción con Selenium (Cuotas, Últimos partidos específicos) ---
            driver = st.session_state.selenium_driver_other_feature
            driver_needs_init = False
            
            if driver is None:
                driver_needs_init = True
            else:
                try:
                    # Intenta una operación básica para verificar que el driver sigue vivo.
                    _ = driver.window_handles
                    # Para chromedriver_autoinstaller service no es connectable por default,
                    # mejor checar si la URL sigue funcionando para asegurarse
                    driver.current_url # Try simple operation
                except WebDriverException:
                    driver_needs_init = True
                except Exception as e:
                    # Captura otras excepciones (e.g., driver.quit() llamado previamente)
                    driver_needs_init = True
                    st.warning(f"Se intentará reiniciar el WebDriver: {type(e).__name__} en la verificación.")

            if driver_needs_init:
                if driver is not None:
                    try: driver.quit()
                    except: pass # Intentar cerrar el driver existente si es posible
                with st.spinner("🚀 Inicializando WebDriver de Selenium (esto puede tardar unos segundos)..."):
                    driver = get_selenium_driver()
                st.session_state.selenium_driver_other_feature = driver

            main_match_odds_data = {}
            last_home_match_in_league = None
            last_away_match_in_league = None
            
            if driver:
                with st.status("Obteniendo cuotas y últimos partidos (con Selenium)...", expanded=True) as status_selenium:
                    try:
                        driver.get(f"{BASE_URL}{main_page_url_h2h_view}") 
                        WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS).until(EC.presence_of_element_located((By.ID, "table_v1"))) 
                        time.sleep(0.8) # Espera adicional para renderizado dinámico
                        
                        main_match_odds_data = get_main_match_odds_selenium(driver)
                        
                        if mp_home_id and mp_league_id and display_home_name and display_home_name != "N/A":
                             last_home_match_in_league = extract_last_match_in_league(driver, "table_v1", display_home_name, mp_league_id, "input#cb_sos1[value='1']", is_main_team_home_in_history_filter=True)
                        if mp_away_id and mp_league_id and display_away_name and display_away_name != "N/A":
                            last_away_match_in_league = extract_last_match_in_league(driver, "table_v2", display_away_name, mp_league_id, "input#cb_sos2[value='2']", is_main_team_home_in_history_filter=False)
                        
                        status_selenium.update(label="Cuotas y últimos partidos extraídos correctamente. ¡Análisis completado! ✨", state="complete", icon="✅")

                    except Exception as e_main_sel:
                        status_selenium.update(label="Error en la extracción con Selenium", state="error", icon="❌")
                        st.error(f"❗ Ocurrió un error grave al usar Selenium: {type(e_main_sel).__name__}. {e_main_sel}")
                        if "SessionNotCreatedException" in str(e_main_sel):
                             st.info("Esto puede deberse a una incompatibilidad entre el driver de Chrome y tu versión del navegador. Por favor, asegúrate de que ambos estén actualizados.")
            else:
                st.warning("❗ WebDriver de Selenium no pudo ser inicializado. Algunas características (cuotas, últimos partidos, H2H Col3) no estarán disponibles.")
                status_initial.update(label="Análisis parcial. Selenium no disponible.", state="warning", icon="⚠️")

            # --- Consolidar y Preparar Datos para la Visualización ---
            final_score_fmt, _ = extract_final_score(soup_main_h2h_page)

            # Data for comparative matches (extract to separate variables to use the dict format)
            last_away_opponent_for_home_hist = last_away_match_in_league.get('home_team') if last_away_match_in_league else None
            comparative_L_vs_UVA = None
            if last_away_opponent_for_home_hist and display_home_name != "N/A":
                comparative_L_vs_UVA = extract_comparative_match(soup_main_h2h_page, "table_v1", display_home_name, last_away_opponent_for_home_hist, mp_league_id, is_home_table=True)
            
            last_home_opponent_for_away_hist = last_home_match_in_league.get('away_team') if last_home_match_in_league else None
            comparative_V_vs_ULH = None
            if last_home_opponent_for_away_hist and display_away_name != "N/A":
                comparative_V_vs_ULH = extract_comparative_match(soup_main_h2h_page, "table_v2", display_away_name, last_home_opponent_for_away_hist, mp_league_id, is_home_table=False)

            # --- INICIO DE LA VISUALIZACIÓN EN STREAMLIT ---
            st.markdown(f"## ⚔️ **{display_home_name or 'Local'} vs {display_away_name or 'Visitante'}**")
            st.caption(f"🏆 **Liga:** `{mp_league_name or 'N/A'}` (ID: `{mp_league_id or 'N/A'}`) | 🗓️ **Partido ID:** `{match_id_to_process}`")
            st.divider()

            st.header("🎯 Estado de Clasificación Actual")
            col_home_stand, col_away_stand = st.columns(2)
            _display_team_standings_section(col_home_stand, display_home_name, home_team_main_standings)
            _display_team_standings_section(col_away_stand, display_away_name, away_team_main_standings)
            st.divider()

            st.header("📈 Cuotas y Marcador")
            odds_col1, odds_col2, odds_col3 = st.columns([1.5, 1.5, 1])
            with odds_col1:
                st.markdown(f"**H. Asiático Inicial (Bet365):**")
                st.markdown(
                    f"`{main_match_odds_data.get('ah_home_cuota','N/A')}` "
                    f"<span style='color:#007bff; font-weight:bold;'>[{format_ah_as_decimal_string(main_match_odds_data.get('ah_linea_raw','?'))}]</span> "
                    f"`{main_match_odds_data.get('ah_away_cuota','N/A')}`", 
                    unsafe_allow_html=True
                )
            with odds_col2:
                st.markdown(f"**Línea de Goles Inicial (Bet365):**")
                st.markdown(
                    f"`Ov {main_match_odds_data.get('goals_over_cuota','N/A')}` "
                    f"<span style='color:#dc3545; font-weight:bold;'>[{format_ah_as_decimal_string(main_match_odds_data.get('goals_linea_raw','?'))}]</span> "
                    f"`Un {main_match_odds_data.get('goals_under_cuota','N/A')}`", 
                    unsafe_allow_html=True
                )
            with odds_col3:
                 st.metric(label="🏁 Marcador Final (Si Finalizado)", value=final_score_fmt.replace("*",":"))
            st.divider()
            
            st.header("⚡ Rendimiento Reciente y H2H Directo/Comparado")
            
            col_last_home, col_last_away, col_h2h_rival_opp = st.columns(3)
            _display_last_match_section(col_last_home, 'home', last_home_match_in_league, display_home_name, display_away_name)
            _display_last_match_section(col_last_away, 'away', last_away_match_in_league, display_home_name, display_away_name)
            _display_h2h_col3_section(col_h2h_rival_opp, driver, key_match_id_rival_a_h2h, rival_a_id_col3, rival_b_id_col3, rival_a_name_col3, rival_b_name_col3)

            _display_opponent_standings_expander(rival_a_standings, rival_b_standings, 
                                                rival_a_name_col3 or (rival_a_id_col3 if rival_a_id_col3 else "Rival A"),
                                                rival_b_name_col3 or (rival_b_id_col3 if rival_b_id_col3 else "Rival B"))
            
            with st.expander("🤝 Enfrentamientos Directos", expanded=True):
                h2h_col1, h2h_col2, h2h_col3 = st.columns(3)
                h2h_col1.metric("Último AH H2H (Local de Hoy en Casa)", h2h_main_teams_data.get('ah_h2h_exact_fmt'))
                h2h_col2.metric("Último Res. H2H (Local de Hoy en Casa)", h2h_main_teams_data.get('score_h2h_exact_fmt').replace("*", ":"))
                h2h_col3.metric("Último AH H2H (General)", h2h_main_teams_data.get('ah_h2h_general_fmt'))
                h2h_col3.metric("Último Res. H2H (General)", h2h_main_teams_data.get('score_h2h_general_fmt').replace("*", ":"))

            st.markdown("---") # Separador para una mejor lectura

            st.header("🔁 Comparativas Indirectas (Análisis Profundo)")
            comp_col1, comp_col2 = st.columns(2)
            
            _display_indirect_comparative(comp_col1, 
                                        f"**<span style='color: #1E90FF;'>🏠 {display_home_name}</span> vs. <span style='color: #FF4500;'>Últ. Rival de {display_away_name}</span>** (cuando Visitante jugó Fuera)",
                                        comparative_L_vs_UVA)
            
            _display_indirect_comparative(comp_col2, 
                                        f"**<span style='color: #FF4500;'>✈️ {display_away_name}</span> vs. <span style='color: #1E90FF;'>Últ. Rival de {display_home_name}</span>** (cuando Local jugó en Casa)",
                                        comparative_V_vs_ULH)
            
            st.divider()

            # Bloque de datos adicionales
            st.header("ℹ️ Resumen de Datos Clave")
            info_col1, info_col2, info_col3 = st.columns(3)
            info_col1.metric("Línea Goles Partido (Actual)", format_ah_as_decimal_string(main_match_odds_data.get('goals_linea_raw', '?')))
            info_col2.metric("Liga del Partido", mp_league_name or "N/A")
            info_col3.metric("ID Partido Actual", str(match_id_to_process))

            st.divider()

            end_time = time.time()
            st.sidebar.info(f"⏱️ Análisis completado en {end_time - start_time:.2f} segundos.")
    else:
        results_container.info("✨ ¡Listo para analizar! Ingresa un ID de partido en la barra lateral y haz clic en 'Analizar Partido' para ver los detalles.")

if __name__ == '__main__':
    display_other_feature_ui()
