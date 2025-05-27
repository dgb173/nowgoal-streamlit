# modules/scrap.py
# (omitiendo importaciones previas y otras funciones que ya tienes bien)

from playwright.sync_api import sync_playwright # Debe estar aquí, no dentro de la función

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
            st.write("Depuración Playwright: Lanzando Chromium con opciones estándar para entorno en contenedores...")
            # NO se pasa 'executable_path'. Playwright buscará en su caché por defecto.
            browser = p.chromium.launch(
                headless=True, 
                args=[
                    '--no-sandbox',               
                    '--disable-setuid-sandbox',   
                    '--disable-dev-shm-usage',    
                    '--single-process'           
                ],
            )
            page = browser.new_page()
            
            st.write(f"Depuración Playwright: Navegando a la URL: {url} (Timeout: 60s, Esperando 'networkidle')...")
            # wait_until='networkidle' es crucial para permitir que las peticiones de JavaScript se completen.
            page.goto(url, timeout=60000, wait_until='networkidle') 

            st.write("Depuración Playwright: Esperando que el selector `table#table_live` esté visible (Timeout: 30s)...")
            try:
                page.wait_for_selector('table#table_live', state='visible', timeout=30000) 
                st.success("✅ Depuración Playwright: ¡Selector `table#table_live` encontrado y visible!")
            except Exception as e_selector:
                st.warning(f"⚠️ Depuración Playwright: ¡ADVERTENCIA! El selector `table#table_live` NO se encontró o NO está visible: {e_selector}")
                st.write("El scraper intentará continuar, pero la tabla de partidos podría no estar presente o no ser la esperada. Es probable que esto resulte en 'No se encontraron partidos'.")
                st.write("Contenido del HTML descargado para análisis (primeros 2000 caracteres):")
                st.code(page.content()[:2000]) # Mostrar un fragmento para ver qué hay.
                
            html_content = page.content() # Obtener el HTML completo (con JS ejecutado)
            st.success("✅ Contenido HTML renderizado descargado con éxito.")
            return html_content
            
    except Exception as e:
        st.error(f"❌ Error crítico con Playwright durante lanzamiento o navegación: {e}")
        st.info("💡 Revisa los mensajes de depuración anteriores. Asegúrate que tu `start.sh` solo tenga `playwright install chromium --with-deps` antes de `streamlit run ...` y que esté funcionando.")
        st.markdown("**Si ves `Executable doesn't exist` o similar, aún hay un problema con la instalación o descubrimiento de los binarios de Playwright.** Streamlit Cloud es un entorno peculiar para esto.")
        return None
    finally:
        if browser: 
            try:
                browser.close()
                st.write("Depuración Playwright: Navegador Playwright cerrado en bloque `finally`.")
            except Exception as close_e:
                st.warning(f"Depuración Playwright: Error al intentar cerrar el navegador en el `finally` block: {close_e}")

# ... el resto de tu código de modules/scrap.py (clean_team_name, is_upcoming_match, scrape_upcoming_matches_logic, scrap) 
# debe permanecer IGUAL a como lo tenías. Los cambios importantes solo están en fetch_html_with_playwright.
