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
from selenium.common.exceptions import TimeoutException, WebDriverException
# psutil and gspread related imports are not used in the core logic shown,
# but keeping them if they are part of a larger context you haven't shown.
# import psutil
# import gspread
# import gspread_dataframe
# import requests_html # Añadido requests_html por si se usa

# --- CONFIGURACIÓN GLOBAL ---
BASE_URL = "https://live18.nowgoal25.com"
SELENIUM_TIMEOUT_SECONDS = 20

# Configuración de la sesión de requests
@st.cache_resource # Cache the session object
def get_requests_session():
    session = requests.Session()
    retries_req = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    adapter_req = HTTPAdapter(max_retries=retries_req)
    session.mount("https://", adapter_req)
    session.mount("http://", adapter_req)
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36"})
    return session

# --- FUNCIONES DE REQUESTS ---
@st.cache_data(ttl=3600) # Cache data for 1 hour
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
                st.error(f"  Error final de Requests fetching {url}: {e}")
                return None
            time.sleep(delay * attempt)
    return None

@st.cache_data(ttl=3600)
def get_last_home(match_id):
    soup = fetch_soup_requests(f"/match/h2h-{match_id}")
    if not soup: return None, None
    table = soup.find("table", id="table_v1")
    if not table: return None, None
    for row in table.find_all("tr", id=re.compile(r"tr1_\d+")):
        if row.get("vs") == "1":
            key_match_id = row.get("index")
            if not key_match_id: continue
            onclicks = row.find_all("a", onclick=True)
            if len(onclicks) > 1 and onclicks[1].get("onclick"):
                rival_a_id_match = re.search(r"team\((\d+)\)", onclicks[1]["onclick"])
                if rival_a_id_match:
                    return key_match_id, rival_a_id_match.group(1)
    return None, None

@st.cache_data(ttl=3600)
def get_last_away(match_id):
    soup = fetch_soup_requests(f"/match/h2h-{match_id}")
    if not soup: return None, None
    table = soup.find("table", id="table_v2")
    if not table: return None, None
    for row in table.find_all("tr", id=re.compile(r"tr2_\d+")):
        if row.get("vs") == "1":
            key_match_id = row.get("index")
            if not key_match_id: continue
            onclicks = row.find_all("a", onclick=True)
            if len(onclicks) > 0 and onclicks[0].get("onclick"):
                rival_b_id_match = re.search(r"team\((\d+)\)", onclicks[0]["onclick"])
                if rival_b_id_match:
                    return key_match_id, rival_b_id_match.group(1)
    return None, None

# --- FUNCIONES DE SELENIUM ---
# @st.cache_resource # Caching driver can be tricky with quit()
def get_selenium_driver():
    options = ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36")
    options.add_argument('--blink-settings=imagesEnabled=false')
    try:
        # For Streamlit Cloud, chromedriver should be in PATH if chromium-chromedriver is installed via packages.txt
        driver = webdriver.Chrome(options=options)
        return driver
    except WebDriverException as e:
        st.error(f"ERROR CRÍTICO SELENIUM: No se pudo iniciar ChromeDriver. {e}")
        st.error("Asegúrate de que ChromeDriver (o chromium-chromedriver) esté instalado y sea accesible.")
        st.info("Si usas Streamlit Cloud, añade 'chromium-chromedriver' a tu packages.txt.")
        return None

# Not caching this function directly as it involves Selenium driver interactions that might not be easily cacheable
# and also to ensure fresh data for H2H details.
def get_h2h_details_selenium(key_match_id, rival_a_id, rival_b_id):
    if not key_match_id or not rival_a_id or not rival_b_id:
        return {"resultado": "N/A (IDs incompletos para H2H)"}

    url = f"{BASE_URL}/match/h2h-{key_match_id}"
    st.write(f"  Cargando H2H con Selenium: {url} para {rival_a_id} vs {rival_b_id}")

    driver = get_selenium_driver()
    if not driver:
        return {"resultado": "N/A (Fallo al iniciar Selenium Driver)"}

    soup_selenium = None
    try:
        driver.get(url)
        WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS).until(
            EC.presence_of_element_located((By.ID, "table_v2")) # Wait for a specific table that indicates content load
        )
        time.sleep(0.5) # Pequeña pausa para asegurar renderizado JS
        page_source = driver.page_source
        soup_selenium = BeautifulSoup(page_source, "html.parser")
    except TimeoutException:
        st.warning(f"  Timeout en Selenium esperando #table_v2 en {url}")
        return {"resultado": "N/A (Timeout en Selenium)"}
    except Exception as e:
        st.error(f"  Error en Selenium durante carga/parseo: {e}")
        return {"resultado": f"N/A (Error Selenium: {type(e).__name__})"}
    finally:
        if driver:
            driver.quit()

    if not soup_selenium:
        return {"resultado": "N/A (Fallo al obtener soup con Selenium)"}

    table = soup_selenium.find("table", id="table_v2")
    if not table:
        return {"resultado": "N/A (Tabla H2H no encontrada en Selenium)"}

    for row in table.find_all("tr", id=re.compile(r"tr2_\d+")):
        links = row.find_all("a", onclick=True)
        if len(links) < 2: continue

        home_id_match_search = re.search(r"team\((\d+)\)", links[0].get("onclick", ""))
        away_id_match_search = re.search(r"team\((\d+)\)", links[1].get("onclick", ""))
        if not home_id_match_search or not away_id_match_search: continue

        home_id_found = home_id_match_search.group(1)
        away_id_found = away_id_match_search.group(1)

        if {home_id_found, away_id_found} == {str(rival_a_id), str(rival_b_id)}:
            score_span = row.find("span", class_="fscore_2")
            if not score_span or not score_span.text or "-" not in score_span.text: continue

            score = score_span.text.strip()
            goles_home, goles_away = score.split("-")

            tds = row.find_all("td")
            handicap = "N/A"
            HANDICAP_LINE_TD_INDEX = 11 # Confirm this index is correct

            if len(tds) > HANDICAP_LINE_TD_INDEX:
                celda_handicap = tds[HANDICAP_LINE_TD_INDEX]
                data_o_valor = celda_handicap.get("data-o")

                if data_o_valor is not None and data_o_valor.strip() != "" and data_o_valor.strip() != "-":
                    handicap = data_o_valor.strip()
                else:
                    texto_celda = celda_handicap.text.strip()
                    if texto_celda != "" and texto_celda != "-":
                        handicap = texto_celda
            
            # Determine role based on if rival_a_id was the away team in the H2H match
            rol = "A" if away_id_found == str(rival_a_id) else "H"
            return {"resultado": f"{goles_home}*{goles_away}/{handicap} {rol}"}

    return {"resultado": "N/A (H2H no encontrado para los rivales especificados)"}

# --- STREAMLIT APP UI ---
st.set_page_config(page_title="Análisis H2H Nowgoal", layout="wide")
st.title("Analizador de Partidos H2H - Nowgoal")

st.sidebar.header("Información")
st.sidebar.info(
    "Esta aplicación analiza el historial de enfrentamientos (H2H) entre "
    "los oponentes de los últimos partidos en casa y fuera de un equipo principal."
)

main_match_id_input = st.number_input(
    "Ingresa el ID del Partido Principal:",
    value=2779089,  # Default test ID
    min_value=1,
    step=1,
    format="%d",
    help="ID del partido principal para el cual se quiere realizar el análisis."
)

if st.button("Analizar Partido", type="primary"):
    if not main_match_id_input:
        st.warning("Por favor, ingresa un ID de partido.")
    else:
        with st.spinner(f"Analizando partido ID: {main_match_id_input}... Esto puede tardar un momento."):
            st.subheader(f"Resultados del Análisis para Partido ID: {main_match_id_input}")
            start_time = time.time()

            key_home_id, rival_a = get_last_home(main_match_id_input)
            key_away_id, rival_b = get_last_away(main_match_id_input)

            col1, col2 = st.columns(2)
            with col1:
                st.metric(
                    label="Rival A (Oponente de Local)",
                    value=rival_a if rival_a else "No encontrado",
                    delta=f"Partido clave: {key_home_id}" if key_home_id else "N/A",
                    delta_color="off"
                )
            with col2:
                 st.metric(
                    label="Rival B (Oponente de Visitante)",
                    value=rival_b if rival_b else "No encontrado",
                    delta=f"Partido clave: {key_away_id}" if key_away_id else "N/A",
                    delta_color="off"
                )

            details = {"resultado": "N/A"} # Default
            if key_home_id and rival_a and rival_b:
                # Check if rivals are the same, which might not make sense for H2H
                if rival_a == rival_b:
                    st.warning(f"Rival A ({rival_a}) y Rival B ({rival_b}) son el mismo equipo. El análisis H2H directo entre ellos podría no ser lo que esperas en este contexto.")
                    # Proceeding anyway as per original logic, but it's good to note
                
                st.info(f"Buscando H2H entre Rival A ({rival_a}) y Rival B ({rival_b}) usando el partido clave: {key_home_id}")
                details = get_h2h_details_selenium(key_home_id, rival_a, rival_b)
            elif not key_home_id or not rival_a:
                st.error("No se pudo determinar el último oponente en casa (Rival A) o su partido clave.")
            elif not key_away_id or not rival_b:
                st.error("No se pudo determinar el último oponente como visitante (Rival B) o su partido clave.")
            else:
                st.error("Información de rivales incompleta, no se puede buscar H2H.")

            end_time = time.time()
            
            st.success(f"Resultado H2H ({rival_a if rival_a else 'Rival A Desconocido'} vs {rival_b if rival_b else 'Rival B Desconocido'}): {details.get('resultado', 'No encontrado')}")
            st.caption(f"Tiempo total del análisis: {end_time - start_time:.2f} segundos")
            st.markdown("---")
else:
    st.info("Ingresa un ID de partido y haz clic en 'Analizar Partido'.")
