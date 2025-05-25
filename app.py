# app.py (Prueba de Conexión a GSheets con Cacheo)
import streamlit as st
# Asegúrate de que la carpeta 'modules' y 'modules/__init__.py' (vacío) existan
# y que 'nowgoal_scraper.py' esté dentro de 'modules'.
from modules.nowgoal_scraper import get_gsheets_client_and_sheet # Importa la función

st.set_page_config(
    page_title="Test Conexión GSheets",
    page_icon="🔗",
    layout="wide" # Opcional, para usar más ancho de pantalla
)

st.title("🔗 Prueba de Conexión a Google Sheets (con Cacheo)")
st.write("Esta prueba intentará conectar a Google Sheets usando la función `get_gsheets_client_and_sheet` del módulo `nowgoal_scraper`.")
st.write("La función `get_gsheets_client_and_sheet` debería tener el decorador `@st.cache_resource` activo para esta prueba.")
st.markdown("---")

gsheets_credentials = None
gsheets_sh_handle = None # Para el handle de la hoja de cálculo

# 1. Intentar cargar las credenciales desde st.secrets
st.subheader("Paso 1: Cargar Credenciales desde st.secrets")
try:
    if "gcp_service_account" in st.secrets:
        gsheets_credentials = st.secrets["gcp_service_account"]
        st.success("✅ Credenciales encontradas en `st.secrets['gcp_service_account']`.")

        # --- INICIO SECCIÓN DE DEBUG TEMPORAL (Opcional, pero útil) ---
        with st.expander("Detalles de las credenciales cargadas (Parcial)", expanded=False):
            if isinstance(gsheets_credentials, dict):
                st.write("Tipo de `gsheets_credentials`: Diccionario (¡Correcto!)")
                st.json({
                    "project_id": gsheets_credentials.get('project_id', 'NO ENCONTRADO'),
                    "client_email": gsheets_credentials.get('client_email', 'NO ENCONTRADO'),
                    "private_key_presente": "-----BEGIN PRIVATE KEY-----" in gsheets_credentials.get('private_key', '') if gsheets_credentials.get('private_key') else False
                })
            else:
                st.error(f"Tipo de `gsheets_credentials` NO es Diccionario. Es: {type(gsheets_credentials)}")
                st.text("Contenido (truncado): " + str(gsheets_credentials)[:200] + "...")
        # --- FIN SECCIÓN DE DEBUG TEMPORAL ---

    else:
        st.error("❗️ `gcp_service_account` NO encontrado en `st.secrets`.")
        st.warning("La aplicación no podrá conectar a Google Sheets sin estas credenciales. "
                   "Asegúrate de haber configurado los secretos correctamente en Streamlit Cloud.")
        st.stop() # Detener si no hay credenciales, ya que el propósito es probar la conexión

except Exception as e:
    st.error(f"🆘 Error catastrófico al intentar acceder a `st.secrets`: {e}")
    st.info("Esto podría indicar un problema con la plataforma Streamlit o una configuración de secretos muy dañada.")
    st.stop()

st.markdown("---")

# 2. Intentar conectar usando la función (cacheada)
st.subheader("Paso 2: Conectar usando `get_gsheets_client_and_sheet`")
if gsheets_credentials:
    st.write("Intentando llamar a `get_gsheets_client_and_sheet(credentials_dict)`...")
    try:
        # Esta es la llamada crítica que podría estar fallando con tokenize.TokenError
        # o con otros errores si las credenciales son válidas pero los permisos/API no.
        with st.spinner("⚙️ Conectando a Google Sheets... (Esto puede tardar si es la primera vez o el cache ha expirado)"):
            gc_client, gsheets_sh_handle_temp = get_gsheets_client_and_sheet(gsheets_credentials)

        if gsheets_sh_handle_temp and gc_client: # Comprobar ambos
            gsheets_sh_handle = gsheets_sh_handle_temp
            st.success("✅ ¡Conexión a Google Sheets exitosa!")
            st.info(f"Nombre de la Hoja de Cálculo (Spreadsheet) abierta: **{gsheets_sh_handle.title}**")
            try:
                worksheets = gsheets_sh_handle.worksheets()
                st.write(f"Hojas (Worksheets) encontradas en el archivo: `{[ws.title for ws in worksheets]}`")
            except Exception as e_ws:
                st.warning(f"Se conectó al archivo, pero no se pudieron listar las hojas: {e_ws}")
        else:
            st.error("❌ Falló la conexión a Google Sheets (la función `get_gsheets_client_and_sheet` devolvió None).")
            st.info("Posibles causas: Credenciales incorrectas (aunque encontradas), "
                    "cuenta de servicio sin permisos para la API de Sheets/Drive o para acceder al archivo, "
                    "nombre de la hoja de cálculo incorrecto en `NOMBRE_SHEET` dentro de `nowgoal_scraper.py`.")
            st.info("Revisa los logs de la aplicación en Streamlit Cloud ('Manage app' -> 'Logs') para más detalles si el error no es obvio aquí.")

    except Exception as e:
        st.error(f"💥 Ocurrió una excepción al llamar a `get_gsheets_client_and_sheet`: {type(e).__name__}")
        st.error(f"Mensaje: {e}")
        st.error("Este podría ser el `tokenize.TokenError` si el problema persiste con el mecanismo de cacheo. "
                 "También podría ser un error de `gspread` si las credenciales son inválidas o hay problemas de permisos.")
        st.info("Revisa los logs de la aplicación en Streamlit Cloud ('Manage app' -> 'Logs') para el traceback completo.")

else:
    st.warning("No se intentó la conexión porque las credenciales no se cargaron correctamente en el Paso 1.")

st.markdown("---")
st.info("Fin de la prueba de conexión.")
