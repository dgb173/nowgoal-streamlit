# modules/match_stats_extractor.py

import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd

# Función interna para la extracción de datos
def _get_match_stats_data(match_id: str) -> pd.DataFrame | None:
    """
    Navega a la URL del partido en nowgoal25.com, extrae las estadísticas
    de disparos a puerta, disparos, ataques y ataques peligrosos,
    y devuelve un pandas.DataFrame con los resultados.
    """
    base_url = "https://live18.nowgoal25.com/match/live-"
    full_url = f"{base_url}{match_id}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "en-US,en;q=0.9",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

    stat_titles_of_interest = {
        "Shots on Goal": {"Home": "-", "Away": "-"},
        "Shots": {"Home": "-", "Away": "-"},
        "Attacks": {"Home": "-", "Away": "-"},
        "Dangerous Attacks": {"Home": "-", "Away": "-"},
    }

    try:
        response = requests.get(full_url, headers=headers, timeout=15)
        response.raise_for_status()
        html_content = response.text

        soup = BeautifulSoup(html_content, 'lxml')
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
                                home_value = values[0].get_text(strip=True)
                                away_value = values[1].get_text(strip=True)
                                stat_titles_of_interest[stat_title]["Home"] = home_value
                                stat_titles_of_interest[stat_title]["Away"] = away_value
    except requests.exceptions.RequestException as e:
        st.error(f"Error al obtener la página web para ID {match_id}: {e}. El sitio podría estar bloqueando el acceso o hay un problema de red.")
        return None
    except Exception as e:
        st.error(f"Ocurrió un error inesperado al procesar la página para ID {match_id}: {e}.")
        return None

    table_rows = []
    for stat_name, values in stat_titles_of_interest.items():
        table_rows.append({
            "Estadística": stat_name,
            "Casa": values['Home'],
            "Fuera": values['Away']
        })
    
    df = pd.DataFrame(table_rows)
    return df

# Función principal para la UI de Streamlit de esta característica
def display_match_stats_extractor_ui():
    """
    Muestra la interfaz de usuario para el extractor de estadísticas de partido
    en la aplicación Streamlit.
    """
    st.header("⚽ Extractor de Estadísticas de Partido")
    st.write("Introduce el ID del partido de [nowgoal25.com](https://live18.nowgoal25.com) para ver sus estadísticas clave de ataque y ofensivas.")

    match_id_input = st.text_input("ID del Partido (ej: 2702779):", value="2702779", key="match_id_input_stats")

    if st.button("Obtener Estadísticas", key="get_stats_button"):
        if match_id_input:
            with st.spinner("Buscando estadísticas... Esto puede tardar un momento debido a la conexión o al procesamiento del sitio."):
                stats_df = _get_match_stats_data(match_id_input)

                if stats_df is not None:
                    if not stats_df.empty:
                        st.success(f"Estadísticas para el partido ID: **{match_id_input}**")
                        st.dataframe(stats_df.set_index('Estadística'), use_container_width=True) 
                    else:
                        st.warning(f"No se pudieron extraer estadísticas para el partido ID: **{match_id_input}**. "
                                   "La página no contenía los datos esperados.")
                        st.dataframe(stats_df.set_index('Estadística'), use_container_width=True)
        else:
            st.warning("Por favor, introduce un ID de partido.")
