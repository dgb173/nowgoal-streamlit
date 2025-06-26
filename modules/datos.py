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

# --- CONFIGURACIÓN GLOBAL ---
BASE_URL_OF = "https://live18.nowgoal25.com"
PLACEHOLDER_NODATA = "*(No disponible)*"

# --- SESIÓN Y FETCHING (EFICIENTE Y REUTILIZABLE) ---
@st.cache_resource
def get_requests_session_of():
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=0.4, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(pool_connections=50, pool_maxsize=50, max_retries=retries)
    session.mount("https://", adapter); session.mount("http://", adapter)
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
    return session

def fetch_soup(path: str):
    """Obtiene y parsea una página. Reemplaza fetch_soup_requests_of."""
    url = f"{BASE_URL_OF}{path}"
    try:
        response = get_requests_session_of().get(url, timeout=10)
        response.raise_for_status()
        return BeautifulSoup(response.text, "lxml")
    except requests.RequestException:
        return None

# --- PARSEO Y FORMATEO ---
def parse_ah_to_number_of(ah_line_str: str):
    #... [Código de parseo sin cambios] ...
    if not isinstance(ah_line_str, str): return None
    s = ah_line_str.strip().replace(' ', '')
    if not s or s in ['-', '?']: return None
    original_starts_with_minus = ah_line_str.strip().startswith('-')
    try:
        if '/' in s:
            parts = s.split('/'); p1,p2=float(parts[0]),float(parts[1])
            if p1 < 0 and p2 > 0: p2=-abs(p2)
            elif original_starts_with_minus and p1==0.0 and p2 > 0: p2=-abs(p2)
            return (p1 + p2) / 2.0
        return float(s)
    except (ValueError, IndexError): return None

def format_ah_as_decimal_string_of(ah_line_raw: str | None):
    if not ah_line_raw: return PLACEHOLDER_NODATA
    numeric_value = parse_ah_to_number_of(ah_line_raw)
    if numeric_value is None: return PLACEHOLDER_NODATA
    if numeric_value == 0.0: return "0"
    if numeric_value.is_integer(): return f"{int(numeric_value)}"
    return f"{numeric_value:.2f}".replace('.25', '.25').replace('.75', '.75').rstrip('0').rstrip('.')

def get_match_details_from_row_of(row, score_class_selector):
    try:
        cells = row.find_all('td')
        if len(cells) < 12: return None
        home_tag = cells[2].find('a'); away_tag = cells[4].find('a')
        if not home_tag or not away_tag: return None
        
        score_span = cells[3].find('span', class_=score_class_selector)
        ah_cell = cells[11]
        ah_raw = ah_cell.get('data-o', '').strip() or ah_cell.text.strip()
        ah_raw = ah_raw if ah_raw not in ['-', '', '?'] else None
        
        return {
            'home': home_tag.text.strip(), 'away': away_tag.text.strip(),
            'score': (score_span.text.split('(')[0].strip()).replace('-', ':') if score_span else '?:?',
            'ahLine': format_ah_as_decimal_string_of(ah_raw),
            'ahLine_raw': ah_raw,
            'matchIndex': row.get('index'),
            'league_id_hist': row.get('name')
        }
    except Exception: return None

# --- FUNCIONES DE EXTRACCIÓN RÁPIDAS (SIN SELENIUM) ---
def get_main_match_odds_of(match_id):
    url = f"https://data.nowgoal25.com/3in1Odds/{match_id}"
    try:
        response_text = get_requests_session_of().get(url, timeout=5).text
        parts = response_text.split('$$')
        result = {}
        if len(parts) >= 3:
            if ah_line := next((p.split(',') for p in parts[0].split(';') if p.startswith("8,")), None): # Bet365
                result['ah_home_cuota'] = ah_line[2]; result['ah_linea_raw'] = ah_line[3]; result['ah_away_cuota'] = ah_line[4]
            if ou_line := next((p.split(',') for p in parts[2].split(';') if p.startswith("8,")), None):
                result['goals_over_cuota'] = ou_line[2]; result['goals_linea_raw'] = ou_line[3]; result['goals_under_cuota'] = ou_line[4]
        return result
    except Exception: return {}

@st.cache_data(ttl=7200)
def get_match_progression_stats_data(match_id):
    if not match_id or not str(match_id).isdigit(): return None
    url = f"https://live18.nowgoal25.com/match/live-{match_id}"
    try:
        soup = fetch_soup(f"/match/live-{match_id}")
        if not soup: return None
        stats = {title: ("-", "-") for title in ["Shots", "Shots on Goal", "Attacks", "Dangerous Attacks"]}
        if ul := soup.select_one('#teamTechDiv_detail ul.stat'):
            for li in ul.find_all('li'):
                if (title := li.select_one('span.stat-title')) and (title_text := title.get_text(strip=True)) in stats:
                    if vals := [s.get_text(strip=True) for s in li.select('span.stat-c')]:
                        if len(vals) == 2: stats[title_text] = tuple(vals)
        return pd.DataFrame([{"Estadistica_EN": k, "Casa": v[0], "Fuera": v[1]} for k, v in stats.items()]).set_index("Estadistica_EN")
    except Exception: return None

# --- FUNCIONES DE PARSEO DE SOUP (YA CARGADO) ---
def get_team_league_info_from_script_of(soup):
    script_tag = soup.find("script", string=re.compile(r"var _matchInfo ="))
    if script_tag and (s := script_tag.string):
        return {
            "home_id": (m.group(1) if (m := re.search(r"hId:\s*parseInt\('(\d+)'\)", s)) else None),
            "away_id": (m.group(1) if (m := re.search(r"gId:\s*parseInt\('(\d+)'\)", s)) else None),
            "league_id": (m.group(1) if (m := re.search(r"sclassId:\s*parseInt\('(\d+)'\)", s)) else None),
            "home_name": (m.group(1).replace("\\'", "'") if (m := re.search(r"hName:\s*'([^']*)'", s)) else "Local"),
            "away_name": (m.group(1).replace("\\'", "'") if (m := re.search(r"gName:\s*'([^']*)'", s)) else "Visitante"),
            "league_name": (m.group(1).replace("\\'", "'") if (m := re.search(r"lName:\s*'([^']*)'", s)) else "N/A"),
        }
    return {}

def extract_standings_data_of(soup, team_name):
    # Lógica de parseo de tabla de clasificación...
    data = {"name": team_name, "ranking": "N/A", "total_pj": "-", "specific_type": "N/A"}
    if not (standings_section := soup.find("div", id="porletP4")): return data
    
    div_type, table_class, role_str = (None, None, None)
    if (d:=standings_section.find("div",class_="home-div")) and team_name.lower() in d.get_text().lower():
        div_type, table_class, role_str = ("home-div", "team-table-home", "Local")
    elif (d:=standings_section.find("div",class_="guest-div")) and team_name.lower() in d.get_text().lower():
        div_type, table_class, role_str = ("guest-div", "team-table-guest", "Visitante")
    
    if not div_type or not (table_soup := standings_section.find("div", class_=div_type).find("table", class_=table_class)): return data
    data['specific_type'] = f"Est. como {role_str} (Liga)"
    if header_link := table_soup.find("a"): data['ranking'] = (m.group(1) if (m := re.search(r"\[(?:[^\]]+-)?(\d+)\]", header_link.get_text())) else "N/A")
    for row in table_soup.find_all("tr", align="center"):
        if (cells := row.find_all("td")) and len(cells) > 6:
            stats = [c.get_text(strip=True) or "-" for c in cells]
            key_prefix = "total" if stats[0] == "Total" else ("specific" if stats[0] == role_str.capitalize() else None)
            if key_prefix:
                data.update({f"{key_prefix}_pj":stats[1],f"{key_prefix}_v":stats[2],f"{key_prefix}_e":stats[3],
                             f"{key_prefix}_d":stats[4],f"{key_prefix}_gf":stats[5],f"{key_prefix}_gc":stats[6]})
    return data
    
def get_h2h_data_from_soup_of(soup, home, away, league_id):
    h2h_table = soup.find("table", id="table_v3")
    if not h2h_table: return None, None
    matches = [d for r in h2h_table.find_all('tr') if (d:=get_match_details_from_row_of(r,'fscore_3')) and (not league_id or d['league_id_hist']==league_id)]
    if not matches: return None, None
    general = matches[0]
    specific = next((m for m in matches if m['home'].lower()==home.lower() and m['away'].lower()==away.lower()), None)
    return general, specific
    
def get_last_match_from_soup_of(soup, table_id, team_name, league_id, is_home):
    table = soup.find("table", id=table_id)
    if not table: return None
    for row in table.find_all('tr'):
        if league_id and row.get('name') != league_id: continue
        score_selector = 'fscore_1' if is_home else 'fscore_2'
        if details := get_match_details_from_row_of(row, score_selector):
            if (is_home and details['home'].lower() == team_name.lower()) or \
               (not is_home and details['away'].lower() == team_name.lower()):
                return details
    return None

def get_comparative_match_from_soup_of(soup, table_id, main_team, rival, league_id, is_home_table):
    if not rival: return None
    table = soup.find("table", id=table_id)
    if not table: return None
    for row in table.find_all('tr'):
        if league_id and row.get('name') and row.get('name') != league_id: continue
        details = get_match_details_from_row_of(row, 'fscore_1' if is_home_table else 'fscore_2')
        if details and {main_team.lower(), rival.lower()} == {details['home'].lower(), details['away'].lower()}:
            details['localia'] = 'H' if details['home'].lower() == main_team.lower() else 'A'
            return details
    return None

def get_col3_h2h_of(main_soup):
    h2h_url_id, rival_a_id, rival_a_name = (None, None, None)
    _, rival_b_id, rival_b_name = (None, None, None)

    if (table1 := main_soup.find("table", id="table_v1")) and (row := table1.find("tr", vs="1")) and (tags := row.select("a[onclick]")) and len(tags) > 1:
        if m := re.search(r"team\((\d+)\)", tags[1]['onclick']): rival_a_id=m.group(1); rival_a_name=tags[1].text.strip(); h2h_url_id = row.get('index')
            
    if (table2 := main_soup.find("table", id="table_v2")) and (row := table2.find("tr", vs="1")) and (tags := row.select("a[onclick]")) and len(tags) > 0:
        if m := re.search(r"team\((\d+)\)", tags[0]['onclick']): rival_b_id=m.group(1); rival_b_name=tags[0].text.strip()
    
    if not all([h2h_url_id, rival_a_id, rival_b_id]): return {"status": "error", "resultado": "No se identificaron rivales Col3."}
    
    soup_rivals = fetch_soup(f"/match/h2h-{h2h_url_id}")
    if not soup_rivals: return {"status": "error", "resultado": "Fallo al cargar pág. de rivales."}
    
    table_rivals = soup_rivals.find("table", id="table_v2")
    if not table_rivals: return {"status": "error", "resultado": "Tabla de rivales no encontrada."}
    
    for row in table_rivals.find_all('tr', id=re.compile(r"tr2_\d+")):
        if (tags := row.select("a[onclick]")) and len(tags) > 1:
            ids_in_row = {m.group(1) for t in tags if (m:=re.search(r"team\((\d+)\)", t['onclick']))}
            if ids_in_row == {rival_a_id, rival_b_id}:
                if details := get_match_details_from_row_of(row, 'fscore_2'):
                    return {"status": "found", **details}

    return {"status": "not_found", "resultado": f"H2H no encontrado: {rival_a_name} vs {rival_b_name}"}

# --- FUNCIÓN DE VISUALIZACIÓN DE ESTADÍSTICAS ---
def display_prog_stats_view(prog_stats_df, home_name, away_name, title):
    if prog_stats_df is None or prog_stats_df.empty:
        st.caption(f"ℹ️ _Est. progresión no disp. para: {title}_")
        return

    st.markdown(f"**Est. Progresión: _{title}_**")
    stat_map = {"Shots": "Disparos", "Shots on Goal": "A Puerta", "Attacks": "Ataques", "Dangerous Attacks": "Ataq. Peligrosos"}
    for stat_en, stat_es in stat_map.items():
        if stat_en in prog_stats_df.index:
            home_val, away_val = prog_stats_df.loc[stat_en, 'Casa'], prog_stats_df.loc[stat_en, 'Fuera']
            st.text(f"{home_val.rjust(3)} {stat_es.ljust(15)} {away_val.ljust(3)}")


# --- UI PRINCIPAL (VERSIÓN FINAL Y COMPLETA) ---
def display_other_feature_ui():
    # CSS...
    st.markdown("""<style>/* CSS Omitido por brevedad */</style>""", unsafe_allow_html=True)
    st.sidebar.title("⚙️ Configuración")
    main_match_id_input = st.sidebar.text_input("🆔 ID Partido Principal:", "2696131", key="id_input")

    if st.sidebar.button("🚀 Analizar Partido", type="primary", use_container_width=True):
        match_id = "".join(filter(str.isdigit, main_match_id_input))
        if not match_id:
            st.error("⚠️ ID de partido no válido."); return

        start_time = time.time()
        
        with st.spinner("⚡ Realizando extracción..."):
            main_soup = fetch_soup(f"/match/h2h-{match_id}")
            if not main_soup:
                st.error(f"❌ Fallo crítico al obtener datos para el ID {match_id}."); return
            
            # --- Extracción de Datos ---
            basic_info = get_team_league_info_from_script_of(main_soup)
            home_name, away_name, league_id = basic_info.get('home_name'), basic_info.get('away_name'), basic_info.get('league_id')
            
            home_standings = extract_standings_data_of(main_soup, home_name)
            away_standings = extract_standings_data_of(main_soup, away_name)

            h2h_gen, h2h_spec = get_h2h_data_from_soup_of(main_soup, home_name, away_name, league_id)
            
            last_home = get_last_match_from_soup_of(main_soup, "table_v1", home_name, league_id, is_home=True)
            last_away = get_last_match_from_soup_of(main_soup, "table_v2", away_name, league_id, is_home=False)

            comp_L_vs_rival = get_comparative_match_from_soup_of(main_soup, "table_v1", home_name, last_away.get('home') if last_away else None, league_id, is_home_table=True)
            comp_V_vs_rival = get_comparative_match_from_soup_of(main_soup, "table_v2", away_name, last_home.get('away') if last_home else None, league_id, is_home_table=False)

            col3_data = get_col3_h2h_of(main_soup)

            odds_data = get_main_match_odds_of(match_id)
            
            final_score_tag = main_soup.select_one('#mScore .end .score')
            final_score = main_soup.select('#mScore .end .score')
            is_finished = final_score_tag is not None and len(final_score) == 2

            prog_stats = {}
            if is_finished: # Solo busca stats si el partido acabó
                 prog_stats['main'] = get_match_progression_stats_data(match_id)

        # ---- RENDERIZADO ----
        st.markdown(f"## 🆚 <span class='home-color'>{home_name}</span> vs <span class='away-color'>{away_name}</span>", unsafe_allow_html=True)
        st.caption(f"🏆 {basic_info.get('league_name', 'N/A')} | 🆔 {match_id}")
        st.divider()

        with st.expander("📈 Clasificación en Liga", expanded=True):
            c1, c2 = st.columns(2)
            display_standings_card(c1, home_standings, home_name, "home-color")
            display_standings_card(c2, away_standings, away_name, "away-color")

        with st.expander("⚖️ Cuotas (Bet365) y Marcador Final", expanded=False):
            c1, c2, c3 = st.columns(3)
            score_display = f"{final_score[0].text.strip()}:{final_score[1].text.strip()}" if is_finished else "vs"
            c1.metric("🏁 Marcador Final", score_display)
            c2.metric("⚖️ AH (Línea Inicial)", format_ah_as_decimal_string_of(odds_data.get("ah_linea_raw")), f"{odds_data.get('ah_home_cuota', '-')} / {odds_data.get('ah_away_cuota', '-')}")
            c3.metric("🥅 Goles (Línea Inicial)", format_ah_as_decimal_string_of(odds_data.get("goals_linea_raw")), f"O:{odds_data.get('goals_over_cuota','-')} / U:{odds_data.get('goals_under_cuota','-')}")
            if is_finished: display_prog_stats_view(prog_stats.get('main'), home_name, away_name, "Principal")

        st.subheader("⚡ Rendimiento Reciente y H2H Indirecto")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(f"**Último <span class='home-color'>{home_name}</span> (Casa)**", unsafe_allow_html=True)
            if last_home: st.markdown(f"{last_home['home']} <span class='score-value'>{last_home['score']}</span> {last_home['away']}<br>**AH:** <span class='ah-value'>{last_home['ahLine']}</span>", unsafe_allow_html=True)
            else: st.info("No encontrado.")
        with c2:
            st.markdown(f"**Último <span class='away-color'>{away_name}</span> (Fuera)**", unsafe_allow_html=True)
            if last_away: st.markdown(f"{last_away['home']} <span class='score-value'>{last_away['score']}</span> {last_away['away']}<br>**AH:** <span class='ah-value'>{last_away['ahLine']}</span>", unsafe_allow_html=True)
            else: st.info("No encontrado.")
        with c3:
            st.markdown(f"**H2H Rivales (Col3)**", unsafe_allow_html=True)
            if col3_data.get('status') == 'found': st.markdown(f"{col3_data['home']} <span class='score-value'>{col3_data['score']}</span> {col3_data['away']}<br>**AH:** <span class='ah-value'>{col3_data['ahLine']}</span>", unsafe_allow_html=True)
            else: st.info(col3_data.get('resultado', 'No encontrado.'))
        
        with st.expander("🔁 Comparativas Indirectas", expanded=False):
            c1,c2 = st.columns(2)
            with c1:
                st.markdown(f"**<span class='home-color'>{home_name}</span> vs Últ. Rival de <span class='away-color'>{away_name}</span>**", unsafe_allow_html=True)
                if comp_L_vs_rival: st.markdown(f"{comp_L_vs_rival['home']} <span class='score-value'>{comp_L_vs_rival['score']}</span> {comp_L_vs_rival['away']}<br>**AH:** <span class='ah-value'>{comp_L_vs_rival['ahLine']}</span> ({comp_L_vs_rival['localia']})", unsafe_allow_html=True)
                else: st.caption("No disponible.")
            with c2:
                st.markdown(f"**<span class='away-color'>{away_name}</span> vs Últ. Rival de <span class='home-color'>{home_name}</span>**", unsafe_allow_html=True)
                if comp_V_vs_rival: st.markdown(f"{comp_V_vs_rival['home']} <span class='score-value'>{comp_V_vs_rival['score']}</span> {comp_V_vs_rival['away']}<br>**AH:** <span class='ah-value'>{comp_V_vs_rival['ahLine']}</span> ({comp_V_vs_rival['localia']})", unsafe_allow_html=True)
                else: st.caption("No disponible.")

        with st.expander("🔰 H2H Directos", expanded=False):
            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f"**H2H General (Último)**", unsafe_allow_html=True)
                if h2h_gen: st.metric("Resultado", h2h_gen['score'], delta=h2h_gen['ahLine'], delta_color="off")
                else: st.info("No encontrado.")
            with c2:
                st.markdown(f"**H2H ({home_name} en Casa)**", unsafe_allow_html=True)
                if h2h_spec: st.metric("Resultado", h2h_spec['score'], delta=h2h_spec['ahLine'], delta_color="off")
                else: st.info("No encontrado.")

        st.sidebar.success(f"🎉 Análisis completado en {time.time() - start_time:.2f} seg.")
    else:
        st.info("✨ Ingresa un ID de partido y haz clic en 'Analizar'.")

if __name__ == '__main__':
    st.set_page_config(layout="wide", page_title="Análisis de Partidos", initial_sidebar_state="expanded")
    display_other_feature_ui()
