import io
import json
from pathlib import Path

from flask import Blueprint, Response, request

from ..services import file_manager as fm
from ..services import pdf_service as ps
from ..utils.responses import ApiError, ok
from ..utils.security import get_sid
from .common import form_bool, form_float, form_int, form_json, form_str, parse_page_spec, result

bp = Blueprint("pdf", __name__, url_prefix="/api/pdf")


def _pdf(sid, field="file", encrypted=False):
    return fm.get_inputs(sid, field, {"pdf"}, allow_encrypted=encrypted)[0]


def _count(path, password=None):
    with ps.open_pdf(path, password) as d:
        return d.page_count


def _stem(inp, suffix=""):
    return f"{Path(inp.job.display_name).stem}{suffix}.pdf"


def _out(sid, inp, suffix, fn, meta=None):
    jid, path = fm.new_output(sid, "pdf")
    fn(path)
    m = {"original_bytes": inp.job.size, "output_bytes": path.stat().st_size}
    m.update(meta or {})
    with ps.open_pdf(path) as d:
        m["pages"] = d.page_count
    job = fm.register_output(sid, jid, path, _stem(inp, suffix), meta=m)
    return result(job, info=m)


@bp.post("/info")
def info():
    sid = get_sid()
    inp = _pdf(sid, encrypted=True)
    pages = inp.job.meta.get("pages")
    return ok({"input": {"job_id": inp.job.id, "name": inp.job.display_name, "pages": pages,
                         "encrypted": inp.job.meta.get("encrypted", False), "size": inp.job.size}})


@bp.get("/preview/<job_id>/<int:page>")
def preview(job_id, page):
    sid = get_sid()
    job = fm.get_job(job_id, sid)
    if fm.kind_of(job) != "pdf":
        raise ApiError("Not a PDF.", 400)
    path = fm.job_path(job)
    n = _count(path)
    if not 1 <= page <= n:
        raise ApiError("Page out of range.", 404)
    dpi = max(30, min(int(request.args.get("dpi", 60)), 200))
    data = ps.render_page(path, page - 1, dpi)
    return Response(data, mimetype="image/png", headers={"Cache-Control": "no-store"})


@bp.post("/merge")
def merge():
    sid = get_sid()
    inputs = fm.get_inputs(sid, "file", {"pdf"}, multiple=True)
    if len(inputs) < 2:
        raise ApiError("Choose at least two PDF files to merge.")
    jid, path = fm.new_output(sid, "pdf")
    ps.merge([i.path for i in inputs], path)
    pages = _count(path)
    job = fm.register_output(sid, jid, path, "merged.pdf", meta={"pages": pages, "files": len(inputs)})
    return result(job, info={"pages": pages, "files": len(inputs)})


@bp.post("/split")
def split():
    sid = get_sid()
    inp = _pdf(sid)
    n = _count(inp.path)
    mode = form_str("mode", "ranges", ["ranges", "each", "every"])
    if mode == "each":
        ranges = [[i] for i in range(n)]
    elif mode == "every":
        k = form_int("every", lo=1, hi=n)
        ranges = [list(range(i, min(i + k, n))) for i in range(0, n, k)]
    else:
        spec = form_str("ranges", max_len=300)
        ranges = [parse_page_spec(part, n, False) for part in spec.replace(";", "|").split("|") if part.strip()]
        if not ranges:
            raise ApiError("Enter page ranges, e.g. 1-3;4-6.")
    if len(ranges) > 200:
        raise ApiError("Too many output files.")
    outs = []

    def out_for(i):
        jid, p = fm.new_output(sid, "pdf")
        outs.append((jid, p))
        return p
    ps.split_ranges(inp.path, ranges, out_for)
    stem = Path(inp.job.display_name).stem
    jobs = [fm.register_output(sid, j, p, f"{stem}-part{i + 1}.pdf", meta={"pages": len(r)})
            for i, ((j, p), r) in enumerate(zip(outs, ranges))]
    if len(jobs) == 1:
        return result(jobs[0], info={"parts": 1})
    z = fm.make_zip(sid, [(j.display_name, fm.job_path(j)) for j in jobs], f"{stem}-split.zip")
    return result(z, info={"parts": len(jobs), "pages_per_part": [len(r) for r in ranges]})


@bp.post("/compress")
def compress():
    sid = get_sid()
    inp = _pdf(sid)
    level = form_str("level", "medium", list(ps.LEVELS))
    jid, path = fm.new_output(sid, "pdf")
    ps.compress(inp.path, path, level)
    before, after = inp.job.size, path.stat().st_size
    info = {"original_bytes": before, "output_bytes": after, "level": level}
    if after >= before:  # never hand back a bigger file
        path.write_bytes(inp.path.read_bytes())
        info.update(output_bytes=before, note="This PDF is already well optimised - no further size reduction was possible.")
    job = fm.register_output(sid, jid, path, _stem(inp, "-compressed"), meta=info)
    return result(job, info=info)


@bp.post("/rotate")
def rotate():
    sid = get_sid()
    inp = _pdf(sid)
    n = _count(inp.path)
    angle = form_int("angle", lo=-270, hi=270)
    spec = form_str("pages", "")
    pages = parse_page_spec(spec, n, False) if spec else list(range(n))
    return _out(sid, inp, "-rotated", lambda p: ps.rotate(inp.path, pages, angle, p))


@bp.post("/reorder")
def reorder():
    sid = get_sid()
    inp = _pdf(sid)
    n = _count(inp.path)
    order = form_json("order")
    if order is None:  # also accept "3,1,2"
        order = [i + 1 for i in parse_page_spec(form_str("pages"), n)]
    if not isinstance(order, list) or not all(isinstance(i, int) and 1 <= i <= n for i in order) or not order:
        raise ApiError(f"Order must list page numbers between 1 and {n}.")
    return _out(sid, inp, "-reordered", lambda p: ps.select_pages(inp.path, [i - 1 for i in order], p))


@bp.post("/delete-pages")
def delete_pages():
    sid = get_sid()
    inp = _pdf(sid)
    n = _count(inp.path)
    drop = set(parse_page_spec(form_str("pages"), n, False))
    keep = [i for i in range(n) if i not in drop]
    if not keep:
        raise ApiError("You cannot delete every page.")
    return _out(sid, inp, "-edited", lambda p: ps.select_pages(inp.path, keep, p))


@bp.post("/extract-pages")
def extract_pages():
    sid = get_sid()
    inp = _pdf(sid)
    pages = parse_page_spec(form_str("pages"), _count(inp.path), False)
    return _out(sid, inp, "-extract", lambda p: ps.select_pages(inp.path, pages, p))


@bp.post("/duplicate-pages")
def duplicate_pages():
    sid = get_sid()
    inp = _pdf(sid)
    n = _count(inp.path)
    dup = set(parse_page_spec(form_str("pages"), n, False))
    order = []
    for i in range(n):
        order.append(i)
        if i in dup:
            order.append(i)
    return _out(sid, inp, "-duplicated", lambda p: ps.select_pages(inp.path, order, p))


@bp.post("/add-watermark")
def add_watermark():
    sid = get_sid()
    inp = _pdf(sid)
    n = _count(inp.path)
    text = form_str("text", max_len=80)
    if not text:
        raise ApiError("Enter the watermark text.")
    spec = form_str("pages", "")
    pages = parse_page_spec(spec, n, False) if spec else list(range(n))
    return _out(sid, inp, "-watermarked", lambda p: ps.watermark(
        inp.path, p, text, pages, form_float("opacity", 0.25, 0.05, 1), form_int("size", 48, 8, 200),
        form_int("angle", 45, -90, 90), form_str("color", "#808080")))


@bp.post("/add-page-numbers")
def add_page_numbers():
    sid = get_sid()
    inp = _pdf(sid)
    pos = form_str("position", "bottom-center", [f"{v}-{h}" for v in ("top", "bottom") for h in ("left", "center", "right")])
    return _out(sid, inp, "-numbered", lambda p: ps.page_numbers(
        inp.path, p, pos, form_int("start", 1, 0, 100000), form_str("format", "{n}", max_len=40), form_int("size", 10, 6, 36)))


@bp.post("/sign")
def sign():
    sid = get_sid()
    inp = _pdf(sid)
    sig = None
    fs = request.files.get("signature_file")
    if fs and fs.filename:
        sig = ps.decode_signature(fs.read(5_000_001))
    elif request.form.get("signature"):
        sig = ps.decode_signature(request.form["signature"])
    placements = form_json("placements", []) or []
    annotations = form_json("annotations", []) or []
    if placements and not sig:
        raise ApiError("Draw or upload a signature first.")
    if not placements and not annotations:
        raise ApiError("Place a signature or add a text annotation first.")
    if len(placements) > 50 or len(annotations) > 200:
        raise ApiError("Too many items.")
    try:
        return _out(sid, inp, "-signed", lambda p: ps.sign(inp.path, p, sig, placements, annotations),
                    {"signature_type": "drawn (visual) - not a cryptographic digital signature"})
    except (KeyError, TypeError, ValueError):
        raise ApiError("Signature or annotation data is malformed.")


@bp.post("/protect")
def protect():
    sid = get_sid()
    inp = _pdf(sid)
    pw = request.form.get("password", "")
    if not 4 <= len(pw) <= 128:
        raise ApiError("Password must be 4-128 characters.")
    jid, path = fm.new_output(sid, "pdf")
    ps.protect(inp.path, path, pw)
    job = fm.register_output(sid, jid, path, _stem(inp, "-protected"), meta={"encrypted": True, "cipher": "AES-256"})
    return result(job, info={"encrypted": True, "cipher": "AES-256"})


@bp.post("/unlock")
def unlock():
    sid = get_sid()
    inp = _pdf(sid, encrypted=True)
    pw = request.form.get("password", "")
    jid, path = fm.new_output(sid, "pdf")
    ps.unlock(inp.path, path, pw)
    job = fm.register_output(sid, jid, path, _stem(inp, "-unlocked"), meta={"pages": _count(path)})
    return result(job, info={"unlocked": True})


@bp.post("/to-images")
def to_images():
    sid = get_sid()
    inp = _pdf(sid)
    n = _count(inp.path)
    fmt = form_str("format", "png", ["png", "jpg"])
    dpi = form_int("dpi", 150, 50, 300)
    spec = form_str("pages", "")
    pages = parse_page_spec(spec, n, False) if spec else list(range(n))
    stem = Path(inp.job.display_name).stem
    jobs = []
    for i in pages:
        data = ps.render_page(inp.path, i, dpi, fmt)
        jid, path = fm.new_output(sid, fmt)
        path.write_bytes(data)
        jobs.append(fm.register_output(sid, jid, path, f"{stem}-page{i + 1}.{fmt}", meta={"page": i + 1, "dpi": dpi}))
    if len(jobs) == 1:
        return result(jobs[0], info={"pages": 1, "dpi": dpi})
    z = fm.make_zip(sid, [(j.display_name, fm.job_path(j)) for j in jobs], f"{stem}-images.zip")
    return result(z, info={"pages": len(jobs), "dpi": dpi})


@bp.post("/to-text")
def to_text():
    sid = get_sid()
    inp = _pdf(sid)
    text, empty = ps.to_text(inp.path)
    jid, path = fm.new_output(sid, "txt")
    path.write_text(text, encoding="utf-8")
    job = fm.register_output(sid, jid, path, _stem(inp).replace(".pdf", ".txt"), meta={"pages_without_text": empty})
    info = {"characters": len(text), "pages_without_text": empty}
    if empty:
        info["warning"] = f"Pages {', '.join(map(str, empty))} contain no extractable text (likely scanned images)."
    return result(job, info=info)
