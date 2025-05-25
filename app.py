# app.py (Versión de prueba súper simplificada)
import streamlit as st

st.set_page_config(
    page_title="Test App",
    page_icon="🧪",
)

st.title("🧪 Aplicación de Prueba Mínima 🧪")
st.write("Si ves esto, la estructura base de Streamlit funciona.")

try:
    # Intentemos importar solo una función del módulo para ver si la importación en sí es el problema
    from modules.nowgoal_scraper import get_chrome_options # Una función simple sin decoradores
    st.write("Importación de `get_chrome_options` desde `nowgoal_scraper` parece OK.")

    # No intentes conectar a GSheets ni nada complejo todavía.
    # Simplemente llama a la función importada si existe
    if callable(get_chrome_options):
        opts = get_chrome_options()
        if opts:
            st.success("Llamada a `get_chrome_options` exitosa.")
        else:
            st.error("`get_chrome_options` no devolvió opciones.")

except ImportError as ie:
    st.error(f"Error de IMPORTACIÓN: {ie}")
    st.error("Verifica que la carpeta 'modules' y 'modules/nowgoal_scraper.py' existan y que `__init__.py` esté en 'modules'.")
except Exception as e:
    st.error(f"Otro error durante la importación o prueba: {e}")

st.info("Fin de la prueba mínima.")
