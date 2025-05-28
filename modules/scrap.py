# modules/scrap.py
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import pandas as pd
import logging

# Configurar logging básico (útil para depuración si ejecutas esto fuera de Streamlit)
# logger = logging.getLogger(__name__)
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

def scrape_match_data(url: str):
    """
    Navega a la URL dada con Playwright y extrae datos de partidos de la tabla #table_live.
    Devuelve un DataFrame de Pandas con los datos o un DataFrame vacío si no hay partidos.
    Devuelve None si hay un error crítico de Playwright o navegación.
    """
    # logger.info(f"Iniciando scrape para URL: {url}")
    match_list = []
    
    playwright_instance = None
    browser = None
    try:
        playwright_instance = sync_playwright().start()
        # logger.info("Lanzando navegador Chromium...")
        browser = playwright_instance.chromium.launch(
            headless=True,
            timeout=60000, 
            args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
        )
        page = browser.new_page()
        # logger.info(f"Navegando a {url}...")
            
        try:
            page.goto(url, timeout=90000, wait_until='domcontentloaded')
            # logger.info("Navegación a la página completada.")
        except PlaywrightTimeoutError:
            # logger.error(f"Timeout al cargar la página: {url}")
            return None # Indica error de carga
        except Exception as e:
            # logger.error(f"Error general al navegar a {url}: {e}")
            return None # Indica error de carga

        try:
            page.wait_for_selector('#table_live tr.tds[matchid]', timeout=45000)
            # logger.info("Tabla de partidos y al menos una fila de partido encontrada.")
        except PlaywrightTimeoutError:
            # logger.warning("Timeout esperando por filas de partidos. La tabla podría estar vacía.")
            return pd.DataFrame() # Tabla vacía, no es un error crítico de Playwright

        match_rows = page.query_selector_all('#table_live tr.tds[matchid]')
        # logger.info(f"Encontradas {len(match_rows)} filas de partidos.")

        if not match_rows:
            # logger.info("No se encontraron filas de partidos con el selector 'tr.tds[matchid]'.")
            return pd.DataFrame()

        for i, row in enumerate(match_rows):
            # logger.debug(f"Procesando fila {i+1}...")
            match_id = row.get_attribute('matchid')
            if not match_id:
                # logger.warning(f"Fila {i+1} no tiene matchid, saltando.")
                continue

            time_val = "N/A"
            time_element_mt = row.query_selector(f'td#mt_{match_id}[name="timeData"]')
            if time_element_mt:
                data_t = time_element_mt.get_attribute('data-t')
                if data_t and ' ' in data_t:
                    try:
                        time_val = data_t.split(" ")[1][:5]
                    except IndexError:
                        # logger.warning(f"Formato de data-t inesperado para match {match_id}: {data_t}")
                        time_val = data_t
                elif data_t:
                     time_val = data_t
                else:
                    time_val_text = time_element_mt.text_content().strip()
                    if time_val_text and ":" in time_val_text:
                        time_val = time_val_text
            
            home_team_name = "N/A"
            home_team_anchor = row.query_selector(f'td[id="ht_{match_id}"] > a[id^="team1_"]') # id puede variar ligeramente, usar id^="team1_"
            if not home_team_anchor : # Fallback si el id exacto no existe
                home_team_anchor = row.query_selector(f'td[id="ht_{match_id}"] > a:first-of-type') # Primer 'a' dentro del td del equipo local
            
            if home_team_anchor:
                home_team_name_full = home_team_anchor.text_content()
                home_team_name = home_team_name_full.split('(N)')[0].strip() if home_team_name_full else "N/A"

            away_team_name = "N/A"
            away_team_anchor = row.query_selector(f'td[id="gt_{match_id}"] > a[id^="team2_"]') # id puede variar ligeramente
            if not away_team_anchor: # Fallback
                away_team_anchor = row.query_selector(f'td[id="gt_{match_id}"] > a:first-of-type')
            
            if away_team_anchor:
                away_team_name_full = away_team_anchor.text_content()
                away_team_name = away_team_name_full.split('(N)')[0].strip() if away_team_name_full else "N/A"
            
            score = "N/A"
            score_cell = row.query_selector('td.blue.handpoint > b') 
            if score_cell:
                score_text = score_cell.text_content().strip()
                if score_text and score_text != "-":
                    score = score_text
                elif score_text == "-":
                    score = "Por Jugar"
            else:
                score_cell_fallback = row.query_selector('td.blue.handpoint')
                if score_cell_fallback:
                    score_text_fallback = score_cell_fallback.text_content().strip()
                    score = score_text_fallback if score_text_fallback else "N/A"
                    if score == "-":
                        score = "Por Jugar"
            
            # logger.debug(f"Match ID: {match_id}, Hora: {time_val}, Local: {home_team_name}, Resultado: {score}, Visitante: {away_team_name}")
            match_list.append({
                "ID Partido": match_id,
                "Hora": time_val,
                "Equipo Local": home_team_name,
                "Resultado": score,
                "Equipo Visitante": away_team_name
            })
        
        return pd.DataFrame(match_list)

    except PlaywrightTimeoutError as pte:
        # logger.error(f"Timeout general en Playwright durante el scrapeo: {pte}")
        return None # Error crítico
    except Exception as e:
        # logger.error(f"Error general en Playwright: {e}", exc_info=True)
        return None # Error crítico
    finally:
        if browser:
            browser.close()
            # logger.info("Navegador Playwright cerrado.")
        if playwright_instance:
            playwright_instance.stop()
            # logger.info("Instancia de Playwright detenida.")
