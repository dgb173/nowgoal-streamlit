# ml/features.py
import pandas as pd
import numpy as np

QUARTERS = {0.25,0.75,1.25,1.75,2.25,2.75,3.25,3.75}

def add_core_features(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    out["ah_abs"] = df["ah_line"].abs()
    out["fav_is_away"] = (df["ah_line"] < 0).astype(int)  # NEGATIVO => VISITANTE FAVORITO
    out["is_big_spread"] = (out["ah_abs"] >= 1.5).astype(int)
    out["is_quarter"] = out["ah_abs"].apply(lambda x: float(np.isclose((x*100)%50, 25.0))).astype(int)
    return out

def team_line_median_delta(df: pd.DataFrame) -> pd.Series:
    # diferencia entre la |línea AH| del día y la mediana del equipo en temporada
    med = (
        df.assign(team=np.where(df["ah_line"]>0, df["home"], df["away"]))  # equipo favorito
          .groupby(["team","season"])["ah_line"]
          .transform(lambda s: s.abs().median())
    )
    return df["ah_line"].abs() - med

def rarity_flag(df: pd.DataFrame) -> pd.Series:
    # rareza de línea por liga-temporada y signo (home/away favorito)
    key = (df["league_id"].astype(str) + "_" + df["season"].astype(str) + "_" +
           np.where(df["ah_line"]>0, "home","away"))
    line = df["ah_line"].abs().round(2).astype(str)
    grp = pd.concat([key, line], axis=1)
    # frecuencia por clave
    freq = grp.value_counts(normalize=True)
    idx = pd.MultiIndex.from_frame(grp)
    rate = freq.reindex(idx).fillna(0.0).values
    return (rate < 0.05).astype(int)

def simple_forms(df: pd.DataFrame) -> pd.DataFrame:
    # Señales robustas de forma si hay datos (marcar NaN si faltan)
    out = pd.DataFrame(index=df.index)
    # home_scoring_persistence: si el local viene marcando seguido (para filtrar -1.5/-2.0 visitantes)
    if {"home_goals","match_date","home"}.issubset(df.columns):
        tmp = (df.sort_values("match_date")
                 .groupby("home")["home_goals"]
                 .rolling(5, min_periods=1).apply(lambda s: (s>0).mean(), raw=False)
                 .reset_index(level=0, drop=True))
        out["home_scoring_persistence"] = tmp.values
    else:
        out["home_scoring_persistence"] = np.nan
    # visitor_away_goal_ceiling: media GF visitante fuera (rolling-5)
    if {"away_goals","match_date","away"}.issubset(df.columns):
        tmp2 = (df.sort_values("match_date")
                   .groupby("away")["away_goals"]
                   .rolling(5, min_periods=1).mean()
                   .reset_index(level=0, drop=True))
        out["visitor_away_goal_ceiling"] = tmp2.values
    else:
        out["visitor_away_goal_ceiling"] = np.nan
    return out

def build_features(df: pd.DataFrame) -> pd.DataFrame:
    X = add_core_features(df)
    X["delta_line_vs_team_median"] = team_line_median_delta(df)
    X["rare_line_flag"] = rarity_flag(df)
    X = pd.concat([X, simple_forms(df)], axis=1)
    return X
