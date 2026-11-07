# DASTAVEJ - Windows setup (PowerShell). Run from the project folder.
$ErrorActionPreference = "Stop"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host "Created .env - edit it and add GEMINI_API_KEY if you want AI features." }

Write-Host ""
Write-Host "Optional external tools (install once):"
Write-Host "  LibreOffice (Word/PowerPoint/Excel -> PDF):  winget install TheDocumentFoundation.LibreOffice"
Write-Host "  Tesseract OCR (scans):                       winget install UB-Mannheim.TesseractOCR"
Write-Host "  Hindi OCR data: download hin.traineddata from https://github.com/tesseract-ocr/tessdata_fast"
Write-Host "  and place it, together with eng.traineddata, in the .\tessdata folder (set TESSDATA_PREFIX=tessdata in .env)."
Write-Host ""
Write-Host "Run:  python wsgi.py     then open http://127.0.0.1:5000"
Write-Host "Production on Windows: pip install waitress ; waitress-serve --listen=0.0.0.0:8000 wsgi:app"
