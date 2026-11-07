#!/usr/bin/env bash
set -euo pipefail
sudo apt-get update
sudo apt-get install -y python3-venv libreoffice-writer libreoffice-calc libreoffice-impress \
  tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin libgl1
python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip && pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
# Use the system tessdata (it already has Hindi installed above)
sed -i 's#^TESSDATA_PREFIX=.*#TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata#' .env
echo "Dev:  python wsgi.py        Production:  gunicorn -c gunicorn.conf.py wsgi:app"
