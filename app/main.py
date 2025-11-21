# app/main.py
# Bluecroft Finance — Streamlit app (full main.py)
# - Uses app.metrics.compute_lending_metrics for robust lending calculations
# - Uses app.parse_helpers.extract_embedded_kv to extract machine fields embedded inside text
# - Prompts user to fix implausible loan amounts and missing required fields
# - Stores manual parsed payload as JSON string in session_state to avoid StreamlitAPIException
# - Stacked single-column report layout and centered charts (via center_chart helper)
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

# ensure repo root importable
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# robust metrics and parse helpers (make sure these files exist: app/metrics.py, app/parse_helpers.py)
from app.metrics import compute_lending_metrics, amortization_schedule  # type: ignore
from app.parse_helpers import extract_embedded_kv, detect_implausible_loan  # type: ignore

st.set_page_config(page_title="Bluecroft Finance — AI Lending Assistant", layout="wide")

# Output dirs
os.makedirs(ROOT / "output" / "generated_pdfs", exist_ok=True)
os.makedirs(ROOT / "output" / "supporting_docs", exist_ok=True)

# small CSS to keep charts centered
st.markdown(
    """
    <style>
    .report-box { max-width:980px; margin-left:auto; margin-right:auto; background:rgba(255,255,255,0.98); padding:18px; border-radius:10px; }
    .stAltairChart, .stVegaLiteChart, .vega-embed { display:block !important; margin-left:auto !important; margin-right:auto !important; width:100% !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

# helper to center altair charts using three-column trick
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

# initialize session_state keys (only simple types or JSON strings)
if "generated_pdf" not in st.session_state:
    st.session_state["generated_pdf"] = None
if "uploaded_pdf" not in st.session_state:
    st.session_state["uploaded_pdf"] = None
if "calc_result" not in st.session_state:
    st.session_state["calc_result"] = None
if "last_analysis" not in st.session_state:
    st.session_state["last_analysis"] = None
if "qa_question" not in st.session_state:
    st.session_state["qa_question"] = ""
if "qa_answer" not in st.session_state:
    st.session_state["qa_answer"] = None
# manual parsed will be stored as JSON string to avoid Streamlit session issues
if "manual_parsed_json" not in st.session_state:
    st.session_state["manual_parsed_json"] = None
# supporting docs mapping group -> list(paths)
if "supporting_groups" not in st.session_state:
    st.session_state["supporting_groups"] = {}

# Page header
st.markdown("<h2>Bluecroft Finance — AI Lending Assistant</h2>", unsafe_allow_html=True)
st.markdown("Fill the form, upload a PDF, or use the quick calculator. Then click 'Analyse With AI'.")

# Left: Inputs / Forms
with st.expander("Quick Calculator (create sample parsed data)"):
    with st.form("calc"):
        c_borrower = st.text_input("Borrower name", "John Doe")
        c_income = st.number_input("Annual income (GBP)", value=85000, step=1000)
        c_loan = st.number_input("Loan amount (GBP)", value=200000, step=1000)
        c_property = st.number_input("Property value (GBP)", value=300000, step=1000)
        c_rate = st.number_input("Interest rate (annual %)", value=9.5, step=0.1)
        c_term_years = st.number_input("Term (years)", value=1, min_value=1, step=1)
        calc_submit = st.form_submit_button("Create sample parsed")
    if calc_submit:
        parsed = {
            "borrower": c_borrower,
            "income": float(c_income),
            "loan_amount": float(c_loan),
            "property_value": float(c_property),
            # The parser expects interest_rate_annual possibly as percent (9.5) — metrics handles >1 -> /100
            "interest_rate_annual": float(c_rate),
            "loan_term_months": int(c_term_years) * 12,
            "term_months": int(c_term_years) * 12,  # compatibility
        }
        st.session_state["calc_result"] = parsed
        st.success("Sample parsed stored; choose 'Use quick calculator result' in Selection and click Analyse.")

with st.expander("Manual parsed JSON"):
    st.markdown("Paste a raw parsed dict / JSON output from your pipeline. The app will try to extract machine fields embedded inside strings.")
    manual_text = st.text_area("Raw parsed JSON (or Python repr)", height=140)
    if st.button("Save manual parsed"):
        # attempt to parse JSON; if fails, store as raw string inside a JSON wrapper to allow extract_embedded_kv to work
        manual_obj = None
        try:
            manual_obj = json.loads(manual_text)
        except Exception:
            # fall back to putting the raw string into a field 'raw_text'
            manual_obj = {"raw_text": manual_text}
        # serialize to JSON string for safe session storage
        st.session_state["manual_parsed_json"] = json.dumps(manual_obj)
        st.success("Manual parsed JSON saved (to be used as analysis source).")

# Upload PDF (basic)
with st.expander("Upload PDF (optional)"):
    uploaded_file = st.file_uploader("Upload application PDF (optional)", type=["pdf"])
    if uploaded_file is not None:
        dest_dir = ROOT / "output" / "uploaded_pdfs"
        dest_dir.mkdir(parents=True, exist_ok=True)
        fname = f"{int(time.time())}_{Path(uploaded_file.name).name}"
        dest = dest_dir / fname
        with open(dest, "wb") as fh:
            fh.write(uploaded_file.getbuffer())
        st.session_state["uploaded_pdf"] = str(dest)
        st.success(f"Uploaded PDF saved to {dest}")

st.markdown("---")

# Selection: choose data source to analyse
sources = []
if st.session_state.get("uploaded_pdf"):
    sources.append("Uploaded PDF")
if st.session_state.get("generated_pdf"):
    sources.append("Most recent generated PDF")
if st.session_state.get("calc_result"):
    sources.append("Use quick calculator result")
if st.session_state.get("manual_parsed_json"):
    sources.append("Use manual parsed values")
if not sources:
    sources = ["Manual entry (no preloaded data)"]

choice = st.selectbox("Choose source to inspect / analyse", options=sources, index=0)

# Prepare parsed dict from selected source
parsed: dict = {}
if choice == "Use quick calculator result":
    parsed = dict(st.session_state.get("calc_result") or {})
elif choice == "Use manual parsed values":
    try:
        parsed = json.loads(st.session_state.get("manual_parsed_json") or "{}")
    except Exception:
        parsed = {"raw_text": st.session_state.get("manual_parsed_json")}
elif choice == "Uploaded PDF":
    # NOTE: pipeline extraction is repository-specific. Try to call pipeline if present.
    pdf_path = st.session_state.get("uploaded_pdf")
    parsed = {}
    try:
        try:
            from pipeline.pipeline import process_pdf  # type: ignore
            parsed = process_pdf(pdf_path) or {}
        except Exception:
            # pipeline not installed or failed; leave parsed empty for manual input
            parsed = {}
            st.warning("No pipeline available to extract PDF — use Manual parsed values or Quick Calculator.")
    except Exception as e:
        st.error("Error while trying to process uploaded PDF: " + str(e))
        parsed = {}
else:
    # Manual entry fallback (user can edit raw parsed above and Save)
    parsed = {}

# Display raw parsed for debugging
st.markdown("### Raw parsed (diagnostic)")
st.write(parsed)

# --- INSERTION POINT: extract embedded machine fields and suggest fixes ---
# Use parse_helpers to extract key:value pairs that may be embedded inside string fields
parsed, extracted = extract_embedded_kv(parsed)
if extracted:
    st.info(f"Extracted machine fields from text: {', '.join(extracted)}")
    st.write("Parsed after extraction:", parsed)

# Normalize a few common fields (strip currency formatting) - keep minimal so canonicaliser in metrics can work well
def _norm_quiet(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip()
    if s == "":
        return None
    s = s.replace(",", "").replace("£", "").replace("$", "")
    # try numeric
    try:
        if "." in s:
            return float(s)
        return int(s)
    except Exception:
        return s

# apply normalisation gently to keys we care about
for k in ("loan_amount", "property_value", "project_cost", "total_cost", "interest_rate_annual", "loan_term_months", "term_months", "income"):
    if k in parsed:
        parsed[k] = _norm_quiet(parsed.get(k))

# Show normalised parsed
st.markdown("### Normalised parsed (diagnostic)")
st.write(parsed)

# If embedded extraction didn't pick up required fields, show audit and supply-missing form later (metrics will also audit)
# Detect implausible loan and prompt quick fix before computing metrics
if detect_implausible_loan(parsed):
    st.warning("Detected implausible loan amount (very small vs property / project). Please confirm or fix the loan amount.")
    with st.form("fix_loan_amount"):
        suggested1 = parsed.get("project_cost")
        suggested2 = parsed.get("total_cost") or parsed.get("project_cost")
        options = ["Enter manually"]
        if suggested1:
            options.append(f"Set loan_amount = project_cost ({suggested1})")
        if suggested2:
            options.append(f"Set loan_amount = total_cost ({suggested2})")
        opt = st.radio("Fix option", options)
        manual_val = st.number_input("Manual loan amount (GBP)", value=0.0, step=100.0, format="%.2f")
        apply_fix = st.form_submit_button("Apply fix")
    if apply_fix:
        if opt.startswith("Set loan_amount = project_cost") and suggested1:
            parsed["loan_amount"] = suggested1
            st.success(f"Applied: loan_amount = {suggested1}")
        elif opt.startswith("Set loan_amount = total_cost") and suggested2:
            parsed["loan_amount"] = suggested2
            st.success(f"Applied: loan_amount = {suggested2}")
        elif manual_val and manual_val > 0:
            parsed["loan_amount"] = manual_val
            st.success(f"Applied manual loan_amount = {manual_val}")
        else:
            st.warning("No valid fix applied. Please enter a manual value > 0.")

# Compute metrics (this will attach input_audit and lending_metrics into parsed)
try:
    metrics = compute_lending_metrics(parsed)
except Exception as e:
    st.error("Metrics computation failed: " + str(e))
    metrics = parsed.get("lending_metrics", {})

# Persist last analysis (store only primitives / JSON-friendly dict)
st.session_state["last_analysis"] = parsed

# Show input audit from metrics (if any)
audit = parsed.get("input_audit") or parsed.get("input_audit", []) or parsed.get("input_audit", [])
# The metrics implementation may also put notes into parsed["input_audit"] or parsed["lending_metrics"]["input_audit_notes"]
if isinstance(audit, list) and audit:
    st.warning("Input audit: " + "; ".join(audit))
# also check lending_metrics.input_audit_notes
lm = parsed.get("lending_metrics") or {}
note_list = lm.get("input_audit_notes") or []
if note_list:
    st.info("Normalization notes: " + "; ".join(note_list))

# Display computed metrics
st.subheader("Computed lending metrics")
st.json(lm)

# Human-friendly summary and KPIs
st.markdown('<div class="report-box">', unsafe_allow_html=True)
try:
    k1, k2, k3 = st.columns([1, 1, 1])
    with k1:
        if lm.get("ltv") is not None:
            st.metric("LTV", f"{lm.get('ltv')*100:.1f}%")
        else:
            st.metric("LTV", "N/A")
    with k2:
        st.metric("Monthly (Amortising)", f"£{lm.get('monthly_amortising_payment'):,}" if lm.get("monthly_amortising_payment") else "N/A")
    with k3:
        st.metric("Monthly (Interest-only)", f"£{lm.get('monthly_interest_only_payment'):,}" if lm.get("monthly_interest_only_payment") else "N/A")
except Exception:
    pass

st.markdown("### Summary")
if lm.get("ltv") is not None:
    st.write(f"LTV: {lm.get('ltv')*100:.2f}%")
else:
    st.write("LTV: N/A")
if lm.get("monthly_interest_only_payment") is not None:
    st.write(f"Monthly interest-only payment: £{lm.get('monthly_interest_only_payment'):,}")
if lm.get("monthly_amortising_payment") is not None:
    st.write(f"Monthly amortising payment: £{lm.get('monthly_amortising_payment'):,}")
if lm.get("noi") is not None:
    st.write(f"NOI: £{lm.get('noi'):,} (estimated: {bool(lm.get('noi_estimated_from_income_proxy', False))})")
st.write(f"Risk category: {lm.get('risk_category')} (score {lm.get('risk_score_computed')})")
st.write("Reasons: " + "; ".join(lm.get("risk_reasons", [])))

# Small amortization chart if available
if lm.get("amortization_preview_rows"):
    try:
        df_am = pd.DataFrame(lm["amortization_preview_rows"])
        base = alt.Chart(df_am).encode(x=alt.X("month:Q", title="Month"))
        balance_line = base.mark_line(color="#1f77b4").encode(y=alt.Y("balance:Q", title="Remaining balance (£)"))
        center_chart((balance_line), height=260)
    except Exception:
        pass

st.markdown('</div>', unsafe_allow_html=True)

# Q&A simple deterministic questions
st.markdown("---")
st.subheader("Ask a question about this application")
st.text_input("Question", key="qa_question")
if st.button("Ask"):
    q = st.session_state.get("qa_question", "").strip().lower()
    if not q:
        st.warning("Enter a question.")
    else:
        if not parsed:
            st.error("No parsed data available. Run Analyse first.")
        else:
            ans = None
            if "why" in q and ("flag" in q or "risk" in q):
                ans = "Reasons: " + "; ".join(lm.get("risk_reasons", []))
            elif "bridge" in q:
                dscr_io = lm.get("dscr_interest_only")
                ans = f"Interest-only DSCR: {dscr_io:.2f}" if dscr_io is not None else "Interest-only DSCR: N/A"
            else:
                ans = "No LLM configured — deterministic answers only. Configure LLM for natural language responses."
            st.session_state["qa_answer"] = ans

if st.session_state.get("qa_answer"):
    st.markdown("**Answer:**")
    st.write(st.session_state.get("qa_answer"))
