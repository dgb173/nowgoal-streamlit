# modules/other_feature.py
import streamlit as st
import time
import requests
import re
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
BASE_URL_OF = "https://live18.nowgoal25.com"
SELENIUM_TIMEOUT_SECONDS_OF = 20
SELENIUM_POLL_FREQUENCY_OF = 0.2

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
        except requests.RequestException:
            if attempt == max_tries: return None
            time.sleep(delay * attempt)
    return None

# --- FUNCIONES PARA LÓGICA ORIGINAL DE H2H (Columna 3) (renombradas) ---
@st.cache_data(ttl=3600)
def get_rival_a_for_original_h2h_of(main_match_id, soup_h2h_page): # Acepta soup
    if not soup_h2h_page: return None, None, None
    table = soup_h2h_page.find("table", id="table_v1")
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

@st.cache_data(ttl=3600)
def get_rival_b_for_original_h2h_of(main_match_id, soup_h2h_page): # Acepta soup
    if not soup_h2h_page: return None, None
    table = soup_h2h_page.find("table", id="table_v2")
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
        st.error(f"SELENIUM DRIVER ERROR (Other Feature): {e}")
        return None

def get_h2h_details_for_original_logic_of(driver_instance, key_match_id_for_h2h_url, rival_a_id, rival_b_id): 
    if not driver_instance: return {"status": "error", "resultado": "N/A (Driver no disponible H2H OF)"}
    if not key_match_id_for_h2h_url or not rival_a_id or not rival_b_id:
        return {"status": "error", "resultado": "N/A (IDs incompletos para H2H Original OF)"}

    url = f"{BASE_URL_OF}/match/h2h-{key_match_id_for_h2h_url}"
    try:
        driver_instance.get(url)
        WebDriverWait(driver_instance, SELENIUM_TIMEOUT_SECONDS_OF, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(
            EC.presence_of_element_located((By.ID, "table_v2")) 
        )
        time.sleep(0.7)
        soup_selenium = BeautifulSoup(driver_instance.page_source, "html.parser")
    except Exception as e:
        return {"status": "error", "resultado": f"N/A (Error Selenium H2H Original OF: {type(e).__name__})"}

    if not soup_selenium: return {"status": "error", "resultado": "N/A (Fallo soup Selenium H2H Original OF)"}
    table = soup_selenium.find("table", id="table_v2") 
    if not table: return {"status": "error", "resultado": "N/A (Tabla H2H Original OF no encontrada)"}

    for row in table.find_all("tr", id=re.compile(r"tr2_\d+")):
        links = row.find_all("a", onclick=True)
        if len(links) < 2: continue
        h2h_rhid_m = re.search(r"team\((\d+)\)", links[0].get("onclick", ""))
        h2h_raid_m = re.search(r"team\((\d+)\)", links[1].get("onclick", ""))
        if not h2h_rhid_m or not h2h_raid_m: continue
        h2h_rhid, h2h_raid = h2h_rhid_m.group(1), h2h_raid_m.group(1)
        h2h_rhname, h2h_raname = links[0].text.strip(), links[1].text.strip()

        if {h2h_rhid, h2h_raid} == {str(rival_a_id), str(rival_b_id)}:
            score_span = row.find("span", class_="fscore_2") 
            if not score_span or not score_span.text or "-" not in score_span.text: continue
            score_val = score_span.text.strip()
            g_h, g_a = score_val.split("-", 1)
            tds = row.find_all("td")
            handicap_val = "N/A"
            HANDICAP_TD_IDX = 11
            if len(tds) > HANDICAP_TD_IDX:
                cell = tds[HANDICAP_TD_IDX]
                d_o = cell.get("data-o"); handicap_val = d_o.strip() if d_o and d_o.strip() not in ["", "-"] else (cell.text.strip() if cell.text.strip() not in ["", "-"] else "N/A")

            rol_a = "A" if h2h_raid == str(rival_a_id) else "H"
            return {
                "status": "found", "goles_home": g_h.strip(), "goles_away": g_a.strip(),
                "handicap": handicap_val, "rol_rival_a": rol_a,
                "h2h_home_team_name": h2h_rhname, "h2h_away_team_name": h2h_raname
            }
    return {"status": "not_found", "resultado": "N/A (H2H Original OF no encontrado en tabla)"}

# --- FUNCIONES PARA NUEVA LÓGICA (renombradas) ---
def get_team_league_info_from_script_of(soup):
    home_id, away_id, league_id, home_name, away_name, league_name = (None,)*3 + ("N/A",)*3
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

def click_element_robust_of(driver, by, value, timeout=7):
    try:
        element = WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(
            EC.presence_of_element_located((by, value))
        )
        WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(
            EC.visibility_of(element)
        )
        driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'center'});", element)
        time.sleep(0.3)
        try:
            WebDriverWait(driver, 2, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(
                EC.element_to_be_clickable((by, value))
            ).click()
        except (ElementClickInterceptedException, TimeoutException):
            driver.execute_script("arguments[0].click();", element)
        return True
    except Exception:
        return False

def extract_last_match_in_league_of(driver, table_css_id_str, main_team_name_in_table, league_id_filter_value,
                                 home_or_away_filter_css_selector, is_home_game_filter):
    try:
        league_checkbox_selector = f"input#checkboxleague{table_css_id_str[-1]}[value='{league_id_filter_value}']"
        if league_id_filter_value:
            click_element_robust_of(driver, By.CSS_SELECTOR, league_checkbox_selector)
            time.sleep(1.5)
        click_element_robust_of(driver, By.CSS_SELECTOR, home_or_away_filter_css_selector)
        time.sleep(1.5)

        page_source_updated = driver.page_source
        soup_updated = BeautifulSoup(page_source_updated, "html.parser")
        table = soup_updated.find("table", id=table_css_id_str)
        if not table: return None

        for row_idx, row in enumerate(table.find_all("tr", id=re.compile(rf"tr{table_css_id_str[-1]}_\d+"))):
            if row.get("style") and "display:none" in row.get("style","").lower(): continue
            if row_idx > 7: break
            if league_id_filter_value and row.get("name") != str(league_id_filter_value): continue

            tds = row.find_all("td")
            if len(tds) < 14: continue

            home_team_row_el = tds[2].find("a")
            away_team_row_el = tds[4].find("a")
            if not home_team_row_el or not away_team_row_el: continue

            home_team_row_name = home_team_row_el.text.strip()
            away_team_row_name = away_team_row_el.text.strip()

            team_is_home_in_row = main_team_name_in_table == home_team_row_name
            team_is_away_in_row = main_team_name_in_table == away_team_row_name

            if (is_home_game_filter and team_is_home_in_row) or \
               (not is_home_game_filter and team_is_away_in_row):
                date_span = tds[1].find("span", {"name": "timeData"})
                date = date_span.text.strip() if date_span else "N/A"
                score_span = tds[3].find("span", class_=re.compile(r"fscore_"))
                score = score_span.text.strip() if score_span else "N/A"

                handicap_cell = tds[11]
                handicap = handicap_cell.get("data-o", handicap_cell.text.strip())
                if not handicap or handicap.strip() == "-": handicap = "N/A"
                else: handicap = handicap.strip()
                return {
                    "date": date, "home_team": home_team_row_name, "away_team": away_team_row_name,
                    "score": score, "handicap_line": handicap,
                }
        return None
    except Exception:
        return None

def get_main_match_odds_selenium_of(driver):
    odds_info = {
        "ah_home_cuota": "N/A", "ah_linea": "N/A", "ah_away_cuota": "N/A",
        "goals_over_cuota": "N/A", "goals_linea": "N/A", "goals_under_cuota": "N/A"
    }
    try:
        live_compare_div = WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS_OF, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(
            EC.presence_of_element_located((By.ID, "liveCompareDiv"))
        )
        bet365_row_selector = "tr#tr_o_1_8[name='earlyOdds']"
        bet365_row_selector_alt = "tr#tr_o_1_31[name='earlyOdds']" 

        table_odds = live_compare_div.find_element(By.XPATH, ".//table[contains(@class, 'team-table-other')]")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", table_odds)
        time.sleep(0.5)

        bet365_early_odds_row = None
        try:
            bet365_early_odds_row = WebDriverWait(driver, 5, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, bet365_row_selector))
            )
        except TimeoutException:
             bet365_early_odds_row = WebDriverWait(driver, 3, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, bet365_row_selector_alt))
            )

        tds = bet365_early_odds_row.find_elements(By.TAG_NAME, "td")
        if len(tds) >= 11:
            odds_info["ah_home_cuota"] = tds[2].get_attribute("data-o") or tds[2].text.strip() or "N/A"
            odds_info["ah_linea"] = tds[3].get_attribute("data-o") or tds[3].text.strip() or "N/A"
            odds_info["ah_away_cuota"] = tds[4].get_attribute("data-o") or tds[4].text.strip() or "N/A"
            odds_info["goals_over_cuota"] = tds[8].get_attribute("data-o") or tds[8].text.strip() or "N/A"
            odds_info["goals_linea"] = tds[9].get_attribute("data-o") or tds[9].text.strip() or "N/A"
            odds_info["goals_under_cuota"] = tds[10].get_attribute("data-o") or tds[10].text.strip() or "N/A"
    except Exception:
        pass
    return odds_info

def get_standings_data_of(soup, team_name_exact):
    """Intenta extraer el ranking de la tabla de Standings (porletP4)."""
    data = {"ranking": "N/A"}
    standings_div = soup.find("div", id="porletP4")
    if not standings_div:
        return data

    # Busca la tabla específica del equipo (home o guest)
    team_table = None
    home_table_div = standings_div.find("div", class_="home-div")
    if home_table_div and team_name_exact in home_table_div.get_text():
        team_table = home_table_div.find("table", class_="team-table-home")
    
    if not team_table:
        guest_table_div = standings_div.find("div", class_="guest-div")
        if guest_table_div and team_name_exact in guest_table_div.get_text():
            team_table = guest_table_div.find("table", class_="team-table-guest")

    if team_table:
        # Buscar la fila de 'Total' bajo 'FT'
        rows = team_table.find_all("tr", align="center")
        ft_total_row_found = False
        for row in rows:
            cells = row.find_all("td")
            if cells and cells[0].get_text(strip=True) == "Total":
                # Esta es la fila FT Total
                if len(cells) > 8: # Necesitamos hasta la celda de Rank
                    rank_val = cells[8].get_text(strip=True)
                    data["ranking"] = rank_val if rank_val else "N/A"
                break # Encontramos la fila de Total bajo FT
    return data


def calculate_record_from_history_table_of(table_soup, team_name_perspective, condition):
    """Calcula PJ, V, E, D, GF, GC de una tabla de historial de partidos."""
    stats = {"pj": 0, "v": 0, "e": 0, "d": 0, "gf": 0, "gc": 0}
    if not table_soup:
        return stats

    match_rows = table_soup.find_all("tr", id=re.compile(r"tr[12]_\d+"))

    for row in match_rows:
        if row.get("style") and "display:none" in row.get("style", "").lower():
            continue

        cells = row.find_all("td")
        if len(cells) < 5:  # Necesitamos al menos hasta la celda del equipo visitante
            continue

        row_home_team_tag = cells[2].find("a")
        row_away_team_tag = cells[4].find("a")
        score_tag = cells[3].find("span", class_=re.compile(r"fscore_"))

        if not row_home_team_tag or not row_away_team_tag or not score_tag:
            continue

        row_home_team_name = row_home_team_tag.get_text(strip=True)
        row_away_team_name = row_away_team_tag.get_text(strip=True)
        score_text = score_tag.get_text(strip=True).split("(")[0].strip() # Tomar solo el score FT

        try:
            goals_home_str, goals_away_str = score_text.split("-")
            goals_home = int(goals_home_str)
            goals_away = int(goals_away_str)
        except ValueError:
            continue # No se pudo parsear el score

        is_target_home = (team_name_perspective == row_home_team_name)
        is_target_away = (team_name_perspective == row_away_team_name)

        if not is_target_home and not is_target_away:
            continue # El equipo no jugó en este partido (raro para estas tablas, pero por si acaso)

        # Filtrar por condición (home/away) si no es 'total'
        if condition == "home" and not is_target_home:
            continue
        if condition == "away" and not is_target_away:
            continue
        
        stats["pj"] += 1
        if is_target_home:
            stats["gf"] += goals_home
            stats["gc"] += goals_away
            if goals_home > goals_away: stats["v"] += 1
            elif goals_home == goals_away: stats["e"] += 1
            else: stats["d"] += 1
        elif is_target_away:
            stats["gf"] += goals_away
            stats["gc"] += goals_home
            if goals_away > goals_home: stats["v"] += 1
            elif goals_away == goals_home: stats["e"] += 1
            else: stats["d"] += 1
            
    return stats


# --- STREAMLIT APP UI (Envuelto en una función) ---
def display_other_feature_ui():
    st.title("🏆 Análisis Visual de Partidos - (Other Feature)")
    # st.info("Contenido específico de 'Otra Funcionalidad (Beta)'") # Se puede quitar si se llena con datos

    main_match_id_str_input_of = st.sidebar.text_input(
        "🆔 ID Partido (OF):", value="2778085",
        help="Pega el ID del partido para análisis en Other Feature.",
        key="other_feature_match_id_input"
    )
    analizar_button_of = st.sidebar.button("🚀 Analizar Partido (OF)", type="secondary", use_container_width=True, key="other_feature_analizar_button")

    if 'driver_other_feature' not in st.session_state:
         st.session_state.driver_other_feature = None

    if analizar_button_of:
        main_match_id_to_process_of = None
        if main_match_id_str_input_of:
            try:
                cleaned_id_str = "".join(filter(str.isdigit, main_match_id_str_input_of))
                if cleaned_id_str: main_match_id_to_process_of = int(cleaned_id_str)
            except ValueError: st.error("⚠️ ID de partido no válido (OF)."); st.stop()

        if not main_match_id_to_process_of:
            st.warning("⚠️ Ingresa un ID de partido válido (OF).")
        else:
            start_time_of = time.time()
            
            with st.spinner("Obteniendo datos generales y de clasificación (OF)..."):
                main_page_url_h2h_view_of = f"/match/h2h-{main_match_id_to_process_of}"
                soup_main_h2h_page_of = fetch_soup_requests_of(main_page_url_h2h_view_of)

            if not soup_main_h2h_page_of:
                st.error("No se pudo obtener la página H2H (OF). El análisis no puede continuar.")
                st.stop()

            mp_home_id_of, mp_away_id_of, mp_league_id_of, mp_home_name_of, mp_away_name_of, mp_league_name_of = \
                get_team_league_info_from_script_of(soup_main_h2h_page_of)

            st.markdown(f"### 📋 {mp_home_name_of or 'Local'} vs {mp_away_name_of or 'Visitante'}")
            # st.markdown(f"**Liga (OF):** {mp_league_name_of or 'N/A'} (ID Liga: {mp_league_id_of or 'N/A'})")


            # Obtener y mostrar datos calculados y de ranking
            # LOCAL TEAM STATS
            if mp_home_name_of and mp_home_name_of != "N/A":
                st.markdown(f"--- **{mp_home_name_of} (Local)** ---")
                standings_home = get_standings_data_of(soup_main_h2h_page_of, mp_home_name_of)
                rank_home = standings_home.get("ranking", "N/A")

                table_v1_soup = soup_main_h2h_page_of.find("table", id="table_v1") # Previous Scores para el local del partido
                
                stats_home_total = calculate_record_from_history_table_of(table_v1_soup, mp_home_name_of, "total")
                stats_home_specific = calculate_record_from_history_table_of(table_v1_soup, mp_home_name_of, "home")
                
                st.markdown(f"🏆 Rk: {rank_home}")
                st.markdown(f"🌍 T: {stats_home_total['pj']}|{stats_home_total['v']}/{stats_home_total['e']}/{stats_home_total['d']}|{stats_home_total['gf']}-{stats_home_total['gc']}")
                st.markdown(f"🏠 En Casa: {stats_home_specific['pj']}|{stats_home_specific['v']}/{stats_home_specific['e']}/{stats_home_specific['d']}|{stats_home_specific['gf']}-{stats_home_specific['gc']}")
            
            # AWAY TEAM STATS
            if mp_away_name_of and mp_away_name_of != "N/A":
                st.markdown(f"--- **{mp_away_name_of} (Visitante)** ---")
                standings_away = get_standings_data_of(soup_main_h2h_page_of, mp_away_name_of)
                rank_away = standings_away.get("ranking", "N/A")
                
                table_v2_soup = soup_main_h2h_page_of.find("table", id="table_v2") # Previous Scores para el visitante del partido

                stats_away_total = calculate_record_from_history_table_of(table_v2_soup, mp_away_name_of, "total")
                stats_away_specific = calculate_record_from_history_table_of(table_v2_soup, mp_away_name_of, "away")
                
                st.markdown(f"🏆 Rk: {rank_away}")
                st.markdown(f"🌍 T: {stats_away_total['pj']}|{stats_away_total['v']}/{stats_away_total['e']}/{stats_away_total['d']}|{stats_away_total['gf']}-{stats_away_total['gc']}")
                st.markdown(f"✈️ Fuera: {stats_away_specific['pj']}|{stats_away_specific['v']}/{stats_away_specific['e']}/{stats_away_specific['d']}|{stats_away_specific['gf']}-{stats_away_specific['gc']}")
            
            st.markdown("---")


            main_match_odds_data_of = {}
            last_home_match_in_league_of = None
            last_away_match_in_league_of = None

            key_h2h_url_for_orig_col3_of, rival_a_id_orig_col3_of, rival_a_name_orig_col3_of = get_rival_a_for_original_h2h_of(main_match_id_to_process_of, soup_main_h2h_page_of)
            rival_b_id_orig_col3_of, rival_b_name_orig_col3_of = get_rival_b_for_original_h2h_of(main_match_id_to_process_of, soup_main_h2h_page_of)

            driver_actual_of = st.session_state.driver_other_feature
            driver_of_needs_init = False
            if driver_actual_of is None:
                driver_of_needs_init = True
            else:
                try:
                    _ = driver_actual_of.window_handles
                    if hasattr(driver_actual_of, 'service') and driver_actual_of.service and not driver_actual_of.service.is_connectable():
                       driver_of_needs_init = True
                except WebDriverException:
                    driver_of_needs_init = True

            if driver_of_needs_init:
                if driver_actual_of is not None:
                    try: driver_actual_of.quit()
                    except: pass
                with st.spinner("🚘 Inicializando WebDriver (OF)..."):
                    driver_actual_of = get_selenium_driver_of()
                st.session_state.driver_other_feature = driver_actual_of


            if driver_actual_of:
                try:
                    with st.spinner("Accediendo a datos detallados con Selenium (OF)..."):
                        driver_actual_of.get(f"{BASE_URL_OF}{main_page_url_h2h_view_of}")
                        WebDriverWait(driver_actual_of, SELENIUM_TIMEOUT_SECONDS_OF).until(
                            EC.presence_of_element_located((By.ID, "table_v1"))
                        )
                        time.sleep(0.5) # Pausa para renderizado completo
                        page_source_for_selenium_extras = driver_actual_of.page_source # Guardar page source para extracciones adicionales
                        
                        main_match_odds_data_of = get_main_match_odds_selenium_of(driver_actual_of)

                        # Re-parsear la página obtenida por Selenium para asegurar que los filtros de JS se aplicaron
                        soup_selenium_page = BeautifulSoup(page_source_for_selenium_extras, 'html.parser')


                        if mp_home_id_of and mp_league_id_of and mp_home_name_of!="N/A":
                            last_home_match_in_league_of = extract_last_match_in_league_of(
                                driver_actual_of, # Pasar el driver
                                "table_v1", # ID de la tabla del equipo local
                                mp_home_name_of,
                                mp_league_id_of,
                                "input#cb_sos1[value='1']", # Selector para el filtro "Home" del equipo local
                                is_home_game_filter=True
                            )
                        if mp_away_id_of and mp_league_id_of and mp_away_name_of!="N/A":
                            last_away_match_in_league_of = extract_last_match_in_league_of(
                                driver_actual_of, # Pasar el driver
                                "table_v2", # ID de la tabla del equipo visitante
                                mp_away_name_of,
                                mp_league_id_of,
                                "input#cb_sos2[value='2']", # Selector para el filtro "Away" del equipo visitante
                                is_home_game_filter=False
                            )
                except Exception as e_main_sel_of:
                     st.error(f"Error Selenium en pág. principal (OF): {type(e_main_sel_of).__name__} - {str(e_main_sel_of)[:100]}")
            else:
                st.error("No se pudo iniciar driver Selenium para datos de página principal (OF).")

            st.markdown("#### Betting Odds Bet365 (Iniciales del Partido Principal OF)")
            col_odds1_of, col_odds2_of = st.columns(2)
            with col_odds1_of:
                st.markdown(f"**H. Asiático (OF):** `{main_match_odds_data_of.get('ah_home_cuota','N/A')}` <span style='color:blue; font-weight:bold;'>[{main_match_odds_data_of.get('ah_linea','N/A')}]</span> `{main_match_odds_data_of.get('ah_away_cuota','N/A')}`", unsafe_allow_html=True)
            with col_odds2_of:
                st.markdown(f"**Línea Goles (OF):** `Ov {main_match_odds_data_of.get('goals_over_cuota','N/A')}` <span style='color:red; font-weight:bold;'>[{main_match_odds_data_of.get('goals_linea','N/A')}]</span> `Un {main_match_odds_data_of.get('goals_under_cuota','N/A')}`", unsafe_allow_html=True)
            st.markdown("---")

            st.markdown("### ⚔️ Análisis Detallado (OF) - Partidos Seleccionados")
            col1of, col2of, col3of = st.columns(3)

            with col1of:
                st.markdown(f"##### <span style='color:#4CAF50;'>🏡 Último de {mp_home_name_of or 'Local'} (OF)</span><br>(Casa, Misma Liga)", unsafe_allow_html=True)
                if last_home_match_in_league_of:
                    res = last_home_match_in_league_of
                    st.markdown(f"{res['home_team']} **{res['score']}** {res['away_team']}")
                    st.markdown(f"**AH:** <span style='font-weight:bold;'>{res['handicap_line']}</span>", unsafe_allow_html=True)
                    st.caption(f"{res['date']}")
                else: st.info("No encontrado (OF).")

            with col2of:
                st.markdown(f"##### <span style='color:#2196F3;'>✈️ Último de {mp_away_name_of or 'Visitante'} (OF)</span><br>(Fuera, Misma Liga)", unsafe_allow_html=True)
                if last_away_match_in_league_of:
                    res = last_away_match_in_league_of
                    st.markdown(f"{res['home_team']} **{res['score']}** {res['away_team']}")
                    st.markdown(f"**AH:** <span style='font-weight:bold;'>{res['handicap_line']}</span>", unsafe_allow_html=True)
                    st.caption(f"{res['date']}")
                else: st.info("No encontrado (OF).")

            with col3of:
                st.markdown(f"##### <span style='color:#E65100;'>🆚 H2H Oponentes (OF)</span><br>(Método Original)", unsafe_allow_html=True)
                rival_a_col3_name_of = rival_a_name_orig_col3_of if rival_a_name_orig_col3_of and rival_a_name_orig_col3_of != "N/A" else (rival_a_id_orig_col3_of or "Rival A")
                rival_b_col3_name_of = rival_b_name_orig_col3_of if rival_b_name_orig_col3_of and rival_b_name_orig_col3_of != "N/A" else (rival_b_id_orig_col3_of or "Rival B")

                details_h2h_col3_of = {"status": "error", "resultado": "N/A (OF)"}
                if key_h2h_url_for_orig_col3_of and rival_a_id_orig_col3_of and rival_b_id_orig_col3_of and driver_actual_of: 
                    with st.spinner(f"H2H Original (OF): {rival_a_col3_name_of} vs {rival_b_col3_name_of}..."):
                        details_h2h_col3_of = get_h2h_details_for_original_logic_of(driver_actual_of, key_h2h_url_for_orig_col3_of, rival_a_id_orig_col3_of, rival_b_id_orig_col3_of)

                if details_h2h_col3_of.get("status") == "found":
                    res_h2h = details_h2h_col3_of
                    h2h_p_home_name = res_h2h.get("h2h_home_team_name", "Local H2H (OF)")
                    h2h_p_away_name = res_h2h.get("h2h_away_team_name", "Visitante H2H (OF)")
                    g_h_h2h = res_h2h['goles_home']
                    g_a_h2h = res_h2h['goles_away']
                    rol_a_en_h2h = res_h2h['rol_rival_a']
                    handicap_h2h_val = res_h2h['handicap']

                    resultado_display = f"{g_h_h2h}-{g_a_h2h}"

                    if rol_a_en_h2h == 'H':
                        equipo1_info = f"{rival_a_col3_name_of} (Local)"
                        equipo2_info = f"{rival_b_col3_name_of} (Visitante)"
                    else:
                        equipo1_info = f"{rival_b_col3_name_of} (Local)"
                        equipo2_info = f"{rival_a_col3_name_of} (Visitante)"

                    output_str = f"{equipo1_info} **{resultado_display}** / ({handicap_h2h_val}) {equipo2_info}"
                    st.markdown(f"<p style='font-size:1.0em; font-weight:bold; color:#E65100;'>{output_str}</p>", unsafe_allow_html=True)
                else:
                    st.info(f"H2H Oponentes (OF): {details_h2h_col3_of.get('resultado', 'No disponible')}")
                st.caption(f"H2H entre (op. generales OF): {rival_a_col3_name_of} & {rival_b_col3_name_of}")

            end_time_of = time.time() 
            st.markdown("---")
            st.caption(f"⏱️ Tiempo total del análisis (OF): {end_time_of - start_time_of:.2f} segundos")
    else:
        st.info("✨ Ingresa un ID de partido en la barra lateral (OF) y haz clic en 'Analizar Partido (OF)' para comenzar.")
