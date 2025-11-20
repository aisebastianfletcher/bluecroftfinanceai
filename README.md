```markdown
# AI Lending Assistant Demo

Project Goal — AI Lending Assistant Demo
This project demonstrates a full end-to-end AI system designed for a property/bridging finance lender (e.g., Bluecroft Finance).
It shows how AI can:

- Extract key financial information from uploaded or generated PDFs
- Analyse borrower/property data using NLP
- Run a simple ML model to generate a “risk score”
- Produce an underwriter-friendly summary with explainability
- Provide natural-language Q&A about the application
- Automate PDF creation from a web form
- Be deployed to a cloud environment (AWS/GCP/Azure)

The goal is to demonstrate:
✔ NLP extraction  
✔ Predictive modelling  
✔ LLM summarisation  
✔ UI-based automation  
✔ Responsible AI (explainability)  
✔ Cloud-ready modular architecture

Quick start
1. Create and activate a virtualenv, then install dependencies:
   pip install -r requirements.txt

2. Train the demo model (optional — a heuristic fallback is used if the model isn't present):
   python pipeline/ml/train_model.py

3. Run the Streamlit app:
   streamlit run app/main.py

Notes
- To enable LLM features, set OPENAI_API_KEY in your environment.
- This is a demo scaffold with simple heuristics and templates — extend extraction, OCR, model training and guardrails for production.
```
