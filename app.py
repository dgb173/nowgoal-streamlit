import streamlit as st
from bs4 import BeautifulSoup
import re
import time
import subprocess
from playwright.sync_api import sync_playwright

BASE_URL = "https://live18.nowgoal25.com"

# Asegurarse de que Chromium esté instalado para Playwright
def ensure_playwright_browsers():
    try:
        subprocess.run(["playwright", "install", "chromium"], check=True, stdout=subprocess.DEVNULL)
    except Exception as e:
        st.error(f"Error al instalar navegadores Playwright: {e}")

def fetch_soup_playwright(path):
    url = f"{BASE_URL}{path}"
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=15000)
            # Esperar a que la tabla V2 (H2H visitante) esté presente
            page.wait_for_selector("table#table_v2", timeout=10000)
            html = page.content()
            browser.close()
        return BeautifulSoup(html, "html.parser")
    except Exception as e:
        st.error(f"Error con Playwright al cargar {url}: {e}")
        return None

def get_last_home(match_id):
    soup = fetch_soup_playwright(f"/match/h2h-{match_id}")
    if not soup:
        return None, None
    table = soup.find("table", id="table_v1")
    if not table:
        return None, None
    for row in table.find_all("tr", id=re.compile(r"tr1_\d+")):
        if row.get("vs") == "1":
            key = row.get("index")
            rival = re.search(r"team\((\d+)\)", row.text)
            if key and rival:
                return key, rival.group(1)
    return None, None

def get_last_away(match_id):
    soup = fetch_soup_playwright(f"/match/h2h-{match_id}")
    if not soup:
        return None, None
    table = soup.find("table", id="table_v2")
    if not table:
        return None, None
    for row in table.find_all("tr", id=re.compile(r"tr2_\d+")):
        if row.get("vs") == "1":
            key = row.get("index")
            rival = re.search(r"team\((\d+)\)", row.text)
            if key and rival:
                return key, rival.group(1)
    return None, None

def get_h2h_result(key, a_id, b_id):
    soup = fetch_soup_playwright(f"/match/h2h-{key}")
    if not soup:
        return "No se pudo cargar datos H2H"
    table = soup.find("table", id="table_v2")
    if not table:
        return "No se encontró la tabla de resultados"
    for row in table.find_all("tr", id=re.compile(r"tr2_\d+")):
        ids = re.findall(r"team\((\d+)\)", str(row))
        if {str(a_id), str(b_id)}.issubset(set(ids)):
            score_span = row.find("span", class_="fscore_2")
            score = score_span.text.strip() if score_span else "Sin marcador"
            cols = row.find_all("td")
            hc = cols[11].text.strip() if len(cols) > 11 else "—"
            return f"{score}   |   Hándicap: {hc}"
    return "No se encontró el enfrentamiento exacto"

# — INTERFAZ STREAMLIT —
st.title("🔎 NowGoal H2H por ID (Playwright)")

# Instalación de navegadores la primera vez
ensure_playwright_browsers()

match_id = st.text_input("Introduce el ID del partido", "2762052")
if st.button("Consultar"):
    with st.spinner("🔄 Consultando NowGoal..."):
        home_key, a = get_last_home(match_id)
        away_key, b = get_last_away(match_id)
        if home_key and a and away_key and b:
            res = get_h2h_result(home_key, a, b)
            st.success(res)
        else:
            st.error("🚫 No se pudo extraer la info H2H. Revisa el ID o prueba más tarde.")
