"""Utilities for comparative stats table for Nowgoal scraper"""

import time
import pandas as pd
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
import streamlit as st


def get_match_specific_tech_stats_for_table(
    driver,
    match_iid,
    match_description="",
    base_url="https://live18.nowgoal25.com",
    timeout_seconds=25,
):
    """Extract 'Shots', 'Shots on Goal', 'Attacks' and 'Dangerous Attacks' for a match."""
    stats_data = {
        "Descripción Partido": match_description,
        "ID Partido": match_iid if match_iid else "N/A",
        "Tiros (L)": None,
        "Tiros (V)": None,
        "Tiros a Puerta (L)": None,
        "Tiros a Puerta (V)": None,
        "Ataques (L)": None,
        "Ataques (V)": None,
        "Ataques Peligrosos (L)": None,
        "Ataques Peligrosos (V)": None,
    }
    if not match_iid:
        return stats_data
    stats_url = f"{base_url}/match/live-{match_iid}"
    try:
        driver.get(stats_url)
        WebDriverWait(driver, timeout_seconds).until(
            EC.presence_of_element_located((By.ID, "teamTechDiv_detail"))
        )
        soup = BeautifulSoup(driver.page_source, "html.parser")
        team_div = soup.find("div", id="teamTechDiv_detail")
        if not team_div:
            return stats_data
        stat_ul = team_div.find("ul", class_="stat")
        if not stat_ul:
            return stats_data
        mapping = {
            "Shots": ("Tiros (L)", "Tiros (V)"),
            "Shots on Goal": ("Tiros a Puerta (L)", "Tiros a Puerta (V)"),
            "Attacks": ("Ataques (L)", "Ataques (V)"),
            "Dangerous Attacks": ("Ataques Peligrosos (L)", "Ataques Peligrosos (V)"),
        }
        for li in stat_ul.find_all("li"):
            stat_title = li.find("span", class_="stat-title")
            if not stat_title:
                continue
            name = stat_title.text.strip()
            if name not in mapping:
                continue
            home_key, away_key = mapping[name]
            stat_values = li.find_all("span", class_="stat-c")
            if len(stat_values) >= 2:
                try:
                    stats_data[home_key] = int(stat_values[0].text.strip())
                    stats_data[away_key] = int(stat_values[1].text.strip())
                except ValueError:
                    pass
    except TimeoutException:
        pass
    except WebDriverException:
        pass
    except Exception:
        pass
    return stats_data


def display_comparative_stats_table(
    driver,
    main_match_id,
    mp_home_name,
    mp_away_name,
    last_home_match_in_league,
    last_away_match_in_league,
    details_h2h_col3,
    base_url="https://live18.nowgoal25.com",
    timeout_seconds=25,
):
    """Build and display dataframe with coloured stats for matches."""
    st.markdown("---")
    st.subheader("📊 Resumen de Estadísticas Clave por Partido")

    matches_to_analyze_stats = []
    matches_to_analyze_stats.append({
        "description": "Partido Principal",
        "id": main_match_id,
        "name": f"{mp_home_name} vs {mp_away_name}",
    })
    if last_home_match_in_league and last_home_match_in_league.get("match_id"):
        matches_to_analyze_stats.append({
            "description": f"Último Local {mp_home_name}",
            "id": last_home_match_in_league["match_id"],
            "name": f"{last_home_match_in_league['home_team']} vs {last_home_match_in_league['away_team']}",
        })
    else:
        matches_to_analyze_stats.append({"description": f"Último Local {mp_home_name}", "id": None, "name": "No Encontrado"})
    if last_away_match_in_league and last_away_match_in_league.get("match_id"):
        matches_to_analyze_stats.append({
            "description": f"Último Visitante {mp_away_name}",
            "id": last_away_match_in_league["match_id"],
            "name": f"{last_away_match_in_league['home_team']} vs {last_away_match_in_league['away_team']}",
        })
    else:
        matches_to_analyze_stats.append({"description": f"Último Visitante {mp_away_name}", "id": None, "name": "No Encontrado"})
    if details_h2h_col3.get("status") == "found" and details_h2h_col3.get("h2h_match_id"):
        matches_to_analyze_stats.append({
            "description": f"H2H Oponentes ({details_h2h_col3.get('h2h_home_team_name','?')}-{details_h2h_col3.get('h2h_away_team_name','?')})",
            "id": details_h2h_col3["h2h_match_id"],
            "name": f"{details_h2h_col3.get('h2h_home_team_name','N/A')} vs {details_h2h_col3.get('h2h_away_team_name','N/A')}",
        })
    else:
        matches_to_analyze_stats.append({"description": "H2H Oponentes", "id": None, "name": "No Encontrado"})

    all_stats_for_table = []
    with st.spinner("Extrayendo estadísticas técnicas para la tabla comparativa..."):
        for info in matches_to_analyze_stats:
            stats = get_match_specific_tech_stats_for_table(
                driver,
                info["id"],
                info["description"],
                base_url=base_url,
                timeout_seconds=timeout_seconds,
            )
            all_stats_for_table.append(stats)
            time.sleep(0.5)

    if all_stats_for_table:
        df_stats = pd.DataFrame(all_stats_for_table)

        def style_stats_table(df):
            color_shots = "#E0F7FA"
            color_attacks = "#E8F5E9"
            shots_cols = ["Tiros (L)", "Tiros (V)", "Tiros a Puerta (L)", "Tiros a Puerta (V)"]
            attacks_cols = ["Ataques (L)", "Ataques (V)", "Ataques Peligrosos (L)", "Ataques Peligrosos (V)"]
            styles = []
            for col in df.columns:
                if col in shots_cols:
                    styles.append({"selector": f"th.col_heading.col{df.columns.get_loc(col)}, td.col{df.columns.get_loc(col)}", "props": [("background-color", color_shots)]})
                elif col in attacks_cols:
                    styles.append({"selector": f"th.col_heading.col{df.columns.get_loc(col)}, td.col{df.columns.get_loc(col)}", "props": [("background-color", color_attacks)]})
            return styles

        st.dataframe(
            df_stats.style.set_table_styles(style_stats_table(df_stats)),
            use_container_width=True,
            hide_index=True,
        )
        st.caption("Los valores 'None' indican que la estadística no pudo ser extraída o no estaba disponible.")
    else:
        st.info("No se pudieron obtener las estadísticas técnicas para los partidos comparados.")
