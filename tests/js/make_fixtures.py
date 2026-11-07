import io, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import cv2, docx, numpy as np, pymupdf, shutil
from tests.conftest import make_pdf, png_bytes
from tests.test_scanner import synth_doc, jpg
from tests.test_resume import GOOD, mkdocx

d = Path(__file__).parent / "fixtures"; d.mkdir(exist_ok=True)
(d / "photo.png").write_bytes(png_bytes(640, 480))
shutil.copy(Path(__file__).parents[1] / "face_sample.png", d / "face.png")
(d / "a.pdf").write_bytes(make_pdf(2, "Alpha"))
(d / "b.pdf").write_bytes(make_pdf(3, "Beta"))
doc = pymupdf.open(); p = doc.new_page(); p.insert_text((72, 100), "Invoice 4471 from Sharma Traders. Item A costs 1200 rupees and Item B costs 350 rupees.", fontsize=11); (d / "invoice.pdf").write_bytes(doc.tobytes())
dd = docx.Document(); dd.add_paragraph("Hello converter test document."); b = io.BytesIO(); dd.save(b); (d / "doc.docx").write_bytes(b.getvalue())
(d / "resume.docx").write_bytes(mkdocx(GOOD))
(d / "scan.jpg").write_bytes(jpg(synth_doc()[0]))
print("fixtures ok")
