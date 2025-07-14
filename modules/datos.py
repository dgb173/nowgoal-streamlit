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
API_ODDS_URL = "https://data.nowgoal.com/gf/data/panDetail/{}.json"
API_STATS_URL = "https://live18.nowgoal25.com/match/live-{}"
PLACEHOLDER_NODATA = "*(No disponible)*"

# --- FUNCIONES HELPER PARA PARSEO Y FORMATEO (Optimizadas) ---
def parse_ah_to_number_of(ah_line_str: str):
    if not isinstance(ah_line_str, str): return None
    s = ah_line_str.strip().replace(' ', '')
    if not s or s in ['-', '?']: return None
    try:
        if '/' in s:
            p1, p2 = map(float, s.split('/'))
            return (p1 + p2) / 2.0
        return float(s)
    except (ValueError, TypeError):
        return None

def format_ah_as_decimal_string_of(ah_line_str: str):
    numeric_value = parse_ah_to_number_of(ah_line_str)
    if numeric_value is None:
        return PLACEHOLDER_NODATA if ah_line_str not in ['-','?'] else ah_line_str
    if numeric_value == 0.0: return "0"
    sign = "" if numeric_value > 0 else "-"
    abs_num = abs(numeric_value)
    if abs_num % 1 == 0.25 or abs_num % 1 == 0.75:
        return f"{sign}{abs_num:.2f}"
    return f"{sign}{abs_num:.2f}".replace(".50", ".5").replace(".00", "")

# --- SESIÓN Y FETCHING ---
@st.cache_resource
def get_requests_session_of():
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36"})
    return session

@st.cache_data(ttl=3600)
def fetch_soup_requests_of(path):
    session = get_requests_session_of()
    try:
        resp = session.get(f"{BASE_URL_OF}{path}", timeout=10)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException:
        return None

# --- FUNCIONES DE EXTRACCIÓN CONCURRENTES Y OPTIMIZADAS ---

def fetch_single_stat(match_id):
    """Función worker para buscar estadísticas de un solo partido."""
    if not match_id or not match_id.isdigit():
        return match_id, None
    try:
        session = get_requests_session_of()
        response = session.get(API_STATS_URL.format(match_id), timeout=8)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'lxml')
        team_tech_div = soup.find('div', id='teamTechDiv_detail')
        if not team_tech_div: return match_id, pd.DataFrame()

        stats = {
            "Shots": ["-", "-"], "Shots on Goal": ["-", "-"],
            "Attacks": ["-", "-"], "Dangerous Attacks": ["-", "-"]
        }
        for li in team_tech_div.find_all('li'):
            title_span = li.find('span', class_='stat-title')
            if title_span and (stat_title := title_span.get_text(strip=True)) in stats:
                values = li.find_all('span', class_='stat-c')
                if len(values) == 2:
                    stats[stat_title] = [values[0].get_text(strip=True), values[1].get_text(strip=True)]
        
        rows = [{"Estadistica_EN": name, "Casa": vals[0], "Fuera": vals[1]} for name, vals in stats.items()]
        df = pd.DataFrame(rows).set_index("Estadistica_EN")
        return match_id, df
    except (requests.RequestException, Exception):
        return match_id, None

@st.cache_data(ttl=7200)
def batch_fetch_progression_stats(match_ids: list[str]):
    """Busca todas las estadísticas de progresión en paralelo."""
    stats_dict = {}
    unique_ids = [mid for mid in set(match_ids) if mid and mid.isdigit()]
    with ThreadPoolExecutor(max_workers=len(unique_ids) or 1) as executor:
        results = executor.map(fetch_single_stat, unique_ids)
        for match_id, df in results:
            stats_dict[match_id] = df
    return stats_dict

@st.cache_data(ttl=3600)
def get_main_match_odds_api(match_id):
    odds_info = {"ah_home_cuota": "N/A", "ah_linea_raw": "N/A", "ah_away_cuota": "N/A", "goals_over_cuota": "N/A", "goals_linea_raw": "N/A", "goals_under_cuota": "N/A"}
    try:
        session = get_requests_session_of()
        response = session.get(API_ODDS_URL.format(match_id), timeout=5)
        data = response.json()
        
        if (bet365_hda := next((c for c in data.get('hda', []) if c['cId'] == 8), None)) and bet365_hda.get('early'):
            odds_info.update(ah_home_cuota=str(bet365_hda['early'][0]), ah_linea_raw=str(bet365_hda['early'][1]), ah_away_cuota=str(bet365_hda['early'][2]))
        if (bet365_ou := next((c for c in data.get('ou', []) if c['cId'] == 8), None)) and bet365_ou.get('early'):
            odds_info.update(goals_linea_raw=str(bet365_ou['early'][0]), goals_over_cuota=str(bet365_ou['early'][1]), goals_under_cuota=str(bet365_ou['early'][2]))
    except (requests.RequestException, ValueError, KeyError): pass
    return odds_info

def get_team_info_from_script(soup):
    script_tag = soup.find("script", string=re.compile(r"var _matchInfo ="))
    if not script_tag: return (None,) * 6
    content = script_tag.string
    find = lambda pattern: (m.group(1).replace("\\'", "'") if (m := re.search(pattern, content)) else None)
    return find(r"hId:\s*parseInt\('(\d+)'\)"), find(r"gId:\s*parseInt\('(\d+)'\)"), \
           find(r"sclassId:\s*parseInt\('(\d+)'\)"), find(r"hName:\s*'([^']*)'"), \
           find(r"gName:\s*'([^']*)'"), find(r"lName:\s*'([^']*)'")

def extract_last_match_from_soup(soup, table_id, main_team_name, league_id, filter_type):
    if not (table := soup.find("table", id=table_id)): return None
    for row in table.find_all("tr", id=re.compile(rf"tr{table_id[-1]}_\d+")):
        if league_id and row.get("name") != str(league_id): continue
        if len(tds := row.find_all("td")) < 12 or not (home_el := tds[2].find("a")) or not (away_el := tds[4].find("a")): continue
        home_name, away_name = home_el.text.strip(), away_el.text.strip()
        is_team_home = main_team_name.lower() == home_name.lower()
        if (filter_type == 'home' and not is_team_home) or (filter_type == 'away' and main_team_name.lower() != away_name.lower()): continue
        if not is_team_home and not (main_team_name.lower() == away_name.lower()): continue
        
        onclick = (away_el if is_team_home else home_el).get("onclick", "")
        return {"date": tds[1].text.strip(), "home_team": home_name, "away_team": away_name,
                "score": (s.text.strip() if (s := tds[3].find("span", class_=re.compile(r"fscore_"))) else "N/A"),
                "handicap_line_raw": (tds[11].get("data-o", tds[11].text.strip()) or "N/A").strip(),
                "match_id": row.get('index'), "opponent_name": (away_el if is_team_home else home_el).text.strip(),
                "opponent_id": m.group(1) if (m := re.search(r"team\((\d+)\)", onclick)) else None}
    return None

def extract_standings_data(h2h_soup, target_team_name):
    data = {"name": target_team_name, "ranking": "N/A", "total_v": "N/A", "total_e": "N/A", "total_d": "N/A", "total_gf": "N/A", "total_gc": "N/A", "specific_v": "N/A", "specific_e": "N/A", "specific_d": "N/A", "specific_gf": "N/A", "specific_gc": "N/A"}
    if not h2h_soup or not target_team_name or not (standings_section := h2h_soup.find("div", id="porletP4")): return data
    
    home_div = standings_section.find("div", class_="home-div")
    guest_div = standings_section.find("div", class_="guest-div")
    
    team_table_soup, is_home = (home_div.find("table"), True) if home_div and target_team_name.lower() in home_div.get_text(strip=True).lower() else ((guest_div.find("table"), False) if guest_div and target_team_name.lower() in guest_div.get_text(strip=True).lower() else (None, False))

    if not team_table_soup: return data
    
    if (header_link := team_table_soup.find("tr", class_=re.compile(r"team-"))):
        if (rank_match := re.search(r"\[(?:[^\]]+-)?(\d+)\]", header_link.get_text(strip=True))): data["ranking"] = rank_match.group(1)
            
    for row in team_table_soup.find_all("tr", align="center"):
        if (th := row.find("th")) and "FT" not in th.get_text(strip=True): continue
        if len(cells := row.find_all("td")) < 7: continue
        row_type = cells[0].get_text(strip=True)
        stats = [c.get_text(strip=True) or "N/A" for c in cells[1:7]]
        v, e, d, gf, gc = stats[1], stats[2], stats[3], stats[4], stats[5]
        if row_type == "Total": data.update(total_v=v, total_e=e, total_d=d, total_gf=gf, total_gc=gc)
        elif (row_type == "Home" and is_home) or (row_type == "Away" and not is_home): data.update(specific_v=v, specific_e=e, specific_d=d, specific_gf=gf, specific_gc=gc)
    return data

def extract_h2h_data(soup, home_name, away_name, league_id):
    h2h_table = soup.find("table", id="table_v3")
    if not h2h_table: return ('-', '?:?', None), ('-', '?:?', None)
    
    h2h_list = [row for r in h2h_table.find_all("tr", id=re.compile(r"tr3_\d+")) if (row := get_match_details_from_row_of(r, 'fscore_3', 'h2h')) and (not league_id or row.get('league_id_hist') == str(league_id))]
    if not h2h_list: return ('-', '?:?', None), ('-', '?:?', None)
    
    last_h2h = h2h_list[0]
    h2h_general = (last_h2h['ahLine'], last_h2h['score'], last_h2h['matchIndex'])
    
    specific_match = next((m for m in h2h_list if m['home'].lower() == home_name.lower() and m['away'].lower() == away_name.lower()), None)
    h2h_specific = (specific_match['ahLine'], specific_match['score'], specific_match['matchIndex']) if specific_match else ('-', '?:?', None)
    
    return h2h_specific, h2h_general

# --- STREAMLIT UI COMPONENTS ---

def render_progression_stats(title, match_id, home_name, away_name, all_stats_data):
    """Muestra estadísticas de progresión desde el diccionario pre-cargado."""
    if not match_id: return
    stats_df = all_stats_data.get(match_id)
    
    if stats_df is None or stats_df.empty:
        st.caption(f"Estadísticas de progresión no disponibles para: {title}")
        return

    st.markdown(f"###### 👁️ Est. Progresión: *{title}*")
    for stat_key_en, stat_name_es in {"Shots": "Disparos", "Shots on Goal": "Disparos a P.", "Attacks": "Ataques", "Dangerous Attacks": "Ataques Pelig."}.items():
        if stat_key_en in stats_df.index:
            home_val, away_val = stats_df.loc[stat_key_en, 'Casa'], stats_df.loc[stat_key_en, 'Fuera']
            home_color, away_color = ("green", "red") if int(home_val or 0) > int(away_val or 0) else (("red", "green") if int(away_val or 0) > int(home_val or 0) else ("grey", "grey"))
            st.markdown(f"<div style='display: flex; justify-content: space-between; align-items: center;'>"
                        f"<strong style='color:{home_color}'>{home_val}</strong>"
                        f"<span style='text-align: center; font-size: 0.9em;'>{stat_name_es}</span>"
                        f"<strong style='color:{away_color}; text-align: right;'>{away_val}</strong>"
                        "</div>", unsafe_allow_html=True)
    st.markdown("<hr style='margin: 5px 0;'>", unsafe_allow_html=True)

def display_match_card(title, match_data, home_name_main, all_stats_data):
    """Muestra una tarjeta de partido unificada."""
    st.markdown(f"<h4 style='font-size: 1.1em; color: #333;'>{title}</h4>", unsafe_allow_html=True)
    if match_data:
        res = match_data
        st.markdown(f"🆚 <span style='color: #007bff;'>{res['home_team']}</span> <b style='color: #28a745;'>{res['score'].replace('-',':')}</b> <span style='color: #fd7e14;'>{res['away_team']}</span>", unsafe_allow_html=True)
        st.markdown(f"**AH:** <span style='color: #6f42c1; font-weight: bold;'>{format_ah_as_decimal_string_of(res.get('handicap_line_raw','-'))}</span>", unsafe_allow_html=True)
        render_progression_stats(title, res.get('match_id'), res.get('home_team'), res.get('away_team'), all_stats_data)
    else:
        st.info("No se encontró partido.")

# --- STREAMLIT APP UI PRINCIPAL ---
def display_other_feature_ui():
    st.markdown("""
    <style>
        .main-title { font-size: 2.2em; font-weight: bold; color: #1E90FF; text-align: center; }
        .sub-title { font-size: 1.6em; text-align: center; margin-bottom: 15px; }
        div[data-testid="stExpander"] div[role="button"] p {font-size: 1.4em; font-weight: bold; color: #4682B4;}
    </style>
    """, unsafe_allow_html=True)

    st.sidebar.image("https://raw.githubusercontent.com/streamlit/docs/main/public/images/brand/streamlit-logo-secondary-colormark-darktext.svg", width=200)
    st.sidebar.title("⚙️ Configuración del Partido")
    main_match_id_input = st.sidebar.text_input("🆔 ID Partido Principal:", value="2696131", key="match_id_input")
    analizar_button = st.sidebar.button("🚀 Analizar Partido", type="primary", use_container_width=True)

    if not analizar_button:
        st.info("✨ ¡Bienvenido! Ingresa un ID de partido y haz clic en 'Analizar Partido'.")
        return

    try: match_id = int("".join(filter(str.isdigit, main_match_id_input)))
    except (ValueError, TypeError): st.error("⚠️ ID de partido no válido."); return

    start_time = time.time()
    with st.spinner("🔄 Procesando datos... ¡Esto será rápido!"):
        soup = fetch_soup_requests_of(f"/match/h2h-{match_id}")
        if not soup: st.error(f"❌ No se pudo obtener la página para ID {match_id}."); return
        
        home_id, away_id, league_id, home_name, away_name, league_name = get_team_info_from_script(soup)
        
        last_home_match = extract_last_match_from_soup(soup, "table_v1", home_name, league_id, 'home')
        last_away_match = extract_last_match_from_soup(soup, "table_v2", away_name, league_id, 'away')
        last_overall_home = extract_last_match_from_soup(soup, "table_v1", home_name, league_id, 'overall')
        last_overall_away = extract_last_match_from_soup(soup, "table_v2", away_name, league_id, 'overall')
        h2h_specific, h2h_general = extract_h2h_data(soup, home_name, away_name, league_id)

        required_ids = {str(match_id)}
        for match in [last_home_match, last_away_match, last_overall_home, last_overall_away]:
            if match and match.get('match_id'): required_ids.add(match['match_id'])
        if h2h_specific[2]: required_ids.add(h2h_specific[2])
        if h2h_general[2]: required_ids.add(h2h_general[2])
        
        all_stats_data = batch_fetch_progression_stats(list(required_ids))

    st.markdown(f"<p class='main-title'>📊 Análisis Rápido de Partido ⚡</p>", unsafe_allow_html=True)
    st.markdown(f"<p class='sub-title'><span class='home-color'>{home_name}</span> vs <span class='away-color'>{away_name}</span></p>", unsafe_allow_html=True)
    st.caption(f"🏆 **Liga:** {league_name or PLACEHOLDER_NODATA} | 🆔 **Partido ID:** {match_id}")
    st.divider()

    with st.expander("📈 Clasificación y Cuotas"):
        odds_data = get_main_match_odds_api(match_id)
        final_score, _ = extract_final_score_of(soup)
        c1, c2, c3 = st.columns(3)
        with c1:
            home_standings = extract_standings_data(soup, home_name)
            st.markdown(f"**<span class='home-color'>{home_name}</span> (Rank: {home_standings['ranking']})**", unsafe_allow_html=True)
            st.text(f"  V-E-D: {home_standings['total_v']}-{home_standings['total_e']}-{home_standings['total_d']}")
        with c2:
            away_standings = extract_standings_data(soup, away_name)
            st.markdown(f"**<span class='away-color'>{away_name}</span> (Rank: {away_standings['ranking']})**", unsafe_allow_html=True)
            st.text(f"  V-E-D: {away_standings['total_v']}-{away_standings['total_e']}-{away_standings['total_d']}")
        with c3:
            st.metric("🏁 Marcador Final", final_score if final_score != "?:?" else "N/A", label_visibility="collapsed")
            st.metric("⚖️ AH Inicial", format_ah_as_decimal_string_of(odds_data['ah_linea_raw']), f"{odds_data.get('ah_home_cuota','-')}/{odds_data.get('ah_away_cuota','-')}", "inverse")
        render_progression_stats("Partido Principal", str(match_id), home_name, away_name, all_stats_data)
        
    with st.expander("⚡ Rendimiento Reciente (Local/Visitante)"):
        c1, c2 = st.columns(2)
        with c1: display_match_card(f"Último {home_name} (Casa)", last_home_match, home_name, all_stats_data)
        with c2: display_match_card(f"Último {away_name} (Fuera)", last_away_match, home_name, all_stats_data)
            
    with st.expander("⚡ Rendimiento Último Partido (General)"):
        c1, c2 = st.columns(2)
        with c1: display_match_card(f"Último General {home_name}", last_overall_home, home_name, all_stats_data)
        with c2: display_match_card(f"Último General {away_name}", last_overall_away, home_name, all_stats_data)
    
    with st.expander("🔰 H2H Directos (Local vs Visitante)"):
        c1, c2 = st.columns(2)
        with c1:
            st.metric("Res H2H (Local en Casa)", h2h_specific[1].replace("*",":") if h2h_specific[1] != '?:?' else "N/A")
            st.markdown(f"**AH:** <span style='color: #6f42c1; font-weight: bold;'>{format_ah_as_decimal_string_of(h2h_specific[0])}</span>", unsafe_allow_html=True)
            render_progression_stats(f"H2H {home_name} (C)", h2h_specific[2], home_name, away_name, all_stats_data)
        with c2:
            st.metric("Res H2H (Último General)", h2h_general[1].replace("*",":") if h2h_general[1] != '?:?' else "N/A")
            st.markdown(f"**AH:** <span style='color: #6f42c1; font-weight: bold;'>{format_ah_as_decimal_string_of(h2h_general[0])}</span>", unsafe_allow_html=True)
            render_progression_stats("H2H General", h2h_general[2], home_name, away_name, all_stats_data)

    end_time = time.time()
    st.sidebar.success(f"🎉 Análisis completado en {end_time - start_time:.2f} segundos.")

if __name__ == '__main__':
    st.set_page_config(layout="wide", page_title="Análisis Rápido de Partidos", initial_sidebar_state="expanded")
    display_other_feature_ui()
