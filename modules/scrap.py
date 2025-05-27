# modules/scrap.py

import streamlit as st
import requests 
from bs4 import BeautifulSoup
import pandas as pd
import re
import os # Aún se necesita para Playwright, no importa si se usa o no explícitamente


from playwright.sync_api import sync_playwright # <-- Importar Playwright

# URL objetivo de Live Score
LIVE_SCORE_URL = "https://live18.nowgoal25.com/" 
# ¡IMPORTANTE! Verificar manualmente si el subdominio (live18) cambia, ya que afecta la accesibilidad.


def fetch_html_with_playwright(url):
    """
    Descarga el contenido HTML de la URL usando Playwright para ejecutar JavaScript.
    """
    st.info(f"🌐 Iniciando navegador headless para descargar: `{url}`")
    html_content = None
    browser = None # Inicializar a None para asegurar que se cierre en `finally`

    try:
        with sync_playwright() as p:
            # Opción para lanzar Chromium
            # Playwright automáticamente usará PLAYWRIGHT_BROWSERS_PATH si está definido en el entorno.
            # No se necesita `executable_path` aquí.
            browser = p.chromium.launch(
                headless=True, # Modo sin interfaz gráfica
                args=[
                    '--no-sandbox',               # Crucial para entornos de contenedores como Streamlit Cloud
                    '--disable-setuid-sandbox',   # Seguridad
                    '--disable-dev-shm-usage',    # Resuelve problemas de memoria en Docker/contenedores
                    '--single-process'            # Para conservar recursos en entornos con RAM limitada
                ],
            )
            page = browser.new_page()
            
            st.write(f"Depuración Playwright: Navegando a la URL: {url} (Timeout: 60s, Esperando red inactiva)...")
            page.goto(url, timeout=60000, wait_until='networkidle') # wait_until='networkidle' es clave: espera que no haya nuevas solicitudes de red por un tiempo.

            st.write("Depuración Playwright: Esperando que la tabla principal (`table#table_live`) sea visible (Timeout: 30s)...")
            try:
                # Asegúrate de que este selector CSS sea el correcto si ha cambiado la web.
                # Puedes ajustarlo a, por ejemplo: 'div#mintable table' si 'table#table_live' es inestable.
                page.wait_for_selector('table#table_live', state='visible', timeout=30000) 
                st.success("✅ Depuración Playwright: ¡Tabla principal (`table#table_live`) detectada en el DOM y es visible!")
            except Exception as e:
                st.warning(f"⚠️ Depuración Playwright: ¡ADVERTENCIA! La tabla `table#table_live` NO apareció a tiempo o no es visible: {e}")
                st.write("Se continuará con el HTML disponible para depuración. Esto podría ser el motivo si no se encuentran partidos.")
                
            html_content = page.content() # Obtener el HTML renderizado (con JS ejecutado)
            st.success("✅ Contenido HTML renderizado descargado con éxito.")
            return html_content
            
    except Exception as e:
        st.error(f"❌ Error crítico con Playwright: {e}")
        st.info("💡 Este error se da al intentar lanzar el navegador de Playwright.")
        st.markdown("**Por favor, revisa el código `start.sh` de tu repositorio.** Es lo más importante. Asegúrate de que:")
        st.markdown("- Contenga `playwright install chromium --with-deps --install-dir \"$PLAYWRIGHT_BROWSERS_PATH\"`.")
        st.markdown("- Contenga `export PLAYWRIGHT_BROWSERS_PATH=\"$(pwd)/.playwright_browsers\"`.")
        st.markdown("- Los pasos se ejecuten en el orden correcto.")
        st.markdown("- Tu repositorio de GitHub no tenga archivos inesperados (`.gitignore` suele excluir `.playwright_browsers`).")
        return None
    finally:
        if browser: 
            try:
                browser.close()
                st.write("Depuración Playwright: Navegador Playwright cerrado.")
            except Exception as close_e:
                st.warning(f"Depuración Playwright: Error al cerrar el navegador en el `finally` block: {close_e}")


# --- is_upcoming_match, clean_team_name, y scrape_upcoming_matches_logic se mantienen. ---
# Simplemente añade el código restante de la versión anterior debajo de estas funciones.

def clean_team_name(team_name_raw):
    """Limpia el nombre del equipo, removiendo cualquier anotación de ranking (ej. "[LIT D1-8]") o neutralidad "(N)", etc."""
    cleaned_name = re.sub(r'\[[^\]]*\]', '', team_name_raw) 
    cleaned_name = re.sub(r'\s*\(\s*[Nn]\s*\)', '', cleaned_name)
    cleaned_name = re.sub(r'\s*\([^)]*\)\s*', '', cleaned_name) 
    return cleaned_name.strip()

def is_upcoming_match(status_td_content, status_td_title):
    """Determina si un partido está "por comenzar" basándose en el texto de su celda de estado y su atributo `title`."""
    status_text_lower = status_td_content.lower()
    status_title_lower = status_td_title.lower()
    live_or_finished_regex = re.compile(r'^\d+(\+\d+)?\s*(min)?$|^\s*(ht|ft|canc|postp|susp|live|aet|pen|pau|aban|int)\s*$', re.IGNORECASE)

    if live_or_finished_regex.search(status_text_lower):
        st.write(f"  - Descartado (Estado del TD indica activo/finalizado/etc.): `'{status_text_lower}'` coincide con un patrón excluyente.")
        return False
    
    if 'half' in status_title_lower or 'finished' in status_title_lower or 'postponed' in status_title_lower or 'cancelled' in status_title_lower or 'in-play' in status_title_lower or 'suspended' in status_title_lower or 'interrupted' in status_title_lower or 'abandoned' in status_title_lower or 'fulltime' in status_title_lower:
        st.write(f"  - Descartado (Título del TD indica activo/finalizado/etc.): `'{status_title_lower}'` coincide con un patrón excluyente.")
        return False
        
    if status_td_content == '' and status_td_title == '':
        st.write(f"  ✅ ¡CONFIRMADO! Contenido de estado (`'{status_td_content}'`) y título (`'{status_td_title}'`) de TD de estado están ambos vacíos. Esto indica un partido PROGRAMADO.")
        return True
    
    st.write(f"  - Ambiguo/Desconocido: Estado `{status_td_content}` / Título `{status_td_title}`. No se clasifica como PROGRAMADO ni se descartó explícitamente.")
    return False

def scrape_upcoming_matches_logic(html_content_raw):
    """Extrae los IDs, nombres de equipos, y horas de los partidos que AÚN NO HAN COMENZADO."""
    st.markdown("---") 
    st.subheader("🕵️‍♂️ **Registro Detallado de la Extracción de Partidos de NowGoal:**")
    st.markdown("---") 

    soup = BeautifulSoup(html_content_raw, 'html.parser')
    upcoming_matches_data = []
    main_match_table = None

    st.write("Depuración: Intentando localizar la tabla principal por ID `table_live`...")
    main_match_table = soup.find('table', id='table_live')

    if not main_match_table:
        st.write("Depuración: ID `table_live` NO ENCONTRADO. Intentando una búsqueda más robusta por patrones de contenido (`scoretitle` y `tds` classes).")
        all_tables = soup.find_all('table')
        if not all_tables:
            st.error("❌ ERROR: No se encontró NINGUNA etiqueta `<table>` en el HTML analizado.")
            st.warning("Esto es crítico y sugiere que el HTML está vacío o no contiene tablas de partidos.")
            return []

        for table in all_tables:
            if table.find('tr', class_='scoretitle') and table.find('tr', class_='tds'):
                main_match_table = table
                st.success(f"🎉 **Éxito!** Tabla principal encontrada por sus clases de fila. ID: `{table.get('id', 'N/A')}`, Clases: `{table.get('class', 'N/A')}`.")
                break 
        
        if not main_match_table:
            st.error("❌ ERROR CRÍTICO: No se encontró la tabla principal de partidos ni por ID específico (`table_live`) ni por la combinación de clases (`scoretitle` y `tds`).")
            st.warning("Esto indica un cambio MUY significativo en la estructura del HTML o que el contenido relevante aún no está en el HTML recibido. Revisa el HTML RAW descargado para ver el contenido real.")
            return []

    st.success("✅ **Tabla principal de partidos localizada.**")

    found_result_split = False
    rows_processed_count = 0
    upcoming_matches_count = 0

    all_trs_in_table = main_match_table.find_all('tr', recursive=False)
    
    if not all_trs_in_table:
        st.warning("Depuración: La tabla de partidos encontrada está vacía o no contiene filas `<tr>` directas. ¡Inesperado! (¿La tabla se cargó, pero sin datos?)")
        return []

    st.info(f"Depuración: Iniciando análisis de {len(all_trs_in_table)} filas dentro de la tabla...")

    for row in all_trs_in_table:
        rows_processed_count += 1
        row_id = row.get('id', 'No ID')
        row_classes = row.get('class', [])
        
        st.write(f"\n--- **Procesando Fila {rows_processed_count}: ID=`{row_id}`, Clases=`{row_classes}`** ---")

        if 'result-split' in row_classes or row_id == 'resultSplit':
            found_result_split = True
            st.info("Depuración: Detectado el separador de Resultados (`resultSplit`). Las siguientes filas serán consideradas RESULTADOS y no 'Programados'.")
            continue

        if found_result_split:
            st.write("Depuración: Saltando fila, ya que se encontró `resultSplit` anteriormente. Esta fila es un partido TERMINADO.")
            continue

        if 'Leaguestitle' in row_classes or 'adtext-bg' in row_classes or 'ad_m' in row_classes or (row_id.startswith('tr3_') and not row.get('matchid')): 
            st.write("Depuración: Saltando fila: No es una fila de partido principal (puede ser título de liga, anuncio, o metadatos irrelevantes).")
            continue

        if 'tds' in row_classes:
            match_id = row.get('matchid')

            if not match_id:
                st.warning(f"Depuración: Fila `tds` {rows_processed_count} no tiene 'matchid'. Esto es inesperado para una fila de partido. Contenido: `{row.get_text(strip=True)[:100]}`. Saltando.")
                continue 

            status_td = row.find('td', id=f'time_{match_id}', class_='status') 
            if not status_td:
                st.warning(f"¡ADVERTENCIA! Para Partido ID `{match_id}` (Fila {rows_processed_count}), no se encontró la celda de estado (`id=time_{match_id}`, class=`status`). Sin esto, no podemos clasificarlo. Saltando.")
                st.write(f"Raw HTML de esta fila de partido para depuración (porción): `{str(row)[:500]}`") 
                continue
            
            time_data_td = row.find('td', {'name': 'timeData'})

            status_text_clean = status_td.get_text(strip=True)
            status_title_clean = status_td.get('title', '').strip()
            current_time_text_raw = time_data_td.get_text(strip=True) if time_data_td else "Hora_TD_N/A" 

            st.write(f"  **- Clasificando Partido ID `{match_id}`:**")
            st.write(f"    - `status_td` Contenido (limpio): `'{status_text_clean}'`")
            st.write(f"    - `status_td` Atributo `title` (limpio): `'{status_title_clean}'`")
            st.write(f"    - `timeData_td` Contenido (hora visible, ej. `19:00`): `'{current_time_text_raw}'`")

            if is_upcoming_match(status_text_clean, status_title_clean):
                upcoming_matches_count += 1
                
                home_team_tag = row.find('a', id=f'team1_{match_id}')
                away_team_tag = row.find('a', id=f'team2_{match_id}')
                
                home_team_name = clean_team_name(home_team_tag.get_text(strip=True)) if home_team_tag else f"Local {match_id} (No Tag A)"
                away_team_name = clean_team_name(away_team_tag.get_text(strip=True)) if away_team_tag else f"Visitante {match_id} (No Tag A)"
                
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
            st.write(f"Depuración: Fila {rows_processed_count} no tiene la clase `tds`. Saltando. (Ej. es una fila de cabecera de liga, un anuncio, etc.)")

    st.markdown("---")
    st.info(f"**Análisis Finalizado:** Se revisaron {rows_processed_count} filas. Se encontraron **{upcoming_matches_count}** partidos programados.")
    if upcoming_matches_count == 0:
        st.warning("Si esperabas ver partidos y no se encontró ninguno, el sitio podría haber cambiado o no hay partidos programados.")
        st.markdown("---") 
        st.info("Para depuración, puedes expandir el HTML RAW que Playwright logró descargar:")
        if st.checkbox("Mostrar el HTML RAW que Playwright descargó (puede ser muy grande)"):
            with st.expander("Contenido HTML Raw Completo"):
                st.code(html_content_raw[:10000] + ("\n... [Contenido truncado]" if len(html_content_raw) > 10000 else ""))

    return upcoming_matches_data

# El resto del UI (`scrap()` wrapper) se mantiene igual
def scrap():
    st.header("⚡ Scraper de Partidos Programados de NowGoal ⚡")
    st.markdown("""
    Esta herramienta se conecta a NowGoal.com utilizando un **navegador real** (headless) para ejecutar el JavaScript de la página
    y extraer los IDs, las horas (UTC y visible), y los nombres de los equipos de los partidos
    que **AÚN NO HAN COMENZADO (están programados)**.
    """)
    st.warning(f"**Aviso:** La URL de NowGoal y su estructura HTML pueden cambiar. Asegúrate de que esta URL esté actualizada si hay problemas: `{LIVE_SCORE_URL}`")
    st.markdown("---")

    html_content = None
    if st.button("🚀 ¡Extraer Partidos Programados Ahora de la Web!"):
        html_content = fetch_html_with_playwright(LIVE_SCORE_URL) 

    if html_content: 
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
            st.error("❌ **No se encontraron partidos programados en el HTML descargado.** Revisa los logs de depuración para más detalles.")
            st.info("Esto puede significar que: 1) Actualmente no hay partidos programados en la página. 2) La estructura HTML de NowGoal cambió. 3) Playwright no pudo cargar el contenido.")

    st.markdown("---") 
    st.info("Para problemas persistentes, el [repositorio de Playwright](https://github.com/microsoft/playwright/issues) o la [documentación de Streamlit Community Cloud](https://docs.streamlit.io/streamlit-community-cloud/get-started/troubleshooting) pueden ser de ayuda.")
