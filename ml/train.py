# ml/train.py
import pandas as pd
import numpy as np
from sklearn.model_selection import TimeSeriesSplit
from sklearn.isotonic import IsotonicRegression
from xgboost import XGBClassifier
from joblib import dump
from pathlib import Path
from .features import build_features

MODELS_DIR = Path("models")
MODELS_DIR.mkdir(exist_ok=True)

def make_labels(df: pd.DataFrame) -> pd.Series:
    # 1 si el favorito (por signo AH) cubre full o half; 0 en resto (incluye push=0)
    fav_home = df["ah_line"] > 0
    fav_goals = np.where(fav_home, df["home_goals"], df["away_goals"])
    dog_goals = np.where(fav_home, df["away_goals"], df["home_goals"])
    margin = fav_goals - dog_goals
    line = df["ah_line"].abs().values

    def outcome(m, L):
        # aproximación robusta: gana si m > L - 0.25 (cuartos cuentan a favor),
        # push (==L redondo) no suma. Simplifica el half-win hacia 1 (conservador).
        if np.isnan(m) or np.isnan(L): return np.nan
        if (L*2).is_integer():  # .0 o .5
            return 1 if m > L else 0
        else:  # .25 o .75
            return 1 if m >= np.ceil(L - 1e-9) else 0
    y = np.array([outcome(m, L) for m, L in zip(margin, line)], dtype=float)
    return pd.Series(y)

def train_league(df: pd.DataFrame, league_id: str):
    df_league = df[df["league_id"] == league_id].sort_values("match_date").copy()
    y = make_labels(df_league)
    df_league = df_league[~y.isna()].copy(); y = y.dropna().astype(int)
    X = build_features(df_league)

    tscv = TimeSeriesSplit(n_splits=5)
    p_va_all, idx_all = [], []
    models, calibrators = [], []

    for tr, va in tscv.split(X):
        model = XGBClassifier(
            n_estimators=400, learning_rate=0.05, max_depth=5,
            subsample=0.9, colsample_bytree=0.9, eval_metric="logloss"
        )
        model.fit(X.iloc[tr], y.iloc[tr])
        proba = model.predict_proba(X.iloc[va])[:,1]
        ir = IsotonicRegression(out_of_bounds="clip").fit(proba, y.iloc[va])
        proba_cal = ir.predict(proba)
        p_va_all.append(proba_cal); idx_all.append(va)
        models.append(model); calibrators.append(ir)

    # guarda último fold como modelo de producción simple (o haz refit completo si prefieres)
    dump(models[-1], MODELS_DIR / f"ah_{league_id}_model.joblib")
    dump(calibrators[-1], MODELS_DIR / f"ah_{league_id}_cal.joblib")
    return float(np.mean(np.concatenate(p_va_all)))
