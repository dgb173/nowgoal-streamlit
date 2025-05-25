# modules/nowgoal_scraper.py
import streamlit as st
import time
import json
import re
import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import gspread
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import random

# --- CONFIGURACIÓN ESPECÍFICA DEL SCRAPER (VALORES POR DEFECTO) ---
# Estos pueden ser sobrescritos por la UI en main_app.py
DEFAULT_MAX_WORKERS_SCRAPER = 2
DEFAULT_SELENIUM_TIMEOUT_SCRAPER = 90
DEFAULT_BATCH_SIZE_SCRAPER = 50

# Constantes del scraper
WORKER_START_DELAY = random.uniform(0.3, 0.8)
INTER_ID_SUBMIT_DELAY = 0.05
RETRY_DELAY_GSPREAD = 15
API_PAUSE_GSPREAD = 0.5
NOMBRE_SHEET = "Datos" # Usado en get_gsheets_client_and_sheet
NOMBRE_HOJA_NEG_CERO = "Visitantes"
NOMBRE_HOJA_POSITIVOS = "Locales"
OUTPUT_COLUMNS = [
    "AH_H2H_V", "AH_Act", "Res_H2H_V", "AH_L_H", "Res_L_H",
    "AH_V_A", "Res_V_A", "AH_H2H_G", "Res_H2H_G",
    "L_vs_UV_A", "V_vs_UL_H", "Stats_L", "Stats_V",
    "Fin", "G_i", "League", "match_id",
    "H2H_Opponents"
]

# --- COPIAR AQUÍ TODAS LAS FUNCIONES DEL SCRAPER ---
# get_gsheets_client_and_sheet (ya lo tienes, se puede mantener aquí o mover a un utils.py si se usa en más módulos)
# parse_ah_to_number
# format_ah_as_decimal_string
# get_chrome_options
# safe_int
# get_match_details_from_row
# extract_team_stats_from_summary
# extract_match_worker
# worker_task
# upload_data_to_sheet
# run_nowgoal_scraper (la función principal que orquesta el scraping)

# --- (INICIO DE FUNCIONES COPIADAS Y PEGADAS DEL CÓDIGO ANTERIOR) ---

@st.cache_resource(ttl=3600)
def get_gsheets_client_and_sheet(credentials_dict):
    # ... (código de get_gsheets_client_and_sheet de la respuesta anterior) ...
    # Modificado para que st.info/success/error se muestren en el sidebar o área principal
    # st.sidebar.info("--- 📊 Conectando a Google Sheets... ---")
    # ...
    # st.sidebar.success(f"✅ Conexión exitosa a la hoja '{NOMBRE_SHEET}'.")
    # ...
    # st.sidebar.error(f"❌ Error al conectar a GSheets (Intento {attempt + 1}/{retries}): {e}")
    # ...
    # st.sidebar.error("❌ Fallo crítico al conectar a Google Sheets...");
    # Adaptar los st.xxx para que no rompan si esta función es llamada desde fuera de un contexto de Streamlit si es necesario
    # O asegurar que solo se llame desde un contexto de Streamlit.
    # Por simplicidad, asumo que main_app.py la llama y los mensajes de st se mostrarán allí.

    # print("--- 📊 Conectando a Google Sheets... ---") # Usar print si st no está disponible o para logs
    retries = 3
    for attempt in range(retries):
        try:
            gc = gspread.service_account_from_dict(credentials_dict)
            sh = gc.open(NOMBRE_SHEET)
            # print(f"✅ Conexión exitosa a la hoja '{NOMBRE_SHEET}'.")
            return gc, sh
        except Exception as e:
            # print(f"❌ Error al conectar a GSheets (Intento {attempt + 1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(RETRY_DELAY_GSPREAD)
            else:
                # print("❌ Fallo crítico al conectar a Google Sheets.");
                return None, None

def parse_ah_to_number(ah_line_str: str):
    # ... (código de parse_ah_to_number de la respuesta anterior) ...
    if not isinstance(ah_line_str, str) or not ah_line_str.strip() or ah_line_str.strip() in ['-', '?', '']:
        return None
    s = ah_line_str.strip().replace(' ', '')
    if not s: return None
    original_starts_with_minus = s.startswith('-')
    try:
        if '/' in s:
            parts = s.split('/')
            if len(parts) != 2: return None
            try:
                val1 = float(parts[0])
                val2 = float(parts[1])
            except ValueError: return None
            if (parts[0] == "0" or parts[0] == "-0.0" or parts[0] == "+0.0") and (parts[1].startswith('-') or parts[1].startswith('+') or val2 != 0.0):
                return (val1 + val2) / 2.0
            return (val1 + val2) / 2.0
        else: return float(s)
    except ValueError: return None
    except Exception as e: return None

def format_ah_as_decimal_string(ah_line_str: str):
    # ... (código de format_ah_as_decimal_string de la respuesta anterior) ...
    if not isinstance(ah_line_str, str) or not ah_line_str.strip() or ah_line_str.strip() in ['-', '?', '']: return '-'
    numeric_value = parse_ah_to_number(ah_line_str)
    if numeric_value is None: return '-'
    if numeric_value == 0.0: return "0"
    sign = -1 if numeric_value < 0 else 1
    abs_num = abs(numeric_value)
    parte_entera = math.floor(abs_num)
    parte_decimal_original = round(abs_num - parte_entera, 4)
    epsilon = 1e-9
    if abs(parte_decimal_original - 0.25) < epsilon or abs(parte_decimal_original - 0.75) < epsilon:
        nueva_parte_decimal = 0.5
    else: nueva_parte_decimal = parte_decimal_original
    resultado_num_redondeado = parte_entera + nueva_parte_decimal
    final_value_signed = sign * resultado_num_redondeado
    if abs(final_value_signed - round(final_value_signed, 0)) < epsilon:
        return str(int(round(final_value_signed, 0)))
    else: return f"{final_value_signed:.1f}"


def get_chrome_options():
    # ... (código de get_chrome_options de la respuesta anterior) ...
    chrome_opts = Options()
    chrome_opts.add_argument('--headless')
    chrome_opts.add_argument('--no-sandbox')
    chrome_opts.add_argument('--disable-dev-shm-usage')
    chrome_opts.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36")
    chrome_opts.add_argument('--disable-blink-features=AutomationControlled')
    chrome_opts.add_argument("--disable-gpu")
    chrome_opts.add_argument('--blink-settings=imagesEnabled=false')
    prefs = {"profile.managed_default_content_settings.images": 2,
             "profile.default_content_setting_values.notifications": 2,
             "profile.default_content_setting_values.popups": 2}
    chrome_opts.add_experimental_option("prefs", prefs)
    chrome_opts.add_argument("--window-size=1280x720")
    return chrome_opts

def safe_int(value, default=0):
    # ... (código de safe_int de la respuesta anterior) ...
    try:
        cleaned = ''.join(filter(str.isdigit, str(value)))
        return int(cleaned) if cleaned else default
    except (ValueError, TypeError): return default

def get_match_details_from_row(row_element, score_class_selector='score'):
    # ... (código de get_match_details_from_row de la respuesta anterior) ...
    try:
        cells = row_element.find_all('td')
        if len(cells) < 12: return None
        home_idx, score_idx, away_idx, ah_idx = 2, 3, 4, 11
        home_tag = cells[home_idx].find('a')
        home = home_tag.text.strip() if home_tag else cells[home_idx].text.strip()
        away_tag = cells[away_idx].find('a')
        away = away_tag.text.strip() if away_tag else cells[away_idx].text.strip()
        score_span = cells[score_idx].find('span', class_=lambda x: x and score_class_selector in x)
        score_raw_text = score_span.text.strip() if score_span else cells[score_idx].text.strip()
        score_m = re.match(r'(\d+)-(\d+)', score_raw_text)
        score_raw = score_m.group(0) if score_m else '?-?'
        score_fmt = score_raw.replace('-', '*') if score_raw != '?-?' else '?*?'
        ah_line_raw_text = cells[ah_idx].text.strip()
        ah_line_fmt = format_ah_as_decimal_string(ah_line_raw_text)
        ah_line_num = parse_ah_to_number(ah_line_raw_text)
        league_id_hist = row_element.get('name')
        if not home or not away: return None
        return {'home': home, 'away': away, 'score': score_fmt, 'score_raw': score_raw,
                'ahLine': ah_line_fmt, 'ahLine_raw': ah_line_raw_text, 'ahLine_num': ah_line_num,
                'matchIndex': row_element.get('index'), 'vs': row_element.get('vs'),
                'league_id_hist': league_id_hist}
    except Exception as e: return None

def extract_team_stats_from_summary(soup_obj, table_selector, is_home_team):
    # ... (código de extract_team_stats_from_summary de la respuesta anterior) ...
    stats = {'nombre': 'N/A', 'total_matches': 0, 'total_w': 0, 'total_d': 0, 'total_l': 0,
             'total_gf': 0, 'total_ga': 0, 'total_rank': 'N/A', 'loc_aw_matches': 0,
             'loc_aw_w': 0, 'loc_aw_d': 0, 'loc_aw_l': 0, 'loc_aw_gf': 0, 'loc_aw_ga': 0,
             'loc_aw_label': 'Home' if is_home_team else 'Away'}
    try:
        table = soup_obj.select_one(table_selector)
        if not table: return None
        rows = table.find_all('tr')
        if len(rows) < 4: return None
        name_tag = rows[0].find('a')
        temp_name = name_tag.text.strip() if name_tag else rows[0].text.strip()
        stats['nombre'] = re.sub(r'^\[.*?\]\s*', '', temp_name).strip()
        total_row_idx = 2
        if len(rows) > total_row_idx:
            t_cells = rows[total_row_idx].find_all('td')
            if len(t_cells) > 8:
                 stats.update({'total_matches': safe_int(t_cells[1].text), 'total_w': safe_int(t_cells[2].text),
                               'total_d': safe_int(t_cells[3].text), 'total_l': safe_int(t_cells[4].text),
                               'total_gf': safe_int(t_cells[5].text), 'total_ga': safe_int(t_cells[6].text),
                               'total_rank': t_cells[8].text.strip() if t_cells[8].text.strip().isdigit() else 'N/A'})
        loc_aw_row_idx = 4
        if len(rows) > loc_aw_row_idx:
            la_cells = rows[loc_aw_row_idx].find_all('td')
            if len(la_cells) > 6:
                 label_text = la_cells[0].text.strip()
                 if (is_home_team and "Home" in label_text) or (not is_home_team and "Away" in label_text):
                     stats['loc_aw_label'] = label_text
                 stats.update({'loc_aw_matches': safe_int(la_cells[1].text), 'loc_aw_w': safe_int(la_cells[2].text),
                               'loc_aw_d': safe_int(la_cells[3].text), 'loc_aw_l': safe_int(la_cells[4].text),
                               'loc_aw_gf': safe_int(la_cells[5].text), 'loc_aw_ga': safe_int(la_cells[6].text)})
        return stats
    except Exception as e_stats_sum: return None

def extract_match_worker(driver_instance, mid, selenium_timeout_val, home_name_cache, away_name_cache):
    # ... (código de extract_match_worker de la respuesta anterior) ...
    # Asegúrate de que esta función NO use st.write directamente, sino que devuelva datos
    # para que la función run_nowgoal_scraper pueda manejarlos y usar st.write.
    # (El código de la respuesta anterior ya está bien en este aspecto)
    url = f"https://live16.nowgoal25.com/match/h2h-{mid}"
    html = None; soup = None; time.sleep(WORKER_START_DELAY)
    try:
        driver_instance.get(url)
        WebDriverWait(driver_instance, selenium_timeout_val).until(
             EC.any_of(EC.presence_of_element_located((By.CSS_SELECTOR, '#table_v3')),
                         EC.presence_of_element_located((By.CSS_SELECTOR, 'div.crumbs')),
                         EC.presence_of_element_located((By.CSS_SELECTOR, 'body[errorpage]'))))
        time.sleep(0.5)
        html = driver_instance.page_source
        if "match not found" in html.lower() or "evento no encontrado" in html.lower() or \
           "the match is not found" in html.lower() or '<body errorpage' in html.lower():
             return mid, 'not_found', url
        soup = BeautifulSoup(html, 'lxml')
    except Exception as e_load: return mid, 'load_error', (url, f"{type(e_load).__name__}: {str(e_load)[:100]}")
    if soup is None : return mid, 'load_error', (url, "Soup object is None after page load.")

    ah1, res1, res1Raw = '-', '?*?', '?-?'; ah_curr_str, goals_curr_str = '?', '?'; ah_curr_num = None
    res3, res3Raw = '-', '?-?'; ah4, res4, res4Raw = '-', '?*?', '?-?'; ah5, res5, res5Raw = '-', '?*?', '?-?'
    ah6, res6, res6Raw = '-', '?*?', '?-?'; comp7, comp8 = '-', '-'; h2h_opponents_data = '-'
    finalScoreFmt, finalScoreRaw = '?*?', "?-?"; localStatsStr, visitorStatsStr = "Stats L: N/A", "Stats V: N/A"
    league_name = 'League N/A'; current_league_id = None
    home_name_actual, away_name_actual = home_name_cache, away_name_cache
    try:
        crumbs_league_link = soup.select_one('div.crumbs a[href*="/leagueinfo/"]')
        if crumbs_league_link:
            league_name_temp = crumbs_league_link.text.strip()
            if league_name_temp: league_name = league_name_temp
            href_val = crumbs_league_link.get('href', '')
            id_match_href = re.search(r'leagueinfo/(\d+)', href_val)
            if id_match_href: current_league_id = id_match_href.group(1)
        if not current_league_id or league_name == 'League N/A':
            header_league_span = soup.select_one('span.LName span.nosclassLink')
            if header_league_span:
                league_name_temp_header = header_league_span.text.strip()
                if league_name_temp_header: league_name = league_name_temp_header
                if not current_league_id:
                    onclick_val = header_league_span.get('onclick', '')
                    id_match_onclick = re.search(r'leagueinfo/(\d+)', onclick_val)
                    if id_match_onclick: current_league_id = id_match_onclick.group(1)
        ah_raw, goals_raw = "?", "?"
        try:
            odds_row = soup.select_one('#liveCompareDiv #tr_o_1_8[name="earlyOdds"]') or \
                       soup.select_one('#liveCompareDiv #tr_o_1_31[name="earlyOdds"]') or \
                       soup.select_one('#tr_o_1_8[name="earlyOdds"]')
            if odds_row:
                cells = odds_row.find_all('td')
                if len(cells) > 3: ah_raw = cells[3].text.strip()
                if len(cells) > 9: goals_raw = cells[9].text.strip()
            ah_curr_num = parse_ah_to_number(ah_raw)
            ah_curr_str = format_ah_as_decimal_string(ah_raw)
            goals_curr_str = format_ah_as_decimal_string(goals_raw)
        except Exception as e_odds_cur: ah_curr_str, goals_curr_str = '?', '?'; ah_curr_num = None
        try:
            score_divs = soup.select('#mScore .end .score')
            if len(score_divs) == 2:
                hs, aws = score_divs[0].text.strip(), score_divs[1].text.strip()
                if hs.isdigit() and aws.isdigit(): finalScoreRaw = f"{hs}-{aws}"; finalScoreFmt = finalScoreRaw.replace('-', '*')
        except: pass
        try:
            home_name_tag_header = soup.select_one('div.fbheader div.home div.sclassName a') or soup.select_one('div.fbheader div.home div.sclassName')
            away_name_tag_header = soup.select_one('div.fbheader div.guest div.sclassName a') or soup.select_one('div.fbheader div.guest div.sclassName')
            if home_name_tag_header: home_name_actual = home_name_tag_header.text.strip()
            if away_name_tag_header: away_name_actual = away_name_tag_header.text.strip()
            if not home_name_actual or not away_name_actual:
                 ht_hist_tag = soup.select_one('#table_v1 a.team-home-f') or soup.select_one('#table_v1 .team-home a')
                 at_hist_tag = soup.select_one('#table_v2 a.team-away-f') or soup.select_one('#table_v2 .team-guest a')
                 if ht_hist_tag and not home_name_actual: home_name_actual = re.sub(r'^\[.*?\]\s*', '', ht_hist_tag.text.strip()).strip()
                 if at_hist_tag and not away_name_actual: away_name_actual = re.sub(r'^\[.*?\]\s*', '', at_hist_tag.text.strip()).strip()
            if not home_name_actual or not away_name_actual: return mid, 'parse_error', (url, "Missing team names")
            t1 = soup.select_one('#table_v1'); t2 = soup.select_one('#table_v2'); t3 = soup.select_one('#table_v3')
            home_history_rows = t1.select('tr[id^="tr1_"]') if t1 else []
            away_history_rows = t2.select('tr[id^="tr2_"]') if t2 else []
            h2h_history_rows = t3.select('tr[id^="tr3_"]') if t3 else []
        except Exception as e_teams: return mid, 'parse_error', (url, f"Error teams/tables: {e_teams}")
        h2h_v_match_details, h2h_ov_match_details = None, None; filtered_h2h_list = []
        for row_h2h in h2h_history_rows:
            d = get_match_details_from_row(row_h2h, 'fscore_3')
            if not d: continue
            if current_league_id and d.get('league_id_hist') and d.get('league_id_hist') != current_league_id: continue
            filtered_h2h_list.append(d)
        if filtered_h2h_list:
            h2h_ov_match_details = filtered_h2h_list[0]
            for d_h2h_f in filtered_h2h_list:
                if home_name_actual and d_h2h_f.get('home') == home_name_actual: h2h_v_match_details = d_h2h_f; break
        if h2h_v_match_details:
            ah1, res1, res1Raw = h2h_v_match_details.get('ahLine', '-'), h2h_v_match_details.get('score', '?*?'), h2h_v_match_details.get('score_raw', '?-?')
            res3, res3Raw = res1, res1Raw
        else: ah1, res1, res1Raw, res3, res3Raw = '-', '?*?', '?-?', '-', '?-?'
        if h2h_ov_match_details:
            is_different_from_v = not h2h_v_match_details or (h2h_v_match_details and h2h_ov_match_details.get('matchIndex') != h2h_v_match_details.get('matchIndex'))
            if is_different_from_v:
                ah6, res6, res6Raw = h2h_ov_match_details.get('ahLine', '-'), h2h_ov_match_details.get('score', '?*?'), h2h_ov_match_details.get('score_raw', '?-?')
                if not h2h_v_match_details and res3 == '-': res3, res3Raw = res6, res6Raw
            elif not h2h_v_match_details:
                ah6, res6, res6Raw = h2h_ov_match_details.get('ahLine', '-'), h2h_ov_match_details.get('score', '?*?'), h2h_ov_match_details.get('score_raw', '?-?')
                if res3 == '-': res3, res3Raw = res6, res6Raw
        last_home_details, last_home_opp = None, None
        for row_home in home_history_rows:
            if row_home.get('vs') == '1':
                d = get_match_details_from_row(row_home, 'fscore_1')
                if not d: continue
                if current_league_id and d.get('league_id_hist') and d.get('league_id_hist') != current_league_id: continue
                if home_name_actual and d.get('home') == home_name_actual: last_home_details = d; break
        if last_home_details:
            ah4, res4, res4Raw = last_home_details.get('ahLine', '-'), last_home_details.get('score', '?*?'), last_home_details.get('score_raw', '?-?')
            last_home_opp = last_home_details.get('away')
        last_away_details, last_away_opp_host = None, None
        for row_away in away_history_rows:
            if row_away.get('vs') == '1':
                d = get_match_details_from_row(row_away, 'fscore_2')
                if not d: continue
                if current_league_id and d.get('league_id_hist') and d.get('league_id_hist') != current_league_id: continue
                if away_name_actual and d.get('away') == away_name_actual: last_away_details = d; break
        if last_away_details:
            ah5, res5, res5Raw = last_away_details.get('ahLine', '-'), last_away_details.get('score', '?*?'), last_away_details.get('score_raw', '?-?')
            last_away_opp_host = last_away_details.get('home')
        comp7, comp8 = '-', '-'
        if last_away_opp_host and home_history_rows:
             for row_comp7 in home_history_rows:
                d = get_match_details_from_row(row_comp7, 'fscore_1')
                if not d: continue
                if current_league_id and d.get('league_id_hist') and d.get('league_id_hist') != current_league_id: continue
                loc_c7 = ''; ah_val_c7 = d.get('ahLine', '-')
                formatted_ah_c7 = ah_val_c7 if ah_val_c7 != '0.0' else '0'
                if d.get('home') == home_name_actual and d.get('away') == last_away_opp_host: loc_c7 = 'H'
                elif d.get('away') == home_name_actual and d.get('home') == last_away_opp_host: loc_c7 = 'A'
                if loc_c7: comp7 = f"{d.get('score', '?*?')}/{formatted_ah_c7} {loc_c7}".strip(); break
        if last_home_opp and away_history_rows:
            for row_comp8 in away_history_rows:
                d = get_match_details_from_row(row_comp8, 'fscore_2')
                if not d: continue
                if current_league_id and d.get('league_id_hist') and d.get('league_id_hist') != current_league_id: continue
                loc_c8 = ''; ah_val_c8 = d.get('ahLine', '-')
                formatted_ah_c8 = ah_val_c8 if ah_val_c8 != '0.0' else '0'
                if d.get('home') == away_name_actual and d.get('away') == last_home_opp: loc_c8 = 'H'
                elif d.get('away') == away_name_actual and d.get('home') == last_home_opp: loc_c8 = 'A'
                if loc_c8: comp8 = f"{d.get('score', '?*?')}/{formatted_ah_c8} {loc_c8}".strip(); break
        h2h_opponents_data_temp = '-'
        if last_home_opp and last_away_opp_host and h2h_history_rows:
            found_h2h_opp = False
            for row_h2h_opp in h2h_history_rows:
                d_h2h_opp = get_match_details_from_row(row_h2h_opp, 'fscore_3')
                if not d_h2h_opp: continue
                if current_league_id and d_h2h_opp.get('league_id_hist') and d_h2h_opp.get('league_id_hist') != current_league_id: continue
                ah_val = d_h2h_opp.get('ahLine', '-')
                formatted_ah = ah_val if ah_val != '0.0' else '0'
                if d_h2h_opp.get('home') == last_home_opp and d_h2h_opp.get('away') == last_away_opp_host:
                    h2h_opponents_data_temp = f"({d_h2h_opp.get('score', '?*?').replace('*','-')}/{formatted_ah} Rival de local en casa)"
                    found_h2h_opp = True; break
                elif d_h2h_opp.get('home') == last_away_opp_host and d_h2h_opp.get('away') == last_home_opp:
                    h2h_opponents_data_temp = f"({d_h2h_opp.get('score', '?*?').replace('*','-')}/{formatted_ah} Rival de visitante en casa)"
                    found_h2h_opp = True; break
            if found_h2h_opp: h2h_opponents_data = h2h_opponents_data_temp
        home_stats_sum = extract_team_stats_from_summary(soup, 'table.team-table-home', True)
        guest_stats_sum = extract_team_stats_from_summary(soup, 'table.team-table-guest', False)
        if home_stats_sum:
            localStatsStr = (f"🏆Rk:{home_stats_sum['total_rank']} 🏠{home_stats_sum['loc_aw_label']}\n"
                             f"🌍T:{home_stats_sum['total_matches']}|{home_stats_sum['total_w']}/{home_stats_sum['total_d']}/{home_stats_sum['total_l']}|{home_stats_sum['total_gf']}-{home_stats_sum['total_ga']}\n"
                             f"🏡L:{home_stats_sum['loc_aw_matches']}|{home_stats_sum['loc_aw_w']}/{home_stats_sum['loc_aw_d']}/{home_stats_sum['loc_aw_l']}|{home_stats_sum['loc_aw_gf']}-{home_stats_sum['loc_aw_ga']}")
        if guest_stats_sum:
            visitorStatsStr = (f"🏆Rk:{guest_stats_sum['total_rank']} ✈️{guest_stats_sum['loc_aw_label']}\n"
                               f"🌍T:{guest_stats_sum['total_matches']}|{guest_stats_sum['total_w']}/{guest_stats_sum['total_d']}/{guest_stats_sum['total_l']}|{guest_stats_sum['total_gf']}-{guest_stats_sum['total_ga']}\n"
                               f"🛫V:{guest_stats_sum['loc_aw_matches']}|{guest_stats_sum['loc_aw_w']}/{guest_stats_sum['loc_aw_d']}/{guest_stats_sum['loc_aw_l']}|{guest_stats_sum['loc_aw_gf']}-{guest_stats_sum['loc_aw_ga']}")
    except Exception as main_extract_e: return mid, 'parse_error', (url, f"Detailed parse error: {main_extract_e}")
    final_row_data = [ah1, ah_curr_str, res3, ah4, res4, ah5, res5, ah6, res6, comp7, comp8,
                      localStatsStr, visitorStatsStr, finalScoreFmt, goals_curr_str, league_name,
                      str(mid), h2h_opponents_data]
    formatted_final_row = []
    for v_format_item in final_row_data:
        val_str = str(v_format_item) if v_format_item is not None else '-'
        if re.fullmatch(r"^-?\d+(\.\d+)?$", val_str.strip()) and val_str not in ['-', '?', '?*?', 'N/A']:
            final_display_str_para_sheets = val_str.replace('.', ',')
            formatted_final_row.append("'" + final_display_str_para_sheets)
        else: formatted_final_row.append(val_str)
    if ah_curr_str == '?': return mid, 'skipped', None
    else: return mid, 'ok', (formatted_final_row, ah_curr_num)


def worker_task(mid_param, selenium_timeout_val, home_name_cache='N/A', away_name_cache='N/A'):
    # ... (código de worker_task de la respuesta anterior) ...
    driver = None
    try:
        opts = get_chrome_options()
        driver = webdriver.Chrome(options=opts) # Asegúrate que chromedriver esté en PATH o usa webdriver_manager
        result = extract_match_worker(driver, mid_param, selenium_timeout_val, home_name_cache, away_name_cache)
        return result
    except Exception as e_worker_init: return mid_param, 'load_error', ('driver_init', str(e_worker_init))
    finally:
        if driver:
            try:
                time.sleep(random.uniform(0.1, 0.3))
                driver.quit()
            except: pass

def upload_data_to_sheet(worksheet_name, data_rows, columns_list, sheet_handle, batch_size, api_pause, retry_delay_gs, progress_bar_slot=None):
    # ... (código de upload_data_to_sheet de la respuesta anterior) ...
    # Asegúrate de que usa st.write/info/success/error para la UI, no print.
    # Y usa el progress_bar_slot para la barra de progreso de Streamlit.
    # (El código de la respuesta anterior ya está bien en este aspecto)
    # Reemplazar st.progress(0, text=...) con progress_bar_slot.progress(...)
    # y st.empty() con progress_bar_slot.empty()
    ui_area = st.status(f"📤 Subiendo a '{worksheet_name}'...", expanded=True)

    if not data_rows:
        ui_area.success(f"✅ No hay datos para subir a '{worksheet_name}'.")
        ui_area.update(state="complete")
        return True

    try:
        df = pd.DataFrame(data_rows, columns=columns_list)
        if df.empty:
            ui_area.success(f"✅ DataFrame vacío, no hay nada para subir a '{worksheet_name}'.")
            ui_area.update(state="complete")
            return True
    except Exception as df_err:
        ui_area.error(f"❌ Error creando DataFrame para '{worksheet_name}': {df_err}")
        ui_area.update(state="error")
        return False

    ui_area.write(f"Preparando {len(df)} filas para '{worksheet_name}'...")
    upload_successful_sheet = True; ws = None; start_row_for_data = 1
    try:
        try:
            ws = sheet_handle.worksheet(worksheet_name)
            ui_area.write(f"Hoja '{worksheet_name}' encontrada.")
            list_of_lists = ws.get_all_values(); current_rows_with_content = len(list_of_lists)
            header_exists = False
            if current_rows_with_content > 0 and list_of_lists[0] == columns_list: header_exists = True; ui_area.write("Encabezado detectado.")
            elif current_rows_with_content > 0 and list_of_lists[0] != columns_list: ui_area.warning("Encabezado existente NO coincide.")
            else:
                ui_area.write("Hoja vacía. Escribiendo cabecera..."); ws.update('A1', [columns_list], value_input_option='RAW')
                ui_area.write("Cabecera escrita."); start_row_for_data = 2; time.sleep(api_pause / 2 or 0.5)
            if header_exists: start_row_for_data = current_rows_with_content + 1
            elif current_rows_with_content > 0 and not header_exists: start_row_for_data = current_rows_with_content + 1
        except gspread.exceptions.WorksheetNotFound:
            ui_area.warning(f"Hoja '{worksheet_name}' no encontrada. Creando...");
            ws = sheet_handle.add_worksheet(title=worksheet_name, rows=max(len(df) + 100, 200), cols=len(columns_list) + 5)
            ui_area.write(f"Hoja '{worksheet_name}' creada. Escribiendo cabecera..."); ws.update('A1', [columns_list], value_input_option='RAW')
            start_row_for_data = 2; time.sleep(api_pause / 2 or 0.5)
        except Exception as ws_err: ui_area.error(f"❌ Error worksheet '{worksheet_name}': {ws_err}"); ui_area.update(state="error"); return False
        if not ws: ui_area.update(state="error"); return False
        num_batches = math.ceil(len(df) / batch_size)
        ui_area.write(f"Subiendo {len(df)} filas en {num_batches} lotes a partir de fila ~{start_row_for_data}...")
        
        # Usar el slot pasado para la barra de progreso si existe
        current_progress_bar = progress_bar_slot if progress_bar_slot else st # Fallback a st si no se pasa slot

        if hasattr(current_progress_bar, 'progress'): # Check if it's a slot or st itself
            prog_bar_instance = current_progress_bar.progress(0, text=f"Subiendo a {worksheet_name}...")
        else:
            prog_bar_instance = st.progress(0, text=f"Subiendo a {worksheet_name}...")


        for i_batch in range(num_batches):
            batch_start_index = i_batch * batch_size; batch_end_index = min((i_batch + 1) * batch_size, len(df))
            batch_df = df.iloc[batch_start_index:batch_end_index]; values_to_upload = batch_df.values.tolist()
            current_gspread_start_row = start_row_for_data + batch_start_index
            end_col_letter = gspread.utils.rowcol_to_a1(1, len(columns_list)).replace('1',''); full_range_to_update = f"A{current_gspread_start_row}:{end_col_letter}{current_gspread_start_row + len(values_to_upload) - 1}"
            # ui_area.write(f"    Subiendo Lote {i_batch+1}/{num_batches} ({len(values_to_upload)} filas) a {full_range_to_update}...")
            prog_bar_instance.progress((i_batch) / num_batches, text=f"Subiendo a {worksheet_name}: Lote {i_batch+1}/{num_batches}...")
            try:
                ws.update(full_range_to_update, values_to_upload, value_input_option='USER_ENTERED'); # ui_area.write(" OK.")
                time.sleep(api_pause)
            except gspread.exceptions.APIError as api_e:
                 ui_area.error(f" ❌ Error API Lote {i_batch+1} ({api_e.response.status_code}). Mensaje: {str(api_e)[:150]}...")
                 upload_successful_sheet = False
                 if api_e.response.status_code == 429: # Rate limit
                    wait_time = retry_delay_gs * (1 + random.uniform(0.1, 0.5)); ui_area.warning(f"Límite API. Durmiendo {wait_time:.1f}s y reintentando...")
                    time.sleep(wait_time)
                    try:
                         ws.update(full_range_to_update, values_to_upload, value_input_option='USER_ENTERED'); ui_area.write(f"Reintento Lote {i_batch+1} OK.")
                         upload_successful_sheet = True; time.sleep(api_pause + 0.5)
                    except Exception as retry_e: ui_area.error(f"Reintento Lote {i_batch+1} fallido: {retry_e}"); upload_successful_sheet = False; break
                 else: break
            except Exception as e_upload: ui_area.error(f"Error Lote {i_batch+1}: {type(e_upload).__name__} - {e_upload}"); upload_successful_sheet = False; break
        prog_bar_instance.progress(1.0, text=f"Subida a {worksheet_name} completada.")
        time.sleep(0.5) # Pequeña pausa para que el mensaje "completada" se vea
        if hasattr(current_progress_bar, 'empty'): # Si es un slot, vaciarlo
            current_progress_bar.empty()


    except Exception as e_outer: ui_area.error(f"❌ Error fatal subida para '{worksheet_name}': {e_outer}"); upload_successful_sheet = False
    
    if upload_successful_sheet and not df.empty : ui_area.success(f"✅ Subida a '{worksheet_name}' completada ({len(df)} filas).")
    elif not upload_successful_sheet and not df.empty: ui_area.error(f"❌ Subida a '{worksheet_name}' con errores.")
    
    if upload_successful_sheet: ui_area.update(state="complete")
    else: ui_area.update(state="error")
    return upload_successful_sheet


def run_nowgoal_scraper(gsheet_sh_handle, extraction_ranges, max_workers, batch_size, selenium_timeout):
    # ... (código de run_nowgoal_scraper de la respuesta anterior) ...
    # Asegúrate de que usa st.write/info/success/error para la UI, no print.
    # (El código de la respuesta anterior ya está bien en este aspecto)
    total_processed_ranges = 0; count_ok, count_skipped, count_not_found, count_load_error, count_parse_error = 0,0,0,0,0
    failed_mids = {'not_found': [], 'load': [], 'parse': []}; ranges_upload_success = {}
    st.write(f"--- 🚀 Iniciando Extracción con {max_workers} Workers ---")
    global_start_time = time.time()
    total_ids_all_ranges = sum(abs(r['start_id'] - r['end_id']) + 1 for r in extraction_ranges if r['start_id'] >= r['end_id'])
    
    # Crear placeholders para el progreso general en la UI
    overall_progress_text_slot = st.empty()
    overall_progress_bar_slot = st.progress(0.0)
    processed_ids_overall_count = 0

    for range_idx, range_info in enumerate(extraction_ranges):
        range_start_time = time.time(); total_processed_ranges += 1
        start_id, end_id = range_info.get('start_id'), range_info.get('end_id')
        label = range_info.get('label', f"Rango {range_idx + 1}")
        if not isinstance(start_id, int) or not isinstance(end_id, int) or start_id < end_id:
            st.error(f"Error Config Rango '{label}': start({start_id}) >= end({end_id}). Saltando."); ranges_upload_success[label] = {'neg_zero': False, 'pos': False, 'skipped_config': True}; continue
        
        st.markdown(f"--- \n### 🔍 Procesando Rango {range_idx + 1}/{len(extraction_ranges)}: '{label}' (IDs: {start_id} a {end_id})")
        rows_neg_zero_range, rows_pos_range = [], []; ids_to_process = list(range(start_id, end_id - 1, -1))
        total_ids_in_range = len(ids_to_process); processed_count_range = 0; current_successful_range = 0
        st.write(f"   Rango '{label}': {total_ids_in_range} IDs a procesar...")
        
        range_status_slot = st.status(f"Procesando Rango '{label}'...", expanded=True)
        range_progress_bar_in_status = range_status_slot.progress(0)

        futures = {}; counter_lock = threading.Lock()
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix='SeleniumWorker') as executor:
            for i, mid_exec in enumerate(ids_to_process):
                future = executor.submit(worker_task, mid_exec, selenium_timeout) # No pasamos caches de nombres aquí
                futures[future] = mid_exec; time.sleep(INTER_ID_SUBMIT_DELAY)
            for future_item in as_completed(futures):
                processed_count_range += 1; processed_ids_overall_count +=1
                mid_completed = futures[future_item]
                try:
                    f_mid, status, result_data = future_item.result()
                    with counter_lock:
                        if status == 'ok':
                            count_ok += 1; current_successful_range += 1
                            row_data, ah_act_n = result_data
                            if ah_act_n is None or ah_act_n <= 0: rows_neg_zero_range.append(row_data)
                            else: rows_pos_range.append(row_data)
                        elif status == 'skipped': count_skipped += 1
                        elif status == 'not_found': count_not_found += 1; failed_mids['not_found'].append(f_mid)
                        elif status == 'load_error': count_load_error += 1; failed_mids['load'].append(f_mid); range_status_slot.warning(f"MID {f_mid} Load Error: {result_data}")
                        elif status == 'parse_error': count_parse_error += 1; failed_mids['parse'].append(f_mid); range_status_slot.warning(f"MID {f_mid} Parse Error: {result_data}")
                    
                    # Actualizar progreso del rango
                    percentage_range = processed_count_range / total_ids_in_range if total_ids_in_range > 0 else 0
                    range_progress_bar_in_status.progress(int(percentage_range * 100))
                    range_status_slot.caption(f"Rango '{label}': {processed_count_range}/{total_ids_in_range} (OK: {current_successful_range})")

                    # Actualizar progreso general
                    overall_percentage = processed_ids_overall_count / total_ids_all_ranges if total_ids_all_ranges > 0 else 0
                    overall_progress_bar_slot.progress(overall_percentage)
                    overall_progress_text_slot.text(f"Progreso Total: {processed_ids_overall_count}/{total_ids_all_ranges} IDs ({overall_percentage:.1%})")

                except Exception as exc_future:
                     with counter_lock: count_load_error += 1; failed_mids['load'].append(mid_completed)
                     range_status_slot.error(f'Error Hilo MID {mid_completed}: {exc_future}')
        
        range_status_slot.success(f"Extracción Rango '{label}' completada. ({(time.time() - range_start_time):.2f}s)")
        range_status_slot.update(state="complete", expanded=False)
        st.write(f"Resultados OK Rango '{label}': {len(rows_neg_zero_range)} (AH<=0), {len(rows_pos_range)} (AH>0)")
        
        # Slots para las barras de progreso de subida
        upload_neg_progress_slot = st.empty()
        upload_pos_progress_slot = st.empty()

        succ_neg = upload_data_to_sheet(NOMBRE_HOJA_NEG_CERO, rows_neg_zero_range, OUTPUT_COLUMNS, gsheet_sh_handle, batch_size, API_PAUSE_GSPREAD, RETRY_DELAY_GSPREAD, upload_neg_progress_slot)
        succ_pos = upload_data_to_sheet(NOMBRE_HOJA_POSITIVOS, rows_pos_range, OUTPUT_COLUMNS, gsheet_sh_handle, batch_size, API_PAUSE_GSPREAD, RETRY_DELAY_GSPREAD, upload_pos_progress_slot)
        ranges_upload_success[label] = {'neg_zero': succ_neg, 'pos': succ_pos, 'skipped_config': False}
        if range_idx < len(extraction_ranges) - 1: st.info(f"Pausando 5s antes del siguiente rango..."); time.sleep(5)

    overall_progress_bar_slot.empty(); overall_progress_text_slot.empty() # Limpiar al final
    
    # --- RESUMEN FINAL ---
    st.markdown(f"\n{'='*60}\n## ✨ Proceso Completado ✨\n{'='*60}")
    global_end_time = time.time(); total_duration = global_end_time - global_start_time
    st.header("📊 Resumen General"); st.metric(label="Tiempo Total", value=f"{total_duration:.2f}s")
    st.info(f"Config: {len(extraction_ranges)} rangos, Workers={max_workers}, Timeout={selenium_timeout}s")
    col1_res, col2_res = st.columns(2)
    col1_res.success(f"**Total OK:** {count_ok}"); col2_res.error(f"**Total Fallos/Saltos:** {count_skipped + count_not_found + count_load_error + count_parse_error}")
    st.markdown("---"); st.subheader("⚠️ Detalles de Problemas:");
    st.warning(f"Saltados (AH='?'): {count_skipped}"); st.error(f"No Encontrados: {count_not_found}")
    st.error(f"Errores Carga: {count_load_error}"); st.error(f"Errores Parseo: {count_parse_error}")
    if any(failed_mids.values()):
        with st.expander("Ver MIDs con Errores"):
            for err_type, id_list in failed_mids.items():
                if id_list: st.write(f"**{err_type.replace('_',' ').capitalize()} ({len(id_list)}):**"); st.json(id_list)
    st.markdown("---"); st.subheader("✅/❌ Subida por rango:"); overall_up_success = True
    for lbl, stat in ranges_upload_success.items():
        if stat.get('skipped_config', False): st.warning(f"Rango '{lbl}': ⚠️ Saltado (Config)"); overall_up_success = False
        else:
            neg_ok_val, pos_ok_val = stat.get('neg_zero', False), stat.get('pos', False); stat_str = "❓"
            if neg_ok_val and pos_ok_val: stat_str = "✅ OK Ambas"
            elif neg_ok_val and not pos_ok_val: stat_str = "⚠️ Fallo Positivos"; overall_up_success = False
            elif not neg_ok_val and pos_ok_val: stat_str = "⚠️ Fallo Neg/Cero"; overall_up_success = False
            else: stat_str = "❌ Fallo Ambas"; overall_up_success = False
            st.write(f"Rango '{lbl}': [{stat_str}]")
    st.markdown(f"\n{'='*60}")
    if overall_up_success and (count_not_found + count_load_error + count_parse_error == 0) and count_skipped == 0: st.balloons(); st.success("🎉🎉 ¡Proceso OK! Revisa hojas.")
    elif overall_up_success : st.warning("⚠️ Proceso completado (Subidas OK), PERO hubo saltos o fallos.")
    else: st.error("❌❌ Proceso CON ERRORES en extracción Y/O subida.")


# --- (FIN DE FUNCIONES COPIADAS Y PEGADAS) ---


# --- INTERFAZ DE USUARIO PARA EL SCRAPER DE NOWGOAL (LLAMADA DESDE MAIN_APP.PY) ---
def display_nowgoal_scraper_ui(gsheet_sh_handle): # Recibe el handle de la hoja
    st.header("1️⃣ Extractor de Datos de Partidos (Nowgoal)")
    st.markdown("""
    Introduce los rangos de IDs de partidos que deseas extraer.
    Cada rango debe estar en el formato `start_id,end_id,EtiquetaDelRango` (cada rango en una nueva línea).
    *Ejemplo:*
    ```
    2775557,2775557,ID Prueba Individual
    2654543,2654043,Lote de Prueba Corto
    ```
    Asegúrate que `start_id` sea mayor o igual que `end_id`.
    """)

    default_id_ranges = "2775557,2775557,ID Ejemplo Singular\n2610938,2610711,Otro Ejemplo"
    id_ranges_input = st.text_area(
        "📝 Rangos de IDs de Partidos:",
        value=default_id_ranges,
        height=100, # Más compacto
        help="Un rango por línea: start_id,end_id,Etiqueta"
    )

    st.sidebar.subheader("⚙️ Config. Scraper Nowgoal")
    max_workers_slider = st.sidebar.slider(
        "Número de Workers Selenium", 1, 8, DEFAULT_MAX_WORKERS_SCRAPER,
        key="nowgoal_workers",
        help="Más workers = más rápido, pero más recursos y riesgo de bloqueo."
    )
    batch_size_slider = st.sidebar.number_input(
        "Tamaño Lote Subida GSheets", min_value=10, max_value=500, value=DEFAULT_BATCH_SIZE_SCRAPER, step=10,
        key="nowgoal_batchsize",
        help="Filas a subir a GSheets por operación API."
    )
    selenium_timeout_slider = st.sidebar.number_input(
        "Timeout Selenium (segundos)", min_value=30, max_value=300, value=DEFAULT_SELENIUM_TIMEOUT_SCRAPER, step=10,
        key="nowgoal_timeout",
        help="Tiempo máximo de espera para carga de página/elemento."
    )

    if st.button("🚀 Iniciar Extracción de Nowgoal", type="primary", key="start_nowgoal_scraping"):
        if not id_ranges_input.strip():
            st.warning("⚠️ Introduce al menos un rango de IDs.")
            return

        parsed_ranges = []
        for line_num, line in enumerate(id_ranges_input.strip().split('\n')):
            parts = [p.strip() for p in line.split(',')]
            if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
                try:
                    parsed_ranges.append({
                        'start_id': int(parts[0]), 'end_id': int(parts[1]), 'label': parts[2]
                    })
                except ValueError:
                    st.error(f"Error línea {line_num+1}: IDs deben ser números. Línea: '{line}'")
                    return
            elif line.strip(): # Ignorar líneas vacías pero advertir sobre las mal formateadas
                st.error(f"Error línea {line_num+1}: Formato inválido. Usa `start_id,end_id,Etiqueta`. Línea: '{line}'")
                return
        
        if not parsed_ranges:
            st.warning("⚠️ No se encontraron rangos de IDs válidos para procesar.")
            return

        if not gsheet_sh_handle:
            st.error("❌ Conexión a Google Sheets no disponible. No se puede iniciar el scraping.")
            return

        st.info("🎉 ¡Iniciando proceso de extracción de datos de Nowgoal!")
        run_nowgoal_scraper(
            gsheet_sh_handle,
            parsed_ranges,
            max_workers_slider,
            batch_size_slider,
            selenium_timeout_slider
        )
