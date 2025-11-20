import os
from pipeline.extractor.pdf_to_text import extract_text_from_pdf
from pipeline.extractor.field_parser import parse_fields_from_text
from pipeline.ml.predict import predict_risk
from pipeline.rules.policy_rules import evaluate_policy_rules
from pipeline.llm.summarizer import generate_summary
from utils.file_utils import save_json

def process_pdf(pdf_path: str) -> dict:
    """
    Orchestrates extraction -> parsing -> ML -> rules -> LLM summarisation.
    """
    text = extract_text_from_pdf(pdf_path)
    parsed = parse_fields_from_text(text)

    if parsed.get("ltv") is None:
        try:
            parsed["ltv"] = parsed["loan_amount"] / parsed["property_value"]
        except Exception:
            parsed["ltv"] = None

    risk = predict_risk(parsed)
    parsed["risk_score"] = risk

    flags = evaluate_policy_rules(parsed)
    parsed["policy_flags"] = flags

    summary = generate_summary(parsed)
    parsed["summary"] = summary

    os.makedirs("output/analysis_reports", exist_ok=True)
    save_json(parsed, os.path.join("output/analysis_reports", os.path.basename(pdf_path) + ".analysis.json"))
    return parsed

def process_data(structured: dict, ask: str = None) -> str:
    if ask:
        from pipeline.llm.qna import ask as llm_ask
        return llm_ask(structured, ask)
    return structured.get("summary", "")
