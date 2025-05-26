# modules/other_feature.py
import streamlit as st
import time
import requests
import re
import math # Añadido para format_ah_as_decimal_string_of
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

# --- CONFIGURACIÓN GLOBAL (renombrada para evitar conflictos) ---
BASE_URL_OF = "https://live18.nowgoal25.com" # Asegúrate que este es el dominio correcto, el original era live16
SELENIUM_TIMEOUT_SECONDS_OF = 20
SELENIUM_POLL_FREQUENCY_OF = 0.2

# --- FUNCIONES HELPER ADAPTADAS DE Eldefinitivo.txt ---
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
            # Ajuste para casos como "0/-0.5" o "-0/0.5" donde el signo se aplica a ambos
            if val1 < 0 and not p2_str.startswith('-') and val2 > 0: # ej: -0.5/1 -> -0.5/-1 (no es usual, pero por si acaso)
                 val2 = -abs(val2)
            elif original_starts_with_minus and val1 == 0.0 and \
                 (p1_str == "0" or p1_str == "-0") and \
                 not p2_str.startswith('-') and val2 > 0: # ej: -0/0.5 -> 0/-0.5
                val2 = -abs(val2)
            return (val1 + val2) / 2.0
        else:
            return float(s)
    except ValueError:
        return None

def format_ah_as_decimal_string_of(ah_line_str: str, for_sheets=False):
    if not isinstance(ah_line_str, str) or not ah_line_str.strip() or ah_line_str.strip() in ['-', '?']:
        return ah_line_str.strip() if isinstance(ah_line_str, str) else '-'
    
    numeric_value = parse_ah_to_number_of(ah_line_str)
    if numeric_value is None:
        return ah_line_str.strip() if isinstance(ah_line_str, str) else '-' # Devuelve el original si no se puede parsear

    if numeric_value == 0.0:
        return "0"

    # Lógica de redondeo de Eldefinitivo.txt: 0.25 -> 0.5, 0.75 -> 0.5 (esto es inusual, normalmente sería 0.25->0.25, 0.75->0.75 o redondear al .0 o .5 más cercano)
    # Voy a aplicar el redondeo a .0 o .5 como es más estándar para hándicaps
    # Si realmente necesitas el redondeo 0.25->0.5 y 0.75->0.5, la lógica original de Eldefinitivo.txt debe ser replicada aquí.
    # Por ahora, redondearé a 1 decimal, que suele ser .0 o .5 para hándicaps.
    
    # Lógica original de Eldefinitivo para redondeo específico:
    sign = -1 if numeric_value < 0 else 1
    abs_num = abs(numeric_value)
    parte_entera = math.floor(abs_num)
    parte_decimal_original = round(abs_num - parte_entera, 4) # Usar round para evitar imprecisiones de float
    
    # Esta es la parte que convierte .25 y .75 a .5
    # Si quieres que -0.25 sea -0.5 y -0.75 sea -0.5:
    # epsilon = 1e-9
    # if abs(parte_decimal_original - 0.25) < epsilon or abs(parte_decimal_original - 0.75) < epsilon:
    #     nueva_parte_decimal = 0.5
    # else: # Para 0.0 o 0.5, mantenerlos
    #     if abs(parte_decimal_original - 0.0) < epsilon or abs(parte_decimal_original - 0.5) < epsilon:
    #       nueva_parte_decimal = parte_decimal_original
    #     else: # Otros decimales (ej 0.1, 0.3) - ¿cómo se manejan? El original no los consideraba.
    #           # Por ahora, los dejaré como están si no son 0, .25, .5, .75
    #       nueva_parte_decimal = parte_decimal_original
    # resultado_num_redondeado = parte_entera + nueva_parte_decimal
    # final_value_signed = sign * resultado_num_redondeado
    
    # Implementando un redondeo más estándar a X.0 o X.5
    mod_val = abs_num % 1
    if mod_val < 0.25:
        abs_rounded = math.floor(abs_num) # X.0
    elif mod_val < 0.75:
        abs_rounded = math.floor(abs_num) + 0.5 # X.5
    else:
        abs_rounded = math.ceil(abs_num) # (X+1).0
    
    final_value_signed = sign * abs_rounded

    if final_value_signed == 0.0: # Re-chequeo por si el redondeo lleva a cero
        output_str = "0"
    elif abs(final_value_signed - round(final_value_signed, 0)) < 1e-9 : # Es un entero
        output_str = str(int(round(final_value_signed, 0)))
    else: # Es X.5
        output_str = f"{final_value_signed:.1f}" # ej: -2.5, 0.5

    if for_sheets: # Para Google Sheets, reemplazar punto por coma y añadir apóstrofo
        return "'" + output_str.replace('.', ',') if output_str not in ['-','?'] else output_str
    return output_str

def get_match_details_from_row_of(row_element, score_class_selector='score', source_table_type='h2h'):
    # score_class_selector: 'fscore_3' para H2H (table_v3), 'fscore_1' para Local (table_v1), 'fscore_2' para Visitante (table_v2)
    try:
        cells = row_element.find_all('td')
        if len(cells) < 12: return None

        league_id_hist_attr = row_element.get('name') # 'name' contiene el leagueid en tr1_, tr2_, tr3_
        
        # Índices de celdas para los datos comunes
        # En table_v1 (local hist): home_idx=2, score_idx=3, away_idx=4, ah_idx=11 (12ª celda)
        # En table_v2 (visit hist): home_idx=2, score_idx=3, away_idx=4, ah_idx=11
        # En table_v3 (h2h hist):   home_idx=2, score_idx=3, away_idx=4, ah_idx=11
        home_idx, score_idx, away_idx, ah_idx = 2, 3, 4, 11

        home_tag = cells[home_idx].find('a')
        home = home_tag.text.strip() if home_tag else cells[home_idx].text.strip()
        
        away_tag = cells[away_idx].find('a')
        away = away_tag.text.strip() if away_tag else cells[away_idx].text.strip()

        score_cell_content = cells[score_idx].text.strip()
        # La clase del span del score varía: fscore_1, fscore_2, fscore_3
        score_span = cells[score_idx].find('span', class_=lambda x: x and score_class_selector in x)
        score_raw_text = score_span.text.strip() if score_span else score_cell_content
        
        score_m = re.match(r'(\d+-\d+)', score_raw_text) # Buscar el patrón N-N
        score_raw = score_m.group(1) if score_m else '?-?'
        score_fmt = score_raw.replace('-', '*') if score_raw != '?-?' else '?*?'
        
        ah_line_raw_text = cells[ah_idx].text.strip()
        ah_line_fmt = format_ah_as_decimal_string_of(ah_line_raw_text) # Usar la función de formateo

        if not home or not away: return None
        
        return {'home': home, 'away': away, 'score': score_fmt, 'score_raw': score_raw,
                'ahLine': ah_line_fmt, 'ahLine_raw': ah_line_raw_text,
                'matchIndex': row_element.get('index'), # 'index' es el match_id del partido histórico
                'vs': row_element.get('vs'), # 'vs' es '1' para el último partido en tablas de historial
                'league_id_hist': league_id_hist_attr}
    except Exception as e:
        # st.error(f"Error en get_match_details_from_row_of: {e}")
        return None

# --- FIN FUNCIONES HELPER ADAPTADAS ---


# --- FUNCIONES DE REQUESTS (renombradas) ---
@st.cache_resource
def get_requests_session_of():
    session = requests.Session()
    retries_req = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    adapter_req = HTTPAdapter(max_retries=retries_req)
    session.mount("https://", adapter_req)
    session.mount("http://", adapter_req)
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36"})
    return session

@st.cache_data(ttl=3600)
def fetch_soup_requests_of(path, max_tries=3, delay=1):
    session = get_requests_session_of()
    url = f"{BASE_URL_OF}{path}"
    for attempt in range(1, max_tries + 1):
        try:
            resp = session.get(url, timeout=10)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except requests.RequestException as e:
            if attempt == max_tries: 
                # st.error(f"Max tries ({max_tries}) en fetch_soup para {url}. Error: {e}")
                return None
            time.sleep(delay * attempt)
    return None

# --- FUNCIONES PARA LÓGICA ORIGINAL DE H2H (Columna 3) ---
# Adaptadas ESTRICTAMENTE de tu streamlit_app.py funcional
@st.cache_data(ttl=3600) 
def get_rival_a_for_original_h2h_of(main_match_id: int):
    soup_h2h_page = fetch_soup_requests_of(f"/match/h2h-{main_match_id}") 
    if not soup_h2h_page: return None, None, None # (key_match_id, rival_id, rival_name)
    
    table = soup_h2h_page.find("table", id="table_v1") 
    if not table: return None, None, None
    
    for row in table.find_all("tr", id=re.compile(r"tr1_\d+")):
        if row.get("vs") == "1": # Condición clave de tu script funcional
            key_match_id_for_h2h_url = row.get("index") 
            if not key_match_id_for_h2h_url: continue
            
            onclicks = row.find_all("a", onclick=True) # En tu script: onclick=True
            if len(onclicks) > 1 and onclicks[1].get("onclick"): # Tu script toma onclicks[1]
                rival_tag = onclicks[1]
                rival_a_id_match = re.search(r"team\((\d+)\)", rival_tag.get("onclick", ""))
                rival_a_name = rival_tag.text.strip()
                if rival_a_id_match and rival_a_name:
                    return key_match_id_for_h2h_url, rival_a_id_match.group(1), rival_a_name
    return None, None, None

@st.cache_data(ttl=3600)
def get_rival_b_for_original_h2h_of(main_match_id: int): 
    soup_h2h_page = fetch_soup_requests_of(f"/match/h2h-{main_match_id}") 
    if not soup_h2h_page: return None, None, None # (match_id_ref, rival_id, rival_name)
    
    table = soup_h2h_page.find("table", id="table_v2") 
    if not table: return None, None, None
    
    for row in table.find_all("tr", id=re.compile(r"tr2_\d+")):
        if row.get("vs") == "1": # Condición clave de tu script funcional
            match_id_of_rival_b_game = row.get("index") # Necesitamos este para buscar standings del Rival B
            if not match_id_of_rival_b_game: continue

            onclicks = row.find_all("a", onclick=True) # En tu script: onclick=True
            if len(onclicks) > 0 and onclicks[0].get("onclick"): # Tu script toma onclicks[0]
                rival_tag = onclicks[0]
                rival_b_id_match = re.search(r"team\((\d+)\)", rival_tag.get("onclick", ""))
                rival_b_name = rival_tag.text.strip() 
                if rival_b_id_match and rival_b_name:
                    # Devolvemos el ID del partido donde se encontró a Rival B, el ID de Rival B y su nombre
                    return match_id_of_rival_b_game, rival_b_id_match.group(1), rival_b_name
    return None, None, None

# --- FUNCIONES DE SELENIUM (renombradas) ---
@st.cache_resource 
def get_selenium_driver_of():
    options = ChromeOptions(); options.add_argument("--headless"); options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage"); options.add_argument("--disable-gpu")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36")
    options.add_argument('--blink-settings=imagesEnabled=false'); options.add_argument("--window-size=1920,1080")
    try:
        driver = webdriver.Chrome(options=options)
        return driver
    except WebDriverException as e:
        st.error(f"Error inicializando Selenium driver (OF): {e}")
        return None

# Adaptada de tu streamlit_app.py funcional
def get_h2h_details_for_original_logic_of(driver_instance, key_match_id_for_h2h_url, rival_a_id, rival_b_id, rival_a_name="Rival A", rival_b_name="Rival B"):
    if not driver_instance: return {"status": "error", "resultado": "N/A (Driver no disponible H2H OF)"}
    if not key_match_id_for_h2h_url or not rival_a_id or not rival_b_id:
        return {"status": "error", "resultado": f"N/A (IDs incompletos para H2H {rival_a_name} vs {rival_b_name})"}
    
    url_to_visit = f"{BASE_URL_OF}/match/h2h-{key_match_id_for_h2h_url}"
    
    try:
        driver_instance.get(url_to_visit)
        WebDriverWait(driver_instance, SELENIUM_TIMEOUT_SECONDS_OF, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(
            EC.presence_of_element_located((By.ID, "table_v2")) 
        )
        time.sleep(0.7) 
        soup_selenium = BeautifulSoup(driver_instance.page_source, "html.parser")
    except TimeoutException:
        return {"status": "error", "resultado": f"N/A (Timeout esperando table_v2 en {url_to_visit})"}
    except Exception as e:
        return {"status": "error", "resultado": f"N/A (Error Selenium en {url_to_visit}: {type(e).__name__})"}

    if not soup_selenium: return {"status": "error", "resultado": f"N/A (Fallo soup Selenium H2H Original OF en {url_to_visit})"}
    
    table_to_search_h2h = soup_selenium.find("table", id="table_v2") 
    if not table_to_search_h2h: return {"status": "error", "resultado": f"N/A (Tabla v2 para H2H no encontrada en {url_to_visit})"}

    for row in table_to_search_h2h.find_all("tr", id=re.compile(r"tr2_\d+")): 
        links = row.find_all("a", onclick=True)
        if len(links) < 2: continue
        
        h2h_row_home_id_m = re.search(r"team\((\d+)\)", links[0].get("onclick", ""))
        h2h_row_away_id_m = re.search(r"team\((\d+)\)", links[1].get("onclick", ""))
        if not h2h_row_home_id_m or not h2h_row_away_id_m: continue
        
        h2h_row_home_id = h2h_row_home_id_m.group(1)
        h2h_row_away_id = h2h_row_away_id_m.group(1)
        
        if {h2h_row_home_id, h2h_row_away_id} == {str(rival_a_id), str(rival_b_id)}:
            score_span = row.find("span", class_="fscore_2") 
            if not score_span or not score_span.text or "-" not in score_span.text: continue
            
            score_val = score_span.text.strip().split("(")[0].strip() 
            g_h, g_a = score_val.split("-", 1)
            tds = row.find_all("td")
            handicap_val = "N/A"
            HANDICAP_TD_IDX = 11 
            if len(tds) > HANDICAP_TD_IDX:
                cell = tds[HANDICAP_TD_IDX]
                d_o = cell.get("data-o"); 
                handicap_val = d_o.strip() if d_o and d_o.strip() not in ["", "-"] else (cell.text.strip() if cell.text.strip() not in ["", "-"] else "N/A")
            
            rol_a_in_this_h2h = "H" if h2h_row_home_id == str(rival_a_id) else "A"
            
            return {
                "status": "found", "goles_home": g_h.strip(), "goles_away": g_a.strip(), 
                "handicap": handicap_val, "rol_rival_a": rol_a_in_this_h2h, 
                "h2h_home_team_name": links[0].text.strip(), "h2h_away_team_name": links[1].text.strip()
            }
    return {"status": "not_found", "resultado": f"H2H directo no encontrado para {rival_a_name} vs {rival_b_name} en historial (table_v2) de la página de ref. ({key_match_id_for_h2h_url})."}

def get_team_league_info_from_script_of(soup):
    home_id, away_id, league_id, home_name, away_name, league_name = (None,)*3 + ("N/A",)*3
    script_tag = soup.find("script", string=re.compile(r"var _matchInfo ="))
    if script_tag and script_tag.string:
        script_content = script_tag.string
        h_id_m = re.search(r"hId:\s*parseInt\('(\d+)'\)", script_content); g_id_m = re.search(r"gId:\s*parseInt\('(\d+)'\)", script_content)
        sclass_id_m = re.search(r"sclassId:\s*parseInt\('(\d+)'\)", script_content); h_name_m = re.search(r"hName:\s*'([^']*)'", script_content)
        g_name_m = re.search(r"gName:\s*'([^']*)'", script_content); l_name_m = re.search(r"lName:\s*'([^']*)'", script_content)
        if h_id_m: home_id = h_id_m.group(1); 
        if g_id_m: away_id = g_id_m.group(1)
        if sclass_id_m: league_id = sclass_id_m.group(1)
        if h_name_m: home_name = h_name_m.group(1).replace("\\'", "'"); 
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

def extract_last_match_in_league_of(driver, table_css_id_str, main_team_name_in_table, league_id_filter_value, home_or_away_filter_css_selector, is_home_game_filter):
    try:
        # Intentar desmarcar todos los checkboxes de liga primero para asegurar un estado limpio
        all_league_checkboxes_selector = f"#{table_css_id_str} input[type='checkbox'][id^='checkboxleague']"
        checkboxes = driver.find_elements(By.CSS_SELECTOR, all_league_checkboxes_selector)
        # for cb in checkboxes: # Esto puede ser lento, y a veces no necesario si solo se filtra uno
        #     if cb.is_selected():
        #         driver.execute_script("arguments[0].click();", cb) # Clic robusto
        # time.sleep(0.5) # Pausa después de desmarcar

        # Aplicar filtro de liga específica
        if league_id_filter_value:
            league_checkbox_selector = f"input#checkboxleague{table_css_id_str[-1]}[value='{league_id_filter_value}']"
            # Asegurarse de que el checkbox de la liga esté marcado
            # cb_league = driver.find_element(By.CSS_SELECTOR, league_checkbox_selector)
            # if not cb_league.is_selected():
            #     driver.execute_script("arguments[0].click();", cb_league)
            # time.sleep(0.5)
            click_element_robust_of(driver, By.CSS_SELECTOR, league_checkbox_selector); time.sleep(1.0) # Aumentado sleep

        # Aplicar filtro Home/Away
        click_element_robust_of(driver, By.CSS_SELECTOR, home_or_away_filter_css_selector); time.sleep(1.0) # Aumentado sleep
        
        page_source_updated = driver.page_source; soup_updated = BeautifulSoup(page_source_updated, "html.parser")
        table = soup_updated.find("table", id=table_css_id_str)
        if not table: return None
        
        count_visible_rows = 0
        for row_idx, row in enumerate(table.find_all("tr", id=re.compile(rf"tr{table_css_id_str[-1]}_\d+"))):
            if row.get("style") and "display:none" in row.get("style","").lower(): continue # Fila oculta por JS
            count_visible_rows +=1
            if count_visible_rows > 10: break # Limitar a las primeras N filas visibles
            
            # Doble chequeo de liga, por si el filtro JS no es perfecto
            if league_id_filter_value and row.get("name") != str(league_id_filter_value): continue
            
            tds = row.find_all("td"); 
            if len(tds) < 14: continue # Mínimo de columnas esperado
            
            home_team_row_el = tds[2].find("a"); away_team_row_el = tds[4].find("a")
            if not home_team_row_el or not away_team_row_el: continue
            
            home_team_row_name = home_team_row_el.text.strip(); away_team_row_name = away_team_row_el.text.strip()
            
            # Verificar si el equipo principal está en la posición correcta (Local/Visitante)
            team_is_home_in_row = main_team_name_in_table.lower() == home_team_row_name.lower()
            team_is_away_in_row = main_team_name_in_table.lower() == away_team_row_name.lower()
            
            if (is_home_game_filter and team_is_home_in_row) or \
               (not is_home_game_filter and team_is_away_in_row):
                date_span = tds[1].find("span", {"name": "timeData"}); date = date_span.text.strip() if date_span else "N/A"
                
                score_class_re = re.compile(r"fscore_") # fscore_1, fscore_2, etc.
                score_span = tds[3].find("span", class_=score_class_re); score = score_span.text.strip() if score_span else "N/A"
                
                handicap_cell = tds[11]; handicap = handicap_cell.get("data-o", handicap_cell.text.strip())
                if not handicap or handicap.strip() == "-": handicap = "N/A"
                else: handicap = handicap.strip()
                
                # Devolver el primer partido que cumpla todas las condiciones
                return {"date": date, "home_team": home_team_row_name, "away_team": away_team_row_name,"score": score, "handicap_line": handicap}
        return None # Si no se encuentra ningún partido después de iterar
    except Exception as e:
        # st.warning(f"Advertencia en extract_last_match_in_league_of: {type(e).__name__} - {str(e)[:100]}")
        return None

def get_main_match_odds_selenium_of(driver):
    odds_info = {"ah_home_cuota": "N/A", "ah_linea": "N/A", "ah_away_cuota": "N/A", "goals_over_cuota": "N/A", "goals_linea": "N/A", "goals_under_cuota": "N/A"}
    try:
        live_compare_div = WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS_OF, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.presence_of_element_located((By.ID, "liveCompareDiv")))
        bet365_row_selector = "tr#tr_o_1_8[name='earlyOdds']"; bet365_row_selector_alt = "tr#tr_o_1_31[name='earlyOdds']"
        table_odds = live_compare_div.find_element(By.XPATH, ".//table[contains(@class, 'team-table-other')]")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", table_odds); time.sleep(0.5)
        bet365_early_odds_row = None
        try: bet365_early_odds_row = WebDriverWait(driver, 5, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.visibility_of_element_located((By.CSS_SELECTOR, bet365_row_selector)))
        except TimeoutException: 
            try:
                bet365_early_odds_row = WebDriverWait(driver, 3, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.visibility_of_element_located((By.CSS_SELECTOR, bet365_row_selector_alt)))
            except TimeoutException:
                 # st.warning("No se encontró la fila de odds de Bet365 (earlyOdds) por ID 8 o 31 (OF).")
                 return odds_info # Devuelve N/A si no se encuentra

        tds = bet365_early_odds_row.find_elements(By.TAG_NAME, "td")
        if len(tds) >= 11: # AH Cuota Home, AH Linea, AH Cuota Away, ..., Goles Cuota Over, Goles Linea, Goles Cuota Under
            odds_info["ah_home_cuota"] = tds[2].get_attribute("data-o") or tds[2].text.strip() or "N/A"
            odds_info["ah_linea"] = tds[3].get_attribute("data-o") or tds[3].text.strip() or "N/A" # Este es el AH_Act
            odds_info["ah_away_cuota"] = tds[4].get_attribute("data-o") or tds[4].text.strip() or "N/A"
            
            odds_info["goals_over_cuota"] = tds[8].get_attribute("data-o") or tds[8].text.strip() or "N/A"
            odds_info["goals_linea"] = tds[9].get_attribute("data-o") or tds[9].text.strip() or "N/A" # Este es G_i
            odds_info["goals_under_cuota"] = tds[10].get_attribute("data-o") or tds[10].text.strip() or "N/A"
    except Exception as e:
        # st.warning(f"Error obteniendo odds: {type(e).__name__} - {str(e)[:100]}")
        pass # Devuelve N/A por defecto
    return odds_info

def extract_standings_data_from_h2h_page_of(h2h_soup, target_team_name_exact):
    data = {"name": target_team_name_exact, "ranking": "N/A", "total_pj": "N/A", "total_v": "N/A", "total_e": "N/A", "total_d": "N/A", "total_gf": "N/A", "total_gc": "N/A", "specific_pj": "N/A", "specific_v": "N/A", "specific_e": "N/A", "specific_d": "N/A", "specific_gf": "N/A", "specific_gc": "N/A", "specific_type": "N/A" }
    if not h2h_soup: return data
    standings_section = h2h_soup.find("div", id="porletP4") # La sección principal de standings
    if not standings_section: return data

    team_table_soup = None; is_home_team_table_type = False # Para saber si es "Home" o "Away" la tabla específica

    # Intentar encontrar la tabla del equipo en la sección "home-div"
    home_div_standings = standings_section.find("div", class_="home-div")
    if home_div_standings:
        home_table_header = home_div_standings.find("tr", class_="team-home") # Cabecera de la tabla local
        if home_table_header and target_team_name_exact.lower() in home_table_header.get_text().lower():
            team_table_soup = home_div_standings.find("table", class_="team-table-home")
            is_home_team_table_type = True
            data["specific_type"] = home_div_standings.find("td", class_="bg1").text.strip() if home_div_standings.find("td", class_="bg1") else "En Casa"


    # Si no se encontró, intentar en "guest-div"
    if not team_table_soup:
        guest_div_standings = standings_section.find("div", class_="guest-div")
        if guest_div_standings:
            guest_table_header = guest_div_standings.find("tr", class_="team-guest") # Cabecera de la tabla visitante
            if guest_table_header and target_team_name_exact.lower() in guest_table_header.get_text().lower():
                team_table_soup = guest_div_standings.find("table", class_="team-table-guest")
                is_home_team_table_type = False # Es la tabla Away
                data["specific_type"] = guest_div_standings.find("td", class_="bg1").text.strip() if guest_div_standings.find("td", class_="bg1") else "Fuera"
    
    if not team_table_soup: return data # No se encontró la tabla del equipo

    # Extraer Nombre y Ranking de la cabecera de la tabla encontrada
    header_row_found = team_table_soup.find("tr", class_=re.compile(r"team-(home|guest)")) 
    if header_row_found:
        link = header_row_found.find("a")
        if link:
            full_text = link.get_text(separator=" ", strip=True)
            # El nombre del equipo puede estar después de algo como "[ENG PR-3]"
            name_match = re.search(r"]\s*(.*)", full_text)
            if name_match: data["name"] = name_match.group(1).strip()
            
            # El ranking está dentro de los corchetes, ej: "[ENG PR-3]" o "[3]"
            rank_match = re.search(r"\[(?:[^\]]+-)?(\d+)\]", full_text) # Busca el último número en corchetes
            if rank_match: data["ranking"] = rank_match.group(1)
        else: # Fallback si no hay link <a>
            header_text_no_link = header_row_found.get_text(separator=" ", strip=True)
            name_match_nl = re.search(r"]\s*(.*)", header_text_no_link)
            if name_match_nl: data["name"] = name_match_nl.group(1).strip()
            rank_match_nl = re.search(r"\[(?:[^\]]+-)?(\d+)\]", header_text_no_link)
            if rank_match_nl: data["ranking"] = rank_match_nl.group(1)


    # Extraer filas de datos (Total, Home/Away específico)
    ft_rows = [] # Filas correspondientes a "Full Time"
    current_section = None
    for row in team_table_soup.find_all("tr", align="center"): # Las filas de datos tienen align="center"
        th_cell = row.find("th") # Las cabeceras de sección (FT, HT) están en <th>
        if th_cell:
            if "FT" in th_cell.get_text(strip=True): current_section = "FT"
            elif "HT" in th_cell.get_text(strip=True): break # No nos interesan los datos de Half Time
        
        if current_section == "FT":
            cells = row.find_all("td")
            if cells and len(cells) > 0 and cells[0].get_text(strip=True) in ["Total", "Home", "Away"]: # Filas de datos
                ft_rows.append(cells)

    for cells in ft_rows:
        if len(cells) > 8: # PJ, V, E, D, GF, GC, GD, Pts, % (mínimo 8 para los datos que necesitamos)
            row_type_text = cells[0].get_text(strip=True)
            pj, v, e, d, gf, gc = (cells[i].get_text(strip=True) for i in range(1, 7))
            
            # Asignar a N/A si está vacío
            pj = pj if pj else "N/A"; v = v if v else "N/A"; e = e if e else "N/A"; d = d if d else "N/A"
            gf = gf if gf else "N/A"; gc = gc if gc else "N/A"

            if row_type_text == "Total":
                data["total_pj"], data["total_v"], data["total_e"], data["total_d"], data["total_gf"], data["total_gc"] = pj, v, e, d, gf, gc
            elif row_type_text == "Home" and is_home_team_table_type: # Si esta es la tabla "Home" y la fila es "Home"
                data["specific_pj"], data["specific_v"], data["specific_e"], data["specific_d"], data["specific_gf"], data["specific_gc"] = pj, v, e, d, gf, gc
            elif row_type_text == "Away" and not is_home_team_table_type: # Si esta es la tabla "Away" y la fila es "Away"
                data["specific_pj"], data["specific_v"], data["specific_e"], data["specific_d"], data["specific_gf"], data["specific_gc"] = pj, v, e, d, gf, gc
    return data


# --- NUEVAS FUNCIONES DE EXTRACCIÓN (Estilo Eldefinitivo.txt) ---
def extract_final_score_of(soup):
    """Extrae el marcador final del partido si está disponible."""
    try:
        score_divs = soup.select('#mScore .end .score') # Selector de Eldefinitivo
        if len(score_divs) == 2:
            hs = score_divs[0].text.strip()
            aws = score_divs[1].text.strip()
            if hs.isdigit() and aws.isdigit():
                return f"{hs}*{aws}", f"{hs}-{aws}" # Formateado y Raw
    except Exception:
        pass
    return '?*?', "?-?" # Por defecto

def extract_h2h_data_of(soup, main_home_team_name, main_away_team_name, current_league_id):
    """
    Extrae AH_H2H_V, Res_H2H_V (res3) y AH_H2H_G, Res_H2H_G (res6).
    """
    ah1, res1, res1_raw = '-', '?*?', '?-?' # H2H_V (Local actual es local en H2H)
    ah6, res6, res6_raw = '-', '?*?', '?-?' # H2H_G (General más reciente)
    
    h2h_table = soup.find("table", id="table_v3")
    if not h2h_table:
        return ah1, res1, res1_raw, ah6, res6, res6_raw

    # Lista para todos los partidos H2H (filtrados por liga si es posible)
    filtered_h2h_list = []
    for row_h2h in h2h_table.find_all("tr", id=re.compile(r"tr3_\d+")):
        details = get_match_details_from_row_of(row_h2h, score_class_selector='fscore_3', source_table_type='h2h')
        if not details: continue
        # Filtrar por liga actual
        if current_league_id and details.get('league_id_hist') and details.get('league_id_hist') != str(current_league_id):
            continue
        filtered_h2h_list.append(details)

    if not filtered_h2h_list: # No hay H2H (o ninguno en la misma liga)
        return ah1, res1, res1_raw, ah6, res6, res6_raw

    # Para AH_H2H_G, Res_H2H_G (res6): el más reciente de la lista filtrada
    # El primer elemento de filtered_h2h_list es el más reciente.
    h2h_general_match = filtered_h2h_list[0]
    ah6 = h2h_general_match.get('ahLine', '-')
    res6 = h2h_general_match.get('score', '?*?')
    res6_raw = h2h_general_match.get('score_raw', '?-?')

    # Para AH_H2H_V, Res_H2H_V (res1 -> res3 en Eldefinitivo): buscar cuando el local actual fue local
    # Iteramos sobre la lista filtrada (que ya está ordenada por fecha descendente)
    h2h_local_specific_match = None
    for d_h2h in filtered_h2h_list:
        # Comprobar si el equipo local del partido H2H (d_h2h['home']) es el equipo local del partido principal (main_home_team_name)
        # Y el visitante del H2H es el visitante del principal
        if d_h2h.get('home','').lower() == main_home_team_name.lower() and \
           d_h2h.get('away','').lower() == main_away_team_name.lower():
            h2h_local_specific_match = d_h2h
            break # Encontramos el más reciente donde el local actual fue local

    if h2h_local_specific_match:
        ah1 = h2h_local_specific_match.get('ahLine', '-')
        res1 = h2h_local_specific_match.get('score', '?*?')
        res1_raw = h2h_local_specific_match.get('score_raw', '?-?')
    else: # Si no se encuentra un H2H específico donde el local fue local, se puede tomar el general o dejar en blanco
          # Eldefinitivo parece que en algunos casos usa el general para res3 si el específico no existe.
          # Por ahora, si no hay específico, ah1 y res1 quedan como '-' y '?*?'
          pass


    # En Eldefinitivo, res3 (Res_H2H_V) toma el valor de res1 si ah1 se encontró, o res6 si ah1 no.
    # Vamos a mantener res1 como el resultado del H2H específico del local, y res6 como el general.
    # El usuario decidirá cómo usarlo.
    # `res3` en el output de Eldefinitivo es Res_H2H_V, que aquí es `res1`.

    return ah1, res1, res1_raw, ah6, res6, res6_raw


def extract_comparative_match_of(soup_for_team_history, # Sopa de la página H2H principal
                                 table_id_of_team_to_search, # "table_v1" para Local, "table_v2" para Visitante
                                 team_name_to_find_match_for, # Nombre del equipo cuyo historial se busca (Local o Visitante actual)
                                 opponent_name_to_search,     # Nombre del oponente contra quien debe haber jugado
                                 current_league_id,
                                 is_home_table): # True si table_id_of_team_to_search es la del equipo jugando en casa
    """
    Busca en el historial de `team_name_to_find_match_for` (en `table_id_of_team_to_search`)
    un partido contra `opponent_name_to_search`.
    Devuelve "Marcador/AH Localía" o '-'.
    """
    if not opponent_name_to_search or opponent_name_to_search == "N/A":
        return "-"

    table = soup_for_team_history.find("table", id=table_id_of_team_to_search)
    if not table: return "-"

    score_class_selector = 'fscore_1' if is_home_table else 'fscore_2'

    for row in table.find_all("tr", id=re.compile(rf"tr{table_id_of_team_to_search[-1]}_\d+")):
        details = get_match_details_from_row_of(row, score_class_selector=score_class_selector, source_table_type='hist')
        if not details: continue

        # Filtrar por liga actual
        if current_league_id and details.get('league_id_hist') and details.get('league_id_hist') != str(current_league_id):
            continue
        
        # Verificar si el oponente está en el partido y si el equipo principal es el correcto
        home_hist = details.get('home','').lower()
        away_hist = details.get('away','').lower()
        team_main_lower = team_name_to_find_match_for.lower()
        opponent_lower = opponent_name_to_search.lower()

        # El equipo para el que buscamos el historial debe ser uno de los participantes,
        # y el oponente buscado debe ser el otro.
        if (team_main_lower == home_hist and opponent_lower == away_hist) or \
           (team_main_lower == away_hist and opponent_lower == home_hist):
            
            score = details.get('score', '?*?')
            ah_line = details.get('ahLine', '-')
            localia = ''
            if team_main_lower == home_hist: # El equipo de interés jugó en casa en este partido histórico
                localia = 'H'
            elif team_main_lower == away_hist: # El equipo de interés jugó como visitante
                localia = 'A'
            
            return f"{score}/{ah_line} {localia}".strip()
            
    return "-"


# --- STREAMLIT APP UI (Función principal) ---
def display_other_feature_ui():
    st.header("📊 Estadísticas de Clasificación y Partidos (OF)")
    main_match_id_str_input_of = st.sidebar.text_input("🆔 ID Partido (Análisis OF):", value="2696131", help="Pega el ID del partido para análisis en Other Feature.", key="other_feature_match_id_input")
    analizar_button_of = st.sidebar.button("🚀 Analizar Partido (OF)", type="secondary", use_container_width=True, key="other_feature_analizar_button")

    if 'driver_other_feature' not in st.session_state: st.session_state.driver_other_feature = None

    if analizar_button_of:
        main_match_id_to_process_of = None
        if main_match_id_str_input_of:
            try:
                cleaned_id_str = "".join(filter(str.isdigit, main_match_id_str_input_of))
                if cleaned_id_str: main_match_id_to_process_of = int(cleaned_id_str)
            except ValueError: st.error("⚠️ ID de partido no válido (OF)."); st.stop()

        if not main_match_id_to_process_of: st.warning("⚠️ Ingresa un ID de partido válido (OF).")
        else:
            start_time_of = time.time()
            with st.spinner("Obteniendo datos generales y de clasificación (OF)..."):
                main_page_url_h2h_view_of = f"/match/h2h-{main_match_id_to_process_of}"
                soup_main_h2h_page_of = fetch_soup_requests_of(main_page_url_h2h_view_of)

            if not soup_main_h2h_page_of: st.error("No se pudo obtener la página H2H principal (OF). El análisis no puede continuar."); st.stop()

            mp_home_id_of, mp_away_id_of, mp_league_id_of, mp_home_name_from_script, mp_away_name_from_script, mp_league_name_of = get_team_league_info_from_script_of(soup_main_h2h_page_of)
            home_team_main_standings = extract_standings_data_from_h2h_page_of(soup_main_h2h_page_of, mp_home_name_from_script)
            away_team_main_standings = extract_standings_data_from_h2h_page_of(soup_main_h2h_page_of, mp_away_name_from_script)
            display_home_name = home_team_main_standings.get("name", mp_home_name_from_script) if home_team_main_standings.get("name", "N/A") != "N/A" else mp_home_name_from_script
            display_away_name = away_team_main_standings.get("name", mp_away_name_from_script) if away_team_main_standings.get("name", "N/A") != "N/A" else mp_away_name_from_script


            st.markdown(f"### 📋 {display_home_name or 'Local'} vs {display_away_name or 'Visitante'}"); st.caption(f"Liga: {mp_league_name_of or 'N/A'} (ID: {mp_league_id_of or 'N/A'})")
            if display_home_name and display_home_name != "N/A":
                st.markdown(f"--- **{display_home_name} (Local Partido Principal)** ---"); st.markdown(f"🏆 Rk: {home_team_main_standings.get('ranking', 'N/A')}")
                st.markdown(f"🌍 T: {home_team_main_standings.get('total_pj', 'N/A')}|{home_team_main_standings.get('total_v', 'N/A')}/{home_team_main_standings.get('total_e', 'N/A')}/{home_team_main_standings.get('total_d', 'N/A')}|{home_team_main_standings.get('total_gf', 'N/A')}-{home_team_main_standings.get('total_gc', 'N/A')}")
                st.markdown(f"🏠 {home_team_main_standings.get('specific_type','En Casa')}: {home_team_main_standings.get('specific_pj', 'N/A')}|{home_team_main_standings.get('specific_v', 'N/A')}/{home_team_main_standings.get('specific_e', 'N/A')}/{home_team_main_standings.get('specific_d', 'N/A')}|{home_team_main_standings.get('specific_gf', 'N/A')}-{home_team_main_standings.get('specific_gc', 'N/A')}")
            if display_away_name and display_away_name != "N/A":
                st.markdown(f"--- **{display_away_name} (Visitante Partido Principal)** ---"); st.markdown(f"🏆 Rk: {away_team_main_standings.get('ranking', 'N/A')}")
                st.markdown(f"🌍 T: {away_team_main_standings.get('total_pj', 'N/A')}|{away_team_main_standings.get('total_v', 'N/A')}/{away_team_main_standings.get('total_e', 'N/A')}/{away_team_main_standings.get('total_d', 'N/A')}|{away_team_main_standings.get('total_gf', 'N/A')}-{away_team_main_standings.get('total_gc', 'N/A')}")
                st.markdown(f"✈️ {away_team_main_standings.get('specific_type','Fuera')}: {away_team_main_standings.get('specific_pj', 'N/A')}|{away_team_main_standings.get('specific_v', 'N/A')}/{away_team_main_standings.get('specific_e', 'N/A')}/{away_team_main_standings.get('specific_d', 'N/A')}|{away_team_main_standings.get('specific_gf', 'N/A')}-{away_team_main_standings.get('specific_gc', 'N/A')}")
            st.markdown("---")

            main_match_odds_data_of = {}; last_home_match_in_league_of = None; last_away_match_in_league_of = None
            
            key_match_id_for_rival_a_h2h, rival_a_id_orig_col3, rival_a_name_orig_col3 = get_rival_a_for_original_h2h_of(main_match_id_to_process_of)
            match_id_rival_b_game_ref, rival_b_id_orig_col3, rival_b_name_orig_col3 = get_rival_b_for_original_h2h_of(main_match_id_to_process_of)
            
            rival_a_standings = {}; rival_b_standings = {}
            with st.spinner("Obteniendo clasificaciones de oponentes (OF)..."):
                if rival_a_name_orig_col3 and rival_a_name_orig_col3 != "N/A" and key_match_id_for_rival_a_h2h:
                    soup_rival_a_h2h_page = fetch_soup_requests_of(f"/match/h2h-{key_match_id_for_rival_a_h2h}")
                    if soup_rival_a_h2h_page: rival_a_standings = extract_standings_data_from_h2h_page_of(soup_rival_a_h2h_page, rival_a_name_orig_col3)
                if rival_b_name_orig_col3 and rival_b_name_orig_col3 != "N/A" and match_id_rival_b_game_ref:
                    soup_rival_b_h2h_page = fetch_soup_requests_of(f"/match/h2h-{match_id_rival_b_game_ref}")
                    if soup_rival_b_h2h_page: rival_b_standings = extract_standings_data_from_h2h_page_of(soup_rival_b_h2h_page, rival_b_name_orig_col3)

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
                with st.spinner("🚘 Inicializando WebDriver (OF)..."): driver_actual_of = get_selenium_driver_of()
                st.session_state.driver_other_feature = driver_actual_of

            if driver_actual_of:
                try:
                    with st.spinner("Accediendo a datos detallados con Selenium (OF)..."):
                        driver_actual_of.get(f"{BASE_URL_OF}{main_page_url_h2h_view_of}") # Ir a la página principal
                        WebDriverWait(driver_actual_of, SELENIUM_TIMEOUT_SECONDS_OF).until(EC.presence_of_element_located((By.ID, "table_v1"))) # Esperar carga
                        time.sleep(0.5) # Pausa adicional
                        main_match_odds_data_of = get_main_match_odds_selenium_of(driver_actual_of) # Odds de la página actual
                        
                        # Para last_home_match y last_away_match, la página ya está cargada.
                        # Las funciones extract_last_match_in_league_of harán los clics necesarios en la página actual.
                        if mp_home_id_of and mp_league_id_of and display_home_name and display_home_name != "N/A":
                             # st.write(f"Debug: Extracting last home for {display_home_name}, league {mp_league_id_of}")
                             last_home_match_in_league_of = extract_last_match_in_league_of(driver_actual_of, "table_v1", display_home_name, mp_league_id_of, "input#cb_sos1[value='1']", is_home_game_filter=True)
                        
                        if mp_away_id_of and mp_league_id_of and display_away_name and display_away_name != "N/A":
                            # st.write(f"Debug: Extracting last away for {display_away_name}, league {mp_league_id_of}")
                            last_away_match_in_league_of = extract_last_match_in_league_of(driver_actual_of, "table_v2", display_away_name, mp_league_id_of, "input#cb_sos2[value='2']", is_home_game_filter=False)

                except Exception as e_main_sel_of: st.error(f"Error Selenium en pág. principal (OF): {type(e_main_sel_of).__name__} - {str(e_main_sel_of)[:100]}")
            else: st.error("No se pudo iniciar driver Selenium para datos de página principal (OF).")

            # --- EXTRACCIÓN DE DATOS ADICIONALES (ESTILO Eldefinitivo.txt) ---
            col_data = {
                "AH_H2H_V": "-", "AH_Act": "?", "Res_H2H_V": "?*?",
                "AH_L_H": "-", "Res_L_H": "?*?", "AH_V_A": "-", "Res_V_A": "?*?",
                "AH_H2H_G": "-", "Res_H2H_G": "?*?",
                "L_vs_UV_A": "-", "V_vs_UL_H": "-",
                "Stats_L": "Stats L: N/A", "Stats_V": "Stats V: N/A",
                "Fin": "?*?", "G_i": "?", "League": mp_league_name_of or "N/A",
                "match_id": str(main_match_id_to_process_of)
            }

            # AH_Act y G_i (de Selenium odds)
            raw_ah_act = main_match_odds_data_of.get('ah_linea', '?')
            col_data["AH_Act"] = format_ah_as_decimal_string_of(raw_ah_act)
            raw_g_i = main_match_odds_data_of.get('goals_linea', '?')
            col_data["G_i"] = format_ah_as_decimal_string_of(raw_g_i)
            
            # Fin (Marcador Final del partido actual)
            col_data["Fin"], _ = extract_final_score_of(soup_main_h2h_page_of)

            # Stats_L y Stats_V (formatear desde home_team_main_standings)
            if home_team_main_standings.get("name", "N/A") != "N/A":
                hst = home_team_main_standings
                col_data["Stats_L"] = (f"🏆Rk:{hst.get('ranking','N/A')} 🏠{hst.get('specific_type','En Casa')}\n"
                                       f"🌍T:{hst.get('total_pj','N/A')}|{hst.get('total_v','N/A')}/{hst.get('total_e','N/A')}/{hst.get('total_d','N/A')}|{hst.get('total_gf','N/A')}-{hst.get('total_gc','N/A')}\n"
                                       f"🏡L:{hst.get('specific_pj','N/A')}|{hst.get('specific_v','N/A')}/{hst.get('specific_e','N/A')}/{hst.get('specific_d','N/A')}|{hst.get('specific_gf','N/A')}-{hst.get('specific_gc','N/A')}")
            if away_team_main_standings.get("name", "N/A") != "N/A":
                ast = away_team_main_standings
                col_data["Stats_V"] = (f"🏆Rk:{ast.get('ranking','N/A')} ✈️{ast.get('specific_type','Fuera')}\n"
                                       f"🌍T:{ast.get('total_pj','N/A')}|{ast.get('total_v','N/A')}/{ast.get('total_e','N/A')}/{ast.get('total_d','N/A')}|{ast.get('total_gf','N/A')}-{ast.get('total_gc','N/A')}\n"
                                       f"🛫V:{ast.get('specific_pj','N/A')}|{ast.get('specific_v','N/A')}/{ast.get('specific_e','N/A')}/{ast.get('specific_d','N/A')}|{ast.get('specific_gf','N/A')}-{ast.get('specific_gc','N/A')}")

            # AH_L_H, Res_L_H y AH_V_A, Res_V_A (de Selenium last_match)
            if last_home_match_in_league_of:
                col_data["AH_L_H"] = format_ah_as_decimal_string_of(last_home_match_in_league_of.get('handicap_line', '-'))
                col_data["Res_L_H"] = last_home_match_in_league_of.get('score', '?*?').replace('-', '*')
            if last_away_match_in_league_of:
                col_data["AH_V_A"] = format_ah_as_decimal_string_of(last_away_match_in_league_of.get('handicap_line', '-'))
                col_data["Res_V_A"] = last_away_match_in_league_of.get('score', '?*?').replace('-', '*')

            # AH_H2H_V, Res_H2H_V, AH_H2H_G, Res_H2H_G (de soup H2H)
            ah1_val, res1_val, _, ah6_val, res6_val, _ = extract_h2h_data_of(soup_main_h2h_page_of, display_home_name, display_away_name, mp_league_id_of)
            col_data["AH_H2H_V"] = ah1_val
            col_data["Res_H2H_V"] = res1_val # Este es res3 en Eldefinitivo
            col_data["AH_H2H_G"] = ah6_val
            col_data["Res_H2H_G"] = res6_val
            
            # L_vs_UV_A (comp7) y V_vs_UL_H (comp8)
            last_away_opponent_for_home_hist = last_away_match_in_league_of.get('home_team') if last_away_match_in_league_of else None
            if last_away_opponent_for_home_hist and display_home_name != "N/A":
                col_data["L_vs_UV_A"] = extract_comparative_match_of(soup_main_h2h_page_of, "table_v1", display_home_name, last_away_opponent_for_home_hist, mp_league_id_of, is_home_table=True)

            last_home_opponent_for_away_hist = last_home_match_in_league_of.get('away_team') if last_home_match_in_league_of else None
            if last_home_opponent_for_away_hist and display_away_name != "N/A":
                col_data["V_vs_UL_H"] = extract_comparative_match_of(soup_main_h2h_page_of, "table_v2", display_away_name, last_home_opponent_for_away_hist, mp_league_id_of, is_home_table=False)


            # --- FIN EXTRACCIÓN DATOS ADICIONALES ---

            st.markdown("#### Betting Odds Bet365 (Iniciales del Partido Principal OF)"); col_odds1_of, col_odds2_of = st.columns(2)
            with col_odds1_of: st.markdown(f"**H. Asiático (OF):** `{main_match_odds_data_of.get('ah_home_cuota','N/A')}` <span style='color:blue; font-weight:bold;'>[{format_ah_as_decimal_string_of(main_match_odds_data_of.get('ah_linea','N/A'))}]</span> `{main_match_odds_data_of.get('ah_away_cuota','N/A')}`", unsafe_allow_html=True)
            with col_odds2_of: st.markdown(f"**Línea Goles (OF):** `Ov {main_match_odds_data_of.get('goals_over_cuota','N/A')}` <span style='color:red; font-weight:bold;'>[{format_ah_as_decimal_string_of(main_match_odds_data_of.get('goals_linea','N/A'))}]</span> `Un {main_match_odds_data_of.get('goals_under_cuota','N/A')}`", unsafe_allow_html=True)
            st.markdown("---")
            st.markdown("### ⚔️ Análisis Detallado (OF) - Partidos Seleccionados"); col1of, col2of, col3of = st.columns(3)
            with col1of:
                st.markdown(f"##### <span style='color:#4CAF50;'>🏡 Último de {display_home_name or 'Local'} (OF)</span><br>(Casa, Misma Liga)", unsafe_allow_html=True)
                if last_home_match_in_league_of: 
                    res = last_home_match_in_league_of
                    st.markdown(f"{res['home_team']} **{res['score'].replace('-',':')}** {res['away_team']}")
                    st.markdown(f"**AH:** <span style='font-weight:bold;'>{format_ah_as_decimal_string_of(res['handicap_line'])}</span>", unsafe_allow_html=True); st.caption(f"{res['date']}")
                else: st.info("Último partido local no encontrado.")
            with col2of:
                st.markdown(f"##### <span style='color:#2196F3;'>✈️ Último de {display_away_name or 'Visitante'} (OF)</span><br>(Fuera, Misma Liga)", unsafe_allow_html=True)
                if last_away_match_in_league_of: 
                    res = last_away_match_in_league_of
                    st.markdown(f"{res['home_team']} **{res['score'].replace('-',':')}** {res['away_team']}")
                    st.markdown(f"**AH:** <span style='font-weight:bold;'>{format_ah_as_decimal_string_of(res['handicap_line'])}</span>", unsafe_allow_html=True); st.caption(f"{res['date']}")
                else: st.info("Último partido visitante no encontrado.")
            with col3of: # Columna 3 original
                st.markdown(f"##### <span style='color:#E65100;'>🆚 H2H Oponentes (OF)</span><br>(Método Original Col3)", unsafe_allow_html=True)
                rival_a_col3_name_display = rival_a_name_orig_col3 if rival_a_name_orig_col3 and rival_a_name_orig_col3 != "N/A" else (rival_a_id_orig_col3 or "Rival A")
                rival_b_col3_name_display = rival_b_name_orig_col3 if rival_b_name_orig_col3 and rival_b_name_orig_col3 != "N/A" else (rival_b_id_orig_col3 or "Rival B")
                details_h2h_col3_of = {"status": "error", "resultado": "N/A (OF)"}

                if key_match_id_for_rival_a_h2h and rival_a_id_orig_col3 and rival_b_id_orig_col3 and driver_actual_of: 
                    with st.spinner(f"Buscando H2H Col3: {rival_a_col3_name_display} vs {rival_b_col3_name_display}..."):
                        details_h2h_col3_of = get_h2h_details_for_original_logic_of(driver_actual_of, key_match_id_for_rival_a_h2h, rival_a_id_orig_col3, rival_b_id_orig_col3, rival_a_col3_name_display, rival_b_col3_name_display)
                
                if details_h2h_col3_of.get("status") == "found":
                    res_h2h = details_h2h_col3_of
                    st.markdown(f"<p style='font-size:0.9em;'><b>{res_h2h.get('h2h_home_team_name')}</b> {res_h2h.get('goles_home')} - {res_h2h.get('goles_away')} <b>{res_h2h.get('h2h_away_team_name')}</b> (AH: {format_ah_as_decimal_string_of(res_h2h.get('handicap'))})</p>", unsafe_allow_html=True)
                else: st.info(details_h2h_col3_of.get('resultado', f"H2H Col3 no encontrado."))
                st.markdown("---") # Separador antes de standings de rivales
                if rival_a_standings.get("name", "N/A") != "N/A":
                    st.markdown(f"**Clasif. {rival_a_standings.get('name', 'Rival A')}:**"); st.markdown(f"🏆 Rk: {rival_a_standings.get('ranking', 'N/A')}")
                    st.markdown(f"🌍 T: {rival_a_standings.get('total_pj', 'N/A')}|{rival_a_standings.get('total_v', 'N/A')}/{rival_a_standings.get('total_e', 'N/A')}/{rival_a_standings.get('total_d', 'N/A')}|{rival_a_standings.get('total_gf', 'N/A')}-{rival_a_standings.get('total_gc', 'N/A')}")
                    icon_specific_a = "🏠" if rival_a_standings.get('specific_type') == "En Casa" else "✈️"; st.markdown(f"{icon_specific_a} {rival_a_standings.get('specific_type','Stats')}: {rival_a_standings.get('specific_pj', 'N/A')}|{rival_a_standings.get('specific_v', 'N/A')}/{rival_a_standings.get('specific_e', 'N/A')}/{rival_a_standings.get('specific_d', 'N/A')}|{rival_a_standings.get('specific_gf', 'N/A')}-{rival_a_standings.get('specific_gc', 'N/A')}")
                else: st.caption(f"Standings no disponibles para {rival_a_col3_name_display}")
                st.markdown("---")
                if rival_b_standings.get("name", "N/A") != "N/A":
                    st.markdown(f"**Clasif. {rival_b_standings.get('name', 'Rival B')}:**"); st.markdown(f"🏆 Rk: {rival_b_standings.get('ranking', 'N/A')}")
                    st.markdown(f"🌍 T: {rival_b_standings.get('total_pj', 'N/A')}|{rival_b_standings.get('total_v', 'N/A')}/{rival_b_standings.get('total_e', 'N/A')}/{rival_b_standings.get('total_d', 'N/A')}|{rival_b_standings.get('total_gf', 'N/A')}-{rival_b_standings.get('total_gc', 'N/A')}")
                    icon_specific_b = "🏠" if rival_b_standings.get('specific_type') == "En Casa" else "✈️"; st.markdown(f"{icon_specific_b} {rival_b_standings.get('specific_type','Stats')}: {rival_b_standings.get('specific_pj', 'N/A')}|{rival_b_standings.get('specific_v', 'N/A')}/{rival_b_standings.get('specific_e', 'N/A')}/{rival_b_standings.get('specific_d', 'N/A')}|{rival_b_standings.get('specific_gf', 'N/A')}-{rival_b_standings.get('specific_gc', 'N/A')}")
                else: st.caption(f"Standings no disponibles para {rival_b_col3_name_display}")
            
            # --- VISUALIZACIÓN DE LAS NUEVAS COLUMNAS (Estilo Eldefinitivo.txt) ---
            st.markdown("---")
            st.markdown("### 📈 Datos Adicionales del Partido (Estilo Eldefinitivo.txt)")

            # Fila 1: AH_H2H_V, AH_Act, Res_H2H_V
            c1, c2, c3 = st.columns(3)
            c1.metric(label="AH H2H (Local vs Visitante, Local en Casa)", value=col_data["AH_H2H_V"])
            c2.metric(label="AH Actual Partido", value=col_data["AH_Act"])
            c3.metric(label="Res H2H (Local vs Visitante, Local en Casa)", value=col_data["Res_H2H_V"].replace("*",":"))
            
            # Fila 2: AH_L_H, Res_L_H, AH_V_A, Res_V_A
            c4, c5, c6, c7 = st.columns(4)
            c4.metric(label="AH Últ. Local (Casa)", value=col_data["AH_L_H"])
            c5.metric(label="Res Últ. Local (Casa)", value=col_data["Res_L_H"].replace("*",":"))
            c6.metric(label="AH Últ. Visitante (Fuera)", value=col_data["AH_V_A"])
            c7.metric(label="Res Últ. Visitante (Fuera)", value=col_data["Res_V_A"].replace("*",":"))

            # Fila 3: AH_H2H_G, Res_H2H_G
            c8, c9 = st.columns(2)
            c8.metric(label="AH H2H (General, más reciente)", value=col_data["AH_H2H_G"])
            c9.metric(label="Res H2H (General, más reciente)", value=col_data["Res_H2H_G"].replace("*",":"))

            # Fila 4: L_vs_UV_A, V_vs_UL_H
            c10, c11 = st.columns(2)
            c10.markdown(f"**Local vs Últ. Rival Visitante (Fuera):**\n{col_data['L_vs_UV_A'].replace('*',':')}")
            c11.markdown(f"**Visitante vs Últ. Rival Local (Casa):**\n{col_data['V_vs_UL_H'].replace('*',':')}")
            
            # Fila 5: Stats_L (columnas preformateadas)
            st.markdown("**Estadísticas Local:**")
            st.text(col_data["Stats_L"])
            
            # Fila 6: Stats_V (columnas preformateadas)
            st.markdown("**Estadísticas Visitante:**")
            st.text(col_data["Stats_V"])
            
            # Fila 7: Fin, G_i, League, match_id
            c12, c13, c14, c15 = st.columns(4)
            c12.metric(label="Marcador Final Partido", value=col_data["Fin"].replace("*",":"))
            c13.metric(label="Línea Goles Actual Partido", value=col_data["G_i"])
            c14.metric(label="Liga", value=col_data["League"])
            c15.metric(label="ID Partido", value=col_data["match_id"])
            
            end_time_of = time.time(); st.markdown("---"); st.caption(f"⏱️ Tiempo total del análisis (OF): {end_time_of - start_time_of:.2f} segundos")
    else: st.info("✨ Ingresa un ID de partido en la barra lateral (OF) y haz clic en 'Analizar Partido (OF)' para comenzar.")

# Para ejecutar si es el script principal (opcional, para pruebas locales)
if __name__ == '__main__':
    # Esto es solo para prueba, Streamlit normalmente maneja la ejecución.
    # Necesitarías configurar un entorno de Streamlit para verlo.
    # Ejemplo: streamlit run tu_archivo.py
    st.set_page_config(layout="wide")
    display_other_feature_ui()
