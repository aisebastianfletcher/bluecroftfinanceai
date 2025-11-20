import math
import io
from pathlib import Path
from typing import Dict, Any, Optional

import pandas as pd
import altair as alt
import streamlit as st


def amortization_schedule(loan_amount: float, annual_rate: float, term_months: int) -> pd.DataFrame:
    """
    Returns a DataFrame with columns:
      month (1..n), payment, interest, principal, balance
    annual_rate is decimal (e.g., 0.055)
    """
    if term_months <= 0:
        raise ValueError("term_months must be > 0")
    P = float(loan_amount)
    r = float(annual_rate) / 12.0 if annual_rate is not None else 0.0
    n = int(term_months)
    if r == 0:
        payment = P / n
    else:
        payment = P * r / (1 - (1 + r) ** (-n))
    rows = []
    balance = P
    for m in range(1, n + 1):
        interest = balance * r
        principal = payment - interest
        # guard final payment rounding
        if m == n:
            principal = balance
            payment = interest + principal
            balance = 0.0
        else:
            balance = balance - principal
        rows.append({"month": m, "payment": round(payment, 2), "interest": round(interest, 2),
                     "principal": round(principal, 2), "balance": round(balance, 2)})
    df = pd.DataFrame(rows)
    return df


def chart_amortization_balance(df: pd.DataFrame, width=600, height=320):
    """
    Line/area chart showing remaining balance over time.
    """
    base = alt.Chart(df).encode(x=alt.X("month:Q", title="Month"))
    balance_line = base.mark_line(color="#1f77b4", strokeWidth=2).encode(y=alt.Y("balance:Q", title="Remaining balance (£)"))
    balance_area = base.mark_area(opacity=0.12, color="#1f77b4").encode(y="balance:Q")
    return (balance_area + balance_line).properties(width=width, height=height)


def chart_principal_interest_pie(df: pd.DataFrame, width=300, height=300):
    """
    Pie chart (donut) summarising total principal vs total interest paid over the life of the loan.
    """
    total_principal = df["principal"].sum()
    total_interest = df["interest"].sum()
    data = pd.DataFrame([
        {"part": "Principal", "value": total_principal},
        {"part": "Interest", "value": total_interest},
    ])
    chart = alt.Chart(data).mark_arc(innerRadius=40).encode(
        theta=alt.Theta("value:Q"),
        color=alt.Color("part:N", scale=alt.Scale(range=["#2ca02c", "#ff7f0e"])),
        tooltip=["part", alt.Tooltip("value:Q", format=",.2f")]
    ).properties(width=width, height=height)
    return chart


def chart_monthly_principal_interest(df: pd.DataFrame, width=600, height=320):
    """
    Stacked area chart showing principal vs interest component of monthly payments over time.
    """
    src = df.melt(id_vars=["month"], value_vars=["principal", "interest"], var_name="component", value_name="amount")
    chart = alt.Chart(src).mark_area().encode(
        x=alt.X("month:Q", title="Month"),
        y=alt.Y("amount:Q", title="Amount (£)"),
        color=alt.Color("component:N", scale=alt.Scale(range=["#2ca02c", "#ff7f0e"])),
        tooltip=["month", "component", alt.Tooltip("amount:Q", format=",.2f")]
    ).properties(width=width, height=height)
    return chart


def chart_affordability(parsed: Dict[str, Any], width=480, height=240):
    """
    Bar chart comparing monthly payment to monthly income and showing a ratio indicator.
    """
    monthly = parsed.get("monthly_payment", None) or parsed.get("monthly", None) or 0.0
    income = parsed.get("income", None) or 0.0
    income_monthly = income / 12.0 if income else 0.0
    ratio = (monthly / income_monthly) if income_monthly else None

    data = pd.DataFrame([
        {"label": "Monthly payment", "value": monthly},
        {"label": "Monthly income (available)", "value": income_monthly},
    ])
    bars = alt.Chart(data).mark_bar().encode(
        x=alt.X("label:N", title=""),
        y=alt.Y("value:Q", title="Amount (£)"),
        color=alt.Color("label:N", scale=alt.Scale(range=["#1f77b4", "#2ca02c"]))
    ).properties(width=width, height=height)

    # Add text for ratio if available
    if ratio is not None:
        ratio_text = f"Payment / Income = {ratio:.2f}x"
        bars = (bars & alt.Chart(pd.DataFrame({"text": [ratio_text]})).mark_text(
            align="left", baseline="middle", dx=10).encode(text="text:N").properties(width=width, height=30))
    return bars


def chart_risk_donut(lending_metrics: Dict[str, Any], width=300, height=300):
    """
    Donut chart showing risk composition (affordability vs ltv vs flags) by normalized scores.
    """
    aff_score = lending_metrics.get("_aff_score", None)
    ltv_score = lending_metrics.get("_ltv_score", None)
    flags_score = lending_metrics.get("_flags_score", None)

    # If internal scores not present, fall back to computed components
    if aff_score is None or ltv_score is None or flags_score is None:
        # create fallback distribution
        aff_score = 1 - (lending_metrics.get("ltv", 0) or 0)
        ltv_score = lending_metrics.get("ltv", 0) or 0
        flags_score = 1.0 if lending_metrics.get("policy_flags") or lending_metrics.get("bank_red_flags") else 0.0

    total = (aff_score + ltv_score + flags_score) or 1.0
    data = pd.DataFrame({
        "factor": ["Affordability", "LTV risk", "Flags"],
        "value": [aff_score / total * 100, ltv_score / total * 100, flags_score / total * 100]
    })
    chart = alt.Chart(data).mark_arc(innerRadius=50).encode(
        theta=alt.Theta("value:Q"),
        color=alt.Color("factor:N", scale=alt.Scale(range=["#1f77b4", "#ff7f0e", "#d62728"])),
        tooltip=["factor", alt.Tooltip("value:Q", format=".1f")]
    ).properties(width=width, height=height)
    return chart


def kpi_cards(metrics: Dict[str, Any]):
    """
    Display KPI metric cards (big numbers) using st.columns and st.metric.
    """
    kpi_cols = st.columns(3)
    try:
        ltv = metrics.get("ltv")
        dscr = metrics.get("dscr")
        risk = metrics.get("risk_score_computed")
    except Exception:
        ltv = dscr = risk = None

    with kpi_cols[0]:
        st.metric(label="LTV", value=f"{ltv:.0%}" if isinstance(ltv, float) else (ltv or "N/A"))
    with kpi_cols[1]:
        st.metric(label="DSCR", value=f"{dscr:.2f}" if dscr is not None else "N/A")
    with kpi_cols[2]:
        # present risk score as percent and category
        cat = metrics.get("risk_category", "N/A")
        score_str = f"{metrics.get('risk_score_computed', 'N/A'):.0%}" if isinstance(metrics.get("risk_score_computed"), float) else (metrics.get("risk_score_computed") or "N/A")
        st.metric(label=f"Risk ({cat})", value=score_str)


def render_full_report(parsed: Dict[str, Any], lending_metrics: Dict[str, Any]):
    """
    Render a full professional report section in Streamlit based on parsed data and lending_metrics.
    Call this after compute_lending_metrics(parsed) in your main app flow.
    """
    st.markdown("## Professional Report")
    # KPI cards
    kpi_cards(lending_metrics)

    # Left: amortization + monthly breakdown; Right: pie + affordability + risk chart
    col1, col2 = st.columns([2, 1])

    # Amortization chart and monthly stacked component
    with col1:
        st.markdown("### Amortization & Payment Schedule")
        loan_amount = parsed.get("loan_amount", 0) or 0
        term_months = parsed.get("term_months") or lending_metrics.get("term_months") or 360
        rate = parsed.get("interest_rate_annual") or parsed.get("interest_rate") or lending_metrics.get("interest_rate_annual") or 0.0
        # ensure decimal form for annual rate
        if isinstance(rate, (int, float)) and rate > 1:
            # user may have entered a percent e.g., 5.5 -> convert to 0.055
            rate = float(rate) / 100.0
        try:
            df_am = amortization_schedule(loan_amount, rate or 0.0, int(term_months))
            st.altair_chart(chart_amortization_balance(df_am), use_container_width=True)
            st.altair_chart(chart_monthly_principal_interest(df_am), use_container_width=True)
        except Exception as e:
            st.warning("Could not build amortization schedule: " + str(e))
            # still attempt to show monthly payment if present
            if parsed.get("monthly_payment"):
                st.write(f"Monthly payment: £{parsed.get('monthly_payment'):,}")

    with col2:
        st.markdown("### Payment Composition")
        try:
            st.altair_chart(chart_principal_interest_pie(df_am), use_container_width=True)
        except Exception:
            st.info("Principal/Interest chart not available (amortization data missing).")

        st.markdown("### Affordability")
        try:
            st.altair_chart(chart_affordability(parsed), use_container_width=True)
        except Exception:
            st.info("Affordability chart not available.")

        st.markdown("### Risk Breakdown")
        try:
            st.altair_chart(chart_risk_donut(lending_metrics), use_container_width=True)
            # show explainability reasons
            reasons = lending_metrics.get("risk_reasons", [])
            st.write("Reasons:", "; ".join(reasons))
        except Exception:
            st.info("Risk chart not available.")

    # Full metrics table
    st.markdown("### Lending Metrics (detailed)")
    try:
        rows = []
        for k, v in lending_metrics.items():
            if isinstance(v, (dict, list)):
                continue
            rows.append({"metric": k, "value": v})
        dfm = pd.DataFrame(rows)
        st.table(dfm)
    except Exception:
        st.info("Detailed metrics not available.")

    # Download JSON report (parsed + metrics)
    try:
        buf = io.BytesIO()
        payload = {"parsed": parsed, "lending_metrics": lending_metrics}
        buf.write(io.BytesIO(str(payload).encode("utf-8")).getvalue())
        buf.seek(0)
        st.download_button("Download full report (JSON)", data=buf, file_name="underwriting_report.json", mime="application/json")
    except Exception:
        pass
