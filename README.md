# Bluecroft Finance

Professional bridging-loan calculator, underwriter dashboard and PDF report generator.

Bluecroft Finance provides a lightweight, modern web application for rapid bridging loan due-diligence: a clean UI for entering deal inputs, instant financial metrics (LTV, LTC, DSCR, NOI), visual charts, policy flags and a professional PDF underwriting report that includes charts and attachments.

---

## Key features

- Elegant, finance-focused Streamlit UI with blue-branded header and two-panel layout
  - Left: loan inputs and drag & drop uploads
  - Right: instant metrics, charts, flags and report preview
- Bridging loan calculator
  - Inputs: purchase price, refurbishment/project cost, total cost (auto-sum), loan requested, deposit, loan term (months), interest rate (annual/monthly), fees, monthly rent, GDV
  - Auto-calculated metrics: LTV, LTC, monthly interest-only, monthly amortising payment, total interest, NOI (proxy), DSCR, net profit (if GDV), risk score and category
  - Policy flags: High LTV (>75%), High LTC (>80%), Low DSCR (≤1.2), Missing income, Missing amortisation data
- Charts and visual indicators
  - LTV vs LTC bar chart
  - Monthly interest cost chart
  - Risk gauge (donut)
  - Amortisation preview table
  - Charts are exportable to PNG and embeddable in the generated PDF
- File uploads
  - Drag & drop supporting documents (valuations, photos, models)
  - Uploaded files are listed in the UI and attached/listed inside the PDF report; images are previewed
- PDF generator
  - Professional report with company header, borrower summary, all metrics, risk breakdown, policy violations, charts, amortisation table and attachments list
  - Clean typography and spacing suitable for underwriting and submissions
- Defensive code & parser helpers
  - Robust normalization of inputs and extraction of machine-readable key:value blocks embedded inside text
  - Helpful diagnostics/audit notes when inputs are missing or suspect
- Extensible for LLM summarization (optional) — plug in your own summarizer for richer natural language sections

---

## Project structure (high level)

- app/
  - main.py — Streamlit application entrypoint (UI + orchestration)
  - metrics.py — lending metrics, amortization schedule and risk scoring
  - parse_helpers.py — helpers to extract embedded machine-readable fields and detect implausible inputs
  - pdf_form.py — PDF report generator (reportlab + matplotlib)
  - output/ — runtime output (generated PDFs, charts, uploaded docs)
- requirements.txt — Python dependencies

---

## Quickstart — run locally

1. Clone the repository:

   git clone https://github.com/aisebastianfletcher/bluecroftfinanceai.git
   cd bluecroftfinanceai

2. (Recommended) Create and activate a virtual environment:

   python -m venv .venv
   source .venv/bin/activate  # Linux / macOS
   .venv\Scripts\activate     # Windows PowerShell

3. Install dependencies:

   pip install -r requirements.txt

4. Run the Streamlit app:

   streamlit run app/main.py

5. Open your browser at the URL shown by Streamlit (usually http://localhost:8501).

---

## Usage notes

- Fill the inputs on the Left panel. Use the sample quick-calculator button for a ready example.
- Upload supporting files (PDFs, images, spreadsheets) via the drag & drop uploader — images will be previewed and files are saved under `app/output/supporting_docs/<timestamp>/`.
- Click "Analyse With AI" (or "Run Analysis") to compute metrics, show flags and render charts.
- Use the "Generate PDF Report" button to produce a professional underwriting PDF. If the PDF generator is not available, the app will provide a downloadable JSON fallback.
- The app expects exact machine-readable keys for strict parsing in some flows:
  - project_cost
  - total_cost
  - interest_rate_annual
  - loan_term_months
  Make sure generated PDFs or upstream parsers include those exact keys (the built-in PDF generator writes them exactly).

---

## Troubleshooting

- ModuleNotFoundError: No module named 'app.parse_helpers' (or app.metrics)
  - Ensure all files in `app/` are present: `app/metrics.py`, `app/parse_helpers.py`, `app/pdf_form.py`, `app/main.py`.
  - Ensure the repository root is on Python's import path. Running `streamlit run app/main.py` from the repository root normally works.
  - Add an empty `app/__init__.py` if your environment requires it.

- Reportlab / headless environment:
  - The PDF generator uses ReportLab and Matplotlib. In headless servers you may need to ensure system fonts or backends are available and `matplotlib` is configured to use a non-interactive backend (the code uses savefig and should work headless).

- Plotly image export:
  - The app uses Plotly to render charts in the UI. It may use `kaleido` or a renderer to export PNGs. If PNG export fails, the app falls back to JSON download.

- Long-running or missing dependencies:
  - Check `requirements.txt` and install the listed packages. If you use Streamlit Cloud, add these to your cloud requirements.

---

## Development & Contributing

Contributions, fixes and polish are welcome.

- Create a new branch for your change: `git checkout -b feat/your-change`
- Run tests (if added) and ensure the app runs locally
- Open a Pull Request describing your changes

If you want me to open a PR adding the finished UI and helper files to this repository, I can prepare and push a commit for you.

---

## Extensibility

- LLM summarizer: The UI includes a placeholder to call an external summarizer (pipeline/llm/summarizer). Plug your LLM backend to provide AI-generated executive summaries and Q&A.
- PDF enhancement: The PDF generator is modular — you can embed PDFs, include first-page thumbnails, or attach full files into a ZIP alongside the PDF.
- Frontend rewrite: If you later prefer React + Vite + Tailwind, the current Python backend (metrics, report generation) can be reused as an API.

---

## License

Add a LICENSE file to the repository to make licensing explicit. (MIT recommended for open-source.)

---

## Contact

Repository: https://github.com/aisebastianfletcher/bluecroftfinanceai

For support, open an issue in the repo or contact the maintainer (aisebastianfletcher) on GitHub.

---
