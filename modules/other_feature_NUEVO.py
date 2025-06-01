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
# from selenium.webdriver.chrome.service import Service as ChromeService # Para webdriver-manager
# from webdriver_manager.chrome import ChromeDriverManager # Para webdriver-manager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, ElementClickInterceptedException, NoSuchElementException

# --- CONFIGURACIÓN GLOBAL ---
BASE_URL_OF = "https://live18.nowgoal25.com"
SELENIUM_TIMEOUT_SECONDS_OF = 20
SELENIUM_POLL_FREQUENCY_OF = 0.2

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

    if numeric_value == 0.0:
        return "0"
    
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

def get_match_details_from_row_of(row_element, score_class_selector='score', source_table_type='h2h'):
    try:
        cells = row_element.find_all('td')
        min_cells_required = 0
        if source_table_type == 'hist':
            ah_idx = 5 
            min_cells_required = 6 
        elif source_table_type == 'h2h':
            ah_idx = 11
            min_cells_required = 12
        else:
            ah_idx = 11 
            min_cells_required = 12

        if len(cells) < min_cells_required:
            return None
            
        league_id_hist_attr = row_element.get('name')
        home_idx, score_idx, away_idx = 2, 3, 4

        home_tag = cells[home_idx].find('a')
        home = home_tag.text.strip() if home_tag else cells[home_idx].text.strip()
        
        away_tag = cells[away_idx].find('a')
        away = away_tag.text.strip() if away_tag else cells[away_idx].text.strip()
        
        score_cell_content = cells[score_idx].text.strip()
        score_span = cells[score_idx].find('span', class_=lambda x: x and score_class_selector in x)
        score_raw_text = score_span.text.strip() if score_span else score_cell_content
        
        score_m = re.match(r'(\d+-\d+)', score_raw_text)
        score_raw = score_m.group(1) if score_m else '?-?'
        score_fmt = score_raw.replace('-', '*') if score_raw != '?-?' else '?*?'
        
        ah_cell = cells[ah_idx]
        ah_data_o = ah_cell.get("data-o")
        
        ah_line_raw_text = "-"
        if ah_data_o and ah_data_o.strip() and ah_data_o.strip() not in ['-', '?']:
            ah_line_raw_text = ah_data_o.strip()
        else:
            cell_text = ah_cell.text.strip()
            if cell_text and cell_text not in ['-', '?']:
                 ah_line_raw_text = cell_text

        ah_line_fmt = format_ah_as_decimal_string_of(ah_line_raw_text) 
        
        if not home or not away: 
            return None
            
        return {
            'home': home, 'away': away, 
            'score': score_fmt, 'score_raw': score_raw,
            'ahLine': ah_line_fmt, 'ahLine_raw': ah_line_raw_text,
            'matchIndex': row_element.get('index'), 
            'vs': row_element.get('vs'),
            'league_id_hist': league_id_hist_attr
        }
    except IndexError:
        return None
    except Exception:
        return None

# --- REQUESTS Y SELENIUM HELPERS ---
@st.cache_resource
def get_requests_session_of():
    session = requests.Session()
    retries_req = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    adapter_req = HTTPAdapter(max_retries=retries_req)
    session.mount("https://", adapter_req); session.mount("http://", adapter_req)
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36"})
    return session

@st.cache_data(ttl=3600) # Cache for 1 hour
def fetch_soup_requests_of(path, max_tries=3, delay=1):
    session = get_requests_session_of(); url = f"{BASE_URL_OF}{path}"
    for attempt in range(1, max_tries + 1):
        try:
            resp = session.get(url, timeout=10); resp.raise_for_status()
            return BeautifulSoup(resp.content, "lxml") # Using resp.content and lxml
        except requests.RequestException:
            if attempt == max_tries: return None
            time.sleep(delay * attempt)
    return None

@st.cache_resource 
def get_selenium_driver_of():
    options = ChromeOptions(); options.add_argument("--headless"); options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage"); options.add_argument("--disable-gpu")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36")
    options.add_argument('--blink-settings=imagesEnabled=false'); options.add_argument("--window-size=1920,1080")
    try: 
        # If using webdriver-manager:
        # return webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)
        # If ChromeDriver is in PATH or specified elsewhere:
        return webdriver.Chrome(options=options)
    except WebDriverException as e: 
        st.error(f"Error inicializando Selenium driver (OF): {e}. Asegúrate que ChromeDriver está instalado y en tu PATH.")
        return None

def click_element_robust_of(driver, by, value, timeout=7):
    try:
        element = WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.presence_of_element_located((by, value)))
        WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.visibility_of(element))
        # Scroll into view with JS, slight delay, then try clickable, then JS click
        driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'center'});", element)
        time.sleep(0.3) # Wait for scroll and potential overlays to clear
        try:
            # Try to wait for element to be clickable and click
            WebDriverWait(driver, 2, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.element_to_be_clickable((by, value))).click()
        except (ElementClickInterceptedException, TimeoutException):
            # If intercepted or not clickable directly, use JS click
            driver.execute_script("arguments[0].click();", element)
        return True
    except Exception:
        return False

# --- FUNCIONES DE EXTRACCIÓN DE DATOS ---
@st.cache_data(ttl=3600)
def get_rival_a_for_original_h2h_of(main_match_id: int): # Rival de Home
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

@st.cache_data(ttl=3600)
def get_rival_b_for_original_h2h_of(main_match_id: int): # Rival de Away
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

def get_h2h_details_for_original_logic_of(driver_instance, key_match_id_for_h2h_url, rival_a_id, rival_b_id, rival_a_name="Rival A", rival_b_name="Rival B"):
    if not driver_instance: return {"status": "error", "resultado": "N/A (Driver no disponible H2H OF)"}
    if not key_match_id_for_h2h_url or not rival_a_id or not rival_b_id: return {"status": "error", "resultado": f"N/A (IDs incompletos para H2H {rival_a_name} vs {rival_b_name})"}
    
    url_to_visit = f"{BASE_URL_OF}/match/h2h-{key_match_id_for_h2h_url}"
    try:
        driver_instance.get(url_to_visit)
        WebDriverWait(driver_instance, SELENIUM_TIMEOUT_SECONDS_OF, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.presence_of_element_located((By.ID, "table_v2")))
        time.sleep(0.7) # Small delay for JS rendering if any
        soup_selenium = BeautifulSoup(driver_instance.page_source, "html.parser")
    except TimeoutException: return {"status": "error", "resultado": f"N/A (Timeout esperando table_v2 en {url_to_visit})"}
    except Exception as e: return {"status": "error", "resultado": f"N/A (Error Selenium en {url_to_visit}: {type(e).__name__})"}

    if not soup_selenium: return {"status": "error", "resultado": f"N/A (Fallo soup Selenium H2H Original OF en {url_to_visit})"}
    
    table_to_search_h2h = soup_selenium.find("table", id="table_v2") 
    if not table_to_search_h2h: return {"status": "error", "resultado": f"N/A (Tabla v2 para H2H no encontrada en {url_to_visit})"}

    for row in table_to_search_h2h.find_all("tr", id=re.compile(r"tr2_\d+")): 
        links = row.find_all("a", onclick=True); 
        if len(links) < 2: continue # Need at least home and away team links
        
        h2h_row_home_id_m = re.search(r"team\((\d+)\)", links[0].get("onclick", ""))
        h2h_row_away_id_m = re.search(r"team\((\d+)\)", links[1].get("onclick", ""))
        
        if not h2h_row_home_id_m or not h2h_row_away_id_m: continue
            
        h2h_row_home_id = h2h_row_home_id_m.group(1)
        h2h_row_away_id = h2h_row_away_id_m.group(1)

        # Check if this row is the H2H match between rival_a_id and rival_b_id
        if {h2h_row_home_id, h2h_row_away_id} == {str(rival_a_id), str(rival_b_id)}:
            score_span = row.find("span", class_="fscore_2") # Score is in class fscore_2 for table_v2
            if not score_span or not score_span.text or "-" not in score_span.text: continue
            
            score_val = score_span.text.strip().split("(")[0].strip() # Get "X-Y" from "X-Y (Z-W)"
            g_h, g_a = score_val.split("-", 1)
            
            tds = row.find_all("td")
            handicap_raw = "N/A"
            HANDICAP_TD_IDX = 11 # This index might need to be dynamic if the table varies significantly
            
            if len(tds) > HANDICAP_TD_IDX:
                cell = tds[HANDICAP_TD_IDX]
                d_o = cell.get("data-o") 
                handicap_raw = d_o.strip() if d_o and d_o.strip() not in ["", "-"] else (cell.text.strip() if cell.text.strip() not in ["", "-"] else "N/A")

            rol_a_in_this_h2h = "H" if h2h_row_home_id == str(rival_a_id) else "A"
            
            return {
                "status": "found", 
                "goles_home": g_h.strip(), 
                "goles_away": g_a.strip(), 
                "handicap": handicap_raw, 
                "rol_rival_a": rol_a_in_this_h2h,
                "h2h_home_team_name": links[0].text.strip(),
                "h2h_away_team_name": links[1].text.strip()
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
        if h_id_m: home_id = h_id_m.group(1)
        if g_id_m: away_id = g_id_m.group(1)
        if sclass_id_m: league_id = sclass_id_m.group(1)
        if h_name_m: home_name = h_name_m.group(1).replace("\\'", "'")
        if g_name_m: away_name = g_name_m.group(1).replace("\\'", "'")
        if l_name_m: league_name = l_name_m.group(1).replace("\\'", "'")
    return home_id, away_id, league_id, home_name, away_name, league_name

def extract_last_match_in_league_of(driver, table_css_id_str, main_team_name_in_table, league_id_filter_value, home_or_away_filter_css_selector, is_home_game_filter):
    try:
        # 1. Navigate to the H2H page (assuming driver is not already there or needs reset)
        # The caller should ensure driver is on the /match/h2h-MATCH_ID page first.
        # For safety, one could re-navigate, but it adds overhead.
        # Example: driver.get(f"{BASE_URL_OF}/match/h2h-{some_main_match_id_passed_here}")
        # WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS_OF).until(EC.presence_of_element_located((By.ID, table_css_id_str)))

        # 2. Click league filter if league_id_filter_value is provided
        if league_id_filter_value:
            league_checkbox_selector = f"input#checkboxleague{table_css_id_str[-1]}[value='{league_id_filter_value}']"
            # st.write(f"Attempting to click league filter: {league_checkbox_selector}") # Debug
            if not click_element_robust_of(driver, By.CSS_SELECTOR, league_checkbox_selector):
                # st.warning(f"Could not click league filter {league_checkbox_selector}") # Debug
                pass # Continue even if click fails, might still find match if it's default
            time.sleep(1.0) # Wait for table to update

        # 3. Click Home/Away filter
        # st.write(f"Attempting to click H/A filter: {home_or_away_filter_css_selector}") # Debug
        if not click_element_robust_of(driver, By.CSS_SELECTOR, home_or_away_filter_css_selector):
            # st.warning(f"Could not click H/A filter {home_or_away_filter_css_selector}") # Debug
            return None # If this crucial filter fails, likely won't find the correct match
        time.sleep(1.0) # Wait for table to update

        page_source_updated = driver.page_source
        soup_updated = BeautifulSoup(page_source_updated, "html.parser")
        
        table = soup_updated.find("table", id=table_css_id_str)
        if not table: 
            # st.warning(f"Table {table_css_id_str} not found after filtering.") # Debug
            return None

        count_visible_rows = 0
        for row in table.find_all("tr", id=re.compile(rf"tr{table_css_id_str[-1]}_\d+")):
            if row.get("style") and "display:none" in row.get("style","").lower(): 
                continue # Skip hidden rows
            
            count_visible_rows +=1
            # if count_visible_rows > 10: break # Limit search to avoid excessive parsing if logic is off
            
            # Check league ID directly on the row if league_id_filter_value was used
            if league_id_filter_value and row.get("name") != str(league_id_filter_value):
                continue

            tds = row.find_all("td")
            if len(tds) < 6: continue # Need at least Date, Home, Score, Away, HDP

            home_team_row_el = tds[2].find("a")
            away_team_row_el = tds[4].find("a")
            
            if not home_team_row_el or not away_team_row_el: continue
            
            home_team_row_name = home_team_row_el.text.strip()
            away_team_row_name = away_team_row_el.text.strip()

            # Check if the main_team_name_in_table is playing in the correct role (Home/Away)
            team_is_home_in_row = main_team_name_in_table.lower() == home_team_row_name.lower()
            team_is_away_in_row = main_team_name_in_table.lower() == away_team_row_name.lower()
            
            correct_role_match = (is_home_game_filter and team_is_home_in_row) or \
                                 (not is_home_game_filter and team_is_away_in_row)

            if correct_role_match:
                date_span = tds[1].find("span", {"name": "timeData"})
                date_raw = date_span.get("data-time").split(" ")[0] if date_span and date_span.get("data-time") else tds[1].text.strip() # "YYYY-MM-DD HH:MM:SS" -> "YYYY-MM-DD"
                try:
                    # Reformat date from YYYY-MM-DD to DD-MM-YYYY
                    year, month, day = date_raw.split('-')
                    date = f"{day}-{month}-{year}"
                except:
                    date = date_raw # fallback to original if parsing fails

                score_class_re = re.compile(r"fscore_") 
                score_span = tds[3].find("span", class_=score_class_re)
                score = score_span.text.strip().split("(")[0].strip() if score_span else "N/A"
                
                # Handicap is usually in the 6th td (index 5) for these tables (table_v1, table_v2)
                handicap_cell_idx = 5 
                handicap_raw = "N/A"
                if len(tds) > handicap_cell_idx:
                    handicap_cell = tds[handicap_cell_idx] 
                    handicap_data_o = handicap_cell.get("data-o")
                    if handicap_data_o and handicap_data_o.strip() and handicap_data_o.strip() not in ['-', '?']:
                        handicap_raw = handicap_data_o.strip()
                    else:
                        cell_text_hdp = handicap_cell.text.strip()
                        if cell_text_hdp and cell_text_hdp not in ['-', '?']:
                             handicap_raw = cell_text_hdp
                
                return {
                    "date": date, 
                    "home_team": home_team_row_name, 
                    "away_team": away_team_row_name,
                    "score": score, 
                    "handicap_line_raw": handicap_raw
                }
        # st.warning(f"No matching game found for {main_team_name_in_table} in table {table_css_id_str} with filters.") # Debug
        return None # No match found after checking visible rows
    except Exception as e:
        # st.error(f"Exception in extract_last_match_in_league_of: {e}") # Debug
        return None

def get_main_match_odds_selenium_of(driver):
    odds_info = {"ah_home_cuota": "N/A", "ah_linea_raw": "N/A", "ah_away_cuota": "N/A", "goals_over_cuota": "N/A", "goals_linea_raw": "N/A", "goals_under_cuota": "N/A"}
    try:
        # Ensure liveCompareDiv is present (it usually contains the odds tables)
        live_compare_div = WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS_OF, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(
            EC.presence_of_element_located((By.ID, "liveCompareDiv"))
        )
        
        # Bet365 has company ID 8 or 31 typically for early odds.
        # Look for tr with id "tr_o_1_8" (live odds) or "tr_o_3_8" (early odds) or similar for Bet365 (ID 8)
        # The name attribute is "earlyOdds" for initial odds.
        bet365_row_selectors = [
            "tr#tr_o_1_8[name='earlyOdds']",  # Bet365 (ID 8) early odds (live table context)
            "tr#tr_o_3_8[name='earlyOdds']",  # Bet365 (ID 8) early odds (ended table context)
            "tr#tr_o_1_31[name='earlyOdds']", # Bet365 (ID 31) early odds
            "tr#tr_o_3_31[name='earlyOdds']", 
        ]
        
        table_odds = live_compare_div.find_element(By.XPATH, ".//table[contains(@class, 'team-table-other')]") # Main odds table
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", table_odds)
        time.sleep(0.5) # allow scrolling and rendering

        bet365_early_odds_row = None
        for selector in bet365_row_selectors:
            try:
                bet365_early_odds_row = WebDriverWait(driver, 3, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, selector))
                )
                if bet365_early_odds_row: break # Found it
            except TimeoutException:
                continue # Try next selector
        
        if not bet365_early_odds_row:
            return odds_info # Bet365 early odds row not found

        tds = bet365_early_odds_row.find_elements(By.TAG_NAME, "td")
        
        # Expected indices for early odds row:
        # Index 2: AH Home Odd (data-o or text)
        # Index 3: AH Line (data-o or text)
        # Index 4: AH Away Odd (data-o or text)
        # Index 8: O/U Over Odd (data-o or text)
        # Index 9: O/U Line (data-o or text)
        # Index 10: O/U Under Odd (data-o or text)
        
        if len(tds) >= 11: # Need at least 11 cells for all these odds
            odds_info["ah_home_cuota"] = tds[2].get_attribute("data-o") or tds[2].text.strip() or "N/A"
            odds_info["ah_linea_raw"] = tds[3].get_attribute("data-o") or tds[3].text.strip() or "N/A" 
            odds_info["ah_away_cuota"] = tds[4].get_attribute("data-o") or tds[4].text.strip() or "N/A"
            
            odds_info["goals_over_cuota"] = tds[8].get_attribute("data-o") or tds[8].text.strip() or "N/A"
            odds_info["goals_linea_raw"] = tds[9].get_attribute("data-o") or tds[9].text.strip() or "N/A" 
            odds_info["goals_under_cuota"] = tds[10].get_attribute("data-o") or tds[10].text.strip() or "N/A"
    except Exception:
        # Silently pass if any error occurs, returning default N/A values
        pass 
    return odds_info

def extract_standings_data_from_h2h_page_of(h2h_soup, target_team_name_exact):
    data = {
        "name": target_team_name_exact, "ranking": "N/A", 
        "total_pj": "N/A", "total_v": "N/A", "total_e": "N/A", "total_d": "N/A", 
        "total_gf": "N/A", "total_gc": "N/A", 
        "specific_pj": "N/A", "specific_v": "N/A", "specific_e": "N/A", "specific_d": "N/A", 
        "specific_gf": "N/A", "specific_gc": "N/A", 
        "specific_type": "N/A", "standings_status": "Not processed"
    }
    if not h2h_soup:
        data["standings_status"] = "Error: h2h_soup is None"; return data

    standings_section = h2h_soup.find("div", id="porletP4") 
    if not standings_section:
        data["standings_status"] = "Error: Standings section (div#porletP4) not found."; return data
    
    data["standings_status"] = "Standings section 'porletP4' found, processing..."
    team_table_soup = None; is_home_team_table_type = False

    home_div_standings = standings_section.find("div", class_="home-div")
    if home_div_standings:
        home_table_header = home_div_standings.find("tr", class_="team-home")
        if home_table_header and target_team_name_exact and target_team_name_exact.lower() in home_table_header.get_text().lower(): 
            team_table_soup = home_div_standings.find("table", class_="team-table-home")
            is_home_team_table_type = True
            specific_type_cell = home_div_standings.find("td", class_="bg1")
            data["specific_type"] = specific_type_cell.text.strip() if specific_type_cell else "En Casa"

    if not team_table_soup:
        guest_div_standings = standings_section.find("div", class_="guest-div")
        if guest_div_standings:
            guest_table_header = guest_div_standings.find("tr", class_="team-guest")
            if guest_table_header and target_team_name_exact and target_team_name_exact.lower() in guest_table_header.get_text().lower(): 
                team_table_soup = guest_div_standings.find("table", class_="team-table-guest")
                is_home_team_table_type = False
                specific_type_cell = guest_div_standings.find("td", class_="bg1")
                data["specific_type"] = specific_type_cell.text.strip() if specific_type_cell else "Fuera"
    
    if not team_table_soup:
        data["standings_status"] = "Warning: Standings table for target team not found in 'porletP4'."; return data

    header_row_found = team_table_soup.find("tr", class_=re.compile(r"team-(home|guest)")) 
    if header_row_found:
        link = header_row_found.find("a")
        if link:
            full_text = link.get_text(separator=" ", strip=True)
            name_match = re.search(r"]\s*(.*)", full_text)
            rank_match = re.search(r"\[(?:[^\]]+-)?(\d+)\]", full_text)
            if name_match: data["name"] = name_match.group(1).strip()
            if rank_match: data["ranking"] = rank_match.group(1)
        else: 
            header_text_no_link = header_row_found.get_text(separator=" ", strip=True)
            name_match_nl = re.search(r"]\s*(.*)", header_text_no_link)
            if name_match_nl: data["name"] = name_match_nl.group(1).strip()
            rank_match_nl = re.search(r"\[(?:[^\]]+-)?(\d+)\]", header_text_no_link)
            if rank_match_nl: data["ranking"] = rank_match_nl.group(1)

    ft_rows_cells_list = []
    current_section_is_ft = False
    for row in team_table_soup.find_all("tr", align="center"): 
        th_cell = row.find("th")
        if th_cell:
            th_text = th_cell.get_text(strip=True)
            if "FT" in th_text: current_section_is_ft = True
            elif "HT" in th_text: current_section_is_ft = False; break 
        
        if current_section_is_ft:
            cells = row.find_all("td")
            if cells and len(cells) > 0 and cells[0].get_text(strip=True) in ["Total", "Home", "Away", "Last 6"]: # Added "Last 6"
                ft_rows_cells_list.append(cells)

    if not ft_rows_cells_list:
        data["standings_status"] = "Warning: No FT statistics rows found."; return data

    parsed_stats = False
    for cells_in_row in ft_rows_cells_list:
        if len(cells_in_row) > 8: # Type, PJ, V, E, D, GF, GC, Pts, %
            row_type_text = cells_in_row[0].get_text(strip=True)
            stats_values = [(cells_in_row[i].get_text(strip=True) if cells_in_row[i].get_text(strip=True) else "N/A") for i in range(1, 7)]
            pj, v, e, d, gf, gc = stats_values

            if row_type_text == "Total":
                data["total_pj"], data["total_v"], data["total_e"], data["total_d"], data["total_gf"], data["total_gc"] = pj,v,e,d,gf,gc
                parsed_stats = True
            elif row_type_text == "Home" and is_home_team_table_type:
                data["specific_pj"],data["specific_v"],data["specific_e"],data["specific_d"],data["specific_gf"],data["specific_gc"] = pj,v,e,d,gf,gc
                parsed_stats = True
            elif row_type_text == "Away" and not is_home_team_table_type:
                data["specific_pj"],data["specific_v"],data["specific_e"],data["specific_d"],data["specific_gf"],data["specific_gc"] = pj,v,e,d,gf,gc
                parsed_stats = True
    
    if parsed_stats: data["standings_status"] = "Success: Standings data extracted."
    else: data["standings_status"] = "Warning: Relevant stats rows (Total/Home/Away) not found/parsed."
    return data

def extract_final_score_of(soup):
    try:
        # Try to find score in <div id="mScore"> ... <div class="end"> <span class="score">HS</span> <span class="score">AS</span>
        mscore_div = soup.find('div', id='mScore')
        if mscore_div:
            end_div = mscore_div.find('div', class_='end')
            if end_div:
                score_spans = end_div.find_all('span', class_='score')
                if len(score_spans) == 2:
                    hs = score_spans[0].text.strip()
                    aws = score_spans[1].text.strip()
                    if hs.isdigit() and aws.isdigit():
                        return f"{hs}*{aws}", f"{hs}-{aws}"
        
        # Fallback for slightly different structures if the above fails
        # e.g. if score is directly in some other identifiable element
        # This part might need adjustment based on actual HTML of finished matches
        # For now, keeping it simple.
    except Exception:
        pass # Silently fail
    return '?*?', "?-?"


def extract_comparative_match_of(soup_for_team_history, table_id_of_team_to_search, team_name_to_find_match_for, opponent_name_to_search, current_league_id, is_home_table):
    default_return = {'found': False, 'ahLine': '-', 'score_raw': '?-?', 'home': 'N/A', 'away': 'N/A'}
    if not opponent_name_to_search or opponent_name_to_search == "N/A" or not team_name_to_find_match_for:
        return default_return
        
    table = soup_for_team_history.find("table", id=table_id_of_team_to_search)
    if not table: return default_return
    
    score_class_selector = 'fscore_1' if is_home_table else 'fscore_2'
    
    for row in table.find_all("tr", id=re.compile(rf"tr{table_id_of_team_to_search[-1]}_\d+")):
        details = get_match_details_from_row_of(row, score_class_selector=score_class_selector, source_table_type='hist')
        if not details: continue
        
        if current_league_id and details.get('league_id_hist') and details.get('league_id_hist') != str(current_league_id):
            continue
            
        home_hist = details.get('home','').lower()
        away_hist = details.get('away','').lower()
        team_main_lower = team_name_to_find_match_for.lower()
        opponent_lower = opponent_name_to_search.lower()
        
        is_match_of_interest = (team_main_lower == home_hist and opponent_lower == away_hist) or \
                               (team_main_lower == away_hist and opponent_lower == home_hist)
                               
        if is_match_of_interest:
            return {
                'ahLine': details.get('ahLine', '-'), 
                'score_raw': details.get('score_raw', '?-?'), 
                'home': details.get('home'), 
                'away': details.get('away'), 
                'found': True
            }
            
    return default_return

def extract_standings_from_team_page_of(team_page_soup, target_team_name, target_league_name, specific_focus="Total"):
    data = {
        "name": target_team_name, "ranking": "N/A",
        "pj": "N/A", "v": "N/A", "e": "N/A", "d": "N/A",
        "gf": "N/A", "gc": "N/A",
        "specific_type_found": specific_focus,
        "status": "Not processed"
    }
    if not team_page_soup:
        data["status"] = "Error: team_page_soup is None"
        return data

    team_point_div = team_page_soup.find("div", id="teamPointDiv")
    if not team_point_div:
        data["status"] = "Error: div#teamPointDiv not found"
        return data

    league_tables = team_point_div.find_all("table", class_="tdlink")
    found_league_table = None
    for table in league_tables:
        caption = table.find("caption")
        if caption and target_league_name and target_league_name.lower() in caption.text.lower():
            found_league_table = table
            break
    
    if not found_league_table:
        if league_tables: # Fallback to first table if specific league not found
            found_league_table = league_tables[0]
            # data["status"] = "Warning: Target league not found, using first available table." # Too verbose
        else:
            data["status"] = "Error: No league tables found in teamPointDiv."
            return data

    caption_text = found_league_table.find("caption").text if found_league_table.find("caption") else ""
    rank_match = re.search(r"\[(\d+)\]", caption_text) 
    if rank_match: data["ranking"] = rank_match.group(1)
    else:
        rank_match_long = re.search(r"\[(?:.*?-)?(\d+)\]", caption_text)
        if rank_match_long: data["ranking"] = rank_match_long.group(1)

    stat_row_to_parse = None; rows = found_league_table.find_all("tr")
    focus_label_map = {"Total": "Overall", "En Casa": "Home", "Fuera": "Away"}
    target_label = focus_label_map.get(specific_focus, "Overall")

    for row in rows:
        tds = row.find_all("td")
        if tds and len(tds) > 1 and tds[0].text.strip() == target_label:
            stat_row_to_parse = tds
            data["specific_type_found"] = specific_focus
            break
    
    if not stat_row_to_parse and specific_focus != "Total": # Fallback to "Total"
        for row in rows:
            tds = row.find_all("td")
            if tds and len(tds) > 1 and tds[0].text.strip() == "Overall":
                stat_row_to_parse = tds
                data["specific_type_found"] = "Total"
                # data["status"] = f"Warning: '{specific_focus}' stats not found, fell back to 'Total'." # Too verbose
                break

    if stat_row_to_parse and len(stat_row_to_parse) >= 7: # Label, PJ, W, D, L, GF, GA
        try:
            data["pj"] = stat_row_to_parse[1].text.strip(); data["v"]  = stat_row_to_parse[2].text.strip()
            data["e"]  = stat_row_to_parse[3].text.strip(); data["d"]  = stat_row_to_parse[4].text.strip()
            data["gf"] = stat_row_to_parse[5].text.strip(); data["gc"] = stat_row_to_parse[6].text.strip()
            if data["status"] == "Not processed": data["status"] = "Success: Standings extracted."
        except IndexError: data["status"] = "Error: Not enough cells in stats row."
    elif not stat_row_to_parse : data["status"] = "Error: Could not find relevant stat row."
    return data


# --- STREAMLIT APP UI ---
def display_other_feature_ui():
    st.set_page_config(layout="wide")
    st.markdown("""
        <style>
            body { font-family: 'Inter', sans-serif; }
            .stApp { /* background-color: #f0f2f6; */ }
            .card { background-color: #ffffff; border: 1px solid #e1e4e8; border-radius: 6px; padding: 12px; margin-bottom: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.04); }
            .section-title { font-size: 1em; font-weight: bold; color: #24292e; margin-bottom: 6px; }
            .match-score-ah { font-size: 0.9em; margin-bottom: 4px; }
            .match-score-ah .score { font-weight: bold; color: #d73a49; }
            .match-score-ah .ah { background-color: #f1f8ff; color: #0366d6; padding: 2px 5px; border-radius: 8px; font-weight: 500; border: 1px solid #0366d630; font-size: 0.85em; }
            .date-text { font-size: 0.75em; color: #586069; margin-bottom: 6px; }
            .description-text { font-size: 0.8em; color: #444d56; line-height: 1.3; }
            .team-name-home { color: #0366d6; font-weight: bold; }
            .team-name-away { color: #e36209; font-weight: bold; }
            div[data-testid="stMetric"] { background-color: #ffffff; border: 1px solid #e1e4e8; border-radius: 6px; padding: 8px; text-align: center; }
            div[data-testid="stMetric"] label { font-size: 0.8em; color: #586069; font-weight: 500; }
            div[data-testid="stMetric"] div[data-testid="stMetricValue"] { font-size: 1.1em; font-weight: bold; color: #24292e; }
            .st-emotion-cache-ue6h3e summary { font-size: 1.05em !important; font-weight: 600 !important; color: #0366d6 !important; }
            .st-emotion-cache-ue6h3e summary:hover { color: #005cc5 !important; }
            .main-title { text-align: left; color: #24292e; font-size: 1.5em; font-weight: bold; margin-bottom: 15px; }
            .stats-text { font-size: 0.85em; color: #333; line-height: 1.5; }
            .stat-label {font-weight: 500; color: #454545;}
        </style>
    """, unsafe_allow_html=True)

    if 'show_final_score' not in st.session_state:
        st.session_state.show_final_score = False

    st.markdown("<h1 class='main-title'>⚡ Rendimiento Reciente y Contexto H2H (Indirecto)</h1>", unsafe_allow_html=True)
    
    st.sidebar.image("https://raw.githubusercontent.com/streamlit/docs/main/public/images/brand/streamlit-logo-secondary-colormark-darktext.svg", width=180)
    st.sidebar.title("Configuración (OF)")
    main_match_id_str_input_of = st.sidebar.text_input(
        "🆔 ID Partido Principal:", value="2696131", # Example: Melbourne Victory FC (Youth) vs Heidelberg United
        help="Pega el ID numérico del partido.", key="other_feature_match_id_input"
    )
    analizar_button_of = st.sidebar.button("🚀 Analizar Partido", type="primary", use_container_width=True)

    if analizar_button_of:
        if main_match_id_str_input_of.isdigit():
            match_id = int(main_match_id_str_input_of)
            status_placeholder = st.empty()
            status_placeholder.info(f"🚀 Iniciando análisis para ID: {match_id}...")
            driver = None
            try:
                h2h_page_path = f"/match/h2h-{match_id}"
                main_h2h_soup = fetch_soup_requests_of(h2h_page_path)
                if not main_h2h_soup:
                    status_placeholder.error(f"❌ No se pudo obtener H2H para ID {match_id} (Requests)."); return

                home_id, away_id, league_id, home_name, away_name, league_name = get_team_league_info_from_script_of(main_h2h_soup)
                
                if home_name == "N/A" or away_name == "N/A": # Fallback with Selenium for names
                    status_placeholder.warning(f"⚠️ Nombres no extraídos de H2H. Intentando con Selenium...")
                    driver = get_selenium_driver_of()
                    if driver:
                        live_page_url = f"{BASE_URL_OF}/match/live-{match_id}"
                        try:
                            driver.get(live_page_url)
                            WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS_OF).until(EC.presence_of_element_located((By.ID, "fbheader")))
                            live_soup_selenium_for_names = BeautifulSoup(driver.page_source, "html.parser")
                            home_id, away_id, league_id, home_name, away_name, league_name = get_team_league_info_from_script_of(live_soup_selenium_for_names)
                        except Exception as e_live: status_placeholder.error(f"❌ Error obteniendo nombres de Live: {e_live}")
                    else: status_placeholder.error("❌ Driver Selenium no disponible para fallback de nombres.")
                
                if home_name == "N/A" or away_name == "N/A":
                    status_placeholder.error(f"❌ Nombres no extraídos. Análisis detenido."); return
                
                status_placeholder.info(f"Partido: {home_name} vs {away_name}. Obteniendo rivales...")
                key_match_id_h2h_rival_a, rival_a_id, rival_a_name = get_rival_a_for_original_h2h_of(match_id)
                key_match_id_h2h_rival_b, rival_b_id, rival_b_name = get_rival_b_for_original_h2h_of(match_id)

                last_home_match_info, last_away_match_info = None, None
                rivals_h2h_info = {"status": "error", "resultado": "N/A"}

                if not driver : # Initialize driver if not already
                    status_placeholder.info("🔄 Obteniendo driver Selenium para análisis detallado...")
                    driver = get_selenium_driver_of()

                if driver:
                    # Navigate to main H2H page once for last match extractions
                    driver.get(f"{BASE_URL_OF}/match/h2h-{match_id}")
                    try:
                        WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS_OF).until(EC.presence_of_element_located((By.ID, "table_v1"))) # wait for a table
                    except TimeoutException:
                        status_placeholder.warning("Timeout esperando tablas en página H2H principal.")
                    
                    status_placeholder.info(f"🔍 Extrayendo último partido de {home_name} (Casa)...")
                    if home_name != "N/A" and league_id:
                        last_home_match_info = extract_last_match_in_league_of(driver, "table_v1", home_name, league_id, "#homeAwayCheckboxs1_h", True)
                    
                    status_placeholder.info(f"🔍 Extrayendo último partido de {away_name} (Fuera)...")
                    if away_name != "N/A" and league_id:
                        last_away_match_info = extract_last_match_in_league_of(driver, "table_v2", away_name, league_id, "#homeAwayCheckboxs2_a", False)
                    
                    status_placeholder.info(f"🆚 Extrayendo H2H entre {rival_a_name or 'Rival A'} y {rival_b_name or 'Rival B'}...")
                    if key_match_id_h2h_rival_a and rival_a_id and rival_b_id:
                        rivals_h2h_info = get_h2h_details_for_original_logic_of(driver, key_match_id_h2h_rival_a, rival_a_id, rival_b_id, rival_a_name, rival_b_name)
                else: status_placeholder.warning("⚠️ Driver Selenium no disponible. Faltarán datos.")

                # --- Display Top 3 Columns ---
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.markdown("<div class='card'>", unsafe_allow_html=True)
                    st.markdown(f"<div class='section-title'>Último <span class='team-name-home'>{home_name}</span> (Casa)</div>", unsafe_allow_html=True)
                    opp_home = last_home_match_info.get('away_team', rival_a_name or "Rival") if last_home_match_info else (rival_a_name or "Rival")
                    st.markdown(f"🆚 <span class='team-name-away'>{opp_home}</span>", unsafe_allow_html=True)
                    if last_home_match_info:
                        score = last_home_match_info.get('score', 'N/A').replace('-', ':')
                        ah = format_ah_as_decimal_string_of(last_home_match_info.get('handicap_line_raw', 'N/A'))
                        st.markdown(f"<div class='match-score-ah'><span class='team-name-home'>{last_home_match_info.get('home_team','H')}</span> <span class='score'>{score}</span> <span class='team-name-away'>{last_home_match_info.get('away_team','A')}</span></div>", unsafe_allow_html=True)
                        st.markdown(f"<div class='match-score-ah'>AH: <span class='ah'>{ah}</span></div>", unsafe_allow_html=True)
                        st.markdown(f"<div class='date-text'>🗓️ {last_home_match_info.get('date', 'N/A')}</div>", unsafe_allow_html=True)
                    else: st.markdown("<div class='match-score-ah'>AH: <span class='ah'>N/A</span></div>", unsafe_allow_html=True)
                    st.markdown("<div class='description-text'>Último partido del equipo local jugado en casa en esta misma liga.</div></div>", unsafe_allow_html=True)

                with col2:
                    st.markdown("<div class='card'>", unsafe_allow_html=True)
                    st.markdown(f"<div class='section-title'>Último <span class='team-name-away'>{away_name}</span> (Fuera)</div>", unsafe_allow_html=True)
                    opp_away = last_away_match_info.get('home_team', rival_b_name or "Rival") if last_away_match_info else (rival_b_name or "Rival")
                    st.markdown(f"🆚 <span class='team-name-home'>{opp_away}</span>", unsafe_allow_html=True)
                    if last_away_match_info:
                        score = last_away_match_info.get('score', 'N/A').replace('-', ':')
                        ah = format_ah_as_decimal_string_of(last_away_match_info.get('handicap_line_raw', 'N/A'))
                        st.markdown(f"<div class='match-score-ah'><span class='team-name-home'>{last_away_match_info.get('home_team','H')}</span> <span class='score'>{score}</span> <span class='team-name-away'>{last_away_match_info.get('away_team','A')}</span></div>", unsafe_allow_html=True)
                        st.markdown(f"<div class='match-score-ah'>AH: <span class='ah'>{ah}</span></div>", unsafe_allow_html=True)
                        st.markdown(f"<div class='date-text'>🗓️ {last_away_match_info.get('date', 'N/A')}</div>", unsafe_allow_html=True)
                    else: st.markdown("<div class='match-score-ah'>AH: <span class='ah'>N/A</span></div>", unsafe_allow_html=True)
                    st.markdown("<div class='description-text'>Último partido del equipo visitante jugado fuera en esta misma liga.</div></div>", unsafe_allow_html=True)

                with col3:
                    st.markdown("<div class='card'>", unsafe_allow_html=True)
                    r_a = rival_a_name or 'Rival A'; r_b = rival_b_name or 'Rival B'
                    st.markdown(f"<div class='section-title'>🆚 H2H Rivales (Col3)</div>", unsafe_allow_html=True)
                    if rivals_h2h_info and rivals_h2h_info.get("status") == "found":
                        h2h_home = rivals_h2h_info.get('h2h_home_team_name', r_a)
                        h2h_away = rivals_h2h_info.get('h2h_away_team_name', r_b)
                        score = f"{rivals_h2h_info.get('goles_home', '?')}:{rivals_h2h_info.get('goles_away', '?')}"
                        ah = format_ah_as_decimal_string_of(rivals_h2h_info.get('handicap', 'N/A'))
                        st.markdown(f"<div class='match-score-ah'><span class='team-name-home'>{h2h_home}</span> <span class='score'>{score}</span> <span class='team-name-away'>{h2h_away}</span></div>", unsafe_allow_html=True)
                        st.markdown(f"<div class='match-score-ah'>AH: <span class='ah'>{ah}</span></div>", unsafe_allow_html=True)
                    else: 
                        st.markdown(f"<div class='match-score-ah'><span class='team-name-home'>{r_a}</span> <span class='score'>?:?</span> <span class='team-name-away'>{r_b}</span></div>", unsafe_allow_html=True)
                        st.markdown("<div class='match-score-ah'>AH: <span class='ah'>N/A</span></div>", unsafe_allow_html=True)
                    st.markdown(f"<div class='description-text'>Enfrentamiento directo entre {r_a} y {r_b}.</div></div>", unsafe_allow_html=True)
                
                st.markdown("---")

                # --- Standings Sections ---
                with st.expander("📊 Estadísticas Detalladas de Equipos (Resumen)", expanded=False):
                    standings_home = extract_standings_data_from_h2h_page_of(main_h2h_soup, home_name)
                    standings_away = extract_standings_data_from_h2h_page_of(main_h2h_soup, away_name)
                    scol1, scol2 = st.columns(2)
                    with scol1:
                        st.markdown(f"##### <span class='team-name-home'>{home_name}</span>", unsafe_allow_html=True)
                        if standings_home.get("standings_status", "").startswith("Success"):
                            st.markdown(f"<p class='stats-text'><span class='stat-label'>🏅 Rk:</span> {standings_home.get('ranking', 'N/A')} | <span class='stat-label'>🏠 {standings_home.get('specific_type','N/A')}</span></p>", unsafe_allow_html=True)
                            st.markdown(f"<p class='stats-text'><span class='stat-label'>T:</span> {standings_home.get('total_pj','N/A')}PJ | {standings_home.get('total_v','N/A')}V/{standings_home.get('total_e','N/A')}E/{standings_home.get('total_d','N/A')}D | {standings_home.get('total_gf','N/A')}GF-{standings_home.get('total_gc','N/A')}GC</p>", unsafe_allow_html=True)
                            st.markdown(f"<p class='stats-text'><span class='stat-label'>L:</span> {standings_home.get('specific_pj','N/A')}PJ | {standings_home.get('specific_v','N/A')}V/{standings_home.get('specific_e','N/A')}E/{standings_home.get('specific_d','N/A')}D | {standings_home.get('specific_gf','N/A')}GF-{standings_home.get('specific_gc','N/A')}GC</p>", unsafe_allow_html=True)
                        else: st.caption(f"No se cargaron estadísticas para {home_name}.")
                    with scol2:
                        st.markdown(f"##### <span class='team-name-away'>{away_name}</span>", unsafe_allow_html=True)
                        if standings_away.get("standings_status", "").startswith("Success"):
                            st.markdown(f"<p class='stats-text'><span class='stat-label'>🏅 Rk:</span> {standings_away.get('ranking', 'N/A')} | <span class='stat-label'>✈️ {standings_away.get('specific_type','N/A')}</span></p>", unsafe_allow_html=True)
                            st.markdown(f"<p class='stats-text'><span class='stat-label'>T:</span> {standings_away.get('total_pj','N/A')}PJ | {standings_away.get('total_v','N/A')}V/{standings_away.get('total_e','N/A')}E/{standings_away.get('total_d','N/A')}D | {standings_away.get('total_gf','N/A')}GF-{standings_away.get('total_gc','N/A')}GC</p>", unsafe_allow_html=True)
                            st.markdown(f"<p class='stats-text'><span class='stat-label'>V:</span> {standings_away.get('specific_pj','N/A')}PJ | {standings_away.get('specific_v','N/A')}V/{standings_away.get('specific_e','N/A')}E/{standings_away.get('specific_d','N/A')}D | {standings_away.get('specific_gf','N/A')}GF-{standings_away.get('specific_gc','N/A')}GC</p>", unsafe_allow_html=True)
                        else: st.caption(f"No se cargaron estadísticas para {away_name}.")

                with st.expander("📈 Clasificación Oponentes Indirectos (H2H Col3)", expanded=False):
                    rcol1, rcol2 = st.columns(2)
                    with rcol1:
                        st.markdown(f"##### <span class='team-name-home'>{rival_a_name or 'Rival A'}</span>", unsafe_allow_html=True)
                        if rival_a_id and rival_a_name != "N/A":
                            rival_a_team_page_soup = fetch_soup_requests_of(f"/team/htanalyse-{rival_a_id}.html")
                            rival_a_stats = extract_standings_from_team_page_of(rival_a_team_page_soup, rival_a_name, league_name, specific_focus="Fuera") # As per image: Hume City "Fuera"
                            if rival_a_stats.get("status", "").startswith("Success"):
                                st.markdown(f"<p class='stats-text'><span class='stat-label'>🏅 Rk:</span> {rival_a_stats.get('ranking', 'N/A')} | <span class='stat-label'>{rival_a_stats.get('specific_type_found', 'N/A')}</span></p>", unsafe_allow_html=True)
                                st.markdown(f"<p class='stats-text'><span class='stat-label'>{rival_a_stats.get('specific_type_found', 'N/A')}:</span> {rival_a_stats.get('pj','N/A')}PJ | {rival_a_stats.get('v','N/A')}V/{rival_a_stats.get('e','N/A')}E/{rival_a_stats.get('d','N/A')}D | {rival_a_stats.get('gf','N/A')}GF-{rival_a_stats.get('gc','N/A')}GC</p>", unsafe_allow_html=True)
                            else: st.caption(f"No se cargaron stats para {rival_a_name}.")
                        else: st.caption("Rival A no identificado.")
                    with rcol2:
                        st.markdown(f"##### <span class='team-name-away'>{rival_b_name or 'Rival B'}</span>", unsafe_allow_html=True)
                        if rival_b_id and rival_b_name != "N/A":
                            rival_b_team_page_soup = fetch_soup_requests_of(f"/team/htanalyse-{rival_b_id}.html")
                            rival_b_stats = extract_standings_from_team_page_of(rival_b_team_page_soup, rival_b_name, league_name, specific_focus="En Casa") # As per image: Oakleigh "En Casa"
                            if rival_b_stats.get("status", "").startswith("Success"):
                                st.markdown(f"<p class='stats-text'><span class='stat-label'>🏅 Rk:</span> {rival_b_stats.get('ranking', 'N/A')} | <span class='stat-label'>{rival_b_stats.get('specific_type_found', 'N/A')}</span></p>", unsafe_allow_html=True)
                                st.markdown(f"<p class='stats-text'><span class='stat-label'>{rival_b_stats.get('specific_type_found', 'N/A')}:</span> {rival_b_stats.get('pj','N/A')}PJ | {rival_b_stats.get('v','N/A')}V/{rival_b_stats.get('e','N/A')}E/{rival_b_stats.get('d','N/A')}D | {rival_b_stats.get('gf','N/A')}GF-{rival_b_stats.get('gc','N/A')}GC</p>", unsafe_allow_html=True)
                            else: st.caption(f"No se cargaron stats para {rival_b_name}.")
                        else: st.caption("Rival B no identificado.")
                
                with st.expander("🔍 Comparativas Indirectas Detalladas", expanded=False):
                    c_col1, c_col2 = st.columns(2)
                    with c_col1:
                        st.markdown(f"**<span class='team-name-home'>{home_name}</span> vs. Últ. Rival del <span class='team-name-away'>{away_name}</span>**", unsafe_allow_html=True)
                        if rival_b_name and rival_b_name != "N/A":
                            st.caption(f"Partido de {home_name} vs {rival_b_name} (últ. rival de {away_name})")
                            comp = extract_comparative_match_of(main_h2h_soup, "table_v1", home_name, rival_b_name, league_id, is_home_table=True)
                            st.metric("Resultado", comp.get('score_raw', '?-?').replace('-',':'))
                            st.metric("AH (Partido Comparado)", comp.get('ahLine', '-'))
                        else: st.metric("AH (Partido Comparado)", "-"); st.caption(f"No se encontró rival para {away_name}.")
                    with c_col2:
                        st.markdown(f"**<span class='team-name-away'>{away_name}</span> vs. Últ. Rival del <span class='team-name-home'>{home_name}</span>**", unsafe_allow_html=True)
                        if rival_a_name and rival_a_name != "N/A":
                            st.caption(f"Partido de {away_name} vs {rival_a_name} (últ. rival de {home_name})")
                            comp = extract_comparative_match_of(main_h2h_soup, "table_v2", away_name, rival_a_name, league_id, is_home_table=False)
                            st.metric("Resultado", comp.get('score_raw', '?-?').replace('-',':'))
                            st.metric("AH (Partido Comparado)", comp.get('ahLine', '-'))
                        else: st.metric("AH (Partido Comparado)", "-"); st.caption(f"No se encontró rival para {home_name}.")

                with st.expander("💰 Cuotas Iniciales Bet365 y Marcador Final", expanded=False):
                    odds = {"ah_linea_raw": "N/A", "goals_linea_raw": "N/A"}
                    final_score_raw = "?-?"
                    if driver:
                        status_placeholder.info("📊 Obteniendo cuotas y marcador final...")
                        driver.get(f"{BASE_URL_OF}/match/h2h-{match_id}") # Ensure driver is on page with odds info
                        try:
                            WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS_OF).until(EC.presence_of_element_located((By.ID, "liveCompareDiv")))
                            odds = get_main_match_odds_selenium_of(driver)
                            current_soup = BeautifulSoup(driver.page_source, "html.parser")
                            _, final_score_raw = extract_final_score_of(current_soup)
                        except Exception as e_odds: st.caption(f"No se obtuvieron cuotas/marcador: {e_odds}")
                    
                    st.markdown("##### Cuotas Iniciales (Bet365)")
                    q_c1,q_c2,q_c3 = st.columns(3); q_c4,q_c5,q_c6 = st.columns(3)
                    q_c1.metric("Local (AH)", odds.get('ah_home_cuota', 'N/A'))
                    q_c2.metric("H. Asiático (AH)", f"[{format_ah_as_decimal_string_of(odds.get('ah_linea_raw', 'N/A'))}]")
                    q_c3.metric("Visitante (AH)", odds.get('ah_away_cuota', 'N/A'))
                    q_c4.metric("Over (Goles)", odds.get('goals_over_cuota', 'N/A'))
                    q_c5.metric("Línea Goles (O/U)", f"[{odds.get('goals_linea_raw', 'N/A')}]")
                    q_c6.metric("Under (Goles)", odds.get('goals_under_cuota', 'N/A'))
                    
                    st.markdown("---")
                    st.markdown("##### Marcador Final del Partido Principal")
                    if st.button("👁️ Mostrar Marcador Final", key="show_score_btn"):
                        st.session_state.show_final_score = not st.session_state.show_final_score
                    
                    if st.session_state.show_final_score:
                        st.metric(f"Resultado: {home_name} vs {away_name}", final_score_raw.replace('-',':') if final_score_raw != "?-?" else "No Disponible")
                    else: st.info("Clic para revelar marcador (si disponible).")

                status_placeholder.success("🎉 Análisis completado.")
            except Exception as e:
                st.exception(e) 
                status_placeholder.error(f"❌ Error crítico: {type(e).__name__} - {e}")
            finally:
                if driver: driver.quit()
                status_placeholder.empty()
        else: st.sidebar.error("ID de partido debe ser numérico.")
    else: st.info("ℹ️ Introduce ID y haz clic en 'Analizar Partido'.")

if __name__ == "__main__":
    display_other_feature_ui()
