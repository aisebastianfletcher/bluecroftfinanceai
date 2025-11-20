import os
import json
from typing import Optional

# Default model name (override via environment or Streamlit secrets)
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4")

# Lazy client placeholders
_openai_client = None
_use_new_client = False

def _get_openai_key() -> Optional[str]:
    """
    Prefer Streamlit secrets (st.secrets) when running in the Streamlit environment,
    fall back to environment variables. This allows keys stored in Streamlit Cloud
    secrets to be used without committing them in the repo.
    """
    # Try Streamlit secrets first (won't crash if Streamlit isn't available)
    try:
        import streamlit as st  # type: ignore
        key = st.secrets.get("OPENAI_API_KEY") or st.secrets.get("OPENAI_KEY")
        if key:
            return key
    except Exception:
        pass

    # Fallback to environment variables
    return os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_KEY")

def _ensure_client():
    """
    Initialize the OpenAI client lazily, using whichever library interface is available.
    """
    global _openai_client, _use_new_client

    if _openai_client is not None:
        return

    key = _get_openai_key()
    if not key:
        _openai_client = None
        _use_new_client = False
        return

    # Try new-style client first (openai>=1.0)
    try:
        from openai import OpenAI as OpenAIClient  # type: ignore
        _openai_client = OpenAIClient(api_key=key)
        _use_new_client = True
        return
    except Exception:
        pass

    # Fallback to legacy openai library interface
    try:
        import openai  # type: ignore
        openai.api_key = key
        _openai_client = openai
        _use_new_client = False
        return
    except Exception:
        _openai_client = None
        _use_new_client = False
        return

def _call_chat_completion(messages, max_tokens=350):
    """
    Unified helper that calls chat completions for either the new OpenAI client or
    the legacy openai library. Returns assistant reply text or raises RuntimeError
    with a sanitized message on key/authorization issues.
    """
    _ensure_client()
    if _openai_client is None:
        raise RuntimeError("OPENAI_API_KEY not configured. Add OPENAI_API_KEY in Streamlit Secrets or environment.")

    try:
        if _use_new_client:
            # openai>=1.0 client interface
            resp = _openai_client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=messages,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content
        else:
            # legacy openai library interface
            resp = _openai_client.ChatCompletion.create(
                model=OPENAI_MODEL,
                messages=messages,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content
    except Exception as e:
        err_text = str(e)
        # Sanitize common invalid key errors and give an actionable message
        if "invalid_api_key" in err_text or "Incorrect API key" in err_text or "401" in err_text:
            raise RuntimeError("OPENAI_API_KEY_INVALID: The OpenAI API key is invalid, expired, or not permitted. Update OPENAI_API_KEY in Streamlit Secrets (or environment) and redeploy.")
        raise

def generate_prompt(parsed: dict) -> str:
    lines = []
    lines.append("Please generate a concise underwriting summary for the following application:")
    lines.append(json.dumps(parsed, indent=2))
    return "\n".join(lines)

def generate_summary(parsed: dict) -> str:
    prompt = generate_prompt(parsed)

    # Attempt LLM call if a key/client is available
    try:
        messages = [{"role": "user", "content": prompt}]
        text = _call_chat_completion(messages, max_tokens=350)
        return text
    except RuntimeError as e:
        # Friendly sanitized message for invalid/missing key
        return f"LLM_ERROR: {e}"
    except Exception as e:
        # Return detailed error for unexpected failures (not leaking keys)
        return f"LLM_ERROR: {e}\n\nPrompt:\n{prompt}"

    # Deterministic fallback (if no client/key)
    borrower = parsed.get("borrower", "Unknown")
    income = parsed.get("income", "N/A")
    loan = parsed.get("loan_amount", "N/A")
    prop = parsed.get("property_value", "N/A")
    ltv = parsed.get("ltv", "N/A")
    risk = parsed.get("risk_score", "N/A")
    flags = parsed.get("policy_flags", [])
    summary = (
        f"Borrower: {borrower}\n"
        f"Income: {income}\n"
        f"Loan amount: {loan}\n"
        f"Property value: {prop}\n"
        f"LTV: {ltv}\n"
        f"Risk score (0-1): {risk}\n"
        f"Policy flags: {', '.join(flags) if flags else 'None'}\n\n"
        "Recommendation: Manual review recommended for high LTV or weak affordability."
    )
    return summary

def answer_question(parsed: dict, question: str) -> str:
    prompt = f"Context:\n{json.dumps(parsed, indent=2)}\n\nQuestion: {question}\nAnswer concisely."
    try:
        messages = [{"role": "user", "content": prompt}]
        return _call_chat_completion(messages, max_tokens=200)
    except RuntimeError as e:
        return f"LLM_ERROR: {e}"
    except Exception as e:
        # Simple heuristic fallback for common queries
        q = question.lower()
        if "ltv" in q:
            return f"LTV: {parsed.get('ltv', 'N/A')}"
        if "income" in q:
            return f"Income: {parsed.get('income', 'N/A')}"
        return f"LLM_ERROR: {e}"
