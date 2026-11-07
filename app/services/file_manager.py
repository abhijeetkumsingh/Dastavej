"""Temporary storage manager: secure uploads, random names, session-bound jobs, cleanup."""
import json
import logging
import os
import secrets
import shutil
import time
import zipfile
from collections import namedtuple
from pathlib import Path

from flask import current_app, request

from ..extensions import db
from ..models import Job, default_expiry, utcnow
from ..utils import validators as V
from ..utils.responses import ApiError
from ..utils.security import ID_RE, SID_RE, display_name

log = logging.getLogger("dastavej")
Input = namedtuple("Input", "job path kind")

OFFICE = {"docx", "pptx", "xlsx"}
PRIVATE_KINDS = {"ai-doc", "ai-state", "ai-input"}  # never downloadable


def storage_root() -> Path:
    root = Path(current_app.config["STORAGE_DIR"])
    root.mkdir(parents=True, exist_ok=True)
    return root


def session_dir(sid) -> Path:
    if not SID_RE.match(str(sid)):
        raise ApiError("Invalid session.", 400)
    d = storage_root() / sid
    d.mkdir(parents=True, exist_ok=True)
    return d


def new_job_id():
    return secrets.token_hex(12)


def mime_for(ext):
    return V.MIME.get(ext, "application/octet-stream")


def register(sid, jid, path, name, kind, meta=None, mime=None, ttl=None):
    path = Path(path)
    job = Job(
        id=jid, session_id=sid, kind=kind, display_name=display_name(name),
        stored_name=path.name, mime=mime or mime_for(path.suffix.lstrip(".")),
        size=path.stat().st_size, meta_json=json.dumps(meta or {}),
        expires_at=default_expiry(ttl or current_app.config["FILE_TTL_MINUTES"]),
    )
    db.session.add(job)
    db.session.commit()
    return job


def new_output(sid, ext):
    jid = new_job_id()
    return jid, session_dir(sid) / f"{jid}.{ext}"


def register_output(sid, jid, path, name, kind="output", meta=None):
    return register(sid, jid, path, name, kind, meta)


def save_upload(fs, sid, allowed, kind="input", allow_encrypted=False):
    cfg = current_app.config
    if fs is None or not getattr(fs, "filename", ""):
        raise ApiError("No file was provided.")
    jid = new_job_id()
    tmp = session_dir(sid) / f"{jid}.part"
    fs.save(tmp)
    try:
        if tmp.stat().st_size == 0:
            raise ApiError("The uploaded file is empty.", 400, "empty_file")
        k = V.sniff_kind(tmp, fs.filename)
        if k is None:
            raise ApiError("Unsupported or unrecognised file type.", 415, "unsupported_type")
        if k not in allowed:
            raise ApiError(
                f"'{k.upper()}' files are not supported here. Allowed: {', '.join(sorted(a.upper() for a in allowed))}.",
                415, "unsupported_type",
            )
        meta = {}
        if k in V.IMAGE_KINDS:
            w, h = V.validate_image(tmp, cfg["MAX_IMAGE_PIXELS"])
            meta.update(width=w, height=h)
        elif k == "pdf":
            meta.update(V.validate_pdf(tmp, cfg["MAX_PDF_PAGES"], allow_encrypted))
        elif k in OFFICE:
            V.validate_office(tmp, k)
        final = session_dir(sid) / f"{jid}.{k}"
        os.replace(tmp, final)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    meta["kind"] = k
    return register(sid, jid, final, fs.filename, kind, meta, mime=V.MIME[k])


def job_path(job: Job) -> Path:
    return session_dir(job.session_id) / job.stored_name


def get_job(job_id, sid) -> Job:
    if not job_id or not ID_RE.match(str(job_id)):
        raise ApiError("File not found or expired.", 404, "not_found")
    job = Job.query.filter_by(id=job_id, session_id=sid).first()
    if not job or job.expires_at < utcnow() or not job_path(job).exists():
        raise ApiError("File not found or expired.", 404, "not_found")
    return job


def kind_of(job):
    return Path(job.stored_name).suffix.lstrip(".")


def get_inputs(sid, field="file", allowed=None, multiple=False, required=True, allow_encrypted=False):
    """Accept uploads in `field` and/or previously uploaded job ids in `<field>_id` (or `job_id`)."""
    allowed = set(allowed or [])
    cfg = current_app.config
    files = [f for f in request.files.getlist(field) if f and f.filename]
    ids = request.form.getlist(f"{field}_id") + (request.form.getlist("job_id") if field == "file" else [])
    ids = [i for i in ids if i]
    total = len(files) + len(ids)
    if total == 0:
        if required:
            raise ApiError("Please choose a file first." if not multiple else "Please choose at least one file.")
        return []
    if total > cfg["MAX_FILES_PER_REQUEST"]:
        raise ApiError(f"Too many files. Maximum is {cfg['MAX_FILES_PER_REQUEST']} per request.", 413)
    if not multiple and total > 1:
        raise ApiError("Please provide only one file.")
    out = []
    for jid in ids:
        job = get_job(jid, sid)
        k = kind_of(job)
        if allowed and k not in allowed:
            raise ApiError(f"'{k.upper()}' files are not supported here.", 415, "unsupported_type")
        out.append(Input(job, job_path(job), k))
    for fs in files:
        job = save_upload(fs, sid, allowed or set(V.MIME), allow_encrypted=allow_encrypted)
        out.append(Input(job, job_path(job), kind_of(job)))
    return out


def make_zip(sid, entries, name="dastavej-output.zip", kind="output", meta=None):
    jid, path = new_output(sid, "zip")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for arc, p in entries:
            z.write(p, display_name(arc))
    return register_output(sid, jid, path, name, kind, meta)


def delete_job(job: Job):
    try:
        job_path(job).unlink(missing_ok=True)
    except Exception:
        log.warning("could not remove file for job %s", job.id)
    db.session.delete(job)
    db.session.commit()


def delete_session_files(sid, kinds=None):
    q = Job.query.filter_by(session_id=sid)
    if kinds:
        q = q.filter(Job.kind.in_(list(kinds)))
    n = 0
    for job in q.all():
        delete_job(job)
        n += 1
    return n


def cleanup_expired(app=None):
    """Remove expired jobs, their files, and orphaned files/partials in storage."""
    app = app or current_app._get_current_object()
    with app.app_context():
        removed = 0
        for job in Job.query.filter(Job.expires_at < utcnow()).all():
            delete_job(job)
            removed += 1
        root = storage_root()
        known = {(j.session_id, j.stored_name) for j in Job.query.all()}
        cutoff = time.time() - max(app.config["FILE_TTL_MINUTES"], 5) * 60 - 600
        for sdir in root.iterdir():
            if not sdir.is_dir():
                continue
            for f in sdir.iterdir():
                try:
                    if (sdir.name, f.name) not in known and f.stat().st_mtime < cutoff:
                        f.unlink()
                        removed += 1
                except OSError:
                    pass
            try:
                if not any(sdir.iterdir()):
                    sdir.rmdir()
            except OSError:
                pass
        return removed
