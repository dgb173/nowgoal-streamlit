# requirements.txt
# streamlit
# beautifulsoup4
# pandas

import streamlit as st
from bs4 import BeautifulSoup
import pandas as pd

def scrape_upcoming_matches(html_content):
    """
    Extrae los IDs, nombres de equipos local y visitante
    de los partidos que aún no han comenzado del HTML proporcionado.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    upcoming_matches_data = []

    # Buscar todas las filas <tr> con la clase "tds" que representan los partidos
    # y que no están en la sección "Results" (que está después de un <tr> con id "resultSplit")
    
    # Encontrar la tabla principal que contiene los partidos
    live_table = soup.find('table', id='table_live')
    
    if not live_table:
        st.error("No se encontró la tabla principal de partidos. Asegúrate de pegar el HTML correcto.")
        return []

    # Extraer las filas relevantes antes de la sección "Results"
    # La sección "Results" comienza con <tr id="resultSplit">
    relevant_rows = []
    found_result_split = False
    
    # Iterar sobre todos los <tr> de la tabla principal
    for row in live_table.find_all('tr'):
        if row.get('id') == 'resultSplit':
            found_result_split = True
            continue # Una vez que encontramos el separador, el resto son resultados

        if not found_result_split and 'tds' in row.get('class', []):
            relevant_rows.append(row)

    for row in relevant_rows:
        match_id = row.get('matchid')
        if not match_id:
            continue # Saltar filas que no son partidos (ej. títulos de liga, ads)

        # La columna de estado es el 4to td que no tiene style="display:none"
        # O, de forma más robusta, buscar el td con id='time_MATCHID' y class='status handpoint'
        status_td = row.find('td', id=f'time_{match_id}', class_='status handpoint')

        if status_td:
            # Los partidos por comenzar tienen un estado vacío (que puede ser   o una cadena vacía al strip())
            # y no tienen el título "Postponed", "FT", "HT" etc.
            # Verificamos que el texto del estado sea vacío después de strip()
            status_text = status_td.get_text(strip=True)
            status_title = status_td.get('title', '').strip()
            
            # Un partido "por comenzar" usualmente tendrá un estado de texto vacío y un título vacío.
            # Los que ya están en juego tienen minutos o 'HT', los terminados tienen 'FT', etc.
            if status_text == '' and status_title == '':
                
                # Extraer nombres de los equipos
                home_team_tag = row.find('a', id=f'team1_{match_id}')
                away_team_tag = row.find('a', id=f'team2_{match_id}')
                
                home_team_name = home_team_tag.get_text(strip=True) if home_team_tag else "N/A"
                away_team_name = away_team_tag.get_text(strip=True) if away_team_tag else "N/A"

                upcoming_matches_data.append({
                    'id': match_id,
                    'home_team': home_team_name,
                    'away_team': away_team_name
                })
                
    return upcoming_matches_data

# Configuración de la interfaz de Streamlit
st.set_page_config(layout="wide")
st.title("⚽ Scraper de Partidos por Comenzar")

st.markdown(
    """
    Este scraper te ayuda a extraer los IDs y nombres de los equipos de los partidos
    que aún no han comenzado (programados) de la sección principal de un feed de partidos en HTML.

    **Instrucciones:**
    1.  Abre la página web que contiene la estructura HTML de los partidos (ej. LiveScore).
    2.  Haz clic derecho en la página y selecciona "Inspeccionar" (o "Ver código fuente de la página").
    3.  Copia todo el contenido HTML (normalmente, desde `<html>` hasta `</html>`).
    4.  Pégalo en el cuadro de texto de abajo y haz clic en "Extraer Partidos".
    """
)

# Área de texto para que el usuario pegue el HTML
html_input = st.text_area("Pega el contenido HTML aquí:", height=500, key="html_content_input")

# Botón para activar el scraping
if st.button("Extraer Partidos"):
    if html_input:
        with st.spinner("Extrayendo datos de los partidos..."):
            extracted_matches = scrape_upcoming_matches(html_input)

        if extracted_matches:
            st.subheader(f"✅ ¡Se encontraron {len(extracted_matches)} partidos por comenzar!:")
            df = pd.DataFrame(extracted_matches)
            st.dataframe(df, use_container_width=True) # Mostrar como tabla interactiva

            # Opción para descargar los datos
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="Descargar datos como CSV",
                data=csv,
                file_name="partidos_por_comenzar.csv",
                mime="text/csv",
            )
        else:
            st.warning("⚠️ No se encontraron partidos por comenzar en el HTML proporcionado o el formato de la página ha cambiado.")
    else:
        st.info("Por favor, pega el contenido HTML en el cuadro de texto para comenzar la extracción.")

st.markdown(
    """
    ---
    *Desarrollado con ❤️ para ti. Este scraper se basa en la estructura HTML proporcionada. Si la página cambia su estructura, es posible que el scraper necesite ser actualizado.*
    """
)
