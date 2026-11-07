import io

import cv2
import numpy as np
from PIL import Image

from app.services import scanner_service as sc


def synth_doc(w=900, h=1200):
    """Dark desk with a white, perspective-skewed sheet carrying text-like lines."""
    img = np.full((h, w, 3), (45, 60, 70), np.uint8)
    sheet = np.full((600, 450, 3), 245, np.uint8)
    for y in range(60, 560, 40):
        cv2.putText(sheet, "Hello DASTAVEJ scan", (30, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (20, 20, 20), 2)
    src = np.float32([[0, 0], [449, 0], [449, 599], [0, 599]])
    dst = np.float32([[170, 210], [700, 170], [740, 980], [120, 1010]])
    M = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(sheet, M, (w, h))
    mask = cv2.warpPerspective(np.full((600, 450), 255, np.uint8), M, (w, h))
    img[mask > 0] = warped[mask > 0]
    return img, dst


def jpg(img):
    ok, b = cv2.imencode(".jpg", img)
    return b.tobytes()


def test_corner_detection_accuracy():
    img, dst = synth_doc()
    corners, found = sc.detect_corners(Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)))
    assert found
    px = np.array(corners) * [900, 1200]
    assert np.abs(px - dst).max() < 25


def test_perspective_warp_output_aspect():
    img, _ = synth_doc()
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    corners, _ = sc.detect_corners(pil)
    out = sc.warp(pil, corners)
    ratio = out.size[0] / out.size[1]
    assert 0.6 < ratio < 0.9  # sheet is 450x600 = 0.75
    arr = np.array(out.convert("L"))
    assert arr[10:40, 10:40].mean() > 200  # paper, not desk


def up(api, url, data, content, name="s.jpg"):
    d = dict(data); d["file"] = (io.BytesIO(content), name)
    return api.post(url, d)


def test_full_scan_flow_and_export(api):
    img, _ = synth_doc()
    j = up(api, "/api/scanner/upload", {}, jpg(img)).get_json()
    assert j["ok"] and j["edges_found"] and len(j["corners"]) == 4
    p = api.post("/api/scanner/process", {"file_id": j["result"]["job_id"], "corners": str(j["corners"])}).get_json()
    assert p["ok"], p
    f = api.post("/api/scanner/filter", {"file_id": p["result"]["job_id"], "mode": "bw", "rotate": "0"}).get_json()
    bw = np.array(Image.open(io.BytesIO(api.download(f["result"]))).convert("L"))
    assert ((bw < 40) | (bw > 215)).mean() > 0.97  # near-binary (JPEG storage adds edge noise)
    c = api.post("/api/scanner/crop", {"file_id": f["result"]["job_id"], "x": "0.1", "y": "0.1", "width": "0.8", "height": "0.8"}).get_json()
    assert c["ok"]
    a2 = up(api, "/api/scanner/add-page", {"mode": "enhanced"}, jpg(img)).get_json()
    assert a2["ok"] and a2["result"]["kind"] == "scanner-page"
    import json, pymupdf
    ex = api.post("/api/scanner/export", {"pages": json.dumps([c["result"]["job_id"], a2["result"]["job_id"]]), "page_size": "a4"}).get_json()
    assert ex["ok"], ex
    doc = pymupdf.open(stream=api.download(ex["result"]), filetype="pdf")
    assert doc.page_count == 2
    assert abs(doc[0].rect.width - 595) < 2
    # reorder
    ex2 = api.post("/api/scanner/export", {"pages": json.dumps([a2["result"]["job_id"]]), "page_size": "original"}).get_json()
    assert pymupdf.open(stream=api.download(ex2["result"]), filetype="pdf").page_count == 1


def test_scanner_validation(api):
    img, _ = synth_doc()
    j = up(api, "/api/scanner/upload", {}, jpg(img)).get_json()
    r = api.post("/api/scanner/process", {"file_id": j["result"]["job_id"], "corners": "[[0,0],[1,1]]"})
    assert r.status_code == 400
    r = api.post("/api/scanner/export", {"pages": "[]"})
    assert r.status_code == 400
    r = api.post("/api/scanner/export", {"pages": '["' + "a" * 24 + '"]'})
    assert r.status_code == 404
    r = api.post("/api/scanner/filter", {"file_id": j["result"]["job_id"], "mode": "nonsense"})
    assert r.status_code == 400
