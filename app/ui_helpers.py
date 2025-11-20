# app/ui_helpers.py
# Small UI helpers: center charts and inject small chart CSS overrides.

from pathlib import Path
import streamlit as st

# Inject a minimal CSS override once so chart wrappers can center nicely.
# This is intentionally small and non-invasive.
_css = """
/* Keep Altair/Vega charts block-level and auto-centered */
.stAltairChart, .stVegaLiteChart, .vega-embed, .vega-embed > div {
  display: block !important;
  margin-left: auto !important;
  margin-right: auto !important;
  width: auto !important;
}
/* Ensure Streamlit chart containers don't float */
[data-testid="stAltairChart"], [data-testid="stChart"], [data-testid="stVegaLiteChart"] {
  float: none !important;
  clear: both !important;
}
"""
# Apply the CSS once when this module is imported
try:
    st.markdown(f"<style>{_css}</style>", unsafe_allow_html=True)
except Exception:
    # safe fallback if called before streamlit is ready
    pass


def center_chart(chart, use_container_width: bool = True, left_spacer: int = 1, right_spacer: int = 1, middle_weight: int = 8):
    """
    Renders an Altair (or other Streamlit) chart centered in the page by using three columns
    and placing the chart in the middle column.

    Args:
      chart: the Altair chart object (or any object supported by st.altair_chart)
      use_container_width: passed through to st.altair_chart
      left_spacer/right_spacer/middle_weight: relative column weights; default centers the chart nicely
    """
    try:
        cols = st.columns([left_spacer, middle_weight, right_spacer])
        cols[1].altair_chart(chart, use_container_width=use_container_width)
    except Exception:
        # Fallback: attempt direct rendering if columns fail
        st.altair_chart(chart, use_container_width=use_container_width)
