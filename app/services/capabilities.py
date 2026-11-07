"""Detect optional external tools so the UI only advertises what actually works."""
import os
import shutil
import subprocess
from functools import lru_cache

from flask import current_app


def soffice_path():
    cfg = current_app.config.get("SOFFICE_BIN")
    if cfg and os.path.exists(cfg):
        return cfg
    return shutil.which("soffice") or shutil.which("libreoffice")


def setup_tesseract():
    import pytesseract
    prefix = current_app.config.get("TESSDATA_PREFIX")
    if prefix and os.path.isdir(prefix) and any(f.endswith(".traineddata") for f in os.listdir(prefix)):
        os.environ["TESSDATA_PREFIX"] = prefix
    return pytesseract


@lru_cache(maxsize=4)
def _ocr_langs(prefix):
    try:
        import pytesseract
        if not shutil.which("tesseract"):
            return ()
        return tuple(pytesseract.get_languages(config=""))
    except Exception:
        return ()


def ocr_languages():
    setup_tesseract()
    return list(_ocr_langs(os.environ.get("TESSDATA_PREFIX", "")))


def detect():
    langs = ocr_languages()
    return {
        "tesseract": bool(langs),
        "ocr_english": "eng" in langs,
        "ocr_hindi": "hin" in langs,
        "libreoffice": bool(soffice_path()),
        "gemini_configured": bool(current_app.config.get("GEMINI_API_KEY")),
    }
