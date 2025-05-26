# modules/other_feature_NUEVO.py
import streamlit as st

def display_other_feature_ui():
    st.title("PRUEBA RADICAL DE other_feature_NUEVO.py")
    st.header("Si ves esto, el archivo se está cargando.")
    st.write("Esto es contenido mínimo para probar.")
    st.error("¡El módulo NUEVO está funcionando!")

    if st.button("Botón de Prueba en Módulo Nuevo"):
        st.success("¡El botón funciona!")
