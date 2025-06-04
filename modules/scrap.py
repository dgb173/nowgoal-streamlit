# modules/scrap.py
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
import pandas as pd
import logging
from bs4 import BeautifulSoup

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
        
        # Extraer solo la tabla y procesar con BeautifulSoup
        table_html = driver.find_element(By.ID, "table_live").get_attribute("innerHTML")
        soup = BeautifulSoup(table_html, "html.parser")
        match_rows = soup.select('tr.tds[matchid]')

        if not match_rows:
            return pd.DataFrame()

        for i, row_element in enumerate(match_rows):
            match_id = row_element.get("matchid")
            if not match_id:
                continue

            time_val = "N/A"
            time_cell = row_element.select_one(f'td#mt_{match_id}[name="timeData"]')
            if time_cell:
                data_t = time_cell.get("data-t")
                if data_t and " " in data_t:
                    time_val = data_t.split(" ")[1][:5]
                elif data_t:
                    time_val = data_t
                else:
                    time_val_text = time_cell.get_text(strip=True)
                    if ":" in time_val_text:
                        time_val = time_val_text

            home_team_name = "N/A"
            home_anchor = row_element.select_one(f'td#ht_{match_id} a[id^="team1_"]') or \
                          row_element.select_one(f'td#ht_{match_id} a')
            if home_anchor and home_anchor.text:
                home_team_name = home_anchor.text.split('(N)')[0].strip()

            away_team_name = "N/A"
            away_anchor = row_element.select_one(f'td#gt_{match_id} a[id^="team2_"]') or \
                          row_element.select_one(f'td#gt_{match_id} a')
            if away_anchor and away_anchor.text:
                away_team_name = away_anchor.text.split('(N)')[0].strip()

            score = "N/A"
            score_b_element = row_element.select_one('td.blue.handpoint > b')
            if score_b_element and score_b_element.text:
                score = score_b_element.text.strip()
            else:
                score_td_element = row_element.select_one('td.blue.handpoint')
                if score_td_element and score_td_element.text:
                    score = score_td_element.text.strip()
            if score == "-":
                score = "Por Jugar"

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
