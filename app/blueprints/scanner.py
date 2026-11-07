from pathlib import Path

from flask import Blueprint

from ..services import file_manager as fm
from ..services import image_service as imgs
from ..services import scanner_service as sc
from ..utils.responses import ApiError, ok
from ..utils.security import get_sid
from .common import form_bool, form_float, form_int, form_json, form_str, result

bp = Blueprint("scanner", __name__, url_prefix="/api/scanner")
IMG = {"jpg", "png", "webp"}
MAX_EXPORT_PAGES = 100


def _save_page(sid, im, name, meta=None):
    jid, path = fm.new_output(sid, "jpg")
    imgs.write_image(im, "jpg", path, 92)
    m = {"width": im.size[0], "height": im.size[1]}
    m.update(meta or {})
    return fm.register_output(sid, jid, path, name, kind="scanner-page", meta=m)


@bp.post("/upload")
def upload():
    sid = get_sid()
    inp = fm.get_inputs(sid, "file", IMG)[0]
    im = imgs.open_image(inp.path)
    corners, found = sc.detect_corners(im)
    page = _save_page(sid, im, f"page-{Path(inp.job.display_name).stem}.jpg", {"source": "upload"})
    return result(page, corners=corners, edges_found=found)


@bp.post("/add-page")
def add_page():
    """Upload + (optionally) automatic scan in one step; used for multi-page scanning."""
    sid = get_sid()
    inp = fm.get_inputs(sid, "file", IMG)[0]
    im = imgs.open_image(inp.path)
    found = False
    if form_bool("auto_scan", True):
        corners, found = sc.detect_corners(im)
        if found:
            im = sc.warp(im, corners)
    mode = form_str("mode", "enhanced", ["original", "gray", "bw", "enhanced"])
    im = sc.apply_filter(im, mode)
    page = _save_page(sid, im, f"page-{Path(inp.job.display_name).stem}.jpg", {"auto_scanned": found, "filter": mode})
    return result(page, edges_found=found)


@bp.post("/process")
def process():
    sid = get_sid()
    inp = fm.get_inputs(sid, "file", IMG)[0]
    im = imgs.open_image(inp.path)
    corners = form_json("corners")
    found = True
    if corners is None:
        corners, found = sc.detect_corners(im)
    if not (isinstance(corners, list) and len(corners) == 4 and all(isinstance(p, list) and len(p) == 2 for p in corners)):
        raise ApiError("'corners' must be four [x, y] points.")
    try:
        corners = [[float(a), float(b)] for a, b in corners]
    except (TypeError, ValueError):
        raise ApiError("'corners' must be numeric.")
    if any(not (-0.05 <= v <= 1.05) for p in corners for v in p):
        raise ApiError("Corner points must be inside the image.")
    out = sc.warp(im, corners)
    page = _save_page(sid, out, inp.job.display_name, {"step": "perspective"})
    return result(page, edges_found=found)


@bp.post("/crop")
def crop():
    sid = get_sid()
    inp = fm.get_inputs(sid, "file", IMG)[0]
    im = imgs.open_image(inp.path)
    out = sc.crop_norm(im, form_float("x"), form_float("y"), form_float("width"), form_float("height"))
    return result(_save_page(sid, out, inp.job.display_name, {"step": "crop"}))


@bp.post("/filter")
def filt():
    sid = get_sid()
    inp = fm.get_inputs(sid, "file", IMG)[0]
    im = imgs.open_image(inp.path)
    out = sc.apply_filter(im, form_str("mode", "original"), form_int("brightness", 0, -100, 100),
                          form_float("contrast", 1.0, 0.5, 2.5), form_int("rotate", 0, -360, 360))
    return result(_save_page(sid, out, inp.job.display_name, {"step": "filter"}))


@bp.post("/export")
def export():
    sid = get_sid()
    ids = form_json("pages")
    if not isinstance(ids, list) or not ids:
        raise ApiError("'pages' must be an ordered list of page IDs.")
    if len(ids) > MAX_EXPORT_PAGES:
        raise ApiError(f"At most {MAX_EXPORT_PAGES} pages can be exported at once.")
    paths = [fm.job_path(fm.get_job(i, sid)) for i in ids]
    size = form_str("page_size", "a4", ["a4", "a3", "letter", "legal", "original"])
    jid, path = fm.new_output(sid, "pdf")
    sc.export_pdf(paths, size, path)
    name = (form_str("name", "scan") or "scan")[:60]
    job = fm.register_output(sid, jid, path, f"{name}.pdf", meta={"pages": len(paths), "page_size": size})
    return result(job, info={"pages": len(paths), "page_size": size})
