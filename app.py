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

# --- CONFIGURACIÓN GLOBAL ---
BASE_URL = "https://live18.nowgoal25.com"
SELENIUM_TIMEOUT_SECONDS = 20

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
def get_selenium_driver():
    options = ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36")
    options.add_argument('--blink-settings=imagesEnabled=false')
    try:
        driver = webdriver.Chrome(options=options)
        return driver
    except WebDriverException as e:
        st.error(f"ERROR CRÍTICO SELENIUM: No se pudo iniciar ChromeDriver. {e}")
        st.error("Asegúrate de que ChromeDriver (o chromium-chromedriver) esté instalado y sea accesible.")
        st.info("Si usas Streamlit Cloud, añade 'chromium-chromedriver' a tu packages.txt.")
        return None

def get_h2h_details_selenium(key_match_id, rival_a_id, rival_b_id):
    if not key_match_id or not rival_a_id or not rival_b_id:
        return {"status": "error", "resultado": "N/A (IDs incompletos para H2H)"}

    url = f"{BASE_URL}/match/h2h-{key_match_id}"
    driver = get_selenium_driver()
    if not driver:
        return {"status": "error", "resultado": "N/A (Fallo al iniciar Selenium Driver)"}

    soup_selenium = None
    try:
        st.write(f"⚙️ Accediendo a URL con Selenium: {url}") 
        driver.get(url)
        WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS).until(
            EC.presence_of_element_located((By.ID, "table_v2"))
        )
        time.sleep(0.5)
        page_source = driver.page_source 
        soup_selenium = BeautifulSoup(page_source, "html.parser")
    except TimeoutException:
        st.warning(f"⏳ Timeout en Selenium esperando #table_v2 en {url}")
        return {"status": "error", "resultado": "N/A (Timeout en Selenium)"}
    except Exception as e:
        st.error(f"❌ Error en Selenium durante carga/parseo: {e}")
        return {"status": "error", "resultado": f"N/A (Error Selenium: {type(e).__name__})"}
    finally:
        if driver:
            driver.quit()

    if not soup_selenium:
        return {"status": "error", "resultado": "N/A (Fallo al obtener soup con Selenium)"}

    table = soup_selenium.find("table", id="table_v2")
    if not table:
        return {"status": "error", "resultado": "N/A (Tabla H2H no encontrada en Selenium)"}

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
            HANDICAP_LINE_TD_INDEX = 11

            if len(tds) > HANDICAP_LINE_TD_INDEX:
                celda_handicap = tds[HANDICAP_LINE_TD_INDEX]
                data_o_valor = celda_handicap.get("data-o")

                if data_o_valor is not None and data_o_valor.strip() != "" and data_o_valor.strip() != "-":
                    handicap = data_o_valor.strip()
                else:
                    texto_celda = celda_handicap.text.strip()
                    if texto_celda != "" and texto_celda != "-":
                        handicap = texto_celda
            
            rol_rival_a = "A" if away_id_found == str(rival_a_id) else "H" 
            return {
                "status": "found",
                "goles_home": goles_home, 
                "goles_away": goles_away, 
                "handicap": handicap,
                "rol_rival_a": rol_rival_a, 
                "raw_string": f"{goles_home}*{goles_away}/{handicap} {rol_rival_a}" 
            }
    return {"status": "not_found", "resultado": "N/A (H2H no encontrado para los rivales especificados)"}

# --- STREAMLIT APP UI ---
st.set_page_config(page_title="Análisis H2H Nowgoal", layout="wide", initial_sidebar_state="expanded")
st.title("🎯 Analizador de Partidos H2H - Nowgoal")
st.markdown("Encuentra el resultado del enfrentamiento directo (H2H) entre los últimos oponentes de un equipo.")

st.sidebar.image("https://nowgoal.com/img/logo.png", width=150) 
st.sidebar.header("Configuración del Análisis")

main_match_id_input = st.sidebar.number_input(
    "🆔 ID del Partido Principal:",
    value=2778543, 
    min_value=1,
    step=1,
    format="%d",
    help="Ingresa el ID del partido para el cual quieres encontrar los últimos oponentes y su H2H."
)
analizar_button = st.sidebar.button("🚀 Analizar Partido", type="primary", use_container_width=True)

st.sidebar.markdown("---")
st.sidebar.header("Información")
st.sidebar.info(
    "Esta aplicación web recupera el último partido en casa y fuera del equipo local "
    "del 'Partido Principal'. Luego, identifica a los oponentes de esos dos partidos. "
    "Finalmente, busca el resultado del enfrentamiento directo (H2H) entre esos dos oponentes."
)
st.sidebar.markdown("Creado con Streamlit por un entusiasta del análisis deportivo.")

if analizar_button:
    if not main_match_id_input:
        st.warning("⚠️ Por favor, ingresa un ID de partido válido.")
    else:
        st.header(f"📊 Resultados del Análisis para Partido ID: {main_match_id_input}")
        start_time = time.time()
        
        with st.spinner(f"Obteniendo datos iniciales..."):
            key_home_id, rival_a = get_last_home(main_match_id_input)
            key_away_id, rival_b = get_last_away(main_match_id_input)

        col_info1, col_info2 = st.columns(2)
        rival_a_nombre_contexto = rival_a if rival_a else "No encontrado"
        rival_b_nombre_contexto = rival_b if rival_b else "No encontrado"

        with col_info1:
            st.metric(
                label="🏠 Rival A (Oponente del último partido en casa del equipo local del ID principal)",
                value=rival_a_nombre_contexto,
                delta=f"Partido clave H2H: {key_home_id}" if key_home_id else "N/A",
                delta_color="off"
            )
        with col_info2:
            st.metric(
                label="✈️ Rival B (Oponente del último partido fuera del equipo local del ID principal)",
                value=rival_b_nombre_contexto,
                delta=f"Partido clave H2H (Usado si no hay Rival A): {key_away_id}" if key_away_id else "N/A",
                delta_color="off"
            )
        st.markdown("---")

        details = {"status": "error", "resultado": "N/A"} 
        
        if key_home_id and rival_a and rival_b:
            if rival_a == rival_b:
                st.info(f"ℹ️ Rival A ({rival_a}) y Rival B ({rival_b}) son el mismo equipo. El H2H será de este equipo contra sí mismo, lo cual no es usual pero se buscará.")
            
            st.write(f"⏳ Buscando H2H entre **Rival A ({rival_a})** y **Rival B ({rival_b})** usando el partido clave del Rival A: **{key_home_id}**")
            with st.spinner(f"Cargando datos H2H con Selenium... Esto puede tardar unos segundos."):
                details = get_h2h_details_selenium(key_home_id, rival_a, rival_b)
        
        elif not key_home_id or not rival_a:
            st.error("❌ No se pudo determinar el Rival A (último oponente en casa) o su partido clave.")
        elif not key_away_id or not rival_b: 
            st.error("❌ No se pudo determinar el Rival B (último oponente visitante) o su partido clave.")
        else:
            st.error("❌ Información de rivales incompleta, no se puede buscar H2H.")

        # --- SECCIÓN DE RESULTADO ESPECTACULAR (SIMPLIFICADA) ---
        if details.get("status") == "found":
            primary_result_display = details['raw_string'] 

            bg_color = "#E0F2F7" 
            text_color_main = "#0D47A1" 
            border_color = "#B3E5FC" 

            st.subheader(f"🌟 Resultado H2H Encontrado 🌟")
            st.write(f"Este es el resultado del enfrentamiento directo entre **{rival_a_nombre_contexto}** y **{rival_b_nombre_contexto}**.")
            
            st.markdown(f"""
            <div style="
                background-color: {bg_color};
                padding: 25px; 
                border-radius: 12px;
                text-align: center;
                border: 2px solid {border_color};
                box-shadow: 0 4px 8px rgba(0,0,0,0.1);
                margin-bottom: 25px;
                margin-top: 15px;
            ">
                <h2 style="
                    color: {text_color_main};
                    font-size: 3.2em; 
                    font-weight: 700;
                    margin-top: 0;
                    margin-bottom:10px;
                    letter-spacing: 1px;
                ">{primary_result_display}</h2>
                <p style="font-size: 0.95em; color: #546E7A; margin-top: 5px;">
                    (Formato: GolesLocal<sub>del H2H</sub> * GolesVisitante<sub>del H2H</sub> / Hándicap   <strong>Rol de '{rival_a_nombre_contexto}' en este H2H</strong>)
                </p>
            </div>
            """, unsafe_allow_html=True)
            
            with st.expander("Ver desglose simple del resultado H2H", expanded=False):
                rol_rival_a_en_h2h_display = "Local (H)" if details['rol_rival_a'] == "H" else "Visitante (A)"
                st.markdown(f"""
                    - **Resultado del Partido H2H:** {details['goles_home']} - {details['goles_away']}
                    - **Hándicap del Partido H2H:** {details['handicap']}
                    - **Rol de '{rival_a_nombre_contexto}' en el Partido H2H:** {rol_rival_a_en_h2h_display}
                """)

            h2h_url_selenium = f"{BASE_URL}/match/h2h-{key_home_id}" 
            st.markdown(f"<p style='text-align:center; margin-top:15px;'>🔗 <a href='{h2h_url_selenium}' target='_blank' style='color:{text_color_main};'>Ver datos fuente en Nowgoal (Partido Clave {key_home_id})</a></p>", unsafe_allow_html=True)

        elif details.get("status") in ["error", "not_found"]:
            st.error(f"❌ No se pudo obtener el resultado H2H detallado entre **{rival_a_nombre_contexto}** y **{rival_b_nombre_contexto}**: {details.get('resultado')}")
            if (key_home_id and rival_a and rival_b):
                 h2h_url_selenium = f"{BASE_URL}/match/h2h-{key_home_id}"
                 st.info(f"Se intentó acceder a: {h2h_url_selenium}")
        else: 
             st.error("❌ Error desconocido al procesar el resultado H2H.")

        end_time = time.time()
        st.caption(f"⏱️ Tiempo total del análisis: {end_time - start_time:.2f} segundos")
        st.markdown("---")
else:
    st.info("✨ Ingresa un ID de partido en la barra lateral y haz clic en 'Analizar Partido' para comenzar.")
