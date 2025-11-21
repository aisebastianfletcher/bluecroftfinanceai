"""
app/metrics.py

Robust lending metrics for Bluecroft Finance.
Implements:
- compute_lending_metrics(parsed): returns a metrics dict and attaches parsed['input_audit'] and parsed['lending_metrics']
- amortization_schedule(loan_amount, annual_rate_decimal, term_months): pandas DataFrame
"""
from typing import Optional, Dict, Any, List, Tuple
import re
import pandas as pd

def _to_float(v: Optional[Any]) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if s == "":
        return None
    s = s.replace(",", "").replace("£", "").replace("$", "").replace("%", "")
    try:
        return float(s)
    except Exception:
        m = re.search(r"-?\d+(\.\d+)?", s)
        if m:
            return float(m.group(0))
        return None

def amortization_schedule(loan_amount: float, annual_rate_decimal: float, term_months: int) -> pd.DataFrame:
    P = float(loan_amount)
    n = int(term_months)
    if n <= 0:
        raise ValueError("term_months must be > 0")
    r_month = float(annual_rate_decimal) / 12.0 if annual_rate_decimal else 0.0
    if r_month == 0:
        payment = P / n
    else:
        payment = P * r_month / (1 - (1 + r_month) ** (-n))
    balance = P
    rows = []
    for m in range(1, n + 1):
        interest = balance * r_month
        principal = payment - interest
        if m == n:
            principal = balance
            payment = interest + principal
            balance = 0.0
        else:
            balance = max(balance - principal, 0.0)
        rows.append({
            "month": m,
            "payment": round(payment, 2),
            "interest": round(interest, 2),
            "principal": round(principal, 2),
            "balance": round(balance, 2)
        })
    return pd.DataFrame(rows)

def compute_lending_metrics(parsed: Dict[str, Any]) -> Dict[str, Any]:
    loan = _to_float(parsed.get("loan_amount") or parsed.get("loan"))
    prop = _to_float(parsed.get("property_value") or parsed.get("property") or parsed.get("purchase_price"))
    project_cost = _to_float(parsed.get("total_cost") or parsed.get("project_cost"))
    rate = _to_float(parsed.get("interest_rate_annual") or parsed.get("interest_rate") or parsed.get("rate"))
    term = parsed.get("loan_term_months") or parsed.get("term_months") or parsed.get("term")
    try:
        term = int(term) if term is not None else None
    except Exception:
        term = None

    audit: List[str] = []
    if loan is None:
        audit.append("Missing or invalid loan_amount")
    if prop is None:
        audit.append("Missing or invalid property_value or purchase_price")
    if project_cost is None:
        audit.append("project_cost / total_cost not provided")
    if rate is None:
        audit.append("Interest rate not provided or invalid")
    if term is None:
        audit.append("Loan term (months) not provided or invalid")

    # Normalise rate: if percent >1 treat as percent
    if rate is not None and rate > 1:
        rate = rate / 100.0

    # LTV & LTC
    ltv = loan / prop if loan is not None and prop not in (None, 0) else None
    ltc = loan / project_cost if loan is not None and project_cost not in (None, 0) else None

    # Amortisation & payments
    amort_df = None
    monthly_amort = None
    total_interest = None
    if loan is not None and rate is not None and term:
        try:
            amort_df = amortization_schedule(loan, rate, term)
            monthly_amort = float(amort_df["payment"].iloc[0])
            total_interest = float(amort_df["interest"].sum())
        except Exception:
            amort_df = None

    # Interest-only monthly
    monthly_io = None
    if loan is not None and rate is not None:
        monthly_io = loan * rate / 12.0

    # NOI estimation: prefer NOI if provided, else monthly_rent*12 - operating_costs, else income*0.3 proxy
    noi = _to_float(parsed.get("noi"))
    if noi is None and parsed.get("monthly_rent"):
        try:
            noi = float(parsed.get("monthly_rent")) * 12.0 - float(parsed.get("operating_costs") or 0.0)
        except Exception:
            noi = None
    if noi is None and parsed.get("income"):
        noi = float(parsed.get("income")) * 0.30

    # DSCR
    dscr_am = None
    dscr_io = None
    if noi is not None and monthly_amort:
        annual_ds_am = monthly_amort * 12.0
        dscr_am = noi / annual_ds_am if annual_ds_am > 0 else None
    if noi is not None and monthly_io:
        annual_ds_io = monthly_io * 12.0
        dscr_io = noi / annual_ds_io if annual_ds_io > 0 else None

    # Flags
    policy_flags = []
    bank_flags = parsed.get("bank_red_flags") or []
    if ltv is not None and ltv > 0.75:
        policy_flags.append("High LTV (>75%)")
    if ltc is not None and ltc > 0.8:
        policy_flags.append("High LTC (>80%)")
    if dscr_am is not None and dscr_am <= 1.2:
        policy_flags.append("Low DSCR (≤1.2)")
    if parsed.get("income") is None:
        policy_flags.append("Missing income")
    if amort_df is None:
        policy_flags.append("Missing amortisation data")

    # Risk scoring
    ltv_risk = 1.0 if (ltv is not None and ltv >= 0.85) else (0.5 if (ltv is not None and ltv >= 0.75) else 0.0)
    dscr_for_score = dscr_am if dscr_am is not None else dscr_io
    dscr_risk = 1.0 if (dscr_for_score is not None and dscr_for_score < 1.0) else (0.5 if (dscr_for_score is not None and dscr_for_score < 1.25) else 0.0)
    flags_risk = 1.0 if (policy_flags or bank_flags) else 0.0
    risk_score = min(max(0.0, 0.5 * ltv_risk + 0.35 * dscr_risk + 0.15 * flags_risk), 1.0)
    risk_cat = "High" if risk_score >= 0.7 else ("Medium" if risk_score >= 0.4 else "Low")

    lm = {
        "ltv": round(ltv, 4) if isinstance(ltv, float) else None,
        "ltc": round(ltc, 4) if isinstance(ltc, float) else None,
        "monthly_amortising_payment": round(monthly_amort, 2) if monthly_amort else None,
        "monthly_interest_only_payment": round(monthly_io, 2) if monthly_io else None,
        "total_interest": round(total_interest, 2) if total_interest else None,
        "annual_debt_service_amortising": round(monthly_amort * 12, 2) if monthly_amort else None,
        "annual_debt_service_io": round(monthly_io * 12, 2) if monthly_io else None,
        "noi": round(noi, 2) if noi else None,
        "dscr_amortising": round(dscr_am, 3) if dscr_am else None,
        "dscr_interest_only": round(dscr_io, 3) if dscr_io else None,
        "policy_flags": policy_flags,
        "bank_red_flags": bank_flags,
        "risk_score_computed": round(risk_score, 3),
        "risk_category": risk_cat,
        "risk_reasons": policy_flags or ["No automated flags detected"],
        "amortization_preview_rows": amort_df.head(12).to_dict(orient="records") if amort_df is not None else None,
        "amortization_total_interest": round(total_interest,2) if total_interest else None
    }

    parsed["input_audit"] = audit
    parsed["lending_metrics"] = lm
    return lm
