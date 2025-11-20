def combine_signals(parsed: dict) -> dict:
    out = parsed.copy()
    flags = out.get("policy_flags", [])
    out["final_flags"] = flags
    return out
