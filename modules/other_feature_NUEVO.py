# modules/other_feature_NUEVO.py
# ... (todas las importaciones y funciones auxiliares de arriba se mantienen igual) ...

# --- STREAMLIT APP UI (Función principal limpia) ---
def display_other_feature_ui():
    st.header("⚽ Herramienta de Análisis Avanzado de Partidos")
    st.markdown("Esta herramienta te permite obtener estadísticas detalladas y el contexto H2H para un partido específico de Nowgoal. 🎉")
    st.divider()

    st.sidebar.title("⚙️ Configuración del Partido (Avanzado)")
    
    # Usar st.session_state para el valor del input si queremos persistirlo entre reruns del botón
    if 'other_feature_match_id_input_adv_val' not in st.session_state:
        st.session_state.other_feature_match_id_input_adv_val = "2696131"

    main_match_id_str_input = st.sidebar.text_input(
        "🆔 ID del Partido Principal (Avanzado):",
        key="other_feature_match_id_input_adv_key", # Diferente al de session_state para el valor
        value=st.session_state.other_feature_match_id_input_adv_val, # Leer valor de session_state
        on_change=lambda: setattr(st.session_state, 'other_feature_match_id_input_adv_val', st.session_state.other_feature_match_id_input_adv_key) # Actualizar session_state si cambia
    )
    
    if 'analysis_in_progress_adv' not in st.session_state:
        st.session_state.analysis_in_progress_adv = False

    analizar_button_clicked = st.sidebar.button(
        "🚀 Analizar Partido (Avanzado)",
        type="primary",
        use_container_width=True,
        key="other_feature_analizar_button_adv_key",
        disabled=st.session_state.analysis_in_progress_adv
    )

    results_container = st.container()

    if 'selenium_driver_other_feature_adv' not in st.session_state:
        st.session_state.selenium_driver_other_feature_adv = None

    if analizar_button_clicked:
        st.session_state.analysis_in_progress_adv = True
        # No necesitamos st.rerun() aquí inmediatamente si el flujo es lineal

    if st.session_state.analysis_in_progress_adv:
        # Esta es la sección que se ejecuta cuando el análisis está "activado"
        results_container.empty() # Limpiar resultados anteriores al iniciar
        match_id_to_process = None
        
        current_input_id = st.session_state.other_feature_match_id_input_adv_val # Usar el valor de session_state
        if current_input_id:
            try:
                cleaned_id_str = "".join(filter(str.isdigit, current_input_id))
                if cleaned_id_str:
                    match_id_to_process = int(cleaned_id_str)
            except ValueError:
                results_container.error("⚠️ ID de partido no válido. Por favor, introduce solo números.")
                st.session_state.analysis_in_progress_adv = False
                st.rerun() # Para resetear el estado y habilitar el botón
                st.stop()

        if not match_id_to_process:
            results_container.warning("⚠️ Ingresa un ID de partido válido para comenzar el análisis.")
            st.session_state.analysis_in_progress_adv = False
            st.rerun() # Para resetear
            st.stop()

        start_time = time.time()
        
        # --- BLOQUE DE EXTRACCIÓN DE DATOS INICIALES ---
        # El st.status se maneja fuera del try-except para su .update() final.
        # El try-except interno es para la lógica de extracción.
        soup_main_h2h_page = None
        mp_home_id, mp_away_id, mp_league_id, mp_home_name_script, mp_away_name_script, mp_league_name = (None,) * 6
        home_team_main_standings, away_team_main_standings = {}, {}
        display_home_name, display_away_name = "N/A", "N/A"
        h2h_main_teams_data = {}
        key_match_id_rival_a_h2h, rival_a_id_col3, rival_a_name_col3 = (None,) * 3
        match_id_rival_b_game_ref, rival_b_id_col3, rival_b_name_col3 = (None,) * 3
        rival_a_standings, rival_b_standings = {}, {}
        initial_data_success = False

        with st.status("Preparando análisis... Obteniendo datos iniciales...", expanded=True) as status_initial:
            try:
                main_page_url_h2h_view = f"/match/h2h-{match_id_to_process}"
                soup_main_h2h_page = fetch_soup_requests(main_page_url_h2h_view)

                if not soup_main_h2h_page:
                    st.error("❌ No se pudo obtener la página H2H principal. Verifica el ID del partido o la conectividad.")
                    # NO status_initial.update() aquí
                    st.session_state.analysis_in_progress_adv = False
                    st.rerun() # Salir y resetear
                    st.stop()

                mp_home_id, mp_away_id, mp_league_id, mp_home_name_script, mp_away_name_script, mp_league_name = get_team_league_info_from_script(soup_main_h2h_page)
                
                home_team_main_standings = extract_standings_data_from_h2h_page(soup_main_h2h_page, mp_home_name_script)
                away_team_main_standings = extract_standings_data_from_h2h_page(soup_main_h2h_page, mp_away_name_script)
                
                display_home_name = home_team_main_standings.get("name", mp_home_name_script) if home_team_main_standings.get("name", "N/A") != "N/A" else mp_home_name_script
                display_away_name = away_team_main_standings.get("name", mp_away_name_script) if away_team_main_standings.get("name", "N/A") != "N/A" else mp_away_name_script

                h2h_main_teams_data = extract_h2h_data(soup_main_h2h_page, display_home_name, display_away_name, mp_league_id)
                
                key_match_id_rival_a_h2h, rival_a_id_col3, rival_a_name_col3 = get_rival_info_from_h2h_table(soup_main_h2h_page, "table_v1", r"tr1_\d+", 1)
                match_id_rival_b_game_ref, rival_b_id_col3, rival_b_name_col3 = get_rival_info_from_h2h_table(soup_main_h2h_page, "table_v2", r"tr2_\d+", 0)
                
                if rival_a_name_col3 and rival_a_name_col3 != "N/A" and key_match_id_rival_a_h2h:
                    soup_rival_a_h2h_page = fetch_soup_requests(f"/match/h2h-{key_match_id_rival_a_h2h}")
                    if soup_rival_a_h2h_page:
                        rival_a_standings = extract_standings_data_from_h2h_page(soup_rival_a_h2h_page, rival_a_name_col3)
                
                if rival_b_name_col3 and rival_b_name_col3 != "N/A" and match_id_rival_b_game_ref:
                    soup_rival_b_h2h_page = fetch_soup_requests(f"/match/h2h-{match_id_rival_b_game_ref}")
                    if soup_rival_b_h2h_page:
                        rival_b_standings = extract_standings_data_from_h2h_page(soup_rival_b_h2h_page, rival_b_name_col3)
                
                # Si llegamos aquí, la extracción inicial fue (aparentemente) exitosa
                initial_data_success = True
                status_initial.update(label="Datos iniciales y H2H extraídos. Iniciando Selenium...", state="running", icon="🛠️")

            except Exception as e_initial_data:
                # NO actualices status_initial aquí si la excepción causó que el bloque 'with' termine.
                # El st.status se cerrará automáticamente (posiblemente con el último mensaje que tuvo
                # o un estado de error implícito si la excepcción no fue TypeError o ValueError que st.status puede manejar)
                st.error(f"Ocurrió un error inesperado al procesar los datos iniciales: {type(e_initial_data).__name__} - {e_initial_data}")
                st.error(traceback.format_exc()) # Para depuración MUY detallada en los logs de Streamlit
                st.session_state.analysis_in_progress_adv = False
                st.rerun() # Salir y resetear
                st.stop()
        
        # Si la extracción de datos iniciales falló y ya hicimos st.stop(), no llegaremos aquí.
        # Si initial_data_success es True, continuamos.

        # --- Lógica de Selenium (solo si datos iniciales OK) ---
        driver = st.session_state.selenium_driver_other_feature_adv
        # ... (resto de la lógica de inicialización del driver y Selenium, igual que antes) ...
        # ... (la visualización de datos igual que antes) ...
        
        if not initial_data_success: # Doble chequeo por si acaso, aunque el st.stop debería haber funcionado
            st.session_state.analysis_in_progress_adv = False
            st.rerun()
            st.stop()

        # (Lógica de inicialización del driver aquí, si es necesaria)
        driver = st.session_state.selenium_driver_other_feature_adv
        driver_needs_init = False
        
        if driver is None:
            driver_needs_init = True
        else:
            try:
                _ = driver.window_handles; _ = driver.current_url
            except Exception: driver_needs_init = True

        if driver_needs_init:
            if driver is not None:
                try: driver.quit()
                except: pass
            with st.spinner("🚀 Inicializando WebDriver de Selenium (esto puede tardar)..."): # Spinner para el driver
                driver = get_selenium_driver()
            st.session_state.selenium_driver_other_feature_adv = driver
        
        # --- Extracción con Selenium ---
        main_match_odds_data = {}
        last_home_match_in_league = None
        last_away_match_in_league = None
        selenium_data_success = False

        if driver:
            with st.status("Obteniendo cuotas y últimos partidos (con Selenium)...", expanded=True) as status_selenium:
                try:
                    # Es importante pasar main_page_url_h2h_view, que se definió arriba
                    if not 'main_page_url_h2h_view' in locals() and not soup_main_h2h_page : # Si soup_main_h2h_page es None, ya debimos haber salido.
                         st.error("Error crítico: Falta URL para Selenium. No se puede continuar.")
                         st.session_state.analysis_in_progress_adv = False
                         st.rerun()
                         st.stop()

                    driver.get(f"{BASE_URL}{main_page_url_h2h_view}") # Asegurar que main_page_url_h2h_view esté disponible
                    WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS).until(EC.presence_of_element_located((By.ID, "table_v1")))
                    time.sleep(0.8) # Pausa para renderizado

                    main_match_odds_data = get_main_match_odds_selenium(driver)
                    
                    if mp_home_id and mp_league_id and display_home_name and display_home_name != "N/A":
                        last_home_match_in_league = extract_last_match_in_league(driver, "table_v1", display_home_name, mp_league_id, "input#cb_sos1[value='1']", is_main_team_home_in_history_filter=True)
                    if mp_away_id and mp_league_id and display_away_name and display_away_name != "N/A":
                        last_away_match_in_league = extract_last_match_in_league(driver, "table_v2", display_away_name, mp_league_id, "input#cb_sos2[value='2']", is_main_team_home_in_history_filter=False)
                    
                    selenium_data_success = True
                    status_selenium.update(label="Cuotas y últimos partidos extraídos. ✨", state="complete", icon="✅")

                except Exception as e_main_sel:
                    # NO actualices status_selenium aquí si la excepción causó que el bloque 'with' termine.
                    st.error(f"❗ Error al usar Selenium: {type(e_main_sel).__name__}. {e_main_sel}")
                    st.error(traceback.format_exc())
                    # No necesitamos st.session_state.analysis_in_progress_adv = False aquí, se hará al final
        else:
            st.warning("❗ WebDriver de Selenium no disponible. Algunas características no se pudieron obtener.")

        # --- Visualización de Datos ---
        # Esta sección solo se alcanza si initial_data_success es True
        
        results_container.empty() # Limpiar cualquier spinner/status residual
        
        with results_container: # Volver a usar el container para dibujar los resultados
            final_score_fmt, _ = extract_final_score(soup_main_h2h_page) # soup_main_h2h_page debería estar definido

            last_away_opponent_for_home_hist = last_home_match_in_league.get('home_team') if last_home_match_in_league else None # Corregido
            comparative_L_vs_UVA = None
            if last_away_opponent_for_home_hist and display_home_name != "N/A": # Corregido display_home_name
                comparative_L_vs_UVA = extract_comparative_match(soup_main_h2h_page, "table_v1", display_home_name, last_away_opponent_for_home_hist, mp_league_id, is_home_table=True)
            
            last_home_opponent_for_away_hist = last_away_match_in_league.get('away_team') if last_away_match_in_league else None # Corregido
            comparative_V_vs_ULH = None
            if last_home_opponent_for_away_hist and display_away_name != "N/A": # Corregido display_away_name
                comparative_V_vs_ULH = extract_comparative_match(soup_main_h2h_page, "table_v2", display_away_name, last_home_opponent_for_away_hist, mp_league_id, is_home_table=False)

            # (Aquí va toda tu lógica de _display_... igual que antes)
            st.markdown(f"## ⚔️ **{display_home_name or 'Local'} vs {display_away_name or 'Visitante'}**")
            st.caption(f"🏆 **Liga:** `{mp_league_name or 'N/A'}` (ID: `{mp_league_id or 'N/A'}`) | 🗓️ **Partido ID:** `{match_id_to_process}`")
            st.divider()
            # ... y así sucesivamente con el resto de tus _display_ y st.metric ...
            st.header("🎯 Estado de Clasificación Actual")
            col_home_stand, col_away_stand = st.columns(2)
            _display_team_standings_section(col_home_stand, display_home_name, home_team_main_standings)
            _display_team_standings_section(col_away_stand, display_away_name, away_team_main_standings)
            st.divider()

            st.header("📈 Cuotas y Marcador")
            odds_col1, odds_col2, odds_col3 = st.columns([1.5, 1.5, 1])
            with odds_col1:
                st.markdown(f"**H. Asiático Inicial (Bet365):**")
                st.markdown(
                    f"`{main_match_odds_data.get('ah_home_cuota','N/A')}` "
                    f"<span style='color:#007bff; font-weight:bold;'>[{format_ah_as_decimal_string(main_match_odds_data.get('ah_linea_raw','?'))}]</span> "
                    f"`{main_match_odds_data.get('ah_away_cuota','N/A')}`",
                    unsafe_allow_html=True
                )
            with odds_col2:
                st.markdown(f"**Línea de Goles Inicial (Bet365):**")
                st.markdown(
                    f"`Ov {main_match_odds_data.get('goals_over_cuota','N/A')}` "
                    f"<span style='color:#dc3545; font-weight:bold;'>[{format_ah_as_decimal_string(main_match_odds_data.get('goals_linea_raw','?'))}]</span> "
                    f"`Un {main_match_odds_data.get('goals_under_cuota','N/A')}`",
                    unsafe_allow_html=True
                )
            with odds_col3:
                 st.metric(label="🏁 Marcador Final (Si Finalizado)", value=final_score_fmt.replace("*",":"))
            st.divider()
            
            st.header("⚡ Rendimiento Reciente y H2H")
            
            col_last_home, col_last_away, col_h2h_rival_opp = st.columns(3)
            _display_last_match_section(col_last_home, 'home', last_home_match_in_league, display_home_name, display_away_name)
            _display_last_match_section(col_last_away, 'away', last_away_match_in_league, display_home_name, display_away_name)
            _display_h2h_col3_section(col_h2h_rival_opp, driver, key_match_id_rival_a_h2h, rival_a_id_col3, rival_b_id_col3, rival_a_name_col3, rival_b_name_col3)

            _display_opponent_standings_expander(rival_a_standings, rival_b_standings, 
                                                rival_a_name_col3 or "Rival A",
                                                rival_b_name_col3 or "Rival B")
            
            with st.expander("🤝 Enfrentamientos Directos", expanded=True):
                h2h_col1, h2h_col2, h2h_col3, h2h_col4 = st.columns(4)
                h2h_col1.metric("AH H2H (Local Casa)", h2h_main_teams_data.get('ah_h2h_exact_fmt','-'))
                h2h_col2.metric("Res. H2H (Local Casa)", h2h_main_teams_data.get('score_h2h_exact_fmt','?*?').replace("*", ":"))
                h2h_col3.metric("AH H2H (General)", h2h_main_teams_data.get('ah_h2h_general_fmt','-'))
                h2h_col4.metric("Res. H2H (General)", h2h_main_teams_data.get('score_h2h_general_fmt','?*?').replace("*", ":"))
            st.divider()

            st.header("🔁 Comparativas Indirectas")
            comp_col1, comp_col2 = st.columns(2)
            _display_indirect_comparative(comp_col1, 
                                        f"**<span style='color: #1E90FF;'>🏠 {display_home_name or 'Local'}</span> vs. <span style='color: #FF4500;'>Últ. Rival de {display_away_name or 'Visitante'}</span>**",
                                        comparative_L_vs_UVA)
            _display_indirect_comparative(comp_col2, 
                                        f"**<span style='color: #FF4500;'>✈️ {display_away_name or 'Visitante'}</span> vs. <span style='color: #1E90FF;'>Últ. Rival de {display_home_name or 'Local'}</span>**",
                                        comparative_V_vs_ULH)
            st.divider()

            st.header("ℹ️ Resumen de Datos Clave del Partido")
            info_col1, info_col2, info_col3 = st.columns(3)
            info_col1.metric("Línea Goles Partido (Actual)", format_ah_as_decimal_string(main_match_odds_data.get('goals_linea_raw', '?')))
            info_col2.metric("Liga del Partido", mp_league_name or "N/A")
            info_col3.metric("ID Partido Actual", str(match_id_to_process))
            st.divider()

            end_time = time.time()
            st.sidebar.success(f"⏱️ Análisis (Avanzado) completado en {end_time - start_time:.2f} segundos.")

        st.session_state.analysis_in_progress_adv = False # Marcar como completado
        st.rerun() # Para limpiar la UI del botón, etc.

    elif not st.session_state.analysis_in_progress_adv and not analizar_button_clicked : # Estado inicial
        results_container.info("✨ ¡Listo para el análisis avanzado! Ingresa un ID de partido y haz clic en 'Analizar Partido (Avanzado)'.")
