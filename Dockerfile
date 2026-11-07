FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DASTAVEJ_ENV=production

# LibreOffice (Office -> PDF), Tesseract (OCR) with Hindi + English, fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
      libreoffice-writer libreoffice-calc libreoffice-impress \
      tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin \
      fonts-dejavu fonts-noto-core fonts-noto-extra libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY wsgi.py gunicorn.conf.py ./

# Use the system tessdata installed above (not the dev ./tessdata folder)
ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata \
    STORAGE_DIR=/data/storage \
    DATABASE_URL=sqlite:////data/dastavej.db

RUN useradd -m -u 10001 dastavej && mkdir -p /data && chown -R dastavej /data /app
USER dastavej
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/health',timeout=4)"
CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]
