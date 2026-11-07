"""PDF operations built on PyMuPDF."""
import base64
import io
import re

import pymupdf
from PIL import Image

from ..utils.responses import ApiError
from . import image_service as imgs

PAGE_SIZES_MM = {"a4": (210, 297), "a3": (297, 420), "letter": (215.9, 279.4), "legal": (215.9, 355.6)}
MM = 72 / 25.4


def open_pdf(path, password=None):
    try:
        doc = pymupdf.open(path)
    except Exception:
        raise ApiError("This PDF could not be opened.", 400, "corrupted_file")
    if doc.needs_pass:
        if not password or not doc.authenticate(password):
            doc.close()
            raise ApiError("Incorrect password." if password else "This PDF needs a password.", 400, "bad_password")
    return doc


def save(doc, path, **kw):
    doc.save(str(path), garbage=3, deflate=True, **kw)
    doc.close()


def merge(paths, out):
    result = pymupdf.open()
    for p in paths:
        with open_pdf(p) as d:
            result.insert_pdf(d)
    save(result, out)


def select_pages(path, order, out):
    """Keep pages in `order` (zero-based; duplicates allowed) - used for reorder/extract/delete/duplicate."""
    doc = open_pdf(path)
    doc.select(order)
    save(doc, out)


def split_ranges(path, ranges, out_for):
    """ranges: list of zero-based page lists. out_for(i) -> output path. Returns list of page counts."""
    counts = []
    for i, pages in enumerate(ranges):
        doc = open_pdf(path)
        doc.select(pages)
        save(doc, out_for(i))
        counts.append(len(pages))
    return counts


LEVELS = {"low": (200, 150, 80), "medium": (150, 110, 60), "high": (110, 72, 40)}


def compress(path, out, level="medium"):
    thr, tgt, q = LEVELS[level]
    doc = open_pdf(path)
    try:
        doc.rewrite_images(dpi_threshold=thr, dpi_target=tgt, quality=q)
    except Exception:
        pass  # structure-only optimisation still applies
    doc.save(str(out), garbage=4, deflate=True, clean=True, deflate_images=True, deflate_fonts=True, use_objstms=True)
    doc.close()


def rotate(path, pages, angle, out):
    if angle % 90:
        raise ApiError("Rotation must be a multiple of 90 degrees.")
    doc = open_pdf(path)
    for i in pages:
        doc[i].set_rotation((doc[i].rotation + angle) % 360)
    save(doc, out)


def _latin(text, what):
    try:
        text.encode("latin-1")
    except UnicodeEncodeError:
        raise ApiError(f"{what} currently supports Latin characters only (A-Z, digits, punctuation, accents).")


def _color(hexv):
    h = (hexv or "#000000").lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", h):
        raise ApiError("Colour must be a hex value like #FF0000.")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def watermark(path, out, text, pages, opacity=0.25, size=48, angle=45, color="#808080"):
    _latin(text, "Watermark text")
    doc = open_pdf(path)
    for i in pages:
        page = doc[i]
        r = page.rect
        tw = pymupdf.get_text_length(text, "helv", size)
        pt = pymupdf.Point(r.width / 2 - tw / 2, r.height / 2 + size / 3)
        page.insert_text(pt, text, fontsize=size, fontname="helv", color=_color(color), fill_opacity=opacity,
                         morph=(pymupdf.Point(r.width / 2, r.height / 2), pymupdf.Matrix(-angle)),
                         overlay=True)
    save(doc, out)


def page_numbers(path, out, position="bottom-center", start=1, fmt="{n}", size=10, pages=None):
    if "{n}" not in fmt and "{total}" not in fmt:
        raise ApiError("Format must contain {n} and/or {total}, e.g. 'Page {n} of {total}'.")
    _latin(fmt, "Page number format")
    doc = open_pdf(path)
    total = doc.page_count
    sel = pages if pages is not None else range(total)
    for k, i in enumerate(sel):
        page = doc[i]
        label = fmt.replace("{n}", str(start + k)).replace("{total}", str(total + start - 1))
        r = page.rect
        tw = pymupdf.get_text_length(label, "helv", size)
        v, h = position.split("-")
        y = 24 if v == "top" else r.height - 20
        x = {"left": 36, "center": (r.width - tw) / 2, "right": r.width - 36 - tw}[h]
        page.insert_text((x, y), label, fontsize=size, fontname="helv", color=(0.15, 0.15, 0.15))
    save(doc, out)


def decode_signature(data_url_or_bytes):
    """Accept a data URL or raw bytes; return trimmed PNG bytes (transparent background kept)."""
    raw = data_url_or_bytes
    if isinstance(raw, str):
        m = re.match(r"^data:image/(png|jpeg|webp);base64,(.+)$", raw, re.S)
        if not m:
            raise ApiError("Signature must be a PNG/JPEG data URL or image file.")
        try:
            raw = base64.b64decode(m.group(2), validate=False)
        except Exception:
            raise ApiError("Signature image is not valid.")
    if len(raw) > 5_000_000:
        raise ApiError("Signature image is too large.")
    try:
        im = Image.open(io.BytesIO(raw))
        im.load()
        if im.size[0] * im.size[1] > 8_000_000:
            raise ApiError("Signature image is too large.")
        im = im.convert("RGBA")
    except ApiError:
        raise
    except Exception:
        raise ApiError("Signature image is not valid.")
    bbox = im.split()[-1].getbbox()
    if not bbox:
        raise ApiError("The signature is empty. Please draw it first.")
    im = im.crop(bbox)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def sign(path, out, sig_png, placements, annotations):
    """Visual (drawn) signature + text annotations. NOT a cryptographic digital signature."""
    doc = open_pdf(path)
    n = doc.page_count
    sim = Image.open(io.BytesIO(sig_png)) if sig_png else None
    for p in placements:
        pg, x, y, w = int(p["page"]) - 1, float(p["x"]), float(p["y"]), float(p["w"])
        if not (0 <= pg < n and 0 <= x < 1 and 0 <= y < 1 and 0.02 <= w <= 1):
            raise ApiError("Signature position is outside the page.")
        page = doc[pg]
        W, H = page.rect.width, page.rect.height
        sw = w * W
        sh = sw * sim.size[1] / sim.size[0]
        rect = pymupdf.Rect(x * W, y * H, min(W, x * W + sw), min(H, y * H + sh))
        page.insert_image(rect, stream=sig_png, keep_proportion=True, overlay=True)
    for a in annotations:
        pg = int(a["page"]) - 1
        text = str(a.get("text", ""))[:500]
        x, y, size = float(a["x"]), float(a["y"]), float(a.get("size", 12))
        if not (0 <= pg < n and 0 <= x <= 1 and 0 <= y <= 1 and 4 <= size <= 96):
            raise ApiError("Annotation position is outside the page.")
        _latin(text, "Text annotation")
        page = doc[pg]
        page.insert_text((x * page.rect.width, y * page.rect.height + size), text, fontsize=size,
                         fontname="helv", color=_color(a.get("color", "#000000")))
    save(doc, out)


def protect(path, out, user_pw, owner_pw=None):
    doc = open_pdf(path)
    doc.save(str(out), encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=user_pw, owner_pw=owner_pw or user_pw + "#owner",
             permissions=pymupdf.PDF_PERM_ACCESSIBILITY | pymupdf.PDF_PERM_PRINT | pymupdf.PDF_PERM_COPY, garbage=3, deflate=True)
    doc.close()


def unlock(path, out, password):
    doc = open_pdf(path, password)
    doc.save(str(out), encryption=pymupdf.PDF_ENCRYPT_NONE, garbage=3, deflate=True)
    doc.close()


def render_page(path, index, dpi=72, fmt="png", password=None):
    doc = open_pdf(path, password)
    try:
        pix = doc[index].get_pixmap(dpi=dpi, alpha=False)
        return pix.tobytes("png" if fmt == "png" else "jpeg", jpg_quality=90) if fmt != "png" else pix.tobytes("png")
    finally:
        doc.close()


def to_text(path):
    doc = open_pdf(path)
    parts, empty = [], []
    for i, page in enumerate(doc):
        t = page.get_text().strip()
        if not t:
            empty.append(i + 1)
            t = "[No extractable text on this page - it may be scanned. Use the AI Assistant OCR instead.]"
        parts.append(f"--- Page {i + 1} ---\n{t}")
    doc.close()
    return "\n\n".join(parts), empty


def images_to_pdf(paths, out, page_size="a4", orientation="auto", margin_mm=10, custom=None):
    """page_size: a4|a3|letter|legal|fit|custom (custom=(w_mm,h_mm))."""
    doc = pymupdf.open()
    for p in paths:
        im = imgs.open_image(p)
        w, h = im.size
        if im.format in ("JPEG",) and im.mode in ("RGB", "L") and not _has_exif_rotation(p):
            data = open(p, "rb").read()
        else:
            buf = io.BytesIO()
            imgs.flatten(im).save(buf, "JPEG", quality=92) if im.mode != "RGBA" else imgs.flatten(im).save(buf, "JPEG", quality=92)
            data = buf.getvalue()
        if page_size == "fit":
            pw, ph = w * 72 / 150, h * 72 / 150
            m = 0
        else:
            if page_size == "custom":
                mw, mh = custom
            else:
                mw, mh = PAGE_SIZES_MM[page_size]
            if orientation == "auto":
                land = (w > h) if page_size != "custom" else (mw > mh)  # custom sizes are used exactly as given
            else:
                land = orientation == "landscape"
            if land != (mw > mh):
                mw, mh = mh, mw
            pw, ph, m = mw * MM, mh * MM, margin_mm * MM
        page = doc.new_page(width=pw, height=ph)
        page.insert_image(pymupdf.Rect(m, m, pw - m, ph - m), stream=data, keep_proportion=True)
    save(doc, out)


def _has_exif_rotation(path):
    try:
        with Image.open(path) as im:
            return (im.getexif().get(274) or 1) != 1
    except Exception:
        return True
