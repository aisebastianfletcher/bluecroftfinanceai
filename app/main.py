# Bluecroft Finance — Complete app/main.py wired to robust metrics module
# - Uses app.metrics.compute_lending_metrics for all computed metrics
# - Displays parsed input audit to explain missing/suspicious inputs
# - Stacked, single-column report layout to avoid layout float issues
# - Shows both amortising and interest-only bridging payments and DSCRs
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

# Import our robust metrics helpers
from app.metrics import compute_lending_metrics, amortization_schedule  # type: ignore

st.set_page_config(page_title="Bluecroft Finance — AI Lending Assistant", layout="wide")

# Load optional CSS safely
_css_path = Path(__file__).parent / "static" / "styles.css"
if _css_path.exists():
    try:
        st.markdown(f"<style>{_css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)
    except Exception:
        pass

# Report box and chart niceties
st.markdown(
    """
    <style>
    .report-box {
      max-width: 980px;
      margin-left: auto;
      margin-right: auto;
      background: rgba(255,255,255,0.98);
      padding: 18px;
      border-radius: 10px;
      box-shadow: 0 8px 24px rgba(10,30,60,0.08);
      border: 1px solid rgba(15,40,80,0.04);
    }
    .stAltairChart, .stVegaLiteChart, .vega-embed { display:block !important; margin-left: auto !important; margin-right: auto !important; width: 100% !important; }
    [data-testid="stAltairChart"], [data-testid="stChart"], [data-testid="stVegaLiteChart"] { float:none !important; clear:both !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

# Lazy imports for pipeline and summariser (non-blocking)
def load_pipeline() -> typing.Tuple[typing.Optional[typing.Callable], typing.Optional[typing.Callable]]:
    try:
        from pipeline.pipeline import process_pdf, process_data  # type: ignore
        return process_pdf, process_data
    except Exception as e:
        print("PIPELINE IMPORT ERROR:", e)
        return None, None

def load_summarizer() -> typing.Tuple[typing.Callable, typing.Callable]:
    try:
        from pipeline.llm.summarizer import generate_summary, answer_question  # type: ignore
        return generate_summary, answer_question
    except Exception as e:
        print("SUMMARIZER IMPORT ERROR:", e)
        def fallback_summary(parsed: dict) -> str:
            lm = parsed.get("lending_metrics", {}) or {}
            return f"Borrower: {parsed.get('borrower','Unknown')}. LTV: {lm.get('ltv','N/A')}, Risk: {lm.get('risk_category','N/A')}"
        def fallback_answer(parsed: dict, question: str) -> str:
            return "LLM not available. Please set OPENAI_API_KEY for richer answers."
        return fallback_summary, fallback_answer

# Helper: center charts in a column middle
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

# Header
st.markdown(
    """
    <div style="margin-bottom:12px;">
      <div style="display:flex; align-items:center; gap:16px;">
        <div style="font-size:24px; font-weight:800; color:#003366;">Bluecroft Finance</div>
        <div style="flex:1; color:#234;">AI Lending Assistant — stacked underwriting report</div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Session defaults
for k, v in [
    ("generated_pdf", None),
    ("uploaded_pdf", None),
    ("calc_result", None),
    ("last_analysis", None),
    ("qa_question", ""),
    ("qa_answer", None),
]:
    if k not in st.session_state:
        st.session_state[k] = v

# ---- Inputs (stacked) ----
st.markdown("## Inputs & Actions")

with st.expander("Fill form (generate PDF)"):
    with st.form("application_form"):
        c1, c2 = st.columns(2)
        with c1:
            borrower_name = st.text_input("Borrower name", "John Doe")
            email = st.text_input("Email", "")
            income = st.number_input("Annual income (GBP)", value=85000, step=1000)
            loan_amount = st.number_input("Requested loan amount (GBP)", value=240000, step=1000)
        with c2:
            property_value = st.number_input("Property value (GBP)", value=330000, step=1000)
            term_months = st.number_input("Loan term (months)", value=300, min_value=1, step=1)
            interest_rate = st.number_input("Interest rate (annual %)", value=5.5, step=0.1)
            repayment_type = st.selectbox("Repayment type", ["Amortising", "Interest-only (bridging)"])
            notes = st.text_area("Notes / comments", "")
        submit_generate = st.form_submit_button("Generate PDF")
    if submit_generate:
        try:
            from app.pdf_form import create_pdf_from_dict  # type: ignore
            data = {
                "borrower": borrower_name,
                "email": email,
                "income": float(income),
                "loan_amount": float(loan_amount),
                "property_value": float(property_value),
                "term_months": int(term_months),
                "interest_rate_annual": float(interest_rate),
                "repayment_type": repayment_type,
                "notes": notes,
            }
            generated_path = create_pdf_from_dict(data)
            st.session_state["generated_pdf"] = generated_path
            st.success(f"PDF generated: {generated_path}")
            with open(generated_path, "rb") as f:
                st.download_button("Download generated PDF", data=f.read(), file_name=os.path.basename(generated_path), mime="application/pdf")
        except Exception as e:
            st.error("Failed to generate PDF. See logs.")
            print("PDF GENERATION ERROR:", e)

with st.expander("Upload PDF for analysis"):
    uploaded = st.file_uploader("Upload application / statement PDF", type=["pdf"], accept_multiple_files=False, key="upload1")
    if uploaded:
        try:
            from app.upload_handler import save_uploaded_file  # type: ignore
            uploaded_path = save_uploaded_file(uploaded)
            st.session_state["uploaded_pdf"] = uploaded_path
            st.success(f"Saved uploaded file to {uploaded_path}")
            with open(uploaded_path, "rb") as f:
                st.download_button("Download uploaded PDF", data=f.read(), file_name=os.path.basename(uploaded_path), mime="application/pdf")
        except Exception as e:
            st.error("Failed to save uploaded file. See logs.")
            print("UPLOAD SAVE ERROR:", e)

with st.expander("Quick Calculator"):
    with st.form("calc_form"):
        cc1, cc2 = st.columns(2)
        with cc1:
            calc_borrower = st.text_input("Borrower name", "John Doe", key="calc_borrower")
            calc_income = st.number_input("Annual income (GBP)", value=85000, step=1000, key="calc_income")
            calc_loan = st.number_input("Loan amount (GBP)", value=240000, step=1000, key="calc_loan")
        with cc2:
            calc_property = st.number_input("Property value (GBP)", value=330000, step=1000, key="calc_property")
            calc_rate = st.number_input("Interest rate (annual %)", value=5.5, step=0.1, key="calc_rate")
            calc_term_years = st.number_input("Term (years)", value=25, min_value=1, step=1, key="calc_term")
            calc_repayment = st.selectbox("Repayment type", ["Amortising", "Interest-only (bridging)"], key="calc_repayment")
        calc_submit = st.form_submit_button("Calculate")
    if calc_submit:
        try:
            P = float(calc_loan)
            annual_r = float(calc_rate) / 100.0
            n = int(calc_term_years) * 12
            monthly_amort = None
            monthly_io = None
            total_payment = None
            total_interest = None
            if annual_r == 0:
                monthly_amort = P / n
            else:
                r = annual_r / 12.0
                monthly_amort = P * r / (1 - (1 + r) ** (-n))
            monthly_io = P * (annual_r) / 12.0 if annual_r is not None else None
            total_payment = monthly_amort * n if monthly_amort is not None else None
            total_interest = total_payment - P if total_payment is not None else None
            ltv = None
            if calc_property and calc_property > 0:
                ltv = P / float(calc_property)
            st.session_state["calc_result"] = {
                "borrower": calc_borrower,
                "income": float(calc_income),
                "loan_amount": float(calc_loan),
                "property_value": float(calc_property),
                "monthly_amortising_payment": round(monthly_amort, 2) if monthly_amort is not None else None,
                "monthly_interest_only_payment": round(monthly_io, 2) if monthly_io is not None else None,
                "total_payment": round(total_payment, 2) if total_payment is not None else None,
                "total_interest": round(total_interest, 2) if total_interest is not None else None,
                "ltv": round(ltv, 4) if ltv is not None else None,
                "term_months": n,
                "interest_rate_annual": annual_r,
                "repayment_type": calc_repayment,
            }
            st.success("Calculation done — choose it below to analyse.")
        except Exception as e:
            st.error("Calculation failed; see logs.")
            print("CALC ERROR:", e)

# ----------------- Selection -----------------
st.markdown("## Selection")
out_dir = os.path.join(ROOT, "output", "generated_pdfs")
os.makedirs(out_dir, exist_ok=True)
gen_list = sorted(glob.glob(os.path.join(out_dir, "*.pdf")), key=os.path.getmtime, reverse=True)
gen_list = [os.path.basename(p) for p in gen_list]

options = []
if st.session_state.get("uploaded_pdf"):
    options.append("Uploaded PDF")
if st.session_state.get("generated_pdf"):
    options.append("Most recent generated PDF")
if gen_list:
    options.append("Choose from generated files")
options.append("Use quick calculator result")

choice = st.selectbox("Choose source to inspect / analyse", options=options, index=0 if options else -1)

tmp_file = None
tmp_parsed = None
if choice == "Uploaded PDF":
    tmp_file = st.session_state.get("uploaded_pdf")
    st.markdown(f"**Uploaded PDF:** {os.path.basename(tmp_file) if tmp_file else '—'}")
elif choice == "Most recent generated PDF":
    tmp_file = st.session_state.get("generated_pdf")
    st.markdown(f"**Generated PDF:** {os.path.basename(tmp_file) if tmp_file else '—'}")
elif choice == "Choose from generated files":
    sel = st.selectbox("Select generated file", options=gen_list, index=0)
    tmp_file = os.path.join("output", "generated_pdfs", sel)
    st.markdown(f"**Generated PDF:** {sel}")
elif choice == "Use quick calculator result":
    tmp_parsed = st.session_state.get("calc_result")
    if tmp_parsed:
        st.markdown("**Calculator result selected**")
        st.write(tmp_parsed)
    else:
        st.info("No quick calculation present. Use the Quick Calculator tab to create one.")

if tmp_file:
    try:
        with open(tmp_file, "rb") as f:
            st.download_button("Download selected PDF", data=f.read(), file_name=os.path.basename(tmp_file), mime="application/pdf")
    except Exception:
        st.warning("Could not open the selected file for preview/download.")

st.markdown("**Automatically derived lending metrics help underwriters make fast decisions.**")

# ----------------- ANALYSE & REPORT (stacked) -----------------
if st.button("Analyse With AI"):
    generate_summary, answer_question = load_summarizer()
    proc_pdf, proc_data = load_pipeline()

    # Choose parsed source (calculator vs extracted PDF)
    if tmp_parsed:
        parsed = tmp_parsed.copy()
        # ensure standard keys are present
        if "loan_amount" not in parsed and parsed.get("loan") is not None:
            parsed["loan_amount"] = parsed.get("loan")
    elif tmp_file:
        if proc_pdf is None:
            st.error("Pipeline not available. Check logs.")
            parsed = {}
        else:
            parsed = proc_pdf(tmp_file) or {}
    else:
        st.error("No source selected to analyse.")
        parsed = {}

    # Diagnostic: show raw parsed input to help debug bad parsing
    st.markdown("### Raw parsed input (diagnostic)")
    st.write(parsed)

    # Safe normalisation of common problematic fields (commas, currency symbols, strings)
    def _norm_quiet(v):
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return v
        s = str(v).strip()
        if s == "":
            return None
        s = s.replace(",", "").replace("£", "").replace("$", "")
        try:
            return float(s)
        except Exception:
            return s

    if parsed.get("loan_amount") is None and parsed.get("loan") is not None:
        parsed["loan_amount"] = _norm_quiet(parsed.get("loan"))
    parsed["loan_amount"] = _norm_quiet(parsed.get("loan_amount"))
    parsed["property_value"] = _norm_quiet(parsed.get("property_value") or parsed.get("property_value_estimate") or parsed.get("property"))
    # interest rate: allow percent like 5.5 or decimal 0.055
    rate_raw = parsed.get("interest_rate_annual") or parsed.get("interest_rate") or parsed.get("rate")
    parsed["interest_rate_annual"] = _norm_quiet(rate_raw)
    term_raw = parsed.get("term_months") or parsed.get("term")
    if term_raw is not None:
        try:
            parsed["term_months"] = int(term_raw)
        except Exception:
            parsed["term_months"] = None
    parsed["income"] = _norm_quiet(parsed.get("income") or parsed.get("annual_income"))

    # Diagnostic after normalisation
    st.markdown("### Normalised parsed input (diagnostic)")
    st.write(parsed)

    # Compute lending metrics (robust)
    try:
        metrics = compute_lending_metrics(parsed)
    except Exception as e:
        st.error("Metrics computation failed; see server logs.")
        print("METRICS ERROR:", e)
        metrics = parsed.get("lending_metrics", {})

    # Persist last analysis
    st.session_state["last_analysis"] = parsed

    # Show input audit if any
    audit = parsed.get("input_audit") or []
    if audit:
        st.warning("Input audit: " + "; ".join(audit))

    # Show computed metrics as JSON
    st.subheader("Computed lending metrics")
    st.json(parsed.get("lending_metrics"))

    # KPIs and Payment Scenarios table
    lm = parsed.get("lending_metrics") or {}
    st.markdown('<div class="report-box">', unsafe_allow_html=True)
    try:
        k1, k2, k3 = st.columns([1,1,1])
        with k1:
            if lm.get("ltv") is not None:
                st.metric("LTV", f"{lm.get('ltv')*100:.1f}%")
            else:
                st.metric("LTV", "N/A")
        with k2:
            st.metric("Monthly (Amortising)", f"£{lm.get('monthly_amortising_payment'):,}" if lm.get('monthly_amortising_payment') else "N/A")
        with k3:
            st.metric("Monthly (Interest-only)", f"£{lm.get('monthly_interest_only_payment'):,}" if lm.get('monthly_interest_only_payment') else "N/A")
    except Exception:
        pass

    st.markdown("### Payment scenarios")
    rows = [
        {
            "Scenario": "Amortising",
            "Monthly payment": f"£{lm.get('monthly_amortising_payment'):,}" if lm.get('monthly_amortising_payment') else "N/A",
            "Annual debt service": f"£{lm.get('annual_debt_service_amortising'):,}" if lm.get('annual_debt_service_amortising') else "N/A",
            "DSCR": lm.get('dscr_amortising') if lm.get('dscr_amortising') is not None else "N/A"
        },
        {
            "Scenario": "Interest-only (Bridging)",
            "Monthly payment": f"£{lm.get('monthly_interest_only_payment'):,}" if lm.get('monthly_interest_only_payment') else "N/A",
            "Annual debt service": f"£{lm.get('annual_debt_service_io'):,}" if lm.get('annual_debt_service_io') else "N/A",
            "DSCR": lm.get('dscr_interest_only') if lm.get('dscr_interest_only') is not None else "N/A"
        },
    ]
    st.table(pd.DataFrame(rows))

    # Amortization visuals if available; center in report box
    st.markdown("### Amortization & monthly breakdown")
    try:
        df_am = None
        amort_preview = lm.get("amortization_preview_rows")
        if amort_preview:
            df_am = pd.DataFrame(amort_preview)
            # try to build full schedule when possible
            if parsed.get("loan_amount") and parsed.get("interest_rate_annual") and parsed.get("term_months"):
                try:
                    rate_raw = parsed.get("interest_rate_annual")
                    rate = float(rate_raw) / 100.0 if float(rate_raw) > 1 else float(rate_raw)
                    df_am_full = amortization_schedule(parsed.get("loan_amount"), rate, int(parsed.get("term_months")))
                    df_am = df_am_full
                except Exception:
                    pass
        else:
            if parsed.get("loan_amount") and parsed.get("interest_rate_annual") and parsed.get("term_months"):
                try:
                    rate_raw = parsed.get("interest_rate_annual")
                    rate = float(rate_raw) / 100.0 if float(rate_raw) > 1 else float(rate_raw)
                    df_am = amortization_schedule(parsed.get("loan_amount"), rate, int(parsed.get("term_months")))
                except Exception:
                    df_am = None
            else:
                df_am = None

        if df_am is not None:
            base = alt.Chart(df_am).encode(x=alt.X("month:Q", title="Month"))
            balance_line = base.mark_line(color="#1f77b4", strokeWidth=2).encode(y=alt.Y("balance:Q", title="Remaining balance (£)"))
            balance_area = base.mark_area(opacity=0.12, color="#1f77b4").encode(y="balance:Q")
            center_chart((balance_area + balance_line), height=260)
            src = df_am.melt(id_vars=["month"], value_vars=["principal", "interest"], var_name="component", value_name="amount")
            center_chart(alt.Chart(src).mark_area().encode(x="month:Q", y=alt.Y("amount:Q", title="Amount (£)"), color=alt.Color("component:N")), height=200)
        else:
            st.info("Amortization schedule not available: provide loan, interest rate and term.")
    except Exception as e:
        st.warning("Could not render amortization visuals: " + str(e))

    # Payment composition, affordability and risk (stacked)
    st.markdown("### Payment composition")
    try:
        if 'df_am' in locals() and df_am is not None:
            pie_df = pd.DataFrame([{"part": "Principal", "value": df_am["principal"].sum()}, {"part": "Interest", "value": df_am["interest"].sum()}])
            center_chart(alt.Chart(pie_df).mark_arc(innerRadius=40).encode(theta=alt.Theta("value:Q"), color=alt.Color("part:N")), height=200)
        else:
            if lm.get("total_interest") is not None:
                st.write(f"Estimated total interest (amortising): £{lm.get('total_interest'):,}")
    except Exception:
        pass

    st.markdown("### Affordability")
    try:
        income_monthly = parsed.get("income", 0) / 12.0 if parsed.get("income") else 0
        payment_am = lm.get("monthly_amortising_payment") or 0
        payment_io = lm.get("monthly_interest_only_payment") or 0
        df_aff = pd.DataFrame([
            {"Label": "Monthly payment (amortising)", "Value": payment_am},
            {"Label": "Monthly payment (interest-only)", "Value": payment_io},
            {"Label": "Monthly income", "Value": income_monthly},
        ])
        center_chart(alt.Chart(df_aff).mark_bar().encode(x="Label:N", y=alt.Y("Value:Q", title="Amount (£)"), color=alt.Color("Label:N")), height=160)
        if income_monthly:
            st.write(f"Payment/Income (amortising) = {(payment_am / income_monthly):.2f}x")
            st.write(f"Payment/Income (interest-only) = {(payment_io / income_monthly):.2f}x")
    except Exception:
        pass

    st.markdown("### Risk & explainability")
    try:
        aff_score = max(min(1 - (lm.get("ltv") or 0), 1.0), 0.0) if lm.get("ltv") is not None else 0.33
        ltv_score = lm.get("ltv") or 0
        flag_score = 1.0 if lm.get("policy_flags") or lm.get("bank_red_flags") else 0.0
        total = (aff_score + ltv_score + flag_score) or 1.0
        df_r = pd.DataFrame({"factor": ["Affordability", "LTV risk", "Flags"], "value": [aff_score / total * 100, ltv_score / total * 100, flag_score / total * 100]})
        center_chart(alt.Chart(df_r).mark_arc(innerRadius=40).encode(theta=alt.Theta("value:Q"), color=alt.Color("factor:N")), height=160)
        st.write("Reasons:", "; ".join(lm.get("risk_reasons", [])))
    except Exception:
        pass

    # Optional richer reporting module (non-blocking)
    try:
        import app.reporting as reporting  # type: ignore
        try:
            reporting.render_full_report(parsed, lm)
        except Exception as e:
            print("REPORTING.render_full_report error:", e)
    except Exception:
        pass

    # Download JSON
    try:
        buf = io.BytesIO()
        payload = {"parsed": parsed, "lending_metrics": lm}
        buf.write(json.dumps(payload, indent=2).encode("utf-8"))
        buf.seek(0)
        st.download_button("Download report (JSON)", data=buf, file_name="underwriting_report.json", mime="application/json")
    except Exception:
        pass

    st.markdown('</div>', unsafe_allow_html=True)

# ----------------- Q&A -----------------
st.markdown("## Ask about this application")
st.text_input("Enter a natural language question", key="qa_question")
if st.button("Ask"):
    question = st.session_state.get("qa_question", "").strip()
    if not question:
        st.warning("Please enter a question.")
    else:
        parsed = st.session_state.get("last_analysis")
        if not parsed:
            st.error("No analysis available. Run 'Analyse With AI' first.")
        else:
            q = question.lower()
            lm = parsed.get("lending_metrics") or compute_lending_metrics(parsed)
            # Deterministic explanations for common queries
            if ("why" in q and ("flag" in q or "risk" in q)):
                st.session_state["qa_answer"] = "Reasons: " + "; ".join(lm.get("risk_reasons", []))
            elif ("summar" in q) or ("financial position" in q):
                gen, _ = load_summarizer()
                try:
                    st.session_state["qa_answer"] = gen(parsed)
                except Exception:
                    st.session_state["qa_answer"] = f"Borrower: {parsed.get('borrower','Unknown')}. Income: £{parsed.get('income','N/A')}. LTV: {lm.get('ltv','N/A')}."
            elif ("bridge" in q or "bridg" in q) and ("suit" in q or "suitable" in q):
                term_ok = parsed.get("term_months") is not None and parsed.get("term_months") <= 24
                ltv_ok = lm.get("ltv") is not None and lm.get("ltv") <= 0.75
                dscr_io_ok = lm.get("dscr_interest_only") is None or lm.get("dscr_interest_only") >= 1.0
                ok = term_ok and ltv_ok and dscr_io_ok
                reasons = []
                if not term_ok:
                    reasons.append(f"term months = {parsed.get('term_months')}")
                if not ltv_ok:
                    reasons.append(f"ltv = {lm.get('ltv')}")
                if not dscr_io_ok:
                    reasons.append(f"interest-only dscr = {lm.get('dscr_interest_only')}")
                st.session_state["qa_answer"] = "Suitable for typical bridging: " + ("Yes" if ok else "No") + ("" if ok else f". Issues: {', '.join(reasons)}")
            else:
                proc_pdf, proc_data = load_pipeline()
                if proc_data:
                    try:
                        st.session_state["qa_answer"] = proc_data(parsed, ask=question)
                    except Exception as e:
                        print("Q&A pipeline error:", e)
                        _, answer_q = load_summarizer()
                        try:
                            st.session_state["qa_answer"] = answer_q(parsed, question)
                        except Exception as e2:
                            st.session_state["qa_answer"] = f"LLM_ERROR: {e2}"
                else:
                    _, answer_q = load_summarizer()
                    try:
                        st.session_state["qa_answer"] = answer_q(parsed, question)
                    except Exception as e:
                        st.session_state["qa_answer"] = f"LLM_ERROR: {e}"

if st.session_state.get("qa_answer"):
    st.markdown("**Answer:**")
    st.write(st.session_state.get("qa_answer"))
