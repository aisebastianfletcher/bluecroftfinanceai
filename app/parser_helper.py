# app/parse_helpers.py
# Helper functions to extract embedded machine-readable key:value pairs from parsed text fields
# and to suggest fixes when loan_amount appears implausible.
import re
from typing import Dict, Any, Tuple, List

# Map common label variants (normalized -> canonical name)
ALIAS_TO_CANONICAL = {
    "project_cost": ["project_cost", "project cost", "total_project_cost", "total project cost", "total_cost"],
    "total_cost": ["total_cost", "total cost", "totalprojectcost"],
    "interest_rate_annual": ["interest_rate_annual", "interest rate (annual)", "interest_rate", "interest rate", "rate", "annual_rate"],
    "loan_term_months": ["loan_term_months", "loan term months", "term_months", "term", "loan_term", "loan term"],
    "term_months": ["term_months", "term", "loan_term_months"],
    "loan_amount": ["loan_amount", "loan", "requested_loan", "amount_requested"],
    "property_value": ["property_value", "property value", "property_value_estimate", "property"],
    "income": ["income", "annual_income"],
    "borrower": ["borrower", "applicant", "name"],
    "arv": ["arv", "after_repair_value"],
    "purchase_price": ["purchase_price", "purchase price"],
    "refurbishment_budget": ["refurbishment_budget", "refurb budget", "refurbishment"],
    "dscr": ["dscr"],
    "monthly_rent": ["monthly_rent", "monthly rent", "rent_monthly"],
    "operating_costs": ["operating_costs", "operating costs", "operating_expenses"],
}

# Reverse mapping: variant -> canonical
_variant_to_canonical = {}
for canon, variants in ALIAS_TO_CANONICAL.items():
    for v in variants:
        _variant_to_canonical[v.lower().replace("_", " ").replace("-", " ")] = canon

_num_rx = re.compile(r'(-?\d[\d,\.]*)')  # captures numbers with commas and decimals
_kv_rx = re.compile(
    r'(?:["\']?\b([A-Za-z0-9_ \(\)\-]+?)["\']?\s*[:=]\s*(?:["\']?([^\n\r,,{}]+?)["\']?))',
    re.I
)
_json_kv_rx = re.compile(r'"([^"]+)"\s*:\s*(".*?"|[0-9.\-]+)', re.I)


def _normalize_key_label(label: str) -> str:
    """Return canonical key name for a label if a known variant is found, else normalized label."""
    if not label:
        return ""
    n = label.strip().lower().replace("_", " ").replace("-", " ")
    for variant, canon in _variant_to_canonical.items():
        if variant in n or n in variant:
            return canon
    return re.sub(r'[^\w]', '_', label.strip()).lower()


def _to_number(s: str):
    """Convert a numeric-like string to int/float where possible, else return trimmed string."""
    if s is None:
        return None
    s = str(s).strip()
    if s == "":
        return None
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1].strip()
    s_clean = s.replace(",", "").replace("£", "").replace("$", "").replace("%", "").strip()
    try:
        if re.fullmatch(r'-?\d+', s_clean):
            return int(s_clean)
        if re.fullmatch(r'-?\d+\.\d+', s_clean):
            return float(s_clean)
    except Exception:
        pass
    m = _num_rx.search(s_clean)
    if m:
        num = m.group(1).replace(",", "")
        try:
            if '.' in num:
                return float(num)
            return int(num)
        except Exception:
            try:
                return float(num)
            except Exception:
                return s.strip()
    return s.strip()


def extract_embedded_kv(parsed: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """
    Scan string values in parsed for embedded key:value pairs or JSON key/value.
    Merge discovered values into parsed using canonical key names where possible.
    Returns (parsed_updated, list_of_extracted_keys).
    """
    if parsed is None:
        return parsed, []

    extracted_keys: List[str] = []
    for k, v in list(parsed.items()):
        if not isinstance(v, str):
            continue
        txt = v

        # JSON-like "key": value
        for jm in _json_kv_rx.finditer(txt):
            key_raw = jm.group(1)
            val_raw = jm.group(2)
            canon = _normalize_key_label(key_raw)
            val = _to_number(val_raw)
            if canon and parsed.get(canon) in (None, "", parsed.get(canon)):
                parsed[canon] = val
                extracted_keys.append(canon)

        # Generic key: value matches (key: value)
        for m in _kv_rx.finditer(txt):
            key_raw = m.group(1)
            val_raw = m.group(2)
            canon = _normalize_key_label(key_raw)
            val = _to_number(val_raw)
            if canon and parsed.get(canon) in (None, "", parsed.get(canon)):
                parsed[canon] = val
                extracted_keys.append(canon)

        # Inline tokens like key: 12345
        inline_rx = re.finditer(r'([A-Za-z0-9_ \(\)\-]+?)\s*:\s*([0-9,\.\-]+)', txt)
        for m in inline_rx:
            key_raw = m.group(1)
            val_raw = m.group(2)
            canon = _normalize_key_label(key_raw)
            val = _to_number(val_raw)
            if canon and parsed.get(canon) in (None, "", parsed.get(canon)):
                parsed[canon] = val
                extracted_keys.append(canon)

    # deduplicate
    extracted_keys = list(dict.fromkeys(extracted_keys))
    return parsed, extracted_keys


def detect_implausible_loan(parsed: Dict[str, Any]) -> bool:
    """
    Return True when loan_amount is implausibly small vs property_value or project_cost.
    Heuristics:
      - loan_amount < 100 OR loan_amount / property_value < 0.01
    """
    try:
        loan = parsed.get("loan_amount")
        prop = parsed.get("property_value") or parsed.get("project_cost") or parsed.get("total_cost")
        if loan is None:
            return False
        if isinstance(loan, (int, float)) and loan > 0:
            if loan < 100:
                return True
            if prop and isinstance(prop, (int, float)) and prop > 0 and loan / prop < 0.01:
                return True
    except Exception:
        return False
    return False
