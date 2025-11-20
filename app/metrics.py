"""
Robust lending metrics helpers.

Drop this file in app/metrics.py and import:
from app.metrics import compute_lending_metrics, amortization_schedule

This module:
 - normalises inputs (strings, ints, floats, None)
 - computes amortisation schedule accurately
 - computes amortising and interest-only payments
 - computes DSCRs, risk score and reasons
 - returns precise numeric outputs (no accidental NULLs when inputs exist)
"""
from typing import Optional, Dict, Any
import math
import pandas as pd


def _to_float(v: Optional[Any]) -> Optional[float]:
    """Safe convert to float; return None for None/empty/invalid."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if s == "":
        return None
    try:
        return float(s)
    except Exception:
        return None


def amortization_schedule(loan_amount: float, annual_rate_decimal: float, term_months: int) -> pd.DataFrame:
    """
    Produce amortization schedule with accurate monthly payment.
    - annual_rate_decimal: decimal (e.g., 0.055 for 5.5%)
    - term_months: total months
    Returns DataFrame with month, payment, interest, principal, balance
    """
    if loan_amount is None or term_months is None:
        raise ValueError("loan_amount and term_months are required")
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
        # final payment adjustment
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
    """
    Compute LTV, LTC, amortising & interest-only payments, DSCRs, risk score and reasons.
    Input: parsed dictionary (may come from PDF extraction or calculator).
    Output: lending_metrics dictionary added to parsed['lending_metrics'] and returned.

    Important:
     - LTV/LTC are returned as decimals (0.75 = 75%). If you want percent strings,
       format in the UI layer.
     - monthly_amortising_payment & total_interest are computed if both rate & term are present.
     - monthly_interest_only_payment computed if rate present.
     - NOI is used when present; otherwise a conservative income proxy (30% of income) is used and marked.
    """
    lm: Dict[str, Any] = {}

    # Sanitize numeric inputs
    loan = _to_float(parsed.get("loan_amount") or parsed.get("loan"))
    prop = _to_float(parsed.get("property_value") or parsed.get("property_value_estimate"))
    total_cost = _to_float(parsed.get("project_cost") or parsed.get("total_cost"))
    # Rate can be percent (5.5) or decimal (0.055)
    rate_raw = parsed.get("interest_rate_annual") or parsed.get("interest_rate") or parsed.get("rate")
    rate = _to_float(rate_raw)
    if rate is not None and rate > 1:
        # assume user provided percentage like 5.5 -> convert to decimal
        rate = rate / 100.0

    term_months = parsed.get("term_months") or parsed.get("term")
    if term_months is not None:
        try:
            term_months = int(term_months)
        except Exception:
            term_months = None

    # LTV
    if loan is not None and prop is not None and prop > 0:
        ltv = loan / prop
    else:
        ltv = None
    lm["ltv"] = round(ltv, 4) if isinstance(ltv, float) else None

    # LTC
    if loan is not None and total_cost is not None and total_cost > 0:
        ltc = loan / total_cost
    else:
        ltc = None
    lm["ltc"] = round(ltc, 4) if isinstance(ltc, float) else None

    # Attempt amortization if rate and term both present
    amort_df = None
    monthly_amort = None
    total_interest = None
    if loan is not None and rate is not None and term_months:
        try:
            amort_df = amortization_schedule(loan, rate, term_months)
            monthly_amort = float(amort_df["payment"].iloc[0])
            total_interest = float(amort_df["interest"].sum())
        except Exception:
            amort_df = None

    # Fallback monthly amortising payment calculation if not built above but rate+term present
    if monthly_amort is None and loan is not None and rate is not None and term_months:
        try:
            r = rate
            n = int(term_months)
            if r == 0:
                monthly_amort = loan / n
            else:
                monthly_amort = loan * (r / 12.0) / (1 - (1 + r / 12.0) ** (-n))
            # approximate total interest
            total_interest = monthly_amort * n - loan
        except Exception:
            monthly_amort = None

    # Interest-only monthly payment (bridging)
    monthly_io = None
    if loan is not None and rate is not None:
        try:
            monthly_io = loan * rate / 12.0
        except Exception:
            monthly_io = None

    lm["monthly_amortising_payment"] = round(monthly_amort, 2) if isinstance(monthly_amort, (int, float)) else None
    lm["monthly_interest_only_payment"] = round(monthly_io, 2) if isinstance(monthly_io, (int, float)) else None
    lm["total_interest"] = round(total_interest, 2) if isinstance(total_interest, (int, float)) else None

    # Annual debt service for both scenarios
    lm["annual_debt_service_amortising"] = round(lm["monthly_amortising_payment"] * 12.0, 2) if lm.get("monthly_amortising_payment") else None
    lm["annual_debt_service_io"] = round(lm["monthly_interest_only_payment"] * 12.0, 2) if lm.get("monthly_interest_only_payment") else None

    # NOI detection (explicit) or proxy from income (30% of income)
    noi = _to_float(parsed.get("noi") or parsed.get("net_operating_income"))
    if noi is None:
        annual_rent = _to_float(parsed.get("annual_rent") or parsed.get("rental_income_annual"))
        operating_expenses = _to_float(parsed.get("operating_expenses") or parsed.get("annual_expenses"))
        if annual_rent is not None:
            try:
                noi = annual_rent - (operating_expenses or 0.0)
                lm["noi_estimated_from_rent"] = True
            except Exception:
                noi = None
        else:
            borrower_income = _to_float(parsed.get("income"))
            if borrower_income is not None:
                noi = borrower_income * 0.30
                lm["noi_estimated_from_income_proxy"] = True
            else:
                noi = None
    lm["noi"] = round(noi, 2) if isinstance(noi, (int, float)) else None

    # DSCR calculations
    dscr_amort = None
    dscr_io = None
    try:
        if lm.get("noi") is not None and lm.get("annual_debt_service_amortising"):
            if lm["annual_debt_service_amortising"] > 0:
                dscr_amort = lm["noi"] / lm["annual_debt_service_amortising"]
        if lm.get("noi") is not None and lm.get("annual_debt_service_io"):
            if lm["annual_debt_service_io"] > 0:
                dscr_io = lm["noi"] / lm["annual_debt_service_io"]
    except Exception:
        dscr_amort = None
        dscr_io = None
    lm["dscr_amortising"] = round(dscr_amort, 3) if isinstance(dscr_amort, (int, float)) else None
    lm["dscr_interest_only"] = round(dscr_io, 3) if isinstance(dscr_io, (int, float)) else None

    # Flags, bank red flags
    policy_flags = parsed.get("policy_flags") or parsed.get("flags") or []
    bank_red_flags = parsed.get("bank_red_flags") or []
    lm["policy_flags"] = policy_flags
    lm["bank_red_flags"] = bank_red_flags

    # Risk scoring (clearer thresholds)
    ltv_risk = 0.0
    if lm.get("ltv") is not None:
        v = lm["ltv"]
        if v < 0.6:
            ltv_risk = 0.0
        elif v < 0.8:
            ltv_risk = 0.5
        else:
            ltv_risk = 1.0

    # Use amortising DSCR for score if available, otherwise interest-only DSCR
    dscr_for_score = lm.get("dscr_amortising") if lm.get("dscr_amortising") is not None else lm.get("dscr_interest_only")
    dscr_risk = 1.0
    if dscr_for_score is not None:
        d = dscr_for_score
        if d >= 1.25:
            dscr_risk = 0.0
        elif d >= 1.0:
            dscr_risk = 0.5
        else:
            dscr_risk = 1.0

    flags_risk = 1.0 if (policy_flags or bank_red_flags) else 0.0

    risk_score = (0.5 * ltv_risk) + (0.35 * dscr_risk) + (0.15 * flags_risk)
    risk_score = min(max(risk_score, 0.0), 1.0)
    lm["risk_score_computed"] = round(risk_score, 3)
    lm["risk_category"] = "High" if risk_score >= 0.7 else ("Medium" if risk_score >= 0.4 else "Low")

    # Explainable reasons
    reasons = []
    if lm.get("ltv") is not None:
        if lm["ltv"] >= 0.85:
            reasons.append(f"High LTV ({lm['ltv']:.2f})")
        elif lm["ltv"] >= 0.75:
            reasons.append(f"Elevated LTV ({lm['ltv']:.2f})")
    if lm.get("dscr_amortising") is not None and lm["dscr_amortising"] < 1.0:
        reasons.append(f"Amortising DSCR below 1.0 ({lm['dscr_amortising']:.2f})")
    if lm.get("dscr_interest_only") is not None and lm["dscr_interest_only"] < 1.0:
        reasons.append(f"Interest-only DSCR below 1.0 ({lm['dscr_interest_only']:.2f})")
    if flags_risk:
        reasons.append("Policy / bank flags present")
    if not reasons:
        reasons.append("No automated flags detected")
    lm["risk_reasons"] = reasons

    # Amortization preview (first 12 rows) to attach for lightweight reporting
    if amort_df is not None:
        try:
            lm["amortization_preview_rows"] = amort_df.head(12).to_dict(orient="records")
            lm["amortization_total_interest"] = round(amort_df["interest"].sum(), 2)
        except Exception:
            lm["amortization_preview_rows"] = None
            lm["amortization_total_interest"] = None
    else:
        lm["amortization_preview_rows"] = None
        lm["amortization_total_interest"] = None

    # attach and return
    parsed["lending_metrics"] = lm
    return lm


# Example quick test (run locally)
if __name__ == "__main__":
    sample = {
        "loan_amount": 240000,
        "property_value": 330000,
        "interest_rate_annual": 5.5,
        "term_months": 300,
        "income": 85000
    }
    out = compute_lending_metrics(sample)
    import pprint
    pprint.pprint(out, width=120)
