"""
app/pdf_form.py

Create a professional PDF report from the payload:
payload = {
  "parsed": {...},
  "metrics": {...},
  "notes": "...",
  "attachments": [paths],
  "charts": [chart_png_paths],
  "generated_at": "..."
}

Uses reportlab + matplotlib/PIL to include charts and images inline.
"""
from __future__ import annotations
import io
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List
import matplotlib.pyplot as plt
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from PIL import Image as PILImage

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "output" / "generated_pdfs"
OUT_DIR.mkdir(parents=True, exist_ok=True)

def _safe_image_for_pdf(path: str, max_width_mm: float = 160.0) -> str:
    """
    Ensure image exists and optionally resize; return path (may overwrite small temp file)
    """
    try:
        img = PILImage.open(path)
        # convert to RGB if needed
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        # Save temporary resized copy if width too large
        max_px = int((max_width_mm / 25.4) * img.info.get("dpi", (96,96))[0] if img.info.get("dpi") else max(img.size))
        # We'll simply return original path; let reportlab scale at insertion time
        tmp_path = path
        return tmp_path
    except Exception:
        return None

def create_pdf_report(payload: Dict[str, Any]) -> str:
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    out_path = OUT_DIR / f"underwriting_report_{ts}.pdf"
    doc = SimpleDocTemplate(str(out_path), pagesize=A4, leftMargin=18*mm, rightMargin=18*mm, topMargin=18*mm, bottomMargin=18*mm)
    styles = getSampleStyleSheet()
    elements = []

    # Title + header
    title_style = ParagraphStyle(name="Title", parent=styles["Heading1"], fontSize=18, leading=20, spaceAfter=6)
    elements.append(Paragraph("Bluecroft Finance — Underwriting Report", title_style))
    elements.append(Spacer(1, 6))

    parsed = payload.get("parsed", {})
    metrics = payload.get("metrics", {})
    notes = payload.get("notes", "")
    attachments = payload.get("attachments", []) or []
    charts = payload.get("charts", []) or []

    # Key facts table
    key_rows = []
    key_rows.append(["Borrower", parsed.get("borrower", "N/A")])
    key_rows.append(["Loan amount", f"£{parsed.get('loan_amount', 'N/A')}"])
    key_rows.append(["Project / Total cost", f"£{parsed.get('total_cost', parsed.get('project_cost', 'N/A'))}"])
    key_rows.append(["Interest rate (annual)", f"{parsed.get('interest_rate_annual', 'N/A')}%"])
    key_rows.append(["Loan term (months)", f"{parsed.get('loan_term_months','N/A')}"])
    t = Table(key_rows, colWidths=[100*mm, 70*mm])
    t.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.25,colors.grey),('BACKGROUND',(0,0),(-1,0),colors.whitesmoke)]))
    elements.append(t)
    elements.append(Spacer(1,10))

    # Insert charts
    for c in charts:
        if c:
            safe = _safe_image_for_pdf(c)
            if safe:
                try:
                    img = Image(safe, width=160*mm, height=60*mm)
                    elements.append(img)
                    elements.append(Spacer(1,8))
                except Exception:
                    continue

    # Risk summary and flags
    elements.append(Paragraph("<b>Risk assessment</b>", styles["Heading3"]))
    elements.append(Paragraph(f"Category: {metrics.get('risk_category', 'N/A')} — Score: {metrics.get('risk_score_computed', 'N/A')}", styles["Normal"]))
    elements.append(Spacer(1,6))
    pf = metrics.get("policy_flags") or []
    if pf:
        elements.append(Paragraph("<b>Policy flags</b>", styles["Heading4"]))
        for f in pf:
            elements.append(Paragraph(f"- {f}", styles["Normal"]))
    else:
        elements.append(Paragraph("No policy flags detected.", styles["Normal"]))
    elements.append(Spacer(1,8))

    # Amortisation table
    amort = metrics.get("amortization_preview_rows")
    if amort:
        elements.append(Paragraph("<b>Amortization (preview)</b>", styles["Heading4"]))
        rows = [["Month","Payment","Interest","Principal","Balance"]]
        for r in amort:
            rows.append([r.get("month"), f"£{r.get('payment'):,}", f"£{r.get('interest'):,}", f"£{r.get('principal'):,}", f"£{r.get('balance'):,}"])
        tbl = Table(rows, colWidths=[18*mm,30*mm,30*mm,30*mm,40*mm])
        tbl.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.25,colors.grey),('BACKGROUND',(0,0),(-1,0),colors.whitesmoke)]))
        elements.append(tbl)
        elements.append(Spacer(1,8))

    # Attachments list + small preview for images
    if attachments:
        elements.append(Paragraph("<b>Attachments</b>", styles["Heading4"]))
        for p in attachments:
            try:
                elements.append(Paragraph(f"- {Path(p).name}", styles["Normal"]))
                # if image, embed a small preview
                if Path(p).suffix.lower() in (".png", ".jpg", ".jpeg"):
                    safe_img = _safe_image_for_pdf(p)
                    if safe_img:
                        elements.append(Image(safe_img, width=60*mm, height=45*mm))
            except Exception:
                elements.append(Paragraph(f"- {Path(p).name}", styles["Normal"]))
        elements.append(Spacer(1,8))

    # Notes and footer
    if notes:
        elements.append(Paragraph("<b>Underwriter notes</b>", styles["Heading4"]))
        elements.append(Paragraph(notes, styles["Normal"]))
        elements.append(Spacer(1,8))

    elements.append(Paragraph("Generated by Bluecroft Finance. This report is for informational purposes only.", styles["Normal"]))

    doc.build(elements)
    return str(out_path)
