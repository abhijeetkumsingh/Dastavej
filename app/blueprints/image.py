from pathlib import Path

from flask import Blueprint

from ..services import file_manager as fm
from ..services import image_service as imgs
from ..services import passport_service as pp
from ..utils.responses import ApiError, ok
from ..utils.security import get_sid
from .common import form_bool, form_float, form_int, form_str, result

bp = Blueprint("image", __name__, url_prefix="/api/image")
IMG = {"jpg", "png", "webp"}


def _stem(job):
    return Path(job.display_name).stem or "image"


def _batch(sid, inputs, fn, suffix):
    """Run fn(im, input) -> (ext, quality, extra_info) for each input; zip when several."""
    outs, infos = [], []
    for inp in inputs:
        im = imgs.open_image(inp.path)
        ext, quality, extra, im_out = fn(im, inp)
        jid, path = fm.new_output(sid, ext)
        size = imgs.write_image(im_out, ext, path, quality)
        info = {"original_bytes": inp.job.size, "output_bytes": path.stat().st_size,
                "original_size_px": list(im.size), "output_size_px": list(im_out.size)}
        info.update(extra or {})
        job = fm.register_output(sid, jid, path, f"{_stem(inp.job)}{suffix}.{ext}", meta=info)
        outs.append(job)
        infos.append(info)
    if len(outs) == 1:
        return result(outs[0], info=infos[0])
    z = fm.make_zip(sid, [(j.display_name, fm.job_path(j)) for j in outs], "dastavej-images.zip")
    return result(z, info={"files": len(outs), "items": [dict(name=j.display_name, **i) for j, i in zip(outs, infos)]})


@bp.post("/resize")
def resize():
    sid = get_sid()
    inputs = fm.get_inputs(sid, "file", IMG, multiple=True)
    w = form_int("width", 0, 1, 20000) or None
    h = form_int("height", 0, 1, 20000) or None
    pct = form_float("percent", 0, 0, 1000)
    keep = form_bool("keep_aspect", True)
    fmt, q = form_str("format", "same"), form_int("quality", 90, 1, 100)

    def fn(im, inp):
        if pct:
            nw, nh = round(im.size[0] * pct / 100), round(im.size[1] * pct / 100)
            out = imgs.resize(im, nw, nh, False)
        else:
            out = imgs.resize(im, w, h, keep)
        return imgs.resolve_format(fmt, inp.kind), q, None, out
    return _batch(sid, inputs, fn, "-resized")


@bp.post("/compress")
def compress():
    sid = get_sid()
    inputs = fm.get_inputs(sid, "file", IMG, multiple=True)
    mode = form_str("mode", "target", ["target", "quality"])
    fmt = form_str("format", "same")
    q = form_int("quality", 75, 1, 100)
    target = form_float("target_size", 0, 0, 100000) if mode == "target" else 0
    unit = form_str("target_unit", "KB", ["KB", "MB"])
    if mode == "target" and target <= 0:
        raise ApiError("Enter a target size greater than zero.")
    target_bytes = int(target * (1024 if unit == "KB" else 1024 * 1024))
    outs, infos = [], []
    for inp in inputs:
        im = imgs.open_image(inp.path)
        ext = imgs.resolve_format(fmt, inp.kind)
        if mode == "target":
            data, info = imgs.compress_to_target(im, target_bytes, ext)
        else:
            data = imgs.encode(im, ext, q)
            info = {"quality": q, "width": im.size[0], "height": im.size[1], "output_bytes": len(data)}
        jid, path = fm.new_output(sid, ext)
        path.write_bytes(data)
        actual = path.stat().st_size  # verify the real file on disk
        info["output_bytes"] = actual
        info["original_bytes"] = inp.job.size
        if mode == "target":
            info["target_met"] = actual <= target_bytes
            if not info["target_met"]:
                info["warning"] = ("Could not reach the target size without making the image unusably small. "
                                   "This is the smallest result achieved.")
        job = fm.register_output(sid, jid, path, f"{_stem(inp.job)}-compressed.{ext}", meta=info)
        outs.append(job)
        infos.append(info)
    if len(outs) == 1:
        return result(outs[0], info=infos[0])
    z = fm.make_zip(sid, [(j.display_name, fm.job_path(j)) for j in outs], "dastavej-compressed.zip")
    return result(z, info={"files": len(outs), "items": [dict(name=j.display_name, **i) for j, i in zip(outs, infos)]})


@bp.post("/convert")
def convert():
    sid = get_sid()
    inputs = fm.get_inputs(sid, "file", IMG, multiple=True)
    fmt = form_str("format", choices=["jpg", "jpeg", "png", "webp"])
    q = form_int("quality", 90, 1, 100)
    return _batch(sid, inputs, lambda im, inp: (imgs.resolve_format(fmt, inp.kind), q, None, im), "")


@bp.post("/enhance")
def enhance():
    sid = get_sid()
    inputs = fm.get_inputs(sid, "file", IMG, multiple=True)
    b, c = form_float("brightness", 1, 0.2, 3), form_float("contrast", 1, 0.2, 3)
    s, sat = form_float("sharpness", 1, 0, 4), form_float("saturation", 1, 0, 3)
    auto, noise = form_bool("auto"), form_float("noise_reduction", 0, 0, 15)
    fmt, q = form_str("format", "same"), form_int("quality", 92, 1, 100)
    return _batch(sid, inputs, lambda im, inp: (
        imgs.resolve_format(fmt, inp.kind), q, None, imgs.enhance(im, b, c, s, sat, auto, noise)), "-enhanced")


@bp.post("/crop")
def crop():
    sid = get_sid()
    inputs = fm.get_inputs(sid, "file", IMG)
    x, y = form_float("x", lo=0), form_float("y", lo=0)
    w, h = form_float("width", lo=1), form_float("height", lo=1)
    fmt, q = form_str("format", "same"), form_int("quality", 92, 1, 100)
    return _batch(sid, inputs, lambda im, inp: (
        imgs.resolve_format(fmt, inp.kind), q, None, imgs.crop(im, x, y, w, h)), "-cropped")


@bp.post("/rotate")
def rotate():
    sid = get_sid()
    inputs = fm.get_inputs(sid, "file", IMG, multiple=True)
    angle = form_float("angle", lo=-360, hi=360)
    fmt, q = form_str("format", "same"), form_int("quality", 92, 1, 100)
    return _batch(sid, inputs, lambda im, inp: (
        imgs.resolve_format(fmt, inp.kind), q, None, imgs.rotate(im, angle)), "-rotated")


def _passport_dims():
    preset = form_str("preset", "india-passport", list(pp.PRESETS))
    if preset == "custom":
        unit = form_str("unit", "mm", ["mm", "in", "cm"])
        k = {"mm": 1, "cm": 10, "in": 25.4}[unit]
        return form_float("width", lo=0.1) * k, form_float("height", lo=0.1) * k
    return pp.PRESETS[preset][1], pp.PRESETS[preset][2]


@bp.post("/passport")
def passport():
    sid = get_sid()
    inp = fm.get_inputs(sid, "file", IMG)[0]
    im = imgs.open_image(inp.path)
    width_mm, height_mm = _passport_dims()
    if form_bool("detect_only"):
        face = pp.detect_face(im)
        box = pp.default_crop(im.size, face, width_mm / height_mm)
        return ok({"detected": bool(face), "face": dict(zip("xywh", face)) if face else None,
                   "default_crop": dict(zip("xywh", box)), "image": {"width": im.size[0], "height": im.size[1]},
                   "input": {"job_id": inp.job.id}})
    crop_box = None
    if request_has("crop_x"):
        crop_box = (form_float("crop_x"), form_float("crop_y"), form_float("crop_w"), 0)
    background = form_str("background", "original")
    if background != "original" and background not in pp.BACKGROUNDS and background != "custom":
        raise ApiError("Unknown background option.")
    bg_color = form_str("bg_color", "#FFFFFF") if background == "custom" else (background if background != "original" else "white")
    final, info = pp.build_passport(
        im, width_mm, height_mm, "original" if background == "original" else "solid", bg_color, crop_box,
        form_float("zoom", 1, 0.5, 3), form_float("dx", 0, -1, 1), form_float("dy", 0, -1, 1),
        form_float("brightness", 1, 0.5, 1.8), form_float("contrast", 1, 0.5, 1.8),
        form_float("sharpen", 0, 0, 3), form_float("noise_reduction", 0, 0, 10))
    out_fmt = form_str("format", "jpg", ["jpg", "pdf"])
    jid, path = fm.new_output(sid, "jpg" if out_fmt == "jpg" else "pdf")
    if out_fmt == "jpg":
        imgs.write_image(final, "jpg", path, 95, dpi=pp.DPI)
    else:
        final.save(path, "PDF", resolution=pp.DPI)
    # always keep a JPG so the print-sheet step can reuse it
    jpg_job = None
    if out_fmt == "pdf":
        jid2, p2 = fm.new_output(sid, "jpg")
        imgs.write_image(final, "jpg", p2, 95, dpi=pp.DPI)
        jpg_job = fm.register_output(sid, jid2, p2, f"{_stem(inp.job)}-passport.jpg", meta=info)
    job = fm.register_output(sid, jid, path, f"{_stem(inp.job)}-passport.{out_fmt}", meta=info)
    extra = {"info": info, "input": {"job_id": inp.job.id}}
    if jpg_job:
        extra["jpg"] = jpg_job.to_dict()
    return result(job, **extra)


def request_has(name):
    from flask import request
    return request.form.get(name) not in (None, "")


@bp.post("/print-sheet")
def print_sheet():
    sid = get_sid()
    inp = fm.get_inputs(sid, "file", IMG)[0]
    photo = imgs.open_image(inp.path).convert("RGB")
    sheet, info = pp.make_sheet(photo, form_str("paper", "4x6", list(pp.PAPERS)), form_int("copies", 0, 0, 100),
                                form_float("gap_mm", 2, 0, 10), 3.0, form_bool("guides", True))
    out_fmt = form_str("format", "jpg", ["jpg", "pdf"])
    jid, path = fm.new_output(sid, out_fmt)
    if out_fmt == "jpg":
        imgs.write_image(sheet, "jpg", path, 95, dpi=pp.DPI)
    else:
        sheet.save(path, "PDF", resolution=pp.DPI)
    job = fm.register_output(sid, jid, path, f"print-sheet-{info['paper']}.{out_fmt}", meta=info)
    return result(job, info=info)
