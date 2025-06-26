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
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- CONFIGURACIÓN GLOBAL ---
BASE_URL_OF = "https://live18.nowgoal25.com"
PLACEHOLDER_NODATA = "*(No disponible)*"

# --- FUNCIONES HELPER PARA PARSEO Y FORMATEO (SIN CAMBIOS) ---
def parse_ah_to_number_of(ah_line_str: str):
    if not isinstance(ah_line_str, str): return None
    s = ah_line_str.strip().replace(' ', '')
    if not s or s in ['-', '?']: return None
    original_starts_with_minus = ah_line_str.strip().startswith('-')
    try:
        if '/' in s:
            parts = s.split('/')
            if len(parts) != 2: return None
            p1_str, p2_str = parts[0], parts[1]
            try: val1 = float(p1_str)
            except ValueError: return None
            try: val2 = float(p2_str)
            except ValueError: return None
            if val1 < 0 and not p2_str.startswith('-') and val2 > 0:
                 val2 = -abs(val2)
            elif original_starts_with_minus and val1 == 0.0 and \
                 (p1_str == "0" or p1_str == "-0") and \
                 not p2_str.startswith('-') and val2 > 0:
                val2 = -abs(val2)
            return (val1 + val2) / 2.0
        else:
            return float(s)
    except ValueError:
        return None

def format_ah_as_decimal_string_of(ah_line_str: str, for_sheets=False):
    if not isinstance(ah_line_str, str) or not ah_line_str.strip() or ah_line_str.strip() in ['-', '?']:
        return ah_line_str.strip() if isinstance(ah_line_str, str) and ah_line_str.strip() in ['-','?'] else '-'
    numeric_value = parse_ah_to_number_of(ah_line_str)
    if numeric_value is None:
        return ah_line_str.strip() if ah_line_str.strip() in ['-','?'] else '-'
    if numeric_value == 0.0: return "0"
    sign, abs_num = (-1, abs(numeric_value)) if numeric_value < 0 else (1, numeric_value)
    mod_val = abs_num % 1
    if mod_val in [0.0, 0.5]: abs_rounded = abs_num
    elif mod_val == 0.25: abs_rounded = math.floor(abs_num) + 0.25
    elif mod_val == 0.75: abs_rounded = math.floor(abs_num) + 0.75
    else: abs_rounded = math.floor(abs_num) + (0.5 if mod_val > 0.25 and mod_val < 0.75 else (0 if mod_val < 0.25 else 1))
    final_value_signed = sign * abs_rounded
    if final_value_signed == 0.0: return "0"
    return f"{final_value_signed:.0f}" if final_value_signed.is_integer() else f"{final_value_signed:.2f}".rstrip('0').rstrip('.')

def get_match_details_from_row_of(row_element, score_class_selector='score'):
    try:
        cells = row_element.find_all('td')
        if len(cells) < 12: return None
        home = cells[2].find('a').text.strip()
        away = cells[4].find('a').text.strip()
        score_raw = cells[3].find('span', class_=lambda x: x and score_class_selector in x).text.strip().split('(')[0].strip()
        score_fmt = score_raw.replace('-', ':') if '-' in score_raw else '?:?'
        ah_line_raw = cells[11].text.strip()
        return {'home': home, 'away': away, 'score': score_fmt, 'score_raw': score_raw,
                'ahLine': format_ah_as_decimal_string_of(ah_line_raw), 'ahLine_raw': ah_line_raw,
                'matchIndex': row_element.get('index'), 'league_id_hist': row_element.get('name')}
    except (AttributeError, IndexError): return None

# --- SESIÓN Y FETCHING (EFICIENTES Y CACHEADOS) ---
@st.cache_resource
def get_requests_session_of():
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter); session.mount("http://", adapter)
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"})
    return session

@st.cache_data(ttl=3600)
def fetch_soup_requests_of(path, **kwargs):
    url = f"{BASE_URL_OF}{path}"
    try:
        resp = get_requests_session_of().get(url, timeout=8, **kwargs)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")
    except requests.RequestException:
        return None

# --- FUNCIONES DE EXTRACCIÓN (ATÓMICAS Y RÁPIDAS) ---
@st.cache_data(ttl=7200)
def get_match_progression_stats_data(match_id: str) -> pd.DataFrame | None:
    if not match_id or not match_id.isdigit(): return None
    url = f"https://live18.nowgoal25.com/match/live-{match_id}"
    try:
        response = get_requests_session_of().get(url, headers={"Accept-Language": "en-US,en;q=0.9"}, timeout=8)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'lxml')
        stats = {"Shots": "-", "Shots on Goal": "-", "Attacks": "-", "Dangerous Attacks": "-"}
        if (tech_div := soup.find('div', id='teamTechDiv_detail')) and (stat_list := tech_div.find('ul', class_='stat')):
            for li in stat_list.find_all('li'):
                if (title_span := li.find('span', class_='stat-title')) and (stat_title := title_span.get_text(strip=True)) in stats:
                    values = [v.get_text(strip=True) for v in li.find_all('span', class_='stat-c')]
                    if len(values) == 2:
                        stats[stat_title] = (values[0], values[1])
        df_data = [{"Estadistica_EN": name, "Casa": v[0], "Fuera": v[1]} for name, v in stats.items() if isinstance(v, tuple)]
        if not df_data: return None
        return pd.DataFrame(df_data).set_index("Estadistica_EN")
    except requests.RequestException:
        return None

def display_match_progression_stats_view(stats_df: pd.DataFrame | None, home_team_name: str, away_team_name: str, title: str):
    if stats_df is None or stats_df.empty:
        st.caption(f"ℹ️ _Estadísticas de progresión no disponibles para: {title}_")
        return

    st.markdown(f"###### 👁️ Est. Progresión: _{title}_")
    stat_map = {"Shots": "Disparos", "Shots on Goal": "Disparos a Puerta", "Attacks": "Ataques", "Dangerous Attacks": "Ataques Peligrosos"}
    for stat_en, stat_es in stat_map.items():
        if stat_en in stats_df.index:
            home_val, away_val = stats_df.loc[stat_en, 'Casa'], stats_df.loc[stat_en, 'Fuera']
            try: home_num, away_num = int(home_val), int(away_val)
            except (ValueError, TypeError): home_num, away_num = 0, 0
            home_color, away_color = ("green", "red") if home_num > away_num else (("red", "green") if away_num > home_num else ("gray", "gray"))
            st.markdown(f"<div style='display: flex; justify-content: space-between; align-items: center;'>"
                        f"<strong style='color:{home_color};'>{home_val}</strong>"
                        f"<span style='font-size:0.9em; text-align:center;'>{stat_es}</span>"
                        f"<strong style='color:{away_color};'>{away_val}</strong>"
                        f"</div>", unsafe_allow_html=True)

@st.cache_data(ttl=3600)
def get_main_match_odds_requests_of(match_id):
    try:
        url = f"https://data.nowgoal25.com/3in1Odds/{match_id}"
        response = get_requests_session_of().get(url, timeout=5).text
        data_parts = response.split('$$')
        company_id_target = "8" # Bet365
        ah_line = next((line.split(',') for line in data_parts[0].split(';') if line.startswith(company_id_target)), None)
        ou_line = next((line.split(',') for line in data_parts[2].split(';') if line.startswith(company_id_target)), None)
        return {
            "ah_home_cuota": ah_line[2] if ah_line and len(ah_line) > 4 else "N/A",
            "ah_linea_raw": ah_line[3] if ah_line and len(ah_line) > 4 else "N/A",
            "ah_away_cuota": ah_line[4] if ah_line and len(ah_line) > 4 else "N/A",
            "goals_over_cuota": ou_line[2] if ou_line and len(ou_line) > 4 else "N/A",
            "goals_linea_raw": ou_line[3] if ou_line and len(ou_line) > 4 else "N/A",
            "goals_under_cuota": ou_line[4] if ou_line and len(ou_line) > 4 else "N/A"
        }
    except Exception:
        return {k: "N/A" for k in ["ah_home_cuota", "ah_linea_raw", "ah_away_cuota", "goals_over_cuota", "goals_linea_raw", "goals_under_cuota"]}

def extract_all_data_from_main_soup(soup):
    if not soup: return {}
    data = {}
    script_tag = soup.find("script", string=re.compile(r"var _matchInfo ="))
    if script_tag and script_tag.string:
        data.update({
            "home_id": (m.group(1) if (m := re.search(r"hId:\s*parseInt\('(\d+)'\)", script_tag.string)) else None),
            "away_id": (m.group(1) if (m := re.search(r"gId:\s*parseInt\('(\d+)'\)", script_tag.string)) else None),
            "league_id": (m.group(1) if (m := re.search(r"sclassId:\s*parseInt\('(\d+)'\)", script_tag.string)) else None),
            "home_name": (m.group(1).replace("\\'", "'") if (m := re.search(r"hName:\s*'([^']*)'", script_tag.string)) else "Local"),
            "away_name": (m.group(1).replace("\\'", "'") if (m := re.search(r"gName:\s*'([^']*)'", script_tag.string)) else "Visitante"),
            "league_name": (m.group(1).replace("\\'", "'") if (m := re.search(r"lName:\s*'([^']*)'", script_tag.string)) else "N/A")
        })

    data["final_score"], _ = ('?:?', '?-?') if not (s := soup.select('#mScore .end .score')) or len(s) != 2 else (f"{s[0].text.strip()}:{s[1].text.strip()}", f"{s[0].text.strip()}-{s[1].text.strip()}")

    # Historiales y Clasificaciones (ya no necesitan re-fetching)
    if "home_name" in data:
        data['home_standings'] = extract_standings_data_from_h2h_page_of(soup, data['home_name'])
        data['away_standings'] = extract_standings_data_from_h2h_page_of(soup, data['away_name'])
        data['last_home_match'] = extract_last_match_of_team(soup, "table_v1", data['home_name'], data.get('league_id'), is_home=True)
        data['last_away_match'] = extract_last_match_of_team(soup, "table_v2", data['away_name'], data.get('league_id'), is_home=False)
        data['h2h_direct_data'] = extract_h2h_data_of(soup, data['home_name'], data['away_name'], data.get('league_id'))
        
        # Partidos comparativos
        if data['last_away_match'] and 'home_team' in data['last_away_match']:
             rival_name = data['last_away_match']['away_team'] if data['away_name'].lower() == data['last_away_match']['home_team'].lower() else data['last_away_match']['home_team']
             data['comp_L_vs_UV_A'] = extract_comparative_match_of(soup, "table_v1", data['home_name'], rival_name, data.get('league_id'), is_home_table=True)

        if data['last_home_match'] and 'away_team' in data['last_home_match']:
            rival_name = data['last_home_match']['home_team'] if data['home_name'].lower() == data['last_home_match']['away_team'].lower() else data['last_home_match']['away_team']
            data['comp_V_vs_UL_H'] = extract_comparative_match_of(soup, "table_v2", data['away_name'], rival_name, data.get('league_id'), is_home_table=False)

    return data
    
def extract_standings_data_from_h2h_page_of(soup, team_name):
    # (Sin cambios, ya era eficiente)
    data = {"name": team_name, "ranking": "N/A", "total_pj": "N/A", "total_v": "N/A", "total_e": "N/A", "total_d": "N/A", "total_gf": "N/A", "total_gc": "N/A", "specific_pj": "N/A", "specific_v": "N/A", "specific_e": "N/A", "specific_d": "N/A", "specific_gf": "N/A", "specific_gc": "N/A", "specific_type": "N/A"}
    if not soup or not (standings_section := soup.find("div", id="porletP4")): return data
    div_class, table_class, specific_type_str = ("home-div", "team-table-home", "Local") if (h_div := standings_section.find("div", class_="home-div")) and team_name.lower() in h_div.get_text(strip=True).lower() else (("guest-div", "team-table-guest", "Visitante") if (g_div := standings_section.find("div", class_="guest-div")) and team_name.lower() in g_div.get_text(strip=True).lower() else (None, None, None))
    if not div_class or not (table_soup := standings_section.find("div", class_=div_class).find("table", class_=table_class)): return data
    data['specific_type'] = f"Est. como {specific_type_str} (en Liga)"
    if (header_link := table_soup.find("a")) and (full_text := header_link.get_text(separator=" ", strip=True)):
        if m := re.search(r"\[(?:[^\]]+-)?(\d+)\]", full_text): data["ranking"] = m.group(1)
        if m := re.search(r"]\s*(.*)", full_text): data["name"] = m.group(1).strip()
    rows = iter(table_soup.find_all("tr", align="center"))
    for row in rows:
        if row.find("th") and "FT" in row.find("th").get_text(): break
    for row_type, key_prefix in [("Total", "total"), (specific_type_str.capitalize(), "specific")]:
        for row in rows:
            if not (cells := row.find_all("td")) or len(cells) < 7: continue
            row_type_text = (cells[0].find("span") or cells[0]).get_text(strip=True)
            if row_type_text == row_type:
                stats = [c.get_text(strip=True) or "N/A" for c in cells[1:7]]
                data.update({f"{key_prefix}_pj": stats[0], f"{key_prefix}_v": stats[1], f"{key_prefix}_e": stats[2], f"{key_prefix}_d": stats[3], f"{key_prefix}_gf": stats[4], f"{key_prefix}_gc": stats[5]})
                break
    return data

def extract_h2h_data_of(soup, home_name, away_name, league_id):
    h2h_gen, h2h_spec = (None,)*2
    if not (table := soup.find("table", id="table_v3")): return h2h_gen, h2h_spec
    h2h_list = [d for r in table.find_all("tr", id=re.compile(r"tr3_\d+")) if (d := get_match_details_from_row_of(r, 'fscore_3')) and (not league_id or not d.get('league_id_hist') or d['league_id_hist'] == league_id)]
    if not h2h_list: return None, None
    h2h_gen = h2h_list[0]
    for h2h in h2h_list:
        if h2h['home'].lower() == home_name.lower() and h2h['away'].lower() == away_name.lower():
            h2h_spec = h2h; break
    return h2h_gen, h2h_spec

def extract_last_match_of_team(soup, table_id, team_name, league_id, is_home):
    if not (table := soup.find("table", id=table_id)): return None
    for row in table.find_all("tr", id=re.compile(rf"tr{table_id[-1]}_\d+")):
        if league_id and row.get("name") != league_id: continue
        if not (details := get_match_details_from_row_of(row, 'fscore_1' if is_home else 'fscore_2')): continue
        if (is_home and details['home'].lower() == team_name.lower()) or \
           (not is_home and details['away'].lower() == team_name.lower()):
            return details
    return None

def extract_comparative_match_of(soup, table_id, main_team, rival_name, league_id, is_home_table):
    if not rival_name or not (table := soup.find("table", id=table_id)): return None
    for row in table.find_all("tr", id=re.compile(rf"tr{table_id[-1]}_\d+")):
        if league_id and row.get("name") != league_id: continue
        if not (details := get_match_details_from_row_of(row, 'fscore_1' if is_home_table else 'fscore_2')): continue
        if (main_team.lower() == details['home'].lower() and rival_name.lower() == details['away'].lower()) or \
           (main_team.lower() == details['away'].lower() and rival_name.lower() == details['home'].lower()):
            return details
    return None

def get_col3_h2h_details(match_id):
    if not match_id: return {"status": "error", "resultado": "ID de partido principal no encontrado."}
    soup_main_h2h = fetch_soup_requests_of(f"/match/h2h-{match_id}")
    if not soup_main_h2h: return {"status": "error", "resultado": "No se pudo cargar la pág. del partido principal."}
    
    rival_a, rival_b = (None, None, None), (None, None, None)
    # Get Rival A
    if (table1 := soup_main_h2h.find("table", id="table_v1")):
        for row in table1.find_all("tr", vs="1"):
            if (a_tags := row.find_all("a", onclick=True)) and len(a_tags) > 1:
                if (m := re.search(r"team\((\d+)\)", a_tags[1]['onclick'])):
                    rival_a = (row.get("index"), m.group(1), a_tags[1].text.strip())
                    break
    # Get Rival B
    if (table2 := soup_main_h2h.find("table", id="table_v2")):
        for row in table2.find_all("tr", vs="1"):
            if (a_tags := row.find_all("a", onclick=True)) and len(a_tags) > 0:
                if (m := re.search(r"team\((\d+)\)", a_tags[0]['onclick'])):
                    rival_b = (row.get("index"), m.group(1), a_tags[0].text.strip())
                    break

    h2h_match_id, rival_a_id, rival_a_name = rival_a
    _, rival_b_id, rival_b_name = rival_b
    if not all([h2h_match_id, rival_a_id, rival_b_id]):
        return {"status": "error", "resultado": "No se pudieron identificar ambos rivales."}

    soup_h2h_rivals = fetch_soup_requests_of(f"/match/h2h-{h2h_match_id}")
    if not soup_h2h_rivals: return {"status": "error", "resultado": "No se pudo cargar pág. H2H de rivales."}

    if (table := soup_h2h_rivals.find("table", id="table_v2")):
        for row in table.find_all("tr", id=re.compile(r"tr2_\d+")):
            if (details := get_match_details_from_row_of(row, 'fscore_2')) and \
               (a_tags := row.find_all("a", onclick=True)) and len(a_tags) > 1:
                home_id_m = re.search(r"team\((\d+)\)", a_tags[0]['onclick'])
                away_id_m = re.search(r"team\((\d+)\)", a_tags[1]['onclick'])
                if home_id_m and away_id_m:
                    ids = {home_id_m.group(1), away_id_m.group(1)}
                    if ids == {rival_a_id, rival_b_id}:
                        details['status'] = 'found'
                        return details
    return {"status": "not_found", "resultado": f"H2H no encontrado para {rival_a_name} vs {rival_b_name}."}


# --- STREAMLIT APP UI (REESTRUCTURADA PARA MÁXIMA VELOCIDAD) ---
def display_other_feature_ui():
    st.markdown("""<style>/* ... CSS sin cambios ... */</style>""", unsafe_allow_html=True) # CSS OMITIDO POR BREVEDAD

    st.sidebar.title("⚙️ Configuración del Partido (OF)")
    main_match_id_input = st.sidebar.text_input("🆔 ID Partido Principal:", "2696131", key="id_input")
    if st.sidebar.button("🚀 Analizar Partido (OF)", type="primary", use_container_width=True):
        
        try:
            main_match_id = int("".join(filter(str.isdigit, main_match_id_input)))
        except (ValueError, TypeError):
            st.error("⚠️ Por favor, ingresa un ID de partido válido."); return
        
        start_time = time.time()
        
        # CONTENEDORES PARA RESULTADOS
        all_data = {}
        prog_stats = {}
        
        with st.spinner("⚡️ Iniciando extracción paralela..."):
            with ThreadPoolExecutor(max_workers=10) as executor:
                # 1. Lanzar tareas primarias
                future_main_soup = executor.submit(fetch_soup_requests_of, f"/match/h2h-{main_match_id}")
                future_main_odds = executor.submit(get_main_match_odds_requests_of, main_match_id)
                future_col3_h2h = executor.submit(get_col3_h2h_details, main_match_id)

                # 2. Esperar el soup principal (es la dependencia #1) y procesarlo
                main_soup = future_main_soup.result()
                if not main_soup:
                    st.error(f"❌ No se pudo obtener la página principal para ID {main_match_id}."); return
                
                all_data = extract_all_data_from_main_soup(main_soup)
                
                # 3. Lanzar tareas secundarias (estadísticas) basadas en los datos del soup
                match_ids_for_stats = {
                    'main': (main_match_id, all_data.get('home_name', 'L'), all_data.get('away_name', 'V')),
                    'last_home': (all_data.get('last_home_match', {}).get('matchIndex'), all_data.get('last_home_match', {}).get('home'), all_data.get('last_home_match', {}).get('away')),
                    'last_away': (all_data.get('last_away_match', {}).get('matchIndex'), all_data.get('last_away_match', {}).get('home'), all_data.get('last_away_match', {}).get('away')),
                    'h2h_spec': (all_data.get('h2h_direct_data', (None, {}))[1].get('matchIndex'), all_data.get('h2h_direct_data', (None, {}))[1].get('home'), all_data.get('h2h_direct_data', (None, {}))[1].get('away')),
                    'h2h_gen': (all_data.get('h2h_direct_data', ({}, None))[0].get('matchIndex'), all_data.get('h2h_direct_data', ({}, None))[0].get('home'), all_data.get('h2h_direct_data', ({}, None))[0].get('away'))
                }
                
                future_stats = {key: executor.submit(get_match_progression_stats_data, mid[0]) for key, mid in match_ids_for_stats.items() if mid[0]}
                
                # 4. Esperar resultados y renderizar
                all_data['odds'] = future_main_odds.result()
                all_data['col3_h2h'] = future_col3_h2h.result()
                if all_data.get('col3_h2h', {}).get('status') == 'found':
                     future_stats['col3'] = executor.submit(get_match_progression_stats_data, all_data['col3_h2h']['matchIndex'])

                for key, future in future_stats.items():
                    prog_stats[key] = (future.result(), match_ids_for_stats[key][1], match_ids_for_stats[key][2])


        # --- INICIO DEL RENDERIZADO (todos los datos ya están disponibles) ---
        home_name = all_data.get('home_name', 'Local')
        away_name = all_data.get('away_name', 'Visitante')
        
        st.markdown(f"<p class='sub-title' style='font-size: 1.8em'>🆚 <span class='home-color'>{home_name}</span> vs <span class='away-color'>{away_name}</span></p>", unsafe_allow_html=True)
        st.caption(f"🏆 {all_data.get('league_name', 'N/A')} | 🆔 {main_match_id}")

        # Sección de Clasificación
        with st.expander("📈 Clasificación en Liga", expanded=True):
            col1, col2 = st.columns(2)
            with col1:
                st.write(all_data.get('home_standings')) # Reemplazar con una bonita tarjeta de visualización
            with col2:
                st.write(all_data.get('away_standings')) # Reemplazar con una bonita tarjeta de visualización

        # Sección principal de cuotas y marcador
        with st.expander("⚖️ Cuotas Iniciales (Bet365) y Marcador Final", expanded=True):
            st.metric("🏁 Marcador Final", all_data.get('final_score', '?:?'))
            odds = all_data.get('odds', {})
            st.metric("⚖️ AH (Inicial)", format_ah_as_decimal_string_of(odds.get("ah_linea_raw")), f'{odds.get("ah_home_cuota")} / {odds.get("ah_away_cuota")}')
            st.metric("🥅 Goles (Inicial)", format_ah_as_decimal_string_of(odds.get("goals_linea_raw")), f'Más: {odds.get("goals_over_cuota")} / Menos: {odds.get("goals_under_cuota")}')
            if all_data.get('final_score', '?:?') != '?:?':
                df, hn, an = prog_stats.get('main', (None, home_name, away_name))
                display_match_progression_stats_view(df, hn, an, "Partido Principal")

        # Rendimiento reciente y H2H indirecto
        st.markdown("<h3 class='section-header' style='font-size:1.5em; margin-top:30px;'>⚡ Rendimiento Reciente y H2H Indirecto</h3>", unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(f"**Último <span class='home-color'>{home_name}</span> (Casa)**", unsafe_allow_html=True)
            if last_home := all_data.get('last_home_match'):
                st.markdown(f"<span class='home-color'>{last_home['home']}</span> <span class='score-value'>{last_home['score']}</span> <span class='away-color'>{last_home['away']}</span>", unsafe_allow_html=True)
                st.markdown(f"**AH:** <span class='ah-value'>{last_home['ahLine']}</span>", unsafe_allow_html=True)
                df, hn, an = prog_stats.get('last_home', (None, 'L', 'V'))
                display_match_progression_stats_view(df, hn, an, f"{hn} vs {an}")
            else: st.info("No disponible")

        with c2:
            st.markdown(f"**Último <span class='away-color'>{away_name}</span> (Fuera)**", unsafe_allow_html=True)
            if last_away := all_data.get('last_away_match'):
                st.markdown(f"<span class='home-color'>{last_away['home']}</span> <span class='score-value'>{last_away['score']}</span> <span class='away-color'>{last_away['away']}</span>", unsafe_allow_html=True)
                st.markdown(f"**AH:** <span class='ah-value'>{last_away['ahLine']}</span>", unsafe_allow_html=True)
                df, hn, an = prog_stats.get('last_away', (None, 'L', 'V'))
                display_match_progression_stats_view(df, hn, an, f"{hn} vs {an}")
            else: st.info("No disponible")

        with c3:
            st.markdown(f"**H2H Rivales (Col3)**", unsafe_allow_html=True)
            if (col3 := all_data.get('col3_h2h')) and col3.get('status') == 'found':
                st.markdown(f"<span class='home-color'>{col3['home']}</span> <span class='score-value'>{col3['score']}</span> <span class='away-color'>{col3['away']}</span>", unsafe_allow_html=True)
                st.markdown(f"**AH:** <span class='ah-value'>{col3['ahLine']}</span>", unsafe_allow_html=True)
                df, _, _ = prog_stats.get('col3', (None, None, None))
                display_match_progression_stats_view(df, col3.get('home'), col3.get('away'), f"H2H Rivales")
            else: st.info(all_data.get('col3_h2h', {}).get('resultado', 'No disponible'))
            
        # Comparativas Indirectas
        with st.expander("🔁 Comparativas Indirectas Detalladas", expanded=False):
            if comp := all_data.get('comp_L_vs_UV_A'):
                st.write(f"Comparativa L vs UV_A:", comp)
            if comp := all_data.get('comp_V_vs_UL_H'):
                st.write(f"Comparativa V vs UL_H:", comp)
        
        # H2H Directo
        with st.expander("🔰 H2H Directos", expanded=False):
             h2h_gen, h2h_spec = all_data.get('h2h_direct_data', (None, None))
             if h2h_gen: st.write("H2H General", h2h_gen)
             if h2h_spec: st.write("H2H Específico (Local en casa)", h2h_spec)

        st.sidebar.success(f"🎉 Análisis completado en {time.time() - start_time:.2f} seg.")
    else:
        st.info("✨ ¡Bienvenido! Ingresa un ID de partido y haz clic en 'Analizar'.")

if __name__ == '__main__':
    st.set_page_config(layout="wide", page_title="Análisis Avanzado de Partidos (OF)", initial_sidebar_state="expanded")
    display_other_feature_ui()
