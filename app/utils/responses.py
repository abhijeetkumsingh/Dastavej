"""Uniform API responses and safe error handling."""
import logging

from flask import jsonify, request
from werkzeug.exceptions import HTTPException

log = logging.getLogger("dastavej")


class ApiError(Exception):
    def __init__(self, message, status=400, code="bad_request"):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


def ok(data=None, status=200, **extra):
    body = {"ok": True}
    if data:
        body.update(data)
    body.update(extra)
    return jsonify(body), status


def fail(message, status=400, code="bad_request"):
    return jsonify({"ok": False, "error": {"message": message, "code": code}}), status


def register_error_handlers(app):
    @app.errorhandler(ApiError)
    def _api_error(e):
        return fail(e.message, e.status, e.code)

    @app.errorhandler(HTTPException)
    def _http_error(e):
        messages = {
            404: "Not found.",
            405: "Method not allowed.",
            413: "The upload is too large. Please use a smaller file.",
            429: "Too many requests. Please wait a moment and try again.",
        }
        msg = messages.get(e.code, e.description if e.code and e.code < 500 else "Request failed.")
        if request.path.startswith("/api/") or request.path == "/health" or e.code in (413, 429):
            return fail(msg, e.code or 500, (e.name or "error").lower().replace(" ", "_"))
        return e

    @app.errorhandler(Exception)
    def _unhandled(e):
        log.exception("Unhandled error on %s", request.path)
        return fail("Something went wrong while processing your request.", 500, "internal_error")
