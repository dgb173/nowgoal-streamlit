#!/bin/bash

# Actualizar pip e instalar dependencias de requirements.txt (esto lo hace Streamlit antes, pero no está de más ser explícito si hay problemas)
# pip install --upgrade pip
# pip install -r requirements.txt # Streamlit ya debería haber hecho esto

echo "Iniciando la instalación de navegadores Playwright..."
playwright install chromium  # Solo instala chromium si es lo único que usas

# Alternativa: intentar instalar con dependencias (aunque packages.txt debería cubrirlas)
# playwright install --with-deps chromium

echo "Instalación de navegadores Playwright intentada."
ls -R /home/appuser/.cache/ms-playwright/ # Para ver qué se instaló, útil en los logs de Streamlit Cloud
