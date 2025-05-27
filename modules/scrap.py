# modules/scrap.py

import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import re # Para expresiones regulares

# URL objetivo de Live Score
LIVE_SCORE_URL = "https://live18.nowgoal25.com/" # Ojo: A veces cambian el subdominio (live19, live20, etc.)

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
        st.error(f"❌ Error de tiempo de espera: La solicitud a '{url}' tardó demasiado (>30s).")
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

def is_upcoming_match(status_text_clean, status_title_clean, current_time_text_raw):
    """
    Determina si un partido está "por comenzar" basándose en el texto de su estado,
    su atributo title y el texto de la celda de tiempo (si existe).
    """
    
    # Normalizar para comparación insensible a mayúsculas/minúsculas
    status_text_lower = status_text_clean.lower()
    status_title_lower = status_title_clean.lower()
    current_time_text_lower = current_time_text_raw.lower()

    # Patrones para estados que NO son "por comenzar"
    # min:seg (e.g. "90+6"), HT (Half Time), FT (Full Time), Canc (Cancelled), Postp (Postponed), Susp (Suspended)
    live_or_finished_patterns = re.compile(r'^\d+(\+|$)|ht|ft|canc|postp|susp') 

    # Casos explícitos de "no por comenzar":
    if live_or_finished_patterns.search(status_text_lower) or \
       'halftime' in status_title_lower or \
       'finished' in status_title_lower or \
       'postponed' in status_title_lower or \
       'cancelled' in status_title_lower or \
       'suspended' in status_title_lower or \
       'in-play' in status_title_lower or \
       'live' in status_title_lower or \
       '2nd half' in status_title_lower or \
       '1st half' in status_title_lower:
        st.write(f"  - Descartado (is_upcoming): Texto/Título indica LIVE/FINISHED/POSTPONED. `'{status_text_lower}'` / `'{status_title_lower}'`")
        return False
    
    # Ahora, el caso más importante para "por comenzar": estado y título vacíos, hora presente.
    # En NowGoal, el "status" de un partido que va a comenzar es un " " (lo que lo hace un string vacío al strip())
    # y el 'title' de ese td también es vacío. La hora aparece en otro TD con 'name="timeData"'.
    if status_text_clean == '' and status_title_clean == '':
        # Verificamos que el TD que DEBERÍA mostrar el tiempo *sí* tenga texto (ej. "19:00").
        # Esto previene clasificar filas sin datos como partidos futuros.
        if re.fullmatch(r'\d{2}:\d{2}', current_time_text_raw) or re.fullmatch(r'\d{2}:\d{2} \d{2}', current_time_text_raw):
             st.write(f"  - Confirmado (is_upcoming): Estado y Título de TD de status vacíos, Hora del partido: '{current_time_time}'. Es PROGRAMADO.")
             return True
        else:
            st.write(f"  - Descartado (is_upcoming): Estado y Título de TD de status vacíos, pero Hora del partido `'{current_time_text_raw}'` no parece una hora. (Podría ser una fila de AD, etc.)")
            return False

    st.write(f"  - Descartado (is_upcoming): Estado `{status_text_clean}` / Título `{status_title_clean}` NO coincide con patrones de PROGRAMADO/EN_JUEGO/FINALIZADO. Probablemente no es PROGRAMADO o la lógica necesita ajuste.")
    return False 


def scrape_upcoming_matches_logic(html_content):
    """
    Extrae los IDs y nombres de equipos de los partidos que AÚN NO HAN COMENZADO.
    Considera solo los partidos en la sección "Upcoming" (antes de "Results").
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    upcoming_matches_data = []

    st.subheader("🕵️‍♂️ Depuración de la Extracción de Partidos:")

    # **Paso 1: Localizar el contenedor principal que alberga la tabla de partidos.**
    # Primero intentamos con el ID que normalmente tiene el contenedor de la tabla de partidos activos.
    mintable_div = soup.find('div', id='mintable')
    
    if not mintable_div:
        st.error("❌ ERROR: No se encontró el div contenedor principal de partidos (ID: `mintable`).")
        st.warning("Esto podría significar que la estructura HTML de NowGoal ha cambiado radicalmente.")
        st.write("Sugerencia: Intenta encontrar `<div id='mintable'>` en el HTML de la página web actual para verificar.")
        return []

    st.success("✅ ÉXITO: Encontrado el div `mintable`.")

    # **Paso 2: Localizar el span que contiene la tabla de datos en vivo.**
    # En la estructura HTML de NowGoal, la tabla está dentro de un <span id="live">
    live_data_span = mintable_div.find('span', id='live')

    if not live_data_span:
        st.error("❌ ERROR: No se encontró el `<span>` de datos en vivo (ID: `live`) dentro de `mintable`.")
        st.warning("La tabla principal de partidos puede estar ahora en un contenedor diferente dentro de `mintable`.")
        st.write("Sugerencia: Busca `<span id='live'>` en el HTML actual de la página para verificar.")
        return []

    st.success("✅ ÉXITO: Encontrado el span `live`.")

    # **Paso 3: Localizar la tabla real de partidos.**
    # La tabla principal de partidos aún conserva su ID en NowGoal, pero el error original sugiere que el contexto padre pudo haber fallado.
    # Así que, buscamos *cualquier* tabla dentro de 'live_data_span', y confirmamos su ID.
    main_match_table = live_data_span.find('table', id='table_live')

    if not main_match_table:
        st.error("❌ ERROR: No se encontró la tabla de partidos con ID `table_live` dentro de `live_data_span`.")
        st.warning("La `id` de la tabla de partidos principal ha cambiado. El scraper necesitará actualización.")
        st.write("Sugerencia: Busca la tabla con los partidos (`<tr>` con clase `tds`) en el HTML de la página actual y anota su `id` o la del contenedor más cercano.")
        return []

    st.success("✅ ÉXITO: Encontrada la tabla principal de partidos (ID: `table_live`).")

    # Bandera para saber si hemos pasado la sección de partidos en vivo/por comenzar
    # La sección "Results" (partidos terminados) comienza con <tr id="resultSplit">
    found_result_split = False
    rows_processed_count = 0
    matches_found_debug = 0

    # Iterar sobre todas las filas <tr> directamente hijas de la tabla principal.
    # `recursive=False` es crucial para no ir demasiado profundo en tablas anidadas (si las hubiera).
    all_trs_in_table = main_match_table.find_all('tr', recursive=False)
    
    if not all_trs_in_table:
        st.warning("Scraper Debug: La tabla `table_live` se encontró, pero no contiene ninguna fila `<tr>` directa. (¡Es inesperado!)")
        return []

    st.info(f"Scraper Debug: Iniciando análisis de {len(all_trs_in_table)} filas dentro de la tabla principal...")

    for row in all_trs_in_table:
        rows_processed_count += 1
        row_id = row.get('id', 'No ID')
        row_classes = row.get('class', [])

        # Detectar el separador entre partidos en vivo/futuros y resultados
        if row_id == 'resultSplit':
            found_result_split = True
            st.info(f"Scraper Debug: Detectado separador de Resultados ('{row_id}'). Deteniendo búsqueda de partidos programados. Los siguientes son resultados.")
            continue # Pasar a la siguiente fila

        # Una vez que hemos pasado el separador, no hay más partidos "por comenzar"
        if found_result_split:
            st.write(f"Scraper Debug: Saltando fila '{row_id}' - Después del separador 'resultSplit'.")
            continue # Saltamos la fila actual porque es un partido ya terminado

        # Solo procesar filas que tienen la clase 'tds' (que representan partidos)
        if 'tds' in row_classes:
            match_id = row.get('matchid')

            if not match_id:
                st.write(f"Scraper Debug: Fila {rows_processed_count} (ID: {row_id}, Clases: {row_classes}) es 'tds' pero no tiene 'matchid'. Saltando.")
                continue # No es una fila de partido válida

            # Buscar la celda de estado del partido (con id `time_MATCHID` y clase 'status')
            status_td = row.find('td', id=f'time_{match_id}', class_='status') 
            
            # Buscar la celda de la hora de inicio del partido (con nombre 'timeData')
            time_data_td = row.find('td', {'name': 'timeData'})


            if not status_td:
                st.write(f"Scraper Debug: Partido {match_id} - NO se encontró celda de estado (ID: `time_{match_id}`, Clase: `status`). Esto es un problema clave para identificar partidos. Saltando.")
                st.write(f"Raw HTML del partido {match_id} para depuración: {row}")
                continue # No se puede determinar el estado sin esta celda

            # Limpiar el texto y el título de las celdas
            status_text_clean = status_td.get_text(strip=True)
            status_title_clean = status_td.get('title', '').strip()
            current_time_text_raw = time_data_td.get_text(strip=True) if time_data_td else "N/A_TIME"

            # DEBUGGING DEL ESTADO del partido
            st.write(f"Scraper Debug: Analizando Partido ID `{match_id}` (Fila {rows_processed_count})")
            st.write(f"  - Contenido `status_td` (limpio): `'{status_text_clean}'`")
            st.write(f"  - Atributo `title` de `status_td` (limpio): `'{status_title_clean}'`")
            st.write(f"  - Texto `time_data_td` (hora/minutos): `'{current_time_text_raw}'`")

            # Utilizar la función de clasificación para determinar si el partido está por comenzar
            if is_upcoming_match(status_text_clean, status_title_clean, current_time_text_raw):
                matches_found_debug += 1
                # Extraer nombres de los equipos
                home_team_tag = row.find('a', id=f'team1_{match_id}')
                away_team_tag = row.find('a', id=f'team2_{match_id}')
                
                home_team_name = clean_team_name(home_team_tag.get_text(strip=True)) if home_team_tag else "N/A"
                away_team_name = clean_team_name(away_team_tag.get_text(strip=True)) if away_team_tag else "N/A"
                
                # Extraer la hora UTC y la hora visible (del timeData)
                match_time_utc = time_data_td.get('data-t') if time_data_td else "N/A" # Formato 'YYYY-MM-DD HH:MM:SS'
                
                st.success(f"🎉 **¡ENCONTRADO! Partido por Comenzar:** ID `{match_id}` - `{home_team_name}` vs `{away_team_name}` (Hora: `{current_time_text_raw}`)")

                upcoming_matches_data.append({
                    'id': match_id,
                    'hora_utc': match_time_utc,
                    'hora_visible': current_time_text_raw,
                    'equipo_local': home_team_name,
                    'equipo_visitante': away_team_name
                })
            else:
                st.write(f"  - Partido {match_id}: Descartado (No es partido PROGRAMADO según la lógica).")
        else:
             st.write(f"Scraper Debug: Fila {rows_processed_count} (ID: {row_id}, Clases: {row_classes}) no es una fila 'tds' (es una fila de cabecera de liga, anuncio, etc.). Saltando.")

    st.info(f"Scraper Debug: Finalizada la revisión de {rows_processed_count} filas de la tabla. Se encontraron **{len(upcoming_matches_data)}** partidos por comenzar.")
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
        st.markdown("---") # Separador para la salida de depuración
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
                    st.error("❌ No se encontraron partidos por comenzar con el criterio actual. Esto podría deberse a:")
                    st.markdown("""
                    -   Ya no hay partidos programados restantes para el día visible.
                    -   La estructura del HTML de NowGoal ha vuelto a cambiar, haciendo que los elementos que busca el scraper sean diferentes.
                    -   Hay problemas con la URL de origen o tu conexión.
                    
                    **Consulta la sección de 'Depuración de la Extracción de Partidos' arriba para identificar la falla específica.**
                    """)
            else:
                st.error("🚫 No se pudo obtener el contenido HTML de la página web. Revisa los mensajes de error de conexión/red o posibles bloqueos que aparezcan más arriba.")
        st.markdown("---") # Separador al final de la ejecución
