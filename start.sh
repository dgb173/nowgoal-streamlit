#!/bin/bash

echo "Starting deployment setup in start.sh"

# 1. Crear un directorio específico para los navegadores de Playwright DENTRO del repositorio.
# Esto asegura que los binarios estén en un lugar accesible y no dependan de la caché del sistema.
PLAYWRIGHT_BROWSERS_PATH="$(pwd)/.playwright_browsers"
echo "Setting PLAYWRIGHT_BROWSERS_PATH to: $PLAYWRIGHT_BROWSERS_PATH"
mkdir -p "$PLAYWRIGHT_BROWSERS_PATH"

# 2. Exportar la variable de entorno PLAYWRIGHT_BROWSERS_PATH
# Esto le dice a Playwright dónde instalar y luego buscar los navegadores.
export PLAYWRIGHT_BROWSERS_PATH

# 3. Instalar los binarios de Playwright en esa ruta.
# `--install-dir "$PLAYWRIGHT_BROWSERS_PATH"` le dice a playwright que los ponga allí.
# `--with-deps` sigue siendo necesario para las dependencias de sistema.
echo "Running playwright install chromium --with-deps --install-dir "$PLAYWRIGHT_BROWSERS_PATH"..."
playwright install chromium --with-deps --install-dir "$PLAYWRWERS_BROWSERS_PATH"
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to install Playwright browser binaries. Your app might not work."
    exit 1
fi
echo "Playwright browser binaries installed successfully at: $PLAYWRIGHT_BROWSERS_PATH"


# 4. Asegurar que el PATH incluya la ubicación de los ejecutables de Playwright.
# Los ejecutables (chrome, firefox, webkit) suelen estar dentro de un subdirectorio con una ID de build,
# dentro de $PLAYWRIGHT_BROWSERS_PATH.
# Vamos a encontrar el ejecutable real de chromium para asegurarnos.
# Usualmente es un directorio como 'chromium-<build_id>/chrome-linux/chrome'
CHROMIUM_EXEC_PATH=$(find "$PLAYWRIGHT_BROWSERS_PATH" -type f -name 'chrome' | head -n 1)

if [ -z "$CHROMIUM_EXEC_PATH" ]; then
    echo "WARNING: Could not locate 'chrome' executable within $PLAYWRIGHT_BROWSERS_PATH after install."
    echo "This might indicate a problem, trying generic launch. Playwright will search its default location or path."
else
    # Exportar el path a chromium-executable para usarlo directamente si el autodetect falla (opcional)
    # Sin embargo, con PLAYWRIGHT_BROWSERS_PATH establecido, Playwright DEBERÍA encontrarlo automáticamente.
    echo "Located Chrome executable: $CHROMIUM_EXEC_PATH"
fi


# 5. Ejecutar la aplicación Streamlit.
# Es esencial usar 'streamlit run main.py' y dejar que Playwright.launch() descubra la ruta.
# Exportamos la variable PLAYWRIGHT_BROWSERS_PATH ANTES de la ejecución de Streamlit
# para que el entorno Python lo herede.
echo "Starting Streamlit app 'main.py'..."
streamlit run main.py --server.port "$PORT" --server.enableCORS false --server.enableXsrfProtection false
