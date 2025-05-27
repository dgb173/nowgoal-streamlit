# modules/scrap.py

import streamlit as st
import requests # Aún se podría usar para casos de fallback o futuras APIs
from bs4 import BeautifulSoup
import pandas as pd
import re
import os # Para acceder a variables de entorno para playwright
from playwright.sync_api import sync_playwright # <-- Importar Playwright

# URL objetivo de Live Score
LIVE_SCORE_URL = "https://live18.nowgoal25.com/" 
# ¡IMPORTANTE! Este subdominio (live18) puede cambiar (live19, live20, etc.). 
# Si la app deja de cargar la página, lo primero es verificar y actualizar este LIVE_SCORE_URL.

# Usaremos esta variable de entorno para saber si estamos en Streamlit Cloud
# Esto es para configurar el path del browser de Playwright.
if os.environ.get('STREAMLIT_SERVER_RUN_ON_SAVE') == 'true':
    PLAYWRIGHT_CHROMIUM_PATH = os.path.expanduser('~/.cache/ms-playwright/chromium-1153/chrome-linux/chrome') # Path común en Linux para Playwright
else:
    PLAYWRIGHT_CHROMIUM_PATH = None # No necesario para ejecución local normalmente


def fetch_html_with_playwright(url):
    """
    Descarga el contenido HTML de la URL usando Playwright para ejecutar JavaScript.
    """
    st.info(f"🌐 Iniciando navegador headless para descargar: `{url}`")
    html_content = None
    try:
        with sync_playwright() as p:
            # Configurar el navegador Chrome
            browser = p.chromium.launch(
                headless=True, # Modo sin interfaz gráfica
                args=[
                    '--no-sandbox', # Necesario para entornos de contenedores como Streamlit Cloud
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage' # Resuelve problemas de memoria en Docker/contenedores
                ],
                # Si sabes el path exacto de los binarios, podrías usar executable_path,
                # pero el 'playwright install --with-deps' los pone en el cache por defecto
                # executable_path=PLAYWRIGHT_CHROMIUM_PATH # Comentar/Descomentar si es necesario un path específico
            )
            page = browser.new_page()
            
            st.write("Depuración Playwright: Navegando a la URL...")
            page.goto(url, timeout=60000) # Aumentar timeout de navegación a 60 segundos

            st.write("Depuración Playwright: Esperando que la tabla principal ('table_live') sea visible...")
            # Esperar a que la tabla o un selector representativo del contenido cargue
            # Ajusta este selector si el ID 'table_live' no es el que aparece tras JS.
            # Puedes usar CSS selector (table#table_live) o XPath.
            try:
                # Esperar hasta que el elemento de la tabla exista en el DOM y sea visible
                page.wait_for_selector('table#table_live', state='visible', timeout=30000) # Espera 30 segundos
                st.success("✅ Depuración Playwright: ¡Tabla principal (`table#table_live`) detectada en el DOM y visible!")
            except Exception as e:
                st.warning(f"⚠️ Depuración Playwright: ¡ADVERTENCIA! La tabla `table#table_live` no apareció a tiempo o está oculta: {e}")
                st.write("Intentando continuar con el HTML actual, podría estar parcial o el selector de espera no es preciso.")
                # Continúa de todos modos para obtener el HTML actual y permitir la depuración manual

            html_content = page.content()
            browser.close()
            st.success("✅ Contenido HTML descargado y navegador cerrado.")
            return html_content
            
    except Exception as e:
        st.error(f"❌ Error con Playwright: {e}")
        st.info("💡 Asegúrate de que los binarios del navegador de Playwright estén instalados. En Streamlit Cloud, el `start.sh` debe ejecutar `playwright install --with-deps`.")
        st.code("""
# Ejemplo de start.sh (en la raíz de tu repositorio)
#!/bin/bash
echo "Installing Playwright browsers..."
playwright install --with-deps chromium # Puedes añadir firefox, webkit si los necesitas
echo "Starting Streamlit app..."
streamlit run scraper_app.py --server.port $PORT --server.enableCORS false --server.enableXsrfProtection false
        """)
        return None


def clean_team_name(team_name_raw):
    """
    Limpia el nombre del equipo, removiendo cualquier anotación de ranking (ej. "[LIT D1-8]")
    o neutralidad "(N)", o corchetes que no sean de ranking, etc.
    """
    # ... (La lógica de esta función se mantiene igual)
    cleaned_name = re.sub(r'\[[^\]]*\]', '', team_name_raw) # Eliminar texto dentro de corchetes
    cleaned_name = re.sub(r'\s*\(\s*[Nn]\s*\)', '', cleaned_name) # Eliminar texto dentro de paréntesis que contenga '(N)'
    cleaned_name = re.sub(r'\s*\([^)]*\)\s*', '', cleaned_name) # Eliminar otros paréntesis
    return cleaned_name.strip()

def is_upcoming_match(status_td_content, status_td_title):
    """
    Determina si un partido está "por comenzar" basándose en el texto de su celda de estado
    y su atributo `title`. La lógica más robusta es EXCLUIR los que YA tienen un estado definido.
    """
    # ... (La lógica de esta función se mantiene igual, es bastante robusta)
    status_text_lower = status_td_content.lower()
    status_title_lower = status_td_title.lower()

    live_or_finished_regex = re.compile(r'^\d+(\+\d+)?\s*($|\w)|^\s*(ht|ft|canc|postp|susp|live)\s*$', re.IGNORECASE)

    if live_or_finished_regex.search(status_text_lower):
        st.write(f"  - Descartado (Estado Excluido - RegEx): `{status_text_lower}` coincide con LIVE/FINISHED/CANCELLED/POSTPONED.")
        return False
    
    if 'half' in status_title_lower or \
       'finished' in status_title_lower or \
       'postponed' in status_title_lower or \
       'cancelled' in status_title_lower or \
       'in-play' in status_title_lower or \
       'suspended' in status_title_lower:
        st.write(f"  - Descartado (Título Excluido): `{status_title_lower}` indica LIVE/FINISHED/CANCELLED/POSTPONED.")
        return False
        
    if status_td_content == '' and status_td_title == '':
        st.write(f"  ✅ ¡CONFIRMADO! Celdas de estado (`'{status_td_content}'` / `'{status_td_title}'`) ambas vacías. Es PROGRAMADO.")
        return True
    
    st.write(f"  - Ambiguo/Desconocido: Estado `{status_td_content}` / Título `{status_td_title}`. No se clasifica como PROGRAMADO.")
    return False

def scrape_upcoming_matches_logic(html_content_raw):
    """
    Extrae los IDs, nombres de equipos, y horas de los partidos que AÚN NO HAN COMENZADO.
    Prioriza robustez al encontrar elementos y añade mucha depuración.
    """
    st.markdown("---") # Separador para claridad de depuración
    st.subheader("🕵️‍♂️ **Registro Detallado de la Extracción de Partidos de NowGoal:**")
    st.markdown("---") 

    soup = BeautifulSoup(html_content_raw, 'html.parser')
    upcoming_matches_data = []

    # Estrategia robusta para encontrar la tabla principal
    main_match_table = None

    # Primero intentamos el ID común
    st.write("Depuración: Intentando buscar la tabla principal de partidos por ID `table_live`...")
    main_match_table = soup.find('table', id='table_live')

    if not main_match_table:
        st.write("Depuración: ID `table_live` NO ENCONTRADO. Buscando cualquier tabla con una cabecera (`scoretitle`) y una fila de partido (`tds`).")
        all_tables = soup.find_all('table')
        if not all_tables:
            st.error("❌ ERROR: No se encontró NINGUNA tabla en el HTML analizado.")
            return []

        for table in all_tables:
            if table.find('tr', class_='scoretitle') and table.find('tr', class_='tds'):
                main_match_table = table
                st.success(f"🎉 **Éxito!** Tabla principal encontrada por contenido. ID: `{table.get('id', 'N/A')}`, Clases: `{table.get('class', 'N/A')}`.")
                break # Encontrado, salimos del bucle
        
        if not main_match_table:
            st.error("❌ ERROR CRÍTICO: No se encontró la tabla principal de partidos ni por ID (`table_live`) ni por la combinación de clases (`scoretitle` y `tds`).")
            st.warning("Esto podría indicar un cambio de estructura HTML muy significativo o que el contenido aún no se ha cargado/renderizado correctamente.")
            return []

    st.success("✅ **Tabla principal de partidos encontrada.**")

    # Banderas para controlar el flujo
    found_result_split = False
    rows_processed_count = 0
    upcoming_matches_count = 0

    all_trs_in_table = main_match_table.find_all('tr', recursive=False)
    
    if not all_trs_in_table:
        st.warning("Depuración: La tabla de partidos encontrada está vacía o no contiene filas `<tr>` directas. ¡Inesperado!")
        return []

    st.info(f"Depuración: Iniciando análisis de {len(all_trs_in_table)} filas dentro de la tabla...")

    for row in all_trs_in_table:
        rows_processed_count += 1
        row_id = row.get('id', 'No ID')
        row_classes = row.get('class', [])
        
        st.write(f"\n--- **Procesando Fila {rows_processed_count}: ID=`{row_id}`, Clases=`{row_classes}`** ---")

        # Detectar el separador de resultados (pueden cambiar con el tiempo)
        if 'result-split' in row_classes or row_id == 'resultSplit':
            found_result_split = True
            st.info("Depuración: Detectado separador de Resultados. Los siguientes partidos son RESULTADOS y serán ignorados para 'Próximos'.")
            continue

        # Si ya encontramos el separador, omitir el resto de las filas
        if found_result_split:
            st.write("Depuración: Saltando fila. Ya estamos en la sección de Resultados.")
            continue

        # Ignorar filas de títulos de liga, anuncios o filas de pie (tr3_xxx) que no contienen matchid principal
        # Las filas tr3_xxx pueden tener display:none
        if 'Leaguestitle' in row_classes or 'adtext-bg' in row_classes or 'ad_m' in row_classes or (row_id.startswith('tr3_') and not row.get('matchid')):
            st.write("Depuración: Saltando fila: Es título de liga, anuncio, o fila de metadatos irrelevante.")
            continue

        # Si es una fila de partido 'tds'
        if 'tds' in row_classes:
            match_id = row.get('matchid')

            if not match_id:
                st.warning(f"Depuración: Fila `tds` {rows_processed_count} no tiene 'matchid'. Contenido: `{row.get_text(strip=True)[:100]}`. Saltando.")
                continue

            # Buscar la celda de estado (tiempo de juego o 'HT', 'FT', etc.). Id: time_{match_id}, Class: status
            status_td = row.find('td', id=f'time_{match_id}', class_='status') 
            if not status_td:
                st.warning(f"¡ADVERTENCIA! Para Partido ID `{match_id}` (Fila {rows_processed_count}), no se encontró la celda de estado (`id=time_{match_id}`, `class=status`). Es CRÍTICO para clasificar. Saltando.")
                st.write(f"Raw HTML de esta fila para depuración: `{str(row)[:500]}`")
                continue
            
            # Buscar la celda que contiene la hora de inicio visible (data-t para UTC, y texto para la hora visible)
            time_data_td = row.find('td', {'name': 'timeData'})

            # Extraer y limpiar contenido de las celdas
            status_text_clean = status_td.get_text(strip=True)
            status_title_clean = status_td.get('title', '').strip()
            # Esta es la hora visible en la página
            current_time_text_raw = time_data_td.get_text(strip=True) if time_data_td else "Hora_TD_N/A" 

            st.write(f"  **- Detalles para Partido ID `{match_id}`:**")
            st.write(f"    - `status_td` Contenido (limpio): `'{status_text_clean}'`")
            st.write(f"    - `status_td` Atributo `title` (limpio): `'{status_title_clean}'`")
            st.write(f"    - `timeData_td` Contenido (hora visible): `'{current_time_text_raw}'`")


            if is_upcoming_match(status_text_clean, status_title_clean):
                upcoming_matches_count += 1
                # Extraer nombres de los equipos y la hora UTC
                home_team_raw_link = row.find('a', id=f'team1_{match_id}') # El enlace <a> con el nombre del equipo local
                away_team_raw_link = row.find('a', id=f'team2_{match_id}') # El enlace <a> con el nombre del equipo visitante
                
                # Accedemos a la TD para el equipo local y obtenemos su texto. A veces, la fuente <a> está dentro de otra etiqueta.
                # Intentamos buscar el <td> por su id de equipo.
                home_td = row.find('td', id=f'ht_{match_id}') 
                away_td = row.find('td', id=f'gt_{match_id}') 

                # Si el <a> no se encuentra directamente, buscaremos el nombre del equipo en el <td> padre.
                home_team_name = clean_team_name(home_team_raw_link.get_text(strip=True)) if home_team_raw_link else (clean_team_name(home_td.get_text(strip=True)) if home_td else f"Local {match_id} N/A")
                away_team_name = clean_team_name(away_team_raw_link.get_text(strip=True)) if away_team_raw_link else (clean_team_name(away_td.get_text(strip=True)) if away_td else f"Visitante {match_id} N/A")
                
                # La hora UTC siempre está en el atributo 'data-t' del td con name='timeData'
                match_time_utc = time_data_td.get('data-t') if time_data_td else "Hora_UTC_N/A" 
                
                st.success(f"  🎉 **¡PARTIDO PROGRAMADO ENCONTRADO!** ID: `{match_id}` - `{home_team_name}` vs `{away_team_name}` (Hora Visible: {current_time_text_raw})")

                upcoming_matches_data.append({
                    'id': match_id,
                    'hora_utc': match_time_utc,
                    'hora_visible': current_time_text_raw,
                    'equipo_local': home_team_name,
                    'equipo_visitante': away_team_name
                })
            else:
                st.write(f"  Partido ID `{match_id}` (Fila {rows_processed_count}) descartado como PROGRAMADO.")
        else:
            st.write(f"Depuración: Fila {rows_processed_count} no es una fila 'tds' (es una cabecera de liga, anuncio, etc.). Saltando.")

    st.markdown("---")
    st.info(f"**Análisis Finalizado:** Se revisaron {rows_processed_count} filas. Se encontraron **{upcoming_matches_count}** partidos programados.")
    if upcoming_matches_count == 0:
        st.warning("Si esperabas ver partidos y no se encontró ninguno, el sitio podría haber cambiado o no hay partidos programados.")
        
    return upcoming_matches_data

# Función principal que será llamada desde main.py (Streamlit UI)
def scrap():
    st.header("⚡ Scraper de Partidos Programados de NowGoal ⚡")
    st.markdown("""
    Esta herramienta se conecta a NowGoal.com utilizando un **navegador real** (headless) para ejecutar el JavaScript de la página
    y extraer los IDs, las horas (UTC y visible), y los nombres de los equipos de los partidos
    que **AÚN NO HAN COMENZADO (están programados)**.
    """)
    st.warning(f"**Aviso:** La URL de NowGoal y su estructura HTML pueden cambiar. Asegúrate de que esta URL esté actualizada si hay problemas: `{LIVE_SCORE_URL}`")
    st.markdown("---")

    # Si se selecciona desde la web, intentamos la extracción con Playwright
    if st.button("🚀 ¡Extraer Partidos Programados Ahora de la Web!"):
        st.markdown("---") 
        html_content = None
        with st.spinner("Iniciando navegador y descargando HTML (puede tardar más)..."):
            html_content = fetch_html_with_playwright(LIVE_SCORE_URL)

        if html_content:
            # Aquí es donde verás si Playwright ha descargado el contenido correcto
            st.write(f"HTML descargado por Playwright (primeros 1000 chars): `{html_content[:1000]}`")
            # Deberías poder ver la tabla table_live en este extracto si fue cargado por JS
            
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
                st.error("❌ **No se encontraron partidos programados en el HTML descargado de la web.** Esto puede deberse a:")
                st.markdown("""
                *   Ahora mismo no hay partidos programados para el día en la página.
                *   La página cambió la estructura HTML o el selector (`table#table_live`) no es correcto.
                *   La espera de Playwright no fue suficiente o hay otras condiciones que impiden la carga del contenido.

                **⚠️ ¡IMPORTANTE! Revisa la sección de 'Registro Detallado de la Extracción' y el HTML RAW impreso más arriba. Te indicarán dónde exactamente falla el proceso.**
                """)
        else:
            st.error("🚫 No se pudo obtener el contenido HTML de la página web mediante Playwright. Revisa los mensajes de error del navegador Playwright (más arriba en el log de depuración).")
    
    st.markdown("---")
    st.info("Recuerda, los cambios en el diseño web de NowGoal pueden hacer que este scraper deje de funcionar.")
