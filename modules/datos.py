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

# --- FUNCIONES HELPER PARA PARSEO ---
def _parse_ah_to_number(ah_line_str: str):
    if not isinstance(ah_line_str, str): return None
    s = ah_line_str.strip().replace(' ', '')
    if not s or s in ['-', '?']: return None
    try:
        return sum(map(float, s.split('/'))) / len(s.split('/'))
    except (ValueError, TypeError):
        return None

def _format_ah_as_string(ah_line_str: str):
    num = _parse_ah_to_number(ah_line_str)
    if num is None: return PLACEHOLDER_NODATA
    if num == 0.0: return "0"
    return f"{num:+.2f}".replace(".25", ".25").replace(".75", ".75").replace(".50", ".5").replace(".00", "")

# --- SESIÓN Y FETCHING ---
@st.cache_resource
def get_requests_session():
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(pool_connections=100, pool_maxsize=100, max_retries=retries)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
    return session

@st.cache_data(ttl=3600)
def fetch_soup(path):
    try:
        resp = get_requests_session().get(f"{BASE_URL_OF}{path}", timeout=10)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException:
        return None

# --- PARSEO GENÉRICO DE FILAS (Función corregida) ---
def _parse_match_row(row_element):
    try:
        cells = row_element.find_all(['td', 'th'])
        home_tag, away_tag = cells[2].find('a'), cells[4].find('a')
        home = home_tag.text.strip() if home_tag else "N/A"
        away = away_tag.text.strip() if away_tag else "N/A"
        score_span = cells[3].find('span', class_=re.compile(r"fscore_"))
        score_raw = score_match.group(1) if score_span and (score_match := re.search(r'(\d+-\d+)', score_span.text)) else '?-?'
        ah_cell_idx = 13 if cells[0].name == 'th' else 11
        ah_line_raw = cells[ah_cell_idx].text.strip()
        return {'home': home, 'away': away, 'score': score_raw.replace('-', ':'),
                'ahLine_raw': ah_line_raw, 'matchIndex': row_element.get('index')}
    except (IndexError, AttributeError):
        return None

# --- EXTRACCIÓN CONCURRENTE ---
def _fetch_single_stat(match_id, session):
    if not match_id or not match_id.isdigit(): return match_id, None
    try:
        response = session.get(API_STATS_URL.format(match_id), timeout=8)
        soup = BeautifulSoup(response.text, 'lxml')
        if not (tech_div := soup.find('div', id='teamTechDiv_detail')): return match_id, None
        stats = {li.find('span', class_='stat-title').get_text(strip=True): [v.get_text(strip=True) for v in li.find_all('span', class_='stat-c')] for li in tech_div.find_all('li') if li.find('span', class_='stat-title')}
        return match_id, pd.DataFrame([{"Casa": v[0], "Fuera": v[1]} for k, v in stats.items() if len(v)==2], index=stats.keys())
    except Exception: return match_id, None

@st.cache_data(ttl=7200)
def batch_fetch_progression_stats(match_ids):
    session = get_requests_session()
    unique_ids = list(filter(None, set(match_ids)))
    with ThreadPoolExecutor(max_workers=len(unique_ids) or 1) as executor:
        return {mid: df for mid, df in executor.map(lambda mid: _fetch_single_stat(mid, session), unique_ids)}

# --- EXTRACCIÓN DE DATOS PRINCIPALES ---
@st.cache_data(ttl=3600)
def get_main_match_data(match_id):
    soup = fetch_soup(f"/match/h2h-{match_id}")
    if not soup: return None
    
    home_id, away_id, league_id, home_name, away_name, league_name = (None,)*6
    if (script_tag := soup.find("script", string=re.compile(r"var _matchInfo ="))):
        content = script_tag.string
        find = lambda p: (m.group(1).replace("\\'","'") if (m:=re.search(p,content)) else None)
        home_id, away_id, league_id, home_name, away_name, league_name = find(r"hId:\s*'(\d+)'"), find(r"gId:\s*'(\d+)'"), find(r"sclassId:\s*'(\d+)'"), find(r"hName:\s*'([^']*)'"), find(r"gName:\s*'([^']*)'"), find(r"lName:\s*'([^']*)'")

    odds = {"ah_line":"N/A","ah_home":"N/A","ah_away":"N/A","ou_line":"N/A","ou_over":"N/A","ou_under":"N/A"}
    try:
        data = get_requests_session().get(API_ODDS_URL.format(match_id), timeout=5).json()
        if (hda := next((c for c in data.get('hda',[]) if c['cId']==8),None)) and hda.get('early'):
            odds.update(ah_line=str(hda['early'][1]), ah_home=str(hda['early'][0]), ah_away=str(hda['early'][2]))
        if (ou := next((c for c in data.get('ou',[]) if c['cId']==8),None)) and ou.get('early'):
            odds.update(ou_line=str(ou['early'][0]), ou_over=str(ou['early'][1]), ou_under=str(ou['early'][2]))
    except Exception: pass

    final_score = "N/A"
    if (score_divs := soup.select('#mScore .end .score')) and len(score_divs) == 2:
        final_score = f"{score_divs[0].text.strip()}:{score_divs[1].text.strip()}"

    def extract_from_table(table_id, team_name, filt_type):
        if not (table := soup.find("table", id=table_id)): return None
        for row in table.find_all("tr", id=re.compile(rf"tr{table_id[-1]}_\d+")):
            details = _parse_match_row(row)
            if not details or (league_id and details.get('league_id_hist') != str(league_id)): continue
            is_home = team_name.lower() == details['home'].lower()
            if (filt_type == 'home' and not is_home) or (filt_type == 'away' and team_name.lower() != details['away'].lower()) or not (is_home or team_name.lower() == details['away'].lower()): continue
            details['opponent'] = details['away'] if is_home else details['home']
            return details
        return None
        
    last_home_match = extract_from_table("table_v1", home_name, 'home')
    last_away_match = extract_from_table("table_v2", away_name, 'away')
    
    return {
        "soup": soup, "home_name": home_name, "away_name": away_name, "league_name": league_name, "odds": odds, "final_score": final_score,
        "last_home_match": last_home_match,
        "last_away_match": last_away_match,
        "last_overall_home": extract_from_table("table_v1", home_name, 'overall'),
        "last_overall_away": extract_from_table("table_v2", away_name, 'overall'),
        "h2h_data": extract_h2h_data(soup, home_name, away_name, league_id)
    }

def extract_h2h_data(soup, home_name, away_name, league_id):
    if not (h2h_table := soup.find("table", id="table_v3")): return ('-', '?:?', None), ('-', '?:?', None)
    h2h_list = [_parse_match_row(r) for r in h2h_table.find_all("tr", id=re.compile(r"tr3_\d+")) if not league_id or r.get('name') == str(league_id)]
    h2h_list = list(filter(None, h2h_list))
    if not h2h_list: return ('-', '?:?', None), ('-', '?:?', None)
    specific = next((m for m in h2h_list if m['home'].lower()==home_name.lower() and m['away'].lower()==away_name.lower()), None)
    return (specific['ahLine_raw'], specific['score'], specific['matchIndex']) if specific else ('-', '?:?', None), \
           (h2h_list[0]['ahLine_raw'], h2h_list[0]['score'], h2h_list[0]['matchIndex'])

# --- UI COMPONENTS ---
def render_progression_stats(title, match_id, stats_data):
    if not match_id or not (df := stats_data.get(match_id)): return
    st.markdown(f"###### 👁️ Est. Progresión: *{title}*")
    for stat, name in {"Shots":"Disparos","Shots on Goal":"Disparos P.","Attacks":"Ataques","Dangerous Attacks":"Ataques Pelig."}.items():
        if stat in df.index:
            home_v, away_v = df.loc[stat, ['Casa', 'Fuera']]
            h_c, a_c = ("green","red") if int(home_v or 0)>int(away_v or 0) else (("red","green") if int(away_v or 0)>int(home_v or 0) else ("grey","grey"))
            st.markdown(f"<div style='display:flex;justify-content:space-between;align-items:center;font-size:0.9em;'><strong style='color:{h_c}'>{home_v}</strong><span>{name}</span><strong style='color:{a_c};'>{away_v}</strong></div>", unsafe_allow_html=True)

def display_match_card(title, match_data, stats_data):
    st.markdown(f"<h5 style='font-size:1.1em;color:#333;margin-bottom:0px;'>{title}</h5>", unsafe_allow_html=True)
    if match_data:
        st.markdown(f"vs **{match_data['opponent']}** <span style='float:right;color:#28a745;font-weight:bold;'>{match_data['score']}</span>", unsafe_allow_html=True)
        st.markdown(f"**AH:** <b style='color:#6f42c1;'>{_format_ah_as_string(match_data.get('ahLine_raw','-'))}</b>", unsafe_allow_html=True)
        render_progression_stats(title, match_data.get('matchIndex'), stats_data)
    else: st.info("No se encontró partido.")

# --- APP PRINCIPAL ---
def display_other_feature_ui():
    st.markdown("<style>.main-title{font-size:2.2em;font-weight:bold;color:#1E90FF;text-align:center}.sub-title{font-size:1.6em;text-align:center;margin-bottom:15px}div[data-testid='stExpander'] div[role='button'] p{font-size:1.4em;font-weight:bold;color:#4682B4}</style>", unsafe_allow_html=True)
    st.sidebar.image("https://raw.githubusercontent.com/streamlit/docs/main/public/images/brand/streamlit-logo-secondary-colormark-darktext.svg", width=200)
    st.sidebar.title("⚙️ Configuración")
    match_id_input = st.sidebar.text_input("🆔 ID Partido Principal:", value="2696131", key="match_id_input_main")
    if not st.sidebar.button("🚀 Analizar Partido", type="primary", use_container_width=True):
        st.info("✨ ¡Bienvenido! Ingresa un ID de partido y haz clic en 'Analizar Partido'.")
        return
    
    try: match_id = int("".join(filter(str.isdigit, match_id_input)))
    except (ValueError, TypeError): st.error("⚠️ ID de partido no válido."); return
    
    start_time = time.time()
    with st.spinner("🔄 Procesando datos... ¡Esto será rápido!"):
        data = get_main_match_data(match_id)
        if not data: st.error(f"❌ No se pudo obtener datos para ID {match_id}."); return
        ids_to_fetch = {str(match_id)} | {d.get('matchIndex') for d in data.values() if isinstance(d, dict)} | {data['h2h_data'][0][2], data['h2h_data'][1][2]}
        stats_data = batch_fetch_progression_stats(list(ids_to_fetch))

    st.markdown(f"<p class='main-title'>📊 Análisis Rápido de Partido ⚡</p>", unsafe_allow_html=True)
    st.markdown(f"<p class='sub-title'><span style='color:#007bff;'>{data['home_name']}</span> vs <span style='color:#fd7e14;'>{data['away_name']}</span></p>", unsafe_allow_html=True)
    st.caption(f"🏆 **Liga:** {data['league_name'] or 'N/A'} | 🆔 **Partido:** {match_id}")
    st.divider()

    with st.expander("📈 Resumen y Cuotas"):
        c1, c2, c3 = st.columns(3)
        c1.metric("🏁 Marcador Final", data['final_score'] if data['final_score'] != "N/A" else "N/A")
        c2.metric("⚖️ AH Inicial", _format_ah_as_string(data['odds']['ah_line']), f"{data['odds']['ah_home']}/{data['odds']['ah_away']}")
        c3.metric("🥅 Goles Inicial", _format_ah_as_string(data['odds']['ou_line']), f"{data['odds']['ou_over']}/{data['odds']['ou_under']}")
        render_progression_stats("Partido Principal", str(match_id), stats_data)

    with st.expander("⚡ Rendimiento Reciente (Local/Visitante)"):
        c1, c2 = st.columns(2)
        with c1: display_match_card(f"Último {data['home_name']} (Casa)", data["last_home_match"], stats_data)
        with c2: display_match_card(f"Último {data['away_name']} (Fuera)", data["last_away_match"], stats_data)

    with st.expander("⚡ Rendimiento Último Partido (General) y Comparativa Cruzada"):
        c1, c2, c3 = st.columns(3)
        with c1: display_match_card(f"Último General {data['home_name']}", data["last_overall_home"], stats_data)
        with c2: display_match_card(f"Último General {data['away_name']}", data["last_overall_away"], stats_data)
        with c3:
            comp_match = None
            if data["last_overall_away"]:
                comp_match = _parse_match_row(next((r for r in data['soup'].find("table",id="table_v1").find_all("tr") if data["last_overall_away"]['opponent'] in r.text),None))
            display_match_card(f"{data['home_name']} vs Últ. Rival de {data['away_name']}", comp_match, stats_data)

    with st.expander("🔰 H2H Directos"):
        c1, c2 = st.columns(2)
        with c1:
            h2h_s = data['h2h_data'][0]
            st.metric("Res H2H (Local en Casa)", h2h_s[1] if h2h_s[1] != '?:?' else "N/A")
            st.markdown(f"**AH:** <b style='color:#6f42c1;'>{_format_ah_as_string(h2h_s[0])}</b>", unsafe_allow_html=True)
            render_progression_stats(f"H2H {data['home_name']} (C)", h2h_s[2], stats_data)
        with c2:
            h2h_g = data['h2h_data'][1]
            st.metric("Res H2H (Último General)", h2h_g[1] if h2h_g[1] != '?:?' else "N/A")
            st.markdown(f"**AH:** <b style='color:#6f42c1;'>{_format_ah_as_string(h2h_g[0])}</b>", unsafe_allow_html=True)
            render_progression_stats("H2H General", h2h_g[2], stats_data)

    st.sidebar.success(f"🎉 Análisis completado en {time.time() - start_time:.2f} segundos.")

if __name__ == '__main__':
    st.set_page_config(layout="wide", page_title="Análisis Rápido de Partidos", initial_sidebar_state="expanded")
    display_other_feature_ui()
