"""Format conversions. Office -> PDF uses a restricted LibreOffice subprocess."""
import csv
import io
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import openpyxl
import pandas as pd

from ..utils.responses import ApiError
from . import capabilities as caps

LIMITATIONS = {
    "docx-to-pdf": "Rendered by LibreOffice. Fonts missing on the server are substituted, so layout may differ slightly from Word.",
    "pptx-to-pdf": "Rendered by LibreOffice. Animations and transitions are dropped; some fonts/effects may differ.",
    "xlsx-to-pdf": "Each sheet is printed using the workbook's own print settings; very wide sheets may span several pages.",
    "pdf-to-docx": "Best for text-based PDFs. Scanned PDFs are not OCR'd, and complex layouts may need manual cleanup.",
    "xlsx-to-csv": "Exports cell values (formulas are exported as their last calculated values). Multiple sheets become separate CSV files in a ZIP.",
    "csv-to-xlsx": "Creates a single-sheet workbook. Text starting with '=' is stored as plain text, not as a formula.",
    "docx-to-txt": "Plain text only: images and formatting are dropped; tables are exported as tab-separated rows.",
    "image-to-pdf": "One image per page. Choose a page size or 'fit to image'.",
    "pdf-to-image": "Renders each page as an image at the chosen DPI.",
    "image-format": "Converting to JPG flattens transparency onto white. WebP/JPG are lossy.",
}


def lo_to_pdf(src: Path, out_pdf: Path, app_cfg):
    exe = caps.soffice_path()
    if not exe:
        raise ApiError("Office conversion is unavailable: LibreOffice is not installed on the server.", 503, "libreoffice_missing")
    work = Path(tempfile.mkdtemp(prefix="dv-lo-"))
    try:
        local = work / ("input" + src.suffix)
        shutil.copyfile(src, local)
        profile = work / "profile"
        cmd = [exe, f"-env:UserInstallation=file://{profile}", "--headless", "--norestore", "--nolockcheck",
               "--nodefault", "--nologo", "--convert-to", "pdf", "--outdir", str(work), str(local)]
    
        def limits():
            import resource
            limit = app_cfg["LIBREOFFICE_MEMORY_MB"] * 1024 * 1024
            try:
                resource.setrlimit(resource.RLIMIT_AS, (limit, limit))  # address-space cap for the subprocess
            except (ValueError, OSError):
                pass
            resource.setrlimit(resource.RLIMIT_CPU, (app_cfg["LIBREOFFICE_TIMEOUT"] + 10,) * 2)
            try:
                resource.setrlimit(resource.RLIMIT_FSIZE, (500 * 1024 * 1024,) * 2)
            except (ValueError, OSError):
                pass
            os.setsid()

        env = {"PATH": "/usr/bin:/bin", "HOME": str(work), "LANG": "C.UTF-8", "TMPDIR": str(work)}
        try:
            subprocess.run(cmd, cwd=work, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=app_cfg["LIBREOFFICE_TIMEOUT"], preexec_fn=limits, check=False)
        except subprocess.TimeoutExpired:
            raise ApiError("The conversion took too long and was cancelled.", 504, "timeout")
        produced = work / "input.pdf"
        if not produced.exists() or produced.stat().st_size == 0:
            raise ApiError("The document could not be converted. It may be corrupted or use unsupported features.", 422, "conversion_failed")
        shutil.move(str(produced), out_pdf)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def pdf_to_docx(src: Path, out: Path, max_pages=100):
    from pdf2docx import Converter
    import pymupdf
    with pymupdf.open(src) as d:
        n = d.page_count
        has_text = any(p.get_text().strip() for p in d)
    if not has_text:
        raise ApiError("This PDF has no selectable text (it looks scanned). PDF to DOCX needs a text-based PDF.", 422, "no_text")
    cv = Converter(str(src))
    try:
        cv.convert(str(out), start=0, end=min(n, max_pages))
    except Exception:
        raise ApiError("This PDF could not be converted to DOCX.", 422, "conversion_failed")
    finally:
        cv.close()
    if not out.exists():
        raise ApiError("This PDF could not be converted to DOCX.", 422, "conversion_failed")
    return min(n, max_pages), n


def xlsx_to_csvs(src: Path, sheet=None):
    wb = openpyxl.load_workbook(src, data_only=True, read_only=True)
    out = []
    names = [sheet] if sheet else wb.sheetnames
    for name in names:
        if name not in wb.sheetnames:
            raise ApiError(f"Sheet '{name}' not found.")
        buf = io.StringIO()
        w = csv.writer(buf)
        for row in wb[name].iter_rows(values_only=True):
            w.writerow(["" if v is None else v for v in row])
        out.append((name, buf.getvalue()))
    wb.close()
    return out


def csv_to_xlsx(src: Path, out: Path):
    raw = src.read_bytes()
    text = None
    for enc in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ApiError("Could not read this CSV's text encoding.")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    rows = 0
    for row in csv.reader(io.StringIO(text), dialect):
        ws.append(row)
        rows += 1
        if rows > 1_000_000:
            raise ApiError("CSV has too many rows.")
    for r in ws.iter_rows():
        for c in r:
            if isinstance(c.value, str):
                v = c.value.strip()
                if v and not v.startswith("="):
                    try:
                        c.value = int(v) if v.lstrip("-").isdigit() and not v.startswith("0") or v == "0" else float(v) if _isfloat(v) else c.value
                    except ValueError:
                        pass
                else:
                    c.data_type = "s"
    wb.save(out)
    return rows


def _isfloat(v):
    try:
        float(v)
        return not v.lower() in ("nan", "inf", "-inf", "infinity") and not v.startswith("0") or v.startswith("0.")
    except ValueError:
        return False


def docx_to_text(src: Path):
    import docx
    d = docx.Document(str(src))
    parts = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            parts.append("\t".join(c.text for c in row.cells))
    return "\n".join(parts)
