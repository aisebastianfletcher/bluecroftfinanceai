# Polished Bluecroft Finance UI (complete app/main.py)
# - Robust session-state handling
# - Safe lazy imports for pipeline/summariser/reporting
# - Quick calculator + PDF generate/upload flows
# - Automated lending metrics (LTV, LTC, DSCR, risk score/category)
# - Professional report rendering (calls app.reporting.render_full_report when available)
# - Persistent Q&A using last analysis as context
import os
import sys
from pathlib import Path
import glob
import math
import json
import io
import typing

# Ensure repo root is on sys.path so local packages import correctly
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import streamlit as st
import pandas as pd
import altair as alt

# Page config
st.set_page_config(page_title="Bluecroft Finance — AI Lending Assistant", layout="wide")

# Load optional CSS (safe: no error if missing)
_css_path = Path(__file__).parent / "static" / "styles.css"
if _css_path.exists():
    try:
        _css_text = _css_path.read_text(encoding="utf-8")
        st.markdown(f"<style>{_css_text}</style>", unsafe_allow_html=True)
    except Exception:
        pass
else:
    # Minimal inline fallback so header looks ok even if file missing
    st.markdown(
        """
        <style>
        .bf-header { background: linear-gradient(90deg,#003366,#0078D4); color: white; padding:12px 18px; border-radius:8px; }
        .bf-card { background: rgba(255,255,255,0.98); padding:16px; border-radius:10px; box-shadow: 0 6px 18px rgba(10,30,60,0.06); }
        </style>
        """,
        unsafe_allow_html=True,
    )

# ----------------- Lazy import helpers -----------------
def load_pipeline() -> typing.Tuple[typing.Optional[typing.Callable], typing.Optional[typing.Callable]]:
    """
    Lazy import of the processing pipeline so app startup remains resilient.
    Returns (process_pdf, process_data) or (None, None) if import fails.
    """
    try:
        from pipeline.pipeline import process_pdf, process_data  # type: ignore
        return process_pdf, process_data
    except Exception as e:
        print("PIPELINE IMPORT ERROR:", e)
        return None, None

def load_summarizer() -> typing.Tuple[typing.Callable, typing.Callable]:
    """
    Lazy import summarizer functions. Provide deterministic fallbacks when unavailable.
    Returns (generate_summary, answer_question).
    """
    try:
        from pipeline.llm.summarizer import generate_summary, answer_question  # type: ignore
        return generate_summary, answer_question
    except Exception as e:
        print("SUMMARIZER IMPORT ERROR:", e)
        # Deterministic fallback summary and simple QA
        def fallback_summary(parsed: dict) -> str:
            borrower = parsed.get("borrower", "Unknown")
            income = parsed.get("income", "N/A")
            loan = parsed.get("loan_amount", "N/A")
            lm = parsed.get("lending_metrics", {}) or {}
            ltv = lm.get("ltv", "N/A")
            risk_cat = lm.get("risk_category", "N/A")
            return (
                f"Borrower: {borrower}\n"
                f"Income: £{income:,}\n"
                f"Loan amount: £{loan:,}\n"
                f"LTV: {ltv}\n"
                f"Risk category: {risk_cat}\n\n"
                "Recommendation: Manual review recommended for elevated LTV or weak affordability."
            )
        def fallback_answer(parsed: dict, question: str) -> str:
            q = question.lower()
            lm = parsed.get("lending_metrics", {}) or {}
            if "why" in q and ("flag" in q or "risk" in q):
                return "Reasons: " + "; ".join(lm.get("risk_reasons", ["No automated reasons available."]))
            if "summar" in q or "financial position" in q:
                return fallback_summary(parsed)
            if "bridge" in q:
                term_ok = parsed.get("term_months") is not None and parsed.get("term_months") <= 24
                ltv_ok = lm.get("ltv") is not None and lm.get("ltv") <= 0.75
                dscr_ok = lm.get("dscr") is None or lm.get("dscr") >= 1.0
                ok = term_ok and ltv_ok and dscr_ok
                return "Suitable for typical bridging: " + ("Yes" if ok else "No")
            return "LLM not available. Please configure OPENAI_API_KEY for richer answers."
        return fallback_summary, fallback_answer

def load_reporting() -> typing.Optional[typing.Callable]:
    """
    Lazy import of reporting.render_full_report if available.
    """
    try:
        from app.reporting import render_full_report  # type: ignore
        return render_full_report
    except Exception as e:
        print("REPORTING IMPORT ERROR:", e)
        return None

# ----------------- Lending metrics computation -----------------
def compute_lending_metrics(parsed: dict) -> dict:
    """
    Compute LTV, LTC, DSCR, risk score and category and attach as parsed['lending_metrics'].
    Returns the lending metrics dict.
    """
    lm = {}
    loan = parsed.get("loan_amount") or parsed.get("loan") or 0.0
    prop = parsed.get("property_value") or parsed.get("property_value_estimate") or None
    total_cost = parsed.get("project_cost") or parsed.get("total_cost") or None

    # LTV
    try:
        if prop and prop > 0:
            ltv = float(loan) / float(prop)
        else:
            ltv = None
    except Exception:
        ltv = None
    lm["ltv"] = round(ltv, 4) if isinstance(ltv, (int, float)) else None

    # LTC
    try:
        if total_cost and total_cost > 0:
            ltc = float(loan) / float(total_cost)
        else:
            ltc = None
    except Exception:
        ltc = None
    lm["ltc"] = round(ltc, 4) if isinstance(ltc, (int, float)) else None

    # Monthly payment attempt (if not present)
    monthly_payment = parsed.get("monthly_payment")
    if not monthly_payment:
        rate = parsed.get("interest_rate_annual") or parsed.get("interest_rate") or None
        term_months = parsed.get("term_months") or parsed.get("term") or None
        try:
            if rate and term_months:
                # Accept percent-style (5.5) or decimal (0.055)
                r = float(rate)
                if r > 1:
                    r = r / 100.0
                n = int(term_months)
                if r == 0:
                    monthly_payment = float(loan) / n
                else:
                    monthly_payment = float(loan) * (r / 12.0) / (1 - (1 + r / 12.0) ** (-n))
            else:
                monthly_payment = None
        except Exception:
            monthly_payment = None
    lm["monthly_payment"] = round(monthly_payment, 2) if isinstance(monthly_payment, (int, float)) else None

    # Annual debt service
    if lm.get("monthly_payment"):
        annual_debt_service = lm["monthly_payment"] * 12.0
    else:
        annual_debt_service = None
    lm["annual_debt_service"] = round(annual_debt_service, 2) if annual_debt_service else None

    # NOI detection or proxy
    noi = parsed.get("noi") or parsed.get("net_operating_income")
    if not noi:
        annual_rent = parsed.get("annual_rent") or parsed.get("rental_income_annual")
        operating_expenses = parsed.get("operating_expenses") or parsed.get("annual_expenses")
        if annual_rent is not None:
            try:
                noi = float(annual_rent) - float(operating_expenses or 0)
                lm["noi_estimated_from_rent"] = True
            except Exception:
                noi = None
        else:
            borrower_income = parsed.get("income")
            if borrower_income:
                noi = borrower_income * 0.30
                lm["noi_estimated_from_income_proxy"] = True
            else:
                noi = None
    lm["noi"] = round(noi, 2) if isinstance(noi, (int, float)) else None

    # DSCR
    dscr = None
    try:
        if lm.get("noi") and annual_debt_service and annual_debt_service > 0:
            dscr = lm["noi"] / annual_debt_service
    except Exception:
        dscr = None
    lm["dscr"] = round(dscr, 3) if isinstance(dscr, (int, float)) else None

    # Flags
    policy_flags = parsed.get("policy_flags") or parsed.get("flags") or []
    bank_red_flags = parsed.get("bank_red_flags") or []
    lm["policy_flags"] = policy_flags
    lm["bank_red_flags"] = bank_red_flags

    # Risk scoring heuristics
    ltv_risk = 0.0
    if lm.get("ltv") is not None:
        ltv_val = lm["ltv"]
        ltv_risk = min(max((ltv_val - 0.5) / 0.5, 0.0), 1.0)

    dscr_risk = 1.0
    if lm.get("dscr") is not None:
        d = lm["dscr"]
        if d >= 1.5:
            dscr_risk = 0.0
        else:
            dscr_risk = min(max((1.5 - d) / 0.7, 0.0), 1.0)

    flags_risk = 1.0 if (policy_flags or bank_red_flags) else 0.0

    risk_score = 0.55 * ltv_risk + 0.35 * dscr_risk + 0.10 * flags_risk
    risk_score = min(max(risk_score, 0.0), 1.0)
    lm["risk_score_computed"] = round(risk_score, 3)

    if risk_score >= 0.7:
        category = "High"
    elif risk_score >= 0.4:
        category = "Medium"
    else:
        category = "Low"
    lm["risk_category"] = category

    # Explainable reasons
    reasons = []
    if lm.get("ltv") is not None and lm["ltv"] >= 0.85:
        reasons.append(f"High LTV ({lm['ltv']:.2f})")
    elif lm.get("ltv") is not None and lm["ltv"] >= 0.75:
        reasons.append(f"Elevated LTV ({lm['ltv']:.2f})")
    if lm.get("dscr") is not None and lm["dscr"] < 1.0:
        reasons.append(f"DSCR below 1.0 ({lm['dscr']:.2f})")
    if flags_risk:
        reasons.append("Policy / bank flags present")
    if not reasons:
        reasons.append("No major automated flags detected")
    lm["risk_reasons"] = reasons

    parsed["lending_metrics"] = lm
    return lm

# ----------------- Prepare output dirs -----------------
os.makedirs(os.path.join(ROOT, "output", "generated_pdfs"), exist_ok=True)
os.makedirs(os.path.join(ROOT, "output", "extracted_json"), exist_ok=True)

# ----------------- Header -----------------
st.markdown(
    """
    <div class="bf-header">
      <div style="display:flex; align-items:center; gap:16px;">
        <div style="font-size:28px; font-weight:800; letter-spacing:1px; color: #fff;">
          Bluecroft Finance
        </div>
        <div style="flex:1;">
          <p style="margin:0; color: #eaf6ff;">AI Lending Assistant — underwriting metrics, professional report & Q&A</p>
        </div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ----------------- Session state defaults -----------------
defaults = {
    "generated_pdf": None,
    "uploaded_pdf": None,
    "calc_result": None,
    "last_analysis": None,
    "qa_question": "",
    "qa_answer": None,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ----------------- Layout -----------------
left_col, right_col = st.columns([3, 2])

with left_col:
    st.markdown('<div class="bf-card">', unsafe_allow_html=True)
    tab_form, tab_upload, tab_calc = st.tabs(["Fill Form (generate PDF)", "Upload PDF", "Quick Calculator"])

    # --- FORM (generate PDF) ---
    with tab_form:
        st.markdown("Fill fields and click Generate PDF to create an application PDF.")
        with st.form("application_form"):
            col1, col2 = st.columns(2)
            with col1:
                borrower_name = st.text_input("Borrower name", "John Doe")
                email = st.text_input("Email", "")
                income = st.number_input("Annual income (GBP)", value=85000, step=1000)
                loan_amount = st.number_input("Requested loan amount (GBP)", value=240000, step=1000)
            with col2:
                property_value = st.number_input("Property value (GBP)", value=330000, step=1000)
                term_months = st.number_input("Loan term (months)", value=300, min_value=1, step=1)
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
                    "notes": notes,
                }
                generated_path = create_pdf_from_dict(data)
                st.session_state["generated_pdf"] = generated_path
                st.success(f"PDF generated: {generated_path}")
                try:
                    with open(generated_path, "rb") as f:
                        pdf_bytes = f.read()
                    st.download_button("Download generated PDF", data=pdf_bytes, file_name=os.path.basename(generated_path), mime="application/pdf")
                except Exception:
                    pass
            except Exception as e:
                st.error("Failed to generate PDF. See logs.")
                print("PDF GENERATION ERROR:", e)

    # --- UPLOAD ---
    with tab_upload:
        st.markdown("Upload an existing application or statement PDF for analysis.")
        uploaded = st.file_uploader("Upload application / statement PDF", type=["pdf"], accept_multiple_files=False, key="upload1")
        if uploaded:
            try:
                from app.upload_handler import save_uploaded_file  # type: ignore
                uploaded_path = save_uploaded_file(uploaded)
                st.session_state["uploaded_pdf"] = uploaded_path
                st.success(f"Saved uploaded file to {uploaded_path}")
                try:
                    with open(uploaded_path, "rb") as f:
                        up_bytes = f.read()
                    st.download_button("Download uploaded PDF", data=up_bytes, file_name=os.path.basename(uploaded_path), mime="application/pdf")
                except Exception:
                    pass
            except Exception as e:
                st.error("Failed to save uploaded file. See logs.")
                print("UPLOAD SAVE ERROR:", e)

    # --- QUICK CALCULATOR ---
    with tab_calc:
        st.markdown("Quick loan calculator — compute monthly payment and summary.")
        with st.form("calc_form"):
            ccol1, ccol2 = st.columns(2)
            with ccol1:
                calc_borrower = st.text_input("Borrower name", "John Doe", key="calc_borrower")
                calc_income = st.number_input("Annual income (GBP)", value=85000, step=1000, key="calc_income")
                calc_loan = st.number_input("Loan amount (GBP)", value=240000, step=1000, key="calc_loan")
            with ccol2:
                calc_property = st.number_input("Property value (GBP)", value=330000, step=1000, key="calc_property")
                calc_rate = st.number_input("Interest rate (annual %)", value=5.5, step=0.1, key="calc_rate")
                calc_term_years = st.number_input("Term (years)", value=25, min_value=1, step=1, key="calc_term")
            calc_submit = st.form_submit_button("Calculate")
        if calc_submit:
            try:
                P = float(calc_loan)
                annual_r = float(calc_rate) / 100.0
                n = int(calc_term_years) * 12
                if annual_r == 0:
                    monthly = P / n
                else:
                    r = annual_r / 12.0
                    monthly = P * r / (1 - (1 + r) ** (-n))
                total_payment = monthly * n
                total_interest = total_payment - P
                ltv = None
                if calc_property and calc_property > 0:
                    ltv = P / float(calc_property)
                st.session_state["calc_result"] = {
                    "borrower": calc_borrower,
                    "income": float(calc_income),
                    "loan_amount": float(calc_loan),
                    "property_value": float(calc_property),
                    "monthly_payment": round(monthly, 2),
                    "total_payment": round(total_payment, 2),
                    "total_interest": round(total_interest, 2),
                    "ltv": round(ltv, 4) if ltv is not None else None,
                    "term_months": n,
                    "interest_rate_annual": annual_r,
                }
                st.success("Calculation done — select it in the right pane to analyse.")
            except Exception as e:
                st.error("Calculation failed; see logs.")
                print("CALC ERROR:", e)

    st.markdown('</div>', unsafe_allow_html=True)

with right_col:
    st.markdown('<div class="bf-card">', unsafe_allow_html=True)
    st.subheader("Selected PDF / Calculation")

    # Helper to list generated PDFs
    def list_generated_pdfs():
        out_dir = os.path.join(ROOT, "output", "generated_pdfs")
        os.makedirs(out_dir, exist_ok=True)
        files = sorted(glob.glob(os.path.join(out_dir, "*.pdf")), key=os.path.getmtime, reverse=True)
        return [os.path.basename(f) for f in files]

    gen_list = list_generated_pdfs()
    options = []
    if st.session_state.get("uploaded_pdf"):
        options.append("Uploaded PDF")
    if st.session_state.get("generated_pdf"):
        options.append("Most recent generated PDF")
    if gen_list:
        options.append("Choose from generated files")
    options.append("Use quick calculator result")

    default_index = 0 if options else -1
    choice = st.selectbox("Choose source to inspect / analyse", options=options, index=default_index)

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

    # Download / preview if a file is selected
    if tmp_file:
        try:
            with open(tmp_file, "rb") as f:
                btn_bytes = f.read()
            st.download_button(label="Download selected PDF", data=btn_bytes, file_name=os.path.basename(tmp_file), mime="application/pdf")
        except Exception:
            st.warning("Could not open the selected file for preview/download.")

    st.markdown("**Automatically derived lending metrics help underwriters make fast decisions.**")

    # ANALYSE action
    if st.button("Analyse With AI"):
        generate_summary, answer_question = load_summarizer()
        render_full_report = load_reporting()

        if tmp_parsed:
            # analysis from calculator result
            parsed = {
                "borrower": tmp_parsed.get("borrower"),
                "income": tmp_parsed.get("income"),
                "loan_amount": tmp_parsed.get("loan_amount"),
                "property_value": tmp_parsed.get("property_value"),
                "monthly_payment": tmp_parsed.get("monthly_payment"),
                "total_interest": tmp_parsed.get("total_interest"),
                "term_months": tmp_parsed.get("term_months"),
                "interest_rate_annual": tmp_parsed.get("interest_rate_annual"),
            }
            metrics = compute_lending_metrics(parsed)
            st.session_state["last_analysis"] = parsed

            # Summary (LLM or fallback)
            try:
                summary_text = generate_summary(parsed)
            except Exception as e:
                summary_text = f"LLM_ERROR: {e}"
            st.subheader("Underwriter Summary (calculation)")
            st.write(summary_text)

            # Lending metrics table
            st.subheader("Lending Metrics")
            df_metrics = pd.DataFrame([
                {"Metric": "LTV", "Value": f"{metrics.get('ltv') if metrics.get('ltv') is not None else 'N/A'}"},
                {"Metric": "LTC", "Value": f"{metrics.get('ltc') if metrics.get('ltc') is not None else 'N/A'}"},
                {"Metric": "DSCR", "Value": f"{metrics.get('dscr') if metrics.get('dscr') is not None else 'N/A'}"},
                {"Metric": "Annual debt service", "Value": f"{metrics.get('annual_debt_service') if metrics.get('annual_debt_service') is not None else 'N/A'}"},
                {"Metric": "Risk score", "Value": f"{metrics.get('risk_score_computed', 'N/A')}"},
                {"Metric": "Risk category", "Value": f"{metrics.get('risk_category', 'N/A')}"},
            ])
            st.table(df_metrics)

            # Decision factors chart
            try:
                factors = pd.DataFrame({
                    "factor": ["Affordability", "LTV risk", "Flags"],
                    "value": [
                        max(min((1 - (metrics.get("ltv") or 0)), 1.0) * 100, 0) if metrics.get("ltv") is not None else 33,
                        (metrics.get("ltv") or 0) * 100 if metrics.get("ltv") is not None else 33,
                        30 if metrics.get("policy_flags") or metrics.get("bank_red_flags") else 1,
                    ]
                })
                chart = alt.Chart(factors).mark_arc(innerRadius=40).encode(
                    theta=alt.Theta("value:Q"),
                    color=alt.Color("factor:N", scale=alt.Scale(range=["#1f77b4", "#ff7f0e", "#d62728"])),
                    tooltip=["factor", "value"]
                ).properties(width=300, height=300)
                st.altair_chart(chart, use_container_width=True)
            except Exception:
                pass

            # Try to render full reporting visuals (amortization, KPIs) if reporting module is present
            if render_full_report:
                try:
                    render_full_report(parsed, metrics)
                except Exception as e:
                    print("REPORT RENDER ERROR:", e)

            # Download report JSON
            buf = io.BytesIO()
            payload = {"parsed": parsed, "lending_metrics": metrics, "summary": summary_text}
            buf.write(json.dumps(payload, indent=2).encode("utf-8"))
            buf.seek(0)
            st.download_button("Download report (JSON)", data=buf, file_name="calculation_report.json", mime="application/json")

        elif tmp_file:
            proc_pdf, proc_data = load_pipeline()
            if proc_pdf is None:
                st.error("Pipeline not available. Check logs.")
            else:
                with st.spinner("Running pipeline on PDF..."):
                    try:
                        result = proc_pdf(tmp_file)
                        # Compute lending metrics
                        metrics = compute_lending_metrics(result)
                        st.session_state["last_analysis"] = result

                        st.subheader("Extracted / Analysis JSON")
                        st.json(result)

                        # Save extracted JSON (best-effort)
                        try:
                            from utils.file_utils import save_json  # type: ignore
                            save_json(result, os.path.join("output", "extracted_json", f"{os.path.basename(tmp_file)}.json"))
                        except Exception:
                            pass

                        # Summary
                        try:
                            summary_text = generate_summary(result)
                        except Exception as e:
                            summary_text = f"LLM_ERROR: {e}"
                        st.subheader("Underwriter Summary")
                        st.write(summary_text)

                        # Lending metrics table
                        st.subheader("Lending Metrics")
                        df_metrics = pd.DataFrame([
                            {"Metric": "LTV", "Value": f"{metrics.get('ltv') if metrics.get('ltv') is not None else 'N/A'}"},
                            {"Metric": "LTC", "Value": f"{metrics.get('ltc') if metrics.get('ltc') is not None else 'N/A'}"},
                            {"Metric": "DSCR", "Value": f"{metrics.get('dscr') if metrics.get('dscr') is not None else 'N/A'}"},
                            {"Metric": "Annual debt service", "Value": f"{metrics.get('annual_debt_service') if metrics.get('annual_debt_service') is not None else 'N/A'}"},
                            {"Metric": "Risk score", "Value": f"{metrics.get('risk_score_computed', 'N/A')}"},
                            {"Metric": "Risk category", "Value": f"{metrics.get('risk_category', 'N/A')}"},
                        ])
                        st.table(df_metrics)

                        # Chart
                        try:
                            factors = pd.DataFrame({
                                "factor": ["Affordability", "LTV risk", "Flags"],
                                "value": [
                                    max(min((1 - (metrics.get("ltv") or 0)), 1.0) * 100, 0) if metrics.get("ltv") is not None else 33,
                                    (metrics.get("ltv") or 0) * 100 if metrics.get("ltv") is not None else 33,
                                    30 if metrics.get("policy_flags") or metrics.get("bank_red_flags") else 1,
                                ]
                            })
                            chart = alt.Chart(factors).mark_arc(innerRadius=40).encode(
                                theta=alt.Theta("value:Q"),
                                color=alt.Color("factor:N", scale=alt.Scale(range=["#1f77b4", "#ff7f0e", "#d62728"])),
                                tooltip=["factor", "value"]
                            ).properties(width=300, height=300)
                            st.altair_chart(chart, use_container_width=True)
                        except Exception:
                            pass

                        # Render full report visuals if available
                        if render_full_report:
                            try:
                                render_full_report(result, metrics)
                            except Exception as e:
                                print("REPORT RENDER ERROR:", e)
                    except Exception as e:
                        st.error("Pipeline failed during processing. See logs.")
                        print("PIPELINE RUN ERROR:", e)
        else:
            st.error("No PDF or calculation available to analyse.")

    # ---------- Persistent Q&A ----------
    st.markdown("---")
    st.subheader("Ask a question about this application")
    st.text_input("Enter natural language question", key="qa_question")

    if st.button("Ask"):
        question = st.session_state.get("qa_question", "").strip()
        if not question:
            st.warning("Please enter a question before clicking Ask.")
        else:
            parsed = st.session_state.get("last_analysis")
            if not parsed:
                st.error("No analysis available to ask about. Run 'Analyse With AI' first (or select a calculation).")
            else:
                # Deterministic responses for common stakeholder queries first
                qlow = question.lower()
                metrics = parsed.get("lending_metrics") or compute_lending_metrics(parsed)
                answer = None

                if ("why" in qlow and ("flag" in qlow or "risk" in qlow)):
                    reasons = metrics.get("risk_reasons", ["No specific reasons available."])
                    answer = "I flagged risk because: " + "; ".join(reasons)
                elif ("summar" in qlow) or ("financial position" in qlow):
                    generate_summary, _ = load_summarizer()
                    try:
                        answer = generate_summary(parsed)
                    except Exception:
                        answer = (
                            f"Borrower: {parsed.get('borrower','Unknown')}. "
                            f"Income: £{parsed.get('income','N/A')}. Loan: £{parsed.get('loan_amount','N/A')}. "
                            f"LTV: {metrics.get('ltv','N/A')}, DSCR: {metrics.get('dscr','N/A')}."
                        )
                elif ("suit" in qlow or "suitable" in qlow) and "bridge" in qlow:
                    term_ok = parsed.get("term_months") is not None and parsed.get("term_months") <= 24
                    ltv_ok = metrics.get("ltv") is not None and metrics.get("ltv") <= 0.75
                    dscr_ok = metrics.get("dscr") is None or metrics.get("dscr") >= 1.0
                    ok = term_ok and ltv_ok and dscr_ok
                    reasons = []
                    if not term_ok:
                        reasons.append(f"term months = {parsed.get('term_months')}")
                    if not ltv_ok:
                        reasons.append(f"ltv = {metrics.get('ltv')}")
                    if not dscr_ok:
                        reasons.append(f"dscr = {metrics.get('dscr')}")
                    answer = "Suitable for typical bridging: " + ("Yes" if ok else "No") + ("" if ok else f". Issues: {', '.join(reasons)}")
                else:
                    # fall back to pipeline Q&A or summarizer QA
                    proc_pdf, proc_data = load_pipeline()
                    if proc_data:
                        try:
                            answer = proc_data(parsed, ask=question)
                        except Exception as e:
                            print("Q&A pipeline error:", e)
                            _, answer_question = load_summarizer()
                            try:
                                answer = answer_question(parsed, question)
                            except Exception as e2:
                                answer = f"LLM_ERROR: {e2}"
                    else:
                        _, answer_question = load_summarizer()
                        try:
                            answer = answer_question(parsed, question)
                        except Exception as e:
                            answer = f"LLM_ERROR: {e}"
                st.session_state["qa_answer"] = answer

    if st.session_state.get("qa_answer"):
        st.markdown("**Answer:**")
        st.write(st.session_state.get("qa_answer"))

    st.markdown('</div>', unsafe_allow_html=True)
