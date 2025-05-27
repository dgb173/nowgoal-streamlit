# modules/scrap.py

import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import re

# URL objetivo de Live Score
# ¡IMPORTANTE! Este subdominio (live18) puede cambiar (live19, live20, etc.).
# Si la app deja de cargar la página, lo primero es verificar y actualizar este LIVE_SCORE_URL.
LIVE_SCORE_URL = "https://live18.nowgoal25.com/"

def fetch_html(url):
    """
    Realiza una solicitud HTTP GET a la URL y devuelve el contenido HTML.
    Maneja posibles errores de conexión y de timeout.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    st.info(f"🌐 Intentando descargar HTML de: `{url}` con User-Agent de Chrome.")
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        st.success("✅ HTML descargado exitosamente. Código de estado: " + str(response.status_code))
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
    cleaned_name = re.sub(r'\[[^\]]*\]', '', team_name_raw) # Eliminar texto dentro de corchetes
    cleaned_name = re.sub(r'\s*\(\s*[Nn]\s*\)', '', cleaned_name) # Eliminar texto dentro de paréntesis que contenga '(N)'
    cleaned_name = re.sub(r'\s*\([^)]*\)\s*', '', cleaned_name) # Eliminar otros paréntesis
    return cleaned_name.strip()

def is_upcoming_match(status_td_content, status_td_title):
    """
    Determina si un partido está "por comenzar" basándose en el texto de su celda de estado
    y su atributo `title`. La lógica más robusta es EXCLUIR los que YA tienen un estado definido.
    """
    status_text_lower = status_td_content.lower()
    status_title_lower = status_td_title.lower()

    # Patrones RegEx para identificar estados que NO son "por comenzar"
    # Estos son los estados de partidos en curso o terminados (e.g. "90+X", "HT", "FT")
    # o partidos pospuestos/cancelados ("Canc", "Postp").
    live_or_finished_regex = re.compile(r'^\d+(\+\d+)?(?!\S)|^\s*(ht|ft|canc|postp|susp|live)\s*$', re.IGNORECASE)

    # Si el texto de la celda de estado coincide con un patrón de en-juego/finalizado/cancelado/postergado
    # La "!\S" en el regex es una "negative lookahead" para asegurar que '90' no sea seguido de 'min' u otra cosa, 
    # y solo considere números si es el texto completo del status (no parte de un texto más grande).
    if live_or_finished_regex.search(status_text_lower):
        st.write(f"  - Descartado (Estado Excluido - RegEx): `{status_text_lower}` coincide con LIVE/FINISHED/CANCELLED/POSTPONED.")
        return False
    
    # Si el atributo 'title' indica que el partido ya comenzó, terminó, fue pospuesto o cancelado
    # Estos suelen ser más descriptivos, como "1st Half", "Finished", etc.
    if 'half' in status_title_lower or \
       'finished' in status_title_lower or \
       'postponed' in status_title_lower or \
       'cancelled' in status_title_lower or \
       'in-play' in status_title_lower or \
       'suspended' in status_title_lower:
        st.write(f"  - Descartado (Título Excluido): `{status_title_lower}` indica LIVE/FINISHED/CANCELLED/POSTPONED.")
        return False
        
    # Un partido por comenzar idealmente tiene su celda de estado completamente vacía (lo que resulta en '' al strip())
    # y también un `title` vacío. Este es el caso más claro para "por comenzar".
    if status_td_content == '' and status_td_title == '':
        st.write(f"  ✅ ¡CONFIRMADO! Celdas de estado (`'{status_td_content}'` / `'{status_td_title}'`) ambas vacías. Es PROGRAMADO.")
        return True
    
    # Para cualquier otro caso que no se haya descartado explícitamente ni se haya confirmado como vacío,
    # podríamos querer añadir una bandera de advertencia o revisarlos manualmente.
    # Por ahora, los descartamos si no cumplen la condición clara de "vacío".
    st.write(f"  - Ambiguo/Desconocido: Estado `{status_td_content}` / Título `{status_td_title}`. No se clasifica como PROGRAMADO.")
    return False

def scrape_upcoming_matches_logic(html_content_raw):
    """
    Extrae los IDs, nombres de equipos, y horas de los partidos que AÚN NO HAN COMENZADO.
    Prioriza robustez al encontrar elementos y añade mucha depuración.
    """
    st.subheader("🕵️‍♂️ **Registro Detallado de la Extracción:**")
    st.markdown("---") # Separador para claridad de depuración

    soup = BeautifulSoup(html_content_raw, 'html.parser')
    upcoming_matches_data = []

    # **Paso 1: Localizar el contenedor principal que alberga la tabla de partidos.**
    # Intentamos primero el ID 'mintable', que parece ser estable.
    mintable_div = soup.find('div', id='mintable')
    
    if not mintable_div:
        st.error("❌ ERROR: No se encontró el `<div>` contenedor principal (ID: `mintable`).")
        st.write("Ahora buscando la tabla de partidos directamente en el HTML, de forma más genérica.")
        # Intentamos encontrar la tabla sin depender del div 'mintable' si falla.

    main_match_table = None

    # Primero intentamos el ID común de la tabla principal
    if mintable_div:
        main_match_table = mintable_div.find('table', id='table_live')
    
    if not main_match_table: # Si falló con mintable o mintable no existe
        st.write("Depuración: ID `table_live` NO ENCONTRADO en el `mintable` o `mintable` no existe. Intentando buscar cualquier `table` con la clase 'scoretitle' para su cabecera y 'tds' para sus filas de datos.")
        # Buscamos cualquier tabla en todo el HTML que contenga tanto un encabezado de puntuación como filas de datos de partidos
        all_tables = soup.find_all('table')
        if not all_tables:
            st.error("❌ ERROR: No se encontró NINGUNA etiqueta `<table>` en el HTML analizado.")
            st.info("Esto sugiere que la página no ha cargado los datos de la tabla, probablemente es **contenido dinámico (JavaScript)**.")
            return []

        for table in all_tables:
            # Comprobamos si la tabla tiene una fila de cabecera típica de NowGoal Y al menos una fila de datos de partido
            if table.find('tr', class_='scoretitle') and table.find('tr', class_='tds'):
                main_match_table = table
                st.write(f"🎉 **Éxito!** Tabla principal encontrada por contenido. ID: `{table.get('id', 'N/A')}`, Clases: `{table.get('class', 'N/A')}`.")
                break # Encontrado, salimos del bucle
        
        if not main_match_table:
            st.error("❌ ERROR CRÍTICO: No se encontró la tabla principal de partidos ni por ID específico (`table_live`) ni por contenido (`scoretitle` y `tds`).")
            st.warning("Esto es el síntoma de que el contenido está cargándose **dinámicamente via JavaScript** y `requests` no puede verlo, o que la estructura del HTML ha cambiado radicalmente.")
            st.markdown("""
            **Sugerencia Urgente:**
            Para raspar sitios con contenido dinámico, necesitarás una librería como **Selenium** o **Playwright**.
            Estas librerías lanzan un navegador real (invisible), esperan que el JavaScript cargue, y luego extraen el HTML.

            ```python
            # Ejemplo BÁSICO con Selenium (instalación más compleja):
            # from selenium import webdriver
            # from selenium.webdriver.chrome.service import Service
            # from selenium.webdriver.chrome.options import Options
            # from webdriver_manager.chrome import ChromeDriverManager
            
            # chrome_options = Options()
            # chrome_options.add_argument("--headless") # Ejecutar en modo sin cabeza (sin ventana de navegador visible)
            # chrome_options.add_argument("--no-sandbox") # Necesario para algunos entornos (ej. Docker, Streamlit Cloud)
            # chrome_options.add_argument("--disable-dev-shm-usage") # Lo mismo
            # service = Service(ChromeDriverManager().install())
            # driver = webdriver.Chrome(service=service, options=chrome_options)
            # driver.get(LIVE_SCORE_URL)
            # import time; time.sleep(5) # Dale tiempo a JavaScript para cargar
            # html_content = driver.page_source
            # driver.quit()
            # soup = BeautifulSoup(html_content, 'html.parser')
            # ... entonces continúas con el scraping normal sobre esta `soup`.
            ```
            Esto está más allá del alcance de un "scraper simple" y esta aplicación.
            """)
            return []

    # Una vez que la tabla se ha localizado (main_match_table NO es None)
    st.success("✅ **ÉXITO: Se ha localizado la tabla principal de partidos.**")

    # Bandera para identificar el separador "Results" (partidos terminados)
    found_result_split = False
    rows_processed_count = 0
    upcoming_matches_count = 0

    all_trs_in_table = main_match_table.find_all('tr', recursive=False)
    
    if not all_trs_in_table:
        st.warning("Depuración: La tabla de partidos encontrada no contiene filas `<tr>` directas. (¡Es inesperado!)")
        return []

    st.info(f"Depuración: Iniciando análisis de {len(all_trs_in_table)} filas dentro de la tabla principal...")

    for row in all_trs_in_table:
        rows_processed_count += 1
        row_id = row.get('id', 'No ID')
        row_classes = row.get('class', [])
        
        st.write(f"\n--- **Procesando Fila {rows_processed_count}: ID=`{row_id}`, Clases=`{row_classes}`** ---")

        # Detectar el separador de resultados
        if row_id == 'resultSplit':
            found_result_split = True
            st.info("Depuración: Detectado `resultSplit`. Los siguientes partidos son RESULTADOS y serán ignorados para 'Próximos'.")
            continue

        # Una vez que hemos pasado el separador, el resto de las filas son resultados y no nos interesan
        if found_result_split:
            st.write("Depuración: Saltando fila, ya que se encontró `resultSplit` anteriormente. Esta fila es un partido TERMINADO.")
            continue

        # Ignorar filas de títulos de liga o anuncios
        if 'Leaguestitle' in row_classes or 'adtext-bg' in row_classes or 'ad_m' in row_classes or row_id.startswith('tr3_') or row_id.startswith('tr_ad'):
            st.write("Depuración: Saltando fila: Es título de liga o anuncio.")
            continue

        # Si no es un separador, título o anuncio, y es una fila de partido 'tds'
        if 'tds' in row_classes:
            match_id = row.get('matchid')

            if not match_id:
                st.warning(f"Depuración: Fila 'tds' {rows_processed_count} pero sin 'matchid'. Contenido de fila: `{row.get_text(strip=True)[:100]}`. Saltando.")
                continue # Fila 'tds' pero sin matchid, rara.

            # Buscar la celda de estado (tiempo de juego o 'HT', 'FT', etc.)
            status_td = row.find('td', id=f'time_{match_id}', class_='status') 
            if not status_td:
                st.warning(f"¡ADVERTENCIA! Para Partido ID `{match_id}` (Fila {rows_processed_count}), no se encontró la celda de estado (`id=time_{match_id}`, class=`status`). Es CRÍTICO para clasificar. Saltando.")
                st.write(f"Raw HTML de esta fila para depuración: `{str(row)[:500]}`") # Print some raw HTML
                continue
            
            # Buscar la celda que tiene la hora de inicio (td con name='timeData')
            time_data_td = row.find('td', {'name': 'timeData'})

            # Extraer contenido y título de la celda de estado
            status_text_clean = status_td.get_text(strip=True)
            status_title_clean = status_td.get('title', '').strip()
            current_time_text_raw = time_data_td.get_text(strip=True) if time_data_td else "Hora_TD_N/A"

            # Utilizar la función de clasificación para determinar si es un partido por comenzar
            st.write(f"  **- Clasificando Partido ID `{match_id}` (Fila {rows_processed_count}):**")
            st.write(f"    - `status_td` Contenido (limpio): `'{status_text_clean}'`")
            st.write(f"    - `status_td` Atributo `title` (limpio): `'{status_title_clean}'`")
            st.write(f"    - `timeData` Contenido (hora/minutos visibles): `'{current_time_text_raw}'`")

            if is_upcoming_match(status_text_clean, status_title_clean):
                upcoming_matches_count += 1
                # Extraer nombres de los equipos y la hora UTC
                home_team_raw = row.find('a', id=f'team1_{match_id}')
                away_team_raw = row.find('a', id=f'team2_{match_id}')
                
                home_team_name = clean_team_name(home_team_raw.get_text(strip=True)) if home_team_raw else f"Equipo Local {match_id} (No Encontrado)"
                away_team_name = clean_team_name(away_team_tag.get_text(strip=True)) if away_team_tag else f"Equipo Visitante {match_id} (No Encontrado)"
                
                match_time_utc = time_data_td.get('data-t') if time_data_td else "Hora_UTC_N/A" 
                
                st.success(f"  🎉 **¡PARTIDO PROGRAMADO ENCONTRADO!** ID: `{match_id}` - {home_team_name} vs {away_team_name} (Hora Visible: {current_time_text_raw})")

                upcoming_matches_data.append({
                    'id': match_id,
                    'hora_utc': match_time_utc,
                    'hora_visible': current_time_text_raw,
                    'equipo_local': home_team_name,
                    'equipo_visitante': away_team_name
                })
            else:
                st.write(f"  Partido ID `{match_id}` (Fila {rows_processed_count}) fue descartado como PROGRAMADO.")
        else:
            st.write(f"Depuración: Fila {rows_processed_count} no tiene la clase 'tds' (ej. es una cabecera, una fila vacía o un anuncio). Saltando.")

    st.info(f"**Análisis Finalizado:** Se revisaron {rows_processed_count} filas. Se encontraron **{upcoming_matches_count}** partidos programados.")
    if upcoming_matches_count == 0:
        st.warning("Si esperabas ver partidos y no se encontró ninguno, el sitio podría haber cambiado o no hay partidos programados.")
        st.markdown("---") # Separador para la siguiente sección
        st.info("Para entender mejor la razón de 'no matches found', te ofrecemos la opción de ver el HTML RAW que Streamlit ha descargado:")
        if st.checkbox("Mostrar el HTML RAW que Streamlit descargó (puede ser muy grande)"):
            with st.expander("Ver HTML Raw"):
                st.code(html_content_raw) # Esto es crucial si fetch_html está retornando una página esqueleto

    return upcoming_matches_data

# Función principal que será llamada desde main.py (Streamlit UI)
def scrap():
    st.header("⚡ Scraper de Partidos Programados de NowGoal ⚡")
    st.markdown("""
    Esta herramienta se conecta directamente a Nowgoal.com para extraer los IDs, las horas (UTC y visible),
    y los nombres de los equipos de los partidos que **AÚN NO HAN COMENZADO (están programados)**.
    """)
    st.warning(f"**Aviso:** La URL de NowGoal y su estructura HTML pueden cambiar frecuentemente, lo que podría 'romper' el scraper. Actualmente la URL es: `{LIVE_SCORE_URL}`")
    st.markdown("---")

    html_source_selection = st.radio(
        "¿De dónde quieres obtener el HTML?",
        ("Desde la web (recomendado para probar)", "Pegar HTML manualmente (para depuración avanzada)"),
        key="html_source_type"
    )

    html_content = None
    if html_source_selection == "Desde la web (recomendado para probar)":
        if st.button("🚀 ¡Extraer Partidos Programados Ahora de la Web!"):
            st.markdown("---")
            with st.spinner("Conectando y analizando el sitio, por favor espera..."):
                html_content = fetch_html(LIVE_SCORE_URL) # La URL se usa aquí
    else: # Pegar HTML manualmente
        st.info("Pega el HTML COMPLETO aquí para que el scraper intente procesarlo localmente. Esto es útil si sospechas que el fetcher no trae todo el contenido.")
        pasted_html = st.text_area("Pega el contenido HTML completo aquí:", height=400, key="manual_html_input")
        if st.button("🚀 ¡Extraer Partidos Programados del HTML Pegado!"):
            if pasted_html:
                html_content = pasted_html
            else:
                st.warning("Por favor, pega el contenido HTML en el cuadro de texto para comenzar.")


    if html_content: # Si tenemos contenido HTML (ya sea de la web o pegado)
        if html_source_selection == "Desde la web (recomendado para probar)":
             # Mostrar el HTML raw para depuración si el usuario ha solicitado la extracción web
             if st.checkbox("Mostrar el HTML RAW que Streamlit **obtuvo de la web** (solo si no se encontró nada o para depuración profunda)"):
                with st.expander("Ver HTML Raw Descargado (hasta 5000 chars)"):
                    st.code(html_content[:5000]) # Muestra solo los primeros 5000 caracteres

        matches = scrape_upcoming_matches_logic(html_content)

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
            if html_source_selection == "Pegar HTML manualmente (para depuración avanzada)":
                st.error("❌ No se encontraron partidos programados en el HTML que pegaste.")
            else: # HTML de la web, y no se encontró
                st.error("❌ No se encontraron partidos programados en el HTML descargado de la web.")
            st.info("Revisa la sección de 'Registro Detallado de la Extracción' más arriba. Te indicará dónde falla el proceso, lo que sugiere posibles cambios en la estructura de NowGoal o problemas de carga de contenido.")

    st.markdown("---") # Separador al final de la ejecución
    st.info("Recuerda, los cambios en el diseño web de NowGoal pueden hacer que este scraper deje de funcionar.")
