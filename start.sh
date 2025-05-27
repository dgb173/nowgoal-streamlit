#!/bin/bash

echo "Starting deployment setup..."

# 1. Asegurar que Playwright instale sus navegadores en una ubicación conocida
# Se instalarán en ~/.cache/ms-playwright/ por defecto, lo cual está bien.
# Vamos a ser explícitos sobre Chromium.
echo "Running playwright install chromium --with-deps..."
playwright install chromium --with-deps # Solo instalamos Chromium
if [ $? -ne 0 ]; then
    echo "ERROR: Falló la instalación de binarios de Chromium para Playwright. Revisa los logs anteriores."
    exit 1
fi
echo "Chromium installation completed."

# 2. Localizar el ejecutable de Chromium después de la instalación de Playwright
# Playwright guarda los navegadores en una estructura como:
# ~/.cache/ms-playwright/chromium-<BUILD_ID>/chrome-linux/chrome (para Linux)
# El mensaje de error que obtuviste apunta a `chromium_headless_shell-1169/chrome-linux/headless_shell`
# Así que intentaremos adivinar el path dinámicamente o usar el estándar.
PLAYWRIGHT_CACHE_DIR="$HOME/.cache/ms-playwright"
CHROMIUM_EXE_PATH=$(find "$PLAYWRIGHT_CACHE_DIR" -name "chrome" | head -n 1) # Busca 'chrome' dentro del directorio cache de playwright

if [ -z "$CHROMIUM_EXE_PATH" ]; then
    # Fallback si 'chrome' no se encuentra, busca 'headless_shell' (path anterior de tu error)
    CHROMIUM_EXE_PATH=$(find "$PLAYWRIGHT_CACHE_DIR" -name "headless_shell" | head -n 1)
fi

if [ -z "$CHROMIUM_EXE_PATH" ]; then
    echo "ERROR: No se pudo localizar el ejecutable de Chromium después de la instalación."
    echo "Playwright podría haberlo instalado en una ubicación diferente o la instalación falló silenciosamente."
    exit 1
else
    echo "Identified Chromium executable at: $CHROMIUM_EXE_PATH"
fi

# Exportar la ruta del ejecutable como una variable de entorno para la aplicación Streamlit
export CHROME_EXECUTABLE_PATH="$CHROMIUM_EXE_PATH"
echo "CHROME_EXECUTABLE_PATH exported: $CHROME_EXECUTABLE_PATH"

# 3. Ejecutar la aplicación Streamlit
# --server.port $PORT: Usar la variable de entorno $PORT proporcionada por Streamlit Cloud
echo "Starting Streamlit app..."
streamlit run main.py --server.port $PORT --server.enableCORS false --server.enableXsrfProtection false
