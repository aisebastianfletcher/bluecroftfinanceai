"""
Safe minimal app/main.py for diagnostics and recovery.

Paste this file over your current app/main.py, commit and redeploy on Streamlit Cloud.
After deploy, check Manage app -> Logs for the diagnostic prints and any tracebacks.
"""
import os
import sys
from pathlib import Path
import traceback

# Ensure repo root is on sys.path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Lightweight diagnostics printed to the server logs (Streamlit Cloud shows these)
print("DIAG: starting app/main.py")
print("DIAG: cwd =", os.getcwd())
print("DIAG: sys.path[0:6] =", sys.path[:6])
print("DIAG: root exists:", Path(ROOT).exists())
print("DIAG: pipeline/pipeline.py exists:", Path(ROOT, "pipeline", "pipeline.py").exists())
print("DIAG: app/static/styles.css exists:", Path(__file__).parent.joinpath("static", "styles.css").exists())

# Import streamlit AFTER printing diagnostics to avoid NameError when logging
import streamlit as st

# Minimal page config
st.set_page_config(page_title="Bluecroft Finance — Diagnostic UI", layout="wide")

# Utility: safe lazy loader for pipeline functions (so import errors won't crash startup)
def load_pipeline():
    try:
        from pipeline.pipeline import process_pdf, process_data  # type: ignore
        return process_pdf, process_data
    except Exception as e:
        # print full traceback to logs for diagnosis
        print("DIAG: failed to import pipeline:", e)
        traceback.print_exc()
        return None, None

# Minimal UI that avoids loading CSS or other assets
def app_ui():
    st.title("Bluecroft Finance — Diagnostic UI")
    st.info("This is a safe diagnostic UI. If the full app previously crashed at startup, this should load.")

    with st.expander("Diagnostics (server logs)"):
        st.write("Check the Streamlit Cloud logs (Manage app → Logs) for the printed diagnostic lines.")
        if st.button("Print additional diagnostics to logs"):
            print("DIAG: button pressed - printing extra environment info")
            print("DIAG: environ sample keys:", [k for k in os.environ.keys() if "OPENAI" in k or "PATH" in k][:20])
            st.success("Printed diagnostics to logs. Open Manage app → Logs to view them.")

    st.header("Quick test actions")

    # File uploader test
    uploaded = st.file_uploader("Upload a PDF to test save handler (no processing)", type=["pdf"])
    if uploaded:
        try:
            from app.upload_handler import save_uploaded_file  # type: ignore
            path = save_uploaded_file(uploaded)
            st.success(f"Saved uploaded file to {path}")
            print("DIAG: saved uploaded file path:", path)
        except Exception as e:
            st.error("Upload handler failed. See logs.")
            print("DIAG: upload handler exception:", e)
            traceback.print_exc()

    # Quick calculator (client-side only)
    st.subheader("Quick loan calculator")
    ccols = st.columns(3)
    with ccols[0]:
        loan = st.number_input("Loan amount (GBP)", value=240000, step=1000)
    with ccols[1]:
        rate = st.number_input("Interest rate (annual %)", value=5.5, step=0.1)
    with ccols[2]:
        years = st.number_input("Term (years)", value=25, min_value=1, step=1)
    if st.button("Calculate payments"):
        try:
            P = float(loan)
            r = float(rate) / 100.0 / 12.0
            n = int(years) * 12
            if r == 0:
                monthly = P / n
            else:
                monthly = P * r / (1 - (1 + r) ** (-n))
            st.success(f"Monthly payment: £{monthly:,.2f}")
        except Exception as e:
            st.error("Calculation failed; see logs.")
            print("DIAG: calc exception:", e)
            traceback.print_exc()

    # Try to run pipeline analysis (lazy import)
    st.subheader("Run pipeline analysis (lazy import)")
    target = st.text_input("Enter a path to a sample PDF to test (or leave blank to skip)", "")
    if st.button("Attempt pipeline import and run"):
        proc_pdf, proc_data = load_pipeline()
        if proc_pdf is None:
            st.error("Could not import pipeline. See logs for traceback.")
        else:
            st.success("Imported pipeline.process_pdf and process_data successfully.")
            st.write("You can call process_pdf on a file path in the server filesystem if available.")
            if target:
                try:
                    res = proc_pdf(target)
                    st.json(res)
                except Exception as e:
                    st.error("process_pdf raised an exception; see logs.")
                    print("DIAG: process_pdf exception:", e)
                    traceback.print_exc()

# Wrap UI entrypoint to capture exceptions and print full tracebacks to logs
def main():
    try:
        app_ui()
    except Exception as e:
        # Print the full traceback to logs (Streamlit Cloud will show these)
        print("DIAG: UNHANDLED EXCEPTION IN main():", e)
        traceback.print_exc()
        # Show a friendly message to the user without leaking sensitive info
        st.error("The app encountered an unexpected error. The full details are in the server logs (Manage app → Logs).")

if __name__ == "__main__":
    main()
