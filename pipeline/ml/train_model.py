import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
import joblib
import os

MODEL_PATH = "pipeline/ml/model.pkl"
os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)

def generate_synthetic(n=1000):
    rng = np.random.RandomState(0)
    income = rng.normal(60000, 20000, n).clip(10000, 300000)
    ltv = rng.beta(2, 5, n)
    overdrafts = rng.poisson(0.5, n)
    valuation_score = rng.normal(0.7, 0.15, n).clip(0,1)
    logits = -1.5 + 3*ltv - 0.00002*income + 0.7*overdrafts - 2*valuation_score
    p = 1/(1+np.exp(-logits))
    y = (p > 0.5).astype(int)
    df = pd.DataFrame({
        "income": income,
        "ltv": ltv,
        "overdrafts": overdrafts,
        "valuation_score": valuation_score,
        "risk": y
    })
    return df

def train_and_save(n=1000):
    df = generate_synthetic(n)
    X = df[["income", "ltv", "overdrafts", "valuation_score"]]
    y = df["risk"]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    model = LogisticRegression(max_iter=1000)
    model.fit(X_train, y_train)
    joblib.dump(model, MODEL_PATH)
    print("Model trained and saved to", MODEL_PATH)
    return MODEL_PATH

if __name__ == "__main__":
    train_and_save()
