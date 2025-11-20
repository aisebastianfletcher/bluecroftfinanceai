# Ensure repo root is on sys.path so top-level modules (pipeline, utils) import correctly when running Streamlit
import os
import sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import streamlit as st
from pipeline.pipeline import process_pdf, process_data
from app.pdf_form import create_pdf_from_dict
from app.upload_handler import save_uploaded_file
from utils.file_utils import save_json

st.set_page_config(page_title="AI Lending Assistant", layout="wide")

st.title("AI Lending Assistant — Bluecroft Demo")

# Use tabs to present Form vs Upload paths
tab_form, tab_upload = st.tabs(["Fill Form (generate PDF)", "Upload PDF"])

generated_pdf_path = None
uploaded_pdf_path = None

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
        generated_pdf_path = create_pdf_from_dict(data)
        st.success(f"PDF generated: {generated_pdf_path}")
        # provide download button for convenience
        try:
            with open(generated_pdf_path, "rb") as f:
                pdf_bytes = f.read()
            st.download_button(
                label="Download generated PDF",
                data=pdf_bytes,
                file_name=os.path.basename(generated_pdf_path),
                mime="application/pdf",
            )
        except Exception as e:
            st.warning(f"Couldn't offer a download (server filesystem may be restricted): {e}")

with tab_upload:
    st.markdown("Upload an existing application or statement PDF for analysis.")
    uploaded = st.file_uploader("Upload application / statement PDF", type=["pdf"], accept_multiple_files=False, key="upload1")
    if uploaded:
        uploaded_pdf_path = save_uploaded_file(uploaded)
        st.success(f"Saved uploaded file to {uploaded_pdf_path}")
        # allow download back or quick preview action
        try:
            with open(uploaded_pdf_path, "rb") as f:
                up_bytes = f.read()
            st.download_button(
                label="Download uploaded PDF",
                data=up_bytes,
                file_name=os.path.basename(uploaded_pdf_path),
                mime="application/pdf",
            )
        except Exception as e:
            st.warning(f"Couldn't offer a download (server filesystem may be restricted): {e}")

# Choose which PDF to analyse (priority: uploaded -> generated -> none)
st.markdown("---")
st.header("Analyse a PDF with AI")
source_choice = st.radio("Select PDF source to analyse", options=["Use uploaded PDF", "Use generated PDF"], index=0)

tmp_file = None
if source_choice == "Use uploaded PDF":
    if uploaded_pdf_path:
        tmp_file = uploaded_pdf_path
    else:
        st.warning("No PDF was uploaded. Switch to 'Use generated PDF' or upload a PDF above.")
else:
    if generated_pdf_path:
        tmp_file = generated_pdf_path
    else:
        st.info("No PDF was generated in this session yet. Use the 'Fill Form' tab to create one.")

if st.button("Analyse With AI"):
    if tmp_file is None:
        st.error("No PDF available: please upload a PDF or generate one from the form.")
    else:
        with st.spinner("Running pipeline..."):
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
