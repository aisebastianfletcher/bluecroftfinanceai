"""
Robust lending metrics helpers with input auditing.

Drop into app/metrics.py and import:
from app.metrics import compute_lending_metrics, amortization_schedule
"""
from typing import Optional, Dict, Any, List, Tuple
import math
import re
import pandas as pd

def _to_float_safe(v: Optional[Any]) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        try:
            return float(v)
        except Exception:
            return None
    s = str(v).strip()
    if s == "":
        return None
    s = s.replace("\u00A0", "").replace(",", "").replace("£", "").replace("$", "").strip()
    s = s.replace("%", "")
    try:
        return float(s)
    except Exception:
        m = re.search(r"-?\d+(\.\d+)?", s)
        if m:
            try:
                return float(m.group(0))
            except Exception:
                return None
        return None

CANONICAL_KEYS = {
    "loan_amount": ["loan_amount", "loan", "requested_loan", "amount_requested"],
    "property_value": ["property_value", "property_value_estimate", "property", "value_of_property"],
    "project_cost": ["project_cost", "project cost", "total_project_cost", "total_project", "total_cost"],
    "total_cost": ["total_cost", "total project cost", "totalprojectcost"],
    "interest_rate_annual": ["interest_rate_annual", "interest rate (annual)", "interest_rate", "rate", "annual_rate"],
    "term_months": ["loan_term_months", "loan term months", "term_months", "term", "loan_term", "term_month"],
    "income": ["income", "annual_income", "applicant_income"],
    "noi": ["noi", "net_operating_income"],
    "annual_rent": ["annual_rent", "rental_income_annual", "annual_rental_income"],
    "operating_expenses": ["operating_costs", "operating_costs", "operating_expenses", "annual_expenses"],
    "policy_flags": ["policy_flags", "flags"],
    "bank_red_flags": ["bank_red_flags", "bank_flags", "red_flags"],
    "borrower": ["borrower", "applicant", "name"],
    "arv": ["arv", "after_repair_value"],
    "purchase_price": ["purchase_price"],
    "refurbishment_budget": ["refurbishment_budget", "refurb_budget"],
    "monthly_rent": ["monthly_rent", "rent_monthly"],
    "dscr": ["dscr"]
}

def _find_by_alias(parsed: Dict[str, Any], aliases: List[str]) -> Optional[Any]:
    if not parsed:
        return None
    norm_map = {}
    for k in parsed.keys():
        if k is None:
            continue
        kn = re.sub(r"[^\w]", "", str(k).lower())
        norm_map[kn] = k
    for a in aliases:
        an = re.sub(r"[^\w]", "", str(a).lower())
        if an in norm_map:
            return parsed.get(norm_map[an])
    for k in parsed.keys():
        kl = str(k).lower()
        for a in aliases:
            if a.lower() in kl:
                return parsed.get(k)
    return None

def _canonicalize(parsed: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    p: Dict[str, Any] = {}
    audit: List[str] = []
    for canon, aliases in CANONICAL_KEYS.items():
        val = _find_by_alias(parsed, aliases)
        if canon in ("loan_amount", "property_value", "project_cost", "total_cost",
                     "interest_rate_annual", "term_months", "income", "noi", "annual_rent",
                     "operating_expenses", "monthly_rent", "dscr", "arv", "purchase_price", "refurbishment_budget"):
            num = _to_float_safe(val)
            if num is None and val is not None:
                audit.append(f"Field '{canon}' found but could not parse numeric value: '{val}'")
            p[canon] = num
        else:
            p[canon] = val
    p["_raw_parsed"] = parsed
    return p, audit

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

def _attempt_property_scaling(loan: float, prop: float) -> Tuple[float, str]:
    if prop is None or loan is None:
        return prop, ""
    msg = ""
    try:
        if prop > 0 and prop < 1000:
            scaled = prop * 1000.0
            ltv_scaled = loan / scaled if scaled else None
            if ltv_scaled is not None and 0.05 <= ltv_scaled <= 10.0:
                msg = f"Scaled property_value by x1000 (was {prop}, now {scaled}) because original value was small and produced implausible LTV."
                return scaled, msg
        if prop > 0 and prop < 10000:
            scaled2 = prop * 100.0
            ltv_scaled2 = loan / scaled2 if scaled2 else None
            if ltv_scaled2 is not None and 0.05 <= ltv_scaled2 <= 10.0:
                msg = f"Scaled property_value by x100 (was {prop}, now {scaled2}) because original value produced implausible LTV."
                return scaled2, msg
    except Exception:
        pass
    return prop, ""

def compute_lending_metrics(parsed: Dict[str, Any]) -> Dict[str, Any]:
    if parsed is None:
        parsed = {}
    p, audit = _canonicalize(parsed)
    loan = p.get("loan_amount")
    prop = p.get("property_value")
    project_cost = p.get("project_cost") or p.get("total_cost")
    rate = p.get("interest_rate_annual")
    term_months = p.get("term_months")
    if loan is None:
        audit.append("Missing or invalid loan_amount")
    if prop is None:
        audit.append("Missing or invalid property_value")
    if project_cost is None:
        audit.append("project_cost / total_cost not provided")
    if rate is None:
        audit.append("Interest rate not provided or invalid")
    if term_months is None:
        audit.append("Loan term (months) not provided or invalid")
    if loan is not None and prop is not None:
        try:
            ltv_raw = loan / prop if prop else None
            if ltv_raw is not None and ltv_raw > 10:
                new_prop, msg = _attempt_property_scaling(loan, prop)
                if msg:
                    audit.append(msg)
                    prop = new_prop
                    p["property_value"] = prop
        except Exception:
            pass
    if loan is not None and prop is not None:
        try:
            if prop > 0 and (prop / loan) > 1000:
                audit.append("Property value is orders of magnitude larger than loan — please verify fields were not swapped.")
        except Exception:
            pass
    lm: Dict[str, Any] = {}
    lm["input_audit_notes"] = list(audit)
    ltv = None
    if loan is not None and prop is not None and prop > 0:
        ltv = loan / prop
    lm["ltv"] = round(ltv, 4) if isinstance(ltv, float) else None
    ltc = None
    if loan is not None and project_cost is not None and project_cost > 0:
        ltc = loan / project_cost
    lm["ltc"] = round(ltc, 4) if isinstance(ltc, float) else None
    amort_df = None
    monthly_amort = None
    total_interest = None
    if loan is not None and rate is not None and term_months:
        r = rate
        if r > 1:
            r = r / 100.0
        try:
            amort_df = amortization_schedule(loan, r, int(term_months))
            monthly_amort = float(amort_df["payment"].iloc[0])
            total_interest = float(amort_df["interest"].sum())
        except Exception as e:
            audit.append(f"Failed to build amortization schedule: {e}")
            amort_df = None
    if monthly_amort is None and loan is not None and rate is not None and term_months:
        try:
            r = rate
            if r > 1:
                r = r / 100.0
            n = int(term_months)
            if r == 0:
                monthly_amort = loan / n
            else:
                monthly_amort = loan * (r / 12.0) / (1 - (1 + r / 12.0) ** (-n))
            total_interest = monthly_amort * n - loan
        except Exception as e:
            audit.append(f"Fallback amortising calc failed: {e}")
            monthly_amort = None
    monthly_io = None
    if loan is not None and rate is not None:
        try:
            r = rate
            if r > 1:
                r = r / 100.0
            monthly_io = loan * r / 12.0
        except Exception as e:
            audit.append(f"Failed to compute interest-only payment: {e}")
            monthly_io = None
    lm["monthly_amortising_payment"] = round(monthly_amort, 2) if isinstance(monthly_amort, (int, float)) else None
    lm["monthly_interest_only_payment"] = round(monthly_io, 2) if isinstance(monthly_io, (int, float)) else None
    lm["total_interest"] = round(total_interest, 2) if isinstance(total_interest, (int, float)) else None
    lm["annual_debt_service_amortising"] = round(lm["monthly_amortising_payment"] * 12.0, 2) if lm.get("monthly_amortising_payment") else None
    lm["annual_debt_service_io"] = round(lm["monthly_interest_only_payment"] * 12.0, 2) if lm.get("monthly_interest_only_payment") else None
    noi = p.get("noi")
    if noi is None:
        annual_rent = p.get("annual_rent")
        operating_expenses = p.get("operating_expenses")
        if annual_rent is not None:
            try:
                noi = annual_rent - (operating_expenses or 0.0)
                lm["noi_estimated_from_rent"] = True
            except Exception:
                noi = None
        else:
            borrower_income = p.get("income")
            if borrower_income is not None:
                noi = borrower_income * 0.30
                lm["noi_estimated_from_income_proxy"] = True
            else:
                noi = None
    lm["noi"] = round(noi, 2) if isinstance(noi, (int, float)) else None
    dscr_amort = None
    dscr_io = None
    try:
        if lm.get("noi") is not None and lm.get("annual_debt_service_amortising"):
            if lm["annual_debt_service_amortising"] > 0:
                dscr_amort = lm["noi"] / lm["annual_debt_service_amortising"]
        if lm.get("noi") is not None and lm.get("annual_debt_service_io"):
            if lm["annual_debt_service_io"] > 0:
                dscr_io = lm["noi"] / lm["annual_debt_service_io"]
    except Exception as e:
        audit.append(f"DSCR computation error: {e}")
        dscr_amort = None
        dscr_io = None
    lm["dscr_amortising"] = round(dscr_amort, 3) if isinstance(dscr_amort, (int, float)) else None
    lm["dscr_interest_only"] = round(dscr_io, 3) if isinstance(dscr_io, (int, float)) else None
    policy_flags = parsed.get("policy_flags") or parsed.get("flags") or []
    bank_red_flags = parsed.get("bank_red_flags") or []
    lm["policy_flags"] = policy_flags
    lm["bank_red_flags"] = bank_red_flags
    ltv_risk = 0.0
    if lm.get("ltv") is not None:
        v = lm["ltv"]
        if v < 0.6:
            ltv_risk = 0.0
        elif v < 0.8:
            ltv_risk = 0.5
        else:
            ltv_risk = 1.0
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
    reasons: List[str] = []
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
    parsed["input_audit"] = audit
    parsed["lending_metrics"] = lm
    return lm
