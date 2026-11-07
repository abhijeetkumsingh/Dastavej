from pathlib import Path

from flask import Blueprint, current_app

from ..services import extract_service as ex
from ..services import file_manager as fm
from ..services import resume_report as rr
from ..services import resume_service as rs
from ..services.resume_data import ROLES
from ..utils.responses import ApiError, ok
from ..utils.security import get_sid
from .common import form_bool, form_str

bp = Blueprint("resume", __name__, url_prefix="/api/resume")
ROLE_CHOICES = list(ROLES) + ["Custom"]


def _text_of(inp):
    res = ex.extract(inp.path, inp.kind, current_app.config)
    text = "\n".join(u["text"] for u in res["units"] if u["source"] != "table" or True)
    # keep reading order for PDFs: tables were appended after page text, so drop duplicates
    seen, parts = set(), []
    for u in res["units"]:
        if u["source"] == "table" and inp.kind == "pdf":
            continue
        parts.append(u["text"])
    text = "\n".join(parts)
    return text, res


def _run(report=False):
    sid = get_sid()
    inp = fm.get_inputs(sid, "file", {"pdf", "docx"})[0]
    role = form_str("role", "Software Developer", ROLE_CHOICES)
    jd = form_str("job_description", "", max_len=20000)
    text, res = _text_of(inp)
    result = rs.analyze_resume(text, inp.path, inp.kind, role, jd, form_str("custom_role", "", max_len=60))
    warns = list(res["warnings"])
    if res["ocr_pages"]:
        warns.append("This resume was scanned; text came from OCR and may contain errors. A text-based PDF/DOCX parses better in real ATS.")
    result["extraction_warnings"] = warns
    if report:
        jid, path = fm.new_output(sid, "pdf")
        rr.build_report(result, path)
        job = fm.register_output(sid, jid, path, Path(inp.job.display_name).stem + "-analysis.pdf", kind="output")
        result["report"] = job.to_dict()
    result["resume_job_id"] = inp.job.id
    return result


@bp.post("/upload")
def upload():
    sid = get_sid()
    inp = fm.get_inputs(sid, "file", {"pdf", "docx"})[0]
    text, res = _text_of(inp)
    warns = list(res["warnings"])
    if len(text.strip()) < 80:
        warns.append("Very little text was read from this file.")
    return ok({"input": {"job_id": inp.job.id, "name": inp.job.display_name, "type": inp.kind, "characters": len(text),
                         "pages": res["pages"], "ocr_used": bool(res["ocr_pages"]), "warnings": warns}})


@bp.post("/analyze")
def analyze():
    r = _run(report=form_bool("report", True))
    return ok({"analysis": r, "estimated": True})


@bp.post("/ats-score")
def ats_score():
    r = _run()
    return ok({"score": r["score"], "label": r["score_label"], "breakdown": r["breakdown"], "basis": r["score_basis"],
               "disclaimer": r["disclaimer"], "estimated": True})


@bp.post("/skills")
def skills():
    r = _run()
    return ok({"skills": r["skills"], "keywords": r["keywords"]})


@bp.post("/projects")
def projects():
    r = _run()
    return ok({"projects": r["projects"], "recommendations": r["recommendations"]})


@bp.post("/roadmap")
def roadmap():
    r = _run()
    return ok({"roadmap": r["roadmap"], "recommendations": r["recommendations"], "missing_skills": r["skills"]["missing_required"]})


@bp.post("/jd-match")
def jd_match():
    if not form_str("job_description", "", max_len=20000).strip():
        raise ApiError("Paste the job description to match against.")
    r = _run()
    return ok({"jd_match": r["jd_match"], "score": r["score"], "breakdown": r["breakdown"], "disclaimer": r["disclaimer"], "estimated": True})
