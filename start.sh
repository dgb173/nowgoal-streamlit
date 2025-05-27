#!/bin/bash

echo "Starting deployment setup in start.sh"

# 1. Definir la ruta local y persistente para los navegadores de Playwright.
PLAYWRIGHT_BROWSERS_PATH="$(pwd)/.playwright_browsers"
echo "Setting PLAYWRIGHT_BROWSERS_PATH to: $PLAYWRIGHT_BROWSERS_PATH"

# 2. Crear el directorio si no existe.
mkdir -p "$PLAYWRIGHT_BROWSERS_PATH"

# 3. Exportar la variable de entorno PLAYWRIGHT_BROWSERS_PATH
# Esto es CRUCIAL para que el proceso de Python (tu app de Streamlit)
# sepa dónde Playwright instalará y buscará los binarios.
export PLAYWRIGHT_BROWSERS_PATH

# 4. Instalar los binarios de Playwright en la ruta especificada.
# Esta es la línea corregida. El nombre de la variable está ahora correcto en --install-dir.
echo "Running playwright install chromium --with-deps --install-dir \"$PLAYWRIGHT_BROWSERS_PATH\"..."
playwright install chromium --with-deps --install-dir "$PLAYWRIGHT_BROWSERS_PATH"
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to install Playwright browser binaries. Your app might not work."
    exit 1
fi
echo "Playwright browser binaries installed successfully at: $PLAYWRIGHT_BROWSERS_PATH"

# 5. Ejecutar la aplicación Streamlit.
# --server.port $PORT: Streamlit Cloud proporciona la variable $PORT.
# --server.enableCORS false --server.enableXsrfProtection false: Configuraciones para el despliegue.
echo "Starting Streamlit app 'main.py'..."
streamlit run main.py --server.port "$PORT" --server.enableCORS false --server.enableXsrfProtection false
