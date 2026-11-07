"""Image processing: resize, compress-to-target, convert, crop, rotate, enhance."""
import io
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from ..utils.responses import ApiError

FORMAT_MAP = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP"}
EXT_MAP = {"jpg": "jpg", "jpeg": "jpg", "png": "png", "webp": "webp"}


def open_image(path):
    try:
        im = Image.open(path)
        im = ImageOps.exif_transpose(im)
        im.load()
        return im
    except Exception:
        raise ApiError("This image could not be read.", 400, "corrupted_file")


def flatten(im, bg=(255, 255, 255)):
    """Convert any mode to RGB, compositing transparency onto a background."""
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        base = Image.new("RGB", im.size, bg)
        base.paste(im, mask=im.split()[-1])
        return base
    return im.convert("RGB")


def resolve_format(requested, input_kind):
    r = (requested or "same").lower()
    if r in ("same", ""):
        r = input_kind
    if r not in EXT_MAP:
        raise ApiError("Format must be JPG, PNG or WebP.")
    return EXT_MAP[r]


def encode(im, ext, quality=90, dpi=None):
    buf = io.BytesIO()
    kw = {}
    if dpi:
        kw["dpi"] = (dpi, dpi)
    if ext == "jpg":
        flatten(im).save(buf, "JPEG", quality=int(quality), optimize=True, progressive=True, **kw)
    elif ext == "webp":
        (im if im.mode in ("RGB", "RGBA") else im.convert("RGBA" if "A" in im.mode else "RGB")).save(
            buf, "WEBP", quality=int(quality), method=4)
    else:
        im.save(buf, "PNG", optimize=True, **kw)
    return buf.getvalue()


def write_image(im, ext, path, quality=90, dpi=None):
    data = encode(im, ext, quality, dpi)
    Path(path).write_bytes(data)
    return len(data)


def resize(im, width=None, height=None, keep_aspect=True):
    w0, h0 = im.size
    if not width and not height:
        raise ApiError("Enter a width, a height, or both.")
    if keep_aspect:
        if width and height:
            s = min(width / w0, height / h0)
        elif width:
            s = width / w0
        else:
            s = height / h0
        nw, nh = max(1, round(w0 * s)), max(1, round(h0 * s))
    else:
        nw, nh = int(width or w0), int(height or h0)
    if nw > 20000 or nh > 20000 or nw * nh > 100_000_000:
        raise ApiError("Requested dimensions are too large.")
    return im.resize((nw, nh), Image.LANCZOS)


def compress_to_target(im, target_bytes, ext, min_quality=15):
    """Iteratively compress until the *actual encoded size* is <= target.
    Returns (bytes, info). info['target_met'] is computed from the real output."""
    if target_bytes < 1024:
        raise ApiError("Target size must be at least 1 KB.")
    cur = flatten(im) if ext == "jpg" else im
    scale = 1.0
    attempts = 0
    best = None
    for _ in range(25):
        w, h = cur.size
        if ext in ("jpg", "webp"):
            lo, hi, found = min_quality, 95, None
            while lo <= hi:
                q = (lo + hi) // 2
                data = encode(cur, ext, q)
                attempts += 1
                if len(data) <= target_bytes:
                    found = (q, data)
                    lo = q + 1
                else:
                    hi = q - 1
            if found:
                q, data = found
                return data, _info(data, target_bytes, w, h, quality=q, scale=scale, attempts=attempts)
            best = encode(cur, ext, min_quality)
        else:  # PNG is lossless: try palette reduction, then downscale
            data = encode(cur, "png")
            attempts += 1
            if len(data) <= target_bytes:
                return data, _info(data, target_bytes, w, h, scale=scale, attempts=attempts)
            for colors in (256, 128, 64, 32):
                q = cur.convert("RGBA" if "A" in cur.mode else "RGB").quantize(colors, method=Image.FASTOCTREE)
                data = encode(q, "png")
                attempts += 1
                best = data
                if len(data) <= target_bytes:
                    return data, _info(data, target_bytes, w, h, scale=scale, attempts=attempts, colors=colors)
        if min(w, h) <= 24:
            break
        scale *= 0.88
        cur = cur.resize((max(16, round(im.size[0] * scale)), max(16, round(im.size[1] * scale))), Image.LANCZOS)
        if cur.mode == "P":
            cur = cur.convert("RGB")
    cw, ch = cur.size
    return best, _info(best, target_bytes, cw, ch, scale=scale, attempts=attempts)


def _info(data, target, w, h, **kw):
    d = {"output_bytes": len(data), "target_bytes": target, "target_met": len(data) <= target,
         "width": w, "height": h}
    d.update(kw)
    return d


def crop(im, x, y, w, h):
    W, H = im.size
    x, y, w, h = int(round(x)), int(round(y)), int(round(w)), int(round(h))
    if w < 1 or h < 1 or x < 0 or y < 0 or x + w > W or y + h > H:
        raise ApiError(f"Crop area must lie inside the image ({W}x{H}).")
    return im.crop((x, y, x + w, y + h))


def rotate(im, angle, fill=(255, 255, 255)):
    angle = float(angle) % 360
    if angle % 90 == 0:
        k = int(angle // 90) % 4
        return im.rotate(90 * k, expand=True) if k else im.copy()
    bg = fill if im.mode != "RGBA" else fill + (0,)
    return im.rotate(-angle, expand=True, resample=Image.BICUBIC, fillcolor=bg)


def denoise(im, strength=5):
    arr = np.array(flatten(im))
    if arr.shape[0] * arr.shape[1] > 12_000_000:
        out = cv2.bilateralFilter(arr, 7, 40, 40)
    else:
        out = cv2.fastNlMeansDenoisingColored(arr, None, strength, strength, 7, 21)
    return Image.fromarray(out)


def enhance(im, brightness=1.0, contrast=1.0, sharpness=1.0, saturation=1.0, auto=False, noise=0):
    out = flatten(im) if im.mode not in ("RGB", "RGBA", "L") else im
    if auto:
        out = ImageOps.autocontrast(out.convert("RGB"), cutoff=1)
    if noise and noise > 0:
        out = denoise(out, strength=min(float(noise), 15))
    for factor, cls in ((brightness, ImageEnhance.Brightness), (contrast, ImageEnhance.Contrast),
                        (saturation, ImageEnhance.Color), (sharpness, ImageEnhance.Sharpness)):
        if abs(factor - 1.0) > 1e-3:
            out = cls(out).enhance(factor)
    return out


def info_dict(path_or_bytes_len, im):
    return {"width": im.size[0], "height": im.size[1]}
