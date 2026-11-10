# DASTAVEJ
**All Your Document Needs, One Place.** Scan, convert, compress and manage documents. No login, no permanent storage.

Stack: Python Flask + Blueprints, SQLite (temporary job metadata only), Pillow, OpenCV, PyMuPDF, pypdf, img2pdf, python-docx/pptx, openpyxl, pandas, LibreOffice, Tesseract (English + Hindi), Google Gemini (AI assistant only), Bootstrap 5 (vendored, no CDN), Gunicorn, Docker.

## Features
Image tools · Document scanner (camera/upload, edge detection, perspective fix, filters, multi-page PDF) · PDF Studio · File converter · Passport photo studio (300 DPI, 4x6 sheet) · OCR (Hindi + English) · AI Document Assistant (RAG, citations, Gemini) · Resume analyzer (transparent score, JD match, PDF report).
See `DEVELOPMENT_STATUS.md` for exactly what is tested and what is not.


## API overview
`GET /health` · `/api/image/*` · `/api/scanner/*` · `/api/pdf/*` · `/api/convert/*` · `/api/ai/*` · `/api/resume/*` · `/api/jobs/<id>[/download]`.
All mutating calls need the `X-CSRF-Token` header (from the page's meta tag) and the session cookie.
