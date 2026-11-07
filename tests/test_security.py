import io
import os
import time
import zipfile
from datetime import timedelta
from pathlib import Path

import pytest

from app.extensions import db
from app.models import Job, utcnow
from app.services import file_manager as fm
from tests.conftest import Api, make_pdf, png_bytes


def up(api, url, content, name, data=None):
    d = dict(data or {}); d["file"] = (io.BytesIO(content), name)
    return api.post(url, d)


def test_session_isolation_download_and_use(api, api2):
    j = up(api, "/api/image/resize", png_bytes(), "a.png", {"width": "50"}).get_json()
    jid = j["result"]["job_id"]
    assert api.get(j["result"]["download_url"]).status_code == 200
    assert api2.get(j["result"]["download_url"]).status_code == 404
    assert api2.get(f"/api/jobs/{jid}").status_code == 404
    assert api2.delete(f"/api/jobs/{jid}").status_code == 404
    r = api2.post("/api/image/resize", {"file_id": jid, "width": "20"})
    assert r.status_code == 404  # cannot feed another session's file into a tool
    assert api.get(j["result"]["download_url"]).status_code == 200  # still intact


def test_no_cookie_no_access(app, api):
    j = up(api, "/api/image/resize", png_bytes(), "a.png", {"width": "50"}).get_json()
    anon = app.test_client()
    assert anon.get(j["result"]["download_url"]).status_code == 404


def test_pdf_preview_isolated(api, api2):
    j = up(api, "/api/pdf/info", make_pdf(2), "a.pdf").get_json()
    assert api2.get(f"/api/pdf/preview/{j['input']['job_id']}/1").status_code == 404


def test_download_headers_and_inline_rules(api):
    j = up(api, "/api/image/resize", png_bytes(), "a.png", {"width": "50"}).get_json()
    r = api.get(j["result"]["download_url"])
    assert "attachment" in r.headers["Content-Disposition"] and r.headers["X-Content-Type-Options"] == "nosniff"
    r = api.get(j["result"]["preview_url"])
    assert "attachment" not in r.headers.get("Content-Disposition", "")
    z = up(api, "/api/pdf/split", make_pdf(3), "a.pdf", {"mode": "each"}).get_json()
    r = api.get(z["result"]["download_url"] + "?inline=1")
    assert "attachment" in r.headers["Content-Disposition"]  # zips never inline


def test_malicious_filename_never_touches_filesystem(app, api):
    names = ["../../etc/passwd.png", "..\\..\\windows\\evil.png", "a/b/c.png", "x\x00.png", "<script>alert(1)</script>.png"]
    for n in names:
        r = up(api, "/api/image/resize", png_bytes(), n, {"width": "40"})
        assert r.status_code == 200, n
        res = r.get_json()["result"]
        assert "/" not in res["name"] and "\\" not in res["name"] and "<" not in res["name"]
        cd = api.get(res["download_url"]).headers["Content-Disposition"]
        assert ".." not in cd.split("filename")[-1]
    root = Path(app.config["STORAGE_DIR"])
    for p in root.rglob("*"):
        assert root in p.resolve().parents or p.resolve() == root
    assert not (root.parent / "passwd.png").exists()


def test_random_internal_filenames(app, api):
    j = up(api, "/api/image/resize", png_bytes(), "secret-name.png", {"width": "40"}).get_json()
    files = [p.name for p in Path(app.config["STORAGE_DIR"]).rglob("*") if p.is_file()]
    assert files and all("secret-name" not in f for f in files)
    assert all(len(Path(f).stem) == 24 for f in files)


def test_zip_bomb_and_traversal_rejected(api):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<x/>"); z.writestr("word/../../evil.txt", "x"); z.writestr("word/document.xml", "<x/>")
    r = up(api, "/api/convert/docx-to-pdf", buf.getvalue(), "evil.docx")
    assert r.status_code == 400 and "unsafe" in r.get_json()["error"]["message"].lower()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<x/>"); z.writestr("word/document.xml", b"0" * 120_000_000)
    r = up(api, "/api/convert/docx-to-pdf", buf.getvalue(), "bomb.docx")
    assert r.status_code == 400


def test_pdf_page_limit(app, api):
    app.config["MAX_PDF_PAGES"] = 3
    r = up(api, "/api/pdf/to-text", make_pdf(5), "a.pdf")
    assert r.status_code == 413 and "limit" in r.get_json()["error"]["message"]


def test_too_many_files(app, api):
    app.config["MAX_FILES_PER_REQUEST"] = 2
    d = {"width": "20", "file": [(io.BytesIO(png_bytes()), f"{i}.png") for i in range(3)]}
    assert api.post("/api/image/resize", d).status_code == 413


def test_binary_garbage_and_empty(api):
    assert up(api, "/api/pdf/to-text", os.urandom(2000), "a.pdf").status_code == 415
    assert up(api, "/api/pdf/to-text", b"", "a.pdf").status_code == 400
    assert api.post("/api/pdf/to-text", {}).status_code == 400


def test_csrf_enforced_on_every_mutating_endpoint(api):
    c = api.c
    for url in ("/api/image/resize", "/api/pdf/merge", "/api/ai/ask", "/api/resume/analyze", "/api/scanner/export",
                "/api/convert/docx-to-pdf"):
        r = c.post(url, data={}, content_type="multipart/form-data")
        assert r.status_code == 403, url
        r = c.post(url, data={}, headers={"X-CSRF-Token": "wrong"}, content_type="multipart/form-data")
        assert r.status_code == 403, url
    assert c.delete("/api/ai/session").status_code == 403


def test_cleanup_removes_expired_files_and_rows(app, api):
    j = up(api, "/api/image/resize", png_bytes(), "a.png", {"width": "40"}).get_json()
    keep = up(api, "/api/image/resize", png_bytes(), "b.png", {"width": "40"}).get_json()
    with app.app_context():
        job = Job.query.get(j["result"]["job_id"])
        path = fm.job_path(job)
        assert path.exists()
        job.expires_at = utcnow() - timedelta(minutes=1)
        db.session.commit()
    assert api.get(j["result"]["download_url"]).status_code == 404  # expired -> inaccessible even before cleanup
    with app.app_context():
        n = fm.cleanup_expired(app)
        assert n >= 1 and not path.exists() and Job.query.get(j["result"]["job_id"]) is None
        assert Job.query.get(keep["result"]["job_id"]) is not None
    assert api.get(keep["result"]["download_url"]).status_code == 200


def test_cleanup_removes_orphans(app, api):
    api.get("/health")
    sdir = Path(app.config["STORAGE_DIR"]) / api.sid
    sdir.mkdir(parents=True, exist_ok=True)
    orphan = sdir / "deadbeef.part"
    orphan.write_bytes(b"x")
    old = time.time() - 3 * 3600
    os.utime(orphan, (old, old))
    with app.app_context():
        fm.cleanup_expired(app)
    assert not orphan.exists()


def test_delete_job_removes_file(app, api):
    j = up(api, "/api/image/resize", png_bytes(), "a.png", {"width": "40"}).get_json()
    assert api.delete(f"/api/jobs/{j['result']['job_id']}").status_code == 200
    assert api.get(j["result"]["download_url"]).status_code == 404
    assert not any(p.name.startswith(j["result"]["job_id"]) for p in Path(app.config["STORAGE_DIR"]).rglob("*"))


def test_database_never_stores_document_text(app, api):
    secret = "TOPSECRET-PASSPORT-NUMBER-Z1234567"
    up(api, "/api/ai/upload", secret.encode() + b" is in this note, plus some more words to read.", "n.txt")
    up(api, "/api/pdf/to-text", make_pdf(1, secret), "s.pdf")
    with app.app_context():
        dump = " ".join(f"{j.display_name} {j.meta_json}" for j in Job.query.all())
    assert secret not in dump
    raw = (Path(app.config["SQLALCHEMY_DATABASE_URI"].replace("sqlite:///", ""))).read_bytes()
    assert secret.encode() not in raw


def test_rate_limit_returns_429(tmp_path):
    from app import create_app
    a = create_app({"TESTING": True, "STORAGE_DIR": tmp_path / "s", "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'r.db'}",
                    "RATELIMIT_ENABLED": True, "RATELIMIT_HEAVY": "3 per minute", "SECRET_KEY": "k", "ENABLE_CLEANUP_THREAD": False})
    from app.extensions import limiter
    limiter.reset()
    api = Api(a.test_client())
    codes = [up(api, "/api/image/resize", png_bytes(100, 100), "a.png", {"width": "20"}).status_code for _ in range(6)]
    assert 429 in codes and codes[0] == 200
    r = up(api, "/api/image/resize", png_bytes(100, 100), "a.png", {"width": "20"})
    assert r.get_json()["ok"] is False


def test_errors_do_not_leak_internals(api, monkeypatch):
    from app.services import image_service
    monkeypatch.setattr(image_service, "resize", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("secret path /srv/key")))
    r = up(api, "/api/image/resize", png_bytes(), "a.png", {"width": "20"})
    assert r.status_code == 500 and "secret" not in r.get_data(as_text=True) and "/srv" not in r.get_data(as_text=True)


def test_gemini_key_never_exposed(app, api):
    app.config["GEMINI_API_KEY"] = "AIza-SECRET-KEY-VALUE"
    for url in ("/health", "/api/convert/capabilities", "/"):
        body = api.get(url).get_data(as_text=True)
        assert "AIza-SECRET-KEY-VALUE" not in body
    assert api.get("/health").get_json()["capabilities"]["gemini_configured"] is True


def test_production_requires_secret_key(tmp_path, monkeypatch):
    from app import create_app
    monkeypatch.delenv("SECRET_KEY", raising=False)
    from app.config import Config
    monkeypatch.setattr(Config, "SECRET_KEY_IS_EPHEMERAL", True)
    with pytest.raises(RuntimeError):
        create_app({"ENV_NAME": "production", "STORAGE_DIR": tmp_path / "s", "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'p.db'}"})
