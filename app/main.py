# Ensure repo root is on sys.path so top-level modules (pipeline, utils) import correctly when running Streamlit
import os
import sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
# Diagnostic snippet — paste near top of app/main.py (after sys.path insertion)
import os, sys, traceback
from pathlib import Path

print("DIAG: STARTING APP")
print("DIAG: cwd=", os.getcwd())
print("DIAG: python sys.path[:6]=", sys.path[:6])
# key files
print("DIAG: app/main.py exists:", Path(__file__).exists())
print("DIAG: pipeline/pipeline.py exists:", Path(__file__).parent.parent.joinpath("pipeline", "pipeline.py").exists())
print("DIAG: pipeline/__init__.py exists:", Path(__file__).parent.parent.joinpath("pipeline", "__init__.py").exists())
print("DIAG: styles.css exists:", Path(__file__).parent.joinpath("static", "styles.css").exists())
# check Streamlit secret presence (no key printed)
try:
    import streamlit as _st
    _has_secret = bool(_st.secrets.get("OPENAI_API_KEY") or _st.secrets.get("OPENAI_KEY"))
    print("DIAG: streamlit available, OPENAI key present?:", _has_secret)
except Exception as e:
    print("DIAG: streamlit import error or st.secrets unavail:", e)
# Wrap main UI in try/except to catch runtime errors and emit to logs
def diag_wrap_main(fn):
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except Exception:
            print("DIAG: UNHANDLED EXCEPTION IN UI")
            traceback.print_exc()
            # important: re-raise so Streamlit shows its redacted UI error and logs contain the full trace
            raise
    return wrapper
import glob
import math
import streamlit as st
from pathlib import Path

# Load custom styles (app/static/styles.css) safely AFTER streamlit is available
_css_path = Path(__file__).parent / "static" / "styles.css"
try:
    if _css_path.exists():
        _css_text = _css_path.read_text(encoding="utf-8")
        st.markdown(f"<style>{_css_text}</style>", unsafe_allow_html=True)
    else:
        # Only warn if the file is missing at runtime (keeps logs cleaner during dev)
        st.warning("Custom style not loaded (app/static/styles.css not found).")
except Exception as _e:
    # If reading/applying the CSS fails, show a concise warning (no stacktrace/exposed info)
    st.warning("Custom style could not be applied.")
    
# Continue with the rest of your imports
from pipeline.pipeline import process_pdf, process_data
from app.pdf_form import create_pdf_from_dict
from app.upload_handler import save_uploaded_file
from utils.file_utils import save_json

st.set_page_config(page_title="Bluecroft Finance — AI Lending Assistant", layout="wide")
