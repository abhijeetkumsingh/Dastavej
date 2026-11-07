"""Session isolation, CSRF, security headers and filename helpers."""
import hmac
import re
import secrets
from pathlib import Path

from flask import abort, current_app, request, session

from .responses import fail

SID_RE = re.compile(r"^[0-9a-f]{32}$")
ID_RE = re.compile(r"^[0-9a-f]{24}$")


def get_sid():
    sid = session.get("sid")
    if not sid or not SID_RE.match(sid):
        sid = secrets.token_hex(16)
        session["sid"] = sid
        session.permanent = True
    return sid


def csrf_token():
    tok = session.get("csrf")
    if not tok:
        tok = secrets.token_urlsafe(32)
        session["csrf"] = tok
    return tok


def check_csrf():
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.path.startswith("/api/"):
        sent = request.headers.get("X-CSRF-Token", "")
        expected = session.get("csrf", "")
        if not expected or not hmac.compare_digest(sent, expected):
            return fail("Security token missing or invalid. Please reload the page.", 403, "csrf_failed")
    return None


def add_security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=()")
    resp.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; font-src 'self'; connect-src 'self'; media-src 'self' blob:; "
        "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'",
    )
    if request.is_secure or current_app.config.get("ENV_NAME") == "production":
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.path.startswith("/api/") or request.path == "/health":
        resp.headers["Cache-Control"] = "no-store"
    return resp


def display_name(name, default="file"):
    """Sanitised name used only for display/download - never for filesystem paths."""
    name = Path(str(name or default).replace("\\", "/")).name
    name = re.sub(r"[^\w.\- ()\u0900-\u097F]", "_", name).strip(" .")
    return (name or default)[:120]


def require_job_id(value):
    if not value or not ID_RE.match(str(value)):
        abort(404)
    return value
