"""Application configuration. All secrets come from environment variables."""
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


class Config:
    ENV_NAME = os.environ.get("DASTAVEJ_ENV", "development")
    TEMPLATES_AUTO_RELOAD = ENV_NAME != "production"
    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    SECRET_KEY_IS_EPHEMERAL = not os.environ.get("SECRET_KEY")

    STORAGE_DIR = Path(os.environ.get("STORAGE_DIR", BASE_DIR / "instance" / "storage"))
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{BASE_DIR / 'instance' / 'dastavej.db'}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Upload & processing limits
    MAX_CONTENT_LENGTH = _int("MAX_UPLOAD_MB", 50) * 1024 * 1024
    MAX_FILES_PER_REQUEST = _int("MAX_FILES_PER_REQUEST", 30)
    MAX_IMAGE_PIXELS = _int("MAX_IMAGE_PIXELS", 60_000_000)
    MAX_PDF_PAGES = _int("MAX_PDF_PAGES", 300)
    MAX_ZIP_UNCOMPRESSED_MB = _int("MAX_ZIP_UNCOMPRESSED_MB", 300)

    # Lifetime of temporary files
    FILE_TTL_MINUTES = _int("FILE_TTL_MINUTES", 60)
    CLEANUP_INTERVAL_SECONDS = _int("CLEANUP_INTERVAL_SECONDS", 300)

    # External tools
    SOFFICE_BIN = os.environ.get("SOFFICE_BIN", "")
    LIBREOFFICE_TIMEOUT = _int("LIBREOFFICE_TIMEOUT", 120)
    LIBREOFFICE_MEMORY_MB = _int("LIBREOFFICE_MEMORY_MB", 4096)
    TESSDATA_PREFIX = os.environ.get("TESSDATA_PREFIX", str(BASE_DIR / "tessdata"))
    OCR_LANGS = os.environ.get("OCR_LANGS", "eng+hin")
    OCR_MAX_PAGES = _int("OCR_MAX_PAGES", 40)

    # Gemini (backend only)
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash").strip()
    GEMINI_TIMEOUT_SECONDS = _int("GEMINI_TIMEOUT_SECONDS", 60)

    # Rate limiting
    RATELIMIT_ENABLED = os.environ.get("RATELIMIT_ENABLED", "1") == "1"
    RATELIMIT_DEFAULT = os.environ.get("RATELIMIT_DEFAULT", "300 per minute")
    RATELIMIT_HEAVY = os.environ.get("RATELIMIT_HEAVY", "40 per minute")
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24

    ENABLE_CLEANUP_THREAD = True
    TESTING = False
