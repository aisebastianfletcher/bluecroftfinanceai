"""
Blue Croft Finance — Streamlit app entrypoint (app/main.py)

Updated to:
- show a clear "Analyse With AI" button
- produce a professional, resume-style full report (HTML, not monospace/code-style)
- keep defensive imports for optional helpers (metrics, parse_helpers, pdf generator)
- extract embedded machine fields, normalize, prompt fixes, compute metrics, then render full report
"""
from __future__ import annotations
import os
import sys
import io
import json
import time
from pathlib import Path
from datetime import datetime
import typing

import streamlit as st
import pandas as pd
import altair as alt

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Defensive imports: metrics, parse helpers, pdf generator, summarizer
try:
    from app.metrics import compute_lending_metrics, amortization_schedule  # type: ignore
except Exception:
    compute_lending_metrics = None
    amortization_schedule = None

try:
    from app.parse_helpers import extract_embedded_kv, detect_implausible_loan  # type: ignore
except Exception:
    def extract_embedded_kv(parsed: dict) -> tuple[dict, list]:
        return parsed or {}, []
    def detect_implausible_loan(parsed: dict) -> bool:
        return False

try:
    from app.pdf_form import create_pdf_from_dict  # type: ignore
except Exception:
    create_pdf_from_dict = None

# Optional LLM summarizer (non-fatal)
try:
    from pipeline.llm.summarizer import generate_summary, answer_question  # type: ignore
except Exception:
    def generate_summary(parsed: dict) -> str:
        lm = parsed.get("lending_metrics", {}) or {}
        borrower = parsed.get("borrower") or "Unknown"
        ltv = lm.get("ltv")
        ltv_str = f"{ltv*100:.1f}%" if isinstance(ltv, (int, float)) else "N/A"
        return f"{borrower} — LTV: {ltv_str}. Risk: {lm.get('risk_category','N/A')}."
    def answer_question(parsed: dict, question: str) -> str:
        return "LLM not configured. Provide OPENAI_API_KEY / summarizer for richer answers."

st.set_page_config(page_title="blue croft finance", layout="wide")

# ensure output directories exist
os.makedirs(ROOT / "output" / "generated_pdfs", exist_ok=True)
os.makedirs(ROOT / "output" / "uploaded_pdfs", exist_ok=True)
os.makedirs(ROOT / "output" / "supporting_docs", exist_ok=True)

# Small CSS for resume-style output
st.markdown(
    """
    <style>
    .bf-title {
        font-family: "Helvetica Neue", Arial, sans-serif;
        font-size: 34px;
        font-weight: 900;
        color: #072b4f;
        letter-spacing: 1px;
        margin-bottom: 2px;
    }
    .bf-sub { color: #274257; margin-bottom: 18px; font-size:14px; }
    .resume {
        font-family: "Georgia", "Times New Roman", serif;
        color: #122;
        background: #fff;
        padding: 22px;
        border-radius: 6px;
        border: 1px solid #e6eef5;
        max-width: 980px;
        margin: 12px auto;
    }
    .section-title { font-size:16px; font-weight:700; color:#07385e; margin-top:12px; margin-bottom:6px; }
    .kv { display:flex; gap:12px; margin-bottom:6px; }
    .kv .k { width:160px; color:#49606f; font-weight:700; }
    .kv .v { color:#122; }
    .bullet { margin:6px 0; color:#233; }
    .small { color:#556; font-size:13px; }
    </style>
    """,
    unsafe_allow_html=True,
)

def center_chart(chart_obj, use_container_width: bool = True, height: int | None = None):
    try:
        cols = st.columns([1, 10, 1])
        if height is not None:
            try:
                chart_obj = chart_obj.properties(height=height)
            except Exception:
                pass
        cols[1].altair_chart(chart_obj, use_container_width=use_container_width)
    except Exception:
        st.altair_chart(chart_obj, use_container_width=use_container_width)

def _norm_quiet(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip()
    if s == "":
        return None
    s = s.replace(",", "").replace("£", "").replace("$", "").strip()
    try:
        if "." in s:
            return float(s)
        return int(s)
    except Exception:
        return s

# Session defaults
for k, v in [
    ("generated_pdf", None),
    ("uploaded_pdf", None),
    ("calc_result", None),
    ("last_analysis", None),
    ("manual_parsed_json", None),
    ("supporting_groups", {}),
    ("qa_question", ""),
    ("qa_answer", None),
]:
    if k not in st.session_state:
        st.session_state[k] = v

# Header
st.markdown(f'<div style="text-align:center;"><div class="bf-title">blue croft finance</div><div class="bf-sub">AI underwriting assistant — underwriting report (resume style)</div></div>', unsafe_allow_html=True)

# Inputs area (collapsed)
with st.expander("Inputs & Actions", expanded=False):
    cols = st.columns(2)
    with cols[0]:
        st.markdown("Quick sample (use to create a parsed sample):")
        if st.button("Load sample parsed"):
            s = {
                "borrower": "John Doe",
                "income": 85000,
                "loan_amount": 200000,
                "property_value": 300000,
                "project_cost": 260000,
                "total_cost": 260000,
                "interest_rate_annual": 9.5,
                "loan_term_months": 12,
                "term_months": 12,
            }
            st.session_state["calc_result"] = s
            st.success("Sample parsed loaded (select 'Use quick calculator result' below).")
    with cols[1]:
        st.markdown("Generate parser-friendly PDF (optional):")
        if create_pdf_from_dict:
            if st.button("Generate sample PDF"):
                data = {
                    "project_cost": 260000,
                    "total_cost": 260000,
                    "interest_rate_annual": 9.5,
                    "loan_term_months": 12,
                    "borrower": "John Doe",
                    "income": 85000,
                    "loan_amount": 200000,
                    "property_value": 300000
                }
                try:
                    path = create_pdf_from_dict(data)
                    st.session_state["generated_pdf"] = path
                    st.success(f"PDF generated: {path}")
                    with open(path, "rb") as fh:
                        st.download_button("Download generated PDF", data=fh.read(), file_name=Path(path).name, mime="application/pdf")
                except Exception as e:
                    st.error("PDF generation failed: " + str(e))

st.markdown("---")

# Selection source
options = []
if st.session_state.get("uploaded_pdf"):
    options.append("Uploaded PDF")
if st.session_state.get("generated_pdf"):
    options.append("Most recent generated PDF")
if st.session_state.get("calc_result"):
    options.append("Use quick calculator result")
if st.session_state.get("manual_parsed_json"):
    options.append("Use manual parsed values")
if not options:
    options = ["Manual entry (no preloaded data)"]

choice = st.selectbox("Choose source to analyse", options=options, index=0)

# Prepare parsed dict from choice
parsed = {}
if choice == "Uploaded PDF":
    pdf_path = st.session_state.get("uploaded_pdf")
    parsed = {}
    try:
        from pipeline.pipeline import process_pdf  # type: ignore
        parsed = process_pdf(pdf_path) or {}
    except Exception:
        parsed = {}
        st.info("No pipeline available to auto-extract from PDF; use manual parsed or quick calculator.")
elif choice == "Most recent generated PDF":
    gen = st.session_state.get("generated_pdf")
    if gen:
        try:
            from pipeline.pipeline import process_pdf  # type: ignore
            parsed = process_pdf(gen) or {}
        except Exception:
            parsed = {}
            st.info("Pipeline not available to extract generated PDF.")
elif choice == "Use quick calculator result":
    parsed = dict(st.session_state.get("calc_result") or {})
elif choice == "Use manual parsed values":
    try:
        parsed = json.loads(st.session_state.get("manual_parsed_json") or "{}")
    except Exception:
        parsed = {"raw_text": st.session_state.get("manual_parsed_json")}
else:
    parsed = {}

# Raw parsed diagnostic (collapsible)
with st.expander("Raw parsed (diagnostic)"):
    st.write(parsed)

# Extract embedded machine fields if any
parsed, extracted = extract_embedded_kv(parsed)
if extracted:
    st.info(f"Extracted fields: {', '.join(extracted)}")

# Gentle normalization
for k in ("loan_amount", "property_value", "project_cost", "total_cost", "interest_rate_annual", "loan_term_months", "term_months", "income"):
    if k in parsed and parsed.get(k) is not None:
        parsed[k] = _norm_quiet(parsed.get(k))

# Detect implausible loan and let user fix
if detect_implausible_loan(parsed):
    st.warning("Detected an implausible/suspicious loan amount relative to property/project. Please confirm or fix below.")
    with st.form("fix_loan_amount"):
        s1 = parsed.get("project_cost")
        s2 = parsed.get("total_cost") or s1
        opts = ["Enter manually"]
        if s1:
            opts.append(f"Set loan_amount = project_cost ({s1})")
        if s2:
            opts.append(f"Set loan_amount = total_cost ({s2})")
        choice_fix = st.radio("Fix option", opts)
        manual_val = st.number_input("Manual loan amount (GBP)", value=0.0, step=100.0, format="%.2f")
        applied = st.form_submit_button("Apply fix")
    if applied:
        if choice_fix.startswith("Set loan_amount = project_cost") and s1:
            parsed["loan_amount"] = s1
            st.success(f"Applied: loan_amount = {s1}")
        elif choice_fix.startswith("Set loan_amount = total_cost") and s2:
            parsed["loan_amount"] = s2
            st.success(f"Applied: loan_amount = {s2}")
        elif manual_val and manual_val > 0:
            parsed["loan_amount"] = manual_val
            st.success(f"Applied manual loan_amount = {manual_val}")
        else:
            st.warning("No valid fix applied. Please enter a manual positive value.")

# MAIN ANALYSIS BUTTON
if st.button("Analyse With AI"):
    # compute metrics first
    if compute_lending_metrics:
        try:
            lm = compute_lending_metrics(parsed)
        except Exception as e:
            st.error("Metrics computation failed: " + str(e))
            lm = parsed.get("lending_metrics") or {}
    else:
        st.warning("Metrics module unavailable; install app/metrics.py for full computation.")
        lm = parsed.get("lending_metrics") or {}

    # persist last analysis
    try:
        st.session_state["last_analysis"] = parsed
    except Exception:
        st.session_state["last_analysis"] = json.loads(json.dumps(parsed, default=str))

    # show audits if any
    audit = parsed.get("input_audit") or lm.get("input_audit_notes") or []
    if audit:
        st.warning("Input audit: " + "; ".join(audit))

    # produce professional resume-style full report (HTML)
    def render_resume_report(parsed: dict, lm: dict) -> str:
        borrower = parsed.get("borrower", "N/A")
        income = parsed.get("income", "N/A")
        loan_amount = parsed.get("loan_amount", "N/A")
        property_value = parsed.get("property_value", "N/A")
        project_cost = parsed.get("project_cost", parsed.get("total_cost", "N/A"))
        rate = parsed.get("interest_rate_annual", "N/A")
        term = parsed.get("loan_term_months", parsed.get("term_months", "N/A"))
        ltv = lm.get("ltv")
        ltv_str = f"{ltv*100:.1f}%" if isinstance(ltv, (int, float)) else "N/A"
        monthly_am = lm.get("monthly_amortising_payment")
        monthly_io = lm.get("monthly_interest_only_payment")
        dscr_am = lm.get("dscr_amortising")
        dscr_io = lm.get("dscr_interest_only")
        risk_cat = lm.get("risk_category", "N/A")
        risk_score = lm.get("risk_score_computed", "N/A")
        reasons = lm.get("risk_reasons", [])
        summary_lines = []

        # Build HTML
        html = ['<div class="resume">']
        html.append(f'<div style="display:flex; justify-content:space-between; align-items:baseline;"><div><h2 style="margin:0">{borrower}</h2><div class="small">Underwriting report</div></div><div style="text-align:right"><strong>{risk_cat}</strong><div class="small">Score: {risk_score}</div></div></div>')
        html.append('<hr />')

        # Contact & Key Facts
        html.append('<div class="section-title">Key facts</div>')
        html.append('<div class="kv"><div class="k">Loan amount</div><div class="v">£{:,}</div></div>'.format(int(loan_amount) if isinstance(loan_amount, (int, float)) else loan_amount))
        html.append('<div class="kv"><div class="k">Project / Total cost</div><div class="v">£{:,}</div></div>'.format(int(project_cost) if isinstance(project_cost, (int, float)) else project_cost))
        html.append('<div class="kv"><div class="k">Interest rate (annual)</div><div class="v">{}</div></div>'.format(f"{rate}%" if isinstance(rate, (int, float)) and rate>1 else f"{rate}" if rate!="N/A" else rate))
        html.append('<div class="kv"><div class="k">Loan term</div><div class="v">{}</div></div>'.format(f"{term} months"))
        html.append('<div class="kv"><div class="k">Property value</div><div class="v">£{:,}</div></div>'.format(int(property_value) if isinstance(property_value, (int, float)) else property_value))
        html.append('<div class="kv"><div class="k">LTV</div><div class="v">{}</div></div>'.format(ltv_str))

        # Financials
        html.append('<div class="section-title">Financials & Affordability</div>')
        html.append('<div class="kv"><div class="k">Annual income</div><div class="v">£{:,}</div></div>'.format(int(income) if isinstance(income,(int,float)) else income))
        if monthly_am is not None:
            html.append('<div class="kv"><div class="k">Monthly (Amortising)</div><div class="v">£{:,}</div></div>'.format(int(monthly_am)))
        if monthly_io is not None:
            html.append('<div class="kv"><div class="k">Monthly (Interest-only)</div><div class="v">£{:,}</div></div>'.format(int(monthly_io)))
        html.append('<div class="kv"><div class="k">NOI</div><div class="v">£{:,}</div></div>'.format(int(lm.get("noi")) if lm.get("noi") is not None else "N/A"))

        # Metrics & Ratios
        html.append('<div class="section-title">Metrics</div>')
        html.append('<div class="kv"><div class="k">DSCR (Amortising)</div><div class="v">{}</div></div>'.format(f"{dscr_am:.2f}" if isinstance(dscr_am,(int,float)) else "N/A"))
        html.append('<div class="kv"><div class="k">DSCR (Interest-only)</div><div class="v">{}</div></div>'.format(f"{dscr_io:.2f}" if isinstance(dscr_io,(int,float)) else "N/A"))
        html.append('<div class="kv"><div class="k">Total interest (est.)</div><div class="v">£{:,}</div></div>'.format(int(lm.get("total_interest")) if lm.get("total_interest") is not None else "N/A"))

        # Risk & Reasons
        html.append('<div class="section-title">Risk assessment</div>')
        if reasons:
            html.append('<ul>')
            for r in reasons:
                html.append(f'<li class="bullet">{r}</li>')
            html.append('</ul>')
        else:
            html.append('<div class="kv"><div class="v">No automated flags detected.</div></div>')

        # Amortization preview table (if present)
        if lm.get("amortization_preview_rows"):
            html.append('<div class="section-title">Amortization (first 12 months)</div>')
            rows = lm["amortization_preview_rows"]
            # build small HTML table
            html.append('<table style="width:100%; border-collapse:collapse;">')
            html.append('<tr style="background:#f4f8fb;"><th style="text-align:left;padding:6px">Month</th><th style="text-align:right;padding:6px">Payment</th><th style="text-align:right;padding:6px">Interest</th><th style="text-align:right;padding:6px">Principal</th><th style="text-align:right;padding:6px">Balance</th></tr>')
            for r in rows:
                html.append(f'<tr><td style="padding:6px">{r.get("month")}</td><td style="padding:6px;text-align:right">£{r.get("payment"):,}</td><td style="padding:6px;text-align:right">£{r.get("interest"):,}</td><td style="padding:6px;text-align:right">£{r.get("principal"):,}</td><td style="padding:6px;text-align:right">£{r.get("balance"):,}</td></tr>')
            html.append('</table>')

        # Footer / notes
        html.append('<div style="margin-top:12px;" class="small">Audit notes: {}</div>'.format(", ".join(audit) if isinstance(audit, list) else str(audit)))
        html.append('</div>')  # end resume
        return "\n".join(html)

    report_html = render_resume_report(parsed, lm)
    # Render the report (not code/monsospace)
    st.markdown(report_html, unsafe_allow_html=True)

    # Download JSON report
    try:
        payload = {"parsed": parsed, "lending_metrics": lm}
        b = io.BytesIO()
        b.write(json.dumps(payload, indent=2).encode("utf-8"))
        b.seek(0)
        st.download_button("Download report (JSON)", data=b, file_name="underwriting_report.json", mime="application/json")
    except Exception:
        pass

    # Optional LLM summary area
    with st.expander("AI Summary"):
        try:
            summ = generate_summary(parsed)
        except Exception:
            summ = generate_summary(parsed)
        st.write(summ)

# If user didn't press Analyse yet, still show a compact preview of key metrics when available
if st.session_state.get("last_analysis") and not st.session_state.get("qa_answer"):
    preview = st.session_state["last_analysis"].get("lending_metrics") if isinstance(st.session_state["last_analysis"], dict) else None
    if preview:
        st.markdown("<div style='max-width:980px;margin:auto;'>", unsafe_allow_html=True)
        st.markdown("#### Last computed metrics (preview)")
        st.json(preview)
        st.markdown("</div>", unsafe_allow_html=True)

# Q&A (deterministic fallback)
st.markdown("---")
st.subheader("Ask a question about this application")
st.text_input("Question", key="qa_question")
if st.button("Ask"):
    q = st.session_state.get("qa_question", "").strip()
    if not q:
        st.warning("Please enter a question.")
    else:
        parsed_last = st.session_state.get("last_analysis") or parsed
        lm_last = parsed_last.get("lending_metrics") if isinstance(parsed_last, dict) else {}
        # simple deterministic answers
        ql = q.lower()
        if "why" in ql and ("flag" in ql or "risk" in ql):
            ans = "Reasons: " + "; ".join(lm_last.get("risk_reasons", []))
        elif "summary" in ql or "financial position" in ql:
            try:
                ans = generate_summary(parsed_last)
            except Exception:
                ans = "Summary not available."
        else:
            try:
                ans = answer_question(parsed_last, q)
            except Exception:
                ans = "LLM not available; deterministic response not found."
        st.session_state["qa_answer"] = ans
if st.session_state.get("qa_answer"):
    st.markdown("**Answer:**")
    st.write(st.session_state.get("qa_answer"))
