"""Document scanner: edge detection, perspective correction, filters, PDF export (OpenCV)."""
import cv2
import img2pdf
import numpy as np
from PIL import Image

from ..utils.responses import ApiError
from . import image_service as imgs

PAGE_SIZES_MM = {"a4": (210, 297), "a3": (297, 420), "letter": (215.9, 279.4), "legal": (215.9, 355.6)}


def to_bgr(im):
    return cv2.cvtColor(np.array(imgs.flatten(im)), cv2.COLOR_RGB2BGR)


def to_pil(bgr):
    return Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))


def order_points(pts):
    pts = np.array(pts, dtype="float32")
    s, d = pts.sum(axis=1), np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], dtype="float32")


def _candidates(gray):
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    med = float(np.median(blur))
    edges = cv2.Canny(blur, int(max(0, 0.66 * med)), int(min(255, 1.33 * med + 20)))
    edges = cv2.dilate(edges, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)), iterations=2)
    yield edges
    _, otsu = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    for m in (otsu, 255 - otsu):
        yield cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))


def detect_corners(im):
    """Return (corners_normalized [[x,y]*4 as tl,tr,br,bl], found)."""
    bgr = to_bgr(im)
    h0, w0 = bgr.shape[:2]
    scale = 600.0 / max(h0, w0)
    small = cv2.resize(bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else bgr
    sh, sw = small.shape[:2]
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    img_area = sh * sw
    for mask in _candidates(gray):
        cnts, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for c in sorted(cnts, key=cv2.contourArea, reverse=True)[:6]:
            area = cv2.contourArea(c)
            if area < 0.2 * img_area:
                break
            if area > 0.985 * img_area:
                continue  # the frame itself
            peri = cv2.arcLength(c, True)
            approx = cv2.approxPolyDP(c, 0.02 * peri, True)
            if len(approx) == 4 and cv2.isContourConvex(approx):
                pts = order_points(approx.reshape(4, 2))
                return (pts / [sw, sh]).tolist(), True
    return [[0, 0], [1, 0], [1, 1], [0, 1]], False


def warp(im, corners_norm):
    pts = np.array(corners_norm, dtype="float32")
    if pts.shape != (4, 2) or not np.isfinite(pts).all():
        raise ApiError("Four corner points are required.")
    bgr = to_bgr(im)
    h, w = bgr.shape[:2]
    pts = order_points(pts * [w, h])
    tl, tr, br, bl = pts
    out_w = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    out_h = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
    if out_w < 50 or out_h < 50:
        raise ApiError("The selected area is too small. Move the corners further apart.")
    dst = np.array([[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1], [0, out_h - 1]], dtype="float32")
    M = cv2.getPerspectiveTransform(pts, dst)
    return to_pil(cv2.warpPerspective(bgr, M, (out_w, out_h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE))


def crop_norm(im, x, y, w, h):
    W, H = im.size
    if not (0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1 and 0 < h <= 1 and x + w <= 1.0001 and y + h <= 1.0001):
        raise ApiError("Crop area must be inside the page.")
    box = (round(x * W), round(y * H), round((x + w) * W), round((y + h) * H))
    if box[2] - box[0] < 10 or box[3] - box[1] < 10:
        raise ApiError("Crop area is too small.")
    return im.crop(box)


def _normalise_bg(gray):
    k = max(15, (min(gray.shape) // 12) | 1)
    bg = cv2.medianBlur(cv2.dilate(gray, np.ones((7, 7), np.uint8)), k if k % 2 else k + 1)
    return cv2.divide(gray, bg, scale=255)


def apply_filter(im, mode="original", brightness=0, contrast=1.0, rotate=0):
    if mode not in ("original", "gray", "bw", "enhanced"):
        raise ApiError("Filter must be original, gray, bw or enhanced.")
    bgr = to_bgr(im)
    if mode == "gray":
        g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        bgr = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
    elif mode == "bw":
        g = _normalise_bg(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY))
        g = cv2.GaussianBlur(g, (3, 3), 0)
        t = cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15)
        bgr = cv2.cvtColor(t, cv2.COLOR_GRAY2BGR)
    elif mode == "enhanced":
        lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
        l = _normalise_bg(lab[:, :, 0])
        l = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(l)
        lab[:, :, 0] = l
        bgr = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        blur = cv2.GaussianBlur(bgr, (0, 0), 1.5)
        bgr = cv2.addWeighted(bgr, 1.5, blur, -0.5, 0)
    if brightness or abs(contrast - 1) > 1e-3:
        bgr = cv2.convertScaleAbs(bgr, alpha=contrast, beta=brightness)
    out = to_pil(bgr)
    if rotate % 360:
        out = imgs.rotate(out, rotate)
    return out


def export_pdf(paths, page_size="a4", path_out=None):
    """paths: ordered JPEG/PNG files. Returns bytes written."""
    if not paths:
        raise ApiError("Add at least one page before exporting.")
    kw = {}
    if page_size in PAGE_SIZES_MM:
        w, h = PAGE_SIZES_MM[page_size]
        kw["layout_fun"] = None
        pages = []
        for p in paths:
            with Image.open(p) as im:
                landscape = im.size[0] > im.size[1]
            ww, hh = (h, w) if landscape else (w, h)
            fun = img2pdf.get_layout_fun((img2pdf.mm_to_pt(ww), img2pdf.mm_to_pt(hh)),
                                         border=(img2pdf.mm_to_pt(5),) * 2, fit=img2pdf.FitMode.into)
            pages.append((p, fun))
        # img2pdf takes one layout function; build per-page PDFs and merge via pymupdf
        import pymupdf
        out = pymupdf.open()
        for p, fun in pages:
            data = img2pdf.convert([str(p)], layout_fun=fun, rotation=img2pdf.Rotation.ifvalid)
            with pymupdf.open("pdf", data) as d:
                out.insert_pdf(d)
        out.save(path_out, deflate=True)
        out.close()
    else:
        data = img2pdf.convert([str(p) for p in paths], layout_fun=img2pdf.get_fixed_dpi_layout_fun((150, 150)))
        with open(path_out, "wb") as f:
            f.write(data)
