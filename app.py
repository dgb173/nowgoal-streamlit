import streamlit as st
import requests
from bs4 import BeautifulSoup
import re

BASE_URL = "https://live18.nowgoal25.com"

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36"
})

def fetch_soup_requests(path):
    try:
        resp = session.get(f"{BASE_URL}{path}", timeout=10)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except:
        return None

def get_last_home(match_id):
    soup = fetch_soup_requests(f"/match/h2h-{match_id}")
    if not soup: return None, None
    table = soup.find("table", id="table_v1")
    if not table: return None, None
    for row in table.find_all("tr", id=re.compile(r"tr1_\d+")):
        if row.get("vs") == "1":
            key_match_id = row.get("index")
            rival = re.search(r"team\((\d+)\)", row.text)
            if key_match_id and rival:
                return key_match_id, rival.group(1)
    return None, None

def get_last_away(match_id):
    soup = fetch_soup_requests(f"/match/h2h-{match_id}")
    if not soup: return None, None
    table = soup.find("table", id="table_v2")
    if not table: return None, None
    for row in table.find_all("tr", id=re.compile(r"tr2_\d+")):
        if row.get("vs") == "1":
            key_match_id = row.get("index")
            rival = re.search(r"team\((\d+)\)", row.text)
            if key_match_id and rival:
                return key_match_id, rival.group(1)
    return None, None

def get_h2h_result(key_match_id, rival_a_id, rival_b_id):
    soup = fetch_soup_requests(f"/match/h2h-{key_match_id}")
    if not soup:
        return "No se pudo cargar la página H2H"
    table = soup.find("table", id="table_v2")
    if not table:
        return "No se encontró la tabla de resultados"
    for row in table.find_all("tr", id=re.compile(r"tr2_\d+")):
        ids = re.findall(r"team\((\d+)\)", str(row))
        if {str(rival_a_id), str(rival_b_id)}.issubset(set(ids)):
            score_span = row.find("span", class_="fscore_2")
            score = score_span.text.strip() if score_span else "Sin resultado"
            tds = row.find_all("td")
            handicap = tds[11].text.strip() if len(tds) > 11 else "N/A"
            return f"Resultado: {score} | Hándicap: {handicap}"
    return "No se encontró el resultado entre esos equipos"

# Interfaz Streamlit
st.title("Predicción rápida desde Nowgoal por ID")
match_id = st.text_input("Introduce el ID del partido", value="2762052")

if st.button("Consultar"):
    with st.spinner("Buscando datos..."):
        key_home_id, rival_a = get_last_home(match_id)
        key_away_id, rival_b = get_last_away(match_id)

        if key_home_id and rival_a and rival_b:
            resultado = get_h2h_result(key_home_id, rival_a, rival_b)
            st.success(resultado)
        else:
            st.error("No se pudo obtener la información de rivales o partidos.")
