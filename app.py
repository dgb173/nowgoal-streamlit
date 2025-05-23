# Si lo ejecutas localmente, asegúrate de haber instalado:
#   apt-get update -y && apt-get install -y chromium-chromedriver
#   pip install selenium beautifulsoup4 lxml requests streamlit

import streamlit as st
import time, re, requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

# — CONFIGURACIÓN —
BASE_URL = "https://live18.nowgoal25.com"

# Sesión de requests (por si quieres usarla también)
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36"
})

# Crea y configura el driver de Selenium
def get_selenium_driver():
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    # Ajusta esto si tu chromedriver está en otra ruta
    # options.binary_location = "/usr/bin/chromium-browser"
    return webdriver.Chrome(options=options)

# Extrae el HTML con requests (opcional)
def fetch_soup_requests(path):
    url = f"{BASE_URL}{path}"
    try:
        resp = session.get(url, timeout=10)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except Exception:
        return None

# Obtiene el último partido en casa (home) vía requests
def get_last_home(match_id):
    soup = fetch_soup_requests(f"/match/h2h-{match_id}")
    if not soup: return None, None
    table = soup.find("table", id="table_v1")
    if not table: return None, None
    for row in table.find_all("tr", id=re.compile(r"tr1_\d+")):
        if row.get("vs") == "1":
            key = row.get("index")
            rival = re.search(r"team\((\d+)\)", row.text)
            if key and rival:
                return key, rival.group(1)
    return None, None

# Obtiene el último partido fuera (away) vía requests
def get_last_away(match_id):
    soup = fetch_soup_requests(f"/match/h2h-{match_id}")
    if not soup: return None, None
    table = soup.find("table", id="table_v2")
    if not table: return None, None
    for row in table.find_all("tr", id=re.compile(r"tr2_\d+")):
        if row.get("vs") == "1":
            key = row.get("index")
            rival = re.search(r"team\((\d+)\)", row.text)
            if key and rival:
                return key, rival.group(1)
    return None, None

# Usa Selenium para cargar la página y extraer el H2H
def get_h2h_details_selenium(key_match_id, rival_a_id, rival_b_id):
    url = f"{BASE_URL}/match/h2h-{key_match_id}"
    driver = get_selenium_driver()
    try:
        driver.get(url)
        time.sleep(1)  # espera breve para que cargue JS
        page = driver.page_source
        soup = BeautifulSoup(page, "html.parser")
    except Exception as e:
        return f"Error al abrir con Selenium: {e}"
    finally:
        driver.quit()

    table = soup.find("table", id="table_v2")
    if not table:
        return "No se encontró la tabla de H2H"

    for row in table.find_all("tr", id=re.compile(r"tr2_\d+")):
        links = row.find_all("a", onclick=True)
        if len(links) < 2:
            continue
        ids = re.findall(r"team\((\d+)\)", str(links))
        if {str(rival_a_id), str(rival_b_id)}.issubset(set(ids)):
            score_span = row.find("span", class_="fscore_2")
            score = score_span.text.strip() if score_span else "Sin resultado"
            tds = row.find_all("td")
            hc = tds[11].text.strip() if len(tds) > 11 else "N/A"
            return f"{score}   |   Hándicap: {hc}"
    return "No se encontró el enfrentamiento exacto"

# — INTERFAZ STREAMLIT —

st.title("🔎 NowGoal H2H por ID (Selenium)")

match_id = st.text_input("Introduce el ID del partido", value="2762052")
if st.button("Consultar"):
    with st.spinner("🔄 Consultando NowGoal..."):
        # Primero obtenemos los IDs de home y away
        key_home, rival_home = get_last_home(match_id)
        key_away, rival_away = get_last_away(match_id)

        if key_home and rival_home and key_away and rival_away:
            resultado = get_h2h_details_selenium(key_home, rival_home, rival_away)
            st.success(resultado)
        else:
            st.error("🚫 No se pudo obtener la información de rivales o partidos.")
