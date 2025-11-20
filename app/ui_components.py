import streamlit as st
import os

def two_column_form():
    return st.columns(2)

def small_info(msg):
    st.info(msg)

def pdf_download_button_from_path(path, label="Download PDF"):
    """
    Helper: show a download button for a PDF at filesystem path (if readable).
    Return True on success, False if file couldn't be opened.
    """
    try:
        with open(path, "rb") as f:
            pdf_bytes = f.read()
        st.download_button(label=label, data=pdf_bytes, file_name=os.path.basename(path), mime="application/pdf")
        return True
    except Exception:
        return False
