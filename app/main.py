# Ensure repo root is on sys.path so top-level modules (pipeline, utils) import correctly when running Streamlit
import os
import sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import glob
import streamlit as st
from pipeline.pipeline import process_pdf, process_data
from app.pdf_form import create_pdf_from_dict
from app.upload_handler import save_uploaded_file
from utils.file_utils import save_json

st.set_page_config(page_title="AI Lending Assistant", layout="wide")

st.title("AI Lending Assistant — Bluecroft Demo")

# Persist generated/uploaded PDF paths across reruns
if "generated_pdf" not in st.session_state:
    st.session_state["generated_pdf"] = None
if "uploaded_pdf" not in st.session_state:
    st.session_state["uploaded_pdf"] = None

# Helper to list generated PDFs
def list_generated_pdfs():
    out_dir = os.path.join("output", "generated_pdfs")
    os.makedirs(out_dir, exist_ok=True)
    files = sorted(glob.glob(os.path.join(out_dir, "*.pdf")), key=os.path.getmtime, reverse=True)
    # return basenames for nicer selectbox labels
    return [os.path.basename(f) for f in files]

# Use tabs to present Form vs Upload paths
tab_form, tab_upload = st.tabs(["Fill Form (generate PDF)", "Upload PDF"])

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
        st.session_state["generated_pdf"] = generated_path
        st.success(f"PDF generated: {generated_path}")
        # provide download button
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
            st.warning(f"Couldn't offer a download (server filesystem may be restricted): {e}")

with tab_upload:
    st.markdown("Upload an existing application or statement PDF for analysis.")
    uploaded = st.file_uploader("Upload application / statement PDF", type=["pdf"], accept_multiple_files=False, key="upload1")
    if uploaded:
        uploaded_path = save_uploaded_file(uploaded)
        st.session_state["uploaded_pdf"] = uploaded_path
        st.success(f"Saved uploaded file to {uploaded_path}")
        # allow download back
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
            st.warning(f"Couldn't offer a download (server filesystem may be restricted): {e}")

# Selection area for which PDF to analyse
st.markdown("---")
st.header("Analyse a PDF with AI")

generated_list = list_generated_pdfs()

# Build options and default selection
options = []
if st.session_state.get("uploaded_pdf"):
    options.append("Uploaded PDF")
if st.session_state.get("generated_pdf"):
    options.append("Most recent generated PDF")
if generated_list:
    options.append("Choose from generated files")

if not options:
    st.info("No PDFs available. Please upload a PDF or generate one using the tabs above.")
    tmp_file = None
else:
    choice = st.radio("Select source to analyse", options=options, index=0)

    tmp_file = None
    if choice == "Uploaded PDF":
        tmp_file = st.session_state.get("uploaded_pdf")
    elif choice == "Most recent generated PDF":
        tmp_file = st.session_state.get("generated_pdf")
    elif choice == "Choose from generated files":
        # show selectbox with all generated files
        sel = st.selectbox("Select generated file", options=generated_list, index=0)
        tmp_file = os.path.join("output", "generated_pdfs", sel)

# Quick preview (download) of selected file
if tmp_file:
    st.markdown(f"**Selected file:** {os.path.basename(tmp_file)}")
    try:
        with open(tmp_file, "rb") as f:
            btn_bytes = f.read()
        st.download_button(label="Download selected PDF", data=btn_bytes, file_name=os.path.basename(tmp_file), mime="application/pdf")
    except Exception:
        st.warning("Could not open the selected file for preview/download.")

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
