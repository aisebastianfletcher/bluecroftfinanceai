# app/pdf_form.py
# Generate a parser-friendly PDF with an exact machine-readable JSON block and a human summary.
from __future__ import annotations
import json
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Preformatted

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "output" / "generated_pdfs"
OUT_DIR.mkdir(parents=True, exist_ok=True)

def _ensure_required_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(data or {})
    aliases = {
        "project_cost": ["project_cost", "total_project_cost", "total cost", "total_cost"],
        "total_cost": ["total_cost", "total project cost", "project_cost"],
        "interest_rate_annual": ["interest_rate_annual", "interest rate (annual)", "interest_rate", "rate"],
        "loan_term_months": ["loan_term_months", "loan term months", "term_months", "term"]
    }
    for req_key, keys in aliases.items():
        if req_key not in normalized or normalized.get(req_key) is None:
            for k in keys:
                if k in normalized and normalized.get(k) not in (None, ""):
                    normalized[req_key] = normalized[k]
                    break
    if "term_months" not in normalized:
        normalized["term_months"] = normalized.get("loan_term_months")
    defaults = {
        "project_cost": 260000,
        "total_cost": 260000,
        "interest_rate_annual": 9.5,
        "loan_term_months": 12,
    }
    for k, d in defaults.items():
        if normalized.get(k) in (None, ""):
            normalized[k] = d
    return normalized

def _build_machine_block(data: Dict[str, Any]) -> str:
    machine = {
        "project_cost": data.get("project_cost"),
        "total_cost": data.get("total_cost"),
        "interest_rate_annual": data.get("interest_rate_annual"),
        "loan_term_months": int(data.get("loan_term_months")) if data.get("loan_term_months") is not None else None,
        "borrower": data.get("borrower"),
        "income": data.get("income"),
        "loan_amount": data.get("loan_amount"),
        "property_value": data.get("property_value"),
        "arv": data.get("arv"),
        "purchase_price": data.get("purchase_price"),
        "refurbishment_budget": data.get("refurbishment_budget"),
        "dscr": data.get("dscr"),
        "monthly_rent": data.get("monthly_rent"),
        "operating_costs": data.get("operating_costs"),
        "term_months": int(data.get("term_months")) if data.get("term_months") is not None else data.get("loan_term_months"),
    }
    machine_clean = {k: v for k, v in machine.items() if v is not None}
    return json.dumps(machine_clean, indent=2)

def create_pdf_from_dict(data: Dict[str, Any], filename: Optional[str] = None) -> str:
    d = _ensure_required_fields(data)
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    fn = filename or f"application_{ts}.pdf"
    out_path = OUT_DIR / fn
    doc = SimpleDocTemplate(str(out_path), pagesize=A4,
                            leftMargin=20*mm, rightMargin=20*mm, topMargin=20*mm, bottomMargin=20*mm)
    styles = getSampleStyleSheet()
    body_style = styles["BodyText"]
    title_style = styles["Title"]
    mono_style = ParagraphStyle(
        "monospace",
        parent=styles["Code"],
        fontName="Courier",
        fontSize=8,
        leading=10,
        leftIndent=0,
        rightIndent=0
    )
    elements = []
    elements.append(Paragraph("Application (machine-readable + human summary)", title_style))
    elements.append(Spacer(1, 6))
    elements.append(Paragraph("<b>MACHINE-READABLE BLOCK (exact keys)</b>", body_style))
    elements.append(Spacer(1, 4))
    machine_json = _build_machine_block(d)
    elements.append(Preformatted(machine_json, mono_style))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph("<b>Human-readable summary</b>", body_style))
    elements.append(Spacer(1, 6))
    display_keys = [
        ("Borrower", "borrower"),
        ("Income (GBP)", "income"),
        ("Loan amount (GBP)", "loan_amount"),
        ("Property value (GBP)", "property_value"),
        ("Project cost (GBP)", "project_cost"),
        ("Total cost (GBP)", "total_cost"),
        ("Interest rate (annual)", "interest_rate_annual"),
        ("Loan term (months)", "loan_term_months"),
        ("Term months (alias)", "term_months"),
        ("ARV", "arv"),
        ("Purchase price", "purchase_price"),
        ("Refurbishment budget", "refurbishment_budget"),
        ("DSCR (if provided)", "dscr"),
        ("Monthly rent", "monthly_rent"),
        ("Operating costs", "operating_costs"),
    ]
    table_data = []
    for label, key in display_keys:
        val = d.get(key)
        if val is None:
            continue
        if isinstance(val, float):
            if abs(val) >= 1000:
                val_str = f"£{val:,.2f}"
            else:
                val_str = f"{val:.2f}"
        elif isinstance(val, int):
            if abs(val) >= 1000:
                val_str = f"£{val:,}"
            else:
                val_str = str(val)
        else:
            val_str = str(val)
        table_data.append([label, val_str])
    if not table_data:
        table_data = [["No human-readable fields found", ""]]
    tbl = Table(table_data, colWidths=[120*mm, 60*mm])
    tbl.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.whitesmoke),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('INNERGRID', (0,0), (-1,-1), 0.25, colors.grey),
        ('BOX', (0,0), (-1,-1), 0.25, colors.grey),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
    ]))
    elements.append(tbl)
    elements.append(Spacer(1, 12))
    note = ("NOTE: This document includes a machine-readable JSON block above. "
            "The parser expects exact keys (project_cost, total_cost, interest_rate_annual, loan_term_months).")
    elements.append(Paragraph(note, body_style))
    doc.build(elements)
    return str(out_path)
