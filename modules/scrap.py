
import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import re # Para expresiones regulares, útil para limpiar texto

# URL objetivo
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
        response = requests.get(url, headers=headers, timeout=15) # Añadido timeout
        response.raise_for_status()  # Lanza un error para códigos de estado HTTP 4xx/5xx
        return response.text
    except requests.exceptions.RequestException as e:
        st.error(f"❌ Error al intentar acceder a la página '{url}': {e}")
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


def scrape_upcoming_matches(html_content):
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

    # Iterar sobre todas las filas <tr> dentro de la tabla principal
    for row in live_table.find_all('tr', recursive=False): # Solo hijos directos de la tabla
        if row.get('id') == 'resultSplit':
            found_result_split = True
            continue # Una vez que encontramos el separador, el resto son resultados

        # Procesar solo las filas de partidos antes del separador "Results"
        if not found_result_split and 'tds' in row.get('class', []):
            match_id = row.get('matchid')

            if match_id: # Asegurarse de que sea una fila de partido válida
                # Buscar la celda de estado del partido (generalmente es la segunda visible, o con id `time_MATCHID`)
                status_td = row.find('td', id=f'time_{match_id}', class_='status') # Usar clase 'status'

                if status_td:
                    # Un partido por comenzar tiene un estado vacío (un espacio en blanco como  )
                    # y un título vacío, a diferencia de "FT", "HT", o un minuto de juego.
                    # También descartamos "Postp." (postergado) y "Canc." (cancelado).
                    status_text_clean = status_td.get_text(strip=True)
                    status_title = status_td.get('title', '').strip() # Obtener el atributo title, si existe

                    # La condición clave: si el texto es vacío y el título es vacío, es un partido futuro sin estado especial
                    if status_text_clean == '' and status_title == '':
                        # Extraer nombres de los equipos
                        home_team_raw = row.find('td', id=f'ht_{match_id}') # El td que contiene el equipo local
                        away_team_raw = row.find('td', id=f'gt_{match_id}') # El td que contiene el equipo visitante

                        home_team_name = clean_team_name(home_team_raw.get_text(strip=True)) if home_team_raw else "N/A"
                        away_team_name = clean_team_name(away_team_raw.get_text(strip=True)) if away_team_raw else "N/A"
                        
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

# --- Configuración de la interfaz de Streamlit ---
st.set_page_config(layout="wide", page_title="Scraper de Partidos AhoraGoal", page_icon="⚽")

st.title("⚽ Scraper de Partidos por Comenzar")
st.markdown(
    """
    Esta aplicación se conecta a `nowgoal25.com` y extrae los IDs, la hora (UTC) y los nombres de los equipos
    de los partidos que aún no han comenzado (futuros), excluyendo partidos en juego o terminados.
    """
)

st.info(f"Se realizará scraping de: {LIVE_SCORE_URL}")

if st.button("📈 ¡Cargar y Extraer Partidos!"):
    with st.spinner("Conectando y analizando el sitio... Esto puede tomar un momento..."):
        html_content = fetch_html(LIVE_SCORE_URL)

        if html_content:
            matches = scrape_upcoming_matches(html_content)

            if matches:
                st.success(f"🎉 ¡Extracción completada! Se encontraron {len(matches)} partidos por comenzar.")
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
                *   Ya no hay partidos futuros para hoy en la sección visible.
                *   La estructura del HTML de la página ha cambiado.
                *   Todos los partidos restantes ya están en juego o terminados.
                """)
        else:
            st.error("🚫 No se pudo obtener el contenido HTML de la página. Por favor, revisa el mensaje de error anterior.")

st.markdown(
    """
    ---
    *Disclaimer: Este scraper es una herramienta de demostración. Su funcionalidad puede verse afectada si la estructura HTML de la página web de destino cambia. Se recomienda usarlo de forma responsable y respetando las políticas de uso del sitio web de destino.*
    """
)
