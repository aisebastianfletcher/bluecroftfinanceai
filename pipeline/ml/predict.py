import os
import joblib

MODEL_PATH = "pipeline/ml/model.pkl"

def _load_model():
    if os.path.exists(MODEL_PATH):
        return joblib.load(MODEL_PATH)
    return None

def predict_risk(parsed: dict) -> float:
    model = _load_model()
    income = parsed.get("income") or 0.0
    ltv = parsed.get("ltv") or 0.5
    overdrafts = parsed.get("overdrafts", 0)
    valuation_score = parsed.get("valuation_score", 0.6)

    if model:
        X = [[income, ltv, overdrafts, valuation_score]]
        proba = model.predict_proba(X)[0][1]
        return float(proba)
    else:
        score = 0.2 + 0.6*ltv - 0.000002*income + 0.05*overdrafts - 0.1*valuation_score
        score = max(0.0, min(1.0, score))
        return score
