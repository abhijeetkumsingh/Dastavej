import io
import os
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import create_app  # noqa: E402


class Api:
    def __init__(self, client):
        self.c = client
        self.c.get("/health")  # establishes session
        with self.c.session_transaction() as s:
            self.token = s["csrf"]
            self.sid = s["sid"]

    def post(self, url, data=None, **kw):
        h = {"X-CSRF-Token": self.token}
        return self.c.post(url, data=data or {}, headers=h, content_type="multipart/form-data", **kw)

    def delete(self, url):
        return self.c.delete(url, headers={"X-CSRF-Token": self.token})

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def download(self, result):
        r = self.c.get(result["download_url"])
        assert r.status_code == 200, r.data
        return r.data


@pytest.fixture()
def app(tmp_path):
    a = create_app({
        "TESTING": True, "STORAGE_DIR": tmp_path / "storage",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}",
        "RATELIMIT_ENABLED": False, "SECRET_KEY": "test-secret", "ENABLE_CLEANUP_THREAD": False,
        "GEMINI_API_KEY": "",
    })
    return a


@pytest.fixture()
def api(app):
    return Api(app.test_client())


@pytest.fixture()
def api2(app):
    return Api(app.test_client())


def png_bytes(w=400, h=300, color=(200, 120, 60), noise=False, fmt="PNG"):
    im = Image.new("RGB", (w, h), color)
    d = ImageDraw.Draw(im)
    for i in range(0, w, 20):
        d.line([(i, 0), (w - i, h)], fill=(i % 255, 50, 255 - i % 255), width=2)
    if noise:
        import random
        px = im.load()
        rnd = random.Random(1)
        for x in range(w):
            for y in range(h):
                px[x, y] = (rnd.randrange(256), rnd.randrange(256), rnd.randrange(256))
    b = io.BytesIO()
    im.save(b, fmt)
    return b.getvalue()


def make_pdf(pages=3, text="Hello DASTAVEJ page"):
    import pymupdf
    doc = pymupdf.open()
    for i in range(pages):
        p = doc.new_page()
        p.insert_text((72, 100), f"{text} {i + 1}", fontsize=18)
    b = doc.tobytes()
    doc.close()
    return b


@pytest.fixture()
def img_png():
    return png_bytes()


@pytest.fixture()
def pdf3():
    return make_pdf(3)
