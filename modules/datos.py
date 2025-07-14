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
API_ODDS_URL = "https://data.nowgoal.com/gf/data/panDetail/{}.json"
PLACEHOLDER_NODATA = "*(No disponible)*"

# --- FUNCIONES HELPER PARA PARSEO Y FORMATEO (Sin cambios) ---
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
    sign = -1 if numeric_value < 0 else 1
    abs_num = abs(numeric_value)
    mod_val = abs_num % 1
    if mod_val == 0.0: abs_rounded = abs_num
    elif mod_val == 0.25: abs_rounded = math.floor(abs_num) + 0.25
    elif mod_val == 0.5: abs_rounded = abs_num
    elif mod_val == 0.75: abs_rounded = math.floor(abs_num) + 0.75
    else:
        if mod_val < 0.25: abs_rounded = math.floor(abs_num)
        elif mod_val < 0.75: abs_rounded = math.floor(abs_num) + 0.5
        else: abs_rounded = math.ceil(abs_num)
    final_value_signed = sign * abs_rounded
    if final_value_signed == 0.0: output_str = "0"
    elif abs(final_value_signed - round(final_value_signed, 0)) < 1e-9 : output_str = str(int(round(final_value_signed, 0)))
    elif abs(final_value_signed - (math.floor(final_value_signed) + 0.5)) < 1e-9: output_str = f"{final_value_signed:.1f}"
    elif abs(final_value_signed - (math.floor(final_value_signed) + 0.25)) < 1e-9 or \
         abs(final_value_signed - (math.floor(final_value_signed) + 0.75)) < 1e-9: output_str = f"{final_value_signed:.2f}".replace(".25", ".25").replace(".75", ".75")
    else: output_str = f"{final_value_signed:.2f}"
    if for_sheets:
        return "'" + output_str.replace('.', ',') if output_str not in ['-','?'] else output_str
    return output_str

def get_match_details_from_row_of(row_element, score_class_selector='score', source_table_type='h2h'):
    try:
        cells = row_element.find_all(['td', 'th']) 
        home_idx, score_idx, away_idx = 2, 3, 4
        home_tag = cells[home_idx].find('a')
        home = home_tag.text.strip() if home_tag else cells[home_idx].text.strip()
        away_tag = cells[away_idx].find('a')
        away = away_tag.text.strip() if away_tag else cells[away_idx].text.strip()
        score_span = cells[score_idx].find('span', class_=score_class_selector)
        score_raw = '?-?'
        if score_span:
            score_match = re.search(r'(\d+-\d+)', score_span.text)
            if score_match:
                score_raw = score_match.group(1)
        score_fmt = score_raw.replace('-', ':')
        match_id = row_element.get('index')
        ah_line_raw_text = '-'
        if source_table_type == 'h2h' and len(cells) > 13:
            ah_line_raw_text = cells[13].text.strip()
        elif source_table_type != 'h2h' and len(cells) > 11:
            ah_line_raw_text = cells[11].text.strip()
        ah_line_fmt = format_ah_as_decimal_string_of(ah_line_raw_text)
        
        opponent_id, opponent_name = None, None
        is_home_in_row = True if home_tag and 'team' in home_tag.get('onclick', '') else False
        is_away_in_row = True if away_tag and 'team' in away_tag.get('onclick', '') else False
        
        if is_home_in_row and is_away_in_row:
             onclick_home = home_tag.get('onclick')
             onclick_away = away_tag.get('onclick')
             id_match_home = re.search(r"team\((\d+)\)", onclick_home)
             id_match_away = re.search(r"team\((\d+)\)", onclick_away)
             if id_match_home: opponent_id = id_match_away.group(1) if id_match_away else None
             opponent_name = away
        
        if not home or not away or not match_id:
            return None
        return {'home': home, 'away': away, 'score': score_fmt, 'score_raw': score_raw, 'ahLine': ah_line_fmt, 
                'ahLine_raw': ah_line_raw_text, 'matchIndex': match_id, 'vs': row_element.get('vs'), 
                'league_id_hist': row_element.get('name'), 'opponent_id': opponent_id, 'opponent_name': opponent_name}
    except Exception:
        return None

# --- SESIÓN Y FETCHING ---
@st.cache_resource
def get_requests_session_of():
    session = requests.Session()
    retries_req = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    adapter_req = HTTPAdapter(max_retries=retries_req)
    session.mount("https://", adapter_req); session.mount("http://", adapter_req)
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36"})
    return session

@st.cache_data(ttl=3600)
def fetch_soup_requests_of(path, max_tries=3, delay=1):
    session = get_requests_session_of(); url = f"{BASE_URL_OF}{path}"
    for attempt in range(1, max_tries + 1):
        try:
            resp = session.get(url, timeout=10); resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except requests.RequestException:
            if attempt == max_tries: return None
            time.sleep(delay * attempt)
    return None

# --- FUNCIONES DE ESTADÍSTICAS (Sin cambios) ---
@st.cache_data(ttl=7200)
def get_match_progression_stats_data(match_id: str) -> pd.DataFrame | None:
    base_url_live = "https://live18.nowgoal25.com/match/live-"
    full_url = f"{base_url_live}{match_id}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36",
    }
    stat_titles_of_interest = {"Shots": {"Home": "-", "Away": "-"}, "Shots on Goal": {"Home": "-", "Away": "-"}, "Attacks": {"Home": "-", "Away": "-"}, "Dangerous Attacks": {"Home": "-", "Away": "-"},}
    try:
        response = requests.get(full_url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'lxml')
        team_tech_div = soup.find('div', id='teamTechDiv_detail')
        if team_tech_div:
            stat_list = team_tech_div.find('ul', class_='stat')
            if stat_list:
                for li in stat_list.find_all('li'):
                    title_span = li.find('span', class_='stat-title')
                    if title_span:
                        stat_title = title_span.get_text(strip=True)
                        if stat_title in stat_titles_of_interest:
                            values = li.find_all('span', class_='stat-c')
                            if len(values) == 2:
                                stat_titles_of_interest[stat_title]["Home"] = values[0].get_text(strip=True)
                                stat_titles_of_interest[stat_title]["Away"] = values[1].get_text(strip=True)
    except: return None
    table_rows = [{"Estadistica_EN": name, "Casa": vals['Home'], "Fuera": vals['Away']} for name, vals in stat_titles_of_interest.items()]
    df = pd.DataFrame(table_rows)
    return df.set_index("Estadistica_EN") if not df.empty else df

def display_match_progression_stats_view(match_id: str, home_team_name: str, away_team_name: str):
    stats_df = get_match_progression_stats_data(match_id)
    if stats_df is None or stats_df.empty:
        st.caption(f"No se encontraron datos de progresión para el partido ID: **{match_id}**.")
        return
    ordered_stats_display = {"Shots": "Disparos", "Shots on Goal": "Disparos a Puerta", "Attacks": "Ataques", "Dangerous Attacks": "Ataques Peligrosos"}
    st.markdown("---")
    col_h_name, col_stat_name, col_a_name = st.columns([2, 3, 2])
    with col_h_name: st.markdown(f"<p style='font-weight:bold; color: #007bff;'>{home_team_name or 'Local'}</p>", unsafe_allow_html=True)
    with col_stat_name: st.markdown("<p style='text-align:center; font-weight:bold;'>Estadística</p>", unsafe_allow_html=True)
    with col_a_name: st.markdown(f"<p style='text-align:right; font-weight:bold; color: #fd7e14;'>{away_team_name or 'Visitante'}</p>", unsafe_allow_html=True)
    for stat_key_en, stat_name_es in ordered_stats_display.items():
        if stat_key_en in stats_df.index:
            home_val_str, away_val_str = stats_df.loc[stat_key_en, 'Casa'], stats_df.loc[stat_key_en, 'Fuera']
            try: home_val_num = int(home_val_str)
            except ValueError: home_val_num = 0
            try: away_val_num = int(away_val_str)
            except ValueError: away_val_num = 0
            home_color, away_color = ("green", "red") if home_val_num > away_val_num else (("red", "green") if away_val_num > home_val_num else ("black", "black"))
            c1, c2, c3 = st.columns([2, 3, 2])
            with c1: c1.markdown(f'<p style="font-size: 1.1em; font-weight:bold; color:{home_color};">{home_val_str}</p>', unsafe_allow_html=True)
            with c2: c2.markdown(f'<p style="text-align:center;">{stat_name_es}</p>', unsafe_allow_html=True)
            with c3: c3.markdown(f'<p style="text-align:right; font-size: 1.1em; font-weight:bold; color:{away_color};">{away_val_str}</p>', unsafe_allow_html=True)
    st.markdown("---")

def display_previous_match_progression_stats(title: str, match_id_str: str | None, home_name: str, away_name: str):
    if not match_id_str or match_id_str == "N/A" or not match_id_str.isdigit():
        st.caption(f"ℹ️ _No hay ID para estadísticas de progresión para: {title}_")
        return
    st.markdown(f"###### 👁️ _Est. Progresión para: {title}_")
    display_match_progression_stats_view(match_id_str, home_name, away_name)

# --- NUEVAS FUNCIONES DE EXTRACCIÓN OPTIMIZADAS (SIN SELENIUM) ---

@st.cache_data(ttl=3600)
def get_main_match_odds_api(match_id):
    """Obtiene las cuotas iniciales de Bet365 directamente desde la API JSON."""
    odds_info = {"ah_home_cuota": "N/A", "ah_linea_raw": "N/A", "ah_away_cuota": "N/A", "goals_over_cuota": "N/A", "goals_linea_raw": "N/A", "goals_under_cuota": "N/A"}
    try:
        url = API_ODDS_URL.format(match_id)
        session = get_requests_session_of()
        response = session.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        # Bet365 tiene el ID de compañía 8
        bet365_hda = next((c for c in data.get('hda', []) if c['cId'] == 8), None)
        bet365_ou = next((c for c in data.get('ou', []) if c['cId'] == 8), None)
        
        if bet365_hda and bet365_hda.get('early'):
            odds_info["ah_home_cuota"] = str(bet365_hda['early'][0])
            odds_info["ah_linea_raw"] = str(bet365_hda['early'][1])
            odds_info["ah_away_cuota"] = str(bet365_hda['early'][2])

        if bet365_ou and bet365_ou.get('early'):
            odds_info["goals_linea_raw"] = str(bet365_ou['early'][0])
            odds_info["goals_over_cuota"] = str(bet365_ou['early'][1])
            odds_info["goals_under_cuota"] = str(bet365_ou['early'][2])
    except (requests.RequestException, ValueError):
        pass # Falla silenciosamente si la API no responde o el JSON es inválido
    return odds_info

def get_team_league_info_from_script_of(soup):
    home_id, away_id, league_id, home_name, away_name, league_name = (None,)*3 + ("N/A",)*3
    script_tag = soup.find("script", string=re.compile(r"var _matchInfo ="))
    if script_tag and script_tag.string:
        script_content = script_tag.string
        h_id_m = re.search(r"hId:\s*parseInt\('(\d+)'\)", script_content); g_id_m = re.search(r"gId:\s*parseInt\('(\d+)'\)", script_content)
        sclass_id_m = re.search(r"sclassId:\s*parseInt\('(\d+)'\)", script_content); h_name_m = re.search(r"hName:\s*'([^']*)'", script_content)
        g_name_m = re.search(r"gName:\s*'([^']*)'", script_content); l_name_m = re.search(r"lName:\s*'([^']*)'", script_content)
        if h_id_m: home_id = h_id_m.group(1)
        if g_id_m: away_id = g_id_m.group(1)
        if sclass_id_m: league_id = sclass_id_m.group(1)
        if h_name_m: home_name = h_name_m.group(1).replace("\\'", "'")
        if g_name_m: away_name = g_name_m.group(1).replace("\\'", "'")
        if l_name_m: league_name = l_name_m.group(1).replace("\\'", "'")
    return home_id, away_id, league_id, home_name, away_name, league_name

def extract_last_match_from_soup(soup, table_id, main_team_name, league_id, filter_type):
    """
    Función unificada y optimizada para extraer el último partido desde un objeto soup.
    filter_type puede ser: 'home', 'away', o 'overall'.
    """
    table = soup.find("table", id=table_id)
    if not table: return None

    for row in table.find_all("tr", id=re.compile(rf"tr{table_id[-1]}_\d+")):
        if league_id and row.get("name") != str(league_id):
            continue

        tds = row.find_all("td")
        if len(tds) < 12: continue

        home_el = tds[2].find("a"); away_el = tds[4].find("a")
        if not home_el or not away_el: continue
        
        home_name = home_el.text.strip(); away_name = away_el.text.strip()
        
        is_team_home = main_team_name.lower() == home_name.lower()
        is_team_away = main_team_name.lower() == away_name.lower()

        # Aplicar filtro de localía
        if not (is_team_home or is_team_away): continue
        if (filter_type == 'home' and not is_team_home) or \
           (filter_type == 'away' and not is_team_away):
            continue
        
        # Si pasa los filtros, es el partido que buscamos
        opponent_el = away_el if is_team_home else home_el
        onclick_attr = opponent_el.get("onclick", "")
        id_match = re.search(r"team\((\d+)\)", onclick_attr)
        opponent_id = id_match.group(1) if id_match else None
        
        score_span = tds[3].find("span", class_=re.compile(r"fscore_")); 
        score = score_span.text.strip() if score_span else "N/A"
        
        handicap_cell = tds[11]
        handicap_raw = handicap_cell.get("data-o", handicap_cell.text.strip()) or "N/A"

        return {
            "date": tds[1].text.strip(), "home_team": home_name, "away_team": away_name,
            "score": score, "handicap_line_raw": handicap_raw.strip(), "match_id": row.get('index'),
            "opponent_name": opponent_el.text.strip(), "opponent_id": opponent_id
        }
    return None

def extract_standings_data_from_h2h_page_of(h2h_soup, target_team_name_exact):
    data = {"name": target_team_name_exact, "ranking": "N/A", "total_pj": "N/A", "total_v": "N/A", "total_e": "N/A", "total_d": "N/A", "total_gf": "N/A", "total_gc": "N/A", "specific_pj": "N/A", "specific_v": "N/A", "specific_e": "N/A", "specific_d": "N/A", "specific_gf": "N/A", "specific_gc": "N/A", "specific_type": "N/A"}
    if not h2h_soup or not target_team_name_exact: return data
    standings_section = h2h_soup.find("div", id="porletP4")
    if not standings_section: return data
    team_table_soup = None
    is_home_table_type = False
    home_div = standings_section.find("div", class_="home-div")
    if home_div and (header_tr := home_div.find("tr", class_="team-home")) and header_tr.find("a") and target_team_name_exact.lower() in header_tr.find("a").get_text(strip=True).lower():
        team_table_soup = home_div.find("table", class_="team-table-home")
        is_home_table_type = True
        data["specific_type"] = "Est. como Local (en Liga)"
    if not team_table_soup and (guest_div := standings_section.find("div", class_="guest-div")) and (header_tr := guest_div.find("tr", class_="team-guest")) and header_tr.find("a") and target_team_name_exact.lower() in header_tr.find("a").get_text(strip=True).lower():
        team_table_soup = guest_div.find("table", class_="team-table-guest")
        is_home_table_type = False
        data["specific_type"] = "Est. como Visitante (en Liga)"
    if not team_table_soup: return data
    if (header_link := team_table_soup.find("tr", class_=re.compile(r"team-(home|guest)")).find("a")):
        full_text = header_link.get_text(separator=" ", strip=True)
        if (name_match := re.search(r"]\s*(.*)", full_text)): data["name"] = name_match.group(1).strip()
        if (rank_match := re.search(r"\[(?:[^\]]+-)?(\d+)\]", full_text)): data["ranking"] = rank_match.group(1)
    in_ft_section = False
    for row in team_table_soup.find_all("tr", align="center"):
        if (th_header := row.find("th")):
            if "FT" in th_header.get_text(strip=True): in_ft_section = True; continue
            elif "HT" in th_header.get_text(strip=True): break
        if in_ft_section and (cells := row.find_all("td")) and len(cells) >= 7:
            row_type_text = (cells[0].find("span") or cells[0]).get_text(strip=True)
            stats_values = [cell.get_text(strip=True) or "N/A" for cell in cells[1:7]]
            pj, v, e, d, gf, gc = stats_values[:6]
            if row_type_text == "Total": data.update({"total_pj": pj, "total_v": v, "total_e": e, "total_d": d, "total_gf": gf, "total_gc": gc})
            elif (row_type_text == "Home" and is_home_table_type) or (row_type_text == "Away" and not is_home_table_type): data.update({"specific_pj": pj, "specific_v": v, "specific_e": e, "specific_d": d, "specific_gf": gf, "specific_gc": gc})
    return data

def extract_final_score_of(soup):
    try:
        if (score_divs := soup.select('#mScore .end .score')) and len(score_divs) == 2:
            hs, aws = score_divs[0].text.strip(), score_divs[1].text.strip()
            if hs.isdigit() and aws.isdigit(): return f"{hs}:{aws}", f"{hs}-{aws}"
    except Exception: pass
    return '?:?', "?-?"

def extract_h2h_data_of(soup, main_home_team_name, main_away_team_name, current_league_id):
    ah1, res1, _, match1_id = '-', '?:?', '?-?', None
    ah6, res6, _, match6_id = '-', '?:?', '?-?', None
    h2h_gen_home_name, h2h_gen_away_name = "Local (H2H Gen)", "Visitante (H2H Gen)"
    h2h_table = soup.find("table", id="table_v3")
    if not (h2h_table and main_home_team_name and main_away_team_name):
        return ah1, res1, None, match1_id, ah6, res6, None, match6_id, h2h_gen_home_name, h2h_gen_away_name
    filtered_h2h_list = [details for row_h2h in h2h_table.find_all("tr", id=re.compile(r"tr3_\d+")) if (details := get_match_details_from_row_of(row_h2h, 'fscore_3', 'h2h')) and (not current_league_id or details.get('league_id_hist') == str(current_league_id))]
    if not filtered_h2h_list:
        return ah1, res1, None, match1_id, ah6, res6, None, match6_id, h2h_gen_home_name, h2h_gen_away_name
    h2h_general_match = filtered_h2h_list[0]
    ah6, res6, match6_id = h2h_general_match.get('ahLine', '-'), h2h_general_match.get('score', '?:?'), h2h_general_match.get('matchIndex')
    h2h_gen_home_name, h2h_gen_away_name = h2h_general_match.get('home'), h2h_general_match.get('away')
    for d_h2h in filtered_h2h_list:
        if d_h2h.get('home','').lower() == main_home_team_name.lower() and d_h2h.get('away','').lower() == main_away_team_name.lower():
            ah1, res1, match1_id = d_h2h.get('ahLine', '-'), d_h2h.get('score', '?:?'), d_h2h.get('matchIndex')
            break
    return ah1, res1, None, match1_id, ah6, res6, None, match6_id, h2h_gen_home_name, h2h_gen_away_name

def extract_comparative_match_of(soup, table_id, team_name, opponent_name, league_id, is_home_table):
    if not opponent_name or opponent_name == "N/A" or not team_name: return None
    table = soup.find("table", id=table_id)
    if not table: return None
    score_class = 'fscore_1' if is_home_table else 'fscore_2'
    for row in table.find_all("tr", id=re.compile(rf"tr{table_id[-1]}_\d+")):
        details = get_match_details_from_row_of(row, score_class, 'hist')
        if not details or (league_id and details.get('league_id_hist') != str(league_id)): continue
        home_hist, away_hist = details.get('home','').lower(), details.get('away','').lower()
        team_main_lower, opponent_lower = team_name.lower(), opponent_name.lower()
        if (team_main_lower == home_hist and opponent_lower == away_hist) or (team_main_lower == away_hist and opponent_lower == home_hist):
            return {"score": details.get('score', '?:?'), "ah_line": details.get('ahLine', '-'),
                    "localia": 'H' if team_main_lower == home_hist else 'A', "home_team": details.get('home'),
                    "away_team": details.get('away'), "match_id": details.get('matchIndex')}
    return None

# --- STREAMLIT APP UI (Función principal REESTRUCTURADA) ---
def display_other_feature_ui():
    st.markdown("""
    <style>
        .main-title { font-size: 2.2em; font-weight: bold; color: #1E90FF; text-align: center; margin-bottom: 5px; }
        .sub-title { font-size: 1.6em; text-align: center; margin-bottom: 15px; }
        .card-title { font-size: 1.3em; font-weight: bold; color: #333; margin-bottom: 10px; }
        .home-color { color: #007bff; font-weight: bold; }
        .away-color { color: #fd7e14; font-weight: bold; }
        .score-value { font-size: 1.1em; font-weight: bold; color: #28a745; margin: 0 5px; }
        .ah-value { font-weight: bold; color: #6f42c1; }
        div[data-testid="stExpander"] div[role="button"] p {font-size: 1.5em; font-weight: bold; color: #4682B4;}
    </style>
    """, unsafe_allow_html=True)

    st.sidebar.image("https://raw.githubusercontent.com/streamlit/docs/main/public/images/brand/streamlit-logo-secondary-colormark-darktext.svg", width=200)
    st.sidebar.title("⚙️ Configuración del Partido (OF)")
    main_match_id_input = st.sidebar.text_input(
        "🆔 ID Partido Principal:", value="2696131",
        help="Pega el ID numérico del partido que deseas analizar.", key="other_feature_match_id_input")
    analizar_button = st.sidebar.button("🚀 Analizar Partido (OF)", type="primary", use_container_width=True, key="other_feature_analizar_button")

    if not analizar_button:
        st.info("✨ ¡Bienvenido! Ingresa un ID de partido y haz clic en 'Analizar Partido (OF)'.")
        return

    try:
        match_id = int("".join(filter(str.isdigit, main_match_id_input)))
    except (ValueError, TypeError):
        st.error("⚠️ El ID de partido ingresado no es válido."); return

    start_time = time.time()
    with st.spinner("🔄 Cargando y procesando datos del partido..."):
        # --- CARGA DE DATOS PRINCIPAL (TODO CON REQUESTS) ---
        h2h_path = f"/match/h2h-{match_id}"
        soup = fetch_soup_requests_of(h2h_path)
        if not soup:
            st.error(f"❌ No se pudo obtener la página H2H para ID {match_id}."); return
        
        odds_data = get_main_match_odds_api(match_id)
        
        home_id, away_id, league_id, home_name_script, away_name_script, league_name = get_team_league_info_from_script_of(soup)
        
        home_standings = extract_standings_data_from_h2h_page_of(soup, home_name_script)
        away_standings = extract_standings_data_from_h2h_page_of(soup, away_name_script)
        
        home_name = home_standings.get("name", "N/A") if home_standings.get("name") != "N/A" else home_name_script
        away_name = away_standings.get("name", "N/A") if away_standings.get("name") != "N/A" else away_name_script
        
        final_score, _ = extract_final_score_of(soup)
        ah1, res1, _, m1_id, ah6, res6, _, m6_id, h2h_gen_h, h2h_gen_a = extract_h2h_data_of(soup, home_name, away_name, league_id)

    # --- RENDERIZACIÓN DE LA UI (INSTANTÁNEA) ---
    st.markdown(f"<p class='main-title'>📊 Análisis Rápido de Partido ⚡</p>", unsafe_allow_html=True)
    st.markdown(f"<p class='sub-title'>🆚 <span class='home-color'>{home_name}</span> vs <span class='away-color'>{away_name}</span></p>", unsafe_allow_html=True)
    st.caption(f"🏆 **Liga:** {league_name or PLACEHOLDER_NODATA} | 🆔 **Partido ID:** {match_id}")
    st.divider()

    # --- SECCIÓN DE CLASIFICACIÓN ---
    st.markdown("### 📈 Clasificación en Liga")
    col_home_stand, col_away_stand = st.columns(2)
    def display_standings_card(col, team_standings_data, color_class):
        name = team_standings_data.get("name", "N/A")
        rank = team_standings_data.get("ranking", "N/A")
        with col:
            st.markdown(f"<h4 class='card-title {color_class}'>{name} (Ranking: {rank})</h4>", unsafe_allow_html=True)
            st.markdown(f"**Total:** V:{team_standings_data.get('total_v', '-')} E:{team_standings_data.get('total_e', '-')} D:{team_standings_data.get('total_d', '-')} (GF:{team_standings_data.get('total_gf', '-')}, GC:{team_standings_data.get('total_gc', '-')})")
            st.markdown(f"**Específico:** V:{team_standings_data.get('specific_v', '-')} E:{team_standings_data.get('specific_e', '-')} D:{team_standings_data.get('specific_d', '-')} (GF:{team_standings_data.get('specific_gf', '-')}, GC:{team_standings_data.get('specific_gc', '-')})")
    display_standings_card(col_home_stand, home_standings, "home-color")
    display_standings_card(col_away_stand, away_standings, "away-color")
    st.divider()

    # --- SECCIONES DE ANÁLISIS EN EXPANDERS ---
    
    with st.expander("⚖️ Cuotas Iniciales y Marcador Final"):
        st.metric("🏁 Marcador Final", final_score if final_score != "?:?" else PLACEHOLDER_NODATA)
        st.metric("⚖️ AH (Línea Inicial)", format_ah_as_decimal_string_of(odds_data['ah_linea_raw']), f"{odds_data.get('ah_home_cuota','-')} / {odds_data.get('ah_away_cuota','-')}")
        st.metric("🥅 Goles (Línea Inicial)", format_ah_as_decimal_string_of(odds_data['goals_linea_raw']), f"Más: {odds_data.get('goals_over_cuota','-')} / Menos: {odds_data.get('goals_under_cuota','-')}")
        if final_score != "?:?": display_previous_match_progression_stats(f"Principal: {home_name} vs {away_name}", str(match_id), home_name, away_name)

    with st.expander("⚡ Rendimiento Reciente (Local/Visitante) y H2H Indirecto"):
        last_home_match = extract_last_match_from_soup(soup, "table_v1", home_name, league_id, 'home')
        last_away_match = extract_last_match_from_soup(soup, "table_v2", away_name, league_id, 'away')
        
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(f"<h4 class='card-title'>Último <span class='home-color'>{home_name}</span> (Casa)</h4>", unsafe_allow_html=True)
            if last_home_match:
                res = last_home_match
                st.markdown(f"🆚 <span class='away-color'>{res['opponent_name']}</span> | <span class='score-value'>{res['score'].replace('-',':')}</span>", unsafe_allow_html=True)
                st.markdown(f"**AH:** <span class='ah-value'>{format_ah_as_decimal_string_of(res.get('handicap_line_raw','-'))}</span>", unsafe_allow_html=True)
                display_previous_match_progression_stats(f"Últ. {home_name} (C)", res.get('match_id'), res.get('home_team'), res.get('away_team'))
            else: st.info(f"No se encontró último partido en casa.")
        with c2:
            st.markdown(f"<h4 class='card-title'>Último <span class='away-color'>{away_name}</span> (Fuera)</h4>", unsafe_allow_html=True)
            if last_away_match:
                res = last_away_match
                st.markdown(f"🆚 <span class='home-color'>{res['opponent_name']}</span> | <span class='score-value'>{res['score'].replace('-',':')}</span>", unsafe_allow_html=True)
                st.markdown(f"**AH:** <span class='ah-value'>{format_ah_as_decimal_string_of(res.get('handicap_line_raw','-'))}</span>", unsafe_allow_html=True)
                display_previous_match_progression_stats(f"Últ. {away_name} (F)", res.get('match_id'), res.get('home_team'), res.get('away_team'))
            else: st.info(f"No se encontró último partido fuera.")
        with c3:
            st.markdown(f"<h4 class='card-title'>🆚 H2H Rivales Recientes</h4>", unsafe_allow_html=True)
            # Esta lógica es compleja y lenta, se puede simplificar o mantener si es crucial
            st.info("H2H de rivales no implementado en versión rápida.")

    with st.expander("⚡ Rendimiento Último Partido (General) y H2H Indirecto"):
        last_overall_home = extract_last_match_from_soup(soup, "table_v1", home_name, league_id, 'overall')
        last_overall_away = extract_last_match_from_soup(soup, "table_v2", away_name, league_id, 'overall')
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(f"<h4 class='card-title'>Último General <span class='home-color'>{home_name}</span></h4>", unsafe_allow_html=True)
            if last_overall_home:
                res = last_overall_home
                st.markdown(f"🆚 <span class='away-color'>{res['opponent_name']}</span> | <span class='score-value'>{res['score'].replace('-',':')}</span>", unsafe_allow_html=True)
                st.markdown(f"**AH:** <span class='ah-value'>{format_ah_as_decimal_string_of(res.get('handicap_line_raw','-'))}</span>", unsafe_allow_html=True)
                display_previous_match_progression_stats(f"Últ. Gen. {home_name}", res.get('match_id'), res.get('home_team'), res.get('away_team'))
            else: st.info("No se encontró último partido.")
        with c2:
            st.markdown(f"<h4 class='card-title'>Último General <span class='away-color'>{away_name}</span></h4>", unsafe_allow_html=True)
            if last_overall_away:
                res = last_overall_away
                st.markdown(f"🆚 <span class='home-color'>{res['opponent_name']}</span> | <span class='score-value'>{res['score'].replace('-',':')}</span>", unsafe_allow_html=True)
                st.markdown(f"**AH:** <span class='ah-value'>{format_ah_as_decimal_string_of(res.get('handicap_line_raw','-'))}</span>", unsafe_allow_html=True)
                display_previous_match_progression_stats(f"Últ. Gen. {away_name}", res.get('match_id'), res.get('home_team'), res.get('away_team'))
            else: st.info("No se encontró último partido.")
        with c3:
            st.markdown(f"<h4 class='card-title'>🆚 H2H Últimos Rivales</h4>", unsafe_allow_html=True)
            st.info("H2H de rivales no implementado en versión rápida.")

    with st.expander("🔰 H2H Directos (Local vs Visitante)"):
        c1, c2 = st.columns(2)
        with c1:
            st.metric("AH H2H (Local en Casa)", ah1 if ah1 != '-' else PLACEHOLDER_NODATA)
            st.metric("Res H2H (Local en Casa)", res1.replace("*",":") if res1 != '?:?' else PLACEHOLDER_NODATA)
            if m1_id: display_previous_match_progression_stats(f"H2H: {home_name} (C)", m1_id, home_name, away_name)
        with c2:
            st.metric("AH H2H (Último General)", ah6 if ah6 != '-' else PLACEHOLDER_NODATA)
            st.metric("Res H2H (Último General)", res6.replace("*",":") if res6 != '?:?' else PLACEHOLDER_NODATA)
            if m6_id: display_previous_match_progression_stats(f"H2H Gen: {h2h_gen_h} vs {h2h_gen_a}", m6_id, h2h_gen_h, h2h_gen_a)

    end_time = time.time()
    st.sidebar.success(f"🎉 Análisis completado en {end_time - start_time:.2f} segundos.")

if __name__ == '__main__':
    st.set_page_config(layout="wide", page_title="Análisis Rápido de Partidos", initial_sidebar_state="expanded")
    display_other_feature_ui()
