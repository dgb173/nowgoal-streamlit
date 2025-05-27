#!/bin/bash

echo "Running start.sh script for Streamlit deployment..."

# 1. Asegurar que las dependencias del sistema para Playwright estén instaladas.
# El '--with-deps' se encarga de las dependencias de sistema para el navegador Chromium.
echo "Installing Playwright Chromium browser with dependencies..."
playwright install chromium --with-deps
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to install Playwright browser binaries. Deployment will likely fail."
    exit 1 # Detener el despliegue si los navegadores no se instalan.
fi
echo "Playwright Chromium browser binaries installed successfully."

# 2. Ejecutar la aplicación Streamlit.
# --server.port $PORT: Streamlit Cloud proporciona la variable de entorno $PORT para el puerto.
echo "Starting Streamlit app: main.py"
streamlit run main.py --server.port "$PORT" --server.enableCORS false --server.enableXsrfProtection false
