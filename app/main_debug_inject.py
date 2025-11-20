# DIAGNOSTIC / FORCE-INJECT: paste this after `import streamlit as st`
from pathlib import Path
_css_path = Path(__file__).parent / "static" / "styles.css"

# Print diagnostic to server logs so you can inspect in Streamlit Cloud logs
print("DEBUG: checking for styles.css at", _css_path)
print("DEBUG: styles.css exists?", _css_path.exists())
if _css_path.exists():
    try:
        s = _css_path.read_text(encoding="utf-8")
        print("DEBUG: styles.css first 400 chars:\\n", s[:400].replace("\\n", "\\\\n"))
    except Exception as e:
        print("DEBUG: failed to read styles.css:", e)

# Force-inject a small inline style to guarantee visible background while debugging
# (remove this after you confirm styles.css loads)
st.markdown(
    """
    <style>
    /* Temporary forced inline background to confirm CSS injection */
    body, .stApp, .main, .block-container {
      background: linear-gradient(180deg, #eaf2ff 0%, #ffffff 100%) !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)
