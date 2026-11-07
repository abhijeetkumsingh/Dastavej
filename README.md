# DASTAVEJ
**All Your Document Needs, One Place.** Scan, convert, compress and manage documents. No login, no permanent storage.

Stack: Python Flask + Blueprints, SQLite (temporary job metadata only), Pillow, OpenCV, PyMuPDF, pypdf, img2pdf, python-docx/pptx, openpyxl, pandas, LibreOffice, Tesseract (English + Hindi), Google Gemini (AI assistant only), Bootstrap 5 (vendored, no CDN), Gunicorn, Docker.

## Features
Image tools · Document scanner (camera/upload, edge detection, perspective fix, filters, multi-page PDF) · PDF Studio · File converter · Passport photo studio (300 DPI, 4x6 sheet) · OCR (Hindi + English) · AI Document Assistant (RAG, citations, Gemini) · Resume analyzer (transparent score, JD match, PDF report).
See `DEVELOPMENT_STATUS.md` for exactly what is tested and what is not.

## Run locally
**Windows (PowerShell)**
```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup-windows.ps1
.\.venv\Scripts\Activate.ps1
python wsgi.py          # http://127.0.0.1:5000
```
**Linux / macOS**
```bash
bash scripts/setup-linux.sh && source .venv/bin/activate
python wsgi.py          # development server only
```
Optional tools: LibreOffice (Office to PDF) and Tesseract + `hin.traineddata` (OCR). The app detects them and disables what is unavailable; see `/health`.

## Configuration
Copy `.env.example` to `.env`. For AI set `GEMINI_API_KEY` (kept on the server, never sent to the browser). Without it, AI endpoints return a clear configuration message and everything else works.

## Logo
Put the official logo at `app/static/images/dastavej-logo.png`. It is used automatically in the navbar and footer, unmodified. Until then a text wordmark is shown.

## Production
```bash
export DASTAVEJ_ENV=production SECRET_KEY=<64 hex chars>
gunicorn -c gunicorn.conf.py wsgi:app
```
or `docker compose up --build` (needs `.env` with `SECRET_KEY`). Use Docker Compose rather than `docker run --env-file .env`; Compose parses inline comments in `.env` consistently with the Flask configuration. Serve behind HTTPS (nginx/Caddy) and set `SESSION_COOKIE_SECURE=1`; camera scanning requires HTTPS. Use Redis for `RATELIMIT_STORAGE_URI` with several workers. Set container memory limits.

## Privacy model
Uploads get random names under `instance/storage/<session>/`, are visible only to the browser session that uploaded them, and are deleted after `FILE_TTL_MINUTES` (default 60) by a background cleanup. The database stores only sizes, page counts and expiry. AI features send **only relevant text excerpts** to Gemini, and only after the consent box is ticked.

## Tests
```bash
pip install -r requirements-dev.txt
python -m pytest tests -q                              # 110 tests
cd tests/js && npm install && python make_fixtures.py  # UI tests (jsdom)
python tests/js/server.py 5057 &                       # test server with a fake Gemini
node tests/js/ui.test.js                               # 31 tests
```

## API overview
`GET /health` · `/api/image/*` · `/api/scanner/*` · `/api/pdf/*` · `/api/convert/*` · `/api/ai/*` · `/api/resume/*` · `/api/jobs/<id>[/download]`.
All mutating calls need the `X-CSRF-Token` header (from the page's meta tag) and the session cookie.
