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
import traceback # Para logging de errores detallado si es necesario

# --- CONFIGURACIÓN GLOBAL ---
BASE_URL = "https://live18.nowgoal25.com"
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
        return '-' 

    if numeric_value == 0.0:
        return "0"

    sign = -1 if numeric_value < 0 else 1
    abs_num = abs(numeric_value)
    
    if abs(abs_num - round(abs_num, 0)) < 1e-9:
        return str(int(round(numeric_value, 0)))
    
    if abs(abs_num - (math.floor(abs_num) + 0.5)) < 1e-9:
        return f"{numeric_value:.1f}"
    
    if abs(abs_num - (math.floor(abs_num) + 0.25)) < 1e-9 or \
       abs(abs_num - (math.floor(abs_num) + 0.75)) < 1e-9:
        return f"{numeric_value:.2f}"

    return f"{numeric_value:.2f}"

def get_match_details_from_row(row_element, score_class_selector='score'):
    """Extrae detalles de partido (equipos, resultado, AH) de una fila de tabla."""
    try:
        cells = row_element.find_all('td')
        if len(cells) < 12: return None

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
        score_fmt = score_raw.replace('-', '*') if score_raw != '?-?' else '?*?'

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

# --- FUNCIONES DE REQUESTS ---
@st.cache_resource(ttl=3600)
def get_requests_session() -> requests.Session:
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36"})
    return session

@st.cache_data(ttl=3600)
def fetch_soup_requests(path: str, max_tries: int = 3, delay: int = 1) -> BeautifulSoup | None:
    session = get_requests_session()
    url = f"{BASE_URL}{path}"
    for attempt in range(1, max_tries + 1):
        try:
            resp = session.get(url, timeout=10)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except requests.RequestException as e:
            if attempt == max_tries:
                # No usar st.error aquí directamente para que la función que llama pueda manejar el None
                # st.error(f"❌ Falló la petición a {url} después de {max_tries} intentos: {e}")
                print(f"ERROR fetch_soup_requests: Falló la petición a {url} después de {max_tries} intentos: {e}") # Para logs
                return None
            time.sleep(delay * attempt)
    return None # Debería ser alcanzado solo si max_tries es 0 o menos

def get_rival_info_from_h2h_table(soup: BeautifulSoup, table_id: str, row_id_regex: str, link_index: int) -> tuple[str | None, str | None, str | None]:
    if not soup: return None, None, None # Añadido chequeo por si el soup es None
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

# --- FUNCIONES DE SELENIUM ---
@st.cache_resource(ttl=3600) 
def get_selenium_driver() -> webdriver.Chrome | None:
    options = ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36")
    options.add_argument('--blink-settings=imagesEnabled=false')
    options.add_argument("--window-size=1920,1080")
    options.add_argument('--disable-logging')
    options.add_argument('--log-level=3') # Solo errores fatales
    
    try:
        # Para entornos como Streamlit Cloud, a menudo no se necesita especificar chromedriver_path si está en el buildpack
        return webdriver.Chrome(options=options)
    except WebDriverException as e:
        st.error(f"❌ Error al inicializar Selenium driver: {e}. Asegúrate de que ChromeDriver sea compatible y esté accesible.")
        return None

def click_element_robust(driver: webdriver.Chrome, by: By, value: str, timeout: int = 7) -> bool:
    try:
        element = WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY).until(
            EC.presence_of_element_located((by, value))
        )
        WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY).until(
            EC.visibility_of(element)
        )
        driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'center'});", element)
        time.sleep(0.3) # Pequeña pausa para asegurar que el scroll ha terminado
        try:
            WebDriverWait(driver, 2, poll_frequency=SELENIUM_POLL_FREQUENCY).until(EC.element_to_be_clickable((by, value))).click()
        except (ElementClickInterceptedException, TimeoutException): # Si es interceptado o no clickeable
            driver.execute_script("arguments[0].click();", element) # Forzar click con JS
        return True
    except Exception: # Captura cualquier otra excepción durante el proceso
        return False

# --- FUNCIONES DE EXTRACCIÓN DE DATOS ---
def get_h2h_details_for_rival_teams(driver_instance: webdriver.Chrome, key_match_id: str, rival_a_id: str, rival_b_id: str, rival_a_name: str = "Rival A", rival_b_name: str = "Rival B") -> dict:
    if not driver_instance: return {"status": "error", "message": "Driver no disponible para H2H de rivales."}
    if not key_match_id or not rival_a_id or not rival_b_id: return {"status": "error", "message": f"IDs incompletos para H2H {rival_a_name} vs {rival_b_name}."}

    url_to_visit = f"{BASE_URL}/match/h2h-{key_match_id}"
    try:
        driver_instance.get(url_to_visit)
        WebDriverWait(driver_instance, SELENIUM_TIMEOUT_SECONDS, poll_frequency=SELENIUM_POLL_FREQUENCY).until(
            EC.presence_of_element_located((By.ID, "table_v2")) # Esperar un elemento clave de la tabla
        )
        time.sleep(0.7) # Pausa adicional para asegurar que JS haya cargado todo
        soup_selenium = BeautifulSoup(driver_instance.page_source, "html.parser")
    except TimeoutException:
        return {"status": "error", "message": f"Timeout esperando tabla v2 en {url_to_visit}."}
    except Exception as e:
        return {"status": "error", "message": f"Error Selenium al acceder a {url_to_visit}: {type(e).__name__}."}

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
        
        if {h2h_row_home_id, h2h_row_away_id} == {str(rival_a_id), str(rival_b_id)}:
            score_span = row.find("span", class_="fscore_2")
            if not score_span or not score_span.text or "-" not in score_span.text: continue
            
            score_val_str = score_span.text.strip().split("(")[0].strip() # Tomar solo el marcador, ej '2-1'
            goles_home, goles_away = score_val_str.split("-", 1)
            
            tds = row.find_all("td")
            handicap_raw = "N/A"
            HANDICAP_TD_IDX = 11 # Asumiendo que el índice no cambia

            if len(tds) > HANDICAP_TD_IDX:
                cell = tds[HANDICAP_TD_IDX]
                data_o = cell.get("data-o")
                handicap_raw = data_o.strip() if data_o and data_o.strip() not in ["", "-"] else (cell.text.strip() if cell.text.strip() not in ["", "-"] else "N/A")
            
            rol_rival_a = "H" if h2h_row_home_id == str(rival_a_id) else "A"
            
            return {
                "status": "found", 
                "goles_home": goles_home.strip(), 
                "goles_away": goles_away.strip(), 
                "handicap_raw": handicap_raw,
                "rol_rival_a": rol_rival_a,
                "h2h_home_team_name": links[0].text.strip(),
                "h2h_away_team_name": links[1].text.strip()
            }
    return {"status": "not_found", "message": f"H2H directo no encontrado para {rival_a_name} vs {rival_b_name} en historial (table_v2)."}

def get_team_league_info_from_script(soup: BeautifulSoup) -> tuple[str, str, str, str, str, str]:
    home_id, away_id, league_id = (None,)*3
    home_name, away_name, league_name = ("N/A",)*3
    if not soup: return home_id, away_id, league_id, home_name, away_name, league_name # Chequeo robusto
    
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
    if not driver or not main_team_name or main_team_name == "N/A": # Chequeos robustos
        return None
    try:
        if league_id_filter:
            league_checkbox_selector = f"input#checkboxleague{table_css_id[-1]}[value='{league_id_filter}']"
            if not click_element_robust(driver, By.CSS_SELECTOR, league_checkbox_selector):
                st.warning(f"No se pudo hacer clic en el filtro de liga para {table_css_id}")
                # Considerar si continuar o retornar None
            time.sleep(1.0) # Esperar actualización

        if not click_element_robust(driver, By.CSS_SELECTOR, home_or_away_filter_css_selector):
            st.warning(f"No se pudo hacer clic en el filtro local/visitante para {table_css_id}")
            # Considerar si continuar o retornar None
        time.sleep(1.0)
        
        page_source_updated = driver.page_source
        soup_updated = BeautifulSoup(page_source_updated, "html.parser")
        
        table = soup_updated.find("table", id=table_css_id)
        if not table: return None

        count_visible_rows = 0
        for row in table.find_all("tr", id=re.compile(rf"tr{table_css_id[-1]}_\d+")):
            if row.get("style") and "display:none" in row.get("style","").lower():
                continue
            
            count_visible_rows +=1
            if count_visible_rows > 15: break # Limitar búsqueda

            if league_id_filter and row.get("name") != str(league_id_filter): continue
            
            tds = row.find_all("td")
            if len(tds) < 14: continue

            home_team_row_el = tds[2].find("a")
            away_team_row_el = tds[4].find("a")
            
            if not home_team_row_el or not away_team_row_el: continue

            home_team_row_name = home_team_row_el.text.strip()
            away_team_row_name = away_team_row_el.text.strip()
            
            team_is_home_in_row = main_team_name.lower() == home_team_row_name.lower()
            team_is_away_in_row = main_team_name.lower() == away_team_row_name.lower()

            if (is_main_team_home_in_history_filter and team_is_home_in_row) or \
               (not is_main_team_home_in_history_filter and team_is_away_in_row):
                
                date_span = tds[1].find("span", {"name": "timeData"})
                date_str = date_span.text.strip() if date_span else "N/A"
                
                score_class_re = re.compile(r"fscore_")
                score_span = tds[3].find("span", class_=score_class_re)
                score_str = score_span.text.strip() if score_span else "N/A"
                
                handicap_cell = tds[11]
                handicap_raw = handicap_cell.get("data-o", handicap_cell.text.strip())
                handicap_raw = handicap_raw.strip() if handicap_raw and handicap_raw.strip() not in ["", "-"] else "N/A"
                
                return {
                    "date": date_str, 
                    "home_team": home_team_row_name, 
                    "away_team": away_team_row_name,
                    "score": score_str,
                    "handicap_line_raw": handicap_raw
                }
        return None # No se encontró partido coincidente
    except Exception as e:
        st.warning(f"❗ Error al extraer último partido en liga para {main_team_name}: {type(e).__name__} - {e}")
        return None

def get_main_match_odds_selenium(driver: webdriver.Chrome) -> dict:
    odds_info = {
        "ah_home_cuota": "N/A", "ah_linea_raw": "N/A", "ah_away_cuota": "N/A",
        "goals_over_cuota": "N/A", "goals_linea_raw": "N/A", "goals_under_cuota": "N/A"
    }
    if not driver: return odds_info # Chequeo robusto
    try:
        live_compare_div = WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS, poll_frequency=SELENIUM_POLL_FREQUENCY).until(
            EC.presence_of_element_located((By.ID, "liveCompareDiv"))
        )
        bet365_row_selector = "tr#tr_o_1_8[name='earlyOdds']" # Bet365 ID
        bet365_row_selector_alt = "tr#tr_o_1_31[name='earlyOdds']" # Otro ID común para Bet365
        
        table_odds_container = live_compare_div.find_element(By.XPATH, ".//table[contains(@class, 'team-table-other')]/parent::div")
        driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", table_odds_container) # Scroll hasta el final del div
        time.sleep(0.5)

        bet365_early_odds_row = None
        try:
            bet365_early_odds_row = WebDriverWait(driver, 5, poll_frequency=SELENIUM_POLL_FREQUENCY).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, bet365_row_selector))
            )
        except TimeoutException:
            try:
                bet365_early_odds_row = WebDriverWait(driver, 3, poll_frequency=SELENIUM_POLL_FREQUENCY).until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, bet365_row_selector_alt))
                )
            except TimeoutException:
                return odds_info # No se encontró Bet365

        tds = bet365_early_odds_row.find_elements(By.TAG_NAME, "td")
        if len(tds) >= 11: # Columnas de Bet365
            odds_info["ah_home_cuota"] = (tds[2].get_attribute("data-o") or tds[2].text.strip() or "N/A").strip()
            odds_info["ah_linea_raw"] = (tds[3].get_attribute("data-o") or tds[3].text.strip() or "N/A").strip()
            odds_info["ah_away_cuota"] = (tds[4].get_attribute("data-o") or tds[4].text.strip() or "N/A").strip()
            odds_info["goals_over_cuota"] = (tds[8].get_attribute("data-o") or tds[8].text.strip() or "N/A").strip()
            odds_info["goals_linea_raw"] = (tds[9].get_attribute("data-o") or tds[9].text.strip() or "N/A").strip()
            odds_info["goals_under_cuota"] = (tds[10].get_attribute("data-o") or tds[10].text.strip() or "N/A").strip()
            
    except Exception as e:
        st.warning(f"❗ Error al extraer cuotas Bet365 con Selenium: {type(e).__name__}. Datos podrían estar incompletos.")
    return odds_info

def extract_standings_data_from_h2h_page(h2h_soup: BeautifulSoup, target_team_name_exact: str) -> dict:
    data = {
        "name": "N/A", "ranking": "N/A",
        "total_pj": "N/A", "total_v": "N/A", "total_e": "N/A", "total_d": "N/A", "total_gf": "N/A", "total_gc": "N/A",
        "specific_pj": "N/A", "specific_v": "N/A", "specific_e": "N/A", "specific_d": "N/A", "specific_gf": "N/A", "specific_gc": "N/A",
        "specific_type": "N/A"
    }
    if not h2h_soup or not target_team_name_exact or target_team_name_exact == "N/A": return data

    standings_section = h2h_soup.find("div", id="porletP4")
    if not standings_section: return data

    team_table_soup = None
    is_home_team_table_type = False

    home_div_standings = standings_section.find("div", class_="home-div")
    if home_div_standings:
        home_table_header = home_div_standings.find("tr", class_="team-home")
        if home_table_header and target_team_name_exact.lower() in home_table_header.get_text(strip=True).lower():
            team_table_soup = home_div_standings.find("table", class_="team-table-home")
            is_home_team_table_type = True
            specific_type_td = home_div_standings.find("td", class_="bg1")
            data["specific_type"] = specific_type_td.text.strip() if specific_type_td else "En Casa"

    if not team_table_soup:
        guest_div_standings = standings_section.find("div", class_="guest-div")
        if guest_div_standings:
            guest_table_header = guest_div_standings.find("tr", class_="team-guest")
            if guest_table_header and target_team_name_exact.lower() in guest_table_header.get_text(strip=True).lower():
                team_table_soup = guest_div_standings.find("table", class_="team-table-guest")
                is_home_team_table_type = False # Ya es visitante
                specific_type_td = guest_div_standings.find("td", class_="bg1")
                data["specific_type"] = specific_type_td.text.strip() if specific_type_td else "Fuera"
    
    if not team_table_soup: return data

    header_row_found = team_table_soup.find("tr", class_=re.compile(r"team-(home|guest)"))
    if header_row_found:
        link = header_row_found.find("a")
        text_content = link.get_text(separator=" ", strip=True) if link else header_row_found.get_text(separator=" ", strip=True)
        
        name_match = re.search(r"]\s*(.*)", text_content)
        rank_match = re.search(r"\[(?:[^\]]+-)?(\d+)\]", text_content)

        if name_match: data["name"] = name_match.group(1).strip()
        if rank_match: data["ranking"] = rank_match.group(1)
        
    ft_rows = []
    current_section = None

    for row in team_table_soup.find_all("tr", align="center"):
        th_cell = row.find("th")
        if th_cell:
            if "FT" in th_cell.get_text(strip=True): current_section = "FT"
            elif "HT" in th_cell.get_text(strip=True): break # Solo nos interesa FT
        
        if current_section == "FT":
            cells = row.find_all("td")
            if cells and len(cells) > 0 and cells[0].get_text(strip=True) in ["Total", "Home", "Away"]:
                ft_rows.append(cells)
    
    for cells in ft_rows:
        if len(cells) > 8: # PJ, V, E, D, GF, GC, Pts, %V (son 8 hasta Pts)
            row_type_text = cells[0].get_text(strip=True)
            # Columnas 1 a 6 son PJ, V, E, D, GF, GC
            pj, v, e, d, gf, gc = (cells[i].get_text(strip=True) or "N/A" for i in range(1, 7))

            if row_type_text == "Total":
                data["total_pj"], data["total_v"], data["total_e"], data["total_d"], data["total_gf"], data["total_gc"] = pj, v, e, d, gf, gc
            elif row_type_text == "Home" and is_home_team_table_type: # Equipo principal es local, y esta es su fila "Home"
                data["specific_pj"], data["specific_v"], data["specific_e"], data["specific_d"], data["specific_gf"], data["specific_gc"] = pj, v, e, d, gf, gc
            elif row_type_text == "Away" and not is_home_team_table_type: # Equipo principal es visitante, y esta es su fila "Away"
                data["specific_pj"], data["specific_v"], data["specific_e"], data["specific_d"], data["specific_gf"], data["specific_gc"] = pj, v, e, d, gf, gc
    
    data["name"] = data["name"] if data["name"] != "N/A" else target_team_name_exact
    return data

def extract_final_score(soup: BeautifulSoup) -> tuple[str, str]:
    if not soup: return '?*?', "?-?"
    try:
        score_divs = soup.select('#mScore .end .score')
        if len(score_divs) == 2:
            home_score_str = score_divs[0].text.strip()
            away_score_str = score_divs[1].text.strip()
            if home_score_str.isdigit() and away_score_str.isdigit():
                return f"{home_score_str}*{away_score_str}", f"{home_score_str}-{away_score_str}"
    except Exception: # Ser genérico para cualquier error de parsing
        pass
    return '?*?', "?-?"

def extract_h2h_data(soup: BeautifulSoup, main_home_team_name: str, main_away_team_name: str, current_league_id: str) -> dict:
    data = {
        'ah_h2h_exact_fmt': '-', 'score_h2h_exact_fmt': '?*?', 'score_h2h_exact_raw': '?-?',
        'ah_h2h_general_fmt': '-', 'score_h2h_general_fmt': '?*?', 'score_h2h_general_raw': '?-?'
    }
    if not soup: return data
    h2h_table = soup.find("table", id="table_v3")
    if not h2h_table: return data

    filtered_h2h_list = []
    if not main_home_team_name or main_home_team_name == "N/A" or \
       not main_away_team_name or main_away_team_name == "N/A": 
        return data

    for row_h2h in h2h_table.find_all("tr", id=re.compile(r"tr3_\d+")):
        details = get_match_details_from_row(row_h2h, score_class_selector='fscore_3')
        if not details: continue
        if current_league_id and details.get('league_id_hist') and details.get('league_id_hist') != str(current_league_id):
            continue
        filtered_h2h_list.append(details)
    
    if not filtered_h2h_list: return data

    h2h_general_match = filtered_h2h_list[0] # El más reciente sin importar localía
    data['ah_h2h_general_fmt'] = h2h_general_match.get('ahLine', '-')
    data['score_h2h_general_fmt'] = h2h_general_match.get('score', '?*?')
    data['score_h2h_general_raw'] = h2h_general_match.get('score_raw', '?-?')
    
    h2h_local_specific_match = None
    for h2h_detail in filtered_h2h_list:
        # El equipo local de HOY debe ser el local en el H2H
        if h2h_detail.get('home','').lower() == main_home_team_name.lower() and \
           h2h_detail.get('away','').lower() == main_away_team_name.lower():
            h2h_local_specific_match = h2h_detail
            break # Encontrado el H2H más reciente con el local de hoy en casa
            
    if h2h_local_specific_match:
        data['ah_h2h_exact_fmt'] = h2h_local_specific_match.get('ahLine', '-')
        data['score_h2h_exact_fmt'] = h2h_local_specific_match.get('score', '?*?')
        data['score_h2h_exact_raw'] = h2h_local_specific_match.get('score_raw', '?-?')
        
    return data

def extract_comparative_match(soup_for_team_history: BeautifulSoup, table_id_of_team_to_search: str, 
                             team_name_to_find_match_for: str, opponent_name_to_search: str, 
                             current_league_id: str, is_home_table: bool) -> dict | None:
    if not soup_for_team_history or \
       not opponent_name_to_search or opponent_name_to_search == "N/A" or \
       not team_name_to_find_match_for or team_name_to_find_match_for == "N/A":
        return None
    
    table = soup_for_team_history.find("table", id=table_id_of_team_to_search)
    if not table: return None

    score_class_selector = 'fscore_1' if is_home_table else 'fscore_2'
    
    for row in table.find_all("tr", id=re.compile(rf"tr{table_id_of_team_to_search[-1]}_\d+")):
        # Saltar filas ocultas por filtros de JS (si aplica, style="display:none")
        if row.get("style") and "display:none" in row.get("style","").lower():
            continue

        details = get_match_details_from_row(row, score_class_selector=score_class_selector)
        if not details: continue
        
        if current_league_id and details.get('league_id_hist') and details.get('league_id_hist') != str(current_league_id):
            continue
            
        home_hist_lower = details.get('home','').lower()
        away_hist_lower = details.get('away','').lower()
        
        team_main_lower = team_name_to_find_match_for.lower()
        opponent_lower = opponent_name_to_search.lower()

        if (team_main_lower == home_hist_lower and opponent_lower == away_hist_lower) or \
           (team_main_lower == away_hist_lower and opponent_lower == home_hist_lower):
            
            score = details.get('score', '?*?')
            ah_line_extracted = details.get('ahLine', '-')
            localia = 'H' if team_main_lower == home_hist_lower else 'A'
            
            return {"score": score, "ah_line": ah_line_extracted, "localia": localia}
    
    return None

# --- HELPER DE INTERFAZ DE STREAMLIT ---
def _display_team_standings_section(st_col: st.delta_generator.DeltaGenerator, team_name: str, standings_data: dict):
    st_col.subheader(f"📊 {team_name if team_name and team_name != 'N/A' else 'Equipo Local/Visitante'}")
    if standings_data and standings_data.get("name", "N/A") != "N/A":
        sd = standings_data
        st_col.markdown(f"- **Ranking:** {sd.get('ranking', 'N/A')}\n"
                         f"- **Total:** {sd.get('total_pj', 'N/A')} PJ | {sd.get('total_v', 'N/A')}V-{sd.get('total_e', 'N/A')}E-{sd.get('total_d', 'N/A')}D | GF: {sd.get('total_gf', 'N/A')}, GC: {sd.get('total_gc', 'N/A')}\n"
                         f"- **{sd.get('specific_type','Posición')}:** {sd.get('specific_pj', 'N/A')} PJ | {sd.get('specific_v', 'N/A')}V-{sd.get('specific_e', 'N/A')}E-{sd.get('specific_d', 'N/A')}D | GF: {sd.get('specific_gf', 'N/A')}, GC: {sd.get('specific_gc', 'N/A')}")
    else:
        st_col.info(f"Clasificación no disponible para {team_name if team_name and team_name != 'N/A' else 'este equipo'}.")

def _display_last_match_section(st_col: st.delta_generator.DeltaGenerator, team_type: str, match_data: dict | None, home_name: str, away_name: str): # match_data puede ser None
    team_name_display = home_name if team_type == 'home' else away_name
    team_name_display = team_name_display if team_name_display and team_name_display != "N/A" else ('Local' if team_type == 'home' else 'Visitante')

    st_col.markdown(f"##### {'🏡' if team_type == 'home' else '✈️'} Últ. {team_name_display} ({'Casa' if team_type == 'home' else 'Fuera'})")
    if match_data:
        res = match_data
        opponent_name = res['away_team'] if team_type == 'home' else res['home_team']
        st_col.markdown(f"**vs.** `{opponent_name}`\n\n**{res['home_team']}** `{res['score'].replace('-',':')}` **{res['away_team']}**")
        st_col.markdown(f"**AH:** <span style='font-weight:bold;'>`{format_ah_as_decimal_string(res.get('handicap_line_raw','-'))}`</span>", unsafe_allow_html=True)
        st_col.caption(f"📅 {res['date']}")
    else:
        st_col.info(f"No encontrado o no aplicable.")

def _display_h2h_col3_section(st_col: st.delta_generator.DeltaGenerator, driver: webdriver.Chrome | None, # Driver puede ser None
                                 key_match_id: str | None, rival_a_id: str | None, rival_b_id: str | None, 
                                 rival_a_name: str | None, rival_b_name: str | None):
    rival_a_display = rival_a_name if rival_a_name and rival_a_name != "N/A" else "Rival A"
    rival_b_display = rival_b_name if rival_b_name and rival_b_name != "N/A" else "Rival B"

    st_col.markdown(f"##### ⚔️ H2H entre Oponentes ({rival_a_display} vs {rival_b_display})")
    details_h2h = {"status": "error", "message": "N/A (Datos insuficientes o driver no disponible)"}
    
    if key_match_id and rival_a_id and rival_b_id and driver:
        with st_col.status(f"Buscando H2H: `{rival_a_display}` vs `{rival_b_display}`...", expanded=False) as status_h2h_col3:
            try:
                details_h2h = get_h2h_details_for_rival_teams(driver, key_match_id, rival_a_id, rival_b_id, rival_a_display, rival_b_display)
                if details_h2h.get("status") == "found":
                    status_h2h_col3.update(label=f"H2H encontrado", state="complete", icon="✅")
                else:
                    status_h2h_col3.update(label=f"H2H no encontrado: {details_h2h.get('message', '')[:50]}...", state="warning", icon="⚠️") # Mensaje más corto
            except Exception as e_h2h_col3:
                status_h2h_col3.update(label=f"Error H2H Col3: {type(e_h2h_col3).__name__}", state="error", icon="❌")
                details_h2h = {"status": "error", "message": f"Excepción: {e_h2h_col3}"}


    if details_h2h.get("status") == "found":
        res_h2h = details_h2h
        st_col.markdown(f"**{res_h2h.get('h2h_home_team_name')}** `{res_h2h.get('goles_home')}:{res_h2h.get('goles_away')}` **{res_h2h.get('h2h_away_team_name')}**")
        st_col.markdown(f"(**AH:** `{format_ah_as_decimal_string(res_h2h.get('handicap_raw','-'))}`)")
    else:
        st_col.info(details_h2h.get('message', "H2H de oponentes no disponible o no aplicable."))

def _display_opponent_standings_expander(rival_a_standings: dict, rival_b_standings: dict, rival_a_name_display: str, rival_b_name_display: str):
    with st.expander("🔎 Clasificación Oponentes (H2H Comparado)"):
        opp_stand_col1, opp_stand_col2 = st.columns(2)
        
        rival_a_display_final = rival_a_standings.get('name') if rival_a_standings and rival_a_standings.get('name',"N/A") != "N/A" else rival_a_name_display
        rival_b_display_final = rival_b_standings.get('name') if rival_b_standings and rival_b_standings.get('name',"N/A") != "N/A" else rival_b_name_display
        
        with opp_stand_col1:
            st.markdown(f"###### {rival_a_display_final or 'Rival A'}")
            if rival_a_standings and rival_a_standings.get("name", "N/A") != "N/A":
                rst = rival_a_standings
                st.caption(f"🏆 Rk: {rst.get('ranking','N/A')}\n"
                           f"🌍 T: {rst.get('total_pj','N/A')}|{rst.get('total_v','N/A')}/{rst.get('total_e','N/A')}/{rst.get('total_d','N/A')}|{rst.get('total_gf','N/A')}-{rst.get('total_gc','N/A')}\n"
                           f"🏟️ {rst.get('specific_type','En Casa/Fuera')}: {rst.get('specific_pj','N/A')}|{rst.get('specific_v','N/A')}/{rst.get('specific_e','N/A')}/{rst.get('specific_d','N/A')}|{rst.get('specific_gf','N/A')}-{rst.get('specific_gc','N/A')}")
            else:
                st.caption("No disponible.")
        with opp_stand_col2:
            st.markdown(f"###### {rival_b_display_final or 'Rival B'}")
            if rival_b_standings and rival_b_standings.get("name", "N/A") != "N/A":
                rst = rival_b_standings
                st.caption(f"🏆 Rk: {rst.get('ranking','N/A')}\n"
                           f"🌍 T: {rst.get('total_pj','N/A')}|{rst.get('total_v','N/A')}/{rst.get('total_e','N/A')}/{rst.get('total_d','N/A')}|{rst.get('total_gf','N/A')}-{rst.get('total_gc','N/A')}\n"
                           f"🏟️ {rst.get('specific_type','En Casa/Fuera')}: {rst.get('specific_pj','N/A')}|{rst.get('specific_v','N/A')}/{rst.get('specific_e','N/A')}/{rst.get('specific_d','N/A')}|{rst.get('specific_gf','N/A')}-{rst.get('specific_gc','N/A')}")
            else:
                st.caption("No disponible.")

def _display_indirect_comparative(st_col: st.delta_generator.DeltaGenerator, title: str, comparative_data: dict | None):
    st_col.markdown(title, unsafe_allow_html=True)
    if comparative_data:
        score_part = comparative_data['score'].replace('*', ':')
        ah_val = comparative_data['ah_line']
        loc_val = comparative_data['localia']
        st_col.markdown(f"⚽ **Resultado:** `{score_part or '(No disponible)'}`")
        st_col.markdown(f"⚖️ **AH Partido Comparado:** `{ah_val or '(No disponible)'}`")
        st_col.markdown(f"🏟️ **Localía en ese partido:** `{loc_val or '(No disponible)'}`")
    else:
        st_col.info("Comparativa no disponible o no aplicable.")

# --- STREAMLIT APP UI (Función principal limpia) ---
def display_other_feature_ui():
    st.header("⚽ Herramienta de Análisis Avanzado de Partidos")
    st.markdown("Esta herramienta te permite obtener estadísticas detalladas y el contexto H2H para un partido específico de Nowgoal. 🎉")
    st.divider()

    st.sidebar.title("⚙️ Configuración del Partido (Avanzado)")
    main_match_id_str_input = st.sidebar.text_input(
        "🆔 ID del Partido Principal (Avanzado):", 
        value="2696131", 
        help="Pega el ID numérico del partido que deseas analizar. Ej: `2696131`", 
        key="other_feature_match_id_input_adv"
    )
    analizar_button = st.sidebar.button(
        "🚀 Analizar Partido (Avanzado)", 
        type="primary", 
        use_container_width=True, 
        key="other_feature_analizar_button_adv",
        disabled=st.session_state.get('analysis_in_progress_adv', False) # Deshabilitar si ya está en progreso
    )

    results_container = st.container()

    if 'selenium_driver_other_feature_adv' not in st.session_state: 
        st.session_state.selenium_driver_other_feature_adv = None
    if 'analysis_in_progress_adv' not in st.session_state:
        st.session_state.analysis_in_progress_adv = False


    if analizar_button: # No necesitamos chequear analysis_in_progress_adv aquí por el 'disabled'
        st.session_state.analysis_in_progress_adv = True
        st.rerun() # Para que el botón se deshabilite inmediatamente

    if st.session_state.analysis_in_progress_adv and not analizar_button: # Entra aquí después del rerun si el análisis se disparó
        results_container.empty()
        match_id_to_process = None

        if main_match_id_str_input: # Tomar el valor actual del input
            try:
                cleaned_id_str = "".join(filter(str.isdigit, main_match_id_str_input))
                if cleaned_id_str: 
                    match_id_to_process = int(cleaned_id_str)
            except ValueError: 
                results_container.error("⚠️ ID de partido no válido. Por favor, introduce solo números.")
                st.session_state.analysis_in_progress_adv = False
                st.rerun() # Para habilitar el botón de nuevo y limpiar el estado
                st.stop()
        
        if not match_id_to_process: 
            results_container.warning("⚠️ Ingresa un ID de partido válido para comenzar el análisis.")
            st.session_state.analysis_in_progress_adv = False
            st.rerun()
            st.stop()
        
        start_time = time.time()
        with results_container:
            with st.status("Preparando análisis... Obteniendo datos iniciales...", expanded=True) as status_initial:
                try:
                    main_page_url_h2h_view = f"/match/h2h-{match_id_to_process}"
                    
                    soup_main_h2h_page = fetch_soup_requests(main_page_url_h2h_view)
                    if not soup_main_h2h_page:
                        status_initial.update(label="Error al cargar la página principal H2H", state="error", icon="❌")
                        st.error("❌ No se pudo obtener la página H2H principal. Verifica el ID del partido o la conectividad.")
                        st.session_state.analysis_in_progress_adv = False
                        st.rerun()
                        st.stop()
                    
                    mp_home_id, mp_away_id, mp_league_id, mp_home_name_script, mp_away_name_script, mp_league_name = get_team_league_info_from_script(soup_main_h2h_page)
                    
                    home_team_main_standings = extract_standings_data_from_h2h_page(soup_main_h2h_page, mp_home_name_script)
                    away_team_main_standings = extract_standings_data_from_h2h_page(soup_main_h2h_page, mp_away_name_script)
                    
                    display_home_name = home_team_main_standings.get("name", mp_home_name_script) if home_team_main_standings.get("name", "N/A") != "N/A" else mp_home_name_script
                    display_away_name = away_team_main_standings.get("name", mp_away_name_script) if away_team_main_standings.get("name", "N/A") != "N/A" else mp_away_name_script

                    h2h_main_teams_data = extract_h2h_data(soup_main_h2h_page, display_home_name, display_away_name, mp_league_id)
                    
                    key_match_id_rival_a_h2h, rival_a_id_col3, rival_a_name_col3 = get_rival_info_from_h2h_table(soup_main_h2h_page, "table_v1", r"tr1_\d+", 1)
                    match_id_rival_b_game_ref, rival_b_id_col3, rival_b_name_col3 = get_rival_info_from_h2h_table(soup_main_h2h_page, "table_v2", r"tr2_\d+", 0)
                    
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

                    status_initial.update(label="Datos iniciales y H2H extraídos. Iniciando Selenium...", state="running", icon="🛠️")

                except Exception as e_initial_data:
                    status_initial.update(label=f"Error datos iniciales: {type(e_initial_data).__name__}", state="error", icon="❌")
                    st.error(f"Ocurrió un error inesperado al procesar los datos iniciales: {e_initial_data}")
                    # st.error(traceback.format_exc()) # Descomentar para depuración detallada
                    st.session_state.analysis_in_progress_adv = False
                    st.rerun()
                    st.stop()
            
            # --- Lógica de Selenium ---
            driver = st.session_state.selenium_driver_other_feature_adv
            driver_needs_init = False
            
            if driver is None:
                driver_needs_init = True
            else:
                try:
                    _ = driver.window_handles
                    _ = driver.current_url # Operación simple para verificar
                except WebDriverException:
                    driver_needs_init = True
                except Exception: # Otras excepciones genéricas
                    driver_needs_init = True
                    st.warning("Se intentará reiniciar el WebDriver debido a un problema.")

            if driver_needs_init:
                if driver is not None:
                    try: driver.quit()
                    except: pass
                with st.spinner("🚀 Inicializando WebDriver de Selenium (esto puede tardar)..."):
                    driver = get_selenium_driver()
                st.session_state.selenium_driver_other_feature_adv = driver

            main_match_odds_data = {}
            last_home_match_in_league = None
            last_away_match_in_league = None
            
            if driver:
                with st.status("Obteniendo cuotas y últimos partidos (con Selenium)...", expanded=True) as status_selenium:
                    try:
                        driver.get(f"{BASE_URL}{main_page_url_h2h_view}") 
                        WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS).until(EC.presence_of_element_located((By.ID, "table_v1"))) 
                        time.sleep(0.8)
                        
                        main_match_odds_data = get_main_match_odds_selenium(driver)
                        
                        if mp_home_id and mp_league_id and display_home_name and display_home_name != "N/A":
                             last_home_match_in_league = extract_last_match_in_league(driver, "table_v1", display_home_name, mp_league_id, "input#cb_sos1[value='1']", is_main_team_home_in_history_filter=True)
                        if mp_away_id and mp_league_id and display_away_name and display_away_name != "N/A":
                            last_away_match_in_league = extract_last_match_in_league(driver, "table_v2", display_away_name, mp_league_id, "input#cb_sos2[value='2']", is_main_team_home_in_history_filter=False)
                        
                        status_selenium.update(label="Cuotas y últimos partidos extraídos. ✨", state="complete", icon="✅")

                    except Exception as e_main_sel:
                        status_selenium.update(label=f"Error Selenium: {type(e_main_sel).__name__}", state="error", icon="❌")
                        st.error(f"❗ Error al usar Selenium: {type(e_main_sel).__name__}. {e_main_sel}")
            else:
                st.warning("❗ WebDriver de Selenium no pudo ser inicializado. Algunas características (cuotas, últimos partidos, H2H Col3) no estarán disponibles.")
                # No actualizamos status_initial aquí porque ya terminó ese bloque
            
            # --- Consolidar y Preparar Datos para la Visualización ---
            final_score_fmt, _ = extract_final_score(soup_main_h2h_page)

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
            
            st.header("⚡ Rendimiento Reciente y H2H")
            
            col_last_home, col_last_away, col_h2h_rival_opp = st.columns(3)
            _display_last_match_section(col_last_home, 'home', last_home_match_in_league, display_home_name, display_away_name)
            _display_last_match_section(col_last_away, 'away', last_away_match_in_league, display_home_name, display_away_name)
            _display_h2h_col3_section(col_h2h_rival_opp, driver, key_match_id_rival_a_h2h, rival_a_id_col3, rival_b_id_col3, rival_a_name_col3, rival_b_name_col3)

            _display_opponent_standings_expander(rival_a_standings, rival_b_standings, 
                                                rival_a_name_col3 or "Rival A",
                                                rival_b_name_col3 or "Rival B")
            
            with st.expander("🤝 Enfrentamientos Directos", expanded=True):
                h2h_col1, h2h_col2, h2h_col3, h2h_col4 = st.columns(4)
                h2h_col1.metric("AH H2H (Local Casa)", h2h_main_teams_data.get('ah_h2h_exact_fmt','-'))
                h2h_col2.metric("Res. H2H (Local Casa)", h2h_main_teams_data.get('score_h2h_exact_fmt','?*?').replace("*", ":"))
                h2h_col3.metric("AH H2H (General)", h2h_main_teams_data.get('ah_h2h_general_fmt','-'))
                h2h_col4.metric("Res. H2H (General)", h2h_main_teams_data.get('score_h2h_general_fmt','?*?').replace("*", ":"))

            st.divider()

            st.header("🔁 Comparativas Indirectas")
            comp_col1, comp_col2 = st.columns(2)
            
            _display_indirect_comparative(comp_col1, 
                                        f"**<span style='color: #1E90FF;'>🏠 {display_home_name or 'Local'}</span> vs. <span style='color: #FF4500;'>Últ. Rival de {display_away_name or 'Visitante'}</span>**",
                                        comparative_L_vs_UVA)
            
            _display_indirect_comparative(comp_col2, 
                                        f"**<span style='color: #FF4500;'>✈️ {display_away_name or 'Visitante'}</span> vs. <span style='color: #1E90FF;'>Últ. Rival de {display_home_name or 'Local'}</span>**",
                                        comparative_V_vs_ULH)
            
            st.divider()

            st.header("ℹ️ Resumen de Datos Clave del Partido")
            info_col1, info_col2, info_col3 = st.columns(3)
            info_col1.metric("Línea Goles Partido (Actual)", format_ah_as_decimal_string(main_match_odds_data.get('goals_linea_raw', '?')))
            info_col2.metric("Liga del Partido", mp_league_name or "N/A")
            info_col3.metric("ID Partido Actual", str(match_id_to_process))

            st.divider()

            end_time = time.time()
            st.sidebar.success(f"⏱️ Análisis (Avanzado) completado en {end_time - start_time:.2f} segundos.")
        
        st.session_state.analysis_in_progress_adv = False # Restablecer el flag AL FINAL
        st.rerun() # Para actualizar el estado del botón de análisis y limpiar spinners/status

    elif not st.session_state.analysis_in_progress_adv: # Si no está en progreso y el botón no fue presionado esta vez
         results_container.info("✨ ¡Listo para el análisis avanzado! Ingresa un ID de partido y haz clic en 'Analizar Partido (Avanzado)'.")
