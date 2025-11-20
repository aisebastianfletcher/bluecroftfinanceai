# Polished Bluecroft Finance UI with safe lazy imports and CSS loader
import os
import sys
from pathlib import Path
import glob
import math

# Ensure repo root is on sys.path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Import Streamlit and then load optional CSS (safe: no warnings if missing)
import streamlit as st

# Load custom styles if present (no noisy warnings)
_css_path = Path(__file__).parent / "static" / "styles.css"
if _css_path.exists():
    try:
        _css_text = _css_path.read_text(encoding="utf-8")
        st.markdown(f"<style>{_css_text}</style>", unsafe_allow_html=True)
    except Exception:
        # Silently ignore CSS loading errors so UI still loads
        pass

st.set_page_config(page_title="Bluecroft Finance — AI Lending Assistant", layout="wide")

# Lazy loaders to avoid import-time crashes if pipeline/llm have issues
def load_pipeline():
    try:
        from pipeline.pipeline import process_pdf, process_data  # type: ignore
        return process_pdf, process_data
    except Exception as e:
        # Print to logs for debugging; return None so UI remains alive
        print("PIPELINE IMPORT ERROR:", e)
        return None, None

def load_summarizer():
    try:
        from pipeline.llm.summarizer import generate_summary, answer_question  # type: ignore
        return generate_summary, answer_question
    except Exception as e:
        print("SUMMARIZER IMPORT ERROR:", e)
        # provide simple fallback implementations
        def _fallback_summary(parsed):
            borrower = parsed.get("borrower", "Unknown")
            income = parsed.get("income", "N/A")
            loan = parsed.get("loan_amount", "N/A")
            ltv = parsed.get("ltv", "N/A")
            return (
                f"Summary (fallback): Borrower {borrower}. Income: {income}. "
                f"Loan: {loan}. LTV: {ltv}. (Set OPENAI_API_KEY to enable full summaries.)"
            )
        def _fallback_answer(parsed, q):
            ql = q.lower()
            if "ltv" in ql:
                return f"LTV: {parsed.get('ltv', 'N/A')}"
            if "income" in ql:
                return f"Income: {parsed.get('income', 'N/A')}"
            return "No LLM available. Please configure OPENAI_API_KEY."
        return _fallback_summary, _fallback_answer

# Prepare output dirs to avoid race errors when listing files
os.makedirs(os.path.join(ROOT, "output", "generated_pdfs"), exist_ok=True)
os.makedirs(os.path.join(ROOT, "output", "extracted_json"), exist_ok=True)

# Header + small inline styles (keeps using bf-header / bf-card classes from your CSS)
st.markdown(
    """
    <div class="bf-header" style="margin-bottom:16px;">
      <div style="display:flex; align-items:center; gap:16px;">
        <div style="font-size:28px; font-weight:800; letter-spacing:1px; color: #fff;">
          Bluecroft Finance
        </div>
        <div style="flex:1;">
          <p class="bf-sub" style="margin:0; color: #eaf6ff;">AI Lending Assistant — quick underwriting, PDF analysis and calculator</p>
        </div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Main layout: left for inputs/actions; right for selected item & analysis
left_col, right_col = st.columns([3, 2])

# Ensure session_state keys exist
if "generated_pdf" not in st.session_state:
    st.session_state["generated_pdf"] = None
if "uploaded_pdf" not in st.session_state:
    st.session_state["uploaded_pdf"] = None
if "calc_result" not in st.session_state:
    st.session_state["calc_result"] = None

with left_col:
    st.markdown('<div class="bf-card">', unsafe_allow_html=True)

    tab_form, tab_upload, tab_calc = st.tabs(["Fill Form (generate PDF)", "Upload PDF", "Quick Calculator"])

    # Form tab: generate PDF
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
                    st.download_button(
                        label="Download generated PDF",
                        data=pdf_bytes,
                        file_name=os.path.basename(generated_path),
                        mime="application/pdf",
                    )
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
                    st.download_button(
                        label="Download uploaded PDF",
                        data=up_bytes,
                        file_name=os.path.basename(uploaded_path),
                        mime="application/pdf",
                    )
                except Exception:
                    pass
            except Exception as e:
                st.error("Failed to save uploaded file. See logs.")
                print("UPLOAD SAVE ERROR:", e)

    # Quick calculator tab
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

    st.markdown('</div>', unsafe_allow_html=True)

# Right column: selection and analysis actions
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

    # Default selection index guard
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

    # Download / preview button if a file is selected
    if tmp_file:
        try:
            with open(tmp_file, "rb") as f:
                btn_bytes = f.read()
            st.download_button(label="Download selected PDF", data=btn_bytes, file_name=os.path.basename(tmp_file), mime="application/pdf")
        except Exception:
            st.warning("Could not open the selected file for preview/download.")

    # Analyse With AI button (always present)
    if st.button("Analyse With AI"):
        # If calculator result selected -> summarise that without using PDF pipeline
        if tmp_parsed:
            generate_summary, _ = load_summarizer()
            parsed = {
                "borrower": tmp_parsed.get("borrower"),
                "income": tmp_parsed.get("income"),
                "loan_amount": tmp_parsed.get("loan_amount"),
                "property_value": tmp_parsed.get("property_value"),
                "ltv": tmp_parsed.get("ltv"),
                "bank_red_flags": [],
                "risk_score": None,
                "policy_flags": [],
            }
            try:
                summary_text = generate_summary(parsed)
            except Exception as e:
                summary_text = f"LLM_ERROR: {e}"
            st.subheader("Underwriter Summary (calculation)")
            st.write(summary_text)
        elif tmp_file:
            proc_pdf, proc_data = load_pipeline()
            if proc_pdf is None:
                st.error("Pipeline not available. Check logs. (Pipeline import failed.)")
            else:
                with st.spinner("Running pipeline on PDF..."):
                    try:
                        result = proc_pdf(tmp_file)
                        st.subheader("Extracted / Analysis JSON")
                        st.json(result)
                        os.makedirs(os.path.join(ROOT, "output", "extracted_json"), exist_ok=True)
                        from utils.file_utils import save_json  # type: ignore
                        save_json(result, os.path.join("output", "extracted_json", f"{os.path.basename(tmp_file)}.json"))
                        st.subheader("Underwriter Summary")
                        st.write(result.get("summary", "No summary produced."))
                        # Q&A
                        question = st.text_input("Enter natural language question")
                        if st.button("Ask"):
                            proc_pdf2, proc_data2 = load_pipeline()
                            if proc_data2:
                                answer = proc_data2(result, ask=question)
                                st.write(answer)
                            else:
                                st.info("Q&A not available because pipeline import failed.")
                    except Exception as e:
                        st.error("Pipeline failed during processing. See logs.")
                        print("PIPELINE RUN ERROR:", e)
        else:
            st.error("No PDF or calculation available to analyse.")

    st.markdown('</div>', unsafe_allow_html=True)
    
