import fitz
import pdfplumber
from PIL import Image
import io
import pytesseract

def extract_text_from_pdf(path: str) -> str:
    """
    Try several strategies: PyMuPDF text extraction, pdfplumber for tables,
    fallback to OCR with pytesseract for scanned pages.
    """
    parts = []
    try:
        # Try PyMuPDF first
        doc = fitz.open(path)
        extracted = []
        for page in doc:
            text = page.get_text("text")
            if text and len(text.strip()) > 30:
                extracted.append(text)
            else:
                # Render to image and OCR as fallback
                pix = page.get_pixmap(dpi=150)
                img = Image.open(io.BytesIO(pix.tobytes()))
                ocr = pytesseract.image_to_string(img)
                if ocr:
                    extracted.append(ocr)
        if extracted:
            return "\n".join(extracted)
    except Exception:
        pass

    # Fallback: pdfplumber
    try:
        with pdfplumber.open(path) as pdf:
            texts = []
            for page in pdf.pages:
                t = page.extract_text() or ""
                if t.strip():
                    texts.append(t)
                else:
                    # try table extraction or OCR if needed
                    pass
            if texts:
                return "\n".join(texts)
    except Exception:
        pass

    return ""
