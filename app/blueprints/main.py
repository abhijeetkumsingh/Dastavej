import shutil

from flask import Blueprint, current_app, render_template, jsonify

from ..services import capabilities as caps
from ..extensions import db

bp = Blueprint("main", __name__)

PAGES = {
    "image-tools": "image.html",
    "pdf-tools": "pdf.html",
    "scanner": "scanner.html",
    "passport-photo": "passport.html",
    "converter": "converter.html",
    "ai-assistant": "ai.html",
    "resume-analyzer": "resume.html",
}


@bp.get("/")
def index():
    return render_template("index.html", active="home")


def _make(page, tpl):
    def view():
        return render_template(tpl, active=page)
    view.__name__ = "page_" + page.replace("-", "_")
    return view


for _page, _tpl in PAGES.items():
    bp.add_url_rule(f"/{_page}", view_func=_make(_page, _tpl))


@bp.get("/health")
def health():
    try:
        db.session.execute(db.text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return jsonify({"status": "ok" if db_ok else "degraded", "database": db_ok, "capabilities": caps.detect()})
