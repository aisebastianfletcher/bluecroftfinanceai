# Polished Bluecroft Finance UI with robust session-state handling, safe lazy imports,
# background CSS loader, professional report generation (including pie chart),
# and persistent Q&A that uses the last analysis as context.
import os
import sys
from pathlib import Path
import glob
import math
import json
import io
import typing

# Ensure repo root is on sys.path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import streamlit as st
# load custom styles (app/static/styles.css) safely AFTER streamlit is available
from pathlib import Path
_css_path = Path(__file__).parent / "static" / "styles.css"
if _css_path.exists():
    try:
        _css_text = _css_path.read_text(encoding="utf-8")
        st.markdown(f"<style>{_css_text}</style>", unsafe_allow_html=True)
    except Exception:
        pass
# optional: minimal inline fallback so header/background still looks okay even if file missing
else:
    st.markdown(
        "<style>"
        ".bf-header { background: linear-gradient(90deg,#003366,#0078D4); color:white; padding:12px 18px; border-radius:8px; }"
        ".stApp { background: linear-gradient(180deg,#eaf2ff,#ffffff); }"
        "</style>",
        unsafe_allow_html=True,
    )
import pandas as pd
import altair as alt

# Load optional CSS (keeps UI safe if file missing)
_css_path = Path(__file__).parent / "static" / "styles.css"
if _css_path.exists():
    try:
        _css_text = _css_path.read_text(encoding="utf-8")
        st.markdown(f"<style>{_css_text}</style>", unsafe_allow_html=True)
    except Exception:
        # silently ignore CSS errors so UI still loads
        pass
else:
    # Inline minimal fallback styling so title and header always look OK even if CSS missing
    st.markdown(
        """
        <style>
        .bf-header { background: linear-gradient(90deg,#003366,#0078D4); color: white; padding:12px 18px; border-radius:8px; }
        .bf-card { background: rgba(255,255,255,0.98); padding:16px; border-radius:10px; box-shadow: 0 6px 18px rgba(10,30,60,0.06); }
        </style>
        """,
        unsafe_allow_html=True,
    )

st.set_page_config(page_title="Bluecroft Finance — AI Lending Assistant", layout="wide")

# Lazy loaders to avoid import-time crashes if pipeline/llm have issues
def load_pipeline() -> typing.Tuple[typing.Optional[typing.Callable], typing.Optional[typing.Callable]]:
    try:
        from pipeline.pipeline import process_pdf, process_data  # type: ignore
        return process_pdf, process_data
    except Exception as e:
        print("PIPELINE IMPORT ERROR:", e)
        return None, None

def load_summarizer() -> typing.Tuple[typing.Callable, typing.Callable]:
    """
    Returns (generate_summary(parsed), answer_question(parsed, question)).
    If the real summarizer can't be imported, return deterministic fallbacks.
    """
    try:
        from pipeline.llm.summarizer import generate_summary, answer_question  # type: ignore
        return generate_summary, answer_question
    except Exception as e:
        print("SUMMARIZER IMPORT ERROR:", e)
        def fallback_summary(parsed: dict) -> str:
            borrower = parsed.get("borrower", "Unknown")
            income = parsed.get("income", "N/A")
            loan = parsed.get("loan_amount", "N/A")
            ltv = parsed.get("ltv", "N/A")
            flags = parsed.get("policy_flags", [])
            return (
                f"Borrower: {borrower}\n"
                f"Income: £{income:,}\n"
                f"Loan amount: £{loan:,}\n"
                f"LTV: {ltv}\n"
                f"Policy flags: {', '.join(flags) if flags else 'None'}\n\n"
                "Recommendation: Manual review recommended for elevated LTV or weak affordability."
            )
        def fallback_answer(parsed: dict, question: str) -> str:
            q = question.lower()
            if "ltv" in q:
                return f"LTV: {parsed.get('ltv', 'N/A')}"
            if "income" in q:
                return f"Income: £{parsed.get('income', 'N/A')}"
            if "monthly" in q or "payment" in q:
                return f"Monthly payment: £{parsed.get('monthly_payment', 'N/A')}"
            return "No LLM available. Please configure OPENAI_API_KEY to enable richer answers."
        return fallback_summary, fallback_answer

# Ensure output dirs exist
os.makedirs(os.path.join(ROOT, "output", "generated_pdfs"), exist_ok=True)
os.makedirs(os.path.join(ROOT, "output", "extracted_json"), exist_ok=True)

# Header
st.markdown(
    """
    <div class="bf-header">
      <div style="display:flex; align-items:center; gap:16px;">
        <div style="font-size:28px; font-weight:800; letter-spacing:1px; color: #fff;">
          Bluecroft Finance
        </div>
        <div style="flex:1;">
          <p style="margin:0; color: #eaf6ff;">AI Lending Assistant — professional underwriting report & quick calculator</p>
        </div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Ensure session state keys
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

# Layout
left_col, right_col = st.columns([3, 2])

with left_col:
    st.markdown('<div class="bf-card">', unsafe_allow_html=True)
    tab_form, tab_upload, tab_calc = st.tabs(["Fill Form (generate PDF)", "Upload PDF", "Quick Calculator"])

    # Form tab
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

    # Upload tab
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

    # Calculator tab
    with tab_calc:
        st.markdown("Quick loan calculator — compute monthly payment and summary. You can analyse this calculation directly.")
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

    # ANALYSE action
    if st.button("Analyse With AI"):
        # Load summariser lazily
        generate_summary, answer_question = load_summarizer()

        # If calculator selected, prepare parsed dict and bypass PDF pipeline
        if tmp_parsed:
            parsed = {
                "borrower": tmp_parsed.get("borrower"),
                "income": tmp_parsed.get("income"),
                "loan_amount": tmp_parsed.get("loan_amount"),
                "property_value": tmp_parsed.get("property_value"),
                "ltv": tmp_parsed.get("ltv"),
                "monthly_payment": tmp_parsed.get("monthly_payment"),
                "bank_red_flags": [],
                "risk_score": None,
                "policy_flags": [],
            }
            # persist last analysis for Q&A
            st.session_state["last_analysis"] = parsed
            # produce summary (LLM or fallback)
            try:
                summary_text = generate_summary(parsed)
            except Exception as e:
                summary_text = f"LLM_ERROR: {e}"
            # show report
            st.subheader("Underwriter Summary (calculation)")
            st.write(summary_text)

            # Produce a professional metrics report and pie chart
            st.subheader("Calculation Report")
            metrics = {
                "Monthly payment": parsed.get("monthly_payment") or 0,
                "Total interest": parsed.get("total_interest") or 0,
                "LTV (fraction)": parsed.get("ltv") or 0,
            }
            # Build a pie-like chart for decision factors
            aff_score = 0.0
            ltv_score = 0.0
            flags_score = 0.0
            # Affordability heuristic: monthly / (income/12)
            try:
                income_m = (parsed.get("income") or 0) / 12.0
                monthly = parsed.get("monthly_payment") or 0
                if income_m > 0:
                    aff_ratio = monthly / income_m
                    # higher ratio -> worse affordability
                    aff_score = min(max((aff_ratio - 0.2) * 5.0, 0.0), 1.0)  # scaled 0-1
                else:
                    aff_score = 1.0
            except Exception:
                aff_score = 0.0
            # LTV heuristic
            try:
                ltv_val = parsed.get("ltv") or 0
                if ltv_val >= 0.9:
                    ltv_score = 1.0
                else:
                    ltv_score = max(0.0, (ltv_val - 0.6) / 0.4)  # maps 0.6->0, 1.0->1.0
            except Exception:
                ltv_score = 0.0
            # flags
            flags_score = 1.0 if parsed.get("policy_flags") else 0.0
            # normalize to percentages for display
            total = aff_score + ltv_score + flags_score
            if total <= 0:
                # default neutral weights
                data = pd.DataFrame({
                    "factor": ["Affordability", "LTV risk", "Policy flags"],
                    "value": [1, 1, 1],
                })
            else:
                data = pd.DataFrame({
                    "factor": ["Affordability", "LTV risk", "Policy flags"],
                    "value": [aff_score / total * 100, ltv_score / total * 100, flags_score / total * 100],
                })
            chart = alt.Chart(data).mark_arc(innerRadius=40).encode(
                theta=alt.Theta("value:Q"),
                color=alt.Color("factor:N", scale=alt.Scale(range=["#1f77b4", "#ff7f0e", "#2ca02c"])),
                tooltip=["factor", "value"]
            ).properties(width=300, height=300)
            st.altair_chart(chart, use_container_width=True)

            # Key metrics table
            st.table(pd.DataFrame({
                "Metric": ["Income (annual)", "Loan amount", "Monthly payment", "LTV"],
                "Value": [
                    f"£{parsed.get('income', 0):,.2f}",
                    f"£{parsed.get('loan_amount', 0):,.2f}",
                    f"£{parsed.get('monthly_payment', 0):,.2f}",
                    f"{parsed.get('ltv', 'N/A')}",
                ]
            }))

            # Download report as JSON
            buf = io.BytesIO()
            buf.write(json.dumps({"parsed": parsed, "summary": summary_text}, indent=2).encode("utf-8"))
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
                        # persist last_analysis for Q&A
                        st.session_state["last_analysis"] = result
                        st.subheader("Extracted / Analysis JSON")
                        st.json(result)
                        # Save extracted JSON to output
                        try:
                            from utils.file_utils import save_json  # type: ignore
                            save_json(result, os.path.join("output", "extracted_json", f"{os.path.basename(tmp_file)}.json"))
                        except Exception:
                            pass

                        # Professional summary (LLM or fallback)
                        generate_summary, _ = load_summarizer()
                        try:
                            summary_text = generate_summary(result)
                        except Exception as e:
                            summary_text = f"LLM_ERROR: {e}"

                        st.subheader("Underwriter Summary")
                        st.write(summary_text)

                        # Prepare decision factors and chart (similar heuristics)
                        st.subheader("Decision Factors")
                        # derive numeric metrics if available
                        monthly_payment = result.get("monthly_payment") or result.get("monthly") or 0
                        income = result.get("income") or 0
                        ltv = result.get("ltv") or 0
                        policy_flags = result.get("policy_flags") or []
                        bank_red_flags = result.get("bank_red_flags") or []

                        # Affordability heuristic
                        aff_score = 0.0
                        if income and monthly_payment:
                            income_m = income / 12.0
                            aff_ratio = monthly_payment / income_m if income_m > 0 else 1.0
                            aff_score = min(max((aff_ratio - 0.2) * 5.0, 0.0), 1.0)
                        # LTV heuristic
                        ltv_score = max(0.0, min((ltv - 0.6) / 0.4, 1.0)) if isinstance(ltv, (int, float)) else 0.0
                        flags_score = 1.0 if policy_flags or bank_red_flags else 0.0

                        total = aff_score + ltv_score + flags_score
                        if total <= 0:
                            data = pd.DataFrame({
                                "factor": ["Affordability", "LTV risk", "Flags"],
                                "value": [1, 1, 1],
                            })
                        else:
                            data = pd.DataFrame({
                                "factor": ["Affordability", "LTV risk", "Flags"],
                                "value": [aff_score / total * 100, ltv_score / total * 100, flags_score / total * 100],
                            })
                        chart = alt.Chart(data).mark_arc(innerRadius=40).encode(
                            theta=alt.Theta("value:Q"),
                            color=alt.Color("factor:N", scale=alt.Scale(range=["#1f77b4", "#ff7f0e", "#d62728"])),
                            tooltip=["factor", "value"]
                        ).properties(width=300, height=300)
                        st.altair_chart(chart, use_container_width=True)

                        # Key metrics table
                        st.table(pd.DataFrame({
                            "Metric": ["Income (annual)", "Loan amount", "Monthly payment", "LTV"],
                            "Value": [
                                f"£{income:,.2f}" if income else "N/A",
                                f"£{result.get('loan_amount', 0):,.2f}",
                                f"£{monthly_payment:,.2f}" if monthly_payment else "N/A",
                                f"{ltv}",
                            ]
                        }))

                    except Exception as e:
                        st.error("Pipeline failed during processing. See logs.")
                        print("PIPELINE RUN ERROR:", e)

        else:
            st.error("No PDF or calculation available to analyse.")

    # Persistent Q&A UI
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
                # Prefer pipeline Q&A if available
                proc_pdf, proc_data = load_pipeline()
                try:
                    if proc_data:
                        answer = proc_data(parsed, ask=question)
                    else:
                        _, answer_question = load_summarizer()
                        answer = answer_question(parsed, question)
                except Exception as e:
                    answer = f"LLM_ERROR: {e}"
                st.session_state["qa_answer"] = answer

    if st.session_state.get("qa_answer"):
        st.markdown("**Answer:**")
        st.write(st.session_state.get("qa_answer"))

    st.markdown('</div>', unsafe_allow_html=True)
