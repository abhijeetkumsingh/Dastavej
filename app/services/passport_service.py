"""Passport photo studio. Non-generative: the face is only cropped/scaled, never re-drawn.

Background change uses GrabCut segmentation + alpha compositing of the *original* pixels,
with the detected face area locked as foreground so face pixels are never replaced."""
import math

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

from ..utils.responses import ApiError
from . import image_service as imgs

DPI = 300
PRESETS = {
    "india-passport": ("India passport / visa (35 x 45 mm)", 35.0, 45.0),
    "uk-eu": ("UK / Schengen / most of Europe (35 x 45 mm)", 35.0, 45.0),
    "us": ("US passport / visa (2 x 2 in)", 50.8, 50.8),
    "china-visa": ("China visa (33 x 48 mm)", 33.0, 48.0),
    "pan-card": ("PAN card (25 x 35 mm)", 25.0, 35.0),
    "stamp": ("Stamp size (20 x 25 mm)", 20.0, 25.0),
    "custom": ("Custom size", None, None),
}
BACKGROUNDS = {"white": "#FFFFFF", "blue": "#3B6FB6", "light-blue": "#BFD9F2", "red": "#C8102E", "grey": "#D9D9D9"}
PAPERS = {"4x6": (6.0, 4.0), "5x7": (7.0, 5.0), "a4": (11.69, 8.27)}  # landscape inches (w, h)


def mm_to_px(mm):
    return int(round(mm / 25.4 * DPI))


def parse_color(value):
    v = (value or "").strip()
    if v in BACKGROUNDS:
        v = BACKGROUNDS[v]
    if not (len(v) == 7 and v[0] == "#"):
        raise ApiError("Background colour must be a name or a hex value like #FFFFFF.")
    try:
        return tuple(int(v[i:i + 2], 16) for i in (1, 3, 5))
    except ValueError:
        raise ApiError("Background colour must be a name or a hex value like #FFFFFF.")


_cascades = {}


def _cascade(name):
    if name not in _cascades:
        _cascades[name] = cv2.CascadeClassifier(cv2.data.haarcascades + name)
    return _cascades[name]


def detect_face(im):
    """Return the largest frontal face as (x, y, w, h) in image pixels, or None."""
    rgb = np.array(imgs.flatten(im))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    scale = 800.0 / max(gray.shape) if max(gray.shape) > 800 else 1.0
    small = cv2.resize(gray, None, fx=scale, fy=scale) if scale != 1.0 else gray
    small = cv2.equalizeHist(small)
    min_side = max(30, int(min(small.shape) * 0.12))
    for name in ("haarcascade_frontalface_default.xml", "haarcascade_frontalface_alt2.xml"):
        faces = _cascade(name).detectMultiScale(small, 1.1, 5, minSize=(min_side, min_side))
        if len(faces):
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            return tuple(float(v) / scale for v in (x, y, w, h))
    return None


def default_crop(img_size, face, aspect, zoom=1.0, dx=0.0, dy=0.0):
    """Crop box (x, y, w, h) floats; may extend beyond the image (padded later)."""
    W, H = img_size
    if face:
        fx, fy, fw, fh = face
        crop_h = (fh / 0.55) / max(zoom, 0.2)
        crop_w = crop_h * aspect
        cx = fx + fw / 2 + dx * crop_w
        cy_face = fy + fh / 2
        y0 = cy_face - 0.47 * crop_h + dy * crop_h
        return (cx - crop_w / 2, y0, crop_w, crop_h)
    # no face: largest centred box of the right aspect
    crop_h = min(H, W / aspect) / max(zoom, 0.2)
    crop_w = crop_h * aspect
    return ((W - crop_w) / 2 + dx * crop_w, (H - crop_h) / 2 + dy * crop_h, crop_w, crop_h)


def crop_with_pad(im, box, fill):
    x, y, w, h = box
    x0, y0, x1, y1 = int(round(x)), int(round(y)), int(round(x + w)), int(round(y + h))
    base = imgs.flatten(im)
    W, H = base.size
    if x0 >= 0 and y0 >= 0 and x1 <= W and y1 <= H:
        return base.crop((x0, y0, x1, y1))
    canvas = Image.new("RGB", (x1 - x0, y1 - y0), fill)
    canvas.paste(base, (-x0, -y0))
    return canvas


def replace_background(img, face_box_local, color):
    """GrabCut matte of the person; composite the original person pixels over `color`."""
    arr = np.array(img.convert("RGB"))
    h, w = arr.shape[:2]
    mask = np.full((h, w), cv2.GC_PR_BGD, np.uint8)
    b = max(2, int(0.04 * min(h, w)))
    mask[:b, :] = cv2.GC_BGD
    mask[:, :b] = cv2.GC_BGD
    mask[:, -b:] = cv2.GC_BGD
    fx, fy, fw, fh = face_box_local
    # torso: below the chin, about 1.4 face-widths either side
    tx0, tx1 = int(max(0, fx - 0.6 * fw)), int(min(w, fx + 1.6 * fw))
    ty0 = int(min(h - 1, fy + 0.95 * fh))
    mask[ty0:, tx0:tx1] = cv2.GC_PR_FGD
    # hair + head region probable foreground
    hx0, hx1 = int(max(0, fx - 0.15 * fw)), int(min(w, fx + 1.15 * fw))
    hy0 = int(max(0, fy - 0.45 * fh))
    mask[hy0:int(fy + fh), hx0:hx1] = cv2.GC_PR_FGD
    # face core: sure foreground (guarantees face pixels are never replaced)
    face_core = np.zeros((h, w), np.uint8)
    cv2.ellipse(face_core, (int(fx + fw / 2), int(fy + fh / 2)), (int(fw * 0.5), int(fh * 0.55)), 0, 0, 360, 255, -1)
    mask[face_core > 0] = cv2.GC_FGD
    bgd, fgd = np.zeros((1, 65)), np.zeros((1, 65))
    try:
        cv2.grabCut(arr, mask, None, bgd, fgd, 5, cv2.GC_INIT_WITH_MASK)
    except cv2.error:
        raise ApiError("Background could not be separated for this photo. Try a plainer original background.")
    fg = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, k)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, k)
    # keep the largest connected component (the person)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(fg)
    if n > 2:
        keep = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        fg = np.where(lab == keep, 255, 0).astype(np.uint8)
    fg = cv2.GaussianBlur(fg, (0, 0), 1.1)
    fg = np.maximum(fg, cv2.erode(face_core, k))  # lock face
    alpha = (fg.astype(np.float32) / 255.0)[..., None]
    bg = np.empty_like(arr)
    bg[:] = color
    out = (arr * alpha + bg * (1 - alpha)).round().astype(np.uint8)
    return Image.fromarray(out), face_core


def build_passport(im, width_mm, height_mm, background="original", bg_color="white", crop_box=None,
                   zoom=1.0, dx=0.0, dy=0.0, brightness=1.0, contrast=1.0, sharpen=0.0, denoise=0.0):
    if not (10 <= width_mm <= 100 and 10 <= height_mm <= 120):
        raise ApiError("Width must be 10-100 mm and height 10-120 mm.")
    out_w, out_h = mm_to_px(width_mm), mm_to_px(height_mm)
    aspect = width_mm / height_mm
    face = detect_face(im)
    fill = parse_color(bg_color) if background != "original" else (255, 255, 255)
    if crop_box:
        cx, cy, cw, ch = crop_box
        if cw < 20:
            raise ApiError("Crop area is too small.")
        box = (cx, cy, cw, cw / aspect)
    else:
        box = default_crop(im.size, face, aspect, zoom, dx, dy)
    cropped = crop_with_pad(im, box, fill if background != "original" else (255, 255, 255))
    final = cropped.resize((out_w, out_h), Image.LANCZOS)
    face_local = None
    if face:
        s = out_w / box[2]
        face_local = ((face[0] - box[0]) * s, (face[1] - box[1]) * s, face[2] * s, face[3] * s)
    bg_changed = False
    if background != "original":
        if not face_local:
            raise ApiError("No face was detected, so the background cannot be changed safely. "
                           "Use a clear front-facing photo or keep the original background.")
        final, _ = replace_background(final, face_local, fill)
        bg_changed = True
    adjustments = {}
    if denoise > 0:
        final = imgs.denoise(final, min(denoise, 10))
        adjustments["noise_reduction"] = denoise
    if abs(brightness - 1) > 1e-3:
        final = ImageEnhance.Brightness(final).enhance(brightness)
        adjustments["brightness"] = brightness
    if abs(contrast - 1) > 1e-3:
        final = ImageEnhance.Contrast(final).enhance(contrast)
        adjustments["contrast"] = contrast
    if sharpen > 0:
        final = final.filter(ImageFilter.UnsharpMask(radius=1.2, percent=int(60 * min(sharpen, 3)), threshold=2))
        adjustments["sharpen"] = sharpen
    info = {
        "face_detected": bool(face),
        "face": dict(zip("xywh", [round(v, 1) for v in face])) if face else None,
        "crop": dict(zip("xywh", [round(v, 1) for v in box])),
        "output_px": [out_w, out_h], "dpi": DPI, "size_mm": [width_mm, height_mm],
        "background_changed": bg_changed, "adjustments": adjustments,
        "identity_note": "Face pixels are only cropped and scaled from your original photo. No face generation is used.",
    }
    return final, info


def make_sheet(photo, paper="4x6", copies=0, gap_mm=2.0, margin_mm=3.0, guides=True):
    if paper not in PAPERS:
        raise ApiError("Paper must be one of: " + ", ".join(PAPERS))
    pw, ph = (int(round(v * DPI)) for v in PAPERS[paper])
    w, h = photo.size
    gap, margin = mm_to_px(gap_mm), mm_to_px(margin_mm)
    best = None
    for (sw, sh, rot) in ((pw, ph, False), (ph, pw, False)):
        cols = max(0, (sw - 2 * margin + gap) // (w + gap))
        rows = max(0, (sh - 2 * margin + gap) // (h + gap))
        if best is None or cols * rows > best[0] * best[1]:
            best = (cols, rows, sw, sh)
    cols, rows, sw, sh = best
    capacity = cols * rows
    if capacity == 0:
        raise ApiError("The photo is too large for this paper size.")
    n = capacity if copies in (0, None) else copies
    if n > capacity:
        raise ApiError(f"Only {capacity} copies of this photo fit on {paper.upper()} paper (you asked for {n}).")
    sheet = Image.new("RGB", (sw, sh), (255, 255, 255))
    gw, gh = cols * w + (cols - 1) * gap, rows * h + (rows - 1) * gap
    ox, oy = (sw - gw) // 2, (sh - gh) // 2
    from PIL import ImageDraw
    d = ImageDraw.Draw(sheet)
    placed = 0
    for r in range(rows):
        for c in range(cols):
            if placed >= n:
                break
            x, y = ox + c * (w + gap), oy + r * (h + gap)
            sheet.paste(photo, (x, y))
            if guides:
                d.rectangle([x - 1, y - 1, x + w, y + h], outline=(190, 190, 190), width=1)
            placed += 1
    return sheet, {"copies": placed, "capacity": capacity, "columns": cols, "rows": rows,
                   "paper": paper, "sheet_px": [sw, sh], "dpi": DPI}
