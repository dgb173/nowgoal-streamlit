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
        # Aumentado el timeout para conexiones más lentas o servidores cargados
        response = requests.get(url, headers=headers, timeout=30) 
        response.raise_for_status()  # Lanza un error para códigos de estado HTTP 4xx/5xx
        return response.text
    except requests.exceptions.Timeout:
        st.error(f"❌ Error de tiempo de espera: La solicitud a '{url}' tardó demasiado.")
        st.info("💡 La conexión puede ser lenta o el servidor de la página no responde a tiempo. Intenta de nuevo.")
        return None
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

def is_upcoming_match(status_text, status_title):
    """
    Determina si un partido está "por comenzar" basándose en el texto de su estado
    y su atributo title.
    """
    status_text_lower = status_text.lower()
    status_title_lower = status_title.lower()

    # Patrones para estados "no por comenzar"
    live_patterns = re.compile(r'^\d+(\+|$)|ht|ft|canc|postp') # min:sec, HT, FT, Canc., Postp.

    # Si contiene minutos, o 'HT', o 'FT', 'Canc.', 'Postp.' ya no es 'upcoming'
    if live_patterns.search(status_text_lower) or \
       'halftime' in status_title_lower or \
       'finished' in status_title_lower or \
       'postponed' in status_title_lower or \
       'cancelled' in status_title_lower or \
       'live' in status_title_lower or \
       '2nd half' in status_title_lower or \
       '1st half' in status_title_lower:
        return False
    
    # Si la celda de status está realmente vacía (ej. " ") Y su title también, es un buen candidato para "upcoming".
    # Algunos partidos futuros pueden tener solo la hora aquí sin título específico.
    if status_text == '' and status_title == '': # Caso de   y title vacío
        return True

    # Si es solo una hora (e.g. "19:00"), podría ser un partido por comenzar.
    # Pero también es lo que `mt_matchid` tiene. El `status_td` generalmente tiene  
    # o el tiempo actual. Para estar seguro, nos basamos más en que NO sea in-play/finished.
    
    # Aquí podríamos añadir una heurística más: si el texto es X:XX y el título está vacío,
    # probablemente sea próximo. Sin embargo, en NowGoal lo común para futuros es " ".
    if re.fullmatch(r'\d{2}:\d{2}', status_text) and status_title == '':
         st.write(f"DEBUG: Found a time format status: '{status_text}' - considering as upcoming if it reached this stage.")
         return True # Esto podría atrapar partidos futuros si han cambiado la representación.


    # Si no coincide con ninguna de las condiciones de 'en juego', 'terminado' o 'postergado/cancelado'
    # y no tiene una indicación clara de haber iniciado, asumimos que es 'upcoming'.
    # ¡CUIDADO! Esto es la parte más sensible y requiere ajuste si NowGoal cambia
    st.write(f"DEBUG: Status '{status_text}' / title '{status_title}' does NOT explicitly mark as IN-PLAY/FINISHED. Final check might mark as Upcoming.")
    return True # Es un poco una asunción de "todo lo demás es por comenzar"
                 # Preferiría que la lógica de arriba con status_text=='' fuese suficiente.
                 # Podrías necesitar ajustar esta línea a 'False' si hay muchos "upcoming" falsos.


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
        st.warning("⚠️ Scraper Error: No se encontró la tabla principal de partidos (ID: `table_live`).")
        st.write("Verifica el código fuente de NowGoal para ver si el ID de la tabla ha cambiado.")
        return []

    # Bandera para saber si hemos pasado la sección de partidos en vivo/por comenzar
    # La sección "Results" (partidos terminados) comienza con <tr id="resultSplit">
    found_result_split = False
    rows_processed_count = 0

    st.subheader("🕵️‍♂️ Depuración de la Extracción de Partidos:")

    # Iterar sobre todas las filas <tr> dentro de la tabla principal.
    # Usamos `recursive=False` para obtener solo las filas directamente hijas y no las anidadas.
    all_trs = live_table.find_all('tr', recursive=False)
    if not all_trs:
        st.warning("Scraper Debug: La tabla 'table_live' se encontró, pero no contiene ninguna fila `<tr>`.")
        return []

    for row in all_trs:
        rows_processed_count += 1
        row_id = row.get('id', 'No ID')
        row_classes = row.get('class', [])

        if row_id == 'resultSplit':
            found_result_split = True
            st.info(f"Scraper Debug: Detectado separador de Resultados ('{row_id}'). Deteniendo búsqueda de partidos programados.")
            continue

        if found_result_split:
            continue # Saltar filas después del separador de resultados

        # Solo procesar filas que se supone que son partidos (clase 'tds')
        if 'tds' in row_classes:
            match_id = row.get('matchid')

            if not match_id:
                st.write(f"Scraper Debug: Fila {rows_processed_count} (ID: {row_id}, Clases: {row_classes}) parece un partido pero no tiene 'matchid'. Saltando.")
                continue 

            # Buscar la celda de estado del partido (con id `time_MATCHID` y clase 'status')
            status_td = row.find('td', id=f'time_{match_id}', class_='status') 
            
            if not status_td:
                st.write(f"Scraper Debug: Partido {match_id} - NO se encontró celda de estado (ID: time_{match_id}, Clase: status). Raw HTML del partido: {row}")
                continue # No se puede determinar el estado sin esta celda

            status_text_clean = status_td.get_text(strip=True)
            status_title = status_td.get('title', '').strip()

            # DEBUGGING DEL ESTADO
            st.write(f"Scraper Debug: Procesando Partido ID `{match_id}`")
            st.write(f"  - Contenido `time_td` (limpio): `'{status_text_clean}'`")
            st.write(f"  - Atributo `title` de `time_td` (limpio): `'{status_title}'`")
            st.write(f"  - Texto visible del partido (e.g. `mt_` id): `{row.find('td', id=f'mt_{match_id}').get_text(strip=True) if row.find('td', id=f'mt_{match_id}') else 'N/A'}`")


            if is_upcoming_match(status_text_clean, status_title):
                # Extraer nombres de los equipos
                home_team_tag = row.find('a', id=f'team1_{match_id}')
                away_team_tag = row.find('a', id=f'team2_{match_id}')
                
                home_team_name = clean_team_name(home_team_tag.get_text(strip=True)) if home_team_tag else "N/A"
                away_team_name = clean_team_name(away_team_tag.get_text(strip=True)) if away_team_tag else "N/A"
                
                # Extraer la hora del partido
                time_data_tag = row.find('td', {'name': 'timeData'}) # Este td suele tener la hora GMT+X
                match_time_display = time_data_tag.get_text(strip=True) if time_data_tag else "N/A"
                match_time_utc = time_data_tag.get('data-t') if time_data_tag else "N/A" # La hora exacta en UTC
                
                st.success(f"¡ENCONTRADO! Partido por Comenzar: ID `{match_id}` ({home_team_name} vs {away_team_name})")

                upcoming_matches_data.append({
                    'id': match_id,
                    'hora_utc': match_time_utc, # Formato 'YYYY-MM-DD HH:MM:SS'
                    'hora_visible': match_time_display, # Hora visible en la tabla
                    'equipo_local': home_team_name,
                    'equipo_visitante': away_team_name
                })
            else:
                st.write(f"  - Partido {match_id}: Descartado (No es partido por comenzar según el criterio).")
        # else:
        #     st.write(f"Scraper Debug: Fila {rows_processed_count} (ID: {row_id}, Clases: {row_classes}) NO es una fila 'tds'. Saltando.")


    st.info(f"Scraper Debug: Finalizada la revisión de {rows_processed_count} filas. Se encontraron {len(upcoming_matches_data)} partidos por comenzar.")
    return upcoming_matches_data

# Función principal que será llamada desde main.py (Streamlit UI)
def scrap():
    st.header("⚡ Scraper de Partidos Programados de NowGoal ⚡")
    st.markdown("""
    Esta herramienta se conecta directamente a Nowgoal.com para extraer los IDs, las horas (UTC y visible),
    y los nombres de los equipos de los partidos que **AÚN NO HAN COMENZADO (están programados)**.
    """)
    st.info(f"🌐 La URL de origen es: `{LIVE_SCORE_URL}`")

    if st.button("🚀 ¡Extraer Partidos Programados Ahora!"):
        st.markdown("---")
        with st.spinner("Conectando y analizando el sitio, por favor espera..."):
            html_content = fetch_html(LIVE_SCORE_URL)

            if html_content:
                matches = scrape_upcoming_matches_logic(html_content) # La lógica de depuración está aquí dentro

                if matches:
                    st.subheader(f"📊 Resumen de Partidos Programados Encontrados: {len(matches)}")
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
                    st.error("❌ No se encontraron partidos por comenzar con el criterio actual. Consulta la sección de 'Depuración de la Extracción de Partidos' arriba para más detalles.")
            else:
                st.error("🚫 No se pudo obtener el contenido HTML de la página web. Por favor, revisa los mensajes de error de conexión/red o posibles bloqueos arriba.")
        st.markdown("---") # Separador para limpiar la depuración si no se desea.
