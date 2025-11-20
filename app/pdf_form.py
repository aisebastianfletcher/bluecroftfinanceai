import os
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from datetime import datetime

OUTPUT_DIR = "output/generated_pdfs"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def create_pdf_from_dict(data: dict, filename: str = None) -> str:
    """
    Create a simple lender-style PDF from a dict.
    """
    if filename is None:
        filename = f"application_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.pdf"
    out_path = os.path.join(OUTPUT_DIR, filename)
    c = canvas.Canvas(out_path, pagesize=A4)
    width, height = A4
    x = 50
    y = height - 50
    c.setFont("Helvetica-Bold", 16)
    c.drawString(x, y, "Bluecroft Finance — Application Form")
    c.setFont("Helvetica", 12)
    y -= 30
    for key, value in data.items():
        c.drawString(x, y, f"{key}: {value}")
        y -= 20
    c.showPage()
    c.save()
    return out_path
