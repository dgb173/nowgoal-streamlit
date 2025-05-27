#!/bin/bash

# Este script se ejecuta automáticamente por Streamlit Cloud al desplegar.

echo "Running Streamlit pre-deploy command (start.sh)"

# 1. Instalar los binarios del navegador Playwright (Chromium).
# Esto los instalará en la caché de Playwright (~/.cache/ms-playwright/)
echo "Installing Playwright browser binaries..."
playwright install chromium --with-deps # Solo Chromium para agilizar y reducir tamaño/dependencias.
if [ $? -ne 0 ]; then
    echo "ERROR: Playwright browser binaries failed to install. Exiting deployment."
    # Asegúrate de que las dependencias de sistema estén en requirements.txt si no se manejan con --with-deps.
    # Pero para playwright en linux, --with-deps suele ser suficiente.
    exit 1
fi
echo "Playwright browser binaries installed successfully."

# 2. Iniciar la aplicación Streamlit.
# --server.port $PORT: Usa la variable de entorno $PORT proporcionada por Streamlit Cloud para el puerto.
# --server.enableCORS false --server.enableXsrfProtection false: Configuraciones estándar para seguridad de Streamlit.
echo "Starting Streamlit application..."
streamlit run main.py --server.port "$PORT" --server.enableCORS false --server.enableXsrfProtection false

# NOTA: Los argumentos "--server.enableCORS false --server.enableXsrfProtection false" son importantes
# si Streamlit detecta que tu app no responde al tráfico correctamente debido a estos checks de seguridad.
# Siempre usa comillas para "$PORT" en caso de que su valor contenga espacios (aunque es poco probable para un puerto).
