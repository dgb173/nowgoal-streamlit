# streamlit_app.py

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

# --- CONFIGURACIÓN GLOBAL ---
BASE_URL = "https://live18.nowgoal25.com"
SELENIUM_TIMEOUT_SECONDS = 15 # Ajustado para rapidez, puede necesitar más
SELENIUM_POLL_FREQUENCY = 0.2 # Frecuencia de sondeo para WebDriverWait

# Configuración de la sesión de requests
@st.cache_resource 
def get_requests_session():
    session = requests.Session()
    retries_req = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    adapter_req = HTTPAdapter(max_retries=retries_req)
    session.mount("https://", adapter_req)
    session.mount("http://", adapter_req)
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36"})
    return session

# --- FUNCIONES DE REQUESTS ---
@st.cache_data(ttl=3600) 
def fetch_soup_requests(path, max_tries=3, delay=1):
    session = get_requests_session()
    url = f"{BASE_URL}{path}"
    for attempt in range(1, max_tries + 1):
        try:
            resp = session.get(url, timeout=10)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except requests.RequestException as e:
            if attempt == max_tries:
                st.error(f"Error final de Requests fetching {url}: {e}")
                return None
            time.sleep(delay * attempt)
    return None

@st.cache_data(ttl=3600)
def get_last_home(match_id): # Para el H2H entre rivales (método anterior)
    soup = fetch_soup_requests(f"/match/h2h-{match_id}")
    if not soup: return None, None
    table = soup.find("table", id="table_v1")
    if not table: return None, None
    for row in table.find_all("tr", id=re.compile(r"tr1_\d+")):
        if row.get("vs") == "1": # El equipo local del partido principal jugó en casa
            key_match_id = row.get("index") # ID del partido que jugó
            if not key_match_id: continue
            # El rival es el equipo visitante de esa fila
            onclicks = row.find_all("a", onclick=True) # tds[4] es el equipo visitante
            if len(onclicks) > 1 and onclicks[1].get("onclick") and "team" in onclicks[1]["onclick"]:
                rival_a_id_match = re.search(r"team\((\d+)\)", onclicks[1]["onclick"])
                if rival_a_id_match:
                    return key_match_id, rival_a_id_match.group(1) # Devuelve ID del partido e ID del rival
    return None, None

@st.cache_data(ttl=3600)
def get_last_away(match_id): # Para el H2H entre rivales (método anterior)
    soup = fetch_soup_requests(f"/match/h2h-{match_id}")
    if not soup: return None, None
    table = soup.find("table", id="table_v2") # Usar table_v2 para la perspectiva del equipo visitante
    if not table: return None, None
    # En la tabla del equipo visitante (originalmente table_v2), buscamos cuando el equipo local del partido principal (main_match_id)
    # jugó como VISITANTE. En esa fila, el RIVAL (oponente) será el equipo LOCAL de esa fila.
    # Sin embargo, tu lógica original para get_last_away usaba table_v2 pero con la lógica de 'vs' de table_v1.
    # Esto es para TU lógica específica de H2H: encontrar el oponente del equipo LOCAL del partido principal
    # cuando este jugó su último partido general como VISITANTE.
    # Este es el ID del equipo que era LOCAL cuando el equipo principal era VISITANTE.
    
    # Reinterpretando tu lógica original de get_last_away para el rival B:
    # Buscamos en la tabla de historial del EQUIPO LOCAL DEL PARTIDO PRINCIPAL (table_v1)
    # el último partido donde jugó como VISITANTE (vs="0"). El oponente (Rival B) será el equipo local de esa fila.
    table_home_history = soup.find("table", id="table_v1") # Usar la tabla del equipo local del partido principal
    if not table_home_history: return None, None
    for row in table_home_history.find_all("tr", id=re.compile(r"tr1_\d+")):
        if row.get("vs") == "0": # El equipo local del partido principal jugó como VISITANTE
            key_match_id = row.get("index") # ID del partido que jugó
            if not key_match_id: continue
            # El rival (Rival B) es el equipo local de esa fila (tds[2])
            onclicks = row.find_all("a", onclick=True)
            if len(onclicks) > 0 and onclicks[0].get("onclick") and "team" in onclicks[0]["onclick"]:
                rival_b_id_match = re.search(r"team\((\d+)\)", onclicks[0]["onclick"])
                if rival_b_id_match:
                    return key_match_id, rival_b_id_match.group(1) # Devuelve ID del partido e ID del rival
    return None, None


# --- FUNCIONES DE SELENIUM ---
def get_selenium_driver():
    options = ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36")
    options.add_argument('--blink-settings=imagesEnabled=false')
    options.add_argument("--window-size=1920,1080") # Puede ayudar con elementos ocultos
    try:
        driver = webdriver.Chrome(options=options)
        return driver
    except WebDriverException as e:
        st.error(f"SELENIUM DRIVER ERROR: {e}")
        return None

def get_h2h_details_selenium(key_match_id, rival_a_id, rival_b_id): # Tu función original para H2H
    if not key_match_id or not rival_a_id or not rival_b_id:
        return {"status": "error", "resultado": "N/A (IDs incompletos para H2H)"}
    url = f"{BASE_URL}/match/h2h-{key_match_id}"
    driver = get_selenium_driver()
    if not driver: return {"status": "error", "resultado": "N/A (Fallo Selenium Driver)"}
    soup_selenium = None
    try:
        driver.get(url)
        WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS, poll_frequency=SELENIUM_POLL_FREQUENCY).until(
            EC.presence_of_element_located((By.ID, "table_v2"))
        )
        time.sleep(0.7) # Aumentar un poco la pausa
        page_source = driver.page_source 
        soup_selenium = BeautifulSoup(page_source, "html.parser")
    except TimeoutException:
        return {"status": "error", "resultado": "N/A (Timeout Selenium H2H)"}
    except Exception as e:
        return {"status": "error", "resultado": f"N/A (Error Selenium H2H: {type(e).__name__})"}
    finally:
        if driver: driver.quit()
    if not soup_selenium: return {"status": "error", "resultado": "N/A (Fallo soup Selenium H2H)"}
    table = soup_selenium.find("table", id="table_v2") # Esta tabla es la de H2H entre los 2 equipos de la URL /match/h2h-{key_match_id}
    if not table: return {"status": "error", "resultado": "N/A (Tabla H2H no encontrada en Selenium)"}

    for row in table.find_all("tr", id=re.compile(r"tr2_\d+")): # Filas de la tabla H2H
        links = row.find_all("a", onclick=True)
        if len(links) < 2: continue
        home_id_match_search = re.search(r"team\((\d+)\)", links[0].get("onclick", ""))
        away_id_match_search = re.search(r"team\((\d+)\)", links[1].get("onclick", ""))
        if not home_id_match_search or not away_id_match_search: continue
        home_id_found_h2h = home_id_match_search.group(1)
        away_id_found_h2h = away_id_match_search.group(1)

        # Comprobar si esta fila del H2H es entre rival_a y rival_b
        if {home_id_found_h2h, away_id_found_h2h} == {str(rival_a_id), str(rival_b_id)}:
            score_span = row.find("span", class_="fscore_2")
            if not score_span or not score_span.text or "-" not in score_span.text: continue
            score = score_span.text.strip()
            goles_home_h2h, goles_away_h2h = score.split("-")
            tds = row.find_all("td")
            handicap = "N/A"
            # El índice para el hándicap en la tabla H2H (table_v2 de la página /match/h2h-matchid)
            # puede ser diferente. Suele ser [H, AH, A, AH_Res] -> AH es tds[6], AH_Res es tds[7]
            # Para tu formato "Goles*Goles/Handicap Rol"
            # Asumimos que el "Handicap" que buscas es la línea de AH
            # Si la estructura es Liga, Fecha, Local, Score, Visitante, Córner, H, AH_LINE, A, AH_Res, O/U
            # AH_LINE estaría en tds[7] (índice 7)
            HANDICAP_LINE_TD_INDEX_H2H = 7 
            if len(tds) > HANDICAP_LINE_TD_INDEX_H2H:
                celda_handicap = tds[HANDICAP_LINE_TD_INDEX_H2H]
                data_o_valor = celda_handicap.get("data-o")
                if data_o_valor is not None and data_o_valor.strip() != "" and data_o_valor.strip() != "-":
                    handicap = data_o_valor.strip()
                else:
                    texto_celda = celda_handicap.text.strip()
                    if texto_celda != "" and texto_celda != "-": handicap = texto_celda
            
            # Rol de Rival A en ESE partido H2H
            rol_rival_a_en_este_h2h = "A" if away_id_found_h2h == str(rival_a_id) else "H"
            return {
                "status": "found",
                "goles_home": goles_home_h2h, 
                "goles_away": goles_away_h2h, 
                "handicap": handicap,
                "rol_rival_a": rol_rival_a_en_este_h2h, 
                "raw_string": f"{goles_home_h2h}*{goles_away_h2h}/{handicap} {rol_rival_a_en_este_h2h}" 
            }
    return {"status": "not_found", "resultado": "N/A (H2H entre RivalA y RivalB no encontrado)"}


def get_team_league_info_from_script(soup):
    """Extrae IDs de equipos y liga del script _matchInfo."""
    home_id, away_id, league_id = None, None, None
    home_name, away_name, league_name = "N/A", "N/A", "N/A"
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
        if h_name_m: home_name = h_name_m.group(1)
        if g_name_m: away_name = g_name_m.group(1)
        if l_name_m: league_name = l_name_m.group(1)
    return home_id, away_id, league_id, home_name, away_name, league_name


def click_element_robust(driver, by, value, timeout=5):
    try:
        element = WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY).until(
            EC.element_to_be_clickable((by, value))
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", element) # Asegurar visibilidad
        time.sleep(0.3)
        driver.execute_script("arguments[0].click();", element)
        # element.click() # A veces falla por intercepción
        return True
    except TimeoutException:
        # st.warning(f"Timeout al esperar clickeable: {by}={value}")
        pass
    except ElementClickInterceptedException:
        # st.warning(f"Click interceptado para: {by}={value}. Reintentando con JS.")
        try:
            element = driver.find_element(by, value)
            driver.execute_script("arguments[0].click();", element)
            return True
        except Exception as e_js_click:
            # st.error(f"Fallo JS click en {by}={value}: {e_js_click}")
            pass
    except Exception as e_click:
        # st.error(f"Error al clickear {by}={value}: {e_click}")
        pass
    return False

def extract_last_match_in_league(driver, table_css_id_str, main_team_name_in_table, league_id_filter_value, 
                                 home_or_away_filter_css_selector, is_home_game_filter):
    try:
        # 1. Activar filtro "Same League"
        league_checkbox_selector = f"input#checkboxleague{table_css_id_str[-1]}[value='{league_id_filter_value}']"
        if not click_element_robust(driver, By.CSS_SELECTOR, league_checkbox_selector):
            st.info(f"No se pudo clickear 'Same League' para {table_css_id_str} o ya estaba activo.")
        time.sleep(1.5)

        # 2. Activar filtro "Home" o "Away"
        if not click_element_robust(driver, By.CSS_SELECTOR, home_or_away_filter_css_selector):
            st.info(f"No se pudo clickear filtro Home/Away para {table_css_id_str} o ya estaba activo.")
        time.sleep(1.5)

        page_source_updated = driver.page_source
        soup_updated = BeautifulSoup(page_source_updated, "html.parser")
        table = soup_updated.find("table", id=table_css_id_str)
        if not table: return None

        for row_idx, row in enumerate(table.find_all("tr", id=re.compile(rf"tr{table_css_id_str[-1]}_\d+"))):
            if row_idx > 5: break # Limitar búsqueda a las primeras filas por si acaso
            
            if row.get("name") != str(league_id_filter_value): continue # No es de la misma liga
            
            tds = row.find_all("td")
            if len(tds) < 14: continue

            home_team_row_el = tds[2].find("a")
            away_team_row_el = tds[4].find("a")
            if not home_team_row_el or not away_team_row_el: continue
            
            home_team_row_name = home_team_row_el.text.strip()
            away_team_row_name = away_team_row_el.text.strip()

            # Verificar si el equipo principal está en la perspectiva correcta (Local/Visitante)
            team_is_home_in_row = main_team_name_in_table == home_team_row_name
            team_is_away_in_row = main_team_name_in_table == away_team_row_name

            if (is_home_game_filter and not team_is_home_in_row) or \
               (not is_home_game_filter and not team_is_away_in_row):
                continue # No coincide el rol (buscamos local pero el equipo jugó de visita, o viceversa)

            date_span = tds[1].find("span", {"name": "timeData"})
            date = date_span.text.strip() if date_span else "N/A"
            
            score_span = tds[3].find("span", class_=re.compile(r"fscore_"))
            score = score_span.text.strip() if score_span else "N/A"
            
            # Hándicap Asiático (tds[11] es el data-o con la línea)
            handicap_cell = tds[11] 
            handicap = handicap_cell.get("data-o", handicap_cell.text.strip())
            if not handicap or handicap == "-": handicap = "N/A"
            
            return {
                "date": date,
                "home_team": home_team_row_name,
                "away_team": away_team_row_name,
                "score": score,
                "handicap_line": handicap,
            }
        return None
    except Exception as e:
        # st.error(f"Excepción en extract_last_match_in_league ({table_css_id_str}): {e}")
        return None

# --- STREAMLIT APP UI ---
st.set_page_config(page_title="Análisis H2H Nowgoal V2", layout="wide", initial_sidebar_state="expanded")
st.title("🎯 Analizador Avanzado H2H - Nowgoal")
st.markdown("Resultados H2H y últimos partidos en liga con hándicap.")

st.sidebar.image("https://nowgoal.com/img/logo.png", width=150) 
st.sidebar.header("Configuración")
main_match_id_input = st.sidebar.number_input(
    "🆔 ID del Partido Principal:", value=2778085, min_value=1, step=1, format="%d",
    help="ID del partido para el análisis."
)
analizar_button = st.sidebar.button("🚀 Analizar Partido", type="primary", use_container_width=True)
st.sidebar.markdown("---")
st.sidebar.info("Esta app combina tu lógica H2H original con la búsqueda de los últimos partidos en casa/fuera (misma liga) de los equipos del partido principal.")

if analizar_button:
    if not main_match_id_input:
        st.warning("⚠️ Por favor, ingresa un ID de partido válido.")
    else:
        st.header(f"📊 Resultados del Análisis para Partido ID: {main_match_id_input}")
        start_time = time.time()
        
        main_page_url_h2h = f"/match/h2h-{main_match_id_input}"
        soup_main_h2h = fetch_soup_requests(main_page_url_h2h)
        
        mp_home_id, mp_away_id, mp_league_id, mp_home_name, mp_away_name, mp_league_name = (None,)*6
        if soup_main_h2h:
            mp_home_id, mp_away_id, mp_league_id, mp_home_name, mp_away_name, mp_league_name = get_team_league_info_from_script(soup_main_h2h)
        
        st.subheader("📋 Información del Partido Principal")
        col_mp1, col_mp2, col_mp3 = st.columns(3)
        col_mp1.metric("Equipo Local", mp_home_name or "N/A")
        col_mp2.metric("Equipo Visitante", mp_away_name or "N/A")
        col_mp3.metric("Liga", mp_league_name or "N/A")
        st.markdown("---")

        # --- 1. H2H ENTRE ÚLTIMOS OPONENTES GENERALES (TU LÓGICA) ---
        st.subheader("🔄 H2H entre Oponentes (Método Original)")
        with st.spinner(f"Calculando H2H (método original)..."):
            key_home_id_for_h2h, rival_a_id = get_last_home(main_match_id_input)
            key_away_id_for_h2h, rival_b_id = get_last_away(main_match_id_input)

        rival_a_disp = rival_a_id if rival_a_id else "N/A"
        rival_b_disp = rival_b_id if rival_b_id else "N/A"
        st.write(f"Rival A (ID): {rival_a_disp}, Rival B (ID): {rival_b_disp}, Partido Clave para H2H: {key_home_id_for_h2h if key_home_id_for_h2h else 'N/A'}")

        details_h2h_rivals = {"status": "error", "resultado": "N/A"}
        if key_home_id_for_h2h and rival_a_id and rival_b_id:
            with st.spinner(f"Cargando H2H entre {rival_a_id} y {rival_b_id} con Selenium..."):
                details_h2h_rivals = get_h2h_details_selenium(key_home_id_for_h2h, rival_a_id, rival_b_id)
        
        if details_h2h_rivals.get("status") == "found":
            res_h2h_str = details_h2h_rivals['raw_string']
            st.markdown(f"""<div style="background-color:#FFF3E0; padding:15px; border-radius:10px; text-align:center; border:1px solid #FFCC80; margin:10px 0;">
                <h3 style="color:#E65100; font-size:2.2em; font-weight:bold; margin:0;">{res_h2h_str}</h3>
                <p style="font-size:0.9em;color:#555;">(H2H Rival A vs Rival B: Goles*Goles/Hándicap RolRivalAenH2H)</p>
            </div>""", unsafe_allow_html=True)
        else:
            st.warning(f"H2H (Método Original): {details_h2h_rivals.get('resultado', 'No se pudo obtener.')}")
        st.markdown("---")

        # --- 2. ÚLTIMOS PARTIDOS EN MISMA LIGA (NUEVA LÓGICA) ---
        st.subheader(f"📜 Últimos Partidos en '{mp_league_name or 'Misma Liga'}'")
        last_home_in_league_info = None
        last_away_in_league_info = None

        if mp_home_id and mp_away_id and mp_league_id: # Necesitamos todos estos para proceder
            selenium_driver_league = get_selenium_driver()
            if selenium_driver_league:
                try:
                    st.write(f"⚙️ Accediendo a {BASE_URL}{main_page_url_h2h} para análisis de liga...")
                    selenium_driver_league.get(f"{BASE_URL}{main_page_url_h2h}")
                    WebDriverWait(selenium_driver_league, SELENIUM_TIMEOUT_SECONDS, poll_frequency=SELENIUM_POLL_FREQUENCY).until(
                        EC.presence_of_element_located((By.ID, "table_v1"))
                    )
                    time.sleep(1)

                    with st.spinner(f"Buscando último EN CASA en liga para {mp_home_name}..."):
                        last_home_in_league_info = extract_last_match_in_league(
                            selenium_driver_league, "table_v1", mp_home_name, mp_league_id,
                            "input#cb_sos1", is_home_game_filter=True
                        )
                    
                    with st.spinner(f"Buscando último FUERA en liga para {mp_away_name}..."):
                        last_away_in_league_info = extract_last_match_in_league(
                            selenium_driver_league, "table_v2", mp_away_name, mp_league_id,
                            "input#cb_sos2", is_home_game_filter=False # Buscamos partido fuera del equipo visitante
                        )
                except Exception as e_main_sel:
                    st.error(f"Error principal durante Selenium para análisis de liga: {e_main_sel}")
                finally:
                    if selenium_driver_league: selenium_driver_league.quit()
            else:
                st.error("No se pudo iniciar driver Selenium para análisis de liga.")
        else:
            st.warning("Faltan IDs de equipo/liga del partido principal para análisis de liga.")

        col_L1, col_L2 = st.columns(2)
        with col_L1:
            st.markdown(f"##### Último de {mp_home_name or 'Local'} (en casa, misma liga):")
            if last_home_in_league_info:
                res_str = (f"{last_home_in_league_info['home_team']} {last_home_in_league_info['score']} {last_home_in_league_info['away_team']} "
                           f"<br>(AH: <strong>{last_home_in_league_info['handicap_line']}</strong>) <span style='font-size:0.8em;'>({last_home_in_league_info['date']})</span>")
                st.markdown(f"<div style='background-color:#E8F5E9; padding:10px; border-radius:8px; border-left: 5px solid #4CAF50;'>⚽ {res_str}</div>", unsafe_allow_html=True)
            else:
                st.info("No encontrado o error.")
        with col_L2:
            st.markdown(f"##### Último de {mp_away_name or 'Visitante'} (fuera, misma liga):")
            if last_away_in_league_info:
                res_str = (f"{last_away_in_league_info['home_team']} {last_away_in_league_info['score']} {last_away_in_league_info['away_team']} "
                           f"<br>(AH: <strong>{last_away_in_league_info['handicap_line']}</strong>) <span style='font-size:0.8em;'>({last_away_in_league_info['date']})</span>")
                st.markdown(f"<div style='background-color:#E3F2FD; padding:10px; border-radius:8px; border-left: 5px solid #2196F3;'>⚽ {res_str}</div>", unsafe_allow_html=True)
            else:
                st.info("No encontrado o error.")
        
        end_time = time.time()
        st.caption(f"⏱️ Tiempo total del análisis: {end_time - start_time:.2f} segundos")
        st.markdown("---")
else:
    st.info("✨ Ingresa un ID de partido en la barra lateral y haz clic en 'Analizar Partido' para comenzar.")
