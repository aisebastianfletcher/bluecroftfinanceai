import os
import json

OPENAI_KEY = os.environ.get("OPENAI_API_KEY")
if OPENAI_KEY:
    import openai
    openai.api_key = OPENAI_KEY

def generate_prompt(parsed: dict) -> str:
    lines = []
    lines.append("Please generate a concise underwriting summary for the following application:")
    lines.append(json.dumps(parsed, indent=2))
    return "\n".join(lines)

def generate_summary(parsed: dict) -> str:
    prompt = generate_prompt(parsed)
    if OPENAI_KEY:
        try:
            resp = openai.ChatCompletion.create(
                model="gpt-4o-mini" if "gpt-4o-mini" in openai.Model.list().data else "gpt-4",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=350,
            )
            text = resp.choices[0].message.content
            return text
        except Exception as e:
            return f"LLM_ERROR: {e}\n\nPrompt:\n{prompt}"
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
    if OPENAI_KEY:
        try:
            resp = openai.ChatCompletion.create(
                model="gpt-4o-mini" if "gpt-4o-mini" in openai.Model.list().data else "gpt-4",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
            )
            return resp.choices[0].message.content
        except Exception as e:
            return f"LLM_ERROR: {e}"
    q = question.lower()
    if "ltv" in q:
        return f"LTV: {parsed.get('ltv', 'N/A')}"
    if "income" in q:
        return f"Income: {parsed.get('income', 'N/A')}"
    return "I don't have an LLM key configured. Please set OPENAI_API_KEY to enable richer answers."
