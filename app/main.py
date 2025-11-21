"""
Bluecroft Finance — Streamlit app (app/main.py)

This implementation is aligned to the user's requirements:
- Left panel: full bridging loan inputs (purchase price, refurbishment, auto total, loan, deposit, term, interest annual/monthly,
  fees, monthly rent, GDV)
- Right panel: instant JSON metrics, professional human-readable resume-style report, charts (LTV vs LTC, monthly interest,
  risk gauge), amortisation preview table
- Drag & drop uploads on the left, preview thumbnails and attachments persisted and shown on the PDF
- "Analyse With AI" button to validate inputs, run metrics and render the full report
- "Generate PDF Report" builds a professional PDF embedding charts + attachments
- Validations and policy flags implemented: high LTV (>75%), high LTC (>80%), low DSCR (<=1.2), missing income, missing amortisation
- Exports: raw JSON metrics, downloadable charts (PNG) and PDF report

Notes:
- Requires the companion files in app/: metrics.py, parse_helpers.py and pdf_form.py (provided separately).
- Dependencies: see requirements.txt (plotly, pandas, reportlab, streamlit, matplotlib, pillow)
"""
from __future__ import annotations
import os
import sys
import io
import json
from pathlib import Path
from datetime import datetime
import typing

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Defensive imports of helper modules (provide graceful fallbacks)
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

# Page config and styling
st.set_page_config(page_title="Bluecroft Finance", layout="wide")

st.markdown(
    """
    <style>
      body { background: linear-gradient(180deg, #0A2540 0%, #1E4B79 100%); }
      .header { text-align:center; color: #ffffff; padding: 18px; }
      .brand { font-family: "Helvetica Neue", Arial, sans-serif; font-weight:800; font-size:32px; letter-spacing:1px; }
      .subtitle { color: rgba(255,255,255,0.9); margin-top:4px; font-size:14px; }
      .resume { background:#ffffff; padding:18px; border-radius:8px; color:#122; border:1px solid #e6eef5; font-family: Georgia, serif; }
      .kv { display:flex; gap:12px; margin-bottom:6px; }
      .k { width:200px; color:#445; font-weight:700; }
      .v { color:#122; }
    </style>
    """, unsafe_allow_html=True
)

st.markdown('<div class="header"><div class="brand">Bluecroft Finance</div><div class="subtitle">Bridging Loan Calculator & Underwriting Report</div></div>', unsafe_allow_html=True)

# Ensure output directories
os.makedirs(ROOT / "output" / "generated_pdfs", exist_ok=True)
os.makedirs(ROOT / "output" / "supporting_docs", exist_ok=True)

# Initialize session state
if "uploaded_files" not in st.session_state:
    st.session_state["uploaded_files"] = []
if "last_parsed" not in st.session_state:
    st.session_state["last_parsed"] = {}
if "last_metrics" not in st.session_state:
    st.session_state["last_metrics"] = {}

# Layout: two columns
left_col, right_col = st.columns([4, 6])

# --------------------- LEFT: Inputs & Uploads ---------------------
with left_col:
    st.subheader("Bridging Loan Inputs")
    with st.form("inputs_form"):
        purchase_price = st.number_input("Purchase price (GBP)", value=180000, step=1000, format="%d")
        refurbishment_cost = st.number_input("Refurbishment / project cost (GBP)", value=80000, step=500, format="%d")
        # Auto-sum total project cost, allow override
        auto_total = purchase_price + refurbishment_cost
        total_project_cost = st.number_input("Total project cost (auto)", value=auto_total, disabled=True, format="%d")
        override_total = st.checkbox("Override total project cost manually")
        if override_total:
            total_project_cost = st.number_input("Total project cost (GBP)", value=auto_total, step=500, format="%d")

        loan_amount = st.number_input("Loan amount requested (GBP)", value=200000, step=500, format="%d")
        deposit_amount = st.number_input("Deposit amount (GBP)", value=60000, step=500, format="%d")

        loan_term_months = st.number_input("Loan term (months)", value=12, min_value=1, step=1, format="%d")

        rate_mode = st.selectbox("Interest rate type", ["Annual %", "Monthly %"], index=0)
        if rate_mode == "Annual %":
            interest_rate_annual = st.number_input("Interest rate (annual %)", value=9.5, step=0.1, format="%.3f")
            interest_rate_monthly = interest_rate_annual / 12.0
        else:
            interest_rate_monthly = st.number_input("Interest rate (monthly %)", value=0.79, step=0.01, format="%.4f")
            interest_rate_annual = interest_rate_monthly * 12.0

        arrangement_fee_pct = st.number_input("Arrangement fee (%)", value=1.0, step=0.1, format="%.2f")
        exit_fee_pct = st.number_input("Exit fee (%)", value=1.0, step=0.1, format="%.2f")

        monthly_rent = st.number_input("Estimated monthly rent (optional)", value=0, step=50, format="%d")
        gdv = st.number_input("Estimated resale value / GDV (optional)", value=0, step=1000, format="%d")
        borrower_name = st.text_input("Borrower (optional)", value="")

        # Drag & drop upload supporting files
        st.markdown("Upload supporting documents (valuation, photos, models). Drag & drop or select files.")
        files = st.file_uploader("Upload supporting files", accept_multiple_files=True, type=None)
        if files:
            group = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
            saved_paths = []
            for f in files:
                dest_dir = ROOT / "output" / "supporting_docs" / group
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / f.name
                with open(dest, "wb") as fh:
                    fh.write(f.getbuffer())
                saved_paths.append(str(dest))
            st.session_state["uploaded_files"].extend(saved_paths)
            st.success(f"Saved {len(saved_paths)} supporting files")

        run_button = st.form_submit_button("Analyse With AI")

    # Show saved uploads preview thumbnails (images) and filenames
    if st.session_state["uploaded_files"]:
        st.markdown("Uploaded attachments:")
        for p in st.session_state["uploaded_files"]:
            try:
                if p.lower().endswith((".png", ".jpg", ".jpeg")):
                    img = Image.open(p)
                    st.image(img, width=160, caption=Path(p).name)
                else:
                    st.write(f"- {Path(p).name}")
            except Exception:
                st.write(f"- {Path(p).name}")

# --------------------- RIGHT: Preview, Charts, Report ---------------------
with right_col:
    st.subheader("Instant Output Preview")

    # Build parsed dict from inputs or from previous calc (if user used sample)
    parsed = {
        "borrower": borrower_name or None,
        "purchase_price": purchase_price,
        "refurbishment_budget": refurbishment_cost,
        "project_cost": refurbishment_cost,  # keep field for compatibility
        "total_cost": total_project_cost,
        "loan_amount": loan_amount,
        "deposit_amount": deposit_amount,
        "loan_term_months": int(loan_term_months),
        "interest_rate_annual": float(interest_rate_annual),
        "interest_rate_monthly": float(interest_rate_monthly),
        "arrangement_fee_pct": float(arrangement_fee_pct),
        "exit_fee_pct": float(exit_fee_pct),
        "monthly_rent": monthly_rent if monthly_rent > 0 else None,
        "gdv": gdv if gdv > 0 else None,
        "income": None,
    }

    # If user previously loaded a quick-calculator parsed sample, allow that source
    if st.session_state.get("calc_result"):
        st.info("Quick calculator sample is available via the source selector below.")

    # Source selector (choose parsed origin)
    src_options = ["Use form inputs"]
    if st.session_state.get("calc_result"):
        src_options.insert(0, "Use quick calculator result")
    if st.session_state.get("last_parsed"):
        src_options.append("Use last parsed result")
    src = st.selectbox("Data source for analysis", src_options, index=0)

    if src == "Use quick calculator result":
        parsed = dict(st.session_state["calc_result"] or parsed)
    elif src == "Use last parsed result":
        parsed = dict(st.session_state["last_parsed"] or parsed)

    # Extract embedded machine fields from strings (if present)
    parsed, extracted = extract_embedded_kv(parsed)
    if extracted:
        st.info(f"Extracted fields: {', '.join(extracted)}")

    # Basic normalisation of numeric-like fields
    def _norm_val(v):
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

    for key in ["loan_amount", "total_cost", "project_cost", "interest_rate_annual", "loan_term_months", "income", "property_value", "deposit_amount", "gdv", "monthly_rent"]:
        if key in parsed and parsed.get(key) is not None:
            parsed[key] = _norm_val(parsed.get(key))

    # Detect implausible small loan amounts
    if detect_implausible_loan(parsed):
        st.warning("Detected implausible loan amount relative to property/project. Please verify values on the left.")

    # Validate required core fields (per your strict parser expectations and app logic)
    required_errors = []
    for req in ["project_cost", "total_cost", "interest_rate_annual", "loan_term_months"]:
        if parsed.get(req) in (None, "", 0):
            required_errors.append(f"Required field missing or zero: {req}")

    # If missing required fields, show warnings and let user correct, but still attempt metrics where possible
    if required_errors:
        st.warning("Required inputs missing: " + "; ".join(required_errors))

    # If the user pressed the Analyse button on the left, run metrics and show full report
    if (run_button) or st.button("Run Analysis (compute metrics)"):
        if compute_lending_metrics is None:
            st.error("Metrics engine (app.metrics) is not installed. Please add app/metrics.py.")
            metrics = {}
        else:
            metrics = compute_lending_metrics(parsed)

        # Persist last parsed/metrics
        st.session_state["last_parsed"] = parsed
        st.session_state["last_metrics"] = metrics

        # Display Raw JSON metrics
        st.markdown("#### Raw JSON metrics")
        st.json(metrics)

        # Human-readable summary (professional)
        st.markdown("#### Executive summary")
        borrower = parsed.get("borrower") or "Borrower"
        loan_disp = parsed.get("loan_amount") or "N/A"
        ltv = metrics.get("ltv")
        ltv_str = f"{ltv*100:.1f}%" if isinstance(ltv, (int, float)) else "N/A"
        risk = metrics.get("risk_category") or "N/A"
        summary_text = f"<div class='resume'><strong style='font-size:16px'>{borrower}</strong><div class='kv'><div class='k'>Requested loan</div><div class='v'>£{loan_disp:,}</div></div><div class='kv'><div class='k'>LTV</div><div class='v'>{ltv_str}</div></div><div class='kv'><div class='k'>Risk</div><div class='v'>{risk}</div></div></div>"
        st.markdown(summary_text, unsafe_allow_html=True)

        # Visual indicators (colored badges via metric)
        st.markdown("#### Visual indicators")
        c1, c2, c3 = st.columns(3)
        with c1:
            if metrics.get("ltv") is not None:
                st.metric("LTV", f"{metrics.get('ltv')*100:.1f}%", delta=None)
            else:
                st.metric("LTV", "N/A")
        with c2:
            if metrics.get("ltc") is not None:
                st.metric("LTC", f"{metrics.get('ltc')*100:.1f}%", delta=None)
            else:
                st.metric("LTC", "N/A")
        with c3:
            st.metric("Risk", f"{metrics.get('risk_category', 'N/A')} (score {metrics.get('risk_score_computed', 'N/A')})")

        # Charts
        st.markdown("#### Charts")
        # LTV vs LTC bar chart
        ltv_val = metrics.get("ltv") or 0.0
        ltc_val = metrics.get("ltc") or 0.0
        df_bar = pd.DataFrame({"Metric": ["LTV", "LTC"], "Value": [ltv_val * 100, ltc_val * 100]})
        fig_bar = px.bar(df_bar, x="Metric", y="Value", text=df_bar["Value"].round(1), range_y=[0, max(100, df_bar["Value"].max() + 10)], color="Metric", color_discrete_map={"LTV":"#1f77b4","LTC":"#ff7f0e"})
        st.plotly_chart(fig_bar, use_container_width=True)

        # Monthly interest chart (from amortization preview if present else interest-only)
        st.markdown("Monthly interest costs")
        amort_preview = metrics.get("amortization_preview_rows")
        if amort_preview:
            df_am = pd.DataFrame(amort_preview)
            fig_line = px.line(df_am, x="month", y="interest", title="Monthly interest (first months)", markers=True)
            st.plotly_chart(fig_line, use_container_width=True)
        else:
            monthly_io = metrics.get("monthly_interest_only_payment")
            if monthly_io:
                months = list(range(1, int(min(36, parsed.get("loan_term_months", 12)))+1))
                fig_const = px.line(x=months, y=[monthly_io]*len(months), labels={"x":"Month","y":"Interest (£)"}, title="Interest-only monthly")
                st.plotly_chart(fig_const, use_container_width=True)
            else:
                st.info("Provide loan, interest rate and term to render monthly interest chart.")

        # Risk gauge (donut)
        st.markdown("Risk score")
        rscore = metrics.get("risk_score_computed") or 0.0
        color = "#2ca02c" if rscore < 0.4 else ("#ffae42" if rscore < 0.7 else "#d62728")
        fig_g = go.Figure(data=[go.Pie(values=[rscore, max(0, 1.0 - rscore)], hole=0.6, marker_colors=[color, "#efefef"], sort=False)])
        fig_g.update_layout(showlegend=False, margin=dict(t=0,b=0,l=0,r=0), annotations=[dict(text=f"{rscore:.2f}", x=0.5, y=0.5, showarrow=False, font=dict(size=18))])
        st.plotly_chart(fig_g, use_container_width=True, height=220)

        # Amortisation table
        st.markdown("#### Amortisation preview (first 12 months)")
        if amort_preview:
            st.table(pd.DataFrame(amort_preview).head(12))
        else:
            st.info("No amortisation schedule available.")

        # Flags and reasons
        st.markdown("#### Policy flags / bank red flags")
        all_flags = (metrics.get("policy_flags") or []) + (metrics.get("bank_red_flags") or [])
        if all_flags:
            for f in all_flags:
                st.write(f"- {f}")
        else:
            st.write("No automated flags detected.")

        # Provide downloads: metrics JSON, chart PNGs
        st.markdown("#### Exports")
        # Metrics JSON
        metrics_bytes = json.dumps(metrics, indent=2, default=str).encode("utf-8")
        st.download_button("Download raw JSON metrics", data=metrics_bytes, file_name=f"metrics_{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}.json", mime="application/json")

        # Save Plotly figures as PNG to include in PDF later
        png_dir = ROOT / "output" / "charts"
        png_dir.mkdir(parents=True, exist_ok=True)
        bar_png = png_dir / f"ltv_ltc_{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}.png"
        fig_bar.write_image(str(bar_png), scale=2)
        st.download_button("Download LTV vs LTC chart (PNG)", data=open(bar_png, "rb").read(), file_name=bar_png.name, mime="image/png")

        # Interest chart PNG
        interest_png = png_dir / f"interest_{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}.png"
        if amort_preview:
            fig_line.write_image(str(interest_png), scale=2)
            st.download_button("Download interest chart (PNG)", data=open(interest_png, "rb").read(), file_name=interest_png.name, mime="image/png")
        elif monthly_io:
            fig_const.write_image(str(interest_png), scale=2)
            st.download_button("Download interest chart (PNG)", data=open(interest_png, "rb").read(), file_name=interest_png.name, mime="image/png")

        # ----------------- Generate PDF Report -----------------
        st.markdown("---")
        st.markdown("### Generate Professional PDF Report")
        report_notes = st.text_area("Report notes (optional)", height=100)
        if st.button("Generate PDF Report"):
            payload = {
                "parsed": parsed,
                "metrics": metrics,
                "notes": report_notes,
                "attachments": st.session_state.get("uploaded_files", []),
                "charts": [str(bar_png) if bar_png.exists() else None, str(interest_png) if interest_png.exists() else None],
                "generated_at": datetime.utcnow().isoformat(),
            }
            # Fallback: if pdf generator not present, return JSON
            if create_pdf_report is None:
                st.warning("PDF generator (app.pdf_form) not installed. Downloading JSON report instead.")
                buf = io.BytesIO()
                buf.write(json.dumps(payload, indent=2, default=str).encode("utf-8"))
                buf.seek(0)
                st.download_button("Download JSON report", data=buf, file_name="underwriting_report.json", mime="application/json")
            else:
                try:
                    pdf_path = create_pdf_report(payload)
                    st.success(f"PDF generated: {pdf_path}")
                    with open(pdf_path, "rb") as fh:
                        st.download_button("Download PDF report", data=fh.read(), file_name=Path(pdf_path).name, mime="application/pdf")
                except Exception as e:
                    st.error("Failed to create PDF: " + str(e))
                    # fallback JSON
                    buf = io.BytesIO()
                    buf.write(json.dumps(payload, indent=2, default=str).encode("utf-8"))
                    buf.seek(0)
                    st.download_button("Download JSON report", data=buf, file_name="underwriting_report.json", mime="application/json")

    else:
        # If not yet run, show a compact preview of any cached metrics
        if st.session_state.get("last_metrics"):
            st.markdown("#### Last computed metrics (preview)")
            st.json(st.session_state["last_metrics"])
        else:
            st.info("Enter inputs on the left and click Analyse With AI (or Run Analysis) to compute the metrics and render the full report.")

# Footer
st.markdown("<div style='text-align:center; color:#dbe7f5; margin-top:18px;'>Bluecroft Finance &middot; Confidential underwriting tool</div>", unsafe_allow_html=True)
