# Ensure repo root is on sys.path so top-level modules (pipeline, utils) import correctly when running Streamlit
import os
import sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
# load custom styles (app/static/styles.css)
from pathlib import Path
_css_path = Path(__file__).parent / "static" / "styles.css"
try:
    _css_text = _css_path.read_text(encoding="utf-8")
    st.markdown(f"<style>{_css_text}</style>", unsafe_allow_html=True)
except Exception as _e:
    # if the file isn't present, fall back silently
    st.warning("Custom style not loaded (app/static/styles.css not found).")
import glob
import math
import streamlit as st
from pipeline.pipeline import process_pdf, process_data
from app.pdf_form import create_pdf_from_dict
from app.upload_handler import save_uploaded_file
from utils.file_utils import save_json

# Try to import summariser helpers for the calculator analysis (works even without an API key)
try:
    from pipeline.llm.summarizer import generate_summary, answer_question
except Exception:
    # graceful fallback if summariser not available for any reason
    def generate_summary(parsed):
        borrower = parsed.get("borrower", "Unknown")
        return f"Summary (fallback): Borrower {borrower}. Income {parsed.get('income')}, Loan {parsed.get('loan_amount')}."
    def answer_question(parsed, question):
        return "No LLM available. Please configure OPENAI_API_KEY."

st.set_page_config(page_title="Bluecroft Finance — AI Lending Assistant", layout="wide")

# ---- Styles: header, background, card ----
st.markdown(
    """
    <style>
    /* Background gradient */
    .stApp {
        background: linear-gradient(180deg, #eaf2ff 0%, #ffffff 60%);
    }
    /* Header/banner */
    .bf-header {
        background: linear-gradient(90deg, rgba(0,51,102,1) 0%, rgba(0,120,212,1) 100%);
        color: white;
        padding: 18px 24px;
        border-radius: 8px;
        margin-bottom: 18px;
        box-shadow: 0 6px 18px rgba(0,0,0,0.08);
    }
    .bf-title { font-size: 28px; font-weight: 700; margin: 0; }
    .bf-sub { font-size: 14px; margin: 0; opacity: 0.95; }
    /* Pane card look */
    .bf-card {
        background: rgba(255,255,255,0.95);
        border-radius: 12px;
        padding: 18px;
        box-shadow: 0 6px 18px rgba(10,30,60,0.06);
    }
    /* Small helper text */
    .bf-small { color: #234; font-size: 13px; }
    </style>
    """,
    unsafe_allow_html=True,
)

# Header
st.markdown(
    """
    <div class="bf-header">
      <div style="display:flex; align-items:center; gap:16px;">
        <div style="font-size:32px; font-weight:800; letter-spacing:1px;">
          <!-- Simple text-logo -->
          Bluecroft Finance
        </div>
        <div style="flex:1;">
          <p class="bf-sub">AI Lending Assistant — quick underwriting, PDF analysis and calculator</p>
        </div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Main UI layout: left column for actions, right column for outputs
left_col, right_col = st.columns([3, 2])

with left_col:
    st.markdown('<div class="bf-card">', unsafe_allow_html=True)

    # Tabs: Form, Upload, Calculator
    tab_form, tab_upload, tab_calc = st.tabs(["Fill Form (generate PDF)", "Upload PDF", "Quick Calculator"])

    # --- Form (generate PDF) ---
    with tab_form:
        st.markdown("Fill the fields below and click Generate PDF to create an application PDF.")
        with st.form("application_form"):
            col1, col2 = st.columns(2)
            with col1:
                borrower_name = st.text_input("Borrower name", "John Doe")
                email = st.text_input("Email", "")
                income = st.number_input("Annual income (GBP)", value=85000, step=1000)
                loan_amount = st.number_input("Requested loan amount (GBP)", value=240000, step=1000)
            with col2:
                property_value = st.number_input("Property value (GBP)", value=330000, step=1000)
                term_months = st.number_input("Loan term (months)", value=12)
                notes = st.text_area("Notes / comments", "")
            submit_generate = st.form_submit_button("Generate PDF")

        if submit_generate:
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
            # persist to session so selection persists across reruns
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
            except Exception as e:
                st.warning(f"Couldn't offer a download: {e}")

    # --- Upload ---
    with tab_upload:
        st.markdown("Upload an existing application or statement PDF for analysis.")
        uploaded = st.file_uploader("Upload application / statement PDF", type=["pdf"], accept_multiple_files=False, key="upload1")
        if uploaded:
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
            except Exception as e:
                st.warning(f"Couldn't offer a download: {e}")

    # --- Quick Calculator ---
    with tab_calc:
        st.markdown("Quick loan calculator — compute monthly payment and summary. You can analyse this calculation with AI (bypasses generating a PDF).")
        with st.form("calc_form"):
            ccol1, ccol2 = st.columns(2)
            with ccol1:
                calc_borrower = st.text_input("Borrower name", "John Doe")
                calc_income = st.number_input("Annual income (GBP)", value=85000, step=1000, key="calc_income")
                calc_loan = st.number_input("Loan amount (GBP)", value=240000, step=1000, key="calc_loan")
            with ccol2:
                calc_property = st.number_input("Property value (GBP)", value=330000, step=1000, key="calc_property")
                calc_rate = st.number_input("Interest rate (annual %)", value=5.5, step=0.1, key="calc_rate")
                calc_term_years = st.number_input("Term (years)", value=25, min_value=1, step=1, key="calc_term")
            calc_submit = st.form_submit_button("Calculate")

        if calc_submit:
            # monthly payment formula
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
            # store calculator result in session for later analysis
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
            st.success("Calculation done — see results on the right pane and you can 'Analyse Calculation' with AI.")

    st.markdown('</div>', unsafe_allow_html=True)

# ---- Right column: outputs, selection and analysis ----
with right_col:
    st.markdown('<div class="bf-card">', unsafe_allow_html=True)
    st.subheader("Selected PDF / Calculation")

    # Ensure session_state keys exist
    if "generated_pdf" not in st.session_state:
        st.session_state["generated_pdf"] = None
    if "uploaded_pdf" not in st.session_state:
        st.session_state["uploaded_pdf"] = None
    if "calc_result" not in st.session_state:
        st.session_state["calc_result"] = None

    # list generated PDFs for selection
    def list_generated_pdfs():
        out_dir = os.path.join("output", "generated_pdfs")
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

    # Provide download button if a file is selected
    if tmp_file:
        try:
            with open(tmp_file, "rb") as f:
                btn_bytes = f.read()
            st.download_button(label="Download selected PDF", data=btn_bytes, file_name=os.path.basename(tmp_file), mime="application/pdf")
        except Exception:
            st.warning("Could not open the selected file for preview/download.")

    # Analyse action
    if st.button("Analyse With AI"):
        if tmp_parsed:
            # We have a calculation dict; run summariser (bypass PDF)
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
            with st.spinner("Running summary on calculation..."):
                summary = generate_summary(parsed)
            st.subheader("Underwriter Summary (calculation)")
            st.write(summary)
        elif tmp_file:
            # Use existing pipeline to process the PDF
            with st.spinner("Running pipeline on PDF..."):
                result = process_pdf(tmp_file)
            st.subheader("Extracted / Analysis JSON")
            st.json(result)
            os.makedirs("output/extracted_json", exist_ok=True)
            save_json(result, os.path.join("output/extracted_json", f"{os.path.basename(tmp_file)}.json"))

            st.subheader("Underwriter Summary")
            st.write(result.get("summary", "No summary produced."))
            st.subheader("Ask a question about this application")
            question = st.text_input("Enter natural language question")
            if st.button("Ask"):
                answer = process_data(result, ask=question)
                st.write(answer)
        else:
            st.error("No PDF or calculation available to analyse.")

    st.markdown('</div>', unsafe_allow_html=True)
