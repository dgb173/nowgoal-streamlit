# modules/scrap.py

import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import re # Para expresiones regulares

# URL objetivo de Live Score
LIVE_SCORE_URL = "https://live18.nowgoal25.com/" 
# ¡Ojo! Este subdominio (live18) puede cambiar (live19, live20, etc.). 
# Si la app deja de cargar la página, lo primero es verificar y actualizar este LIVE_SCORE_URL.

def fetch_html(url):
    """
    Realiza una solicitud HTTP GET a la URL y devuelve el contenido HTML.
    Maneja posibles errores de conexión y de timeout.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    try:
        # Aumentado el timeout para conexiones más lentas o servidores cargados
        response = requests.get(url, headers=headers, timeout=30) 
        response.raise_for_status()  # Lanza una excepción si el código de estado HTTP es un error (4xx o 5xx)
        return response.text
    except requests.exceptions.Timeout:
        st.error(f"❌ Error de tiempo de espera: La solicitud a '{url}' tardó demasiado (>30s).")
        st.info("💡 La conexión puede ser lenta o el servidor de NowGoal no responde a tiempo. Intenta de nuevo.")
        return None
    except requests.exceptions.RequestException as e:
        st.error(f"❌ Error de red o al intentar acceder a la página '{url}': {e}")
        st.info("💡 Por favor, verifica tu conexión a internet o si la URL de NowGoal es correcta/accesible.")
        return None

def clean_team_name(team_name_raw):
    """
    Limpia el nombre del equipo, removiendo cualquier anotación de ranking (ej. "[LIT D1-8]")
    o neutralidad "(N)", o corchetes que no sean de ranking, etc.
    """
    # Eliminar texto dentro de corchetes, ej. "[LIT D1-8]"
    cleaned_name = re.sub(r'\[[^\]]*\]', '', team_name_raw)
    # Eliminar texto dentro de paréntesis que contenga '(N)' de neutralidad
    cleaned_name = re.sub(r'\s*\(\s*[Nn]\s*\)', '', cleaned_name)
    # Eliminar otros posibles paréntesis o espacios extra si no contienen la "N" de neutral.
    # Esta es más agresiva y podrías querer ajustarla si aparecen "(Algun Dato)" relevante
    cleaned_name = re.sub(r'\s*\([^)]*\)\s*', '', cleaned_name) 
    
    return cleaned_name.strip()

def is_upcoming_match(status_td_content, status_td_title):
    """
    Determina si un partido está "por comenzar" basándose en el texto de su celda de estado
    y su atributo `title`. La lógica más robusta es EXCLUIR los que YA tienen un estado definido.
    """
    # Convertir a minúsculas para una comparación insensible a mayúsculas/minúsculas
    status_text_lower = status_td_content.lower()
    status_title_lower = status_td_title.lower()

    # Patrones RegEx para identificar estados que NO son "por comenzar"
    # Incluye: cualquier dígito (minutos), 'ht' (half time), 'ft' (full time), 'canc' (cancelled),
    # 'postp' (postponed), 'susp' (suspended). El '^' asegura que empiece por el patrón de tiempo.
    live_or_finished_regex = re.compile(r'^\d+\+?\s*\d*$|^ht$|^ft$|^canc$|^postp$|^susp$') # Regex para minutos o "90+X", o estado fijo

    # Si el texto de la celda de estado coincide con un patrón de en-juego/finalizado/cancelado/postergado
    if live_or_finished_regex.search(status_text_lower):
        st.write(f"  - Descartado (Estado Excluido): `{status_text_lower}` coincide con LIVE/FINISHED/CANCELLED/POSTPONED regex.")
        return False
    
    # Si el atributo 'title' indica que el partido ya comenzó, terminó, fue pospuesto o cancelado
    if 'half' in status_title_lower or \
       'finished' in status_title_lower or \
       'postponed' in status_title_lower or \
       'cancelled' in status_title_lower or \
       'in-play' in status_title_lower or \
       'suspended' in status_title_lower:
        st.write(f"  - Descartado (Título Excluido): `{status_title_lower}` indica LIVE/FINISHED/CANCELLED/POSTPONED.")
        return False
        
    # Un partido por comenzar *idealmente* tiene su celda de estado vacía (lo que resulta en '' al strip())
    # y también un `title` vacío.
    if status_td_content == '' and status_td_title == '':
        st.write(f"  - ¡CONFIRMADO! Celdas de estado (`'{status_td_content}'` / `'{status_td_title}'`) ambas vacías. Es PROGRAMADO.")
        return True
    
    # Si llegó hasta aquí, significa que la celda de estado tiene algún texto
    # o título que no se corresponde con los estados conocidos de "NO PROGRAMADO"
    # Y tampoco es el patrón "limpio" de PROGRAMADO (vacío).
    # Este caso es ambiguo y podríamos necesitar depurar qué texto tienen estos.
    st.write(f"  - Ambiguo/Desconocido: Estado `{status_td_content}` / Título `{status_td_title}`. NO coincide con ningún patrón claro. Se considera NO PROGRAMADO.")
    return False


def scrape_upcoming_matches_logic(html_content):
    """
    Extrae los IDs, nombres de equipos, y horas de los partidos que AÚN NO HAN COMENZADO.
    Prioriza robustez al encontrar elementos y añade mucha depuración.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    upcoming_matches_data = []

    st.subheader("🕵️‍♂️ **Registro Detallado de la Extracción:**")

    # Estrategia más robusta para encontrar la tabla de partidos:
    # Buscar una tabla que contenga *al menos* una fila de encabezado de partido (scoretitle)
    # y *al menos* una fila de partido real (tds).
    main_match_table = None

    # Primero intentamos el ID común, porque es el más eficiente
    st.write(f"Buscando `table` con ID `table_live`...")
    main_match_table = soup.find('table', id='table_live')

    if not main_match_table:
        st.write("ID `table_live` NO ENCONTRADO. Intentando buscar una tabla basada en su contenido (clases de fila).")
        # Si no encontramos el ID, buscamos una tabla que contenga los elementos característicos:
        # Una fila con la clase 'scoretitle' (la cabecera) y una fila con la clase 'tds' (un partido).
        all_tables = soup.find_all('table')
        if not all_tables:
            st.error("❌ ERROR: No se encontró NINGUNA tabla en el HTML.")
            return []

        for table in all_tables:
            if table.find('tr', class_='scoretitle') and table.find('tr', class_='tds'):
                main_match_table = table
                st.write(f"¡Éxito! Tabla principal encontrada usando clases de fila. ID: `{table.get('id', 'N/A')}`, Clases: `{table.get('class', 'N/A')}`.")
                break
        
        if not main_match_table:
            st.error("❌ ERROR CRÍTICO: No se encontró la tabla principal de partidos ni por ID ni por contenido de filas.")
            st.warning("Esto indica un cambio MUY significativo en la estructura del HTML de NowGoal. El scraper necesita una actualización manual profunda.")
            return []

    st.success("✅ **ÉXITO: Tabla principal de partidos encontrada.**")

    # Bandera para identificar el separador "Results" (partidos terminados)
    # Su ID ('resultSplit') parece ser bastante estable.
    found_result_split = False
    rows_processed_count = 0
    upcoming_matches_count = 0

    all_trs_in_table = main_match_table.find_all('tr', recursive=False)
    
    if not all_trs_in_table:
        st.warning("Depuración: La tabla de partidos encontrada no contiene filas `<tr>` directas. ¡Inesperado!")
        return []

    st.info(f"Iniciando análisis de {len(all_trs_in_table)} filas dentro de la tabla...")

    for row in all_trs_in_table:
        rows_processed_count += 1
        row_id = row.get('id', 'Sin ID')
        row_classes = row.get('class', [])
        
        st.write(f"**Procesando Fila {rows_processed_count}: ID=`{row_id}`, Clases=`{row_classes}`**")

        # Detectar el separador de resultados
        if row_id == 'resultSplit':
            found_result_split = True
            st.info("Detectado `resultSplit`. Los siguientes partidos son RESULTADOS y serán ignorados para 'Próximos'.")
            continue

        # Una vez que encontramos el separador, el resto de las filas son resultados y no nos interesan
        if found_result_split:
            st.write("Saltando fila, ya que se encontró `resultSplit` anteriormente.")
            continue

        # Ignorar filas de títulos de liga o anuncios
        if 'Leaguestitle' in row_classes or 'adtext-bg' in row_classes or 'ad_m' in row_classes or row_id.startswith('tr3_') or row_id.startswith('tr_ad'):
            st.write("Saltando fila: Es título de liga o anuncio.")
            continue

        # Si no es un separador, título o anuncio, y es una fila de partido 'tds'
        if 'tds' in row_classes:
            match_id = row.get('matchid')

            if not match_id:
                st.write(f"Fila 'tds' pero sin 'matchid' (`{row}`). Saltando.")
                continue # Fila 'tds' pero sin matchid, rara.

            # Buscar la celda de estado (tiempo de juego o 'HT', 'FT', etc.)
            status_td = row.find('td', id=f'time_{match_id}', class_='status') 
            if not status_td:
                st.warning(f"¡ADVERTENCIA! No se encontró la celda de estado (`time_{match_id}`) para el partido ID `{match_id}`.")
                st.write(f"Raw HTML del partido para depuración: {row}")
                continue
            
            # Buscar la celda que tiene la hora de inicio (puede ser 'time' o data-t)
            time_data_td = row.find('td', {'name': 'timeData'})

            # Extraer contenido y título de la celda de estado
            status_text_clean = status_td.get_text(strip=True)
            status_title_clean = status_td.get('title', '').strip()
            # La hora que aparece en la columna `mt_` o `timeData` para debugging
            current_time_text_raw = time_data_td.get_text(strip=True) if time_data_td else "Hora_TD_N/A"

            st.write(f"  **- Detalles para Partido ID `{match_id}`:**")
            st.write(f"    - Estado de la celda de tiempo (ID=`time_{match_id}`, Clases=`status`): `'{status_text_clean}'` (texto), `'{status_title_clean}'` (title)")
            st.write(f"    - Contenido del `td` con `name='timeData'` (posiblemente la hora `XX:XX`): `'{current_time_text_raw}'`")

            # Ahora, usa la lógica robusta para clasificar si es un partido por comenzar
            if is_upcoming_match(status_text_clean, status_title_clean):
                upcoming_matches_count += 1
                # Extraer nombres de los equipos y la hora UTC
                home_team_raw = row.find('a', id=f'team1_{match_id}')
                away_team_raw = row.find('a', id=f'team2_{match_id}')
                
                home_team_name = clean_team_name(home_team_raw.get_text(strip=True)) if home_team_raw else f"Equipo Local {match_id} N/A"
                away_team_name = clean_team_name(away_team_raw.get_text(strip=True)) if away_team_raw else f"Equipo Visitante {match_id} N/A"
                
                match_time_utc = time_data_td.get('data-t') if time_data_td else "Hora_UTC_N/A" 
                
                st.success(f"  ✅ ¡Partido Programado ENCONTRADO! ID: `{match_id}` - {home_team_name} vs {away_team_name} (Hora Visible: {current_time_text_raw})")

                upcoming_matches_data.append({
                    'id': match_id,
                    'hora_utc': match_time_utc,
                    'hora_visible': current_time_text_raw,
                    'equipo_local': home_team_name,
                    'equipo_visitante': away_team_name
                })
            else:
                st.write(f"  Partido ID `{match_id}` descartado. No es un partido programado.")

    st.info(f"**Análisis Finalizado:** Se revisaron {rows_processed_count} filas. Se encontraron **{upcoming_matches_count}** partidos programados.")
    if upcoming_matches_count == 0:
        st.warning("Si esperabas ver partidos y no se encontró ninguno, el sitio podría haber cambiado. Los mensajes de depuración de arriba pueden darte pistas.")
        
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

                    csv = df.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        label="💾 Descargar datos como CSV",
                        data=csv,
                        file_name="partidos_futuros_nowgoal.csv",
                        mime="text/csv",
                        help="Haz clic para descargar los datos en un archivo CSV."
                    )
                else:
                    st.error("❌ **No se encontraron partidos programados.** Esto podría deberse a:")
                    st.markdown("""
                    *   No hay partidos programados restantes para el día visible.
                    *   **¡Muy probable!** La estructura HTML de NowGoal ha cambiado nuevamente. El scraper podría necesitar una actualización en su lógica de búsqueda de elementos.
                    
                    **⚠️ ¡IMPORTANTE! Revisa la sección de 'Registro Detallado de la Extracción' más arriba para ver dónde falló el scraper.**
                    """)
            else:
                st.error("🚫 No se pudo obtener el contenido HTML de la página web. Esto podría deberse a problemas de red, URL incorrecta o un bloqueo de la web. Consulta los mensajes de error al inicio de esta sección.")
        st.markdown("---") 
