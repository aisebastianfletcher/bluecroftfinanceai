# app/main.py
# Updated main.py with safe Plotly image export (uses app.plotly_utils.safe_write_plotly_image)
from __future__ import annotations
import os
import sys
import io
import json
import math
from pathlib import Path
from datetime import datetime
import typing

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Defensive imports (helpers)
try:
    from app.metrics import compute_lending_metrics, amortization_schedule  # type: ignore
except Exception:
    compute_lending_metrics = None
    amortization_schedule = None

try:
    from app.parse_helpers import extract_embedded_kv, detect_implausible_loan  # type: ignore
except Exception:
    def extract_embedded_kv(parsed: dict) -> tuple[dict, list]:
        return parsed or {}, []
    def detect_implausible_loan(parsed: dict) -> bool:
        return False

try:
    from app.pdf_form import create_pdf_report  # type: ignore
except Exception:
    create_pdf_report = None

# New: safe plotly export helper
try:
    from app.plotly_utils import safe_write_plotly_image  # type: ignore
except Exception:
    def safe_write_plotly_image(fig, out_path, format="png", scale=2):
        # fallback no-op if helper missing: attempt fig.write_image but swallow exceptions
        try:
            fig.write_image(str(out_path), format=format, scale=scale)
            return str(out_path)
        except Exception:
            try:
                import plotly.io as pio
                img_bytes = pio.to_image(fig, format=format, scale=scale)
                with open(out_path, "wb") as fh:
                    fh.write(img_bytes)
                return str(out_path)
            except Exception:
                return None

st.set_page_config(page_title="Bluecroft Finance", layout="wide")

# Styling and setup (kept identical to prior layout)
st.markdown(
    """
    <style>
      .app-header {
        background: linear-gradient(180deg, #0A2540 0%, #1E4B79 100%);
        padding: 26px 0;
        color: white;
        text-align:center;
        border-radius: 8px;
        margin-bottom: 16px;
      }
      .app-title { font-size: 30px; font-weight:800; letter-spacing:1px; margin:0; }
      .app-sub { font-size:14px; color:rgba(255,255,255,0.9); margin:6px 0 0 0; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(f'<div class="app-header"><div class="app-title">Bluecroft Finance</div><div class="app-sub">Bridging loan calculator & underwriting report</div></div>', unsafe_allow_html=True)

# Ensure output dirs
os.makedirs(ROOT / "output" / "generated_pdfs", exist_ok=True)
os.makedirs(ROOT / "output" / "uploaded_pdfs", exist_ok=True)
os.makedirs(ROOT / "output" / "supporting_docs", exist_ok=True)
os.makedirs(ROOT / "output" / "charts", exist_ok=True)

# Session defaults
for k, v in [
    ("uploaded_files", []),
    ("generated_pdf", None),
    ("uploaded_pdf", None),
    ("calc_result", None),
    ("last_analysis", None),
]:
    if k not in st.session_state:
        st.session_state[k] = v

# Two-column layout: left inputs, right preview
left, right = st.columns([4, 6])

with left:
    st.header("Inputs")
    with st.form("loan_inputs", clear_on_submit=False):
        purchase_price = st.number_input("Purchase price (GBP)", value=180000, step=1000, format="%d")
        refurbishment_cost = st.number_input("Refurbishment / project cost (GBP)", value=80000, step=500, format="%d")
        total_project_cost = st.number_input("Total project cost (auto)", value=purchase_price + refurbishment_cost, disabled=True, format="%d")
        total_override = st.checkbox("Allow override total cost", value=False)
        if total_override:
            total_project_cost = st.number_input("Total project cost (GBP)", value=total_project_cost, step=500, format="%d")

        loan_amount = st.number_input("Loan amount requested (GBP)", value=200000, step=500, format="%d")
        deposit_amount = st.number_input("Deposit amount (GBP)", value=60000, step=500, format="%d")
        loan_term_months = st.number_input("Loan term (months)", value=12, min_value=1, step=1, format="%d")
        rate_type = st.selectbox("Interest rate type", ["Annual %", "Monthly %"])
        if rate_type == "Annual %":
            interest_rate = st.number_input("Interest rate (annual %)", value=9.5, step=0.1, format="%.3f")
            interest_rate_annual = interest_rate
            interest_rate_monthly = interest_rate / 12.0
        else:
            interest_rate_monthly = st.number_input("Interest rate (monthly %)", value=0.8, step=0.01, format="%.4f")
            interest_rate_annual = interest_rate_monthly * 12.0

        arrangement_fee_pct = st.number_input("Arrangement fee (%)", value=1.0, step=0.1, format="%.2f")
        exit_fee_pct = st.number_input("Exit fee (%)", value=1.0, step=0.1, format="%.2f")

        monthly_rent = st.number_input("Estimated monthly rent (optional)", value=0, step=50, format="%d")
        gdv = st.number_input("Estimated resale value / GDV (optional)", value=0, step=1000, format="%d")

        uploads = st.file_uploader("Drop supporting files here", accept_multiple_files=True, type=None)
        if uploads:
            group = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
            saved = []
            for f in uploads:
                out = ROOT / "output" / "supporting_docs" / group
                out.mkdir(parents=True, exist_ok=True)
                dest = out / f.name
                with open(dest, "wb") as fh:
                    fh.write(f.getbuffer())
                saved.append(str(dest))
            st.session_state["uploaded_files"] = st.session_state.get("uploaded_files", []) + saved
            st.success(f"Saved {len(saved)} supporting files")

        submitted = st.form_submit_button("Run quick calculation (preview)")
        if st.button("Use sample quick calculator"):
            s = {
                "borrower": "John Doe",
                "income": 85000,
                "loan_amount": 200000,
                "property_value": 300000,
                "project_cost": purchase_price + refurbishment_cost,
                "total_cost": purchase_price + refurbishment_cost,
                "interest_rate_annual": 9.5,
                "loan_term_months": 12,
            }
            st.session_state["calc_result"] = s
            st.success("Sample parsed saved (select on right)")

    if st.session_state.get("uploaded_files"):
        st.markdown("Uploaded supporting files:")
        for p in st.session_state["uploaded_files"]:
            fname = Path(p).name
            st.write(f"- {fname}")

with right:
    st.header("Preview & Analysis")

    source_opts = []
    if st.session_state.get("uploaded_pdf"):
        source_opts.append("Uploaded PDF")
    if st.session_state.get("generated_pdf"):
        source_opts.append("Most recent generated PDF")
    if st.session_state.get("calc_result"):
        source_opts.append("Use quick calculator result")
    source_opts.append("Use inputs from form above")
    source_choice = st.selectbox("Choose data source", options=source_opts, index=len(source_opts)-1)

    parsed = {}
    if source_choice == "Use quick calculator result":
        parsed = dict(st.session_state.get("calc_result") or {})
    elif source_choice == "Use inputs from form above":
        parsed = {
            "purchase_price": purchase_price,
            "refurbishment_budget": refurbishment_cost,
            "project_cost": refurbishment_cost,
            "total_cost": total_project_cost,
            "loan_amount": loan_amount,
            "deposit_amount": deposit_amount,
            "interest_rate_annual": interest_rate_annual,
            "interest_rate_monthly": interest_rate_monthly,
            "loan_term_months": loan_term_months,
            "arrangement_fee_pct": arrangement_fee_pct,
            "exit_fee_pct": exit_fee_pct,
            "monthly_rent": monthly_rent if monthly_rent > 0 else None,
            "gdv": gdv if gdv > 0 else None,
            "income": st.session_state.get("calc_result", {}).get("income"),
            "borrower": st.session_state.get("calc_result", {}).get("borrower"),
        }
    else:
        parsed = {}

    parsed, extracted = extract_embedded_kv(parsed)
    if extracted:
        st.info(f"Extracted machine fields: {', '.join(extracted)}")

    def _norm(v):
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return v
        s = str(v).replace(",", "").replace("£", "")
        try:
            if "." in s:
                return float(s)
            return int(s)
        except Exception:
            return v

    for k in ("loan_amount", "total_cost", "project_cost", "interest_rate_annual", "loan_term_months", "income", "property_value", "deposit_amount", "gdv", "monthly_rent"):
        if k in parsed and parsed.get(k) is not None:
            parsed[k] = _norm(parsed.get(k))

    if detect_implausible_loan(parsed):
        st.warning("Detected implausible loan amount relative to property/project. Please confirm the loan amount is correct.")

    if compute_lending_metrics:
        metrics = compute_lending_metrics(parsed)
    else:
        metrics = {
            "ltv": None,
            "ltc": None,
            "monthly_interest_only_payment": None,
            "monthly_amortising_payment": None,
            "total_interest": None,
            "dscr_amortising": None,
            "dscr_interest_only": None,
            "noi": None,
            "risk_category": "Unknown",
            "risk_score_computed": None,
            "risk_reasons": [],
            "amortization_preview_rows": None
        }

    st.subheader("Raw JSON metrics")
    st.json(metrics)

    st.subheader("Human-readable summary")
    def human_summary(parsed, m):
        borrower = parsed.get("borrower", "Borrower")
        loan_amt = m.get("monthly_amortising_payment") or parsed.get("loan_amount")
        ltv = m.get("ltv")
        ltv_str = f"{ltv*100:.1f}%" if isinstance(ltv, (int, float)) else "N/A"
        risk = m.get("risk_category", "N/A")
        return f"{borrower}: Loan {loan_amt} — LTV {ltv_str} — Risk: {risk}."
    st.markdown(f"**{human_summary(parsed, metrics)}**")

    st.markdown("### Visual indicators")
    col1, col2, col3 = st.columns(3)
    ltv = metrics.get("ltv")
    def indicator_color(val):
        if val is None:
            return "gray"
        if val <= 0.6:
            return "green"
        if val <= 0.75:
            return "yellow"
        return "red"
    with col1:
        st.markdown("LTV")
        if ltv is None:
            st.write("N/A")
        else:
            st.metric("", f"{ltv*100:.1f}%")
    with col2:
        st.markdown("LTC")
        ltc = metrics.get("ltc")
        st.metric("", f"{ltc*100:.1f}%" if ltc is not None else "N/A")
    with col3:
        st.markdown("Risk")
        st.write(f"{metrics.get('risk_category','N/A')} — score {metrics.get('risk_score_computed')}")

    st.markdown("### Charts")
    ltv_val = metrics.get("ltv") or 0.0
    ltc_val = metrics.get("ltc") or 0.0
    df_bar = pd.DataFrame({"metric": ["LTV", "LTC"], "value": [ltv_val * 100, ltc_val * 100]})
    fig_bar = px.bar(df_bar, x="metric", y="value", text="value", range_y=[0, max(100, df_bar.value.max() + 10)], color="metric", color_discrete_map={"LTV":"#1f77b4","LTC":"#ff7f0e"})
    st.plotly_chart(fig_bar, use_container_width=True)

    st.markdown("Monthly interest costs")
    amort_preview = metrics.get("amortization_preview_rows")
    fig_line = None
    if amort_preview:
        df_am = pd.DataFrame(amort_preview)
        fig_line = px.line(df_am, x="month", y="interest", title="Monthly interest (first months)")
        st.plotly_chart(fig_line, use_container_width=True)
    else:
        monthly_io = metrics.get("monthly_interest_only_payment")
        if monthly_io is not None:
            months = list(range(1, 13))
            fig_line = px.line(x=months, y=[monthly_io]*len(months), labels={"x":"Month","y":"Interest (£)"}, title="Interest-only monthly")
            st.plotly_chart(fig_line, use_container_width=True)
        else:
            st.write("No monthly interest data available. Provide loan, rate and term.")

    st.markdown("Risk score")
    rscore = metrics.get("risk_score_computed") or 0.0
    color = "#2ca02c" if rscore < 0.4 else ("#ffae42" if rscore < 0.7 else "#d62728")
    fig_g = go.Figure(data=[go.Pie(values=[rscore, max(0,1-rscore)], hole=0.6, marker_colors=[color, "#eee"]))])
    fig_g.update_layout(showlegend=False, margin=dict(t=0,b=0,l=0,r=0), annotations=[dict(text=f"{rscore:.2f}", x=0.5, y=0.5, showarrow=False, font=dict(size=18))])
    st.plotly_chart(fig_g, use_container_width=True, height=220)

    st.markdown("### Amortisation preview")
    if amort_preview:
        st.table(pd.DataFrame(amort_preview).head(12))
    else:
        st.info("No amortisation schedule available (provide loan, rate, term).")

    st.markdown("### Policy / Flags")
    flags = metrics.get("policy_flags") or []
    bank_flags = metrics.get("bank_red_flags") or []
    all_flags = flags + bank_flags
    if all_flags:
        for f in all_flags:
            st.write(f"- {f}")
    else:
        st.write("No policy or bank red flags detected.")

    st.markdown("---")
    st.markdown("#### Exports")
    metrics_bytes = json.dumps(metrics, indent=2, default=str).encode("utf-8")
    st.download_button("Download raw JSON metrics", data=metrics_bytes, file_name=f"metrics_{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}.json", mime="application/json")

    # Save Plotly images using the safe helper
    png_dir = ROOT / "output" / "charts"
    png_dir.mkdir(parents=True, exist_ok=True)
    bar_png = png_dir / f"ltv_ltc_{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}.png"
    saved_bar = safe_write_plotly_image(fig_bar, str(bar_png)) if fig_bar is not None else None
    if saved_bar:
        try:
            with open(saved_bar, "rb") as fh:
                st.download_button("Download LTV vs LTC chart (PNG)", data=fh.read(), file_name=Path(saved_bar).name, mime="image/png")
        except Exception:
            st.warning("Unable to provide LTV/LTC PNG for download.")
    else:
        st.info("PNG export for LTV/LTC chart is unavailable in this environment.")

    interest_png = png_dir / f"interest_{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}.png"
    saved_interest = None
    if fig_line is not None:
        saved_interest = safe_write_plotly_image(fig_line, str(interest_png))
    if saved_interest:
        try:
            with open(saved_interest, "rb") as fh:
                st.download_button("Download interest chart (PNG)", data=fh.read(), file_name=Path(saved_interest).name, mime="image/png")
        except Exception:
            st.warning("Unable to provide interest chart PNG for download.")
    else:
        st.info("PNG export for interest chart is unavailable in this environment.")

    st.markdown("---")
    st.markdown("### Generate professional report (PDF)")
    report_notes = st.text_area("Notes for report (optional)", height=80)
    if st.button("Generate PDF Report"):
        attachments = st.session_state.get("uploaded_files", [])
        charts = [saved_bar if saved_bar else None, saved_interest if saved_interest else None]
        payload = {
            "parsed": parsed,
            "metrics": metrics,
            "notes": report_notes,
            "attachments": attachments,
            "charts": charts,
            "generated_at": datetime.utcnow().isoformat()
        }
        if create_pdf_report:
            try:
                pdf_path = create_pdf_report(payload)
                st.success(f"PDF created: {pdf_path}")
                with open(pdf_path, "rb") as fh:
                    st.download_button("Download PDF report", data=fh.read(), file_name=Path(pdf_path).name, mime="application/pdf")
            except Exception as e:
                st.error("PDF creation failed: " + str(e))
                buf = io.BytesIO()
                buf.write(json.dumps(payload, indent=2, default=str).encode("utf-8"))
                buf.seek(0)
                st.download_button("Download JSON report", data=buf, file_name="underwriting_report.json", mime="application/json")
        else:
            buf = io.BytesIO()
            buf.write(json.dumps(payload, indent=2, default=str).encode("utf-8"))
            buf.seek(0)
            st.download_button("Download JSON report", data=buf, file_name="underwriting_report.json", mime="application/json")

st.markdown("<div style='text-align:center; color:#556; margin-top:18px;'>Bluecroft Finance &middot; Underwriting assistant</div>", unsafe_allow_html=True)
