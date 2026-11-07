from pathlib import Path

from flask import Blueprint, current_app

from ..services import capabilities as caps
from ..services import convert_service as cs
from ..services import file_manager as fm
from ..services import image_service as imgs
from ..services import pdf_service as ps
from ..utils.responses import ApiError, ok
from ..utils.security import get_sid
from .common import form_float, form_int, form_str, parse_page_spec, result

bp = Blueprint("convert", __name__, url_prefix="/api/convert")
IMG = {"jpg", "png", "webp"}

MATRIX = [
    ("image-to-pdf", "JPG / PNG / WebP", "PDF", None),
    ("pdf-to-image", "PDF", "JPG / PNG", None),
    ("docx-to-pdf", "DOCX", "PDF", "libreoffice"),
    ("pdf-to-docx", "PDF", "DOCX", None),
    ("pptx-to-pdf", "PPTX", "PDF", "libreoffice"),
    ("xlsx-to-pdf", "XLSX", "PDF", "libreoffice"),
    ("xlsx-to-csv", "XLSX", "CSV", None),
    ("csv-to-xlsx", "CSV", "XLSX", None),
    ("docx-to-txt", "DOCX", "TXT", None),
    ("image-format", "JPG / PNG / WebP", "JPG / PNG / WebP", None),
]


@bp.get("/capabilities")
def capabilities():
    c = caps.detect()
    items = []
    for key, src, dst, needs in MATRIX:
        available = c["libreoffice"] if needs == "libreoffice" else True
        items.append({"id": key, "from": src, "to": dst, "available": available,
                      "requires": needs, "limitations": cs.LIMITATIONS[key]})
    return ok({"conversions": items})


def _office(kind, key):
    sid = get_sid()
    inp = fm.get_inputs(sid, "file", {kind})[0]
    jid, path = fm.new_output(sid, "pdf")
    cs.lo_to_pdf(inp.path, path, current_app.config)
    import pymupdf
    with pymupdf.open(path) as d:
        pages = d.page_count
    job = fm.register_output(sid, jid, path, Path(inp.job.display_name).stem + ".pdf", meta={"pages": pages})
    return result(job, info={"pages": pages, "note": cs.LIMITATIONS[key]})


@bp.post("/docx-to-pdf")
def docx_to_pdf():
    return _office("docx", "docx-to-pdf")


@bp.post("/pptx-to-pdf")
def pptx_to_pdf():
    return _office("pptx", "pptx-to-pdf")


@bp.post("/xlsx-to-pdf")
def xlsx_to_pdf():
    return _office("xlsx", "xlsx-to-pdf")


@bp.post("/pdf-to-docx")
def pdf_to_docx():
    sid = get_sid()
    inp = fm.get_inputs(sid, "file", {"pdf"})[0]
    jid, path = fm.new_output(sid, "docx")
    done, total = cs.pdf_to_docx(inp.path, path)
    job = fm.register_output(sid, jid, path, Path(inp.job.display_name).stem + ".docx", meta={"pages": done})
    info = {"pages_converted": done, "total_pages": total, "note": cs.LIMITATIONS["pdf-to-docx"]}
    if done < total:
        info["warning"] = f"Only the first {done} of {total} pages were converted."
    return result(job, info=info)


@bp.post("/xlsx-to-csv")
def xlsx_to_csv():
    sid = get_sid()
    inp = fm.get_inputs(sid, "file", {"xlsx"})[0]
    sheet = form_str("sheet", "") or None
    sheets = cs.xlsx_to_csvs(inp.path, sheet)
    stem = Path(inp.job.display_name).stem
    jobs = []
    for name, text in sheets:
        jid, p = fm.new_output(sid, "csv")
        p.write_text(text, encoding="utf-8-sig")
        jobs.append(fm.register_output(sid, jid, p, f"{stem}-{name}.csv" if len(sheets) > 1 else f"{stem}.csv"))
    if len(jobs) == 1:
        return result(jobs[0], info={"sheets": 1})
    z = fm.make_zip(sid, [(j.display_name, fm.job_path(j)) for j in jobs], f"{stem}-csv.zip")
    return result(z, info={"sheets": len(jobs)})


@bp.post("/csv-to-xlsx")
def csv_to_xlsx():
    sid = get_sid()
    inp = fm.get_inputs(sid, "file", {"csv", "txt"})[0]
    jid, path = fm.new_output(sid, "xlsx")
    rows = cs.csv_to_xlsx(inp.path, path)
    job = fm.register_output(sid, jid, path, Path(inp.job.display_name).stem + ".xlsx", meta={"rows": rows})
    return result(job, info={"rows": rows})


@bp.post("/docx-to-txt")
def docx_to_txt():
    sid = get_sid()
    inp = fm.get_inputs(sid, "file", {"docx"})[0]
    text = cs.docx_to_text(inp.path)
    jid, path = fm.new_output(sid, "txt")
    path.write_text(text, encoding="utf-8")
    job = fm.register_output(sid, jid, path, Path(inp.job.display_name).stem + ".txt")
    return result(job, info={"characters": len(text)})


@bp.post("/image-to-pdf")
def image_to_pdf():
    sid = get_sid()
    inputs = fm.get_inputs(sid, "file", IMG, multiple=True)
    size = form_str("page_size", "a4", ["a4", "a3", "letter", "legal", "fit", "custom"])
    custom = None
    if size == "custom":
        custom = (form_float("width_mm", lo=20, hi=1500), form_float("height_mm", lo=20, hi=1500))
    jid, path = fm.new_output(sid, "pdf")
    ps.images_to_pdf([i.path for i in inputs], path, size, form_str("orientation", "auto", ["auto", "portrait", "landscape"]),
                     form_float("margin_mm", 10, 0, 50), custom)
    name = Path(inputs[0].job.display_name).stem + ("" if len(inputs) == 1 else "-and-more") + ".pdf"
    job = fm.register_output(sid, jid, path, name, meta={"pages": len(inputs)})
    return result(job, info={"pages": len(inputs), "page_size": size})


@bp.post("/pdf-to-image")
def pdf_to_image():
    from .pdf import to_images
    return to_images()


@bp.post("/image-format")
def image_format():
    from .image import convert
    return convert()
