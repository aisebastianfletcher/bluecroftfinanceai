# Bluecroft Finance — app/main.py (updated)
# - Uses app.metrics.compute_lending_metrics
# - Shows detailed input_audit
# - If required inputs are missing (property value, interest rate, term, total cost),
#   displays a small "Supply missing inputs" form so the user can enter values and recompute
# - Keeps stacked single-column report layout and centered charts
import os
import sys
from pathlib import Path
import glob
import io
import json
import typing

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import streamlit as st
import pandas as pd
import altair as alt

# robust metrics helpers (make sure app/metrics.py exists as provided)
from app.metrics import compute_lending_metrics, amortization_schedule  # type: ignore

st.set_page_config(page_title="Bluecroft Finance — AI Lending Assistant", layout="wide")

# minimal styles
_css_path = Path(__file__).parent / "static" / "styles.css"
if _css_path.exists():
    try:
        st.markdown(f"<style>{_css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)
    except Exception:
        pass

st.markdown(
    """
    <style>
    .report-box { max-width:980px; margin-left:auto; margin-right:auto; background:rgba(255,255,255,0.98);
      padding:18px; border-radius:10px; box-shadow:0 8px 24px rgba(10,30,60,0.08); border:1px solid rgba(15,40,80,0.04);}
    </style>
    """,
    unsafe_allow_html=True,
)

# helper center
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

# session defaults
for k, v in [
    ("generated_pdf", None), ("uploaded_pdf", None), ("calc_result", None),
    ("last_analysis", None), ("qa_question", ""), ("qa_answer", None),
]:
    if k not in st.session_state:
        st.session_state[k] = v

# --- Inputs area (kept small for brevity) ---
st.title("Bluecroft Finance — AI Lending Assistant")

with st.expander("Quick calculator (helpful to generate sample)"):
    with st.form("calc_form"):
        borrower = st.text_input("Borrower name", "John Doe")
        income = st.number_input("Annual income (GBP)", value=85000, step=1000)
        loan_amount = st.number_input("Loan amount (GBP)", value=240000, step=1000)
        property_value = st.number_input("Property value (GBP)", value=330000, step=1000)
        interest_rate = st.number_input("Interest rate (annual %)", value=5.5, step=0.1)
        term_years = st.number_input("Term (years)", value=25, min_value=1, step=1)
        submit_calc = st.form_submit_button("Create calculation")
    if submit_calc:
        parsed = {
            "borrower": borrower,
            "income": income,
            "loan_amount": loan_amount,
            "property_value": property_value,
            "interest_rate_annual": interest_rate,  # percent or decimal accepted by metrics module
            "term_months": int(term_years) * 12,
        }
        st.session_state["calc_result"] = parsed
        st.success("Calculation saved — choose 'Use quick calculator result' below and click Analyse.")

# selection
st.markdown("## Selection")
options = []
if st.session_state.get("uploaded_pdf"):
    options.append("Uploaded PDF")
if st.session_state.get("generated_pdf"):
    options.append("Most recent generated PDF")
if st.session_state.get("calc_result"):
    options.append("Use quick calculator result")
options.append("Manual entry")
choice = st.selectbox("Choose source", options=options, index=0 if options else 0)

tmp_parsed = None
tmp_file = None
if choice == "Use quick calculator result":
    tmp_parsed = st.session_state.get("calc_result")
    st.write("Calculator result selected")
elif choice == "Manual entry":
    # let user type a minimal parsed dict
    with st.form("manual_parsed"):
        m_loan = st.text_input("Loan amount", "240000")
        m_prop = st.text_input("Property value", "330000")
        m_rate = st.text_input("Interest rate (annual % or decimal)", "5.5")
        m_term = st.text_input("Term (months)", "300")
        m_income = st.text_input("Annual income", "85000")
        sub_manual = st.form_submit_button("Use manual values")
    if sub_manual:
        def _to_num(s):
            try:
                return float(str(s).replace("£", "").replace(",", "").strip())
            except Exception:
                return None
        parsed = {
            "loan_amount": _to_num(m_loan),
            "property_value": _to_num(m_prop),
            "interest_rate_annual": _to_num(m_rate),
            "term_months": int(_to_num(m_term)) if _to_num(m_term) is not None else None,
            "income": _to_num(m_income),
        }
        tmp_parsed = parsed
        st.session_state["manual_parsed"] = parsed
        st.success("Manual values loaded — click Analyse With AI.")

# Analyse button
st.markdown("---")
if st.button("Analyse With AI"):
    # Build parsed depending on selection
    if tmp_parsed:
        parsed = tmp_parsed.copy()
    elif choice == "Use quick calculator result":
        parsed = st.session_state.get("calc_result") or {}
    else:
        # fallback: if a file is selected earlier (not implemented here), you'd process it
        parsed = {}
    # diagnostic: show raw
    st.markdown("### Raw parsed input (diagnostic)")
    st.write(parsed)

    # compute metrics (this attaches parsed['input_audit'] and parsed['lending_metrics'])
    metrics = compute_lending_metrics(parsed)

    # persist
    st.session_state["last_analysis"] = parsed

    # show audit
    audit = parsed.get("input_audit") or []
    if audit:
        st.warning("Input audit: " + "; ".join(audit))

    # If audit contains missing critical fields, show a small form to let user supply them and recompute
    missing_fields = set()
    for a in audit:
        low = a.lower()
        if "property" in low and ("missing" in low or "invalid" in low):
            missing_fields.add("property_value")
        if "interest rate" in low and ("missing" in low or "invalid" in low):
            missing_fields.add("interest_rate_annual")
        if "term" in low and ("not provided" in low or "invalid" in low or "not an integer" in low):
            missing_fields.add("term_months")
        if "project_cost" in low or "total_cost" in low:
            missing_fields.add("project_cost")
    if missing_fields:
        st.info("Some inputs are missing or invalid. Provide them below to recompute.")
        with st.form("supply_missing"):
            supplied = {}
            if "property_value" in missing_fields:
                supplied["property_value"] = st.number_input("Property value (GBP)", value=0.0, format="%.2f")
            if "interest_rate_annual" in missing_fields:
                supplied["interest_rate_annual"] = st.number_input("Interest rate (annual % or decimal)", value=0.0, format="%.4f")
            if "term_months" in missing_fields:
                supplied["term_months"] = st.number_input("Term (months)", value=0, min_value=0, step=1)
            if "project_cost" in missing_fields:
                supplied["project_cost"] = st.number_input("Total project cost (GBP)", value=0.0, format="%.2f")
            recompute = st.form_submit_button("Recompute metrics with supplied values")
        if recompute:
            # apply supplied into parsed, only where meaningful
            for k, v in supplied.items():
                if v is None:
                    continue
                # ignore zero placeholders
                if isinstance(v, (int, float)) and v == 0:
                    # treat as not supplied
                    continue
                parsed[k] = v
            # recompute
            metrics = compute_lending_metrics(parsed)
            st.session_state["last_analysis"] = parsed
            # show updated audit & metrics
            audit = parsed.get("input_audit") or []
            if audit:
                st.warning("Input audit: " + "; ".join(audit))
            st.subheader("Computed lending metrics (after user-supplied inputs)")
            st.json(parsed.get("lending_metrics"))
    else:
        # no missing fields
        st.subheader("Computed lending metrics")
        st.json(parsed.get("lending_metrics"))

    # show a friendly human-readable summary
    lm = parsed.get("lending_metrics") or {}
    st.markdown("### Summary")
    if lm.get("ltv") is not None:
        st.write(f"LTV: {lm.get('ltv')*100:.2f}%")
    else:
        st.write("LTV: N/A")
    if lm.get("monthly_amortising_payment") is not None:
        st.write(f"Monthly (amortising): £{lm.get('monthly_amortising_payment'):,}")
    if lm.get("monthly_interest_only_payment") is not None:
        st.write(f"Monthly (interest-only): £{lm.get('monthly_interest_only_payment'):,}")
    if lm.get("noi") is not None:
        st.write(f"NOI: £{lm.get('noi'):,} (estimated: {bool(lm.get('noi_estimated_from_income_proxy', False))})")
    st.write(f"Risk category: {lm.get('risk_category')} (score {lm.get('risk_score_computed')})")
    st.write("Reasons: " + "; ".join(lm.get("risk_reasons", [])))

    # small amortization chart if available
    if lm.get("amortization_preview_rows"):
        try:
            df_am = pd.DataFrame(lm["amortization_preview_rows"])
            base = alt.Chart(df_am).encode(x=alt.X("month:Q", title="Month"))
            balance_line = base.mark_line(color="#1f77b4").encode(y=alt.Y("balance:Q", title="Balance"))
            center_chart((balance_line), height=260)
        except Exception:
            pass

# Q&A area (persistent)
st.markdown("---")
st.subheader("Ask a question about this application")
st.text_input("Question", key="qa_question")
if st.button("Ask question"):
    q = st.session_state.get("qa_question", "").strip()
    if not q:
        st.warning("Please enter a question.")
    else:
        parsed = st.session_state.get("last_analysis")
        if not parsed:
            st.error("No analysis available. Run Analyse first.")
        else:
            lm = parsed.get("lending_metrics") or compute_lending_metrics(parsed)
            # simple deterministic answers for common queries
            qq = q.lower()
            if ("why" in qq and ("flag" in qq or "risk" in qq)):
                ans = "Reasons: " + "; ".join(lm.get("risk_reasons", []))
            elif "summar" in qq or "financial position" in qq:
                ans = f"Borrower: {parsed.get('borrower','Unknown')}. LTV: {lm.get('ltv')*100:.1f}% if available. NOI: £{lm.get('noi'):,}."
            elif "bridge" in qq:
                dscr_io = lm.get("dscr_interest_only")
                ans = "Interest-only DSCR: " + (f"{dscr_io:.2f}" if dscr_io is not None else "N/A")
            else:
                ans = "No LLM configured — deterministic answers only. Provide more context or configure LLM."
            st.session_state["qa_answer"] = ans

if st.session_state.get("qa_answer"):
    st.markdown("**Answer:**")
    st.write(st.session_state.get("qa_answer"))
