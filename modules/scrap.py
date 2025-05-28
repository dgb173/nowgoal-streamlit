# modules/scrap.py
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import pandas as pd
import logging # Mantenlo por si quieres habilitar logs localmente alguna vez

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
            executable_path=None, # Dejar que Playwright encuentre el navegador instalado por 'playwright install'
            timeout=90000, # Timeout para el lanzamiento del navegador (90 segundos)
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--disable-extensions',
                # '--disable-software-rasterizer', # Podría ayudar si hay problemas de renderizado
                # '--single-process', # No siempre recomendado, pero puede ayudar en entornos muy restringidos
                '--disable-infobars',
                '--window-size=1920,1080',
                '--blink-settings=imagesEnabled=false', # Opcional: Deshabilitar imágenes para acelerar carga
                # '--proxy-server="http://TU_PROXY_SI_USARAS_UNO"' # Si necesitaras un proxy
            ]
        )
        # logger.debug("Navegador Chromium lanzado.")
        
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36",
            # Puedes añadir aquí viewport, geolocalización, etc. si fuera necesario
            # viewport={'width': 1920, 'height': 1080},
            # java_script_enabled=True # Habilitado por defecto, pero por si acaso
        )
        page = context.new_page()
        # logger.debug(f"Navegando a {url}...")
            
        try:
            page.goto(url, timeout=120000, wait_until='domcontentloaded') # Timeout para navegación (120s)
            # logger.info(f"Navegación a {url} completada. Esperando selector...")
        except PlaywrightTimeoutError as e:
            # logger.error(f"Timeout durante page.goto({url}): {e}")
            page_content_debug = page.content() # Intenta obtener contenido incluso si falla
            raise PlaywrightTimeoutError(f"Timeout (120s) al cargar la página: {url}. Error: {str(e)}")
        except Exception as e:
            # logger.error(f"Error durante page.goto({url}): {e}")
            page_content_debug = page.content() if page else "Página no accesible para obtener contenido."
            raise Exception(f"Error general al navegar a {url}: {str(e)}")

        try:
            # Esperar que un elemento específico de la tabla esté visible, indicando que los datos dinámicos se cargaron.
            # El selector #table_live tr.tds[matchid] es para las filas de partidos individuales.
            page.wait_for_selector('#table_live tr.tds[matchid]', timeout=60000) # Timeout para selector (60s)
            # logger.info("Selector '#table_live tr.tds[matchid]' encontrado.")
        except PlaywrightTimeoutError:
            # logger.warning("Timeout esperando selector '#table_live tr.tds[matchid]'. La tabla puede estar vacía o tardar mucho.")
            # page_content_debug = page.content() # Contenido antes de que el selector falle.
            # Esto puede ser una condición normal (no hay partidos) o un error de carga parcial.
            return pd.DataFrame() # Devolver DataFrame vacío si no se encuentran partidos

        match_rows = page.query_selector_all('#table_live tr.tds[matchid]')
        # logger.info(f"Encontradas {len(match_rows)} filas de partidos.")

        if not match_rows:
            # logger.info("No se encontraron filas de partidos tras encontrar la tabla (lista vacía).")
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
                    time_val = data_t.split(" ")[1][:5]
                elif data_t:
                     time_val = data_t
                else:
                    time_val_text = time_element_mt.text_content().strip()
                    if time_val_text and ":" in time_val_text:
                         time_val = time_val_text
            
            home_team_name = row.query_selector(f'td[id="ht_{match_id}"] > a[id^="team1_"]')?.text_content().split('(N)')[0].strip() or \
                               row.query_selector(f'td[id="ht_{match_id}"] > a:first-of-type')?.text_content().split('(N)')[0].strip() or "N/A"

            away_team_name = row.query_selector(f'td[id="gt_{match_id}"] > a[id^="team2_"]')?.text_content().split('(N)')[0].strip() or \
                               row.query_selector(f'td[id="gt_{match_id}"] > a:first-of-type')?.text_content().split('(N)')[0].strip() or "N/A"
            
            score_element = row.query_selector('td.blue.handpoint > b')
            if score_element:
                score = score_element.text_content().strip()
                if score == "-": score = "Por Jugar"
            else: # Fallback si no hay etiqueta <b>, como en partidos no iniciados
                score_fallback_element = row.query_selector('td.blue.handpoint')
                score = score_fallback_element.text_content().strip() if score_fallback_element else "N/A"
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
        # Para Streamlit, podrías querer propagar el error para que lo maneje la UI
        # o retornar None/algo que indique el fallo. Por ahora, propagar parte del mensaje:
        # No es ideal mostrar page_content_debug en Streamlit UI, es muy grande.
        # Esto será capturado por la app principal y se mostrará un error genérico.
        # print(f"Error de scraping (debug): {page_content_debug[:500]}") # Local debug
        return None 
    finally:
        if browser:
            browser.close()
            # logger.debug("Navegador Playwright cerrado.")
        if playwright_instance:
            playwright_instance.stop()
            # logger.debug("Instancia de Playwright detenida.")
