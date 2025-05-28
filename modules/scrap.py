# modules/scrap.py
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
import pandas as pd
import time
import logging

# logger = logging.getLogger(__name__)
# logging.basicConfig(level=logging.DEBUG)


def scrape_match_data(url: str):
    # logger.info(f"Iniciando scrape con Selenium para URL: {url}")
    match_list = []
    
    # Configuración de Chrome para Selenium
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # Ejecutar en modo headless
    chrome_options.add_argument("--no-sandbox") # Requerido para muchos entornos de CI/contenedores
    chrome_options.add_argument("--disable-dev-shm-usage") # Superar limitaciones de recursos
    chrome_options.add_argument("--disable-gpu") # A menudo recomendado para headless
    chrome_options.add_argument("--window-size=1920,1080") # Establecer un tamaño de ventana
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--blink-settings=imagesEnabled=false") # Opcional: No cargar imágenes
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36")

    # Ruta al ChromeDriver descargado por setup.sh
    # Esto es crucial en Streamlit Cloud si setup.sh lo pone en el raíz.
    webdriver_path = './chromedriver' 
    
    driver = None
    try:
        # logger.debug(f"Intentando iniciar ChromeDriver desde: {webdriver_path}")
        service = Service(executable_path=webdriver_path)
        driver = webdriver.Chrome(service=service, options=chrome_options)
        # logger.debug("WebDriver de Chrome iniciado.")

        driver.get(url)
        # logger.info(f"Navegación a {url} completada. Esperando por tabla...")

        # Esperar a que la tabla de partidos principal exista
        WebDriverWait(driver, 60).until(
            EC.presence_of_element_located((By.ID, "table_live"))
        )
        # logger.info("Tabla #table_live encontrada. Esperando por filas de partidos...")

        # Esperar a que al menos una fila de partido (tr.tds[matchid]) esté presente.
        WebDriverWait(driver, 45).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '#table_live tr.tds[matchid]'))
        )
        # logger.info("Al menos una fila de partido encontrada.")
        
        # Dar un pequeño respiro extra para cualquier JS final
        time.sleep(3) # Puedes ajustar o quitar esto

        match_rows = driver.find_elements(By.CSS_SELECTOR, '#table_live tr.tds[matchid]')
        # logger.info(f"Encontradas {len(match_rows)} filas de partidos.")

        if not match_rows:
            # logger.info("No se encontraron filas de partidos con el selector CSS.")
            return pd.DataFrame()

        for i, row_element in enumerate(match_rows):
            # logger.debug(f"Procesando fila {i+1}...")
            match_id = row_element.get_attribute('matchid')
            if not match_id:
                # logger.warning(f"Fila {i+1} no tiene matchid, saltando.")
                continue

            time_val = "N/A"
            try:
                time_element_mt = row_element.find_element(By.CSS_SELECTOR, f'td#mt_{match_id}[name="timeData"]')
                data_t = time_element_mt.get_attribute('data-t')
                if data_t and ' ' in data_t:
                    time_val = data_t.split(" ")[1][:5]
                elif data_t:
                    time_val = data_t
                else:
                    time_val_text_raw = time_element_mt.text
                    if time_val_text_raw:
                        time_val_text = time_val_text_raw.strip()
                        if time_val_text and ":" in time_val_text:
                             time_val = time_val_text
            except Exception: #Elemento no encontrado u otro error
                # logger.debug(f"No se encontró td#mt_{match_id} para la hora. Saltando hora.")
                pass

            home_team_name = "N/A"
            try:
                home_anchor = row_element.find_element(By.CSS_SELECTOR, f'td[id="ht_{match_id}"] > a[id^="team1_"]')
                home_team_text_full = home_anchor.text
                if home_team_text_full:
                    home_team_name = home_team_text_full.split('(N)')[0].strip()
            except Exception:
                try: # Fallback selector
                    home_anchor = row_element.find_element(By.CSS_SELECTOR, f'td[id="ht_{match_id}"] > a:first-of-type')
                    home_team_text_full = home_anchor.text
                    if home_team_text_full:
                        home_team_name = home_team_text_full.split('(N)')[0].strip()
                except Exception:
                    # logger.debug(f"No se encontró el nombre del equipo local para match {match_id}")
                    pass

            away_team_name = "N/A"
            try:
                away_anchor = row_element.find_element(By.CSS_SELECTOR, f'td[id="gt_{match_id}"] > a[id^="team2_"]')
                away_team_text_full = away_anchor.text
                if away_team_text_full:
                    away_team_name = away_team_text_full.split('(N)')[0].strip()
            except Exception:
                try: # Fallback selector
                    away_anchor = row_element.find_element(By.CSS_SELECTOR, f'td[id="gt_{match_id}"] > a:first-of-type')
                    away_team_text_full = away_anchor.text
                    if away_team_text_full:
                        away_team_name = away_team_text_full.split('(N)')[0].strip()
                except Exception:
                    # logger.debug(f"No se encontró el nombre del equipo visitante para match {match_id}")
                    pass
            
            score = "N/A"
            try:
                score_b_element = row_element.find_element(By.CSS_SELECTOR, 'td.blue.handpoint > b')
                score_text_raw = score_b_element.text
                if score_text_raw:
                    score = score_text_raw.strip()
                    if score == "-": score = "Por Jugar"
            except Exception:
                try: # Fallback si no hay <b>
                    score_td_element = row_element.find_element(By.CSS_SELECTOR, 'td.blue.handpoint')
                    score_text_raw = score_td_element.text
                    if score_text_raw:
                        score = score_text_raw.strip()
                        if score == "-": score = "Por Jugar"
                except Exception:
                    # logger.debug(f"No se encontró el resultado para match {match_id}")
                    pass

            match_list.append({
                "ID Partido": match_id,
                "Hora": time_val,
                "Equipo Local": home_team_name,
                "Resultado": score,
                "Equipo Visitante": away_team_name
            })
        
        return pd.DataFrame(match_list)

    except TimeoutException:
        # logger.warning("Timeout esperando elementos en la página con Selenium.")
        # Esto puede indicar que la página no cargó los elementos esperados o que la estructura cambió.
        return pd.DataFrame() # Retornar DataFrame vacío
    except WebDriverException as e:
        # logger.error(f"Error de WebDriver (Selenium): {e}", exc_info=True)
        # Esto incluye problemas con ChromeDriver o el navegador
        return None # Error crítico de Selenium
    except Exception as e:
        # logger.error(f"Excepción general en scrape_match_data con Selenium: {e}", exc_info=True)
        return None # Error crítico general
    finally:
        if driver:
            driver.quit()
            # logger.debug("WebDriver de Selenium cerrado.")
