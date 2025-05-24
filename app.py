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
    # No mostramos este st.write aquí, lo haremos en la UI principal si es necesario
    # st.write(f"  Cargando H2H con Selenium: {url} para {rival_a_id} vs {rival_b_id}")

    driver = get_selenium_driver()
    if not driver:
        return {"status": "error", "resultado": "N/A (Fallo al iniciar Selenium Driver)"}

    soup_selenium = None
    page_source_for_debug = "" # Para depuración
    try:
        st.write(f"⚙️ Accediendo a URL con Selenium: {url}") # Para feedback en UI
        driver.get(url)
        WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS).until(
            EC.presence_of_element_located((By.ID, "table_v2"))
        )
        time.sleep(0.5)
        page_source_for_debug = driver.page_source # Guardar para posible depuración
        soup_selenium = BeautifulSoup(page_source_for_debug, "html.parser")
    except TimeoutException:
        st.warning(f"⏳ Timeout en Selenium esperando #table_v2 en {url}")
        return {"status": "error", "resultado": "N/A (Timeout en Selenium)"}
    except Exception as e:
        st.error(f"❌ Error en Selenium durante carga/parseo: {e}")
        # Opcional: Mostrar parte del page_source si falla el parseo
        # with st.expander("Ver fuente de la página (parcial) en error de parseo"):
        # st.code(page_source_for_debug[:2000])
        return {"status": "error", "resultado": f"N/A (Error Selenium: {type(e).__name__})"}
    finally:
        if driver:
            driver.quit()

    if not soup_selenium:
        return {"status": "error", "resultado": "N/A (Fallo al obtener soup con Selenium)"}

    table = soup_selenium.find("table", id="table_v2")
    if not table:
        # Opcional: Mostrar parte del page_source si no se encuentra la tabla
        # with st.expander("Ver fuente de la página (parcial) si no se encuentra #table_v2"):
        #     st.code(soup_selenium.prettify()[:2000])
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
            
            rol_rival_a = "A" if away_id_found == str(rival_a_id) else "H" # Rol de Rival A en ESE partido H2H
            return {
                "status": "found",
                "goles_home": goles_home, # Goles del equipo local DEL PARTIDO H2H
                "goles_away": goles_away, # Goles del equipo visitante DEL PARTIDO H2H
                "handicap": handicap,
                "rol_rival_a": rol_rival_a, # Rol de Rival A en el partido H2H ('H' o 'A')
                "raw_string": f"{goles_home}*{goles_away}/{handicap} {rol_rival_a}" # Tu formato original
            }

    return {"status": "not_found", "resultado": "N/A (H2H no encontrado para los rivales especificados)"}

# --- STREAMLIT APP UI ---
st.set_page_config(page_title="Análisis H2H Nowgoal", layout="wide", initial_sidebar_state="expanded")
st.title("🎯 Analizador de Partidos H2H - Nowgoal")
st.markdown("Encuentra el resultado del enfrentamiento directo (H2H) entre los últimos oponentes de un equipo.")

st.sidebar.image("https://nowgoal.com/img/logo.png", width=150) # Ejemplo, puedes cambiar la imagen
st.sidebar.header("Configuración del Análisis")

main_match_id_input = st.sidebar.number_input(
    "🆔 ID del Partido Principal:",
    value=2778543, # ID de prueba
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
        with col_info1:
            st.metric(
                label="🏠 Rival A (Oponente del último partido en casa del equipo local del ID principal)",
                value=rival_a if rival_a else "No encontrado",
                delta=f"Partido clave H2H: {key_home_id}" if key_home_id else "N/A",
                delta_color="off"
            )
        with col_info2:
            st.metric(
                label="✈️ Rival B (Oponente del último partido fuera del equipo local del ID principal)",
                value=rival_b if rival_b else "No encontrado",
                delta=f"Partido clave H2H (Usado si no hay Rival A): {key_away_id}" if key_away_id else "N/A",
                delta_color="off"
            )
        st.markdown("---")

        details = {"status": "error", "resultado": "N/A"} # Default
        
        if key_home_id and rival_a and rival_b:
            if rival_a == rival_b:
                st.info(f"ℹ️ Rival A ({rival_a}) y Rival B ({rival_b}) son el mismo equipo. El H2H será de este equipo contra sí mismo, lo cual no es usual pero se buscará.")
            
            st.write(f"⏳ Buscando H2H entre **Rival A ({rival_a})** y **Rival B ({rival_b})** usando el partido clave del Rival A: **{key_home_id}**")
            with st.spinner(f"Cargando datos H2H con Selenium... Esto puede tardar unos segundos."):
                details = get_h2h_details_selenium(key_home_id, rival_a, rival_b)
        
        elif not key_home_id or not rival_a:
            st.error("❌ No se pudo determinar el Rival A (último oponente en casa) o su partido clave.")
        elif not key_away_id or not rival_b: # Este caso podría ser menos común si siempre se usa key_home_id
            st.error("❌ No se pudo determinar el Rival B (último oponente visitante) o su partido clave.")
        else:
            st.error("❌ Información de rivales incompleta, no se puede buscar H2H.")

        # --- SECCIÓN DE RESULTADO ESPECTACULAR ---
        if details.get("status") == "found":
            rival_a_nombre = rival_a if rival_a else "Rival A Desconocido"
            rival_b_nombre = rival_b if rival_b else "Rival B Desconocido"

            # Determinar quién fue local y visitante EN EL PARTIDO H2H ANALIZADO
            if details['rol_rival_a'] == 'H': # Rival A fue local en el H2H
                h2h_local_team_id = rival_a_nombre
                h2h_local_goles = details['goles_home']
                h2h_away_team_id = rival_b_nombre
                h2h_away_goles = details['goles_away']
            else: # Rival A fue visitante en el H2H (implica que Rival B fue local)
                h2h_local_team_id = rival_b_nombre
                h2h_local_goles = details['goles_home']
                h2h_away_team_id = rival_a_nombre
                h2h_away_goles = details['goles_away']
            
            handicap_h2h = details['handicap']
            rol_rival_a_en_h2h_display = "Local (H)" if details['rol_rival_a'] == "H" else "Visitante (A)"
            
            primary_result_display = details['raw_string']

            bg_color = "#E0F2F7"  # Celeste muy claro
            text_color_main = "#0D47A1" # Azul oscuro
            border_color = "#B3E5FC" # Celeste medio

            st.subheader(f"🌟 Resultado H2H Encontrado 🌟")
            
            st.markdown(f"""
            <div style="
                background-color: {bg_color};
                padding: 20px;
                border-radius: 12px;
                text-align: center;
                border: 2px solid {border_color};
                box-shadow: 0 4px 8px rgba(0,0,0,0.1);
                margin-bottom: 25px;
                margin-top: 10px;
            ">
                <p style="font-size: 1.1em; color: #37474F; margin-bottom: 8px; font-weight: 500;">
                    Partido H2H analizado: <strong style="color:{text_color_main};">{h2h_local_team_id}</strong> (Local) vs <strong style="color:{text_color_main};">{h2h_away_team_id}</strong> (Visitante)
                </p>
                <h2 style="
                    color: {text_color_main};
                    font-size: 3em; 
                    font-weight: 700;
                    margin-top: 5px;
                    margin-bottom:10px;
                    letter-spacing: 1px;
                ">{primary_result_display}</h2>
                <p style="font-size: 0.95em; color: #546E7A; margin-top: 5px;">
                    Formato: GolesLocalDelH2H * GolesVisitanteDelH2H / Hándicap <strong style="color:{text_color_main};">Rol_Rival_A_en_H2H</strong>
                </p>
            </div>
            """, unsafe_allow_html=True)

            # --- DESGLOSE DETALLADO ---
            st.markdown("#### 📋 Desglose Detallado del Partido H2H:")
            
            col_desc1, col_desc2 = st.columns(2)

            with col_desc1:
                st.markdown(f"""
                <div style="padding: 12px; border-left: 4px solid #4CAF50; margin-bottom:12px; background-color:#F1F8E9; border-radius: 5px;">
                    <strong style="font-size:1.15em; color:#2E7D32;">⚽ Goles del Partido H2H:</strong><br>
                       Team {h2h_local_team_id} (Local): <strong style="font-size:1.1em;">{h2h_local_goles}</strong><br>
                       Team {h2h_away_team_id} (Visitante): <strong style="font-size:1.1em;">{h2h_away_goles}</strong>
                </div>
                """, unsafe_allow_html=True)

            with col_desc2:
                st.markdown(f"""
                <div style="padding: 12px; border-left: 4px solid #2196F3; margin-bottom:12px; background-color:#E3F2FD; border-radius: 5px;">
                    <strong style="font-size:1.15em; color:#1565C0;">⚖️ Hándicap del Partido H2H:</strong> <strong style="font-size:1.1em;">{handicap_h2h}</strong><br>
                    <strong style="font-size:1.15em; color:#1565C0;">🧭 Rol de '{rival_a_nombre}' en este H2H:</strong> <strong style="font-size:1.1em;">{rol_rival_a_en_h2h_display}</strong>
                </div>
                """, unsafe_allow_html=True)
            
            h2h_url_selenium = f"{BASE_URL}/match/h2h-{key_home_id}"
            st.markdown(f"<p style='text-align:center; margin-top:15px;'>🔗 <a href='{h2h_url_selenium}' target='_blank' style='color:{text_color_main};'>Ver datos fuente en Nowgoal (Partido Clave {key_home_id})</a></p>", unsafe_allow_html=True)


        elif details.get("status") in ["error", "not_found"]:
            st.error(f"❌ No se pudo obtener el resultado H2H detallado entre **{rival_a if rival_a else 'Rival A'}** y **{rival_b if rival_b else 'Rival B'}**: {details.get('resultado')}")
            # Opción para mostrar URL si hubo intento de Selenium
            if (key_home_id and rival_a and rival_b):
                 h2h_url_selenium = f"{BASE_URL}/match/h2h-{key_home_id}"
                 st.info(f"Se intentó acceder a: {h2h_url_selenium}")
        else: # Caso genérico por si algo muy raro pasa
             st.error("❌ Error desconocido al procesar el resultado H2H.")


        end_time = time.time()
        st.caption(f"⏱️ Tiempo total del análisis: {end_time - start_time:.2f} segundos")
        st.markdown("---")
else:
    st.info("✨ Ingresa un ID de partido en la barra lateral y haz clic en 'Analizar Partido' para comenzar.")
