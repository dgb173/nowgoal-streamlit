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

# --- FUNCIONES HELPER PARA PARSEO Y FORMATEO ---
def parse_ah_to_number_of(ah_line_str: str):
    if not isinstance(ah_line_str, str): return None
    s = ah_line_str.strip().replace(' ', '')
    if not s or s in ['-', '?']: return None
    try:
        if '/' in s:
            parts = s.split('/')
            val1 = float(parts[0])
            val2 = float(parts[1])
            if val1 < 0 and val2 > 0: val2 = -abs(val2)
            elif ah_line_str.strip().startswith('-') and val1 == 0 and val2 > 0: val2 = -abs(val2)
            return (val1 + val2) / 2.0
        else:
            return float(s)
    except (ValueError, IndexError):
        return None

def format_ah_as_decimal_string_of(ah_line_raw: str):
    if not isinstance(ah_line_raw, str) or not ah_line_raw.strip() or ah_line_raw.strip() in ['-', '?']:
        return PLACEHOLDER_NODATA
    numeric_value = parse_ah_to_number_of(ah_line_raw)
    if numeric_value is None: return PLACEHOLDER_NODATA
    if numeric_value == 0.0: return "0"
    if numeric_value.is_integer(): return f"{numeric_value:.0f}"
    return f"{numeric_value:.2f}".replace(".25", ".25").replace(".75", ".75").rstrip('0').rstrip('.')

def get_match_details_from_row_of(row_element, score_class_selector='score'):
    try:
        cells = row_element.find_all('td')
        if len(cells) < 12: return None
        home_tag = cells[2].find('a'); home = home_tag.text.strip() if home_tag else None
        away_tag = cells[4].find('a'); away = away_tag.text.strip() if away_tag else None
        if not home or not away: return None
        score_span = cells[3].find('span', class_=lambda x: x and score_class_selector in x)
        score_raw = score_span.text.strip().split('(')[0].strip() if score_span else '?-?'
        score_fmt = score_raw.replace('-', ':')
        handicap_cell = cells[11]
        ah_line_raw = handicap_cell.get('data-o', '').strip() or handicap_cell.text.strip()
        ah_line_raw = ah_line_raw if ah_line_raw and ah_line_raw not in ['-', '?'] else None
        return {'home': home, 'away': away, 'score': score_fmt,
                'ahLine': format_ah_as_decimal_string_of(ah_line_raw), 'ahLine_raw': ah_line_raw,
                'matchIndex': row_element.get('index'), 'league_id_hist': row_element.get('name')}
    except (AttributeError, IndexError):
        return None

# --- SESIÓN Y FETCHING (EFICIENTES Y CACHEADOS) ---
@st.cache_resource
def get_requests_session_of():
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(pool_connections=100, pool_maxsize=100, max_retries=retries)
    session.mount("https://", adapter); session.mount("http://", adapter)
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"})
    return session

@st.cache_data(ttl=3600)
def fetch_content(url, is_soup=True):
    try:
        resp = get_requests_session_of().get(url, timeout=8)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml") if is_soup else resp.text
    except requests.RequestException:
        return None

# --- FUNCIONES DE EXTRACCIÓN (ATÓMICAS Y RÁPIDAS) ---
@st.cache_data(ttl=7200)
def get_match_progression_stats_data(match_id: str):
    if not match_id or not isinstance(match_id, str) or not match_id.isdigit(): return None
    soup = fetch_content(f"{BASE_URL_OF}/match/live-{match_id}")
    if not soup: return None
    try:
        stats = {"Shots": ("-", "-"), "Shots on Goal": ("-", "-"), "Attacks": ("-", "-"), "Dangerous Attacks": ("-", "-")}
        if (tech_div := soup.find('div', id='teamTechDiv_detail')) and (stat_list := tech_div.find('ul', class_='stat')):
            for li in stat_list.find_all('li'):
                if (title_span := li.find('span', class_='stat-title')) and (title := title_span.get_text(strip=True)) in stats:
                    if (values := [v.get_text(strip=True) for v in li.find_all('span', class_='stat-c')]) and len(values) == 2:
                        stats[title] = (values[0], values[1])
        return pd.DataFrame(
            [{"Estadistica_EN": name, "Casa": v[0], "Fuera": v[1]} for name, v in stats.items()]
        ).set_index("Estadistica_EN")
    except (AttributeError, IndexError):
        return None

@st.cache_data(ttl=3600)
def get_main_match_odds_requests_of(match_id: str):
    odds_data = fetch_content(f"https://data.nowgoal25.com/3in1Odds/{match_id}", is_soup=False)
    result = {k: "N/A" for k in ["ah_home_cuota", "ah_linea_raw", "ah_away_cuota", "goals_over_cuota", "goals_linea_raw", "goals_under_cuota"]}
    if not odds_data or len(parts := odds_data.split('$$')) < 3: return result
    if (ah_line := next((p.split(',') for p in parts[0].split(';') if p.startswith("8,")), None)) and len(ah_line) > 4:
        result.update({"ah_home_cuota": ah_line[2], "ah_linea_raw": ah_line[3], "ah_away_cuota": ah_line[4]})
    if (ou_line := next((p.split(',') for p in parts[2].split(';') if p.startswith("8,")), None)) and len(ou_line) > 4:
        result.update({"goals_over_cuota": ou_line[2], "goals_linea_raw": ou_line[3], "goals_under_cuota": ou_line[4]})
    return result

@st.cache_data(ttl=3600)
def get_col3_h2h_details(match_id: str):
    soup_main = fetch_content(f"{BASE_URL_OF}/match/h2h-{match_id}")
    if not soup_main: return {"status": "error", "resultado": "Fallo H2H(1)"}
    
    rival_a, rival_b = None, None
    if (table1 := soup_main.find("table", id="table_v1")) and (row := table1.find("tr", vs="1")):
        if (tags := row.find_all("a", onclick=True)) and len(tags) > 1 and (m := re.search(r"team\((\d+)\)", tags[1]['onclick'])):
            rival_a = (row.get("index"), m.group(1), tags[1].text.strip())

    if (table2 := soup_main.find("table", id="table_v2")) and (row := table2.find("tr", vs="1")):
        if (tags := row.find_all("a", onclick=True)) and len(tags) > 0 and (m := re.search(r"team\((\d+)\)", tags[0]['onclick'])):
            rival_b = (row.get("index"), m.group(1), tags[0].text.strip())

    if not all([rival_a, rival_b]): return {"status": "error", "resultado": "Fallo H2H(2)"}
    
    h2h_url_id, rival_a_id, rival_a_name = rival_a; _, rival_b_id, rival_b_name = rival_b
    soup_rivals = fetch_content(f"{BASE_URL_OF}/match/h2h-{h2h_url_id}")
    if not soup_rivals: return {"status": "error", "resultado": "Fallo H2H(3)"}
    
    if table := soup_rivals.find("table", id="table_v2"):
        for row in table.find_all("tr", id=re.compile(r"tr2_\d+")):
            if (tags := row.find_all("a", onclick=True)) and len(tags) > 1:
                ids = {re.search(r"(\d+)", t['onclick']).group(1) for t in tags if re.search(r"(\d+)", t['onclick'])}
                if ids == {rival_a_id, rival_b_id} and (details := get_match_details_from_row_of(row, 'fscore_2')):
                    return {"status": "found", **details}
    return {"status": "not_found", "resultado": f"H2H no encontrado: {rival_a_name} vs {rival_b_name}"}

# --- FUNCIÓN ORQUESTADORA DE DATOS DESDE EL SOUP ---
def extract_data_from_main_soup(soup):
    if not soup: return {}
    
    data = {"home_name": "Local", "away_name": "Visitante"}
    # Info básica del script
    if (script_tag := soup.find("script", string=re.compile(r"var _matchInfo ="))) and (s := script_tag.string):
        data.update({
            "home_id": m.group(1) if (m := re.search(r"hId:\s*parseInt\('(\d+)'\)", s)) else None,
            "away_id": m.group(1) if (m := re.search(r"gId:\s*parseInt\('(\d+)'\)", s)) else None,
            "league_id": m.group(1) if (m := re.search(r"sclassId:\s*parseInt\('(\d+)'\)", s)) else None,
            "home_name": m.group(1).replace("\\'", "'") if (m := re.search(r"hName:\s*'([^']*)'", s)) else "Local",
            "away_name": m.group(1).replace("\\'", "'") if (m := re.search(r"gName:\s*'([^']*)'", s)) else "Visitante",
            "league_name": m.group(1).replace("\\'", "'") if (m := re.search(r"lName:\s*'([^']*)'", s)) else "N/A"
        })
    # Marcador final
    data["final_score"] = '?:?'
    if (score_tags := soup.select('#mScore .end .score')) and len(score_tags) == 2:
        data["final_score"] = f"{score_tags[0].text.strip()}:{score_tags[1].text.strip()}"

    # Datos extraídos directamente de tablas en el soup
    if (standings_section := soup.find("div", id="porletP4")):
        data['home_standings'] = parse_standings_table(standings_section, data['home_name'])
        data['away_standings'] = parse_standings_table(standings_section, data['away_name'])

    if h2h_table := soup.find("table", id="table_v3"):
        data['h2h_data'] = parse_h2h_table(h2h_table, data['home_name'], data['away_name'], data.get('league_id'))

    data['last_home_match'] = find_last_match_in_table(soup, "table_v1", data['home_name'], data.get('league_id'), is_home=True)
    data['last_away_match'] = find_last_match_in_table(soup, "table_v2", data['away_name'], data.get('league_id'), is_home=False)

    if data.get('last_away_match') and (rival_name := data['last_away_match'].get('home')):
        data['comp_L_vs_UV'] = find_last_match_in_table(soup, "table_v1", data['home_name'], data.get('league_id'), is_home=True, specific_opponent=rival_name)
    if data.get('last_home_match') and (rival_name := data['last_home_match'].get('away')):
        data['comp_V_vs_UL'] = find_last_match_in_table(soup, "table_v2", data['away_name'], data.get('league_id'), is_home=False, specific_opponent=rival_name)
        
    return data

def parse_standings_table(standings_section, team_name):
    # Función de parseo de clasificación (robusta y reutilizable)
    data = {"name": team_name, "ranking": "N/A", "total_pj": "-", "total_v": "-", "total_e": "-", "total_d": "-", "total_gf": "-", "total_gc": "-", "specific_pj": "-", "specific_v": "-", "specific_e": "-", "specific_d": "-", "specific_gf": "-", "specific_gc": "-", "specific_type": "N/A"}
    div_type, table_class, role_str = ("home-div", "team-table-home", "Local") if (d:=standings_section.find("div",class_="home-div")) and team_name.lower() in d.get_text().lower() else (("guest-div", "team-table-guest", "Visitante") if (d:=standings_section.find("div",class_="guest-div")) and team_name.lower() in d.get_text().lower() else (None,None,None))
    if not div_type or not (table_soup := standings_section.find("div", class_=div_type).find("table", class_=table_class)): return data
    data['specific_type'] = f"Est. como {role_str} (Liga)"
    if header_link := table_soup.find("a"): data['ranking'] = (m.group(1) if (m := re.search(r"\[(?:[^\]]+-)?(\d+)\]", header_link.get_text())) else "N/A")
    for row in table_soup.find_all("tr", align="center"):
        if (cells := row.find_all("td")) and len(cells) > 6:
            stats = [c.get_text(strip=True) or "-" for c in cells]
            if stats[0] == "Total":
                data.update({"total_pj": stats[1], "total_v": stats[2], "total_e": stats[3], "total_d": stats[4], "total_gf": stats[5], "total_gc": stats[6]})
            elif stats[0] == role_str.capitalize():
                data.update({"specific_pj": stats[1], "specific_v": stats[2], "specific_e": stats[3], "specific_d": stats[4], "specific_gf": stats[5], "specific_gc": stats[6]})
    return data

def parse_h2h_table(table, home_name, away_name, league_id):
    h2h_list = [d for r in table.find_all("tr", id=re.compile(r"tr3_\d+")) if (d := get_match_details_from_row_of(r, 'fscore_3')) and (not league_id or not d.get('league_id_hist') or d['league_id_hist'] == league_id)]
    if not h2h_list: return None, None
    h2h_general = h2h_list[0]
    h2h_specific = next((h for h in h2h_list if h['home'].lower() == home_name.lower() and h['away'].lower() == away_name.lower()), None)
    return h2h_general, h2h_specific

def find_last_match_in_table(soup, table_id, team_name, league_id, is_home, specific_opponent=None):
    if not (table := soup.find(id=table_id)): return None
    for row in table.find_all("tr", id=re.compile(rf"tr{table_id[-1]}_\d+")):
        if league_id and row.get("name") and row.get("name") != league_id: continue
        if details := get_match_details_from_row_of(row, 'fscore_1' if is_home else 'fscore_2'):
            is_team_home = details['home'].lower() == team_name.lower()
            is_team_away = details['away'].lower() == team_name.lower()
            is_opponent_home = specific_opponent and details['home'].lower() == specific_opponent.lower()
            is_opponent_away = specific_opponent and details['away'].lower() == specific_opponent.lower()
            
            if specific_opponent: # Buscando comparativa
                if (is_team_home and is_opponent_away) or (is_team_away and is_opponent_home):
                    return details
            else: # Buscando último partido
                if (is_home and is_team_home) or (not is_home and is_team_away):
                    return details
    return None

# --- UI PRINCIPAL (VERSIÓN FINAL) ---
def display_other_feature_ui():
    st.markdown("""<style>/* CSS Omitido */</style>""", unsafe_allow_html=True)
    st.sidebar.title("⚙️ Configuración del Partido")
    main_match_id_input = st.sidebar.text_input("🆔 ID Partido Principal:", "2696131", key="id_input")

    if st.sidebar.button("🚀 Analizar Partido", type="primary", use_container_width=True):
        match_id = "".join(filter(str.isdigit, main_match_id_input))
        if not match_id:
            st.error("⚠️ ID de partido no válido."); return

        start_time = time.time()
        prog_stats_data = {}

        with st.spinner("⚡️ Realizando extracción paralela..."):
            with ThreadPoolExecutor(max_workers=5) as executor:
                future_main_soup = executor.submit(fetch_content, f"/match/h2h-{match_id}")
                future_odds = executor.submit(get_main_match_odds_requests_of, match_id)
                future_col3 = executor.submit(get_col3_h2h_details, match_id)
                main_soup = future_main_soup.result()
                if not main_soup: st.error("❌ Fallo crítico al obtener datos."); return
                
                main_data = extract_data_from_main_soup(main_soup)
                odds_data = future_odds.result()
                col3_data = future_col3.result()

        with st.spinner("📊 Obteniendo estadísticas de progresión..."):
            with ThreadPoolExecutor(max_workers=10) as executor:
                tasks = {'main': executor.submit(get_match_progression_stats_data, str(match_id))}
                if main_data.get('last_home_match'): tasks['last_home'] = executor.submit(get_match_progression_stats_data, main_data['last_home_match']['matchIndex'])
                if main_data.get('last_away_match'): tasks['last_away'] = executor.submit(get_match_progression_stats_data, main_data['last_away_match']['matchIndex'])
                if col3_data.get('status') == 'found': tasks['col3'] = executor.submit(get_match_progression_stats_data, col3_data['matchIndex'])
                h2h_gen, h2h_spec = main_data.get('h2h_data', (None,None))
                if h2h_gen: tasks['h2h_gen'] = executor.submit(get_match_progression_stats_data, h2h_gen['matchIndex'])
                if h2h_spec: tasks['h2h_spec'] = executor.submit(get_match_progression_stats_data, h2h_spec['matchIndex'])
                prog_stats_data = {key: future.result() for key, future in tasks.items()}

        # ---- INICIO DEL RENDERIZADO ----
        home_name = main_data.get('home_name', 'Local')
        away_name = main_data.get('away_name', 'Visitante')
        
        st.markdown(f"## 🆚 <span class='home-color'>{home_name}</span> vs <span class='away-color'>{away_name}</span>", unsafe_allow_html=True)
        st.caption(f"🏆 {main_data.get('league_name', 'N/A')} | 🆔 {match_id}")
        st.divider()

        with st.expander("📈 Clasificación en Liga", expanded=True):
            c1, c2 = st.columns(2)
            display_standings_card(c1, main_data.get('home_standings',{}), home_name, "home-color")
            display_standings_card(c2, main_data.get('away_standings',{}), away_name, "away-color")

        with st.expander("⚖️ Cuotas Iniciales (Bet365) y Marcador Final", expanded=False):
            c1,c2,c3=st.columns(3)
            c1.metric("🏁 Marcador Final", main_data.get('final_score', '?:?'))
            c2.metric("⚖️ AH (Línea Inicial)", format_ah_as_decimal_string_of(odds_data.get("ah_linea_raw")), f"{odds_data.get('ah_home_cuota', '-')} / {odds_data.get('ah_away_cuota', '-')}")
            c3.metric("🥅 Goles (Línea Inicial)", format_ah_as_decimal_string_of(odds_data.get("goals_linea_raw")), f"O:{odds_data.get('goals_over_cuota','-')} / U:{odds_data.get('goals_under_cuota','-')}")
            if main_data.get('final_score', '?:?') != '?:?': display_match_progression_stats_view(prog_stats_data.get('main'), home_name, away_name, "Partido Principal")

        st.subheader("⚡ Rendimiento Reciente y H2H Indirecto")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(f"**Último <span class='home-color'>{home_name}</span> (Casa)**", unsafe_allow_html=True)
            if last_home := main_data.get('last_home_match'):
                st.markdown(f"{last_home['home']} <span class='score-value'>{last_home['score']}</span> {last_home['away']}", unsafe_allow_html=True)
                st.markdown(f"**AH:** <span class='ah-value'>{last_home['ahLine']}</span>", unsafe_allow_html=True)
                display_match_progression_stats_view(prog_stats_data.get('last_home'), last_home['home'], last_home['away'], "Último Local")
            else: st.info("No encontrado.")

        with c2:
            st.markdown(f"**Último <span class='away-color'>{away_name}</span> (Fuera)**", unsafe_allow_html=True)
            if last_away := main_data.get('last_away_match'):
                st.markdown(f"{last_away['home']} <span class='score-value'>{last_away['score']}</span> {last_away['away']}", unsafe_allow_html=True)
                st.markdown(f"**AH:** <span class='ah-value'>{last_away['ahLine']}</span>", unsafe_allow_html=True)
                display_match_progression_stats_view(prog_stats_data.get('last_away'), last_away['home'], last_away['away'], "Último Visitante")
            else: st.info("No encontrado.")
        
        with c3:
            st.markdown(f"**H2H Rivales (Col3)**", unsafe_allow_html=True)
            if col3_data.get("status") == "found":
                st.markdown(f"{col3_data['home']} <span class='score-value'>{col3_data['score']}</span> {col3_data['away']}", unsafe_allow_html=True)
                st.markdown(f"**AH:** <span class='ah-value'>{col3_data['ahLine']}</span>", unsafe_allow_html=True)
                display_match_progression_stats_view(prog_stats_data.get('col3'), col3_data['home'], col3_data['away'], "H2H Rivales")
            else: st.info(col3_data.get('resultado', 'No encontrado.'))
        
        with st.expander("🔁 Comparativas Indirectas", expanded=False):
            c1,c2 = st.columns(2)
            with c1:
                st.markdown(f"**<span class='home-color'>{home_name}</span> vs Últ. Rival de {away_name}**", unsafe_allow_html=True)
                if comp := main_data.get('comp_L_vs_UV'):
                    st.markdown(f"{comp['home']} <span class='score-value'>{comp['score']}</span> {comp['away']}", unsafe_allow_html=True)
                    st.markdown(f"**AH:** <span class='ah-value'>{comp['ahLine']}</span>", unsafe_allow_html=True)
                else: st.caption("No encontrado.")
            with c2:
                st.markdown(f"**<span class='away-color'>{away_name}</span> vs Últ. Rival de {home_name}**", unsafe_allow_html=True)
                if comp := main_data.get('comp_V_vs_UL'):
                    st.markdown(f"{comp['home']} <span class='score-value'>{comp['score']}</span> {comp['away']}", unsafe_allow_html=True)
                    st.markdown(f"**AH:** <span class='ah-value'>{comp['ahLine']}</span>", unsafe_allow_html=True)
                else: st.caption("No encontrado.")
        
        with st.expander("🔰 H2H Directos", expanded=False):
            h2h_gen, h2h_spec = main_data.get('h2h_data', (None,None))
            c1,c2 = st.columns(2)
            with c1:
                st.markdown(f"**H2H General (Último)**", unsafe_allow_html=True)
                if h2h_gen:
                    st.metric("Resultado", h2h_gen['score'])
                    st.metric("Hándicap", h2h_gen['ahLine'])
                    display_match_progression_stats_view(prog_stats_data.get('h2h_gen'), h2h_gen['home'], h2h_gen['away'], "H2H General")
                else: st.info("No encontrado.")
            with c2:
                st.markdown(f"**H2H ({home_name} en Casa)**", unsafe_allow_html=True)
                if h2h_spec:
                    st.metric("Resultado", h2h_spec['score'])
                    st.metric("Hándicap", h2h_spec['ahLine'])
                    display_match_progression_stats_view(prog_stats_data.get('h2h_spec'), h2h_spec['home'], h2h_spec['away'], "H2H Específico")
                else: st.info("No encontrado.")

        st.sidebar.success(f"🎉 Análisis completado en {time.time() - start_time:.2f} seg.")
    else:
        st.info("✨ Ingresa un ID de partido y haz clic en 'Analizar'.")

if __name__ == '__main__':
    st.set_page_config(layout="wide", page_title="Análisis de Partidos (OF)", initial_sidebar_state="expanded")
    display_other_feature_ui()
