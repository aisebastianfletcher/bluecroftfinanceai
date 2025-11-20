import re

def _find_money(text: str, names):
    low = text.lower()
    for name in names:
        idx = low.find(name.lower())
        if idx != -1:
            snippet = text[idx: idx + 250]
            m = re.search(r"£?\s?([\d,]+(?:\.\d{1,2})?)", snippet)
            if m:
                return float(m.group(1).replace(",", ""))
    m2 = re.search(r"£\s?([\d,]+(?:\.\d{1,2})?)", text)
    if m2:
        return float(m2.group(1).replace(",", ""))
    return None

def parse_fields_from_text(text: str) -> dict:
    """
    Heuristic extraction of borrower and numeric fields.
    """
    result = {}
    mname = re.search(r"Borrower[:\s]+([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)", text)
    if mname:
        result["borrower"] = mname.group(1).strip()
    else:
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        result["borrower"] = lines[0][:80] if lines else "Unknown"

    result["income"] = _find_money(text, ["income", "annual income", "salary"])
    result["loan_amount"] = _find_money(text, ["loan amount", "requested loan", "loan"])
    result["property_value"] = _find_money(text, ["property value", "valuation", "value"])
    try:
        if result["loan_amount"] and result["property_value"]:
            result["ltv"] = result["loan_amount"] / result["property_value"]
        else:
            result["ltv"] = None
    except Exception:
        result["ltv"] = None

    result["bank_red_flags"] = []
    return result
