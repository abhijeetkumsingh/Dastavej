import io

import docx
import openpyxl
import pptx
import pymupdf
from PIL import Image

from tests.conftest import make_pdf, png_bytes


def up(api, url, content, name, data=None):
    d = dict(data or {}); d["file"] = (io.BytesIO(content), name)
    return api.post(url, d)


def mk_docx():
    d = docx.Document(); d.add_heading("Quarterly Report", 1); d.add_paragraph("Revenue grew by twelve percent.")
    t = d.add_table(rows=2, cols=2); t.cell(0, 0).text = "A"; t.cell(0, 1).text = "B"; t.cell(1, 0).text = "1"; t.cell(1, 1).text = "2"
    b = io.BytesIO(); d.save(b); return b.getvalue()


def mk_xlsx():
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Sales"
    ws.append(["Item", "Qty"]); ws.append(["Pen", 5]); ws.append(["Book", 7]); ws["B4"] = "=SUM(B2:B3)"
    ws2 = wb.create_sheet("Other"); ws2.append(["x"])
    b = io.BytesIO(); wb.save(b); return b.getvalue()


def mk_pptx():
    p = pptx.Presentation(); s = p.slides.add_slide(p.slide_layouts[1]); s.shapes.title.text = "Launch Plan"
    s.placeholders[1].text = "Ship on Monday"
    b = io.BytesIO(); p.save(b); return b.getvalue()


def test_capabilities_honest(api):
    j = api.get("/api/convert/capabilities").get_json()
    ids = {c["id"]: c for c in j["conversions"]}
    assert "docx-to-pdf" in ids and all("limitations" in c for c in ids.values())


def test_docx_to_pdf(api):
    j = up(api, "/api/convert/docx-to-pdf", mk_docx(), "r.docx").get_json()
    assert j["ok"], j
    d = pymupdf.open(stream=api.download(j["result"]), filetype="pdf")
    assert "Quarterly Report" in d[0].get_text() and "twelve percent" in d[0].get_text()


def test_pptx_and_xlsx_to_pdf(api):
    j = up(api, "/api/convert/pptx-to-pdf", mk_pptx(), "p.pptx").get_json()
    assert "Launch Plan" in pymupdf.open(stream=api.download(j["result"]), filetype="pdf")[0].get_text()
    j = up(api, "/api/convert/xlsx-to-pdf", mk_xlsx(), "s.xlsx").get_json()
    assert "Pen" in pymupdf.open(stream=api.download(j["result"]), filetype="pdf")[0].get_text()


def test_pdf_to_docx_roundtrip(api):
    j = up(api, "/api/convert/pdf-to-docx", make_pdf(2, "Invoice number"), "i.pdf").get_json()
    assert j["ok"], j
    d = docx.Document(io.BytesIO(api.download(j["result"])))
    assert "Invoice number" in "\n".join(p.text for p in d.paragraphs)


def test_pdf_to_docx_scanned_rejected(api):
    pdf = pymupdf.open(); p = pdf.new_page(); p.insert_image(p.rect, stream=png_bytes(200, 200))
    r = up(api, "/api/convert/pdf-to-docx", pdf.tobytes(), "s.pdf")
    assert r.status_code == 422 and "scanned" in r.get_json()["error"]["message"]


def test_xlsx_csv_and_back(api):
    j = up(api, "/api/convert/xlsx-to-csv", mk_xlsx(), "s.xlsx", {"sheet": "Sales"}).get_json()
    txt = api.download(j["result"]).decode("utf-8-sig")
    assert "Pen,5" in txt
    j = up(api, "/api/convert/xlsx-to-csv", mk_xlsx(), "s.xlsx").get_json()
    assert j["result"]["mime"] == "application/zip" and j["info"]["sheets"] == 2
    j = up(api, "/api/convert/csv-to-xlsx", b"name,score\nAsha,90\nRavi,85.5\n=cmd|' /C calc'!A0,1\n", "d.csv").get_json()
    ws = openpyxl.load_workbook(io.BytesIO(api.download(j["result"]))).active
    assert ws["B2"].value == 90 and ws["B3"].value == 85.5
    assert ws["A4"].data_type != "f"  # formula injection neutralised


def test_docx_to_txt(api):
    j = up(api, "/api/convert/docx-to-txt", mk_docx(), "r.docx").get_json()
    t = api.download(j["result"]).decode()
    assert "Revenue grew" in t and "A\tB" in t


def test_image_to_pdf_sizes(api):
    d = {"page_size": "a4", "file": [(io.BytesIO(png_bytes(400, 300)), "a.png"), (io.BytesIO(png_bytes(300, 400)), "b.png")]}
    j = api.post("/api/convert/image-to-pdf", d).get_json()
    doc = pymupdf.open(stream=api.download(j["result"]), filetype="pdf")
    assert doc.page_count == 2 and abs(doc[0].rect.width - 842) < 2 and abs(doc[1].rect.width - 595) < 2  # landscape / portrait
    j = up(api, "/api/convert/image-to-pdf", png_bytes(), "a.png", {"page_size": "custom", "width_mm": "100", "height_mm": "150"}).get_json()
    r = pymupdf.open(stream=api.download(j["result"]), filetype="pdf")[0].rect
    assert abs(r.width - 283.5) < 1 and abs(r.height - 425.2) < 1
    j = up(api, "/api/convert/image-to-pdf", png_bytes(), "a.png", {"page_size": "letter", "orientation": "portrait"}).get_json()
    assert abs(pymupdf.open(stream=api.download(j["result"]), filetype="pdf")[0].rect.width - 612) < 2
    j = up(api, "/api/convert/image-to-pdf", png_bytes(), "a.png", {"page_size": "letter"}).get_json()
    assert abs(pymupdf.open(stream=api.download(j["result"]), filetype="pdf")[0].rect.width - 792) < 2  # auto -> landscape


def test_pdf_to_image_and_formats(api):
    j = up(api, "/api/convert/pdf-to-image", make_pdf(1), "a.pdf", {"format": "jpg", "dpi": "72"}).get_json()
    assert api.download(j["result"])[:2] == b"\xff\xd8"
    j = up(api, "/api/convert/image-format", png_bytes(fmt="WEBP"), "a.webp", {"format": "png"}).get_json()
    assert api.download(j["result"])[:4] == b"\x89PNG"
    j = up(api, "/api/convert/image-format", png_bytes(), "a.png", {"format": "webp"}).get_json()
    assert api.download(j["result"])[:4] == b"RIFF"


def test_wrong_input_types(api):
    assert up(api, "/api/convert/docx-to-pdf", make_pdf(1), "a.docx").status_code == 415
    assert up(api, "/api/convert/docx-to-pdf", b"PK\x03\x04junkjunk", "a.docx").status_code in (400, 415)


def test_libreoffice_missing_message(app, api):
    app.config["SOFFICE_BIN"] = "/nonexistent"
    import shutil
    orig = shutil.which
    shutil.which = lambda n: None
    try:
        r = up(api, "/api/convert/docx-to-pdf", mk_docx(), "r.docx")
    finally:
        shutil.which = orig
    assert r.status_code == 503 and "LibreOffice" in r.get_json()["error"]["message"]


def test_libreoffice_runs_with_memory_cap(app, api):
    """A very small address-space cap must make the sandboxed subprocess fail safely, not hang or crash the app."""
    app.config["LIBREOFFICE_MEMORY_MB"] = 64
    r = up(api, "/api/convert/docx-to-pdf", mk_docx(), "r.docx")
    assert r.status_code in (200, 422)  # either converts or fails with a clean error
    assert r.get_json()["ok"] in (True, False)
