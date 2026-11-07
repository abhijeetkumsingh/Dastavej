import multiprocessing
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = max(1, int(os.environ.get("WEB_CONCURRENCY", min(4, max(2, multiprocessing.cpu_count())))))
threads = 2
timeout = 180            # hard processing timeout per request (kills stuck workers)
graceful_timeout = 30
max_requests = 500       # recycle workers to cap memory growth
max_requests_jitter = 50
limit_request_line = 4094
accesslog = "-"
errorlog = "-"
preload_app = True


def post_fork(server, worker):
    from app.extensions import db
    from wsgi import app

    with app.app_context():
        db.engine.dispose(close=False)
