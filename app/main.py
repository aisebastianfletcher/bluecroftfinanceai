import os
import streamlit as st
from pipeline.pipeline import process_pdf, process_data
from app.pdf_form import create_pdf_from_dict
from app.upload_handler import save_uploaded_file
from utils.file_utils import save_json

st.set_page_config(page_title="AI Lending Assistant", layout="wide")

st.title("AI Lending Assistant — Bluecroft Demo")

st.sidebar.header("Create borrower (form)")
with st.sidebar.form("borrower_form"):
    borrower_name = st.text_input("Borrower name", "John Doe")
    income = st.number_input("Annual income (GBP)", value=85000)
    loan_amount = st.number_input("Requested loan amount (GBP)", value=240000)
    property_value = st.number_input("Property value (GBP)", value=330000)
    submit_generate = st.form_submit_button("Generate PDF")

out_path = None
if submit_generate:
    data = {
        "borrower": borrower_name,
        "income": float(income),
        "loan_amount": float(loan_amount),
        "property_value": float(property_value),
    }
    out_path = create_pdf_from_dict(data)
    st.sidebar.success(f"PDF generated: {out_path}")

st.header("Upload or select a PDF to analyse")
uploaded = st.file_uploader("Upload application / statement PDF", type=["pdf"])

if uploaded:
    tmp_file = save_uploaded_file(uploaded)
    st.success(f"Saved uploaded file to {tmp_file}")
else:
    tmp_file = None
    if out_path:
        st.info(f"You generated a PDF in this session: {out_path}. Use 'Analyse With AI' to process it.")

if st.button("Analyse With AI"):
    if tmp_file is None and out_path:
        tmp_file = out_path
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
