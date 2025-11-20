# Bluecroft Finance — Stacked report layout with bridging loan payment options
# - Adds standard bridging repayment calculations (interest-only monthly payments)
# - Shows both amortising and interest-only payments and compares impacts on DSCR
# - Keeps robust lazy imports, metrics, amortization schedule, and stacked report UI
import os
import sys
from pathlib import Path
import glob
import math
import json
import io
import typing

# Ensure repo root importable
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import streamlit as st
import pandas as pd
import altair as alt

st.set_page_config(page_title="Bluecroft Finance — AI Lending Assistant", layout="wide")

# ---- Load global CSS safely ----
_css_path = Path(__file__).parent / "static" / "styles.css"
if _css_path.exists():
    try:
        st.markdown(f"<style>{_css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)
    except Exception:
        pass

# Report-box and chart CSS
st.markdown(
    """
    <style>
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
    .stAltairChart, .stVegaLiteChart, .vega-embed { display:block !important; margin-left: auto !important; margin-right: auto !important; width: 100% !important; }
    [data-testid="stAltairChart"], [data-testid="stChart"], [data-testid="stVegaLiteChart"] { float:none !important; clear:both !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

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
    """
    Compute and attach lending_metrics to parsed, including:
     - LTV, LTC
     - amortising monthly payment (if rate+term)
     - interest-only monthly payment (bridging standard)
     - DSCR using NOI or proxy
     - risk score and reasons
    """
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
    monthly_amort = parsed.get("monthly_payment")
    total_interest = parsed.get("total_interest")

    # Amortising schedule if available
    if rate_decimal is not None and term_months:
        try:
            amort_df = amortization_schedule(loan, rate_decimal, int(term_months))
            monthly_amort = float(amort_df["payment"].iloc[0])
            total_interest = float(amort_df["interest"].sum())
        except Exception as e:
            print("Amortization generation failed:", e)
            amort_df = None

    # Interest-only monthly payment (standard bridging repayment)
    monthly_io = None
    if rate_decimal is not None:
        # Typical bridging monthly payment is interest-only: loan * annual_rate / 12
        try:
            monthly_io = loan * rate_decimal / 12.0
        except Exception:
            monthly_io = None

    # Store computed payments
    lm["monthly_amortising_payment"] = round(monthly_amort, 2) if isinstance(monthly_amort, (int, float)) else None
    lm["monthly_interest_only_payment"] = round(monthly_io, 2) if isinstance(monthly_io, (int, float)) else None
    lm["total_interest"] = round(total_interest, 2) if isinstance(total_interest, (int, float)) else None
    lm["annual_debt_service_amortising"] = round(lm["monthly_amortising_payment"] * 12.0, 2) if lm.get("monthly_amortising_payment") else None
    lm["annual_debt_service_io"] = round(lm["monthly_interest_only_payment"] * 12.0, 2) if lm.get("monthly_interest_only_payment") else None

    # NOI detection / proxy
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

    # DSCR (for amortising and IO cases)
    dscr_amort = None
    dscr_io = None
    try:
        if lm.get("noi") is not None and lm.get("annual_debt_service_amortising"):
            if lm["annual_debt_service_amortising"] > 0:
                dscr_amort = lm["noi"] / lm["annual_debt_service_amortising"]
        if lm.get("noi") is not None and lm.get("annual_debt_service_io"):
            if lm["annual_debt_service_io"] > 0:
                dscr_io = lm["noi"] / lm["annual_debt_service_io"]
    except Exception:
        dscr_amort = None
        dscr_io = None
    lm["dscr_amortising"] = round(dscr_amort, 3) if isinstance(dscr_amort, (int, float)) else None
    lm["dscr_interest_only"] = round(dscr_io, 3) if isinstance(dscr_io, (int, float)) else None

    # Flags and risk scoring (use amortising DSCR as default risk indicator, but expose IO DSCR)
    policy_flags = parsed.get("policy_flags") or parsed.get("flags") or []
    bank_red_flags = parsed.get("bank_red_flags") or []
    lm["policy_flags"] = policy_flags
    lm["bank_red_flags"] = bank_red_flags

    # Risk heuristics: use LTV and DSCR_amortising for score but show IO impact in report
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
    if lm.get("dscr_amortising") is not None:
        d = lm["dscr_amortising"]
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
    lm["risk_category"] = "High" if risk_score >= 0.7 else ("Medium" if risk_score >= 0.4 else "Low")

    # Reasons
    reasons = []
    if lm.get("ltv") is not None:
        if lm["ltv"] >= 0.85:
            reasons.append(f"High LTV ({lm['ltv']:.2f})")
        elif lm["ltv"] >= 0.75:
            reasons.append(f"Elevated LTV ({lm['ltv']:.2f})")
    if lm.get("dscr_amortising") is not None and lm["dscr_amortising"] < 1.0:
        reasons.append(f"Amortising DSCR below 1.0 ({lm['dscr_amortising']:.2f})")
    if lm.get("dscr_interest_only") is not None and lm["dscr_interest_only"] < 1.0:
        reasons.append(f"Interest-only DSCR below 1.0 ({lm['dscr_interest_only']:.2f})")
    if flags_risk:
        reasons.append("Policy / bank flags present")
    if not reasons:
        reasons.append("No automated flags detected")
    lm["risk_reasons"] = reasons

    # Amortization preview rows
    if amort_df is not None:
        lm["amortization_preview_rows"] = amort_df.head(6).to_dict(orient="records")
        lm["amortization_total_interest"] = round(amort_df["interest"].sum(), 2)
    else:
        lm["amortization_preview_rows"] = None

    parsed["lending_metrics"] = lm
    return lm

# Ensure output dirs exist
os.makedirs(os.path.join(ROOT, "output", "generated_pdfs"), exist_ok=True)
os.makedirs(os.path.join(ROOT, "output", "extracted_json"), exist_ok=True)

# ---- Header ----
st.markdown(
    """
    <div class="bf-header">
      <div style="display:flex; align-items:center; gap:16px;">
        <div style="font-size:28px; font-weight:800; letter-spacing:1px; color: #fff;">
          Bluecroft Finance
        </div>
        <div style="flex:1;">
          <p style="margin:0; color: #eaf6ff;">AI Lending Assistant — bridging repayment analysis added</p>
        </div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Session defaults
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

# ----------------- Inputs: stacked sections -----------------
st.markdown("## Inputs & Actions")
with st.expander("Form (generate PDF)"):
    with st.form("application_form"):
        c1, c2 = st.columns(2)
        with c1:
            borrower_name = st.text_input("Borrower name", "John Doe")
            email = st.text_input("Email", "")
            income = st.number_input("Annual income (GBP)", value=85000, step=1000)
            loan_amount = st.number_input("Requested loan amount (GBP)", value=240000, step=1000)
        with c2:
            property_value = st.number_input("Property value (GBP)", value=330000, step=1000)
            term_months = st.number_input("Loan term (months)", value=300, min_value=1, step=1)
            # allow explicit interest rate and repayment type
            interest_rate = st.number_input("Interest rate (annual %)", value=5.5, step=0.1)
            repayment_type = st.selectbox("Repayment type", ["Amortising", "Interest-only (bridging)", "Interest-only with balloon"])
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
                "interest_rate_annual": float(interest_rate),
                "repayment_type": repayment_type,
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
        cc1, cc2 = st.columns(2)
        with cc1:
            calc_borrower = st.text_input("Borrower name", "John Doe", key="calc_borrower")
            calc_income = st.number_input("Annual income (GBP)", value=85000, step=1000, key="calc_income")
            calc_loan = st.number_input("Loan amount (GBP)", value=240000, step=1000, key="calc_loan")
        with cc2:
            calc_property = st.number_input("Property value (GBP)", value=330000, step=1000, key="calc_property")
            calc_rate = st.number_input("Interest rate (annual %)", value=5.5, step=0.1, key="calc_rate")
            calc_term_years = st.number_input("Term (years)", value=25, min_value=1, step=1, key="calc_term")
            calc_repayment = st.selectbox("Repayment type", ["Amortising", "Interest-only (bridging)"], key="calc_repayment")
        calc_submit = st.form_submit_button("Calculate")
    if calc_submit:
        try:
            P = float(calc_loan)
            annual_r = float(calc_rate) / 100.0
            n = int(calc_term_years) * 12
            monthly_amort = None
            if annual_r == 0:
                monthly_amort = P / n
            else:
                r = annual_r / 12.0
                monthly_amort = P * r / (1 - (1 + r) ** (-n))
            monthly_io = P * (annual_r) / 12.0 if annual_r is not None else None
            total_payment = (monthly_amort * n) if monthly_amort is not None else None
            total_interest = total_payment - P if total_payment is not None else None
            ltv = None
            if calc_property and calc_property > 0:
                ltv = P / float(calc_property)
            st.session_state["calc_result"] = {
                "borrower": calc_borrower,
                "income": float(calc_income),
                "loan_amount": float(calc_loan),
                "property_value": float(calc_property),
                "monthly_amortising_payment": round(monthly_amort, 2) if monthly_amort is not None else None,
                "monthly_interest_only_payment": round(monthly_io, 2) if monthly_io is not None else None,
                "total_payment": round(total_payment, 2) if total_payment is not None else None,
                "total_interest": round(total_interest, 2) if total_interest is not None else None,
                "ltv": round(ltv, 4) if ltv is not None else None,
                "term_months": n,
                "interest_rate_annual": annual_r,
                "repayment_type": calc_repayment,
            }
            st.success("Calculation done — choose it below to analyse.")
        except Exception as e:
            st.error("Calculation failed; see logs.")
            print("CALC ERROR:", e)

# ----------------- Selection -----------------
st.markdown("## Selection")
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

# ----------------- ANALYSE & REPORT (stacked single-column) -----------------
if st.button("Analyse With AI"):
    generate_summary, answer_question = load_summarizer()
    reporting = load_reporting_module()

    if tmp_parsed:
        parsed = {
            "borrower": tmp_parsed.get("borrower"),
            "income": tmp_parsed.get("income"),
            "loan_amount": tmp_parsed.get("loan_amount"),
            "property_value": tmp_parsed.get("property_value"),
            "term_months": tmp_parsed.get("term_months"),
            "interest_rate_annual": tmp_parsed.get("interest_rate_annual"),
            "repayment_type": tmp_parsed.get("repayment_type"),
        }
        # include any precomputed payments from calculator
        if tmp_parsed.get("monthly_amortising_payment") is not None:
            parsed["monthly_payment"] = tmp_parsed.get("monthly_amortising_payment")
        metrics = compute_lending_metrics(parsed)
        st.session_state["last_analysis"] = parsed

        # Summary
        try:
            summary_text = generate_summary(parsed)
        except Exception as e:
            summary_text = f"LLM_ERROR: {e}"
        st.markdown("## Underwriter Summary")
        st.write(summary_text)

        # Report box
        st.markdown('<div class="report-box">', unsafe_allow_html=True)

        # KPI row: show both amortising and interest-only payments
        k1, k2, k3 = st.columns([1,1,1])
        try:
            with k1:
                st.metric("LTV", f"{metrics.get('ltv'):.0%}" if isinstance(metrics.get('ltv'), float) else (metrics.get('ltv') or "N/A"))
            with k2:
                st.metric("Monthly (Amortising)", f"£{metrics.get('monthly_amortising_payment'):,}" if metrics.get('monthly_amortising_payment') else "N/A")
            with k3:
                st.metric("Monthly (Interest-only)", f"£{metrics.get('monthly_interest_only_payment'):,}" if metrics.get('monthly_interest_only_payment') else "N/A")
        except Exception:
            pass

        # Payments comparison section (table)
        st.markdown("### Payment Scenarios")
        try:
            rows = [
                {
                    "Scenario": "Amortising",
                    "Monthly payment": f"£{metrics.get('monthly_amortising_payment'):,}" if metrics.get('monthly_amortising_payment') else "N/A",
                    "Annual debt service": f"£{metrics.get('annual_debt_service_amortising'):,}" if metrics.get('annual_debt_service_amortising') else "N/A",
                    "DSCR": metrics.get('dscr_amortising') if metrics.get('dscr_amortising') is not None else "N/A"
                },
                {
                    "Scenario": "Interest-only (Bridging)",
                    "Monthly payment": f"£{metrics.get('monthly_interest_only_payment'):,}" if metrics.get('monthly_interest_only_payment') else "N/A",
                    "Annual debt service": f"£{metrics.get('annual_debt_service_io'):,}" if metrics.get('annual_debt_service_io') else "N/A",
                    "DSCR": metrics.get('dscr_interest_only') if metrics.get('dscr_interest_only') is not None else "N/A"
                },
            ]
            st.table(pd.DataFrame(rows))
        except Exception:
            pass

        # Amortization (if available)
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
                # center via columns
                cols = st.columns([1,10,1])
                cols[1].altair_chart((balance_area + balance_line).properties(height=260), use_container_width=True)
                src = df_am.melt(id_vars=["month"], value_vars=["principal","interest"], var_name="component", value_name="amount")
                cols[1].altair_chart(alt.Chart(src).mark_area().encode(
                    x="month:Q",
                    y=alt.Y("amount:Q", title="Amount (£)"),
                    color=alt.Color("component:N", scale=alt.Scale(range=["#2ca02c","#ff7f0e"])),
                    tooltip=["month","component",alt.Tooltip("amount:Q", format=",.2f")]
                ).properties(height=200), use_container_width=True)
            else:
                st.info("Amortization schedule not available: provide interest rate and term.")
        except Exception as e:
            st.warning("Could not render amortization visuals: " + str(e))

        # Payment composition, affordability, risk (stacked sections)
        st.markdown("### Payment Composition")
        try:
            if 'df_am' in locals():
                pie_df = pd.DataFrame([{"part":"Principal","value":df_am["principal"].sum()},{"part":"Interest","value":df_am["interest"].sum()}])
                cols = st.columns([1,10,1])
                cols[1].altair_chart(alt.Chart(pie_df).mark_arc(innerRadius=40).encode(theta=alt.Theta("value:Q"), color=alt.Color("part:N")), use_container_width=True)
            else:
                if metrics.get("total_interest") is not None:
                    st.write(f"Estimated total interest (amortising): £{metrics.get('total_interest'):,}")
        except Exception:
            pass

        st.markdown("### Affordability")
        try:
            income_monthly = parsed.get("income",0)/12.0 if parsed.get("income") else 0
            payment_am = metrics.get("monthly_amortising_payment") or 0
            payment_io = metrics.get("monthly_interest_only_payment") or 0
            df_aff = pd.DataFrame([
                {"Label":"Monthly payment (amortising)", "Value": payment_am},
                {"Label":"Monthly payment (interest-only)", "Value": payment_io},
                {"Label":"Monthly income", "Value": income_monthly},
            ])
            cols = st.columns([1,10,1])
            cols[1].altair_chart(alt.Chart(df_aff).mark_bar().encode(
                x=alt.X("Label:N"),
                y=alt.Y("Value:Q", title="Amount (£)"),
                color=alt.Color("Label:N")
            ).properties(height=160), use_container_width=True)
            if income_monthly:
                st.write(f"Payment/Income (amortising) = {(payment_am / income_monthly):.2f}x")
                st.write(f"Payment/Income (interest-only) = {(payment_io / income_monthly):.2f}x")
        except Exception:
            pass

        st.markdown("### Risk Breakdown & Explainability")
        try:
            aff_score = max(min(1 - (metrics.get("ltv") or 0), 1.0), 0.0) if metrics.get("ltv") is not None else 0.33
            ltv_score = metrics.get("ltv") or 0
            flag_score = 1.0 if metrics.get("policy_flags") or metrics.get("bank_red_flags") else 0.0
            total = (aff_score + ltv_score + flag_score) or 1.0
            df_r = pd.DataFrame({"factor":["Affordability","LTV risk","Flags"], "value":[aff_score/total*100, ltv_score/total*100, flag_score/total*100]})
            cols = st.columns([1,10,1])
            cols[1].altair_chart(alt.Chart(df_r).mark_arc(innerRadius=40).encode(theta=alt.Theta("value:Q"), color=alt.Color("factor:N")).properties(height=160), use_container_width=True)
            st.write("Reasons:", "; ".join(metrics.get("risk_reasons",[])))
        except Exception:
            pass

        # Optional richer reporting module rendering (non-blocking)
        reporting = load_reporting_module()
        if reporting:
            try:
                reporting.render_full_report(parsed, metrics)
            except Exception as e:
                print("REPORTING.render_full_report error:", e)

        # Download JSON
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

                    # Render report box for PDF case (same structure as above)
                    st.markdown('<div class="report-box">', unsafe_allow_html=True)
                    k1, k2, k3 = st.columns([1,1,1])
                    with k1:
                        st.metric("LTV", f"{metrics.get('ltv'):.0%}" if isinstance(metrics.get('ltv'), float) else (metrics.get('ltv') or "N/A"))
                    with k2:
                        st.metric("Monthly (Amortising)", f"£{metrics.get('monthly_amortising_payment'):,}" if metrics.get('monthly_amortising_payment') else "N/A")
                    with k3:
                        st.metric("Monthly (Interest-only)", f"£{metrics.get('monthly_interest_only_payment'):,}" if metrics.get('monthly_interest_only_payment') else "N/A")

                    # Amortization visuals & other stacked sections...
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
                            cols = st.columns([1,10,1])
                            cols[1].altair_chart((balance_area + balance_line).properties(height=260), use_container_width=True)
                        else:
                            st.info("Amortization schedule not available.")
                    except Exception as e:
                        st.warning("Amortization visuals unavailable: " + str(e))

                    # Payment composition / affordability / risk (stacked)
                    try:
                        if 'df_am' in locals():
                            pie_df = pd.DataFrame([{"part":"Principal","value":df_am["principal"].sum()},{"part":"Interest","value":df_am["interest"].sum()}])
                            cols = st.columns([1,10,1])
                            cols[1].altair_chart(alt.Chart(pie_df).mark_arc(innerRadius=40).encode(theta=alt.Theta("value:Q"), color=alt.Color("part:N")), use_container_width=True)
                    except Exception:
                        pass

                    try:
                        income_monthly = result.get("income",0)/12.0 if result.get("income") else 0
                        payment_am = metrics.get("monthly_amortising_payment") or 0
                        payment_io = metrics.get("monthly_interest_only_payment") or 0
                        df_aff = pd.DataFrame([
                            {"Label":"Monthly payment (amortising)", "Value": payment_am},
                            {"Label":"Monthly payment (interest-only)", "Value": payment_io},
                            {"Label":"Monthly income", "Value": income_monthly},
                        ])
                        cols = st.columns([1,10,1])
                        cols[1].altair_chart(alt.Chart(df_aff).mark_bar().encode(x="Label:N", y=alt.Y("Value:Q", title="Amount (£)"), color=alt.Color("Label:N")).properties(height=160), use_container_width=True)
                        if income_monthly:
                            st.write(f"Payment/Income (amortising) = {(payment_am / income_monthly):.2f}x")
                            st.write(f"Payment/Income (interest-only) = {(payment_io / income_monthly):.2f}x")
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
                dscr_io_ok = metrics.get("dscr_interest_only") is None or metrics.get("dscr_interest_only") >= 1.0
                ok = term_ok and ltv_ok and dscr_io_ok
                reasons = []
                if not term_ok: reasons.append(f"term months = {parsed.get('term_months')}")
                if not ltv_ok: reasons.append(f"ltv = {metrics.get('ltv')}")
                if not dscr_io_ok: reasons.append(f"interest-only dscr = {metrics.get('dscr_interest_only')}")
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
