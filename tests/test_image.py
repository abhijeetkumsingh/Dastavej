import io

import numpy as np
from PIL import Image

from tests.conftest import png_bytes


def up(api, url, data, name="a.png", content=None, field="file", **kw):
    d = dict(data)
    d[field] = (io.BytesIO(content if content is not None else png_bytes()), name)
    return api.post(url, d, **kw)


def test_resize_keep_aspect(api):
    r = up(api, "/api/image/resize", {"width": "200"})
    j = r.get_json()
    assert r.status_code == 200, j
    im = Image.open(io.BytesIO(api.download(j["result"])))
    assert im.size == (200, 150)


def test_resize_custom_no_aspect(api):
    j = up(api, "/api/image/resize", {"width": "100", "height": "100", "keep_aspect": "false"}).get_json()
    assert Image.open(io.BytesIO(api.download(j["result"]))).size == (100, 100)


def test_resize_requires_dimension(api):
    assert up(api, "/api/image/resize", {}).status_code == 400


def test_compress_target_verified(api):
    big = png_bytes(1600, 1200, noise=True, fmt="JPEG")
    j = up(api, "/api/image/compress", {"target_size": "60", "target_unit": "KB", "format": "jpg"},
           "n.jpg", big).get_json()
    assert j["ok"], j
    data = api.download(j["result"])
    assert len(data) <= 60 * 1024
    assert j["result"]["size"] == len(data)
    assert j["info"]["target_met"] is True
    Image.open(io.BytesIO(data)).verify()


def test_compress_png_target(api):
    big = png_bytes(900, 700, noise=True)
    j = up(api, "/api/image/compress", {"target_size": "80", "target_unit": "KB", "format": "png"},
           content=big).get_json()
    data = api.download(j["result"])
    assert len(data) <= 80 * 1024 and j["info"]["target_met"]


def test_compress_unreachable_is_honest(api):
    j = up(api, "/api/image/compress", {"target_size": "1", "target_unit": "KB", "format": "png"},
           content=png_bytes(800, 800, noise=True)).get_json()
    data = api.download(j["result"])
    assert j["info"]["target_met"] == (len(data) <= 1024)


def test_convert_formats(api):
    for fmt, mag in (("jpg", b"\xff\xd8"), ("webp", b"RIFF"), ("png", b"\x89PNG")):
        j = up(api, "/api/image/convert", {"format": fmt}).get_json()
        assert api.download(j["result"])[:4].startswith(mag), fmt


def test_png_alpha_to_jpg(api):
    im = Image.new("RGBA", (50, 50), (255, 0, 0, 0))
    b = io.BytesIO(); im.save(b, "PNG")
    j = up(api, "/api/image/convert", {"format": "jpg"}, content=b.getvalue()).get_json()
    out = Image.open(io.BytesIO(api.download(j["result"])))
    assert out.getpixel((10, 10))[0] > 240 and out.getpixel((10, 10))[1] > 240  # transparent -> white


def test_crop_rotate_enhance(api):
    j = up(api, "/api/image/crop", {"x": "10", "y": "10", "width": "100", "height": "80"}).get_json()
    assert Image.open(io.BytesIO(api.download(j["result"]))).size == (100, 80)
    assert up(api, "/api/image/crop", {"x": "350", "y": "10", "width": "100", "height": "80"}).status_code == 400
    j = up(api, "/api/image/rotate", {"angle": "90"}).get_json()
    assert Image.open(io.BytesIO(api.download(j["result"]))).size == (300, 400)
    j = up(api, "/api/image/enhance", {"brightness": "1.3", "contrast": "1.2", "noise_reduction": "3"}).get_json()
    assert j["ok"]


def test_batch_zip(api):
    d = {"width": "50", "file": [(io.BytesIO(png_bytes()), "a.png"), (io.BytesIO(png_bytes()), "b.png")]}
    j = api.post("/api/image/resize", d).get_json()
    assert j["result"]["mime"] == "application/zip" and j["info"]["files"] == 2


def test_invalid_and_corrupt(api):
    r = up(api, "/api/image/resize", {"width": "10"}, "x.png", b"not an image at all\x00\x01")
    assert r.status_code == 415
    corrupt = png_bytes()[:200]
    r = up(api, "/api/image/resize", {"width": "10"}, "x.png", corrupt)
    assert r.status_code == 400 and "corrupt" in r.get_json()["error"]["message"]
    assert up(api, "/api/image/resize", {"width": "10"}, "x.png", b"").status_code in (400,)


def test_exe_disguised_as_png_rejected(api):
    r = up(api, "/api/image/resize", {"width": "10"}, "evil.png", b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 100)
    assert r.status_code == 415


def test_pixel_limit(app, api):
    app.config["MAX_IMAGE_PIXELS"] = 10_000
    r = up(api, "/api/image/resize", {"width": "10"}, content=png_bytes(400, 300))
    assert r.status_code == 413


def test_upload_size_limit(app, api):
    app.config["MAX_CONTENT_LENGTH"] = 1000
    r = up(api, "/api/image/resize", {"width": "10"}, content=png_bytes(400, 300, noise=True))
    assert r.status_code == 413 and r.get_json()["ok"] is False
