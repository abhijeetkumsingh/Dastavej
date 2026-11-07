from flask import Blueprint, send_file

from flask import request
from ..services import file_manager as fm
from ..utils.responses import ApiError, ok
from ..utils.security import get_sid

bp = Blueprint("jobs", __name__, url_prefix="/api/jobs")

INLINE_OK = {"image/png", "image/jpeg", "image/webp", "application/pdf", "text/plain"}


@bp.get("/<job_id>")
def status(job_id):
    job = fm.get_job(job_id, get_sid())
    if job.kind in fm.PRIVATE_KINDS:
        raise ApiError("File not found or expired.", 404, "not_found")
    return ok({"status": "done", "job": job.to_dict()})


@bp.get("/<job_id>/download")
def download(job_id):
    job = fm.get_job(job_id, get_sid())
    if job.kind in fm.PRIVATE_KINDS:
        raise ApiError("File not found or expired.", 404, "not_found")
    inline = request.args.get("inline") == "1" and job.mime in INLINE_OK
    resp = send_file(fm.job_path(job), mimetype=job.mime, as_attachment=not inline,
                     download_name=job.display_name, conditional=True, max_age=0)
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    if not inline:
        resp.headers["Content-Disposition"] = resp.headers.get("Content-Disposition", "attachment")
    return resp


@bp.delete("/<job_id>")
def delete(job_id):
    job = fm.get_job(job_id, get_sid())
    fm.delete_job(job)
    return ok({"deleted": True})


@bp.post("/upload")
def upload():
    """Generic upload used by the homepage drop zone; tool pages then pick the file up by id."""
    sid = get_sid()
    inp = fm.get_inputs(sid, "file", {"jpg", "png", "webp", "pdf", "docx", "pptx", "xlsx", "csv", "txt"}, allow_encrypted=True)[0]
    d = inp.job.to_dict()
    d["file_kind"] = inp.kind
    return ok({"file": d})
