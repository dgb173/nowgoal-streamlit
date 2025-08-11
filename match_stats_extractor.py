import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import re
import math

BASE_URL = "https://live19.nowgoal25.com"
ANALYZER_APP_URL = "http://localhost:8502"


def parse_ah_to_number_ng(ah_line_str: str):
    if not isinstance(ah_line_str, str):
        return None
    s = ah_line_str.strip().replace(' ', '')
    if not s or s in ['-', '?']:
        return None
    original_starts_with_minus = ah_line_str.strip().startswith('-')
    try:
        if '/' in s:
            parts = s.split('/')
            if len(parts) != 2:
                return None
            p1_str, p2_str = parts[0], parts[1]
            try:
                val1 = float(p1_str)
            except ValueError:
                return None
            try:
                val2 = float(p2_str)
            except ValueError:
                return None
            if val1 < 0 and not p2_str.startswith('-') and val2 > 0:
                val2 = -abs(val2)
            elif original_starts_with_minus and val1 == 0.0 and (p1_str == "0" or p1_str == "-0") and not p2_str.startswith('-') and val2 > 0:
                val2 = -abs(val2)
            return (val1 + val2) / 2.0
        else:
            return float(s)
    except ValueError:
        return None


def format_ah_as_decimal_string_ng(ah_line_str: str, for_sheets: bool = False):
    if not isinstance(ah_line_str, str) or not ah_line_str.strip() or ah_line_str.strip() in ['-', '?']:
        return ah_line_str.strip() if isinstance(ah_line_str, str) and ah_line_str.strip() in ['-', '?'] else '-'

    numeric_value = parse_ah_to_number_ng(ah_line_str)
    if numeric_value is None:
        return ah_line_str.strip() if ah_line_str.strip() in ['-', '?'] else '-'

    if numeric_value == 0.0:
        return "0"

    sign = -1 if numeric_value < 0 else 1
    abs_num = abs(numeric_value)
    mod_val = abs_num % 1

    if mod_val == 0.0:
        abs_rounded = abs_num
    elif mod_val == 0.25:
        abs_rounded = math.floor(abs_num) + 0.25
    elif mod_val == 0.5:
        abs_rounded = abs_num
    elif mod_val == 0.75:
        abs_rounded = math.floor(abs_num) + 0.75
    else:
        if mod_val < 0.25:
            abs_rounded = math.floor(abs_num)
        elif mod_val < 0.75:
            abs_rounded = math.floor(abs_num) + 0.5
        else:
            abs_rounded = math.ceil(abs_num)

    final_value_signed = sign * abs_rounded
    if final_value_signed == 0.0:
        output_str = "0"
    elif abs(final_value_signed - round(final_value_signed, 0)) < 1e-9:
        output_str = str(int(round(final_value_signed, 0)))
    elif abs(final_value_signed - (math.floor(final_value_signed) + 0.5)) < 1e-9:
        output_str = f"{final_value_signed:.1f}"
    elif abs(final_value_signed - (math.floor(final_value_signed) + 0.25)) < 1e-9 or abs(final_value_signed - (math.floor(final_value_signed) + 0.75)) < 1e-9:
        output_str = f"{final_value_signed:.2f}".replace(".25", ".25").replace(".75", ".75")
    else:
        output_str = f"{final_value_signed:.2f}"

    if for_sheets:
        return "'" + output_str.replace('.', ',') if output_str not in ['-', '?'] else output_str
    return output_str


@st.cache_data(ttl=300)
def fetch_main_page_soup_ng():
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(BASE_URL, headers=headers, timeout=15)
        response.raise_for_status()
        return BeautifulSoup(response.content, 'lxml')
    except requests.RequestException as e:
        st.error(f"Error al conectar con Nowgoal: {e}")
        return None


def get_upcoming_matches(soup):
    if not soup:
        return []

    upcoming_matches = []
    live_table = soup.find('table', id='table_live')
    if not live_table:
        return []

    match_rows = live_table.find_all('tr', class_='tds')
    for row in match_rows:
        status_cell = row.find('td', class_='status')
        status_text = status_cell.get_text(strip=True).lower() if status_cell else "ft"
        if status_text == '' or re.match(r'^\d{2}:\d{2}$', status_text):
            try:
                match_id = row.get('matchid')
                home_team = row.find('a', id=re.compile(r'team1_')).text.strip()
                away_team = row.find('a', id=re.compile(r'team2_')).text.strip()
                odds_cells = row.find_all('td', class_='oddstd')
                ah_raw = "N/A"
                if len(odds_cells) >= 2:
                    ah_p_tag = odds_cells[1].find('p', class_='odds1')
                    if ah_p_tag:
                        ah_raw = ah_p_tag.text.strip()
                ah_formatted = ah_raw
                upcoming_matches.append({
                    "ID": match_id,
                    "Local": home_team,
                    "Visitante": away_team,
                    "AH": ah_formatted
                })
            except AttributeError:
                continue
    return upcoming_matches


st.set_page_config(layout="wide", page_title="Panel de Partidos Futuros")
st.title("📋 Panel de Partidos por Empezar")
st.markdown(f"Partidos extraídos de `{BASE_URL}`. Haz clic en 'Analizar' para ver detalles.")

if st.button("Actualizar Lista de Partidos", type="primary"):
    st.cache_data.clear()

with st.spinner("Cargando partidos futuros..."):
    soup = fetch_main_page_soup_ng()
    if soup:
        matches = get_upcoming_matches(soup)
        if matches:
            st.success(f"Se encontraron {len(matches)} partidos por comenzar.")
            df = pd.DataFrame(matches)
            df['Acción'] = [None] * len(df)
            data_for_display = df.to_dict('records')
            col1, col2, col3, col4, col5 = st.columns([1, 3, 3, 1.5, 2])
            headers = ["ID", "Local", "Visitante", "Hándicap", "Analizar"]
            with col1:
                st.markdown(f"**{headers[0]}**")
            with col2:
                st.markdown(f"**{headers[1]}**")
            with col3:
                st.markdown(f"**{headers[2]}**")
            with col4:
                st.markdown(f"**{headers[3]}**")
            with col5:
                st.markdown(f"**{headers[4]}**")
            for item in data_for_display:
                with col1:
                    st.write(item['ID'])
                with col2:
                    st.write(item['Local'])
                with col3:
                    st.write(item['Visitante'])
                with col4:
                    st.write(item['AH'])
                with col5:
                    link_url = f"{ANALYZER_APP_URL}?match_id={item['ID']}"
                    st.link_button("Analizar en Nueva Pestaña", url=link_url, use_container_width=True)
        else:
            st.warning("No se encontraron partidos por comenzar en este momento.")
