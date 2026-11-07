import base64
import io
import json

import pymupdf
from PIL import Image, ImageDraw

from tests.conftest import make_pdf, png_bytes


def up(api, url, data=None, content=None, name="a.pdf", field="file"):
    d = dict(data or {})
    d[field] = (io.BytesIO(content if content is not None else make_pdf(5)), name)
    return api.post(url, d)


def doc_of(api, j):
    return pymupdf.open(stream=api.download(j["result"]), filetype="pdf")


def test_merge(api):
    d = {"file": [(io.BytesIO(make_pdf(2, "A")), "a.pdf"), (io.BytesIO(make_pdf(3, "B")), "b.pdf")]}
    j = api.post("/api/pdf/merge", d).get_json()
    doc = doc_of(api, j)
    assert doc.page_count == 5 and "A 1" in doc[0].get_text() and "B 1" in doc[2].get_text()
    assert api.post("/api/pdf/merge", {"file": (io.BytesIO(make_pdf(1)), "a.pdf")}).status_code == 400


def test_split_ranges_and_each(api):
    j = up(api, "/api/pdf/split", {"mode": "ranges", "ranges": "1-2;3-5"}).get_json()
    import zipfile
    z = zipfile.ZipFile(io.BytesIO(api.download(j["result"])))
    assert len(z.namelist()) == 2
    assert pymupdf.open(stream=z.read(z.namelist()[1]), filetype="pdf").page_count == 3
    j = up(api, "/api/pdf/split", {"mode": "each"}).get_json()
    assert j["info"]["parts"] == 5
    assert up(api, "/api/pdf/split", {"mode": "ranges", "ranges": "1-9"}).status_code == 400


def test_rotate_reorder_delete_extract_duplicate(api):
    j = up(api, "/api/pdf/rotate", {"angle": "90", "pages": "2"}).get_json()
    d = doc_of(api, j)
    assert d[1].rotation == 90 and d[0].rotation == 0
    j = up(api, "/api/pdf/reorder", {"order": "[5,4,3,2,1]"}).get_json()
    assert "page 5" in doc_of(api, j)[0].get_text().lower() or "5" in doc_of(api, j)[0].get_text()
    j = up(api, "/api/pdf/delete-pages", {"pages": "1,3"}).get_json()
    assert doc_of(api, j).page_count == 3
    j = up(api, "/api/pdf/extract-pages", {"pages": "2-3"}).get_json()
    d = doc_of(api, j)
    assert d.page_count == 2 and "2" in d[0].get_text()
    j = up(api, "/api/pdf/duplicate-pages", {"pages": "1"}).get_json()
    d = doc_of(api, j)
    assert d.page_count == 6 and d[0].get_text() == d[1].get_text()
    assert up(api, "/api/pdf/delete-pages", {"pages": "1-5"}).status_code == 400


def test_compress_never_larger_and_valid(api):
    # PDF with a big noisy image
    pdf = pymupdf.open()
    p = pdf.new_page()
    p.insert_image(p.rect, stream=png_bytes(1800, 1400, noise=True, fmt="PNG"))
    data = pdf.tobytes()
    j = up(api, "/api/pdf/compress", {"level": "high"}, data).get_json()
    out = api.download(j["result"])
    assert len(out) <= len(data) and j["info"]["output_bytes"] == len(out)
    assert len(out) < len(data) * 0.8
    assert pymupdf.open(stream=out, filetype="pdf").page_count == 1
    j = up(api, "/api/pdf/compress", {"level": "low"}, make_pdf(1)).get_json()
    assert j["info"]["output_bytes"] <= j["info"]["original_bytes"]


def test_watermark_and_numbers(api):
    j = up(api, "/api/pdf/add-watermark", {"text": "CONFIDENTIAL"}).get_json()
    assert "CONFIDENTIAL" in doc_of(api, j)[0].get_text()
    j = up(api, "/api/pdf/add-page-numbers", {"format": "Page {n} of {total}", "position": "bottom-right"}).get_json()
    d = doc_of(api, j)
    assert "Page 3 of 5" in d[2].get_text()
    assert up(api, "/api/pdf/add-watermark", {"text": "नमस्ते"}).status_code == 400
    assert up(api, "/api/pdf/add-page-numbers", {"format": "nothing"}).status_code == 400


def sig_data_url():
    im = Image.new("RGBA", (300, 100), (0, 0, 0, 0))
    ImageDraw.Draw(im).line([(10, 80), (100, 10), (200, 80), (290, 20)], fill=(0, 0, 90, 255), width=5)
    b = io.BytesIO(); im.save(b, "PNG")
    return "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()


def test_sign_and_annotate(api):
    pl = json.dumps([{"page": 1, "x": 0.5, "y": 0.7, "w": 0.3}])
    an = json.dumps([{"page": 2, "x": 0.1, "y": 0.1, "text": "Approved by DASTAVEJ", "size": 14}])
    j = up(api, "/api/pdf/sign", {"signature": sig_data_url(), "placements": pl, "annotations": an}).get_json()
    assert j["ok"], j
    d = doc_of(api, j)
    assert len(d[0].get_images()) == 1 and "Approved by DASTAVEJ" in d[1].get_text()
    assert "not a cryptographic" in j["info"]["signature_type"]
    assert up(api, "/api/pdf/sign", {"placements": pl}).status_code == 400
    empty = "data:image/png;base64," + base64.b64encode(
        (lambda b: (Image.new("RGBA", (50, 50), (0, 0, 0, 0)).save(b, "PNG"), b.getvalue())[1])(io.BytesIO())).decode()
    assert up(api, "/api/pdf/sign", {"signature": empty, "placements": pl}).status_code == 400


def test_protect_and_unlock(api):
    j = up(api, "/api/pdf/protect", {"password": "s3cret!"}).get_json()
    enc = api.download(j["result"])
    d = pymupdf.open(stream=enc, filetype="pdf")
    assert d.needs_pass and not d.authenticate("wrong")
    # protected file can't be used by other tools, but unlock accepts it
    r = api.post("/api/pdf/unlock", {"file_id": j["result"]["job_id"], "password": "bad"})
    assert r.status_code == 400 and "password" in r.get_json()["error"]["message"].lower()
    r = api.post("/api/pdf/unlock", {"file_id": j["result"]["job_id"], "password": "s3cret!"}).get_json()
    d2 = doc_of(api, r)
    assert not d2.needs_pass and d2.page_count == 5
    r = api.post("/api/pdf/compress", {"file_id": j["result"]["job_id"]})
    assert r.status_code == 400  # encrypted PDFs rejected by other tools
    assert up(api, "/api/pdf/protect", {"password": "ab"}).status_code == 400


def test_to_images_text_preview_info(api):
    j = up(api, "/api/pdf/to-images", {"format": "png", "dpi": "100", "pages": "1"}).get_json()
    im = Image.open(io.BytesIO(api.download(j["result"])))
    assert abs(im.size[0] - 827) < 3  # A4 @100dpi
    j = up(api, "/api/pdf/to-images", {"format": "jpg", "dpi": "72"}).get_json()
    assert j["result"]["mime"] == "application/zip" and j["info"]["pages"] == 5
    j = up(api, "/api/pdf/to-text").get_json()
    assert "Hello DASTAVEJ page 3" in api.download(j["result"]).decode()
    j = up(api, "/api/pdf/info").get_json()
    assert j["input"]["pages"] == 5
    r = api.get(f"/api/pdf/preview/{j['input']['job_id']}/2")
    assert r.status_code == 200 and r.data[:4] == b"\x89PNG"
    assert api.get(f"/api/pdf/preview/{j['input']['job_id']}/99").status_code == 404


def test_scanned_page_text_warning(api):
    pdf = pymupdf.open(); p = pdf.new_page(); p.insert_image(p.rect, stream=png_bytes(300, 300))
    j = up(api, "/api/pdf/to-text", content=pdf.tobytes()).get_json()
    assert j["info"]["pages_without_text"] == [1] and "warning" in j["info"]


def test_corrupt_and_wrong_type(api):
    assert up(api, "/api/pdf/merge", content=b"%PDF-1.4 garbage").status_code in (400,)
    r = up(api, "/api/pdf/compress", content=png_bytes())
    assert r.status_code == 415
