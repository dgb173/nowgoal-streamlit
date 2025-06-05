# modules/match_stats_extractor.py

import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd

# Función interna para la extracción de datos
def _get_match_stats_data(match_id: str) -> pd.DataFrame | None:
    """
    Navega a la URL del partido en nowgoal25.com, extrae las estadísticas
    de disparos, disparos a puerta, ataques y ataques peligrosos,
    y devuelve un pandas.DataFrame con los resultados.
    Los valores se mantienen como strings (pudiendo ser '-' si no hay dato).
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

    # Mantén los nombres originales en inglés para la extracción, ya que así vienen de la web
    # El orden aquí no importa tanto como el orden de visualización posterior
    stat_titles_of_interest = {
        "Shots": {"Home": "-", "Away": "-"},
        "Shots on Goal": {"Home": "-", "Away": "-"},
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
                        if stat_title in stat_titles_of_interest: # Comprueba si es una de las que nos interesa
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
    # Aquí usamos los nombres en inglés porque son las claves del diccionario
    for stat_name_en, values in stat_titles_of_interest.items():
        table_rows.append({
            "Estadística_EN": stat_name_en, # Guardamos el nombre en inglés como clave
            "Casa": values['Home'],
            "Fuera": values['Away']
        })
    
    df = pd.DataFrame(table_rows)
    # Usamos la columna con nombres en inglés como índice para facilitar la búsqueda ordenada
    if not df.empty:
        df = df.set_index("Estadística_EN")
    return df

# Función principal para la UI de Streamlit de esta característica
def display_match_stats_extractor_ui():
    """
    Muestra la interfaz de usuario para el extractor de estadísticas de partido
    en la aplicación Streamlit, con formato de "línea de progresión" y colores.
    """
    st.header("⚽ Extractor de Estadísticas de Partido")
    st.write("Introduce el ID del partido de [nowgoal25.com](https://live18.nowgoal25.com) para ver sus estadísticas clave.")

    match_id_input = st.text_input("ID del Partido (ej: 2702779):", value="2702779", key="match_id_input_stats")

    if st.button("Obtener Estadísticas", key="get_stats_button"):
        if match_id_input:
            with st.spinner("Buscando estadísticas... Esto puede tardar un momento."):
                stats_df = _get_match_stats_data(match_id_input)

                if stats_df is not None:
                    if not stats_df.empty:
                        st.success(f"Estadísticas para el partido ID: **{match_id_input}**")
                        
                        # Definimos el orden deseado y los nombres en español para mostrar
                        # Las claves son los nombres en inglés tal como están en el índice del DataFrame
                        ordered_stats_display = {
                            "Shots": "Disparos",
                            "Shots on Goal": "Disparos a Puerta",
                            "Attacks": "Ataques",
                            "Dangerous Attacks": "Ataques Peligrosos"
                        }
                        
                        # Encabezados de la "tabla"
                        col1, col2, col3 = st.columns([2, 3, 2]) # Casa, Estadística, Fuera
                        with col1:
                            st.markdown("<p style='font-weight:bold;'>Local</p>", unsafe_allow_html=True)
                        with col2:
                            st.markdown("<p style='text-align:center; font-weight:bold;'>Estadística</p>", unsafe_allow_html=True)
                        with col3:
                            st.markdown("<p style='text-align:right; font-weight:bold;'>Visitante</p>", unsafe_allow_html=True)
                        st.markdown("---") # Línea separadora

                        for stat_key_en, stat_name_es in ordered_stats_display.items():
                            if stat_key_en in stats_df.index:
                                home_val_str = stats_df.loc[stat_key_en, 'Casa']
                                away_val_str = stats_df.loc[stat_key_en, 'Fuera']

                                # Convertir a números para comparación, tratando '-' como 0
                                try:
                                    home_val_num = int(home_val_str)
                                except ValueError:
                                    home_val_num = 0 # Si es '-' o no numérico, se compara como 0
                                
                                try:
                                    away_val_num = int(away_val_str)
                                except ValueError:
                                    away_val_num = 0 # Si es '-' o no numérico, se compara como 0

                                home_color = "black"
                                away_color = "black"

                                if home_val_num > away_val_num:
                                    home_color = "green"
                                    away_color = "red"
                                elif away_val_num > home_val_num:
                                    away_color = "green"
                                    home_color = "red"
                                # Si son iguales (incluyendo 0 vs 0 si ambos eran '-'), se quedan en negro

                                # Usar columnas para alinear
                                col1, col2, col3 = st.columns([2, 3, 2]) # Casa, Estadística, Fuera
                                with col1:
                                    st.markdown(f'<p style="font-weight:bold; color:{home_color};">{home_val_str}</p>', unsafe_allow_html=True)
                                with col2:
                                    st.markdown(f'<p style="text-align:center;">{stat_name_es}</p>', unsafe_allow_html=True)
                                with col3:
                                    st.markdown(f'<p style="text-align:right; font-weight:bold; color:{away_color};">{away_val_str}</p>', unsafe_allow_html=True)
                            else:
                                st.warning(f"No se encontró la estadística: {stat_name_es} ({stat_key_en})")
                        
                    else:
                        st.warning(f"No se pudieron extraer estadísticas para el partido ID: **{match_id_input}**. "
                                   "La página no contenía los datos esperados o el DataFrame está vacío.")
                        # Muestra el DataFrame vacío si es el caso, para depuración
                        st.dataframe(stats_df, use_container_width=True)
        else:
            st.warning("Por favor, introduce un ID de partido.")

# Para probar este módulo directamente (opcional)
if __name__ == "__main__":
    display_match_stats_extractor_ui()
