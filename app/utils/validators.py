"""File signature (magic byte) validation, structure checks and size/page limits."""
import zipfile
from pathlib import Path

import pymupdf
from PIL import Image, UnidentifiedImageError

from .responses import ApiError

IMAGE_KINDS = {"jpg", "png", "webp"}
MIME = {
    "jpg": "image/jpeg", "png": "image/png", "webp": "image/webp", "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv", "txt": "text/plain", "zip": "application/zip", "json": "application/json",
}
EXT_FOR = {k: k for k in MIME}
EXT_FOR["jpg"] = "jpg"


def sniff_kind(path, original_name=""):
    """Return a file kind from content signature, or None if unrecognised."""
    with open(path, "rb") as f:
        head = f.read(8192)
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head.lstrip(b"\xef\xbb\xbf \r\n\t").startswith(b"%PDF-") or b"%PDF-" in head[:1024]:
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        return _ooxml_kind(path)
    if not head:
        return None
    if b"\x00" in head:
        return None
    try:
        head.decode("utf-8")
    except UnicodeDecodeError:
        try:
            head.decode("utf-16")
            if b"\x00" not in head:
                return None
        except UnicodeDecodeError:
            # tolerate truncated multi-byte char at the 8 KB boundary
            try:
                head[:-4].decode("utf-8")
            except UnicodeDecodeError:
                return None
    return "csv" if str(original_name).lower().endswith(".csv") else "txt"


def _ooxml_kind(path):
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            names = [i.filename for i in infos]
            _check_zip_safety(infos)
            if "[Content_Types].xml" not in names:
                return None
            if any(n.startswith("word/") for n in names):
                return "docx"
            if any(n.startswith("ppt/") for n in names):
                return "pptx"
            if any(n.startswith("xl/") for n in names):
                return "xlsx"
    except zipfile.BadZipFile:
        raise ApiError("This file looks corrupted and could not be opened.", 400, "corrupted_file")
    return None


def _check_zip_safety(infos, max_mb=300):
    """Archive safety: block path traversal, zip bombs and absurd entry counts."""
    if len(infos) > 5000:
        raise ApiError("Archive contains too many entries.", 400, "unsafe_archive")
    total = 0
    for i in infos:
        n = i.filename.replace("\\", "/")
        if n.startswith("/") or ".." in n.split("/"):
            raise ApiError("Archive contains unsafe paths.", 400, "unsafe_archive")
        total += i.file_size
        if i.compress_size and i.file_size / max(i.compress_size, 1) > 1000 and i.file_size > 10_000_000:
            raise ApiError("Archive compression ratio is suspicious.", 400, "unsafe_archive")
    if total > max_mb * 1024 * 1024:
        raise ApiError("Archive expands to an unsafe size.", 400, "unsafe_archive")


def validate_image(path, max_pixels):
    try:
        with Image.open(path) as im:
            w, h = im.size
            if w * h > max_pixels:
                raise ApiError(
                    f"Image is too large ({w}x{h}). Maximum is {max_pixels // 1_000_000} megapixels.", 413, "image_too_large"
                )
            im.verify()
        return w, h
    except ApiError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        raise ApiError("This image looks corrupted and could not be opened.", 400, "corrupted_file")


def validate_pdf(path, max_pages, allow_encrypted=False):
    try:
        doc = pymupdf.open(path, filetype="pdf")
    except Exception:
        doc = None
    if doc is None:
        raise ApiError("This PDF looks corrupted and could not be opened.", 400, "corrupted_file")
    try:
        if doc.needs_pass:
            if allow_encrypted:
                return {"pages": None, "encrypted": True}
            raise ApiError("This PDF is password-protected. Unlock it first with the PDF Studio.", 400, "encrypted_pdf")
        n = doc.page_count
        if n < 1:
            raise ApiError("This PDF has no pages.", 400, "corrupted_file")
        if n > max_pages:
            raise ApiError(f"PDF has {n} pages. The limit is {max_pages}.", 413, "too_many_pages")
        try:
            doc.load_page(0).get_text()
        except Exception:
            raise ApiError("This PDF looks corrupted and could not be read.", 400, "corrupted_file")
        return {"pages": n, "encrypted": False}
    finally:
        doc.close()


def validate_office(path, kind):
    """Open-test OOXML files so corrupted ones are rejected up front."""
    try:
        if kind == "docx":
            import docx
            docx.Document(str(path))
        elif kind == "pptx":
            import pptx
            pptx.Presentation(str(path))
        elif kind == "xlsx":
            import openpyxl
            with open(path, "rb") as fh:
                openpyxl.load_workbook(fh, read_only=True).close()
    except ApiError:
        raise
    except Exception:
        raise ApiError("This document looks corrupted and could not be opened.", 400, "corrupted_file")
