# ==============================================================================
# SCRIPT DE ANÁLISIS COMPLETO Y FIEL - VERSIÓN FINAL PARA GOOGLE COLAB (v3.0)
# REPLICA 1:1 LA LÓGICA DEL SCRIPT ORIGINAL USANDO "DESCARGA ÚNICA"
# ==============================================================================

# --- PASO 1: IMPORTACIONES ESENCIALES ---
import requests
from bs4 import BeautifulSoup
import pandas as pd
import re
import math
import time
from IPython.display import display, Markdown
from concurrent.futures import ThreadPoolExecutor

# --- PASO 2: CONFIGURACIÓN ---
MATCH_ID = "2696131"
PLACEHOLDER_NODATA = "*(No disponible)*"
BASE_URL_OF = "https://live18.nowgoal25.com"

# --- PASO 3: TUS FUNCIONES HELPER (INTACTAS Y VALIDADAS) ---
def parse_ah_to_number_of(ah_line_str: str):
    # (Tu función de parseo original, es perfecta)
    if not isinstance(ah_line_str, str): return None
    s = ah_line_str.strip().replace(' ', '')
    if not s or s in ['-', '?']: return None
    original_starts_with_minus = ah_line_str.strip().startswith('-')
    try:
        if '/' in s:
            parts = s.split('/');
            if len(parts) != 2: return None
            p1_str, p2_str = parts[0], parts[1]
            try: val1 = float(p1_str)
            except ValueError: return None
            try: val2 = float(p2_str)
            except ValueError: return None
            if val1 < 0 and not p2_str.startswith('-') and val2 > 0: val2 = -abs(val2)
            elif original_starts_with_minus and val1 == 0.0 and (p1_str == "0" or p1_str == "-0") and not p2_str.startswith('-') and val2 > 0: val2 = -abs(val2)
            return (val1 + val2) / 2.0
        else: return float(s)
    except ValueError: return None

def format_ah_as_decimal_string_of(ah_line_str: str, for_sheets=False):
    # (Tu función de formateo original, es perfecta)
    if not isinstance(ah_line_str, str) or not ah_line_str.strip() or ah_line_str.strip() in ['-', '?']: return ah_line_str.strip() if isinstance(ah_line_str, str) and ah_line_str.strip() in ['-','?'] else '-'
    numeric_value = parse_ah_to_number_of(ah_line_str)
    if numeric_value is None: return ah_line_str.strip() if ah_line_str.strip() in ['-','?'] else '-'
    if numeric_value == 0.0: return "0"
    sign = -1 if numeric_value < 0 else 1
    abs_num = abs(numeric_value); mod_val = abs_num % 1
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
    elif abs(final_value_signed - (math.floor(final_value_signed) + 0.25)) < 1e-9 or abs(final_value_signed - (math.floor(final_value_signed) + 0.75)) < 1e-9: output_str = f"{final_value_signed:.2f}".replace(".25", ".25").replace(".75", ".75")
    else: output_str = f"{final_value_signed:.2f}"
    if for_sheets: return "'" + output_str.replace('.', ',') if output_str not in ['-','?'] else output_str
    return output_str


# --- PASO 4: RECONSTRUCCIÓN FIEL DE TUS FUNCIONES DE EXTRACCIÓN ---

class MatchAnalyzer:
    def __init__(self, match_id):
        self.match_id = match_id
        self.soup = None
        self.start_time = time.time()
        print(f"🚀 Iniciando análisis para el partido ID: {self.match_id}")
        self._fetch_main_page()

    def _fetch_main_page(self):
        url = f"{BASE_URL_OF}/match/h2h-{self.match_id}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36"}
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            self.soup = BeautifulSoup(response.text, 'lxml')
            print(f"✅ Página principal descargada y parseada en {time.time() - self.start_time:.2f}s")
        except requests.RequestException as e:
            print(f"❌ ERROR CRÍTICO AL DESCARGAR: {e}")

    def _get_details_from_row(self, row, source_table_type):
        cells = row.find_all(['td', 'th'])
        if len(cells) < 6: return None
        
        score_class_selector = 'fscore_3' if source_table_type == 'h2h' else ('fscore_1' if source_table_type == 'hist_v1' else 'fscore_2')
        score_span = cells[3].find('span', class_=score_class_selector)
        score_raw = re.search(r'(\d+-\d+)', score_span.text).group(1) if score_span and re.search(r'(\d+-\d+)', score_span.text) else '?-?'
        
        handicap_idx = 13 if source_table_type == 'h2h' else 11
        
        return {
            'home': cells[2].text.strip(), 'away': cells[4].text.strip(),
            'score': score_raw.replace('-', ':'), 'score_raw': score_raw,
            'ahLine': format_ah_as_decimal_string_of(cells[handicap_idx].get('data-o', cells[handicap_idx].text.strip()).strip() if len(cells) > handicap_idx else '-'),
            'ahLine_raw': cells[handicap_idx].get('data-o', cells[handicap_idx].text.strip()).strip() if len(cells) > handicap_idx else '-',
            'matchIndex': row.get('index'), 'league_id_hist': row.get('name'),
            'vs': row.get('vs'), 'row_obj': row
        }

    def _extract_table_to_df(self, table_id, source_type):
        table = self.soup.find('table', id=table_id)
        if not table: return pd.DataFrame()
        rows = table.find_all('tr', id=re.compile(rf'tr{table_id[-1]}_\d+'))
        data = [self._get_details_from_row(row, source_type) for row in rows]
        return pd.DataFrame([d for d in data if d])

    def run(self):
        if not self.soup: return

        # --- EXTRACCIÓN DE DATOS ---
        self.info = get_team_league_info_from_script_of(self.soup)
        self.standings_home = extract_standings_data_from_h2h_page_of(self.soup, self.info['home_name'])
        self.standings_away = extract_standings_data_from_h2h_page_of(self.soup, self.info['away_name'])
        self.final_score, _ = extract_final_score_of(self.soup)

        self.df_home = self._extract_table_to_df('table_v1', 'hist_v1')
        self.df_away = self._extract_table_to_df('table_v2', 'hist_v2')
        self.df_h2h = self._extract_table_to_df('table_v3', 'h2h')
        self.all_matches_df = pd.concat([self.df_home, self.df_away, self.df_h2h]).drop_duplicates(subset=['matchIndex']).reset_index(drop=True)

        # --- LÓGICA DE PARTIDOS ESPECÍFICOS ---
        self.last_home_in_league = self.df_home[self.df_home['league_id_hist'] == self.info['league_id']].iloc[0].to_dict() if not self.df_home[self.df_home['league_id_hist'] == self.info['league_id']].empty else None
        self.last_away_in_league = self.df_away[self.df_away['league_id_hist'] == self.info['league_id']].iloc[0].to_dict() if not self.df_away[self.df_away['league_id_hist'] == self.info['league_id']].empty else None
        self.last_overall_home = self.df_home.iloc[0].to_dict() if not self.df_home.empty else None
        self.last_overall_away = self.df_away.iloc[0].to_dict() if not self.df_away.empty else None

        # --- LÓGICA DE RIVALES Y H2H INDIRECTOS ---
        self.rival_a_info = self._get_rival_info_from_table(self.df_home)
        self.rival_b_info = self._get_rival_info_from_table(self.df_away)
        self.h2h_rivals_recientes = self._find_h2h_between_rivals(self.rival_a_info, self.rival_b_info)
        
        self.h2h_ultimos_rivales = self._find_h2h_between_rivals(
            self._get_opponent_info_from_match(self.last_overall_home, main_team_is_home=True),
            self._get_opponent_info_from_match(self.last_overall_away, main_team_is_home=False)
        )
        
        # --- LÓGICA DE PARTIDOS COMPARATIVOS ---
        self.comp_L_vs_UV_A = self._find_comparative(self.df_home, self.info['home_name'], self.last_away_in_league['home'] if self.last_away_in_league else None)
        self.comp_V_vs_UL_H = self._find_comparative(self.df_away, self.info['away_name'], self.last_home_in_league['away'] if self.last_home_in_league else None)

        # --- MÉTRICAS H2H DIRECTO ---
        if not self.df_h2h.empty:
            spec_h2h = self.df_h2h[self.df_h2h['home'].str.lower() == self.info['home_name'].lower()]
            self.h2h_direct_local = spec_h2h.iloc[0].to_dict() if not spec_h2h.empty else None
            self.h2h_direct_general = self.df_h2h.iloc[0].to_dict()
        else:
            self.h2h_direct_local, self.h2h_direct_general = None, None
            
        # --- ESTADÍSTICAS DE PROGRESIÓN (PARALELO) ---
        self._get_progression_stats()
        
        self.display_results()

    def _get_rival_info_from_table(self, df):
        if df.empty: return None
        rival_row = df[df['vs'] == '1']
        if not rival_row.empty:
            match = rival_row.iloc[0]
            return self._get_opponent_info_from_match(match, main_team_is_home=True)
        return None

    def _get_opponent_info_from_match(self, match, main_team_is_home):
        if match is None: return None
        opponent_name = match['away'] if main_team_is_home else match['home']
        links = match['row_obj'].find_all("a", onclick=re.compile(r'team\(\d+\)'))
        if len(links) > 1:
            opponent_tag = links[1] if main_team_is_home else links[0]
            if id_match := re.search(r"team\((\d+)\)", opponent_tag.get("onclick", "")):
                return {'id': id_match.group(1), 'name': opponent_name}
        return None

    def _find_h2h_between_rivals(self, rival_a, rival_b):
        if not rival_a or not rival_b: return {"status": "error", "resultado": "Faltan datos de rivales."}
        for _, match in self.all_matches_df.iterrows():
            links = match['row_obj'].find_all("a", onclick=re.compile(r'team\(\d+\)'))
            if len(links) > 1:
                home_id = re.search(r"team\((\d+)\)", links[0].get("onclick", "")).group(1)
                away_id = re.search(r"team\((\d+)\)", links[1].get("onclick", "")).group(1)
                if {home_id, away_id} == {rival_a['id'], rival_b['id']}:
                    return {"status": "found", **match.drop('row_obj').to_dict()}
        return {"status": "not_found", "resultado": f"No se encontró H2H entre {rival_a['name']} y {rival_b['name']}."}

    def _find_comparative(self, df, main_team, opponent):
        if df.empty or not opponent: return None
        for _, row in df.iterrows():
            if {main_team.lower(), opponent.lower()} == {row['home'].lower(), row['away'].lower()}:
                return row.drop('row_obj').to_dict()
        return None
        
    def _get_progression_stats(self):
        ids = {self.match_id}
        for item in [self.last_home_in_league, self.last_away_in_league, self.last_overall_home, self.last_overall_away, self.h2h_direct_local, self.h2h_direct_general]:
            if item and item.get('matchIndex'): ids.add(item['matchIndex'])
        if self.h2h_rivals_recientes.get('status') == 'found': ids.add(self.h2h_rivals_recientes.get('matchIndex'))
        if self.h2h_ultimos_rivales.get('status') == 'found': ids.add(self.h2h_ultimos_rivales.get('matchIndex'))
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            results = executor.map(get_match_progression_stats_data_helper, ids)
            self.prog_stats = {mid: stat for mid, stat in zip(ids, results) if stat is not None and not stat.empty}

    def display_results(self):
        # Muestra todos los resultados de forma estructurada
        display(Markdown(f"## 📊 Análisis: **{self.info['home_name']}** vs **{self.info['away_name']}**"))
        display(Markdown(f"🏆 **Liga:** {self.info['league_name']}"))
        
        display(Markdown("--- \n### 📈 Clasificación en Liga"))
        print(f"LOCAL: {self.standings_home['name']} [{self.standings_home['ranking']}] | Total: {self.standings_home['total_pj']} PJ, {self.standings_home['total_v']}-{self.standings_home['total_e']}-{self.standings_home['total_d']}")
        print(f"VISITANTE: {self.standings_away['name']} [{self.standings_away['ranking']}] | Total: {self.standings_away['total_pj']} PJ, {self.standings_away['total_v']}-{self.standings_away['total_e']}-{self.standings_away['total_d']}")
        
        display(Markdown("--- \n### ⚡ Rendimiento Reciente (Local vs Visitante) y H2H Indirecto"))
        print("\n**Último Local (en liga):**\n", pd.Series(self.last_home_in_league).drop('row_obj').to_string() if self.last_home_in_league else PLACEHOLDER_NODATA)
        print("\n**Último Visitante (en liga):**\n", pd.Series(self.last_away_in_league).drop('row_obj').to_string() if self.last_away_in_league else PLACEHOLDER_NODATA)
        print("\n**H2H Rivales Recientes:**\n", pd.Series(self.h2h_rivals_recientes).to_string() if self.h2h_rivals_recientes.get('status') == 'found' else self.h2h_rivals_recientes.get('resultado', 'Error'))
        
        display(Markdown("--- \n### ⚡ Rendimiento Último Partido (General) y H2H Indirecto"))
        print("\n**Último General (Local):**\n", pd.Series(self.last_overall_home).drop('row_obj').to_string() if self.last_overall_home else PLACEHOLDER_NODATA)
        print("\n**Último General (Visitante):**\n", pd.Series(self.last_overall_away).drop('row_obj').to_string() if self.last_overall_away else PLACEHOLDER_NODATA)
        print("\n**H2H Últimos Rivales:**\n", pd.Series(self.h2h_ultimos_rivales).to_string() if self.h2h_ultimos_rivales.get('status') == 'found' else self.h2h_ultimos_rivales.get('resultado', 'Error'))
        
        display(Markdown("--- \n### 🔁 Comparativas Indirectas Detalladas"))
        print(f"\n**{self.info['home_name']} vs. Últ. Rival de {self.info['away_name']}:**\n", pd.Series(self.comp_L_vs_UV_A).drop('row_obj').to_string() if self.comp_L_vs_UV_A else PLACEHOLDER_NODATA)
        print(f"\n**{self.info['away_name']} vs. Últ. Rival de {self.info['home_name']}:**\n", pd.Series(self.comp_V_vs_UL_H).drop('row_obj').to_string() if self.comp_V_vs_UL_H else PLACEHOLDER_NODATA)

        display(Markdown("--- \n### 🔰 Hándicaps y Resultados Clave (H2H Directos)"))
        print(f"\n**H2H Local en Casa:**\n", f"Resultado: {self.h2h_direct_local['score']}, AH: {self.h2h_direct_local['ahLine']}" if self.h2h_direct_local else PLACEHOLDER_NODATA)
        print(f"\n**H2H General:**\n", f"Resultado: {self.h2h_direct_general['score']}, AH: {self.h2h_direct_general['ahLine']}" if self.h2h_direct_general else PLACEHOLDER_NODATA)

        display(Markdown("--- \n### 👁️ Estadísticas de Progresión (Partidos Relevantes)"))
        for match_id, stats_df in self.prog_stats.items():
            print(f"\nEstadísticas para Partido ID: {match_id}")
            print(stats_df.to_string())
        
        end_time = time.time()
        total_time = end_time - self.start_time
        print("\n" + "="*60)
        print(f"⏱️ ANÁLISIS COMPLETO REALIZADO EN {total_time:.2f} SEGUNDOS")
        if total_time <= 10: print("🎉🎉🎉 ¡OBJETIVO DE BONUS CUMPLIDO! ¡ENHORABUENA! 🎉🎉🎉")

# Funciones auxiliares que se quedan fuera de la clase
def get_match_progression_stats_data_helper(match_id):
    if not match_id: return None
    url = f"{BASE_URL_OF}/match/live-{match_id}"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'lxml')
        stats = {title: {"Home": "-", "Away": "-"} for title in ["Shots", "Shots on Goal", "Attacks", "Dangerous Attacks"]}
        if tech_div := soup.find('div', id='teamTechDiv_detail'):
            for li in tech_div.find_all('li'):
                if (title_span := li.find('span', class_='stat-title')) and (title := title_span.get_text(strip=True)) in stats:
                    if len(values := li.find_all('span', class_='stat-c')) == 2:
                        stats[title]["Home"], stats[title]["Away"] = values[0].text.strip(), values[1].text.strip()
        df = pd.DataFrame([{"Estadistica_EN": name, "Casa": vals['Home'], "Fuera": vals['Away']} for name, vals in stats.items()])
        return df.set_index("Estadistica_EN") if not df.empty else None
    except requests.RequestException: return None


def get_team_league_info_from_script_of(soup):
    info = {k: "N/A" for k in ["home_id", "away_id", "league_id", "home_name", "away_name", "league_name"]}
    if script_tag := soup.find("script", string=re.compile(r"var _matchInfo =")):
        script_content = script_tag.string
        try:
            info["home_id"] = re.search(r"hId:\s*parseInt\('(\d+)'\)", script_content).group(1)
            info["away_id"] = re.search(r"gId:\s*parseInt\('(\d+)'\)", script_content).group(1)
            info["league_id"] = re.search(r"sclassId:\s*parseInt\('(\d+)'\)", script_content).group(1)
            info["home_name"] = re.search(r"hName:\s*'([^']*)'", script_content).group(1).replace("\\'", "'")
            info["away_name"] = re.search(r"gName:\s*'([^']*)'", script_content).group(1).replace("\\'", "'")
            info["league_name"] = re.search(r"lName:\s*'([^']*)'", script_content).group(1).replace("\\'", "'")
        except AttributeError: pass
    return info

def extract_standings_data_from_h2h_page_of(h2h_soup, target_team_name_exact):
    data = {"name": target_team_name_exact, "ranking": "N/A", "total_pj": "N/A", "total_v": "N/A", "total_e": "N/A", "total_d": "N/A", "total_gf": "N/A", "total_gc": "N/A", "specific_pj": "N/A", "specific_v": "N/A", "specific_e": "N/A", "specific_d": "N/A", "specific_gf": "N/A", "specific_gc": "N/A", "specific_type": "N/A"}
    if not h2h_soup or not target_team_name_exact: return data
    standings_section = h2h_soup.find("div", id="porletP4")
    if not standings_section: return data
    team_table_soup, is_home_table_type = (None, False)
    if home_div := standings_section.find("div", class_="home-div"):
        if target_team_name_exact.lower() in home_div.get_text(strip=True).lower():
            team_table_soup, is_home_table_type, data["specific_type"] = home_div.find("table", class_="team-table-home"), True, "Est. como Local (en Liga)"
    if not team_table_soup and (guest_div := standings_section.find("div", class_="guest-div")):
        if target_team_name_exact.lower() in guest_div.get_text(strip=True).lower():
            team_table_soup, data["specific_type"] = guest_div.find("table", class_="team-table-guest"), "Est. como Visitante (en Liga)"
    if not team_table_soup: return data
    if header_link := team_table_soup.find("tr", class_=re.compile(r"team-(home|guest)")).find("a"):
        full_text = header_link.get_text(separator=" ", strip=True)
        if name_match := re.search(r"]\s*(.*)", full_text): data["name"] = name_match.group(1).strip()
        if rank_match := re.search(r"\[(?:[^\]]+-)?(\d+)\]", full_text): data["ranking"] = rank_match.group(1)
    in_ft_section = False
    for row in team_table_soup.find_all("tr", align="center"):
        if th := row.find("th"):
            in_ft_section = "FT" in th.get_text(strip=True)
            if not in_ft_section: break
            continue
        if in_ft_section and len(cells := row.find_all("td")) > 6:
            row_type, stats_values = cells[0].get_text(strip=True), [cell.get_text(strip=True) or "N/A" for cell in cells[1:7]]
            pj, v, e, d, gf, gc = stats_values[:6]
            if row_type == "Total": data.update({"total_pj": pj, "total_v": v, "total_e": e, "total_d": d, "total_gf": gf, "total_gc": gc})
            elif (row_type == "Home" and is_home_table_type) or (row_type == "Away" and not is_home_table_type): data.update({"specific_pj": pj, "specific_v": v, "specific_e": e, "specific_d": d, "specific_gf": gf, "specific_gc": gc})
    return data
    
def extract_final_score_of(soup):
    if score_divs := soup.select('#mScore .end .score'):
        if len(score_divs) == 2 and (hs := score_divs[0].text.strip()).isdigit() and (aws := score_divs[1].text.strip()).isdigit():
            return f"{hs}:{aws}", f"{hs}-{aws}"
    return '?:?', "?-?"

# --- EJECUCIÓN ---
if __name__ == '__main__':
    analyzer = MatchAnalyzer(MATCH_ID)
    analyzer.run()
