# modules/scrap.py

import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import re # Para expresiones regulares

# URL objetivo de Live Score
LIVE_SCORE_URL = "https://live18.nowgoal25.com/"

def fetch_html(url):
    """
    Realiza una solicitud HTTP GET a la URL y devuelve el contenido HTML.
    Maneja posibles errores de conexión.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    try:
        response = requests.get(url, headers=headers, timeout=20) # Aumentado el timeout a 20 segundos
        response.raise_for_status()  # Lanza un error para códigos de estado HTTP 4xx/5xx
        return response.text
    except requests.exceptions.RequestException as e:
        st.error(f"❌ Error de red o conexión al intentar acceder a la página '{url}': {e}")
        st.info("💡 Por favor, verifica tu conexión a internet o si la URL es correcta/accesible.")
        return None

def clean_team_name(team_name_raw):
    """
    Limpia el nombre del equipo, removiendo cualquier anotación de ranking (ej. "[LIT D1-8]")
    o neutralidad "(N)".
    """
    # Remover corchetes y su contenido, ej. "[LIT D1-8]"
    cleaned_name = re.sub(r'\[.*?\]', '', team_name_raw)
    # Remover paréntesis y su contenido, ej. "(N)" o cualquier otro info extra
    cleaned_name = re.sub(r'\s*\([^)]*\)\s*', '', cleaned_name)
    return cleaned_name.strip()


def scrape_upcoming_matches_logic(html_content):
    """
    Extrae los IDs y nombres de equipos de los partidos que AÚN NO HAN COMENZADO.
    Considera solo los partidos en la sección "Upcoming" (antes de "Results").
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    upcoming_matches_data = []

    # Encontrar la tabla principal que contiene los partidos en juego y los que van a comenzar
    live_table = soup.find('table', id='table_live')

    if not live_table:
        st.warning("⚠️ No se encontró la tabla principal de partidos (id='table_live'). La estructura del HTML puede haber cambiado.")
        return []

    # Bandera para saber si hemos pasado la sección de partidos en vivo/por comenzar
    # La sección "Results" (partidos terminados) comienza con <tr id="resultSplit">
    found_result_split = False

    # Iterar sobre todas las filas <tr> dentro de la tabla principal.
    # Usamos `recursive=False` para obtener solo las filas directamente hijas y no las anidadas.
    for row in live_table.find_all('tr', recursive=False):
        if row.get('id') == 'resultSplit':
            found_result_split = True
            continue # Una vez que encontramos el separador, el resto son resultados

        # Procesar solo las filas de partidos (con clase 'tds') antes del separador "Results"
        if not found_result_split and 'tds' in row.get('class', []):
            match_id = row.get('matchid')

            if match_id: # Asegurarse de que sea una fila de partido válida
                # Buscar la celda de estado del partido (generalmente es la que tiene el id `time_MATCHID` y clase 'status')
                status_td = row.find('td', id=f'time_{match_id}', class_='status') 

                if status_td:
                    # Un partido por comenzar tiene un estado de texto vacío (que puede ser  )
                    # y su atributo 'title' también debe ser vacío para confirmar que no ha iniciado (HT, FT, 2nd Half, etc.)
                    status_text_clean = status_td.get_text(strip=True)
                    status_title = status_td.get('title', '').strip()
                    
                    # La condición clave: si el texto es vacío y el título es vacío, es un partido futuro (PROGRAMADO)
                    # Excluimos "Postp." (pospuestos) y "Canc." (cancelados) que tendrían un title.
                    if status_text_clean == '' and status_title == '':
                        
                        # Extraer nombres de los equipos
                        home_team_tag = row.find('a', id=f'team1_{match_id}')
                        away_team_tag = row.find('a', id=f'team2_{match_id}')
                        
                        home_team_name = clean_team_name(home_team_tag.get_text(strip=True)) if home_team_tag else "N/A"
                        away_team_name = clean_team_name(away_team_tag.get_text(strip=True)) if away_team_tag else "N/A"
                        
                        # Extraer la hora del partido
                        time_data_tag = row.find('td', {'name': 'timeData'})
                        match_time = ""
                        if time_data_tag:
                            match_time = time_data_tag.get('data-t') # Formato 'YYYY-MM-DD HH:MM:SS'
                        
                        upcoming_matches_data.append({
                            'id': match_id,
                            'hora_utc': match_time,
                            'equipo_local': home_team_name,
                            'equipo_visitante': away_team_name
                        })
                
    return upcoming_matches_data

# Función principal que será llamada desde main.py
def scrap():
    st.header("⚡ Scraper de Partidos Programados ⚡")
    st.markdown("""
    Esta herramienta se conecta directamente a Nowgoal.com para extraer los IDs
    y los nombres de los equipos de los partidos que AÚN NO HAN COMENZADO (están programados).
    """)
    st.info(f"🌐 Intentando extraer datos de: `{LIVE_SCORE_URL}`")

    if st.button("🚀 ¡Extraer Ahora!"):
        with st.spinner("Conectando y analizando el sitio, por favor espera..."):
            html_content = fetch_html(LIVE_SCORE_URL)

            if html_content:
                matches = scrape_upcoming_matches_logic(html_content)

                if matches:
                    st.success(f"✅ ¡Extracción completada! Se encontraron {len(matches)} partidos programados.")
                    df = pd.DataFrame(matches)
                    st.dataframe(df, use_container_width=True)

                    # Opción para descargar los datos en formato CSV
                    csv = df.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        label="💾 Descargar datos como CSV",
                        data=csv,
                        file_name="partidos_futuros_nowgoal.csv",
                        mime="text/csv",
                        help="Haz clic para descargar los datos en un archivo CSV."
                    )
                else:
                    st.warning("🧐 No se encontraron partidos por comenzar con el criterio actual. Esto podría deberse a:")
                    st.markdown("""
                    - Todos los partidos ya están en juego, terminados, o se han pospuesto/cancelado.
                    - La estructura del HTML de Nowgoal ha cambiado, y el scraper necesita una actualización.
                    """)
            else:
                st.error("🚫 No se pudo obtener el contenido HTML de la página web. Consulta los mensajes de error de conexión/red arriba.")
