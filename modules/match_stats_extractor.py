# nowgoal_scraper.py
import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import re

# URL del sitio a scrapear
BASE_URL = "https://live19.nowgoal25.com"

@st.cache_data(ttl=300) # Cache por 5 minutos para no sobrecargar el servidor
def fetch_page_content():
    """
    Obtiene el contenido HTML de la página principal y lo parsea con BeautifulSoup.
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(BASE_URL, headers=headers, timeout=15)
        response.raise_for_status()  # Lanza un error si la petición falla
        soup = BeautifulSoup(response.content, 'lxml')
        return soup
    except requests.RequestException as e:
        st.error(f"Error al conectar con Nowgoal: {e}")
        return None

def parse_match_data(soup):
    """
    Parsea el objeto BeautifulSoup para extraer la información de cada partido.
    """
    if not soup:
        return []

    match_list = []
    # La tabla con id 'table_live' contiene todos los partidos
    live_table = soup.find('table', id='table_live')
    if not live_table:
        st.warning("No se encontró la tabla de partidos en la página.")
        return []

    # Cada fila de partido tiene la clase 'tds' y un atributo 'matchid'
    match_rows = live_table.find_all('tr', class_='tds')

    for row in match_rows:
        try:
            match_id = row.get('matchid')
            if not match_id:
                continue

            # Extraer nombres de equipos
            # El nombre del equipo local está en un enlace <a> con un id que empieza con 'team1_'
            home_team_tag = row.find('a', id=re.compile(r'team1_\d+'))
            home_team = home_team_tag.text.strip() if home_team_tag else "N/A"

            # El nombre del equipo visitante está en un enlace <a> con un id que empieza con 'team2_'
            away_team_tag = row.find('a', id=re.compile(r'team2_\d+'))
            away_team = away_team_tag.text.strip() if away_team_tag else "N/A"

            # Extraer el Hándicap Asiático
            # El AH se encuentra en la segunda celda de cuotas (oddstd)
            odds_cells = row.find_all('td', class_='oddstd')
            asian_handicap = "N/A"
            if len(odds_cells) >= 2:
                # El valor de la línea AH está en el primer <p> de la segunda celda de cuotas
                ah_p_tag = odds_cells[1].find('p', class_='odds1')
                if ah_p_tag:
                    asian_handicap = ah_p_tag.text.strip()

            match_list.append({
                "ID Partido": match_id,
                "Equipo Local": home_team,
                "Equipo Visitante": away_team,
                "Hándicap Asiático": asian_handicap
            })
        except Exception:
            # Si una fila tiene un formato inesperado, la saltamos para no detener el proceso
            continue
            
    return match_list

def main():
    """
    Función principal que construye la interfaz de Streamlit.
    """
    st.set_page_config(layout="wide", page_title="Extractor de Partidos Nowgoal")
    
    st.title("⚽ Extractor de Partidos de Nowgoal")
    st.markdown(f"Esta herramienta extrae la lista de partidos de la portada de `{BASE_URL}`.")

    if st.button("📊 Cargar y Mostrar Partidos", type="primary"):
        with st.spinner("Extrayendo datos, por favor espera..."):
            soup = fetch_page_content()
            
            if soup:
                data = parse_match_data(soup)
                
                if data:
                    st.success(f"¡Se encontraron {len(data)} partidos!")
                    df = pd.DataFrame(data)
                    
                    # Estilizar el DataFrame para mejor visualización
                    st.dataframe(
                        df,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "ID Partido": st.column_config.TextColumn("ID", help="ID único del partido."),
                            "Equipo Local": st.column_config.TextColumn("Local"),
                            "Equipo Visitante": st.column_config.TextColumn("Visitante"),
                            "Hándicap Asiático": st.column_config.TextColumn("AH", help="Línea de Hándicap Asiático inicial."),
                        }
                    )
                else:
                    st.warning("No se encontraron partidos en la tabla. El sitio puede haber cambiado su estructura.")
            else:
                st.error("No se pudo obtener el contenido de la página. Verifica tu conexión o inténtalo más tarde.")

if __name__ == "__main__":
    main()
