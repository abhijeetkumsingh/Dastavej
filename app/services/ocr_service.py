"""OCR with Tesseract (English + Hindi)."""
import numpy as np
import cv2
from PIL import Image

from ..utils.responses import ApiError
from . import capabilities as caps
from . import image_service as imgs


def langs_for(requested, cfg_default):
    avail = caps.ocr_languages()
    if not avail:
        raise ApiError("OCR is unavailable: Tesseract is not installed on the server.", 503, "tesseract_missing")
    want = [l for l in (requested or cfg_default).split("+") if l]
    use = [l for l in want if l in avail]
    missing = [l for l in want if l not in avail]
    if not use:
        raise ApiError(f"OCR language data not installed: {', '.join(missing)}.", 503, "ocr_language_missing")
    return "+".join(use), missing


def _prep(im):
    g = cv2.cvtColor(np.array(imgs.flatten(im)), cv2.COLOR_RGB2GRAY)
    h, w = g.shape
    if max(h, w) < 1600:  # upscale small scans: improves recognition
        f = 1600 / max(h, w)
        g = cv2.resize(g, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    return Image.fromarray(g)


def ocr_image(im, lang):
    """Return (text, mean_confidence 0-100 or None)."""
    pytesseract = caps.setup_tesseract()
    p = _prep(im)
    try:
        data = pytesseract.image_to_data(p, lang=lang, output_type=pytesseract.Output.DICT, timeout=90)
    except RuntimeError:
        raise ApiError("OCR took too long on this page.", 504, "timeout")
    except Exception:
        raise ApiError("OCR failed on this image.", 500, "ocr_failed")
    words, confs, lines = [], [], {}
    for i, t in enumerate(data["text"]):
        t = t.strip()
        if not t:
            continue
        c = float(data["conf"][i])
        if c >= 0:
            confs.append(c)
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append(t)
    text = "\n".join(" ".join(v) for _, v in sorted(lines.items()))
    return text, (round(sum(confs) / len(confs), 1) if confs else None)
