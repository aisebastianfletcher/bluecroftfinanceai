def evaluate_policy_rules(parsed: dict) -> list:
    flags = []
    try:
        ltv = parsed.get("ltv")
        if ltv is not None and ltv > 0.7:
            flags.append("High LTV")
    except Exception:
        pass
    income = parsed.get("income")
    if income is not None and income < 20000:
        flags.append("Weak affordability")
    loan = parsed.get("loan_amount")
    prop = parsed.get("property_value")
    if loan is not None and prop is not None and loan > prop:
        flags.append("Loan > Property value")
    if parsed.get("bank_red_flags"):
        flags.extend(parsed.get("bank_red_flags"))
    return flags
