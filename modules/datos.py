# modules/datos.py
import streamlit as st
import time
import requests
import re
import math
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

# --- CONFIGURACIÓN GLOBAL ---
BASE_URL_OF = "https://live18.nowgoal25.com"
PLACEHOLDER_NODATA = "*(No disponible)*"

# --- FUNCIONES HELPER (SIN DECORADORES st.*) ---
def _make_request(url, is_soup=True, session=None):
    """Función de request pura, para ser usada en hilos."""
    try:
        # Usa una sesión compartida si se provee, si no, una nueva
        s = session or requests.Session()
        resp = s.get(url, timeout=10)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml") if is_soup else resp.text
    except requests.RequestException:
        return None

def parse_ah_to_number_of(ah_line_str: str):
    if not isinstance(ah_line_str, str): return None
    s = ah_line_str.strip().replace(' ', '')
    if not s or s in ['-', '?']: return None
    try:
        if '/' in s:
            p = s.split('/'); v1, v2 = float(p[0]), float(p[1])
            if v1 < 0 and v2 > 0: v2 = -abs(v2)
            elif ah_line_str.strip().startswith('-') and v1==0 and v2>0: v2=-abs(v2)
            return (v1 + v2) / 2.0
        return float(s)
    except (ValueError, IndexError): return None

def format_ah_as_decimal_string_of(ah_line_raw: str):
    if not ah_line_raw: return PLACEHOLDER_NODATA
    num = parse_ah_to_number_of(ah_line_raw)
    if num is None: return PLACEHOLDER_NODATA
    if num == 0.0: return "0"
    return f"{num:.0f}" if num.is_integer() else f"{num:.2f}".rstrip('0').rstrip('.')

def get_match_details_from_row_of(row_element, score_class_selector='score'):
    try:
        cells = row_element.find_all('td')
        if len(cells) < 12: return None
        home_tag, away_tag = cells[2].find('a'), cells[4].find('a')
        if not (home_tag and away_tag): return None
        
        score_span = cells[3].find('span', class_=lambda x: x and score_class_selector in x)
        ah_cell = cells[11]
        ah_line_raw = (ah_cell.get('data-o', '').strip() or ah_cell.text.strip()) or None

        return {
            'home': home_tag.text.strip(), 'away': away_tag.text.strip(),
            'score': (score_span.text.strip().split('(')[0].strip()).replace('-', ':') if score_span else '?:?',
            'ahLine': format_ah_as_decimal_string_of(ah_line_raw), 'ahLine_raw': ah_line_raw,
            'matchIndex': row_element.get('index'), 'league_id_hist': row_element.get('name')
        }
    except Exception: return None

# --- TRABAJADORES PUROS PARA PARALELIZACIÓN (SIN DECORADORES) ---
def _worker_fetch_content(url, is_soup, session):
    return _make_request(url, is_soup, session)

def _worker_get_prog_stats(match_id, session):
    if not match_id: return None
    soup = _make_request(f"{BASE_URL_OF}/match/live-{match_id}", session=session)
    if not soup: return None
    stats = {title: ("-", "-") for title in ["Shots", "Shots on Goal", "Attacks", "Dangerous Attacks"]}
    try:
        if (ul := soup.select_one('#teamTechDiv_detail ul.stat')):
            for li in ul.find_all('li'):
                if (title := li.select_one('span.stat-title')) and (title_text := title.get_text(strip=True)) in stats:
                    if (vals := [s.get_text(strip=True) for s in li.select('span.stat-c')]) and len(vals) == 2:
                        stats[title_text] = tuple(vals)
        return pd.DataFrame([{"Estadistica_EN": k, "Casa": v[0], "Fuera": v[1]} for k, v in stats.items()]).set_index("Estadistica_EN")
    except Exception: return None

# --- FUNCIÓN ORQUESTADORA CACHEADA ---
@st.cache_data(ttl=1800, show_spinner=False)
def fetch_all_match_data(match_id: str):
    session = get_requests_session_of() # Usa la sesión cacheada
    main_soup = _make_request(f"{BASE_URL_OF}/match/h2h-{match_id}", session=session)
    
    if not main_soup:
        return {"status": "error", "message": "Fallo crítico al obtener la página principal del partido."}
        
    data = {}
    tasks = {}
    
    # 1. Parseo Síncrono del Soup Principal (instantáneo)
    if (script_tag := main_soup.find("script", string=re.compile(r"var _matchInfo ="))) and (s := script_tag.string):
        data.update({
            "home_id": m.group(1) if (m:=re.search(r"hId:\s*'(\d+)'",s)) else None,
            "away_id": m.group(1) if (m:=re.search(r"gId:\s*'(\d+)'",s)) else None,
            "league_id": m.group(1) if (m:=re.search(r"sclassId:\s*'(\d+)'",s)) else None,
            "home_name": m.group(1).replace("\\'", "'") if (m:=re.search(r"hName:\s*'([^']*)'",s)) else "Local",
            "away_name": m.group(1).replace("\\'", "'") if (m:=re.search(r"gName:\s*'([^']*)'",s)) else "Visitante",
            "league_name": m.group(1).replace("\\'", "'") if (m:=re.search(r"lName:\s*'([^']*)'",s)) else "N/A"
        })
    else:
        return {"status": "error", "message": "No se encontró información básica del partido."}

    if score_tags := main_soup.select('#mScore .end .score'):
        data["final_score"] = f"{score_tags[0].text.strip()}:{score_tags[1].text.strip()}"
    else:
        data["final_score"] = "vs"

    # 2. Lanzar Tareas Asíncronas
    with ThreadPoolExecutor(max_workers=10) as executor:
        # Tareas de datos
        tasks['odds'] = executor.submit(_worker_fetch_content, f"https://data.nowgoal25.com/3in1Odds/{match_id}", False, session)
        tasks['col3_details'] = executor.submit(get_col3_h2h_details, match_id)
        
        # Tareas de Estadísticas (IDs se extraen del soup, así que no se pueden lanzar antes)
        if match_id:
             tasks['prog_stats_main'] = executor.submit(_worker_get_prog_stats, match_id, session)

    # 3. Procesar resultados de tareas asíncronas
    # Odds
    odds_text = tasks['odds'].result()
    odds_data = {k: "N/A" for k in ["ah_home_cuota", "ah_linea_raw", "ah_away_cuota", "goals_over_cuota", "goals_linea_raw", "goals_under_cuota"]}
    if odds_text and len(parts := odds_text.split('$$')) >= 3:
        if (line := next((p.split(',') for p in parts[0].split(';') if p.startswith("8,")), None)):
            odds_data.update({"ah_home_cuota": line[2], "ah_linea_raw": line[3], "ah_away_cuota": line[4]})
        if (line := next((p.split(',') for p in parts[2].split(';') if p.startswith("8,")), None)):
            odds_data.update({"goals_over_cuota": line[2], "goals_linea_raw": line[3], "goals_under_cuota": line[4]})
    data['odds'] = odds_data
    data['col3'] = tasks['col3_details'].result()
    data['prog_stats_main'] = tasks['prog_stats_main'].result()
    
    data['status'] = "ok"
    return data, main_soup # Devuelve el soup también para no tener que pasarlo como argumento

# --- GETTERS SIMPLES QUE YA NO NECESITAN CACHE, DEPENDEN DEL RESULTADO DEL ORQUESTADOR ---
def get_col3_h2h_details(match_id, session=None):
    if not (session := session or get_requests_session_of()): return {} # Se necesita sesión para _make_request
    soup_main = _make_request(f"{BASE_URL_OF}/match/h2h-{match_id}", session=session)
    if not soup_main: return {"status": "error", "resultado": "Fallo H2H(1)"}

    # Resto de la lógica idéntica
    rival_a, rival_b = None, None
    if (row := soup_main.select_one("table#table_v1 tr[vs='1']")) and (tags := row.select("a[onclick]")) and len(tags) > 1 and (m := re.search(r"team\((\d+)\)", tags[1]['onclick'])):
        rival_a = (row.get("index"), m.group(1), tags[1].text.strip())
    if (row := soup_main.select_one("table#table_v2 tr[vs='1']")) and (tags := row.select("a[onclick]")) and len(tags) > 0 and (m := re.search(r"team\((\d+)\)", tags[0]['onclick'])):
        rival_b = (row.get("index"), m.group(1), tags[0].text.strip())

    if not all([rival_a, rival_b]): return {"status": "error", "resultado": "Fallo H2H(2)"}
    h2h_url_id, rival_a_id, rival_a_name = rival_a; _, rival_b_id, rival_b_name = rival_b
    soup_rivals = _make_request(f"{BASE_URL_OF}/match/h2h-{h2h_url_id}", session=session)
    if not soup_rivals: return {"status": "error", "resultado": "Fallo H2H(3)"}

    for row in soup_rivals.select("table#table_v2 tr[id^='tr2_']"):
        if (tags := row.select("a[onclick]")) and len(tags)>1:
            ids={re.search(r"(\d+)",t['onclick']).group(1) for t in tags if re.search(r"(\d+)",t['onclick'])}
            if ids == {rival_a_id, rival_b_id} and (details := get_match_details_from_row_of(row, 'fscore_2')):
                return {"status": "found", **details}
    return {"status": "not_found", "resultado": f"H2H no hallado: {rival_a_name} vs {rival_b_name}"}

@st.cache_resource
def get_requests_session_of():
    # Esta función si debe ser @st.cache_resource para crear una sola sesión para la app.
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(pool_connections=100, pool_maxsize=100, max_retries=retries)
    session.mount("https://", adapter); session.mount("http://", adapter)
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
    return session
    
def display_standings_card(container, standings_data, team_display_name, team_color_class):
    #... [código de visualización idéntico] ...

# --- UI PRINCIPAL (VERSIÓN FINAL) ---
def display_other_feature_ui():
    st.markdown("""<style>/* CSS Omitido por brevedad */</style>""", unsafe_allow_html=True)
    st.sidebar.title("⚙️ Configuración")
    main_match_id_input = st.sidebar.text_input("🆔 ID Partido Principal:", "2696131", key="id_input")

    if st.sidebar.button("🚀 Analizar Partido", type="primary", use_container_width=True):
        match_id = "".join(filter(str.isdigit, main_match_id_input))
        if not match_id:
            st.error("⚠️ ID de partido no válido."); return

        start_time = time.time()
        
        all_data, main_soup = fetch_all_match_data(match_id)
        
        if all_data.get("status") == "error":
            st.error(f"❌ {all_data['message']}"); return
            
        home_name = all_data.get('home_name', 'Local')
        away_name = all_data.get('away_name', 'Visitante')

        st.markdown(f"## 🆚 <span class='home-color'>{home_name}</span> vs <span class='away-color'>{away_name}</span>", unsafe_allow_html=True)
        st.caption(f"🏆 {all_data.get('league_name', 'N/A')} | 🆔 {match_id}")
        st.divider()

        with st.expander("⚖️ Cuotas (Bet365) y Marcador", expanded=True):
            c1,c2,c3 = st.columns(3)
            final_score_display = all_data.get('final_score', 'vs')
            if final_score_display == 'vs': c1.metric("🏁 Marcador Final", "vs")
            else: c1.metric("🏁 Marcador Final", final_score_display)

            odds = all_data.get('odds', {})
            c2.metric("⚖️ AH (Línea Inicial)", format_ah_as_decimal_string_of(odds.get("ah_linea_raw")), f"{odds.get('ah_home_cuota', '-')} / {odds.get('ah_away_cuota', '-')}")
            c3.metric("🥅 Goles (Línea Inicial)", format_ah_as_decimal_string_of(odds.get("goals_linea_raw")), f"O:{odds.get('goals_over_cuota','-')} / U:{odds.get('goals_under_cuota','-')}")
            
            # Mostrar stats de progresión del partido principal
            if final_score_display != 'vs' and (prog_stats := all_data.get('prog_stats_main')) is not None:
                 #display_prog_stats_view...
                 st.write("Estadísticas del partido principal:")
                 st.dataframe(prog_stats)

        st.subheader("⚡ H2H Rivales (Col3)")
        if (col3 := all_data.get('col3')) and col3.get('status') == 'found':
            st.markdown(f"{col3['home']} <span class='score-value'>{col3['score']}</span> {col3['away']}", unsafe_allow_html=True)
            st.markdown(f"**AH:** <span class='ah-value'>{col3['ahLine']}</span>", unsafe_allow_html=True)
        else:
            st.info(f"H2H Rivales (Col3): {col3.get('resultado', 'No encontrado') if col3 else 'No disponible'}")

        st.sidebar.success(f"🎉 Análisis completado en {time.time() - start_time:.2f} seg.")

    else:
        st.info("✨ Ingresa un ID de partido y haz clic en 'Analizar'.")
        
if __name__ == '__main__':
    st.set_page_config(layout="wide", page_title="Análisis de Partidos", initial_sidebar_state="expanded")
    display_other_feature_ui()
