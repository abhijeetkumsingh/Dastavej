import io

from tests.conftest import png_bytes


def test_health(api):
    r = api.get("/health")
    assert r.status_code == 200
    j = r.get_json()
    assert j["database"] is True and "capabilities" in j
    assert "gemini_configured" in j["capabilities"]


def test_csrf_required(api):
    r = api.c.post("/api/jobs/abc", data={})
    assert r.status_code in (403, 405)
    r = api.c.delete("/api/jobs/" + "a" * 24)
    assert r.status_code == 403


def test_security_headers(api):
    r = api.get("/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert r.headers["Cache-Control"] == "no-store"


def test_unknown_api_is_json(api):
    r = api.get("/api/nope")
    assert r.status_code == 404 and r.get_json()["ok"] is False


def test_bad_job_id_404(api):
    assert api.get("/api/jobs/not-a-valid-id/download").status_code == 404
