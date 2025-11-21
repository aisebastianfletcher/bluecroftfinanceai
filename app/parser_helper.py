"""
app/parse_helpers.py

Helpers to extract embedded machine-readable key:value pairs from textual fields
and to detect implausible loan amounts.
"""
import re
from typing import Dict, Any, Tuple, List

_num_rx = re.compile(r'(-?\d[\d,\.]*)')
_kv_rx = re.compile(r'(?:["\']?\b([A-Za-z0-9_ \(\)\-]+?)["\']?\s*[:=]\s*(?:["\']?([^\n\r,,{}]+?)["\']?))', re.I)
_json_kv_rx = re.compile(r'"([^"]+)"\s*:\s*(".*?"|[0-9.\-]+)', re.I)

def _to_number(s: str):
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

def _normalize_key_label(label: str) -> str:
    if not label:
        return ""
    return re.sub(r'[^\w]', '_', label.strip()).lower()

def extract_embedded_kv(parsed: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    if parsed is None:
        return parsed, []
    extracted: List[str] = []
    for k, v in list(parsed.items()):
        if not isinstance(v, str):
            continue
        txt = v
        for jm in _json_kv_rx.finditer(txt):
            key_raw = jm.group(1)
            val_raw = jm.group(2)
            canon = _normalize_key_label(key_raw)
            val = _to_number(val_raw)
            if canon and parsed.get(canon) in (None, "", parsed.get(canon)):
                parsed[canon] = val
                extracted.append(canon)
        for m in _kv_rx.finditer(txt):
            key_raw = m.group(1)
            val_raw = m.group(2)
            canon = _normalize_key_label(key_raw)
            val = _to_number(val_raw)
            if canon and parsed.get(canon) in (None, "", parsed.get(canon)):
                parsed[canon] = val
                extracted.append(canon)
    extracted = list(dict.fromkeys(extracted))
    return parsed, extracted

def detect_implausible_loan(parsed: Dict[str, Any]) -> bool:
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
