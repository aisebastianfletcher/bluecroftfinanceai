# Bluecroft Finance — Vertical, sectioned report layout (full app/main.py)
# - Switches UI to a stacked, single-column flow so charts render centered in a boxed report
# - Removes side-by-side dependency so left column doesn't appear blank
# - Centers charts inside a "report box" with a max-width so content looks professional
# - Keeps lazy imports, robust lending metrics and amortization
import os
import sys
from pathlib import Path
import glob
import math
import json
import io
import typing

# repo root
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import streamlit as st
import pandas as pd
import altair as alt

st.set_page_config(page_title="Bluecroft Finance — AI Lending Assistant", layout="wide")

# ---- Load global CSS (styles.css) safely and small inline style for report box ----
_css_path = Path(__file__).parent / "static" / "styles.css"
if _css_path.exists():
    try:
        st.markdown(f"<style>{_css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)
    except Exception:
        pass

# Add a small style specifically for the report box and to make charts behave
st.markdown(
    """
    <style>
    /* Centered report container */
    .report-box {
      max-width: 980px;
      margin-left: auto;
      margin-right: auto;
      background: rgba(255,255,255,0.98);
      padding: 18px;
      border-radius: 10px;
      box-shadow: 0 8px 24px rgba(10,30,60,0.08);
      border: 1px solid rgba(15,40,80,0.04);
    }
    /* Make Altair charts block-level so margin:auto works */
    .stAltairChart, .stVegaLiteChart, .vega-embed { display:block !important; margin-left: auto !important; margin-right: auto !important; width: 100% !important; }
    [data-testid="stAltairChart"], [data-testid="stChart"], [data-testid="stVegaLiteChart"] { float:none !important; clear:both !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ----------------- Helper: center_chart (columns fallback) -----------------
def center_chart(chart_obj, use_container_width: bool = True, height: int | None = None):
    """
    Center an Altair chart inside a narrow container.
    Uses the .report-box styling (page-level) and also places the chart inside a middle column
    so Streamlit positions it centrally.
    """
    try:
        cols = st.columns([1, 10, 1])
        if height is not None:
            try:
                chart_obj = chart_obj.properties(height=height)
            except Exception:
                pass
        cols[1].altair_chart(chart_obj, use_container_width=use_container_width)
    except Exception:
        st.altair_chart(chart_obj, use_container_width=use_container_width)

# ----------------- Lazy import helpers -----------------
def load_pipeline() -> typing.Tuple[typing.Optional[typing.Callable], typing.Optional[typing.Callable]]:
    try:
        from pipeline.pipeline import process_pdf, process_data  # type: ignore
        return process_pdf, process_data
    except Exception as e:
        print("PIPELINE IMPORT ERROR:", e)
        return None, None

def load_summarizer() -> typing.Tuple[typing.Callable, typing.Callable]:
    try:
        from pipeline.llm.summarizer import generate_summary, answer_question  # type: ignore
        return generate_summary, answer_question
    except Exception as e:
        print("SUMMARIZER IMPORT ERROR:", e)
        def fallback_summary(parsed: dict) -> str:
            borrower = parsed.get("borrower", "Unknown")
            income = parsed.get("income", "N/A")
            loan = parsed.get("loan_amount", "N/A")
            lm = parsed.get("lending_metrics", {}) or {}
            return (
                f"Borrower: {borrower}\nIncome: £{income:,}\nLoan: £{loan:,}\n"
                f"LTV: {lm.get('ltv','N/A')}, DSCR: {lm.get('dscr','N/A')}\n"
                "Recommendation: Manual review for elevated metrics."
            )
        def fallback_answer(parsed: dict, question: str) -> str:
            return "LLM not available. Please configure OPENAI_API_KEY for richer answers."
        return fallback_summary, fallback_answer

def load_reporting_module() -> typing.Optional[typing.Any]:
    try:
        import app.reporting as reporting  # type: ignore
        return reporting
    except Exception:
        return None

# ----------------- Amortization & Lending metrics -----------------
def amortization_schedule(loan_amount: float, annual_rate_decimal: float, term_months: int) -> pd.DataFrame:
    P = float(loan_amount)
    n = int(term_months)
    r = float(annual_rate_decimal) / 12.0 if annual_rate_decimal else 0.0
    if n <= 0:
        raise ValueError("term_months must be > 0")
    if r == 0:
        payment = P / n
    else:
        payment = P * r / (1 - (1 + r) ** (-n))
    balance = P
    rows = []
    for m in range(1, n + 1):
        interest = balance * r
        principal = payment - interest
        if m == n:
            principal = balance
            payment = interest + principal
            balance = 0.0
        else:
            balance = balance - principal
        rows.append({
            "month": m,
            "payment": round(payment, 2),
            "interest": round(interest, 2),
            "principal": round(principal, 2),
            "balance": round(balance, 2)
        })
    return pd.DataFrame(rows)

def compute_lending_metrics(parsed: dict) -> dict:
    lm = {}
    loan = float(parsed.get("loan_amount") or parsed.get("loan") or 0.0)
    prop = parsed.get("property_value") or None
    total_cost = parsed.get("project_cost") or parsed.get("total_cost") or None

    # LTV & LTC
    try:
        ltv = (loan / float(prop)) if prop and float(prop) > 0 else None
    except Exception:
        ltv = None
    lm["ltv"] = round(ltv, 4) if isinstance(ltv, (int, float)) else None

    try:
        ltc = (loan / float(total_cost)) if total_cost and float(total_cost) > 0 else None
    except Exception:
        ltc = None
    lm["ltc"] = round(ltc, 4) if isinstance(ltc, (int, float)) else None

    # Normalize rate & term
    rate_raw = parsed.get("interest_rate_annual") or parsed.get("interest_rate") or parsed.get("rate")
    term_months = parsed.get("term_months") or parsed.get("term") or None
    rate_decimal = None
    if rate_raw is not None:
        try:
            r = float(rate_raw)
            if r > 1:
                r = r / 100.0
            rate_decimal = r
        except Exception:
            rate_decimal = None

    amort_df = None
    monthly_payment = parsed.get("monthly_payment")
    total_interest = parsed.get("total_interest")

    if rate_decimal is not None and term_months:
        try:
            amort_df = amortization_schedule(loan, rate_decimal, int(term_months))
            monthly_payment = float(amort_df["payment"].iloc[0])
            total_interest = float(amort_df["interest"].sum())
        except Exception as e:
            print("Amortization generation failed:", e)
            amort_df = None

    if monthly_payment is None:
        try:
            if rate_decimal is not None and term_months:
                r = rate_decimal
                n = int(term_months)
                if r == 0:
                    monthly_payment = loan / n
                else:
                    monthly_payment = loan * (r / 12.0) / (1 - (1 + r / 12.0) ** (-n))
            else:
                monthly_payment = parsed.get("monthly_payment") or None
        except Exception:
            monthly_payment = None

    lm["monthly_payment"] = round(monthly_payment, 2) if isinstance(monthly_payment, (int, float)) else None
    lm["total_interest"] = round(total_interest, 2) if isinstance(total_interest, (int, float)) else None
    lm["annual_debt_service"] = round(lm["monthly_payment"] * 12.0, 2) if lm.get("monthly_payment") else None

    # NOI / proxy
    noi = parsed.get("noi") or parsed.get("net_operating_income")
    if noi is None:
        annual_rent = parsed.get("annual_rent") or parsed.get("rental_income_annual")
        operating_expenses = parsed.get("operating_expenses") or parsed.get("annual_expenses")
        if annual_rent is not None:
            try:
                noi = float(annual_rent) - float(operating_expenses or 0)
                lm["noi_estimated_from_rent"] = True
            except Exception:
                noi = None
        else:
            borrower_income = parsed.get("income")
            if borrower_income:
                noi = borrower_income * 0.30
                lm["noi_estimated_from_income_proxy"] = True
            else:
                noi = None
    lm["noi"] = round(noi, 2) if isinstance(noi, (int, float)) else None

    # DSCR
    dscr = None
    try:
        if lm.get("noi") is not None and lm.get("annual_debt_service"):
            if lm["annual_debt_service"] > 0:
                dscr = lm["noi"] / lm["annual_debt_service"]
    except Exception:
        dscr = None
    lm["dscr"] = round(dscr, 3) if isinstance(dscr, (int, float)) else None

    # flags
    policy_flags = parsed.get("policy_flags") or parsed.get("flags") or []
    bank_red_flags = parsed.get("bank_red_flags") or []
    lm["policy_flags"] = policy_flags
    lm["bank_red_flags"] = bank_red_flags

    # risk scoring (clear thresholds)
    ltv_risk = 0.0
    if lm.get("ltv") is not None:
        v = lm["ltv"]
        if v < 0.6:
            ltv_risk = 0.0
        elif v < 0.8:
            ltv_risk = 0.5
        else:
            ltv_risk = 1.0

    dscr_risk = 1.0
    if lm.get("dscr") is not None:
        d = lm["dscr"]
        if d >= 1.25:
            dscr_risk = 0.0
        elif d >= 1.0:
            dscr_risk = 0.5
        else:
            dscr_risk = 1.0

    flags_risk = 1.0 if (policy_flags or bank_red_flags) else 0.0

    risk_score = (0.5 * ltv_risk) + (0.35 * dscr_risk) + (0.15 * flags_risk)
    risk_score = min(max(risk_score, 0.0), 1.0)
    lm["risk_score_computed"] = round(risk_score, 3)
    if risk_score >= 0.7:
        lm["risk_category"] = "High"
    elif risk_score >= 0.4:
        lm["risk_category"] = "Medium"
    else:
        lm["risk_category"] = "Low"

    # reasons
    reasons = []
    if lm.get("ltv") is not None:
        if lm["ltv"] >= 0.85:
            reasons.append(f"High LTV ({lm['ltv']:.2f})")
        elif lm["ltv"] >= 0.75:
            reasons.append(f"Elevated LTV ({lm['ltv']:.2f})")
    if lm.get("dscr") is not None and lm["dscr"] < 1.0:
        reasons.append(f"DSCR below 1.0 ({lm['dscr']:.2f})")
    if flags_risk:
        reasons.append("Policy / bank flags present")
    if not reasons:
        reasons.append("No automated flags detected")
    lm["risk_reasons"] = reasons

    # amortization preview if available
    if amort_df is not None:
        lm["amortization_preview_rows"] = amort_df.head(6).to_dict(orient="records")
        lm["amortization_total_interest"] = round(amort_df["interest"].sum(), 2)
    else:
        lm["amortization_preview_rows"] = None

    parsed["lending_metrics"] = lm
    return lm

# ----------------- Prepare output dirs -----------------
os.makedirs(os.path.join(ROOT, "output", "generated_pdfs"), exist_ok=True)
os.makedirs(os.path.join(ROOT, "output", "extracted_json"), exist_ok=True)

# ----------------- Header -----------------
st.markdown(
    """
    <div class="bf-header">
      <div style="display:flex; align-items:center; gap:16px;">
        <div style="font-size:28px; font-weight:800; letter-spacing:1px; color: #fff;">
          Bluecroft Finance
        </div>
        <div style="flex:1;">
          <p style="margin:0; color: #eaf6ff;">AI Lending Assistant — stacked report layout</p>
        </div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ----------------- Session state defaults -----------------
for k, v in [
    ("generated_pdf", None),
    ("uploaded_pdf", None),
    ("calc_result", None),
    ("last_analysis", None),
    ("qa_question", ""),
    ("qa_answer", None),
]:
    if k not in st.session_state:
        st.session_state[k] = v

# ----------------- TOP: Inputs (stacked sections) -----------------
st.markdown("## Inputs & Actions")
with st.expander("Form (generate PDF)"):
    with st.form("application_form"):
        col1, col2 = st.columns(2)
        with col1:
            borrower_name = st.text_input("Borrower name", "John Doe")
            email = st.text_input("Email", "")
            income = st.number_input("Annual income (GBP)", value=85000, step=1000)
            loan_amount = st.number_input("Requested loan amount (GBP)", value=240000, step=1000)
        with col2:
            property_value = st.number_input("Property value (GBP)", value=330000, step=1000)
            term_months = st.number_input("Loan term (months)", value=300, min_value=1, step=1)
            notes = st.text_area("Notes / comments", "")
        submit_generate = st.form_submit_button("Generate PDF")
    if submit_generate:
        try:
            from app.pdf_form import create_pdf_from_dict  # type: ignore
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
            with open(generated_path, "rb") as f:
                st.download_button("Download generated PDF", data=f.read(), file_name=os.path.basename(generated_path), mime="application/pdf")
        except Exception as e:
            st.error("Failed to generate PDF. See logs.")
            print("PDF GENERATION ERROR:", e)

with st.expander("Upload PDF for analysis"):
    uploaded = st.file_uploader("Upload application / statement PDF", type=["pdf"], accept_multiple_files=False, key="upload1")
    if uploaded:
        try:
            from app.upload_handler import save_uploaded_file  # type: ignore
            uploaded_path = save_uploaded_file(uploaded)
            st.session_state["uploaded_pdf"] = uploaded_path
            st.success(f"Saved uploaded file to {uploaded_path}")
            with open(uploaded_path, "rb") as f:
                st.download_button("Download uploaded PDF", data=f.read(), file_name=os.path.basename(uploaded_path), mime="application/pdf")
        except Exception as e:
            st.error("Failed to save uploaded file. See logs.")
            print("UPLOAD SAVE ERROR:", e)

with st.expander("Quick Calculator"):
    with st.form("calc_form"):
        c1, c2 = st.columns(2)
        with c1:
            calc_borrower = st.text_input("Borrower name", "John Doe", key="calc_borrower")
            calc_income = st.number_input("Annual income (GBP)", value=85000, step=1000, key="calc_income")
            calc_loan = st.number_input("Loan amount (GBP)", value=240000, step=1000, key="calc_loan")
        with c2:
            calc_property = st.number_input("Property value (GBP)", value=330000, step=1000, key="calc_property")
            calc_rate = st.number_input("Interest rate (annual %)", value=5.5, step=0.1, key="calc_rate")
            calc_term_years = st.number_input("Term (years)", value=25, min_value=1, step=1, key="calc_term")
        calc_submit = st.form_submit_button("Calculate")
    if calc_submit:
        try:
            P = float(calc_loan)
            annual_r = float(calc_rate) / 100.0
            n = int(calc_term_years) * 12
            if annual_r == 0:
                monthly = P / n
            else:
                r = annual_r / 12.0
                monthly = P * r / (1 - (1 + r) ** (-n))
            total_payment = monthly * n
            total_interest = total_payment - P
            ltv = None
            if calc_property and calc_property > 0:
                ltv = P / float(calc_property)
            st.session_state["calc_result"] = {
                "borrower": calc_borrower,
                "income": float(calc_income),
                "loan_amount": float(calc_loan),
                "property_value": float(calc_property),
                "monthly_payment": round(monthly, 2),
                "total_payment": round(total_payment, 2),
                "total_interest": round(total_interest, 2),
                "ltv": round(ltv, 4) if ltv is not None else None,
                "term_months": n,
                "interest_rate_annual": annual_r,
            }
            st.success("Calculation done — choose it below to analyse.")
        except Exception as e:
            st.error("Calculation failed; see logs.")
            print("CALC ERROR:", e)

# ----------------- Selection area -----------------
st.markdown("## Selection")
gen_list = []
out_dir = os.path.join(ROOT, "output", "generated_pdfs")
os.makedirs(out_dir, exist_ok=True)
gen_list = sorted(glob.glob(os.path.join(out_dir, "*.pdf")), key=os.path.getmtime, reverse=True)
gen_list = [os.path.basename(p) for p in gen_list]

options = []
if st.session_state.get("uploaded_pdf"):
    options.append("Uploaded PDF")
if st.session_state.get("generated_pdf"):
    options.append("Most recent generated PDF")
if gen_list:
    options.append("Choose from generated files")
options.append("Use quick calculator result")

choice = st.selectbox("Choose source to inspect / analyse", options=options, index=0 if options else -1)

tmp_file = None
tmp_parsed = None
if choice == "Uploaded PDF":
    tmp_file = st.session_state.get("uploaded_pdf")
    st.markdown(f"**Uploaded PDF:** {os.path.basename(tmp_file) if tmp_file else '—'}")
elif choice == "Most recent generated PDF":
    tmp_file = st.session_state.get("generated_pdf")
    st.markdown(f"**Generated PDF:** {os.path.basename(tmp_file) if tmp_file else '—'}")
elif choice == "Choose from generated files":
    sel = st.selectbox("Select generated file", options=gen_list, index=0)
    tmp_file = os.path.join("output", "generated_pdfs", sel)
    st.markdown(f"**Generated PDF:** {sel}")
elif choice == "Use quick calculator result":
    tmp_parsed = st.session_state.get("calc_result")
    if tmp_parsed:
        st.markdown("**Calculator result selected**")
        st.write(tmp_parsed)
    else:
        st.info("No quick calculation present. Use the Quick Calculator tab to create one.")

if tmp_file:
    try:
        with open(tmp_file, "rb") as f:
            st.download_button("Download selected PDF", data=f.read(), file_name=os.path.basename(tmp_file), mime="application/pdf")
    except Exception:
        st.warning("Could not open the selected file for preview/download.")

st.markdown("**Automatically derived lending metrics help underwriters make fast decisions.**")

# ----------------- ANALYSE and REPORT (stacked single-column) -----------------
if st.button("Analyse With AI"):
    generate_summary, answer_question = load_summarizer()
    reporting = load_reporting_module()

    if tmp_parsed:
        parsed = {
            "borrower": tmp_parsed.get("borrower"),
            "income": tmp_parsed.get("income"),
            "loan_amount": tmp_parsed.get("loan_amount"),
            "property_value": tmp_parsed.get("property_value"),
            "monthly_payment": tmp_parsed.get("monthly_payment"),
            "total_interest": tmp_parsed.get("total_interest"),
            "term_months": tmp_parsed.get("term_months"),
            "interest_rate_annual": tmp_parsed.get("interest_rate_annual"),
        }
        metrics = compute_lending_metrics(parsed)
        st.session_state["last_analysis"] = parsed

        # Summary
        try:
            summary_text = generate_summary(parsed)
        except Exception as e:
            summary_text = f"LLM_ERROR: {e}"
        st.markdown("## Underwriter Summary")
        st.write(summary_text)

        # Render report box (centered, stacked sections)
        st.markdown('<div class="report-box">', unsafe_allow_html=True)

        # KPIs row (centered by using columns inside the report box)
        k1, k2, k3 = st.columns([1,1,1])
        try:
            with k1:
                st.metric("LTV", f"{metrics.get('ltv'):.0%}" if isinstance(metrics.get('ltv'), float) else (metrics.get('ltv') or "N/A"))
            with k2:
                st.metric("DSCR", f"{metrics.get('dscr'):.2f}" if metrics.get('dscr') is not None else "N/A")
            with k3:
                st.metric("Risk", f"{metrics.get('risk_score_computed', 'N/A'):.0%}" if isinstance(metrics.get('risk_score_computed'), float) else (metrics.get('risk_score_computed') or "N/A"))
        except Exception:
            pass

        # Amortization section
        st.markdown("### Amortization & Monthly Breakdown")
        try:
            rate_raw = parsed.get("interest_rate_annual")
            term = parsed.get("term_months")
            rate = None
            if rate_raw is not None:
                r = float(rate_raw)
                if r > 1:
                    r = r / 100.0
                rate = r
            if rate is not None and term:
                df_am = amortization_schedule(parsed.get("loan_amount",0), rate, int(term))
                base = alt.Chart(df_am).encode(x=alt.X("month:Q", title="Month"))
                balance_line = base.mark_line(color="#1f77b4", strokeWidth=2).encode(y=alt.Y("balance:Q", title="Remaining balance (£)"))
                balance_area = base.mark_area(opacity=0.12, color="#1f77b4").encode(y="balance:Q")
                center_chart((balance_area + balance_line), height=260)
                src = df_am.melt(id_vars=["month"], value_vars=["principal","interest"], var_name="component", value_name="amount")
                stacked = alt.Chart(src).mark_area().encode(x="month:Q", y=alt.Y("amount:Q", title="Amount (£)"), color=alt.Color("component:N", scale=alt.Scale(range=["#2ca02c","#ff7f0e"])))
                center_chart(stacked, height=200)
            else:
                st.info("Amortization schedule not available: provide interest rate and term.")
        except Exception as e:
            st.warning("Could not render amortization visuals: " + str(e))

        # Payment composition section
        st.markdown("### Payment Composition")
        try:
            if 'df_am' in locals():
                pie_df = pd.DataFrame([{"part":"Principal","value":df_am["principal"].sum()},{"part":"Interest","value":df_am["interest"].sum()}])
                pie = alt.Chart(pie_df).mark_arc(innerRadius=40).encode(theta=alt.Theta("value:Q"), color=alt.Color("part:N", scale=alt.Scale(range=["#2ca02c","#ff7f0e"])), tooltip=["part", alt.Tooltip("value:Q", format=",.2f")])
                center_chart(pie, height=220)
            else:
                if metrics.get("total_interest") is not None:
                    st.write(f"Estimated total interest: £{metrics.get('total_interest'):,}")
        except Exception:
            pass

        # Affordability section
        st.markdown("### Affordability")
        try:
            income_monthly = parsed.get("income",0)/12.0 if parsed.get("income") else 0
            payment = metrics.get("monthly_payment") or 0
            df_aff = pd.DataFrame([{"label":"Monthly payment","value":payment},{"label":"Monthly income","value":income_monthly}])
            bars = alt.Chart(df_aff).mark_bar().encode(x="label:N", y=alt.Y("value:Q", title="Amount (£)"), color=alt.Color("label:N"))
            center_chart(bars, height=160)
            if income_monthly:
                st.write(f"Payment / Income = {(payment / income_monthly):.2f}x")
        except Exception:
            pass

        # Risk section
        st.markdown("### Risk Breakdown & Explainability")
        try:
            aff_score = max(min(1 - (metrics.get("ltv") or 0), 1.0), 0.0) if metrics.get("ltv") is not None else 0.33
            ltv_score = metrics.get("ltv") or 0
            flag_score = 1.0 if metrics.get("policy_flags") or metrics.get("bank_red_flags") else 0.0
            total = (aff_score + ltv_score + flag_score) or 1.0
            df_r = pd.DataFrame({"factor":["Affordability","LTV risk","Flags"], "value":[aff_score/total*100, ltv_score/total*100, flag_score/total*100]})
            donut = alt.Chart(df_r).mark_arc(innerRadius=40).encode(theta=alt.Theta("value:Q"), color=alt.Color("factor:N"))
            center_chart(donut, height=160)
            st.write("Reasons:", "; ".join(metrics.get("risk_reasons",[])))
        except Exception:
            pass

        # Optionally render richer reporting module (non-blocking)
        reporting = load_reporting_module()
        if reporting:
            try:
                reporting.render_full_report(parsed, metrics)
            except Exception as e:
                print("REPORTING.render_full_report error:", e)

        # Download JSON report
        try:
            buf = io.BytesIO()
            payload = {"parsed": parsed, "lending_metrics": metrics, "summary": summary_text}
            buf.write(json.dumps(payload, indent=2).encode("utf-8"))
            buf.seek(0)
            st.download_button("Download report (JSON)", data=buf, file_name="calculation_report.json", mime="application/json")
        except Exception:
            pass

        st.markdown('</div>', unsafe_allow_html=True)

    elif tmp_file:
        proc_pdf, proc_data = load_pipeline()
        if proc_pdf is None:
            st.error("Pipeline not available. Check logs.")
        else:
            with st.spinner("Running pipeline on PDF..."):
                try:
                    result = proc_pdf(tmp_file)
                    metrics = compute_lending_metrics(result)
                    st.session_state["last_analysis"] = result

                    st.markdown("## Extracted / Analysis JSON")
                    st.json(result)

                    generate_summary, _ = load_summarizer()
                    try:
                        summary_text = generate_summary(result)
                    except Exception as e:
                        summary_text = f"LLM_ERROR: {e}"
                    st.markdown("## Underwriter Summary")
                    st.write(summary_text)

                    # Render the same stacked report box for PDF results
                    st.markdown('<div class="report-box">', unsafe_allow_html=True)
                    # KPIs
                    k1, k2, k3 = st.columns([1,1,1])
                    with k1:
                        st.metric("LTV", f"{metrics.get('ltv'):.0%}" if isinstance(metrics.get('ltv'), float) else (metrics.get('ltv') or "N/A"))
                    with k2:
                        st.metric("DSCR", f"{metrics.get('dscr'):.2f}" if metrics.get('dscr') is not None else "N/A")
                    with k3:
                        st.metric("Risk", f"{metrics.get('risk_score_computed', 'N/A'):.0%}" if isinstance(metrics.get('risk_score_computed'), float) else (metrics.get('risk_score_computed') or "N/A"))

                    # Amortization & charts (same rendering)
                    try:
                        rate_raw = result.get("interest_rate_annual")
                        term = result.get("term_months")
                        rate = None
                        if rate_raw is not None:
                            r = float(rate_raw)
                            if r > 1:
                                r = r / 100.0
                            rate = r
                        if rate is not None and term:
                            df_am = amortization_schedule(result.get("loan_amount",0), rate, int(term))
                            base = alt.Chart(df_am).encode(x=alt.X("month:Q", title="Month"))
                            balance_line = base.mark_line(color="#1f77b4", strokeWidth=2).encode(y=alt.Y("balance:Q", title="Remaining balance (£)"))
                            balance_area = base.mark_area(opacity=0.12, color="#1f77b4").encode(y="balance:Q")
                            center_chart((balance_area + balance_line), height=260)
                            src = df_am.melt(id_vars=["month"], value_vars=["principal","interest"], var_name="component", value_name="amount")
                            stacked = alt.Chart(src).mark_area().encode(x="month:Q", y=alt.Y("amount:Q", title="Amount (£)"), color=alt.Color("component:N"))
                            center_chart(stacked, height=200)
                        else:
                            st.info("Amortization schedule not available.")
                    except Exception as e:
                        st.warning("Amortization visuals unavailable: " + str(e))

                    # Payment composition / affordability / risk (stacked sections)
                    try:
                        if 'df_am' in locals():
                            pie_df = pd.DataFrame([{"part":"Principal","value":df_am["principal"].sum()},{"part":"Interest","value":df_am["interest"].sum()}])
                            pie = alt.Chart(pie_df).mark_arc(innerRadius=40).encode(theta=alt.Theta("value:Q"), color=alt.Color("part:N"))
                            center_chart(pie, height=200)
                    except Exception:
                        pass

                    try:
                        income_monthly = result.get("income",0)/12.0 if result.get("income") else 0
                        payment = metrics.get("monthly_payment") or 0
                        df_aff = pd.DataFrame([{"label":"Monthly payment","value":payment},{"label":"Monthly income","value":income_monthly}])
                        bars = alt.Chart(df_aff).mark_bar().encode(x="label:N", y=alt.Y("value:Q", title="Amount (£)"), color=alt.Color("label:N"))
                        center_chart(bars, height=160)
                        if income_monthly:
                            st.write(f"Payment / Income = {(payment / income_monthly):.2f}x")
                    except Exception:
                        pass

                    try:
                        aff_score = max(min(1 - (metrics.get("ltv") or 0), 1.0), 0.0) if metrics.get("ltv") is not None else 0.33
                        ltv_score = metrics.get("ltv") or 0
                        flag_score = 1.0 if metrics.get("policy_flags") or metrics.get("bank_red_flags") else 0.0
                        total = (aff_score + ltv_score + flag_score) or 1.0
                        df_r = pd.DataFrame({"factor":["Affordability","LTV risk","Flags"], "value":[aff_score/total*100, ltv_score/total*100, flag_score/total*100]})
                        donut = alt.Chart(df_r).mark_arc(innerRadius=40).encode(theta=alt.Theta("value:Q"), color=alt.Color("factor:N"))
                        center_chart(donut, height=160)
                        st.write("Reasons:", "; ".join(metrics.get("risk_reasons",[])))
                    except Exception:
                        pass

                    st.markdown('</div>', unsafe_allow_html=True)

                except Exception as e:
                    st.error("Pipeline failed during processing. See logs.")
                    print("PIPELINE RUN ERROR:", e)

# ----------------- Persistent Q&A -----------------
st.markdown("## Ask about this application")
st.text_input("Enter a natural language question", key="qa_question")
if st.button("Ask"):
    question = st.session_state.get("qa_question", "").strip()
    if not question:
        st.warning("Please enter a question.")
    else:
        parsed = st.session_state.get("last_analysis")
        if not parsed:
            st.error("No analysis available. Run 'Analyse With AI' first.")
        else:
            q = question.lower()
            metrics = parsed.get("lending_metrics") or compute_lending_metrics(parsed)
            answer = None
            # Deterministic explainable responses for common queries
            if ("why" in q and ("flag" in q or "risk" in q)):
                answer = "Reasons: " + "; ".join(metrics.get("risk_reasons", []))
            elif ("summar" in q) or ("financial position" in q):
                gen, _ = load_summarizer()
                try:
                    answer = gen(parsed)
                except Exception:
                    answer = f"Borrower: {parsed.get('borrower','Unknown')}. Income: £{parsed.get('income','N/A')}. LTV: {metrics.get('ltv','N/A')}."
            elif ("bridge" in q or "bridg" in q) and ("suit" in q or "suitable" in q):
                term_ok = parsed.get("term_months") is not None and parsed.get("term_months") <= 24
                ltv_ok = metrics.get("ltv") is not None and metrics.get("ltv") <= 0.75
                dscr_ok = metrics.get("dscr") is None or metrics.get("dscr") >= 1.0
                ok = term_ok and ltv_ok and dscr_ok
                reasons = []
                if not term_ok: reasons.append(f"term months = {parsed.get('term_months')}")
                if not ltv_ok: reasons.append(f"ltv = {metrics.get('ltv')}")
                if not dscr_ok: reasons.append(f"dscr = {metrics.get('dscr')}")
                answer = "Suitable for typical bridging: " + ("Yes" if ok else "No") + ("" if ok else f". Issues: {', '.join(reasons)}")
            else:
                proc_pdf, proc_data = load_pipeline()
                if proc_data:
                    try:
                        answer = proc_data(parsed, ask=question)
                    except Exception as e:
                        print("Q&A pipeline error:", e)
                        _, answer_question = load_summarizer()
                        try:
                            answer = answer_question(parsed, question)
                        except Exception as e2:
                            answer = f"LLM_ERROR: {e2}"
                else:
                    _, answer_question = load_summarizer()
                    try:
                        answer = answer_question(parsed, question)
                    except Exception as e:
                        answer = f"LLM_ERROR: {e}"
            st.session_state["qa_answer"] = answer

if st.session_state.get("qa_answer"):
    st.markdown("**Answer:**")
    st.write(st.session_state.get("qa_answer"))
    
