"""Unified text extraction from PDF/DOCX/PPTX/XLSX/CSV/TXT/images with OCR fallback."""
import csv
import io

import pymupdf

from . import capabilities as caps
from . import image_service as imgs
from . import ocr_service as ocr

ROWS_PER_CHUNK = 40


def _unit(page, label, text, source):
    return {"page": page, "label": label, "text": text.strip(), "source": source}


def extract(path, kind, cfg, ocr_langs=None):
    """Return dict(units, failed, ocr_pages, pages, warnings, low_confidence)."""
    res = {"units": [], "failed": [], "ocr_pages": [], "pages": None, "warnings": [], "low_confidence": []}
    fn = {"pdf": _pdf, "docx": _docx, "pptx": _pptx, "xlsx": _xlsx, "csv": _csv, "txt": _txt,
          "jpg": _image, "png": _image, "webp": _image}[kind]
    fn(path, cfg, res, ocr_langs)
    res["units"] = [u for u in res["units"] if u["text"]]
    return res


def _try_ocr(im, cfg, langs):
    try:
        lang, missing = ocr.langs_for(langs, cfg["OCR_LANGS"])
        text, conf = ocr.ocr_image(im, lang)
        return text, conf, None
    except Exception as e:  # ApiError or anything else: record as failure, never claim success
        return "", None, getattr(e, "message", "OCR failed")


def _pdf(path, cfg, res, langs):
    doc = pymupdf.open(path)
    res["pages"] = doc.page_count
    ocr_budget = cfg["OCR_MAX_PAGES"]
    for i, page in enumerate(doc):
        n = i + 1
        try:
            text = page.get_text().strip()
        except Exception:
            text = ""
        if len(text) >= 20:
            res["units"].append(_unit(n, f"Page {n}", text, "text"))
            try:
                for t in page.find_tables().tables:
                    rows = t.extract()
                    md = "\n".join(" | ".join("" if c is None else str(c).replace("\n", " ") for c in r) for r in rows)
                    if md.strip():
                        res["units"].append(_unit(n, f"Page {n} (table)", md, "table"))
            except Exception:
                pass
            continue
        # scanned / image-only page -> OCR
        if ocr_budget <= 0:
            res["failed"].append({"page": n, "reason": f"OCR page limit ({cfg['OCR_MAX_PAGES']}) reached"})
            continue
        ocr_budget -= 1
        try:
            pix = page.get_pixmap(dpi=200, alpha=False)
            from PIL import Image
            im = Image.open(io.BytesIO(pix.tobytes("png")))
        except Exception:
            res["failed"].append({"page": n, "reason": "page could not be rendered"})
            continue
        t, conf, err = _try_ocr(im, cfg, langs)
        if err:
            res["failed"].append({"page": n, "reason": err})
        elif not t.strip():
            res["failed"].append({"page": n, "reason": "no text recognised"})
        else:
            res["units"].append(_unit(n, f"Page {n} (OCR)", t, "ocr"))
            res["ocr_pages"].append(n)
            if conf is not None and conf < 60:
                res["low_confidence"].append({"page": n, "confidence": conf})
    doc.close()


def _docx(path, cfg, res, langs):
    import docx
    d = docx.Document(str(path))
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    parts = []
    for el in d.element.body.iterchildren():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "p":
            t = Paragraph(el, d).text
            if t.strip():
                parts.append(t)
        elif tag == "tbl":
            tbl = Table(el, d)
            for r in tbl.rows:
                parts.append(" | ".join(c.text.replace("\n", " ") for c in r.cells))
    _sections(parts, res, "Section")
    res["warnings"].append("DOCX files have no fixed pages, so sources are labelled by section.")


def _sections(parts, res, label, limit=2500):
    buf, n = [], 1
    size = 0
    for p in parts:
        buf.append(p)
        size += len(p)
        if size >= limit:
            res["units"].append(_unit(None, f"{label} {n}", "\n".join(buf), "text"))
            buf, size, n = [], 0, n + 1
    if buf:
        res["units"].append(_unit(None, f"{label} {n}", "\n".join(buf), "text"))


def _pptx(path, cfg, res, langs):
    import pptx
    prs = pptx.Presentation(str(path))
    res["pages"] = len(prs.slides)
    for i, s in enumerate(prs.slides, 1):
        lines = []
        for sh in s.shapes:
            if sh.has_text_frame:
                lines.append(sh.text_frame.text)
            if getattr(sh, "has_table", False) and sh.has_table:
                for r in sh.table.rows:
                    lines.append(" | ".join(c.text for c in r.cells))
        if s.has_notes_slide:
            lines.append("Notes: " + s.notes_slide.notes_text_frame.text)
        res["units"].append(_unit(i, f"Slide {i}", "\n".join(lines), "text"))


def _rows_to_units(label, header, rows, res):
    for start in range(0, len(rows), ROWS_PER_CHUNK):
        block = rows[start:start + ROWS_PER_CHUNK]
        text = " | ".join(header) + "\n" + "\n".join(" | ".join(r) for r in block)
        res["units"].append(_unit(None, f"{label} rows {start + 2}-{start + 1 + len(block)}", text, "table"))


def _xlsx(path, cfg, res, langs):
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    res["pages"] = len(wb.sheetnames)
    uncalculated = False
    for name in wb.sheetnames:
        rows = [["" if v is None else str(v) for v in r] for r in wb[name].iter_rows(values_only=True)]
        rows = [r for r in rows if any(c.strip() for c in r)]
        if not rows:
            continue
        _rows_to_units(f"Sheet '{name}'", rows[0], rows[1:], res) if len(rows) > 1 else res["units"].append(
            _unit(None, f"Sheet '{name}'", " | ".join(rows[0]), "table"))
    wb.close()
    if uncalculated:
        res["warnings"].append("Some formula cells had no stored value.")


def _read_text(path):
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-8", "utf-16", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _csv(path, cfg, res, langs):
    text = _read_text(path)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    if not rows:
        return
    if len(rows) == 1:
        res["units"].append(_unit(None, "Row 1", " | ".join(rows[0]), "table"))
    else:
        _rows_to_units("Table", rows[0], rows[1:], res)


def _txt(path, cfg, res, langs):
    text = _read_text(path)
    _sections([p for p in text.split("\n")], res, "Part")


def _image(path, cfg, res, langs):
    im = imgs.open_image(path)
    res["pages"] = 1
    t, conf, err = _try_ocr(im, cfg, langs)
    if err:
        res["failed"].append({"page": 1, "reason": err})
    elif not t.strip():
        res["failed"].append({"page": 1, "reason": "no text recognised"})
    else:
        res["units"].append(_unit(1, "Image (OCR)", t, "ocr"))
        res["ocr_pages"].append(1)
        if conf is not None and conf < 60:
            res["low_confidence"].append({"page": 1, "confidence": conf})
