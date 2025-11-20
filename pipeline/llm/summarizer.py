import os
import json

# Config via env
OPENAI_KEY = os.environ.get("OPENAI_API_KEY")
# Allow overriding model name if you want to switch (or leave empty for a sensible default)
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4")

# Try to build a client that works for both openai<1.0 and openai>=1.0
_openai_client = None
_use_new_client = False

if OPENAI_KEY:
    try:
        # New-style client (openai>=1.0)
        from openai import OpenAI as OpenAIClient  # type: ignore
        _openai_client = OpenAIClient(api_key=OPENAI_KEY)
        _use_new_client = True
    except Exception:
        try:
            # Fallback to older openai package interface
            import openai  # type: ignore
            openai.api_key = OPENAI_KEY
            _openai_client = openai
            _use_new_client = False
        except Exception:
            _openai_client = None
            _use_new_client = False
else:
    _openai_client = None
    _use_new_client = False

def _call_chat_completion(messages, max_tokens=350):
    """
    Unified helper that calls the chat completion using either the new openai client (>=1.0)
    or the legacy openai client (<1.0). Returns the assistant reply text.
    Raises Exception on failure.
    """
    if _openai_client is None:
        raise RuntimeError("OPENAI_API_KEY not configured")

    # Use new client API if available
    if _use_new_client:
        # openai>=1.0: client.chat.completions.create(...)
        resp = _openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            max_tokens=max_tokens,
        )
        # New client responses follow resp.choices[0].message.content
        return resp.choices[0].message.content
    else:
        # Legacy API: openai.ChatCompletion.create(...)
        resp = _openai_client.ChatCompletion.create(
            model=OPENAI_MODEL,
            messages=messages,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content

def generate_prompt(parsed: dict) -> str:
    lines = []
    lines.append("Please generate a concise underwriting summary for the following application:")
    lines.append(json.dumps(parsed, indent=2))
    return "\n".join(lines)

def generate_summary(parsed: dict) -> str:
    prompt = generate_prompt(parsed)

    if _openai_client:
        try:
            messages = [{"role": "user", "content": prompt}]
            text = _call_chat_completion(messages, max_tokens=350)
            return text
        except Exception as e:
            return f"LLM_ERROR: {e}\n\nPrompt:\n{prompt}"
    # deterministic fallback (no key configured)
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
    if _openai_client:
        try:
            messages = [{"role": "user", "content": prompt}]
            return _call_chat_completion(messages, max_tokens=200)
        except Exception as e:
            return f"LLM_ERROR: {e}"
    q = question.lower()
    if "ltv" in q:
        return f"LTV: {parsed.get('ltv', 'N/A')}"
    if "income" in q:
        return f"Income: {parsed.get('income', 'N/A')}"
    return "I don't have an LLM key configured. Please set OPENAI_API_KEY to enable richer answers."
