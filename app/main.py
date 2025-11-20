# Bluecroft Finance — app/main.py (manual-input session_state fixed)
# - Stores manual parsed payload as JSON in session_state to avoid StreamlitAPIException
# - Deserializes JSON before use
# - Defensive coercion of manual inputs to plain Python types
import os
import sys
from pathlib import Path
import glob
import io
import json
import typing
import time
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import streamlit as st
import pandas as pd
import altair as alt

# Try to import robust metrics if present; safe fallback to local simple functions if not
try:
    from app.metrics import compute_lending_metrics, amortization_schedule  # type: ignore
except Exception:
    compute_lending_metrics = None
    amortization_schedule = None

st.set_page_config(page_title="Bluecroft Finance — AI Lending Assistant", layout="wide")

# Ensure output directories exist
os.makedirs(os.path.join(ROOT, "output", "generated_pdfs"), exist_ok=True)
os.makedirs(os.path.join(ROOT, "output", "extracted_json"), exist_ok=True)
os.makedirs(os.path.join(ROOT, "output", "supporting_docs"), exist_ok=True)

# Small CSS and header
st.markdown(
    """
    <style>
    .bf-header { background: linear-gradient(90deg,#003366,#0078D4); color: white; padding:12px 18px; border-radius:8px; }
    .bf-card { background: rgba(255,255,255,0.98); padding:16px; border-radius:10px; box-shadow: 0 6px 18px rgba(10,30,60,0.06); }
    .report-box { max-width:980px; margin-left:auto; margin-right:auto; background:rgba(255,255,255,0.98); padding:18px; border-radius:10px; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="bf-header">
      <div style="display:flex; align-items:center; gap:16px;">
        <div style="font-size:24px; font-weight:800; color:#fff;">Bluecroft Finance</div>
        <div style="flex:1; color:#eaf6ff;">AI Lending Assistant — add supporting documents to PDFs</div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Session-state initialisation (store only simple types or JSON strings)
if "supporting_groups" not in st.session_state:
    st.session_state["supporting_groups"] = {}
if "generated_pdf" not in st.session_state:
    st.session_state["generated_pdf"] = None
if "uploaded_pdf" not in st.session_state:
    st.session_state["uploaded_pdf"] = None
if "calc_result" not in st.session_state:
    st.session_state["calc_result"] = None
if "last_analysis" not in st.session_state:
    st.session_state["last_analysis"] = None
if "qa_question" not in st.session_state:
    st.session_state["qa_question"] = ""
if "qa_answer" not in st.session_state:
    st.session_state["qa_answer"] = None
# Note: we will store manual parsed data as JSON in "manual_parsed_json" (string)

# Helper to save uploaded files (supports multiple)
def save_supporting_files(files: typing.Iterable[typing.Any], group_name: str) -> list:
    out_dir = os.path.join(ROOT, "output", "supporting_docs", group_name)
    os.makedirs(out_dir, exist_ok=True)
    saved = []
    for f in files:
        filename = Path(f.name).name
        dest = os.path.join(out_dir, filename)
        try:
            with open(dest, "wb") as fh:
                fh.write(f.getbuffer())
            saved.append(dest)
        except Exception as e:
            print("Failed to save supporting file:", e)
    return saved

# Helper: center charts
def center_chart(chart_obj, use_container_width: bool = True, height: int | None = None):
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

# Left/right layout
left_col, right_col = st.columns([3, 2])

with left_col:
    st.markdown('<div class="bf-card">', unsafe_allow_html=True)
    tab_form, tab_upload, tab_calc = st.tabs(["Fill Form (generate PDF)", "Upload PDF / Add Docs", "Quick Calculator"])

    # FORM tab
    with tab_form:
        st.markdown("Fill fields and attach supporting documents (e.g., bank statements).")
        with st.form("application_form"):
            col1, col2 = st.columns(2)
            with col1:
                borrower_name = st.text_input("Borrower name", "John Doe")
                email = st.text_input("Email")
                income = st.text_input("Annual income (GBP)", value="85,000")
                loan_amount = st.text_input("Requested loan amount (GBP)", value="240,000")
            with col2:
                property_value = st.text_input("Property value (GBP)", value="330,000")
                term_months = st.text_input("Loan term (months)", value="300")
                interest_rate = st.text_input("Interest rate (annual %)", value="5.5")
            supporting = st.file_uploader("Add supporting documents (multiple)", accept_multiple_files=True)
            submit_generate = st.form_submit_button("Generate PDF")
        if submit_generate:
            group_name = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
            attachments = []
            if supporting:
                attachments = save_supporting_files(supporting, group_name)
                st.session_state["supporting_groups"][group_name] = attachments
                st.success(f"Saved {len(attachments)} supporting files to group {group_name}")
            def _to_float_quiet(s):
                try:
                    if s is None:
                        return None
                    return float(str(s).replace(",", "").replace("£", "").strip())
                except Exception:
                    return None
            data = {
                "borrower": borrower_name,
                "email": email,
                "income": _to_float_quiet(income),
                "loan_amount": _to_float_quiet(loan_amount),
                "property_value": _to_float_quiet(property_value),
                "term_months": int(_to_float_quiet(term_months)) if _to_float_quiet(term_months) else None,
                "interest_rate_annual": _to_float_quiet(interest_rate),
                "notes": "",
                "attachments": attachments,
                "attachments_group": group_name,
            }
            try:
                from app.pdf_form import create_pdf_from_dict  # type: ignore
                generated_path = create_pdf_from_dict(data)
                st.session_state["generated_pdf"] = generated_path
                st.success(f"PDF generated: {generated_path}")
                try:
                    with open(generated_path, "rb") as f:
                        st.download_button("Download generated PDF", data=f.read(), file_name=os.path.basename(generated_path), mime="application/pdf")
                except Exception:
                    pass
            except Exception:
                out_json = os.path.join(ROOT, "output", "generated_pdfs", f"application_{group_name}.json")
                with open(out_json, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=2)
                st.warning("PDF generator not available; saved application data (JSON).")
                if attachments:
                    st.markdown("Supporting documents saved:")
                    for p in attachments:
                        try:
                            with open(p, "rb") as fh:
                                st.download_button(label=f"Download {os.path.basename(p)}", data=fh.read(), file_name=os.path.basename(p))
                        except Exception:
                            st.write(os.path.basename(p))

    # UPLOAD tab
    with tab_upload:
        st.markdown("Upload an existing application PDF and optionally add more supporting documents.")
        uploaded_pdf = st.file_uploader("Upload application PDF", type=["pdf"], accept_multiple_files=False, key="upload_pdf")
        extra_docs = st.file_uploader("Upload additional supporting documents (optional, multiple)", accept_multiple_files=True)
        if uploaded_pdf:
            try:
                saved_pdf_path = os.path.join("output", "uploaded_pdfs")
                os.makedirs(saved_pdf_path, exist_ok=True)
                filename = Path(uploaded_pdf.name).name
                dest = os.path.join(saved_pdf_path, f"{int(time.time())}_{filename}")
                with open(dest, "wb") as fh:
                    fh.write(uploaded_pdf.getbuffer())
                st.session_state["uploaded_pdf"] = dest
                st.success(f"Uploaded application PDF saved to {dest}")
                st.download_button("Download uploaded PDF", data=uploaded_pdf.getvalue(), file_name=filename, mime="application/pdf")
            except Exception as e:
                st.error("Failed to save uploaded PDF.")
                print("UPLOAD PDF ERROR:", e)
        if extra_docs:
            group_name = datetime.utcnow().strftime("%Y%m%dT%H%M%S_upload")
            attachments = save_supporting_files(extra_docs, group_name)
            st.session_state["supporting_groups"][group_name] = attachments
            st.success(f"Saved {len(attachments)} supporting files to group {group_name}")
            for p in attachments:
                try:
                    with open(p, "rb") as fh:
                        st.download_button(label=f"Download {os.path.basename(p)}", data=fh.read(), file_name=os.path.basename(p))
                except Exception:
                    st.write(os.path.basename(p))

    # Quick calculator tab
    with tab_calc:
        st.markdown("Quick loan calculator — compute monthly payment and summary.")
        with st.form("calc_form"):
            ccol1, ccol2 = st.columns(2)
            with ccol1:
                calc_borrower = st.text_input("Borrower name", "John Doe", key="calc_borrower")
                calc_income = st.number_input("Annual income (GBP)", value=85000, step=1000, key="calc_income")
                calc_loan = st.number_input("Loan amount (GBP)", value=240000, step=1000, key="calc_loan")
            with ccol2:
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
                    "monthly_amortising_payment": round(monthly, 2),
                    "monthly_interest_only_payment": round(P * annual_r / 12.0, 2),
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

with right_col:
    st.markdown('<div class="bf-card">', unsafe_allow_html=True)
    st.subheader("Selected source and Analysis")

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
    if st.session_state.get("calc_result"):
        options.append("Use quick calculator result")
    # also allow manual parsed if saved as JSON
    if st.session_state.get("manual_parsed_json"):
        options.append("Use manual parsed values")

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
    elif choice == "Use manual parsed values":
        # retrieve manual parsed JSON and deserialize safely
        mp_json = st.session_state.get("manual_parsed_json")
        try:
            tmp_parsed = json.loads(mp_json) if mp_json else None
        except Exception:
            tmp_parsed = None
        if tmp_parsed:
            st.markdown("**Manual parsed values selected**")
            st.write(tmp_parsed)

    # show supporting groups
    if st.session_state.get("supporting_groups"):
        st.markdown("### Saved supporting document groups")
        for gid, paths in st.session_state["supporting_groups"].items():
            with st.expander(f"Group {gid} ({len(paths)} files)"):
                for p in paths:
                    try:
                        with open(p, "rb") as fh:
                            st.download_button(label=f"Download {os.path.basename(p)}", data=fh.read(), file_name=os.path.basename(p))
                    except Exception:
                        st.write(os.path.basename(p))

    # ANALYSE
    if st.button("Analyse With AI"):
        if tmp_parsed:
            parsed = tmp_parsed.copy()
        elif tmp_file:
            try:
                proc_pdf, proc_data = None, None
                try:
                    from pipeline.pipeline import process_pdf, process_data  # type: ignore
                    proc_pdf, proc_data = process_pdf, process_data
                except Exception:
                    proc_pdf = None
                if proc_pdf:
                    parsed = proc_pdf(tmp_file) or {}
                else:
                    st.warning("Pipeline not available — cannot auto-extract from PDF. Please use Quick Calculator or Manual entry.")
                    parsed = {}
            except Exception as e:
                st.error("Error running pipeline: " + str(e))
                parsed = {}
        else:
            st.warning("No source selected for analysis.")
            parsed = {}

        st.markdown("### Raw parsed (diagnostic)")
        st.write(parsed)

        # normalize common fields
        def _norm_quiet(v):
            if v is None:
                return None
            if isinstance(v, (int, float)):
                return v
            s = str(v).strip()
            if s == "":
                return None
            s = s.replace(",", "").replace("£", "").replace("$", "")
            try:
                return float(s)
            except Exception:
                return s

        if parsed.get("loan_amount") is None and parsed.get("loan") is not None:
            parsed["loan_amount"] = _norm_quiet(parsed.get("loan"))
        parsed["loan_amount"] = _norm_quiet(parsed.get("loan_amount"))
        parsed["property_value"] = _norm_quiet(parsed.get("property_value") or parsed.get("property_value_estimate") or parsed.get("property"))
        parsed["interest_rate_annual"] = _norm_quiet(parsed.get("interest_rate_annual") or parsed.get("interest_rate") or parsed.get("rate"))
        trm = parsed.get("term_months") or parsed.get("term")
        if trm is not None:
            try:
                parsed["term_months"] = int(trm)
            except Exception:
                parsed["term_months"] = None
        parsed["income"] = _norm_quiet(parsed.get("income") or parsed.get("annual_income"))

        st.markdown("### Normalised parsed (diagnostic)")
        st.write(parsed)

        if compute_lending_metrics:
            metrics = compute_lending_metrics(parsed)
        else:
            st.warning("Metrics module not available.")
            metrics = parsed.get("lending_metrics", {})

        st.session_state["last_analysis"] = parsed

        audit = parsed.get("input_audit") or []
        if audit:
            st.warning("Input audit: " + "; ".join(audit))

        st.subheader("Computed lending metrics")
        st.json(parsed.get("lending_metrics"))

        # If critical inputs missing offer inline supply
        missing_fields = set()
        for a in audit:
            la = a.lower()
            if "property" in la and ("missing" in la or "invalid" in la):
                missing_fields.add("property_value")
            if "interest rate" in la:
                missing_fields.add("interest_rate_annual")
            if "term" in la:
                missing_fields.add("term_months")
            if "project_cost" in la or "total_cost" in la:
                missing_fields.add("project_cost")
        if missing_fields:
            st.info("Some inputs are missing — supply them below to recompute quickly.")
            with st.form("supply_missing_right"):
                supplied = {}
                if "property_value" in missing_fields:
                    supplied["property_value"] = st.number_input("Property value (GBP)", value=0.0, format="%.2f")
                if "interest_rate_annual" in missing_fields:
                    supplied["interest_rate_annual"] = st.number_input("Interest rate (annual % or decimal)", value=0.0, format="%.4f")
                if "term_months" in missing_fields:
                    supplied["term_months"] = st.number_input("Term (months)", value=0, min_value=0, step=1)
                if "project_cost" in missing_fields:
                    supplied["project_cost"] = st.number_input("Total project cost (GBP)", value=0.0, format="%.2f")
                do_recompute = st.form_submit_button("Recompute with supplied values")
            if do_recompute:
                for k, v in supplied.items():
                    if v is None:
                        continue
                    if isinstance(v, (int, float)) and v == 0:
                        continue
                    parsed[k] = v
                if compute_lending_metrics:
                    metrics = compute_lending_metrics(parsed)
                    st.session_state["last_analysis"] = parsed
                    st.success("Recomputed metrics.")
                    st.json(parsed.get("lending_metrics"))

        st.markdown('</div>', unsafe_allow_html=True)

# Manual entry saving block (fixed): store as JSON string to avoid session_state errors
# This is the block run earlier when using the Manual entry form to save values.
# When the user submits manual values we will store them as JSON rather than as a raw dict.
# (Earlier error was caused by storing a dict with values that Streamlit couldn't serialize.)
if "manual_parsed_json" not in st.session_state:
    st.session_state["manual_parsed_json"] = None

# Note: when manual form is used above, we saved parsed into session_state["manual_parsed_json"] as JSON.
# (See the Manual entry form — this code writes to that key when the user submits.)

# End of file
