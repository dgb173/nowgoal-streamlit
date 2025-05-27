# modules/scrap.py

import streamlit as st
import requests  # Puede usarse para otras cosas o si en el futuro una API se vuelve disponible
from bs4 import BeautifulSoup
import pandas as pd
import re
import os
from playwright.sync_api import sync_playwright

# URL objetivo de Live Score
LIVE_SCORE_URL = "https://live18.nowgoal25.com/"


def fetch_html_with_playwright(url):
    """
    Descarga el contenido HTML de la URL usando Playwright para ejecutar JavaScript.
    Confía en que `start.sh` haya instalado los navegadores en la ubicación por defecto de Playwright.
    """
    st.info(f"🌐 Iniciando navegador headless (Playwright) para descargar: `{url}`")
    html_content = None
    browser = None

    try:
        with sync_playwright() as p:
            st.write("Depuración Playwright: Lanzando Chromium...")
            browser = p.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--single-process'  # Útil para limitar RAM en algunos entornos
                ],
            )
            page = browser.new_page()

            st.write(f"Depuración Playwright: Navegando a la URL: {url} (Timeout: 60s, Esperando 'networkidle')...")
            page.goto(url, timeout=60000, wait_until='networkidle')

            st.write("Depuración Playwright: Esperando que el selector `table#table_live` esté visible (Timeout: 30s)...")
            try:
                page.wait_for_selector('table#table_live', state='visible', timeout=30000)
                st.success("✅ Depuración Playwright: ¡Selector `table#table_live` encontrado y visible!")
            except Exception as e_selector:
                st.warning(f"⚠️ Depuración Playwright: ¡ADVERTENCIA! El selector `table#table_live` NO se encontró o NO está visible: {e_selector}")
                st.write("El scraper intentará continuar con el HTML actual, pero la tabla de partidos podría no estar presente.")
                st.write("HTML actual (primeros 2000 caracteres) para depuración:")
                st.code(page.content()[:2000]) # Para ver si la tabla no llegó a cargar
                
            html_content = page.content()
            st.success("✅ Contenido HTML renderizado descargado con éxito.")
            return html_content

    except Exception as e:
        st.error(f"❌ Error crítico con Playwright durante lanzamiento o navegación: {e}")
        st.info("💡 Por favor, revisa el mensaje detallado de Playwright. Lo más común es un problema con la instalación/ubicación de los binarios del navegador. Asegúrate de que tu `start.sh` en la raíz de tu repo se ejecute correctamente.")
        return None
    finally:
        if browser:
            try:
                browser.close()
                st.write("Depuración Playwright: Navegador Playwright cerrado.")
            except Exception as close_e:
                st.warning(f"Depuración Playwright: Error al cerrar el navegador en el `finally` block: {close_e}")


def clean_team_name(team_name_raw):
    """
    Limpia el nombre del equipo.
    """
    cleaned_name = re.sub(r'\[[^\]]*\]', '', team_name_raw)
    cleaned_name = re.sub(r'\s*\(\s*[Nn]\s*\)', '', cleaned_name)
    cleaned_name = re.sub(r'\s*\([^)]*\)\s*', '', cleaned_name)
    return cleaned_name.strip()

def is_upcoming_match(status_td_content, status_td_title):
    """
    Determina si un partido está "por comenzar".
    """
    status_text_lower = status_td_content.lower()
    status_title_lower = status_td_title.lower()

    live_or_finished_regex = re.compile(r'^\d+(\+\d+)?\s*(min)?$|^\s*(ht|ft|canc|postp|susp|live|aet|pen|pau|aban|int)\s*$', re.IGNORECASE)

    if live_or_finished_regex.search(status_text_lower):
        # st.write(f"  - Descartado (Estado Excluido - RegEx): `{status_text_lower}`") # Para depuración detallada
        return False
    
    if 'half' in status_title_lower or 'finished' in status_title_lower or 'postponed' in status_title_lower or \
       'cancelled' in status_title_lower or 'in-play' in status_title_lower or 'suspended' in status_title_lower or \
       'interrupted' in status_title_lower or 'abandoned' in status_title_lower or 'fulltime' in status_title_lower:
        # st.write(f"  - Descartado (Título Excluido): `{status_title_lower}`") # Para depuración detallada
        return False
        
    if status_td_content == '' and status_td_title == '':
        # st.write(f"  ✅ ¡CONFIRMADO! Estado/Título vacíos: `{status_td_content}`/`{status_td_title}`. PROGRAMADO.") # Para depuración detallada
        return True
    
    # st.write(f"  - Ambiguo/Desconocido: Estado `{status_td_content}` / Título `{status_td_title}`. No Programado.") # Para depuración detallada
    return False

def scrape_upcoming_matches_logic(html_content_raw):
    """
    Extrae los IDs y nombres de equipos de los partidos que AÚN NO HAN COMENZADO.
    """
    st.markdown("---") 
    st.subheader("🕵️‍♂️ **Registro Detallado de la Extracción de Partidos de NowGoal:**")
    st.markdown("---") 

    soup = BeautifulSoup(html_content_raw, 'html.parser')
    upcoming_matches_data = []
    main_match_table = None

    st.write("Depuración: Intentando localizar la tabla principal por ID `table_live`...")
    main_match_table = soup.find('table', id='table_live')

    if not main_match_table:
        st.write("Depuración: ID `table_live` NO ENCONTRADO. Buscando cualquier tabla con `scoretitle` y `tds`.")
        all_tables = soup.find_all('table')
        if not all_tables:
            st.error("❌ ERROR: No se encontró NINGUNA etiqueta `<table>` en el HTML.")
            return []

        for table in all_tables:
            if table.find('tr', class_='scoretitle') and table.find('tr', class_='tds'):
                main_match_table = table
                st.success(f"🎉 **Éxito!** Tabla principal encontrada por contenido. ID: `{table.get('id', 'N/A')}`, Clases: `{table.get('class', 'N/A')}`.")
                break 
        
        if not main_match_table:
            st.error("❌ ERROR CRÍTICO: No se encontró la tabla principal de partidos.")
            st.warning("El contenido está probablemente cargándose dinámicamente (JavaScript) y no se captura con `requests`. Considera usar librerías como Selenium o Playwright.")
            return []

    st.success("✅ **Tabla principal de partidos localizada.**")

    found_result_split = False
    rows_processed_count = 0
    upcoming_matches_count = 0

    all_trs_in_table = main_match_table.find_all('tr', recursive=False)
    
    if not all_trs_in_table:
        st.warning("Depuración: La tabla encontrada está vacía o no contiene filas `<tr>` directas.")
        return []

    st.info(f"Depuración: Iniciando análisis de {len(all_trs_in_table)} filas...")

    for row in all_trs_in_table:
        rows_processed_count += 1
        row_id = row.get('id', 'No ID')
        row_classes = row.get('class', [])
        
        # st.write(f"\n--- **Procesando Fila {rows_processed_count}: ID=`{row_id}`, Clases=`{row_classes}`** ---") # MÁS VERBOSO

        if 'result-split' in row_classes or row_id == 'resultSplit':
            found_result_split = True
            st.info("Depuración: Separador 'resultSplit' encontrado. Fin de partidos 'por comenzar'.")
            continue

        if found_result_split:
            continue

        if 'Leaguestitle' in row_classes or 'adtext-bg' in row_classes or 'ad_m' in row_classes or \
           ('tds' not in row_classes and row_id.startswith('tr')):
            st.write(f"Depuración: Fila {rows_processed_count} saltada (no es fila de partido).")
            continue

        if 'tds' in row_classes:
            match_id = row.get('matchid')

            if not match_id:
                st.write(f"Depuración: Fila 'tds' sin 'matchid'. Saltando.")
                continue 

            status_td = row.find('td', id=f'time_{match_id}', class_='status') 
            if not status_td:
                st.warning(f"Depuración: Partido {match_id} - Sin celda de estado. Saltando.")
                st.write(f"Raw HTML de fila: {str(row)[:200]}")
                continue
            
            time_data_td = row.find('td', {'name': 'timeData'})

            status_text_clean = status_td.get_text(strip=True)
            status_title_clean = status_td.get('title', '').strip()
            current_time_text_raw = time_data_td.get_text(strip=True) if time_data_td else "Hora N/A" 

            st.write(f"  - Clasificando MatchID `{match_id}`: Estado='{status_text_clean}', Título='{status_title_clean}', HoraVisible='{current_time_text_raw}'")

            if is_upcoming_match(status_text_clean, status_title_clean):
                upcoming_matches_count += 1
                
                home_team_tag = row.find('a', id=f'team1_{match_id}')
                away_team_tag = row.find('a', id=f'team2_{match_id}')
                
                home_team_name = clean_team_name(home_team_tag.get_text(strip=True)) if home_team_tag else "Local N/A"
                away_team_name = clean_team_name(away_team_tag.get_text(strip=True)) if away_team_tag else "Visitante N/A"
                
                match_time_utc = time_data_td.get('data-t') if time_data_td else "UTC N/A" 
                
                st.success(f"  ✅ **¡Partido Programado Encontrado!** ID: `{match_id}` | `{home_team_name}` vs `{away_team_name}` | Hora Vis: `{current_time_text_raw}`")

                upcoming_matches_data.append({
                    'id': match_id,
                    'hora_utc': match_time_utc,
                    'hora_visible': current_time_text_raw,
                    'equipo_local': home_team_name,
                    'equipo_visitante': away_team_name
                })
            # else:
                # st.write(f"  - Partido {match_id}: Descartado.") # Descomentar si necesitas depuración de "is_upcoming_match"

    st.markdown("---")
    st.info(f"**Análisis Finalizado:** Se revisaron {rows_processed_count} filas. Se encontraron **{upcoming_matches_count}** partidos programados.")
    if upcoming_matches_count == 0:
        st.warning("Si esperabas ver partidos y no se encontró ninguno, el sitio podría haber cambiado o no hay partidos programados actualmente. Verifica los mensajes de depuración anteriores.")
        if st.checkbox("Mostrar el HTML RAW que Playwright descargó (puede ser muy grande) para depurar:", key="raw_html_checkbox"):
            with st.expander("Contenido HTML Raw Completo"):
                st.code(html_content_raw)
    return upcoming_matches_data


def scrap():
    st.header("⚡ Scraper de Partidos Programados de NowGoal ⚡")
    st.markdown("""
    Esta herramienta se conecta a NowGoal.com utilizando un **navegador real** (headless) para ejecutar el JavaScript de la página
    y extraer los IDs, las horas (UTC y visible), y los nombres de los equipos de los partidos
    que **AÚN NO HAN COMENZADO (están programados)**.
    """)
    st.warning(f"**Aviso:** La URL de NowGoal (`{LIVE_SCORE_URL}`) y su estructura HTML pueden cambiar, lo que podría afectar el scraper.")
    st.markdown("---")
    
    html_content = None
    if st.button("🚀 ¡Extraer Partidos Programados Ahora de la Web!"):
        with st.spinner("Iniciando navegador, cargando página y analizando (puede tardar más de 1 minuto)..."):
            html_content = fetch_html_with_playwright(LIVE_SCORE_URL)

        if html_content:
            st.success("HTML de la página recibido de Playwright. Iniciando extracción de datos...")
            # Imprimir el HTML completo puede ser demasiado, así que solo una confirmación es mejor a menos que el usuario lo pida explícitamente.
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
                st.error("❌ **No se encontraron partidos programados.** Revisa el 'Registro Detallado' más arriba para identificar dónde falló el scraper o por qué se descartaron partidos.")
        else:
            st.error("🚫 No se pudo obtener el contenido HTML de la página web. Revisa los errores de Playwright en el registro.")

    st.markdown("---")
    st.info("Para problemas persistentes con Playwright en Streamlit Cloud, verifica el script `start.sh` y la [documentación de Playwright para CI](https://playwright.dev/docs/ci).")
