import logging
import threading
import time
from pathlib import Path

from flask import Flask, render_template, session
from PIL import Image

from .config import BASE_DIR, Config
from .extensions import db, limiter
from .utils.responses import register_error_handlers
from .utils import security


def create_app(overrides=None):
    app = Flask(__name__, instance_path=str(BASE_DIR / "instance"))
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if app.config["ENV_NAME"] == "production" and app.config["SECRET_KEY_IS_EPHEMERAL"]:
        raise RuntimeError("SECRET_KEY must be set in production (see .env.example).")
    if app.config["SECRET_KEY_IS_EPHEMERAL"]:
        logging.getLogger("dastavej").warning("SECRET_KEY not set - using a temporary key; sessions reset on restart.")

    Path(app.config["STORAGE_DIR"]).mkdir(parents=True, exist_ok=True)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    Image.MAX_IMAGE_PIXELS = app.config["MAX_IMAGE_PIXELS"] * 2

    db.init_app(app)
    limiter.init_app(app)
    register_error_handlers(app)

    from .blueprints import main, jobs
    app.register_blueprint(main.bp)
    app.register_blueprint(jobs.bp)
    for mod in ("image", "scanner", "pdf", "converter", "ai", "resume"):
        try:
            m = __import__(f"app.blueprints.{mod}", fromlist=["bp"])
        except ModuleNotFoundError as e:  # module not built yet
            if e.name != f"app.blueprints.{mod}":
                raise
            continue
        limiter.limit(app.config["RATELIMIT_HEAVY"])(m.bp)
        app.register_blueprint(m.bp)

    app.before_request(security.check_csrf)
    app.after_request(security.add_security_headers)

    @app.before_request
    def _bind_session():
        security.get_sid()
        security.csrf_token()

    @app.context_processor
    def _inject():
        return {"file_ttl": app.config["FILE_TTL_MINUTES"], "csrf_token": security.csrf_token(), "logo_present": (Path(app.static_folder) / "images" / "dastavej-logo.png").exists()}

    with app.app_context():
        db.create_all()

    if app.config["ENABLE_CLEANUP_THREAD"] and not app.config["TESTING"]:
        _start_cleanup(app)
    return app


_cleanup_started = False


def _start_cleanup(app):
    global _cleanup_started
    if _cleanup_started:
        return
    _cleanup_started = True
    from .services.file_manager import cleanup_expired

    def loop():
        while True:
            time.sleep(app.config["CLEANUP_INTERVAL_SECONDS"])
            try:
                cleanup_expired(app)
            except Exception:
                logging.getLogger("dastavej").exception("cleanup failed")

    threading.Thread(target=loop, daemon=True, name="dastavej-cleanup").start()
