# Polished Bluecroft Finance UI — revised graphs layout and corrected calculations
# - Fixes layout so charts render in balanced grid (not stacked down one side)
# - Improves accuracy of amortization, totals, LTV/LTC, DSCR computations
# - Uses amortization schedule when rate & term present to compute total interest and annual debt service
# - Keeps lazy imports/fallbacks for robustness
import os
import sys
from pathlib import Path
import glob
import math
import json
import io
import typing

# Ensure repo root is importable
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import streamlit as st
import pandas as pd
import altair as alt

st.set_page_config(page_title="Bluecroft Finance — AI Lending Assistant", layout="wide")

# Load CSS if present (silent fallback)
_css_path = Path(__file__).parent / "static" / "styles.css"
if _css_path.exists():
    try:
        st.markdown(_css_path.read_text(encoding="utf-8"), unsafe_allow_html=True)
    except Exception:
        pass
else:
    st.markdown(
        """
        <style>
        .bf-header { background: linear-gradient(90deg,#003366,#0078D4); color: white; padding:12px 18px; border-radius:8px; }
        .bf-card { background: rgba(255,255,255,0.98); padding:16px; border-radius:10px; box-shadow: 0 6px 18px rgba(10,30,60,0.06); }
        </style>
        """,
        unsafe_allow_html=True,
    )

# ---------- Lazy import helpers ----------
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
        # fallback implementations
        def fallback_summary(parsed: dict) -> str:
            borrower = parsed.get("borrower", "Unknown")
            income = parsed.get("income", "N/A")
            loan = parsed.get("loan_amount", "N/A")
            lm = parsed.get("lending_metrics", {}) or {}
            ltv = lm.get("ltv", "N/A")
            risk_cat = lm.get("risk_category", "N/A")
            return (
                f"Borrower: {borrower}\n"
                f"Income: £{income:,}\n"
                f"Loan: £{loan:,}\n"
                f"LTV: {ltv}\n"
                f"Risk category: {risk_cat}\n\n"
                "Recommendation: Manual review recommended where metrics exceed policy thresholds."
            )
        def fallback_answer(parsed: dict, question: str) -> str:
            return "No LLM available. Please configure OPENAI_API_KEY for richer answers."
        return fallback_summary, fallback_answer

def load_reporting_module() -> typing.Optional[typing.Any]:
    """
    Return the app.reporting module if available (so we can call its chart helpers).
    """
    try:
        import app.reporting as reporting  # type: ignore
        return reporting
    except Exception as e:
        print("REPORTING IMPORT ERROR:", e)
        return None

# ---------- improved amortization & metrics ----------
def amortization_schedule(loan_amount: float, annual_rate_decimal: float, term_months: int) -> pd.DataFrame:
    """
    Accurate amortization schedule:
      - annual_rate_decimal expected in decimal (e.g., 0.055 for 5.5%)
      - returns DataFrame with month,payment,interest,principal,balance
    """
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
        # last payment adjust
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
    Improved and consistent metrics:
    - LTV = loan/property_value
    - LTC = loan/total_cost (if provided)
    - Use amortization schedule when rate & term exist to compute monthly payment and total interest
    - DSCR computed as NOI / annual_debt_service (NOI detection/proxy kept)
    - Risk score + category computed with clear thresholds
    """
    lm = {}
    loan = float(parsed.get("loan_amount") or parsed.get("loan") or 0.0)
    prop = parsed.get("property_value") or None
    total_cost = parsed.get("project_cost") or parsed.get("total_cost") or None

    # LTV
    try:
        if prop and float(prop) > 0:
            ltv = loan / float(prop)
        else:
            ltv = None
    except Exception:
        ltv = None
    lm["ltv"] = round(ltv, 4) if isinstance(ltv, (int, float)) else None

    # LTC
    try:
        if total_cost and float(total_cost) > 0:
            ltc = loan / float(total_cost)
        else:
            ltc = None
    except Exception:
        ltc = None
    lm["ltc"] = round(ltc, 4) if isinstance(ltc, (int, float)) else None

    # Try compute amortization if rate & term present
    rate_raw = parsed.get("interest_rate_annual") or parsed.get("interest_rate") or parsed.get("rate")
    term_months = parsed.get("term_months") or parsed.get("term") or None
    amort_df = None
    monthly_payment = parsed.get("monthly_payment")
    total_interest = parsed.get("total_interest")

    # Normalize rate into decimal
    rate_decimal = None
    if rate_raw is not None:
        try:
            r = float(rate_raw)
            if r > 1:  # likely percent like 5.5
                r = r / 100.0
            rate_decimal = r
        except Exception:
            rate_decimal = None

    if (rate_decimal is not None) and term_months:
        try:
            amort_df = amortization_schedule(loan, rate_decimal, int(term_months))
            monthly_payment = float(amort_df["payment"].iloc[0])
            total_interest = float(amort_df["interest"].sum())
        except Exception as e:
            print("Amortization generation failed:", e)
            amort_df = None

    # If amortization not available, try best-effort monthly payment
    if monthly_payment is None:
        # try simple formula if rate_decimal & term_months
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

    # Annual debt service
    if lm.get("monthly_payment"):
        lm["annual_debt_service"] = round(lm["monthly_payment"] * 12.0, 2)
    else:
        lm["annual_debt_service"] = None

    # NOI detection / proxy (same approach but explicit)
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

    # Flags
    policy_flags = parsed.get("policy_flags") or parsed.get("flags") or []
    bank_red_flags = parsed.get("bank_red_flags") or []
    lm["policy_flags"] = policy_flags
    lm["bank_red_flags"] = bank_red_flags

    # Risk scoring: clearer mapping & thresholds
    # Normalize LTV risk (0..1)
    ltv_risk = 0.0
    if lm.get("ltv") is not None:
        ltv_val = lm["ltv"]
        # below 60% -> low, 60-80 medium, 80+ high
        if ltv_val < 0.6:
            ltv_risk = 0.0
        elif ltv_val < 0.8:
            ltv_risk = 0.5
        else:
            ltv_risk = 1.0

    # DSCR risk: lower than 1.0 bad, 1.0-1.25 caution, >1.25 good
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

    # Weighted aggregate
    risk_score = (0.5 * ltv_risk) + (0.35 * dscr_risk) + (0.15 * flags_risk)
    risk_score = min(max(risk_score, 0.0), 1.0)
    lm["risk_score_computed"] = round(risk_score, 3)

    if risk_score >= 0.7:
        category = "High"
    elif risk_score >= 0.4:
        category = "Medium"
    else:
        category = "Low"
    lm["risk_category"] = category

    # Explainable reasons
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

    # Attach amortization frame (small) for reporting use if present
    if amort_df is not None:
        lm["amortization_preview_rows"] = amort_df.head(6).to_dict(orient="records")
        lm["amortization_total_interest"] = round(amort_df["interest"].sum(), 2)
    else:
        lm["amortization_preview_rows"] = None

    parsed["lending_metrics"] = lm
    return lm

# Ensure output directories exist
os.makedirs(os.path.join(ROOT, "output", "generated_pdfs"), exist_ok=True)
os.makedirs(os.path.join(ROOT, "output", "extracted_json"), exist_ok=True)

# Header
st.markdown(
    """
    <div class="bf-header">
      <div style="display:flex; align-items:center; gap:16px;">
        <div style="font-size:28px; font-weight:800; letter-spacing:1px; color: #fff;">
          Bluecroft Finance
        </div>
        <div style="flex:1;">
          <p style="margin:0; color: #eaf6ff;">AI Lending Assistant — professional report & metrics</p>
        </div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Session defaults
defaults = {
    "generated_pdf": None,
    "uploaded_pdf": None,
    "calc_result": None,
    "last_analysis": None,
    "qa_question": "",
    "qa_answer": None,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# Layout: left column (controls), right column (report)
left_col, right_col = st.columns([3, 2])

# LEFT: controls (form, upload, calculator)
with left_col:
    st.markdown('<div class="bf-card">', unsafe_allow_html=True)
    tab_form, tab_upload, tab_calc = st.tabs(["Fill Form (generate PDF)", "Upload PDF", "Quick Calculator"])

    # Form
    with tab_form:
        st.markdown("Fill fields and click Generate PDF to create an application PDF.")
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
                try:
                    with open(generated_path, "rb") as f:
                        st.download_button("Download generated PDF", data=f.read(), file_name=os.path.basename(generated_path), mime="application/pdf")
                except Exception:
                    pass
            except Exception as e:
                st.error("Failed to generate PDF. See logs.")
                print("PDF GENERATION ERROR:", e)

    # Upload
    with tab_upload:
        st.markdown("Upload an existing application or statement PDF for analysis.")
        uploaded = st.file_uploader("Upload application / statement PDF", type=["pdf"], accept_multiple_files=False, key="upload1")
        if uploaded:
            try:
                from app.upload_handler import save_uploaded_file  # type: ignore
                uploaded_path = save_uploaded_file(uploaded)
                st.session_state["uploaded_pdf"] = uploaded_path
                st.success(f"Saved uploaded file to {uploaded_path}")
                try:
                    with open(uploaded_path, "rb") as f:
                        st.download_button("Download uploaded PDF", data=f.read(), file_name=os.path.basename(uploaded_path), mime="application/pdf")
                except Exception:
                    pass
            except Exception as e:
                st.error("Failed to save uploaded file. See logs.")
                print("UPLOAD SAVE ERROR:", e)

    # Calculator
    with tab_calc:
        st.markdown("Quick loan calculator — compute monthly payment and summary.")
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
                st.success("Calculation done — select it in the right pane to analyse.")
            except Exception as e:
                st.error("Calculation failed; see logs.")
                print("CALC ERROR:", e)

    st.markdown('</div>', unsafe_allow_html=True)

# RIGHT: selection, analysis, and professional report visuals
with right_col:
    st.markdown('<div class="bf-card">', unsafe_allow_html=True)
    st.subheader("Selected PDF / Calculation")

    # list generated PDFs
    def list_generated_pdfs():
        out_dir = os.path.join(ROOT, "output", "generated_pdfs")
        os.makedirs(out_dir, exist_ok=True)
        files = sorted(glob.glob(os.path.join(out_dir, "*.pdf")), key=os.path.getmtime, reverse=True)
        return [os.path.basename(f) for f in files]

    gen_list = list_generated_pdfs()
    options = []
    if st.session_state.get("uploaded_pdf"):
        options.append("Uploaded PDF")
    if st.session_state.get("generated_pdf"):
        options.append("Most recent generated PDF")
    if gen_list:
        options.append("Choose from generated files")
    options.append("Use quick calculator result")

    default_index = 0 if options else -1
    choice = st.selectbox("Choose source to inspect / analyse", options=options, index=default_index)

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

    # ANALYSE button
    if st.button("Analyse With AI"):
        generate_summary, answer_question = load_summarizer()
        reporting = load_reporting_module()

        # If calculator selected -> build parsed dict
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
            st.subheader("Underwriter Summary (calculation)")
            st.write(summary_text)

            # Professional report layout
            # Top: KPI cards in a single row
            k1, k2, k3 = st.columns([1,1,1])
            try:
                with k1:
                    st.metric("LTV", f"{metrics.get('ltv'):.0%}" if isinstance(metrics.get('ltv'), float) else metrics.get('ltv') or "N/A")
                with k2:
                    st.metric("DSCR", f"{metrics.get('dscr'):.2f}" if metrics.get('dscr') is not None else "N/A")
                with k3:
                    st.metric("Risk", f"{metrics.get('risk_score_computed', 'N/A'):.0%}" if isinstance(metrics.get('risk_score_computed'), float) else metrics.get('risk_score_computed') or "N/A")
            except Exception:
                pass

            # Middle: two-column balanced layout: left wide amortization & stacked, right charts
            left_wide, right_narrow = st.columns([2,1])
            with left_wide:
                st.markdown("### Amortization & Monthly Breakdown")
                # prefer building amortization schedule if possible
                try:
                    rate_raw = parsed.get("interest_rate_annual")
                    term = parsed.get("term_months")
                    rate = None
                    if rate_raw is not None:
                        rate = float(rate_raw) if float(rate_raw) <= 1 else float(rate_raw) / 100.0
                    if rate is not None and term:
                        df_am = amortization_schedule(parsed.get("loan_amount",0), rate, int(term))
                        # line chart for balance
                        base = alt.Chart(df_am).encode(x=alt.X("month:Q", title="Month"))
                        balance_line = base.mark_line(color="#1f77b4", strokeWidth=2).encode(y=alt.Y("balance:Q", title="Remaining balance (£)"))
                        balance_area = base.mark_area(opacity=0.12, color="#1f77b4").encode(y="balance:Q")
                        st.altair_chart((balance_area + balance_line).properties(height=280), use_container_width=True)
                        # stacked principal vs interest
                        src = df_am.melt(id_vars=["month"], value_vars=["principal","interest"], var_name="component", value_name="amount")
                        stacked = alt.Chart(src).mark_area().encode(
                            x="month:Q",
                            y=alt.Y("amount:Q", title="Amount (£)"),
                            color=alt.Color("component:N", scale=alt.Scale(range=["#2ca02c","#ff7f0e"])),
                            tooltip=["month","component",alt.Tooltip("amount:Q", format=",.2f")]
                        ).properties(height=220)
                        st.altair_chart(stacked, use_container_width=True)
                    else:
                        st.info("Amortization schedule not available: provide interest rate and term to show schedule.")
                except Exception as e:
                    st.warning("Could not render amortization visuals: " + str(e))

            with right_narrow:
                st.markdown("### Payment Composition")
                try:
                    if 'df_am' in locals():
                        total_principal = df_am["principal"].sum()
                        total_interest = df_am["interest"].sum()
                        pie_df = pd.DataFrame([{"part":"Principal","value":total_principal},{"part":"Interest","value":total_interest}])
                        pie = alt.Chart(pie_df).mark_arc(innerRadius=40).encode(
                            theta=alt.Theta("value:Q"),
                            color=alt.Color("part:N", scale=alt.Scale(range=["#2ca02c","#ff7f0e"])),
                            tooltip=["part", alt.Tooltip("value:Q", format=",.2f")]
                        ).properties(height=220)
                        st.altair_chart(pie, use_container_width=True)
                    else:
                        if metrics.get("total_interest") is not None:
                            st.write(f"Estimated total interest: £{metrics.get('total_interest'):,}")
                except Exception:
                    pass

                st.markdown("### Affordability")
                try:
                    income_monthly = parsed.get("income",0)/12.0 if parsed.get("income") else 0
                    payment = metrics.get("monthly_payment") or 0
                    df_aff = pd.DataFrame([{"label":"Monthly payment","value":payment},{"label":"Monthly income","value":income_monthly}])
                    bars = alt.Chart(df_aff).mark_bar().encode(x="label:N", y=alt.Y("value:Q", title="Amount (£)"), color=alt.Color("label:N"))
                    st.altair_chart(bars.properties(height=180), use_container_width=True)
                    if income_monthly:
                        st.write(f"Payment / Income = {(payment / income_monthly):.2f}x")
                except Exception:
                    pass

                st.markdown("### Risk Breakdown")
                try:
                    # simple donut computed from metrics
                    aff_score = max(min(1 - (metrics.get("ltv") or 0), 1.0), 0.0) if metrics.get("ltv") is not None else 0.33
                    ltv_score = metrics.get("ltv") or 0
                    flag_score = 1.0 if metrics.get("policy_flags") or metrics.get("bank_red_flags") else 0.0
                    total = (aff_score + ltv_score + flag_score) or 1.0
                    df_r = pd.DataFrame({"factor":["Affordability","LTV risk","Flags"], "value":[aff_score/total*100, ltv_score/total*100, flag_score/total*100]})
                    donut = alt.Chart(df_r).mark_arc(innerRadius=40).encode(theta=alt.Theta("value:Q"), color=alt.Color("factor:N"))
                    st.altair_chart(donut.properties(height=180), use_container_width=True)
                    st.write("Reasons:", "; ".join(metrics.get("risk_reasons",[])))
                except Exception:
                    pass

            # Download JSON report
            try:
                buf = io.BytesIO()
                payload = {"parsed": parsed, "lending_metrics": metrics, "summary": summary_text}
                buf.write(json.dumps(payload, indent=2).encode("utf-8"))
                buf.seek(0)
                st.download_button("Download report (JSON)", data=buf, file_name="calculation_report.json", mime="application/json")
            except Exception:
                pass

            # If reporting module with richer visuals exists, render it below (non-blocking)
            reporting = load_reporting_module()
            if reporting:
                try:
                    # reporting.render_full_report may duplicate some visuals — it will render below
                    reporting.render_full_report(parsed, metrics)
                except Exception as e:
                    print("REPORTING.render_full_report error:", e)

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

                        st.subheader("Extracted / Analysis JSON")
                        st.json(result)

                        # Summary
                        generate_summary, _ = load_summarizer()
                        try:
                            summary_text = generate_summary(result)
                        except Exception as e:
                            summary_text = f"LLM_ERROR: {e}"
                        st.subheader("Underwriter Summary")
                        st.write(summary_text)

                        # KPI row
                        k1, k2, k3 = st.columns([1,1,1])
                        with k1:
                            st.metric("LTV", f"{metrics.get('ltv'):.0%}" if isinstance(metrics.get('ltv'), float) else metrics.get('ltv') or "N/A")
                        with k2:
                            st.metric("DSCR", f"{metrics.get('dscr'):.2f}" if metrics.get('dscr') is not None else "N/A")
                        with k3:
                            st.metric("Risk", f"{metrics.get('risk_score_computed', 'N/A'):.0%}" if isinstance(metrics.get('risk_score_computed'), float) else metrics.get('risk_score_computed') or "N/A")

                        # Balanced middle layout (amortization + charts)
                        left_wide, right_narrow = st.columns([2,1])
                        with left_wide:
                            st.markdown("### Amortization & Monthly Breakdown")
                            try:
                                rate_raw = result.get("interest_rate_annual")
                                term = result.get("term_months")
                                rate = None
                                if rate_raw is not None:
                                    rate = float(rate_raw) if float(rate_raw) <= 1 else float(rate_raw) / 100.0
                                if rate is not None and term:
                                    df_am = amortization_schedule(result.get("loan_amount",0), rate, int(term))
                                    base = alt.Chart(df_am).encode(x=alt.X("month:Q", title="Month"))
                                    balance_line = base.mark_line(color="#1f77b4", strokeWidth=2).encode(y=alt.Y("balance:Q", title="Remaining balance (£)"))
                                    balance_area = base.mark_area(opacity=0.12, color="#1f77b4").encode(y="balance:Q")
                                    st.altair_chart((balance_area + balance_line).properties(height=280), use_container_width=True)
                                    src = df_am.melt(id_vars=["month"], value_vars=["principal","interest"], var_name="component", value_name="amount")
                                    stacked = alt.Chart(src).mark_area().encode(x="month:Q", y=alt.Y("amount:Q", title="Amount (£)"), color=alt.Color("component:N"))
                                    st.altair_chart(stacked.properties(height=220), use_container_width=True)
                                else:
                                    st.info("Amortization schedule not available.")
                            except Exception as e:
                                st.warning("Amortization visuals unavailable: " + str(e))

                        with right_narrow:
                            st.markdown("### Payment Composition")
                            try:
                                if 'df_am' in locals():
                                    pie_df = pd.DataFrame([{"part":"Principal","value":df_am["principal"].sum()},{"part":"Interest","value":df_am["interest"].sum()}])
                                    pie = alt.Chart(pie_df).mark_arc(innerRadius=40).encode(theta=alt.Theta("value:Q"), color=alt.Color("part:N"))
                                    st.altair_chart(pie.properties(height=220), use_container_width=True)
                            except Exception:
                                pass

                            st.markdown("### Affordability")
                            try:
                                income_monthly = result.get("income",0)/12.0 if result.get("income") else 0
                                payment = metrics.get("monthly_payment") or 0
                                df_aff = pd.DataFrame([{"label":"Monthly payment","value":payment},{"label":"Monthly income","value":income_monthly}])
                                bars = alt.Chart(df_aff).mark_bar().encode(x="label:N", y=alt.Y("value:Q", title="Amount (£)"), color=alt.Color("label:N"))
                                st.altair_chart(bars.properties(height=180), use_container_width=True)
                                if income_monthly:
                                    st.write(f"Payment / Income = {(payment / income_monthly):.2f}x")
                            except Exception:
                                pass

                            st.markdown("### Risk Breakdown")
                            try:
                                aff_score = max(min(1 - (metrics.get("ltv") or 0), 1.0), 0.0) if metrics.get("ltv") is not None else 0.33
                                ltv_score = metrics.get("ltv") or 0
                                flag_score = 1.0 if metrics.get("policy_flags") or metrics.get("bank_red_flags") else 0.0
                                total = (aff_score + ltv_score + flag_score) or 1.0
                                df_r = pd.DataFrame({"factor":["Affordability","LTV risk","Flags"], "value":[aff_score/total*100, ltv_score/total*100, flag_score/total*100]})
                                donut = alt.Chart(df_r).mark_arc(innerRadius=40).encode(theta=alt.Theta("value:Q"), color=alt.Color("factor:N"))
                                st.altair_chart(donut.properties(height=180), use_container_width=True)
                                st.write("Reasons:", "; ".join(metrics.get("risk_reasons",[])))
                            except Exception:
                                pass

                        # render additional reporting visuals if module available
                        reporting = load_reporting_module()
                        if reporting:
                            try:
                                reporting.render_full_report(result, metrics)
                            except Exception as e:
                                print("REPORTING.render_full_report error:", e)

                    except Exception as e:
                        st.error("Pipeline failed during processing. See logs.")
                        print("PIPELINE RUN ERROR:", e)
        else:
            st.error("No PDF or calculation available to analyse.")

    # Persistent Q&A
    st.markdown("---")
    st.subheader("Ask a question about this application")
    st.text_input("Enter natural language question", key="qa_question")
    if st.button("Ask"):
        question = st.session_state.get("qa_question","").strip()
        if not question:
            st.warning("Please enter a question.")
        else:
            parsed = st.session_state.get("last_analysis")
            if not parsed:
                st.error("No analysis available. Run 'Analyse With AI' first.")
            else:
                # Deterministic first for common queries for explainability
                q = question.lower()
                metrics = parsed.get("lending_metrics") or compute_lending_metrics(parsed)
                if ("why" in q and ("flag" in q or "risk" in q)):
                    st.session_state["qa_answer"] = "Reasons: " + "; ".join(metrics.get("risk_reasons",[]))
                elif ("summar" in q) or ("financial position" in q):
                    gen, _ = load_summarizer()
                    try:
                        st.session_state["qa_answer"] = gen(parsed)
                    except Exception:
                        st.session_state["qa_answer"] = f"Borrower: {parsed.get('borrower','Unknown')}. Income: £{parsed.get('income','N/A')}. LTV: {metrics.get('ltv','N/A')}."
                elif ("bridge" in q or "bridg" in q) and ("suit" in q or "suitable" in q):
                    term_ok = parsed.get("term_months") is not None and parsed.get("term_months") <= 24
                    ltv_ok = metrics.get("ltv") is not None and metrics.get("ltv") <= 0.75
                    dscr_ok = metrics.get("dscr") is None or metrics.get("dscr") >= 1.0
                    ok = term_ok and ltv_ok and dscr_ok
                    reasons = []
                    if not term_ok: reasons.append(f"term months = {parsed.get('term_months')}")
                    if not ltv_ok: reasons.append(f"ltv = {metrics.get('ltv')}")
                    if not dscr_ok: reasons.append(f"dscr = {metrics.get('dscr')}")
                    st.session_state["qa_answer"] = "Suitable for typical bridging: " + ("Yes" if ok else "No") + ("" if ok else f". Issues: {', '.join(reasons)}")
                else:
                    proc_pdf, proc_data = load_pipeline()
                    if proc_data:
                        try:
                            st.session_state["qa_answer"] = proc_data(parsed, ask=question)
                        except Exception as e:
                            print("Q&A pipeline error:", e)
                            _, answer_q = load_summarizer()
                            try:
                                st.session_state["qa_answer"] = answer_q(parsed, question)
                            except Exception as e2:
                                st.session_state["qa_answer"] = f"LLM_ERROR: {e2}"
                    else:
                        _, answer_q = load_summarizer()
                        try:
                            st.session_state["qa_answer"] = answer_q(parsed, question)
                        except Exception as e:
                            st.session_state["qa_answer"] = f"LLM_ERROR: {e}"

    if st.session_state.get("qa_answer"):
        st.markdown("**Answer:**")
        st.write(st.session_state.get("qa_answer"))

    st.markdown('</div>', unsafe_allow_html=True)
