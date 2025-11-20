def validate_structured(parsed: dict) -> bool:
    required = ["borrower", "income", "loan_amount", "property_value"]
    for r in required:
        if r not in parsed or parsed.get(r) is None:
            return False
    return True
