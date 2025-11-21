"""
Blue Croft Finance — Streamlit app entrypoint (app/main.py)

This file is the main Streamlit UI for the Blue Croft Finance underwriting assistant.
I kept the defensive imports and helpers but updated the visible title to exactly:
    blue croft finance

Drop this file into app/main.py (overwrite existing) and restart Streamlit.
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

# Try to import app.metrics (robust metrics). Fallback to a minimal no-op if missing.
try:
    from app.metrics import compute_lending_metrics, amortization_schedule  # type: ignore
except Exception:
    compute_lending_metrics = None
    amortization_schedule = None

# Try to import parse helpers. Provide no-op fallbacks if missing to avoid crashing.
try:
    from app.parse_helpers import extract_embedded_kv, detect_implausible_loan  # type: ignore
except Exception:
    def extract_embedded_kv(parsed: dict) -> tuple[dict, list]:
        return parsed or {}, []
    def detect_implausible_loan(parsed: dict) -> bool:
        return False

# Optional PDF generator helper
try:
    from app.pdf_form import create_pdf_from_dict  # type: ignore
except Exception:
    create_pdf_from_dict = None

st.set_page_config(page_title="blue croft finance", layout="wide")

# Ensure output folders exist
os.makedirs(ROOT / "output" / "generated_pdfs", exist_ok=True)
os.makedirs(ROOT / "output" / "uploaded_pdfs", exist_ok=True)
os.makedirs(ROOT / "output" / "supporting_docs", exist_ok=True)

# Minimal CSS to create a clean centered title and report box
st.markdown(
    """
    <style>
    .bf-title {
        font-family: "Helvetica Neue", Arial, sans-serif;
        font-size: 28px;
        font-weight: 800;
        color: #002a4e;
        letter-spacing: 1px;
        margin-bottom: 6px;
    }
    .bf-sub {
        color: #345;
        margin-bottom: 18px;
    }
    .report-box { max-width:980px; margin-left:auto; margin-right:auto; background:rgba(255,255,255,0.98);
      padding:18px; border-radius:10px; box-shadow:0 8px 24px rgba(10,30,60,0.06); border:1px solid rgba(15,40,80,0.04); }
    </style>
    """,
    unsafe_allow_html=True,
)

# helper to center altair charts using a middle column
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

def save_supporting_files(files: typing.Iterable[typing.Any], group_name: str) -> list:
    out_dir = ROOT / "output" / "supporting_docs" / group_name
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in files:
        try:
            filename = Path(f.name).name
            dest = out_dir / filename
            with open(dest, "wb") as fh:
                fh.write(f.getbuffer())
            saved.append(str(dest))
        except Exception:
            continue
    return saved

# Initialize session state keys with JSON-serializable defaults
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

# Page header (clean, centered-ish)
st.markdown(f'<div style="text-align:center;"><div class="bf-title">blue croft finance</div><div class="bf-sub">AI underwriting assistant</div></div>', unsafe_allow_html=True)

# Input area: quick calculator, manual parsed, upload/generate PDF
with st.expander("Quick Calculator (create parsed sample)"):
    with st.form("quick_calc"):
        qc1, qc2 = st.columns(2)
        with qc1:
            q_borrower = st.text_input("Borrower", "John Doe")
            q_income = st.number_input("Annual income (GBP)", value=85000, step=1000)
            q_loan = st.number_input("Loan amount (GBP)", value=200000, step=1000)
        with qc2:
            q_prop = st.number_input("Property value (GBP)", value=300000, step=1000)
            q_rate = st.number_input("Interest rate (annual %)", value=9.5, step=0.1)
            q_term_years = st.number_input("Term (years)", value=1, min_value=1, step=1)
        submit_q = st.form_submit_button("Save sample parsed")
    if submit_q:
        parsed = {
            "borrower": q_borrower,
            "income": float(q_income),
            "loan_amount": float(q_loan),
            "property_value": float(q_prop),
            "interest_rate_annual": float(q_rate),
            "loan_term_months": int(q_term_years) * 12,
            "term_months": int(q_term_years) * 12,
        }
        st.session_state["calc_result"] = parsed
        st.success("Sample parsed saved to session (select 'Use quick calculator result' below).")

with st.expander("Manual parsed JSON (paste pipeline output)"):
    st.markdown("Paste raw parsed JSON or Python repr. The app will attempt to extract machine-readable key:value pairs embedded inside strings.")
    manual_text = st.text_area("Raw parsed JSON / text", height=140)
    if st.button("Save manual parsed"):
        try:
            manual_obj = json.loads(manual_text)
        except Exception:
            manual_obj = {"raw_text": manual_text}
        st.session_state["manual_parsed_json"] = json.dumps(manual_obj)
        st.success("Manual parsed saved.")

with st.expander("Upload / Generate PDF"):
    col_a, col_b = st.columns(2)
    with col_a:
        uploaded = st.file_uploader("Upload application PDF", type=["pdf"])
        if uploaded:
            dest_dir = ROOT / "output" / "uploaded_pdfs"
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / f"{int(time.time())}_{Path(uploaded.name).name}"
            with open(dest, "wb") as fh:
                fh.write(uploaded.getbuffer())
            st.session_state["uploaded_pdf"] = str(dest)
            st.success(f"Uploaded and saved: {dest}")
    with col_b:
        if create_pdf_from_dict:
            with st.form("gen_pdf_form"):
                g_borrower = st.text_input("Borrower (for generated PDF)", "John Doe")
                g_income = st.text_input("Income", "85000")
                g_loan = st.text_input("Loan amount", "200000")
                g_property = st.text_input("Property value", "300000")
                g_project_cost = st.text_input("project_cost", "260000")
                g_total_cost = st.text_input("total_cost", "260000")
                g_rate = st.text_input("interest_rate_annual", "9.5")
                g_term = st.text_input("loan_term_months", "12")
                gen_submit = st.form_submit_button("Generate parser-friendly PDF")
            if gen_submit:
                data = {
                    "borrower": g_borrower,
                    "income": _norm_quiet(g_income),
                    "loan_amount": _norm_quiet(g_loan),
                    "property_value": _norm_quiet(g_property),
                    "project_cost": _norm_quiet(g_project_cost),
                    "total_cost": _norm_quiet(g_total_cost),
                    "interest_rate_annual": _norm_quiet(g_rate),
                    "loan_term_months": _norm_quiet(g_term),
                    "term_months": _norm_quiet(g_term),
                }
                try:
                    path = create_pdf_from_dict(data)
                    st.session_state["generated_pdf"] = path
                    st.success(f"PDF created: {path}")
                    with open(path, "rb") as fh:
                        st.download_button("Download generated PDF", data=fh.read(), file_name=Path(path).name, mime="application/pdf")
                except Exception as e:
                    st.error("PDF generation failed: " + str(e))

st.markdown("---")

# Selection of source for analysis
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

# Build parsed dict from selection
parsed: dict = {}
if choice == "Uploaded PDF":
    pdf_path = st.session_state.get("uploaded_pdf")
    parsed = {}
    try:
        from pipeline.pipeline import process_pdf  # type: ignore
        parsed = process_pdf(pdf_path) or {}
    except Exception:
        parsed = {}
        st.info("No pipeline available to auto-extract from PDF; use manual entry or quick calculator.")
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

# Show raw parsed for debugging
st.markdown("### Raw parsed (diagnostic)")
st.write(parsed)

# Extract embedded key:value pairs from string fields
parsed, extracted = extract_embedded_kv(parsed)
if extracted:
    st.info(f"Extracted machine fields from text: {', '.join(extracted)}")
    st.write("Parsed after extraction:", parsed)

# Gentle normalisation of numeric fields
for k in ("loan_amount", "property_value", "project_cost", "total_cost", "interest_rate_annual", "loan_term_months", "term_months", "income"):
    if k in parsed and parsed.get(k) is not None:
        parsed[k] = _norm_quiet(parsed.get(k))

st.markdown("### Normalised parsed (diagnostic)")
st.write(parsed)

# If implausible loan, prompt quick fix
if detect_implausible_loan(parsed):
    st.warning("Detected implausible/suspicious loan amount relative to property/project. Please confirm or fix.")
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

# Compute lending metrics (if metrics module present)
if compute_lending_metrics:
    try:
        lm = compute_lending_metrics(parsed)
    except Exception as e:
        st.error("Metrics computation failed: " + str(e))
        lm = parsed.get("lending_metrics") or {}
else:
    st.warning("Metrics module not installed (app/metrics.py missing). Computation skipped.")
    lm = parsed.get("lending_metrics") or {}

# Persist last analysis (JSON-serializable)
try:
    st.session_state["last_analysis"] = parsed
except Exception:
    try:
        st.session_state["last_analysis"] = json.loads(json.dumps(parsed, default=str))
    except Exception:
        st.session_state["last_analysis"] = {}

# Show audits/notes
audit = parsed.get("input_audit") or []
if isinstance(audit, list) and audit:
    st.warning("Input audit: " + "; ".join(audit))
notes = lm.get("input_audit_notes") if isinstance(lm, dict) else None
if notes:
    st.info("Normalization notes: " + "; ".join(notes))

# Display metrics
st.subheader("Computed lending metrics")
st.json(lm)

# KPIs and summary box
st.markdown('<div class="report-box">', unsafe_allow_html=True)
try:
    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        if lm.get("ltv") is not None:
            st.metric("LTV", f"{lm.get('ltv')*100:.1f}%")
        else:
            st.metric("LTV", "N/A")
    with c2:
        st.metric("Monthly (Amortising)", f"£{lm.get('monthly_amortising_payment'):,}" if lm.get("monthly_amortising_payment") else "N/A")
    with c3:
        st.metric("Monthly (Interest-only)", f"£{lm.get('monthly_interest_only_payment'):,}" if lm.get("monthly_interest_only_payment") else "N/A")
except Exception:
    pass

st.markdown("### Summary")
if lm.get("ltv") is not None:
    st.write(f"LTV: {lm.get('ltv')*100:.2f}%")
else:
    st.write("LTV: N/A")
if lm.get("monthly_amortising_payment") is not None:
    st.write(f"Monthly amortising payment: £{lm.get('monthly_amortising_payment'):,}")
if lm.get("monthly_interest_only_payment") is not None:
    st.write(f"Monthly interest-only payment: £{lm.get('monthly_interest_only_payment'):,}")
if lm.get("noi") is not None:
    st.write(f"NOI: £{lm.get('noi'):,} (estimated: {bool(lm.get('noi_estimated_from_income_proxy', False))})")
st.write(f"Risk category: {lm.get('risk_category')} (score {lm.get('risk_score_computed')})")
st.write("Reasons: " + "; ".join(lm.get("risk_reasons", [])))

# Amortization preview chart if available
if lm.get("amortization_preview_rows"):
    try:
        df_am = pd.DataFrame(lm["amortization_preview_rows"])
        base = alt.Chart(df_am).encode(x=alt.X("month:Q", title="Month"))
        balance_line = base.mark_line(color="#1f77b4").encode(y=alt.Y("balance:Q", title="Remaining balance (£)"))
        center_chart(balance_line, height=260)
    except Exception:
        pass

st.markdown('</div>', unsafe_allow_html=True)

# Q&A deterministic responses
st.markdown("---")
st.subheader("Ask a question about this application")
st.text_input("Question", key="qa_question")
if st.button("Ask"):
    question = st.session_state.get("qa_question", "").strip().lower()
    if not question:
        st.warning("Please enter a question.")
    else:
        if not parsed:
            st.error("No parsed data available. Run Analyse.")
        else:
            answer = None
            if ("why" in question and ("flag" in question or "risk" in question)):
                answer = "Reasons: " + "; ".join(lm.get("risk_reasons", []))
            elif ("bridge" in question or "bridg" in question) and ("suit" in question or "suitable" in question):
                term_ok = parsed.get("loan_term_months") is not None and parsed.get("loan_term_months") <= 24
                ltv_ok = lm.get("ltv") is not None and lm.get("ltv") <= 0.75
                dscr_ok = lm.get("dscr_interest_only") is None or lm.get("dscr_interest_only") >= 1.0
                ok = term_ok and ltv_ok and dscr_ok
                reasons = []
                if not term_ok:
                    reasons.append(f"term months = {parsed.get('loan_term_months')}")
                if not ltv_ok:
                    reasons.append(f"ltv = {lm.get('ltv')}")
                if not dscr_ok:
                    reasons.append(f"interest-only dscr = {lm.get('dscr_interest_only')}")
                answer = "Suitable for typical bridging: " + ("Yes" if ok else "No") + ("" if ok else f". Issues: {', '.join(reasons)}")
            else:
                answer = "No LLM configured — deterministic responses only. Configure LLM for richer answers."
            st.session_state["qa_answer"] = answer

if st.session_state.get("qa_answer"):
    st.markdown("**Answer:**")
    st.write(st.session_state.get("qa_answer"))
