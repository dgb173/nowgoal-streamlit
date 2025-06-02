import requests
import re
import time
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Assuming format_ah_as_decimal_string_of is in utils.py in the same directory
from .utils import format_ah_as_decimal_string_of

# --- CONFIGURACIÓN GLOBAL ---
BASE_URL_OF = "https://live18.nowgoal25.com" # Verifica que este sea el dominio correcto

# --- FUNCIONES DE OBTENCIÓN DE DATOS ---

def get_requests_session_of():
    session = requests.Session()
    retries_req = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    adapter_req = HTTPAdapter(max_retries=retries_req)
    session.mount("https://", adapter_req)
    session.mount("http://", adapter_req)
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36"})
    return session


def fetch_soup_requests_of(path, max_tries=3, delay=1):
    session = get_requests_session_of()
    url = f"{BASE_URL_OF}{path}"
    for attempt in range(1, max_tries + 1):
        try:
            resp = session.get(url, timeout=10)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except requests.RequestException:
            if attempt == max_tries:
                return None
            time.sleep(delay * attempt)
    return None


def get_rival_a_for_original_h2h_of(main_match_id: int):
    soup_h2h_page = fetch_soup_requests_of(f"/match/h2h-{main_match_id}")
    if not soup_h2h_page:
        return None, None, None
    table = soup_h2h_page.find("table", id="table_v1")
    if not table:
        return None, None, None
    for row in table.find_all("tr", id=re.compile(r"tr1_\d+")):
        if row.get("vs") == "1":
            key_match_id_for_h2h_url = row.get("index")
            if not key_match_id_for_h2h_url:
                continue
            onclicks = row.find_all("a", onclick=True)
            if len(onclicks) > 1 and onclicks[1].get("onclick"):
                rival_tag = onclicks[1]
                rival_a_id_match = re.search(r"team\((\d+)\)", rival_tag.get("onclick", ""))
                rival_a_name = rival_tag.text.strip()
                if rival_a_id_match and rival_a_name:
                    return key_match_id_for_h2h_url, rival_a_id_match.group(1), rival_a_name
    return None, None, None


def get_rival_b_for_original_h2h_of(main_match_id: int):
    soup_h2h_page = fetch_soup_requests_of(f"/match/h2h-{main_match_id}")
    if not soup_h2h_page:
        return None, None, None
    table = soup_h2h_page.find("table", id="table_v2")
    if not table:
        return None, None, None
    for row in table.find_all("tr", id=re.compile(r"tr2_\d+")):
        if row.get("vs") == "1":
            match_id_of_rival_b_game = row.get("index")
            if not match_id_of_rival_b_game:
                continue
            onclicks = row.find_all("a", onclick=True)
            if len(onclicks) > 0 and onclicks[0].get("onclick"):
                rival_tag = onclicks[0]
                rival_b_id_match = re.search(r"team\((\d+)\)", rival_tag.get("onclick", ""))
                rival_b_name = rival_tag.text.strip()
                if rival_b_id_match and rival_b_name:
                    return match_id_of_rival_b_game, rival_b_id_match.group(1), rival_b_name
    return None, None, None


def get_team_league_info_from_script_of(soup):
    home_id, away_id, league_id, home_name, away_name, league_name = (None,) * 3 + ("N/A",) * 3
    script_tag = soup.find("script", string=re.compile(r"var _matchInfo ="))
    if script_tag and script_tag.string:
        script_content = script_tag.string
        h_id_m = re.search(r"hId:\s*parseInt\('(\d+)'\)", script_content)
        g_id_m = re.search(r"gId:\s*parseInt\('(\d+)'\)", script_content)
        sclass_id_m = re.search(r"sclassId:\s*parseInt\('(\d+)'\)", script_content)
        h_name_m = re.search(r"hName:\s*'([^']*)'", script_content)
        g_name_m = re.search(r"gName:\s*'([^']*)'", script_content)
        l_name_m = re.search(r"lName:\s*'([^']*)'", script_content)
        if h_id_m:
            home_id = h_id_m.group(1)
        if g_id_m:
            away_id = g_id_m.group(1)
        if sclass_id_m:
            league_id = sclass_id_m.group(1)
        if h_name_m: home_name = h_name_m.group(1).replace("\\'", "'")
        if g_name_m: away_name = g_name_m.group(1).replace("\\'", "'")
        if l_name_m: league_name = l_name_m.group(1).replace("\\'", "'")
    return home_id, away_id, league_id, home_name, away_name, league_name

def extract_standings_data_from_h2h_page_of(h2h_soup, target_team_name_exact):
    data = {"name": target_team_name_exact, "ranking": "N/A", "total_pj": "N/A", "total_v": "N/A", "total_e": "N/A", "total_d": "N/A", "total_gf": "N/A", "total_gc": "N/A", "specific_pj": "N/A", "specific_v": "N/A", "specific_e": "N/A", "specific_d": "N/A", "specific_gf": "N/A", "specific_gc": "N/A", "specific_type": "N/A"}
    if not h2h_soup:
        return data
    standings_section = h2h_soup.find("div", id="porletP4")
    if not standings_section:
        return data
    team_table_soup = None
    is_home_team_table_type = False
    home_div_standings = standings_section.find("div", class_="home-div")
    if home_div_standings:
        home_table_header = home_div_standings.find("tr", class_="team-home")
        if home_table_header and target_team_name_exact and target_team_name_exact.lower() in home_table_header.get_text().lower():
            team_table_soup = home_div_standings.find("table", class_="team-table-home")
            is_home_team_table_type = True
            data["specific_type"] = home_div_standings.find("td", class_="bg1").text.strip() if home_div_standings.find("td", class_="bg1") else "En Casa"
    if not team_table_soup:
        guest_div_standings = standings_section.find("div", class_="guest-div")
        if guest_div_standings:
            guest_table_header = guest_div_standings.find("tr", class_="team-guest")
            if guest_table_header and target_team_name_exact and target_team_name_exact.lower() in guest_table_header.get_text().lower():
                team_table_soup = guest_div_standings.find("table", class_="team-table-guest")
                is_home_team_table_type = False
                data["specific_type"] = guest_div_standings.find("td", class_="bg1").text.strip() if guest_div_standings.find("td", class_="bg1") else "Fuera"
    if not team_table_soup:
        return data
    header_row_found = team_table_soup.find("tr", class_=re.compile(r"team-(home|guest)"))
    if header_row_found:
        link = header_row_found.find("a")
        if link:
            full_text = link.get_text(separator=" ", strip=True)
            name_match = re.search(r"]\s*(.*)", full_text)
            rank_match = re.search(r"\[(?:[^\]]+-)?(\d+)\]", full_text)
            if name_match:
                data["name"] = name_match.group(1).strip()
            if rank_match:
                data["ranking"] = rank_match.group(1)
        else:
            header_text_no_link = header_row_found.get_text(separator=" ", strip=True)
            name_match_nl = re.search(r"]\s*(.*)", header_text_no_link)
            if name_match_nl:
                data["name"] = name_match_nl.group(1).strip()
            rank_match_nl = re.search(r"\[(?:[^\]]+-)?(\d+)\]", header_text_no_link)
            if rank_match_nl:
                data["ranking"] = rank_match_nl.group(1)
    ft_rows = []
    current_section = None
    for row in team_table_soup.find_all("tr", align="center"):
        th_cell = row.find("th")
        if th_cell:
            if "FT" in th_cell.get_text(strip=True):
                current_section = "FT"
            elif "HT" in th_cell.get_text(strip=True):
                break
        if current_section == "FT":
            cells = row.find_all("td")
            if cells and len(cells) > 0 and cells[0].get_text(strip=True) in ["Total", "Home", "Away"]:
                ft_rows.append(cells)
    for cells in ft_rows:
        if len(cells) > 8:
            row_type_text = cells[0].get_text(strip=True)
            pj, v, e, d, gf, gc = (cells[i].get_text(strip=True) for i in range(1, 7))
            data[f"{row_type_text.lower()}_pj"] = pj if pj else "N/A" # Simplified assignment
            data[f"{row_type_text.lower()}_v"] = v if v else "N/A"
            data[f"{row_type_text.lower()}_e"] = e if e else "N/A"
            data[f"{row_type_text.lower()}_d"] = d if d else "N/A"
            data[f"{row_type_text.lower()}_gf"] = gf if gf else "N/A"
            data[f"{row_type_text.lower()}_gc"] = gc if gc else "N/A"

            if row_type_text == "Total":
                data["total_pj"], data["total_v"], data["total_e"], data["total_d"], data["total_gf"], data["total_gc"] = pj,v,e,d,gf,gc
            elif row_type_text == "Home" and is_home_team_table_type:
                data["specific_pj"], data["specific_v"], data["specific_e"], data["specific_d"], data["specific_gf"], data["specific_gc"] = pj,v,e,d,gf,gc
            elif row_type_text == "Away" and not is_home_team_table_type:
                data["specific_pj"], data["specific_v"], data["specific_e"], data["specific_d"], data["specific_gf"], data["specific_gc"] = pj,v,e,d,gf,gc
    return data


def extract_final_score_of(soup):
    try:
        score_divs = soup.select('#mScore .end .score')
        if len(score_divs) == 2:
            hs = score_divs[0].text.strip()
            aws = score_divs[1].text.strip()
            if hs.isdigit() and aws.isdigit():
                return f"{hs}*{aws}", f"{hs}-{aws}"
    except Exception:
        pass
    return '?*?', "?-?"


def get_match_details_from_row_of(row_element, score_class_selector='score', source_table_type='h2h'):
    try:
        cells = row_element.find_all('td')
        if len(cells) < 12:
            return None
        league_id_hist_attr = row_element.get('name')
        home_idx, score_idx, away_idx, ah_idx = 2, 3, 4, 11
        home_tag = cells[home_idx].find('a')
        home = home_tag.text.strip() if home_tag else cells[home_idx].text.strip()
        away_tag = cells[away_idx].find('a')
        away = away_tag.text.strip() if away_tag else cells[away_idx].text.strip()
        score_cell_content = cells[score_idx].text.strip()
        score_span = cells[score_idx].find('span', class_=lambda x: x and score_class_selector in x)
        score_raw_text = score_span.text.strip() if score_span else score_cell_content
        score_m = re.match(r'(\d+-\d+)', score_raw_text)
        score_raw = score_m.group(1) if score_m else '?-?'
        score_fmt = score_raw.replace('-', '*') if score_raw != '?-?' else '?*?'
        ah_line_raw_text = cells[ah_idx].text.strip()
        ah_line_fmt = format_ah_as_decimal_string_of(ah_line_raw_text)
        if not home or not away:
            return None
        return {'home': home, 'away': away, 'score': score_fmt, 'score_raw': score_raw,
                'ahLine': ah_line_fmt, 'ahLine_raw': ah_line_raw_text,
                'matchIndex': row_element.get('index'), 'vs': row_element.get('vs'),
                'league_id_hist': league_id_hist_attr}
    except Exception:
        return None


def extract_h2h_data_of(soup, main_home_team_name, main_away_team_name, current_league_id):
    ah1, res1, res1_raw = '-', '?*?', '?-?'
    ah6, res6, res6_raw = '-', '?*?', '?-?'
    h2h_table = soup.find("table", id="table_v3")
    if not h2h_table:
        return ah1, res1, res1_raw, ah6, res6, res6_raw
    filtered_h2h_list = []
    if not main_home_team_name or not main_away_team_name:
        return ah1, res1, res1_raw, ah6, res6, res6_raw

    for row_h2h in h2h_table.find_all("tr", id=re.compile(r"tr3_\d+")):
        details = get_match_details_from_row_of(row_h2h, score_class_selector='fscore_3', source_table_type='h2h')
        if not details:
            continue
        if current_league_id and details.get('league_id_hist') and details.get('league_id_hist') != str(current_league_id):
            continue
        filtered_h2h_list.append(details)
    if not filtered_h2h_list:
        return ah1, res1, res1_raw, ah6, res6, res6_raw
    
    h2h_general_match = filtered_h2h_list[0]
    ah6 = h2h_general_match.get('ahLine', '-')
    res6 = h2h_general_match.get('score', '?*?')
    res6_raw = h2h_general_match.get('score_raw', '?-?')
    
    h2h_local_specific_match = None
    for d_h2h in filtered_h2h_list:
        if d_h2h.get('home','').lower() == main_home_team_name.lower() and \
           d_h2h.get('away','').lower() == main_away_team_name.lower():
            h2h_local_specific_match = d_h2h
            break
    if h2h_local_specific_match:
        ah1 = h2h_local_specific_match.get('ahLine', '-')
        res1 = h2h_local_specific_match.get('score', '?*?')
        res1_raw = h2h_local_specific_match.get('score_raw', '?-?')
    return ah1, res1, res1_raw, ah6, res6, res6_raw


def extract_comparative_match_of(soup_for_team_history, table_id_of_team_to_search, team_name_to_find_match_for, opponent_name_to_search, current_league_id, is_home_table):
    if not opponent_name_to_search or opponent_name_to_search == "N/A" or not team_name_to_find_match_for:
        return "-"
    table = soup_for_team_history.find("table", id=table_id_of_team_to_search)
    if not table:
        return "-"
    score_class_selector = 'fscore_1' if is_home_table else 'fscore_2'
    for row in table.find_all("tr", id=re.compile(rf"tr{table_id_of_team_to_search[-1]}_\d+")):
        details = get_match_details_from_row_of(row, score_class_selector=score_class_selector, source_table_type='hist')
        if not details:
            continue
        if current_league_id and details.get('league_id_hist') and details.get('league_id_hist') != str(current_league_id):
            continue
        home_hist = details.get('home','').lower()
        away_hist = details.get('away','').lower()
        team_main_lower = team_name_to_find_match_for.lower()
        opponent_lower = opponent_name_to_search.lower()
        if (team_main_lower == home_hist and opponent_lower == away_hist) or \
           (team_main_lower == away_hist and opponent_lower == home_hist):
            score = details.get('score', '?*?')
            ah_line_extracted = details.get('ahLine', '-')
            localia = 'H' if team_main_lower == home_hist else 'A'
            return f"{score}/{ah_line_extracted} {localia}".strip()
    return "-"
