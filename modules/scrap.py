# modules/scrap.py
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import pandas as pd
import logging

# logger = logging.getLogger(__name__) 
# logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

def scrape_match_data(url: str):
    # logger.info(f"Iniciando scrape para URL: {url}")
    match_list = []
    
    playwright_instance = None
    browser = None
    page_content_debug = "No se pudo obtener el contenido de la página para depuración."

    try:
        playwright_instance = sync_playwright().start()
        # logger.debug("Instancia de Playwright iniciada.")
        browser = playwright_instance.chromium.launch(
            headless=True,
            executable_path=None, 
            timeout=90000, 
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--disable-extensions',
                '--disable-infobars',
                '--window-size=1920,1080',
                '--blink-settings=imagesEnabled=false',
            ]
        )
        # logger.debug("Navegador Chromium lanzado.")
        
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36",
        )
        page = context.new_page()
        # logger.debug(f"Navegando a {url}...")
            
        try:
            page.goto(url, timeout=120000, wait_until='domcontentloaded') 
        except PlaywrightTimeoutError as e:
            raise PlaywrightTimeoutError(f"Timeout (120s) al cargar la página: {url}. Error: {str(e)}")
        except Exception as e:
            raise Exception(f"Error general al navegar a {url}: {str(e)}")

        try:
            page.wait_for_selector('#table_live tr.tds[matchid]', timeout=60000)
        except PlaywrightTimeoutError:
            return pd.DataFrame() 

        match_rows = page.query_selector_all('#table_live tr.tds[matchid]')
        if not match_rows:
            return pd.DataFrame()

        for i, row in enumerate(match_rows):
            match_id = row.get_attribute('matchid')
            if not match_id:
                continue

            time_val = "N/A"
            time_element_mt = row.query_selector(f'td#mt_{match_id}[name="timeData"]')
            if time_element_mt:
                data_t = time_element_mt.get_attribute('data-t')
                if data_t and ' ' in data_t:
                    try:
                        time_val = data_t.split(" ")[1][:5]
                    except IndexError:
                        time_val = data_t 
                elif data_t:
                     time_val = data_t
                else:
                    time_val_text = time_element_mt.text_content()
                    if time_val_text:
                        time_val_text = time_val_text.strip()
                        if time_val_text and ":" in time_val_text:
                             time_val = time_val_text
            
            # ---- SECCIÓN CORREGIDA ----
            home_team_name = "N/A"
            home_team_anchor = row.query_selector(f'td[id="ht_{match_id}"] > a[id^="team1_"]')
            if not home_team_anchor: # Fallback
                home_team_anchor = row.query_selector(f'td[id="ht_{match_id}"] > a:first-of-type')
            
            if home_team_anchor:
                home_team_text_full = home_team_anchor.text_content()
                if home_team_text_full:
                    home_team_name = home_team_text_full.split('(N)')[0].strip()

            away_team_name = "N/A"
            away_team_anchor = row.query_selector(f'td[id="gt_{match_id}"] > a[id^="team2_"]')
            if not away_team_anchor: # Fallback
                away_team_anchor = row.query_selector(f'td[id="gt_{match_id}"] > a:first-of-type')
            
            if away_team_anchor:
                away_team_text_full = away_team_anchor.text_content()
                if away_team_text_full:
                    away_team_name = away_team_text_full.split('(N)')[0].strip()
            # ---- FIN DE SECCIÓN CORREGIDA ----

            score = "N/A"
            score_element = row.query_selector('td.blue.handpoint > b')
            if score_element:
                score_text = score_element.text_content()
                if score_text:
                    score = score_text.strip()
                    if score == "-": score = "Por Jugar"
            else: 
                score_fallback_element = row.query_selector('td.blue.handpoint')
                if score_fallback_element:
                    score_text_fallback = score_fallback_element.text_content()
                    if score_text_fallback:
                         score = score_text_fallback.strip()
                         if score == "-": score = "Por Jugar"
            
            match_list.append({
                "ID Partido": match_id,
                "Hora": time_val,
                "Equipo Local": home_team_name,
                "Resultado": score,
                "Equipo Visitante": away_team_name
            })
        
        return pd.DataFrame(match_list)

    except Exception as e:
        # logger.error(f"Excepción general en scrape_match_data: {e}", exc_info=True)
        return None 
    finally:
        if browser:
            browser.close()
        if playwright_instance:
            playwright_instance.stop()
