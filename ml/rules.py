# ml/rules.py
import numpy as np
import pandas as pd

def apply_rules(df: pd.DataFrame, proba: np.ndarray) -> np.ndarray:
    p = proba.copy()
    ah_abs = df["ah_line"].abs().values
    fav_is_away = (df["ah_line"] < 0).values  # negativo => visitante favorito

    # 1) Visitante -0.25 => devaluar (mucho push y 1-0)
    mask_away_025 = fav_is_away & np.isclose(ah_abs, 0.25, atol=1e-6)
    p[mask_away_025] *= 0.92

    # 2) Visitante -0.75 con techo goleador fuera bajo (<2.0) => devaluar (no escalar)
    if "visitor_away_goal_ceiling" in df.columns:
        mask_away_075 = fav_is_away & np.isclose(ah_abs, 0.75, atol=1e-6) & (df["visitor_away_goal_ceiling"].values < 2.0)
        p[mask_away_075] *= 0.93

    # 3) Big spread (>= -1.5 visitante) y local suele marcar => penaliza
    if "home_scoring_persistence" in df.columns:
        mask_big_v = fav_is_away & (ah_abs >= 1.5) & (df["home_scoring_persistence"].values >= 0.6)
        p[mask_big_v] *= 0.88

    # 4) Rareza de línea (poco vista) => baja confianza
    if "rare_line_flag" in df.columns:
        p[df["rare_line_flag"].values == 1] *= 0.9

    # 5) “Inflación” por goleada previa (delta_line_vs_team_median > +0.5)
    if "delta_line_vs_team_median" in df.columns:
        mask_infl = df["delta_line_vs_team_median"].values > 0.5
        p[mask_infl] *= 0.9

    return p

def decision_from_prob(df: pd.DataFrame, p_adj: np.ndarray) -> pd.Series:
    # Umbrales por magnitud de línea (ajusta tras calibrar en tu histórico)
    ah_abs = df["ah_line"].abs().values
    thr = np.where(ah_abs < 0.4, 0.62,
           np.where(np.isclose(ah_abs,0.5,atol=1e-6), 0.60,
           np.where(np.isclose(ah_abs,0.75,atol=1e-6), 0.58,
           np.where(ah_abs < 1.5, 0.57, 0.55))))
    pick = p_adj >= thr
    side = np.where(df["ah_line"].values < 0, "VIS", "HOME")
    text = np.where(pick, side + " " + df["ah_line"].round(2).astype(str), "ABSTAIN")
    return pd.Series(text)
