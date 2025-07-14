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

# --- FUNCIONES HELPER PARA PARSEO Y FORMATEO ---
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
        return PLACEHOLDER_NODATA
    if numeric_value == 0.0: return "0"
    sign = "" if numeric_value > 0 else "-"
    abs_num = abs(numeric_value)
    if abs_num % 1 in [0.25, 0.75]:
        return f"{sign}{abs_num:.2f}"
    return f"{sign}{abs_num:.2f}".replace(".50", ".5").replace(".00", "")

# --- SESIÓN Y FETCHING ---
@st.cache_resource
def get_requests_session_of():
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(pool_connections=100, pool_maxsize=100, max_retries=retries)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36"})
    return session

@st.cache_data(ttl=3600)
def fetch_soup_requests_of(path):
    try:
        resp = get_requests_session_of().get(f"{BASE_URL_OF}{path}", timeout=10)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException:
        return None

# --- PARSEO GENÉRICO DE FILAS ---
def _parse_match_row(row_element):
    """Helper interno para parsear una fila de partido. Soluciona el NameError."""
    try:
        cells = row_element.find_all(['td', 'th'])
        home_tag, away_tag = cells[2].find('a'), cells[4].find('a')
        home = home_tag.text.strip() if home_tag else "N/A"
        away = away_tag.text.strip() if away_tag else "N/A"

        score_span = cells[3].find('span', class_=re.compile(r"fscore_"))
        score_raw = score_match.group(1) if score_span and (score_match := re.search(r'(\d+-\d+)', score_span.text)) else '?-?'
        
        ah_line_raw = (cells[13] if cells[0].name == 'th' else cells[11]).text.strip()
        
        if not all([home != "N/A", away != "N/A", row_element.get('index')]): return None
        
        return {'home': home, 'away': away, 'score': score_raw.replace('-', ':'),
                'ahLine_raw': ah_line_raw, 'matchIndex': row_element.get('index'),
                'league_id_hist': row_element.get('name')}
    except (IndexError, AttributeError):
        return None

# --- FUNCIONES DE EXTRACCIÓN CONCURRENTES Y OPTIMIZADAS ---
def fetch_single_stat(match_id, session):
    if not match_id or not match_id.isdigit(): return match_id, None
    try:
        response = session.get(API_STATS_URL.format(match_id), timeout=8)
        soup = BeautifulSoup(response.text, 'lxml')
        if not (tech_div := soup.find('div', id='teamTechDiv_detail')): return match_id, None
        stats = {li.find('span', class_='stat-title').get_text(strip=True): [v.get_text(strip=True) for v in li.find_all('span', class_='stat-c')] for li in tech_div.find_all('li') if li.find('span', class_='stat-title')}
        return match_id, pd.DataFrame([{"Estadistica_EN": k, "Casa": v[0], "Fuera": v[1]} for k, v in stats.items() if len(v) == 2]).set_index("Estadistica_EN")
    except Exception: return match_id, None

@st.cache_data(ttl=7200)
def batch_fetch_progression_stats(match_ids: list[str]):
    stats_dict = {}
    session = get_requests_session_of()
    unique_ids = list(filter(None, set(match_ids)))
    with ThreadPoolExecutor(max_workers=len(unique_ids) or 1) as executor:
        args = [(uid, session) for uid in unique_ids]
        results = executor.map(lambda p: fetch_single_stat(*p), args)
        for match_id, df in results: stats_dict[match_id] = df
    return stats_dict

@st.cache_data(ttl=3600)
def get_main_match_odds_api(match_id):
    odds = {"ah_home": "N/A", "ah_line": "N/A", "ah_away": "N/A", "ou_line": "N/A", "ou_over": "N/A", "ou_under": "N/A"}
    try:
        data = get_requests_session_of().get(API_ODDS_URL.format(match_id), timeout=5).json()
        if (hda := next((c for c in data.get('hda',[]) if c['cId']==8),None)) and hda.get('early'):
            odds.update(ah_home=str(hda['early'][0]), ah_line=str(hda['early'][1]), ah_away=str(hda['early'][2]))
        if (ou := next((c for c in data.get('ou',[]) if c['cId']==8),None)) and ou.get('early'):
            odds.update(ou_line=str(ou['early'][0]), ou_over=str(ou['early'][1]), ou_under=str(ou['early'][2]))
    except Exception: pass
    return odds

def get_team_info_from_script(soup):
    if not (script_tag := soup.find("script", string=re.compile(r"var _matchInfo ="))): return (None,) * 6
    content, find = script_tag.string, lambda p: (m.group(1).replace("\\'","'") if (m:=re.search(p,content)) else None)
    return find(r"hId:\s*'(\d+)'"), find(r"gId:\s*'(\d+)'"), find(r"sclassId:\s*'(\d+)'"), find(r"hName:\s*'([^']*)'"), find(r"gName:\s*'([^']*)'"), find(r"lName:\s*'([^']*)'")

def extract_last_match_from_soup(soup, table_id, main_team_name, league_id, filter_type):
    if not (table := soup.find("table", id=table_id)): return None
    for row in table.find_all("tr", id=re.compile(rf"tr{table_id[-1]}_\d+")):
        details = _parse_match_row(row)
        if not details or (league_id and details.get('league_id_hist') != str(league_id)): continue
        
        is_team_home = main_team_name.lower() == details['home'].lower()
        is_team_away = main_team_name.lower() == details['away'].lower()
        
        if (filter_type == 'home' and not is_team_home) or (filter_type == 'away' and not is_team_away) or not (is_team_home or is_team_away): continue
        
        cells = row.find_all('td')
        opponent_el = cells[4].find('a') if is_team_home else cells[2].find('a')
        if opponent_el:
            details['opponent_name'] = opponent_el.text.strip()
            details['opponent_id'] = m.group(1) if (m := re.search(r"team\((\d+)\)", opponent_el.get("onclick", ""))) else None
        return details
    return None

def extract_h2h_data(soup, home_name, away_name, league_id):
    if not (h2h_table := soup.find("table", id="table_v3")): return ('-', '?:?', None), ('-', '?:?', None)
    h2h_list = [_parse_match_row(r) for r in h2h_table.find_all("tr", id=re.compile(r"tr3_\d+"))]
    h2h_list = [m for m in h2h_list if m and (not league_id or m.get('league_id_hist') == str(league_id))]
    if not h2h_list: return ('-', '?:?', None), ('-', '?:?', None)
    
    last_h2h = h2h_list[0]
    h2h_general = (last_h2h['ahLine_raw'], last_h2h['score'], last_h2h['matchIndex'])
    
    specific_match = next((m for m in h2h_list if m['home'].lower()==home_name.lower() and m['away'].lower()==away_name.lower()), None)
    h2h_specific = (specific_match['ahLine_raw'], specific_match['score'], specific_match['matchIndex']) if specific_match else ('-', '?:?', None)
    
    return h2h_specific, h2h_general

# --- STREAMLIT UI COMPONENTS ---
def render_progression_stats(title, match_id, all_stats_data):
    if not match_id or not (stats_df := all_stats_data.get(match_id)): return
    st.markdown(f"###### 👁️ Est. Progresión: *{title}*")
    for stat_key, stat_name in {"Shots":"Disparos","Shots on Goal":"Disparos P.","Attacks":"Ataques","Dangerous Attacks":"Ataques Pelig."}.items():
        if stat_key in stats_df.index:
            home_v, away_v = stats_df.loc[stat_key, ['Casa', 'Fuera']]
            h_c, a_c = ("green","red") if int(home_v or 0)>int(away_v or 0) else (("red","green") if int(away_v or 0)>int(home_v or 0) else ("grey","grey"))
            st.markdown(f"<div style='display:flex;justify-content:space-between;align-items:center;font-size:0.9em;'><strong style='color:{h_c}'>{home_v}</strong><span>{stat_name}</span><strong style='color:{a_c};'>{away_v}</strong></div>", unsafe_allow_html=True)
    st.markdown("<hr style='margin:5px 0;'>", unsafe_allow_html=True)

def display_match_card(title, match_data, all_stats_data):
    st.markdown(f"<h4 style='font-size:1.1em;color:#333;'>{title}</h4>", unsafe_allow_html=True)
    if match_data:
        st.markdown(f"🆚 <span style='color:#007bff;'>{match_data['home_team']}</span> <b style='color:#28a745;'>{match_data['score']}</b> <span style='color:#fd7e14;'>{match_data['away_team']}</span>", unsafe_allow_html=True)
        st.markdown(f"**AH:** <b style='color:#6f42c1;'>{format_ah_as_decimal_string_of(match_data.get('ahLine_raw','-'))}</b>", unsafe_allow_html=True)
        render_progression_stats(title, match_data.get('match_id'), all_stats_data)
    else: st.info("No se encontró partido.")

# --- STREAMLIT APP UI PRINCIPAL ---
def display_other_feature_ui():
    st.markdown("<style>.main-title{font-size:2.2em;font-weight:bold;color:#1E90FF;text-align:center}.sub-title{font-size:1.6em;text-align:center;margin-bottom:15px}div[data-testid='stExpander'] div[role='button'] p{font-size:1.4em;font-weight:bold;color:#4682B4}</style>", unsafe_allow_html=True)
    st.sidebar.image("https://raw.githubusercontent.com/streamlit/docs/main/public/images/brand/streamlit-logo-secondary-colormark-darktext.svg", width=200)
    st.sidebar.title("⚙️ Configuración")
    match_id_input = st.sidebar.text_input("🆔 ID Partido Principal:", value="2696131", key="match_id_input_main")
    if not st.sidebar.button("🚀 Analizar Partido", type="primary", use_container_width=True, key="analizar_button"):
        st.info("✨ ¡Bienvenido! Ingresa un ID de partido y haz clic en 'Analizar Partido'.")
        return
    
    try: match_id = int("".join(filter(str.isdigit, match_id_input)))
    except (ValueError, TypeError): st.error("⚠️ ID de partido no válido."); return
    
    start_time = time.time()
    with st.spinner("🔄 Procesando datos... ¡Esto será rápido!"):
        soup = fetch_soup_requests_of(f"/match/h2h-{match_id}")
        if not soup: st.error(f"❌ No se pudo obtener datos para ID {match_id}."); return
        
        home_id, away_id, league_id, home_name, away_name, league_name = get_team_info_from_script(soup)
        
        data_pack = {
            "last_home": extract_last_match_from_soup(soup, "table_v1", home_name, league_id, 'home'),
            "last_away": extract_last_match_from_soup(soup, "table_v2", away_name, league_id, 'away'),
            "last_overall_home": extract_last_match_from_soup(soup, "table_v1", home_name, league_id, 'overall'),
            "last_overall_away": extract_last_match_from_soup(soup, "table_v2", away_name, league_id, 'overall'),
            "h2h_specific": extract_h2h_data(soup, home_name, away_name, league_id)[0],
            "h2h_general": extract_h2h_data(soup, home_name, away_name, league_id)[1]
        }
        
        ids_to_fetch = {str(match_id)} | {d.get('matchIndex') for d in data_pack.values() if isinstance(d, dict) and d.get('matchIndex')} | {data_pack['h2h_specific'][2], data_pack['h2h_general'][2]}
        all_stats_data = batch_fetch_progression_stats(list(ids_to_fetch))

    st.markdown(f"<p class='main-title'>📊 Análisis Rápido de Partido ⚡</p>", unsafe_allow_html=True)
    st.markdown(f"<p class='sub-title'><span style='color:#007bff;'>{home_name}</span> vs <span style='color:#fd7e14;'>{away_name}</span></p>", unsafe_allow_html=True)
    st.caption(f"🏆 **Liga:** {league_name or 'N/A'} | 🆔 **Partido:** {match_id}")
    st.divider()

    with st.expander("📈 Resumen del Partido y Cuotas"):
        odds = get_main_match_odds_api(match_id)
        final_score, _ = extract_final_score_of(soup)
        c1, c2, c3 = st.columns(3)
        c1.metric("🏁 Marcador Final", final_score if final_score != "?:?" else "N/A")
        c2.metric("⚖️ AH Inicial", format_ah_as_decimal_string_of(odds['ah_line']), f"{odds['ah_home']}/{odds['ah_away']}", "inverse")
        c3.metric("🥅 Goles Inicial", format_ah_as_decimal_string_of(odds['ou_line']), f"{odds['ou_over']}/{odds['ou_under']}", "inverse")
        render_progression_stats("Partido Principal", str(match_id), all_stats_data)

    with st.expander("⚡ Rendimiento Reciente (Local/Visitante)"):
        c1, c2 = st.columns(2)
        with c1: display_match_card(f"Último {home_name} (Casa)", data_pack["last_home"], all_stats_data)
        with c2: display_match_card(f"Último {away_name} (Fuera)", data_pack["last_away"], all_stats_data)
            
    with st.expander("⚡ Rendimiento Último Partido (General)"):
        c1, c2 = st.columns(2)
        with c1: display_match_card(f"Último General {home_name}", data_pack["last_overall_home"], all_stats_data)
        with c2: display_match_card(f"Último General {away_name}", data_pack["last_overall_away"], all_stats_data)
    
    with st.expander("🔰 H2H Directos"):
        c1, c2 = st.columns(2)
        with c1:
            h2h_s = data_pack["h2h_specific"]
            st.metric("Res H2H (Local en Casa)", h2h_s[1] if h2h_s[1] != '?:?' else "N/A")
            st.markdown(f"**AH:** <b style='color:#6f42c1;'>{format_ah_as_decimal_string_of(h2h_s[0])}</b>", unsafe_allow_html=True)
            render_progression_stats(f"H2H {home_name} (C)", h2h_s[2], all_stats_data)
        with c2:
            h2h_g = data_pack["h2h_general"]
            st.metric("Res H2H (Último General)", h2h_g[1] if h2h_g[1] != '?:?' else "N/A")
            st.markdown(f"**AH:** <b style='color:#6f42c1;'>{format_ah_as_decimal_string_of(h2h_g[0])}</b>", unsafe_allow_html=True)
            render_progression_stats("H2H General", h2h_g[2], all_stats_data)

    st.sidebar.success(f"🎉 Análisis completado en {time.time() - start_time:.2f} segundos.")

if __name__ == '__main__':
    st.set_page_config(layout="wide", page_title="Análisis Rápido de Partidos", initial_sidebar_state="expanded")
    display_other_feature_ui()
