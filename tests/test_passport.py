import io
from pathlib import Path

import numpy as np
from PIL import Image

FACE = (Path(__file__).parent / "face_sample.png").read_bytes()


def post(api, url, data, content=FACE):
    d = dict(data)
    d["file"] = (io.BytesIO(content), "me.png")
    return api.post(url, d)


def test_detect_only(api):
    j = post(api, "/api/image/passport", {"detect_only": "1"}).get_json()
    assert j["detected"] and j["face"]["w"] > 40 and j["input"]["job_id"]


def test_passport_300dpi_size_and_jpg(api):
    j = post(api, "/api/image/passport", {"preset": "india-passport"}).get_json()
    assert j["ok"], j
    im = Image.open(io.BytesIO(api.download(j["result"])))
    assert im.size == (413, 531)  # 35x45 mm @ 300 dpi
    assert round(im.info["dpi"][0]) == 300
    assert j["info"]["face_detected"] and not j["info"]["background_changed"]


def test_custom_size(api):
    j = post(api, "/api/image/passport", {"preset": "custom", "width": "2", "height": "2", "unit": "in"}).get_json()
    assert Image.open(io.BytesIO(api.download(j["result"]))).size == (600, 600)


def test_pdf_output_is_pdf(api):
    j = post(api, "/api/image/passport", {"format": "pdf"}).get_json()
    assert api.download(j["result"])[:5] == b"%PDF-" and j["jpg"]["mime"] == "image/jpeg"


def test_identity_preserved_when_background_changes(api):
    a = post(api, "/api/image/passport", {"background": "original"}).get_json()
    b = post(api, "/api/image/passport", {"background": "blue"}).get_json()
    assert b["info"]["background_changed"] is True
    A = np.array(Image.open(io.BytesIO(api.download(a["result"]))).convert("RGB")).astype(int)
    B = np.array(Image.open(io.BytesIO(api.download(b["result"]))).convert("RGB")).astype(int)
    crop, face = a["info"]["crop"], a["info"]["face"]
    s = A.shape[1] / crop["w"]
    fx, fy = (face["x"] - crop["x"]) * s, (face["y"] - crop["y"]) * s
    fw, fh = face["w"] * s, face["h"] * s
    x0, x1, y0, y1 = int(fx + .3 * fw), int(fx + .7 * fw), int(fy + .3 * fh), int(fy + .7 * fh)
    assert np.abs(A[y0:y1, x0:x1] - B[y0:y1, x0:x1]).max() == 0  # face pixels untouched
    # background corner actually became blue-ish
    corner = B[5:25, 5:25].reshape(-1, 3).mean(0)
    assert corner[2] > corner[0] + 30


def test_background_needs_face(api):
    from tests.conftest import png_bytes
    r = post(api, "/api/image/passport", {"background": "white"}, png_bytes(300, 300))
    assert r.status_code == 400 and "face" in r.get_json()["error"]["message"].lower()


def test_adjustments_reported(api):
    j = post(api, "/api/image/passport", {"brightness": "1.1", "sharpen": "1", "noise_reduction": "3"}).get_json()
    assert set(j["info"]["adjustments"]) == {"brightness", "sharpen", "noise_reduction"}


def test_print_sheet_4x6(api):
    p = post(api, "/api/image/passport", {}).get_json()
    j = api.post("/api/image/print-sheet", {"file_id": p["result"]["job_id"], "paper": "4x6", "copies": "8"}).get_json()
    assert j["ok"], j
    im = Image.open(io.BytesIO(api.download(j["result"])))
    assert im.size == (1800, 1200) and j["info"]["copies"] == 8
    assert round(im.info["dpi"][0]) == 300
    r = api.post("/api/image/print-sheet", {"file_id": p["result"]["job_id"], "copies": "30"})
    assert r.status_code == 400
    j = api.post("/api/image/print-sheet", {"file_id": p["result"]["job_id"], "format": "pdf"}).get_json()
    assert api.download(j["result"])[:5] == b"%PDF-"
