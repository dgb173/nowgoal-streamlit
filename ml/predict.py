# ml/predict.py
import pandas as pd
import numpy as np
from pathlib import Path
from joblib import load
from .features import build_features
from .rules import apply_rules, decision_from_prob

MODELS_DIR = Path("models")

def predict_league(df_new: pd.DataFrame, league_id: str) -> pd.DataFrame:
    model = load(MODELS_DIR / f"ah_{league_id}_model.joblib")
    cal = load(MODELS_DIR / f"ah_{league_id}_cal.joblib")
    X = build_features(df_new)
    p = model.predict_proba(X)[:,1]
    p_cal = cal.predict(p)
    p_rules = apply_rules(df_new, p_cal)
    dec = decision_from_prob(df_new, p_rules)
    out = df_new[["match_id","home","away","ah_line","ou_line"]].copy()
    out["pred_cover_prob"] = p_cal
    out["pred_after_rules"] = p_rules
    out["decision"] = dec.values
    out["ah_recommendation"] = np.where(dec.values=="ABSTAIN", "", dec.values)
    return out
