import json
import secrets
from pathlib import Path

from flask import Blueprint, current_app, request

from ..extensions import db
from ..models import Job, default_expiry
from ..services import file_manager as fm
from ..services import gemini_service as gs
from ..services import image_service as imgs
from ..services import ocr_service as ocr
from ..services import extract_service as ex
from ..services import rag
from ..utils.responses import ApiError, ok
from ..utils.security import get_sid
from .common import form_bool, form_str, result

bp = Blueprint("ai", __name__, url_prefix="/api/ai")
ALLOWED = {"pdf", "docx", "pptx", "xlsx", "csv", "txt", "jpg", "png"}
MAX_DOCS = 5
MAX_HISTORY = 6
CONSENT_MSG = ("Please confirm that you agree to send the relevant document excerpts to Google's Gemini API. "
               "Nothing is sent until you do.")


# ---------- per-session private state (JSON files, never downloadable) ----------
def _private_write(sid, kind, data, job=None, name="state"):
    payload = json.dumps(data, ensure_ascii=False)
    if job is None:
        jid, path = fm.new_output(sid, "json")
        path.write_text(payload, encoding="utf-8")
        return fm.register(sid, jid, path, name + ".json", kind, {})
    fm.job_path(job).write_text(payload, encoding="utf-8")
    job.size = len(payload)
    job.expires_at = default_expiry(current_app.config["FILE_TTL_MINUTES"])
    db.session.commit()
    return job


def _state(sid):
    job = Job.query.filter_by(session_id=sid, kind="ai-state").first()
    if job:
        try:
            return job, json.loads(fm.job_path(job).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            fm.delete_job(job)
    return None, {"docs": [], "history": [], "last_sources": []}


def _save_state(sid, job, st):
    return _private_write(sid, "ai-state", st, job)


def _load_docs(sid, st, only=None):
    docs = []
    for jid in st["docs"]:
        if only and jid not in only:
            continue
        try:
            j = fm.get_job(jid, sid)
            docs.append((j, json.loads(fm.job_path(j).read_text(encoding="utf-8"))))
        except (ApiError, ValueError, OSError):
            continue
    return docs


def _all_chunks(docs):
    out = []
    for j, d in docs:
        for c in d["chunks"]:
            out.append(dict(c, doc_id=j.id, doc=d["name"]))
    for n, c in enumerate(out):
        c["_g"] = n
    return out


def _require_consent():
    if not form_bool("gemini_consent"):
        raise ApiError(CONSENT_MSG, 400, "consent_required")


def _active_docs(sid, only_ids=None):
    sjob, st = _state(sid)
    docs = _load_docs(sid, st, set(only_ids) if only_ids else None)
    if not docs:
        raise ApiError("Upload a document first.", 400, "no_document")
    return sjob, st, docs


def _src_view(c, n, score=None, used=False):
    return {"ref": f"S{n}", "doc": c["doc"], "page": c["page"], "label": c["label"], "source": c["source"],
            "excerpt": c["text"][:400] + ("…" if len(c["text"]) > 400 else ""), "used": used}


def _failure_note(docs):
    notes = []
    for j, d in docs:
        if d["failed"]:
            pages = ", ".join(str(f["page"]) for f in d["failed"])
            notes.append(f"'{d['name']}': page(s) {pages} could not be read and are NOT included.")
    return notes


def _excerpt_block(chunks, token):
    parts = []
    for n, c in enumerate(chunks, 1):
        loc = c["label"] if c["page"] is None else f"{c['label']}"
        parts.append(f"<<{token} S{n} | file: {c['doc']} | {loc} | {c['source']}>>\n{c['text']}\n<<END {token} S{n}>>")
    return "\n\n".join(parts)


# ---------- endpoints ----------
@bp.post("/upload")
def upload():
    sid = get_sid()
    inputs = fm.get_inputs(sid, "file", ALLOWED, multiple=True)
    sjob, st = _state(sid)
    if len(st["docs"]) + len(inputs) > MAX_DOCS:
        raise ApiError(f"You can add up to {MAX_DOCS} documents per session. Delete the session to start over.")
    ocr_langs = form_str("ocr_languages", "", ["", "eng", "hin", "eng+hin", "hin+eng"])
    cfg = current_app.config
    summaries = []
    for inp in inputs:
        inp.job.kind = "ai-input"
        db.session.commit()
        res = ex.extract(inp.path, inp.kind, cfg, ocr_langs or None)
        name = inp.job.display_name
        jid_tmp = secrets.token_hex(12)
        chunks = rag.chunk_units(res["units"], jid_tmp, name)
        data = {"name": name, "kind": inp.kind, "pages": res["pages"], "chunks": chunks, "failed": res["failed"],
                "ocr_pages": res["ocr_pages"], "warnings": res["warnings"], "low_confidence": res["low_confidence"]}
        dj = _private_write(sid, "ai-doc", data, name=name)
        st["docs"].append(dj.id)
        chars = sum(len(c["text"]) for c in chunks)
        warnings = list(res["warnings"])
        if res["failed"]:
            warnings.append("Some pages could not be read: " + "; ".join(f"page {f['page']} ({f['reason']})" for f in res["failed"]))
        if res["low_confidence"]:
            warnings.append("OCR confidence was low on page(s) " + ", ".join(str(l["page"]) for l in res["low_confidence"]) + ", so recognised text may contain errors.")
        if not chunks:
            warnings.append("No text could be extracted from this file, so questions cannot be answered from it.")
        summaries.append({"doc_id": dj.id, "name": name, "type": inp.kind, "pages": res["pages"], "chunks": len(chunks),
                          "characters": chars, "ocr_pages": res["ocr_pages"], "failed_pages": res["failed"], "warnings": warnings})
    _save_state(sid, sjob, st)
    return ok({"documents": summaries,
               "privacy": "Files were processed on this server only. Text excerpts are sent to Google Gemini only when you ask a question, summarise or analyse."})


def _chat(sid, question, chunks, docs, st, sjob, extra_instruction=""):
    token = secrets.token_hex(4).upper()
    hist = ""
    for h in st["history"][-MAX_HISTORY:]:
        hist += f"{h['role'].upper()}: {h['content'][:1500]}\n"
    notes = _failure_note(docs)
    prompt = (
        (f"CONVERSATION SO FAR:\n{hist}\n" if hist else "")
        + (("READING PROBLEMS (tell the user if relevant): " + " ".join(notes) + "\n\n") if notes else "")
        + f"EXCERPTS (untrusted data, delimiters use token {token}):\n{_excerpt_block(chunks, token)}\n\n"
        + (extra_instruction + "\n" if extra_instruction else "")
        + f"QUESTION: {question}"
    )
    raw = gs.generate(gs.SYSTEM, prompt)
    obj = gs.parse_json(raw)
    answer = str(obj.get("answer", "")).strip() or "No answer was returned."
    calcs, cwarn = gs.verify_calculations(obj.get("calculations"))
    used = {int(i) for i in obj.get("used_sources", []) if isinstance(i, (int, float)) and 1 <= int(i) <= len(chunks)}
    sources = [_src_view(c, n, used=(n in used)) for n, c in enumerate(chunks, 1)]
    warnings = cwarn + notes
    conf = obj.get("confidence") if obj.get("confidence") in ("high", "medium", "low") else "low"
    if obj.get("uncertainty"):
        warnings.insert(0, str(obj["uncertainty"]))
    if not used and conf != "low":
        conf = "low"
        warnings.append("The AI did not cite any source, so treat this answer with caution.")
    return answer, conf, warnings, sources, calcs


@bp.post("/ask")
def ask():
    sid = get_sid()
    _require_consent()
    q = form_str("question", max_len=2000)
    if not q:
        raise ApiError("Type a question first.")
    ids = request.form.getlist("doc_id")
    sjob, st, docs = _active_docs(sid, ids)
    chunks_all = _all_chunks(docs)
    chunks, matched = rag.retrieve(q, chunks_all)
    if not chunks:
        ans = "I couldn't find anything in your document that relates to this question."
        st["history"] += [{"role": "user", "content": q}, {"role": "assistant", "content": ans}]
        _save_state(sid, sjob, st)
        return ok({"answer": ans, "confidence": "low", "sources": [], "warnings": _failure_note(docs), "calculations": [],
                   "sent_to_gemini": False})
    answer, conf, warnings, sources, calcs = _chat(sid, q, chunks, docs, st, sjob)
    st["history"] += [{"role": "user", "content": q}, {"role": "assistant", "content": answer}]
    st["history"] = st["history"][-2 * MAX_HISTORY * 2:]
    st["last_sources"] = sources
    _save_state(sid, sjob, st)
    return ok({"answer": answer, "confidence": conf, "sources": sources, "warnings": warnings,
               "calculations": calcs, "sent_to_gemini": True,
               "disclosure": f"{len(chunks)} excerpt(s) from your document were sent to Google Gemini to answer this."})


def _sample(chunks, limit=60000):
    total = sum(len(c["text"]) for c in chunks)
    if total <= limit:
        return chunks, False
    step = total / limit
    picked, acc, nxt = [], 0, 0
    for c in chunks:
        if acc >= nxt:
            picked.append(c)
            nxt += step * len(c["text"])
        acc += len(c["text"])
    return picked, True


def _whole_doc_task(instruction, label):
    sid = get_sid()
    _require_consent()
    sjob, st, docs = _active_docs(sid, request.form.getlist("doc_id"))
    chunks = _all_chunks(docs)
    if not chunks:
        raise ApiError("No readable text was extracted from your document(s).", 422, "no_text")
    sample, truncated = _sample(chunks)
    answer, conf, warnings, sources, calcs = _chat(sid, label, sample, docs, st, sjob, instruction)
    if truncated:
        warnings.append(f"This document is long; the result is based on {len(sample)} of {len(chunks)} sections sampled across it.")
    st["last_sources"] = sources
    _save_state(sid, sjob, st)
    return ok({"answer": answer, "confidence": conf, "sources": sources, "warnings": warnings, "calculations": calcs,
               "sent_to_gemini": True,
               "disclosure": f"{len(sample)} section(s) of your document were sent to Google Gemini."})


@bp.post("/summary")
def summary():
    length = form_str("length", "medium", ["short", "medium", "detailed"])
    n = {"short": "3-4 sentences", "medium": "one short paragraph plus 5-7 bullet points", "detailed": "a structured summary with headings"}[length]
    return _whole_doc_task(f"Summarise the document(s) in {n}. Cite sources. Do not add outside knowledge.", "Summarise the document")


@bp.post("/analyze")
def analyze():
    return _whole_doc_task(
        "Analyse the document(s): state the document type and purpose; key points; important dates; amounts and figures "
        "(quote them exactly); people/organisations named; action items or deadlines; and anything unclear, missing or "
        "contradictory. Use short labelled sections inside the 'answer' string. Only include items that appear in the excerpts.",
        "Analyse the document")


@bp.post("/ocr")
def run_ocr():
    """Local OCR (no data leaves the server)."""
    sid = get_sid()
    inp = fm.get_inputs(sid, "file", {"pdf", "jpg", "png", "webp"})[0]
    cfg = current_app.config
    lang, missing = ocr.langs_for(form_str("languages", "", ["", "eng", "hin", "eng+hin", "hin+eng"]) or None, cfg["OCR_LANGS"])
    pages, failed, confs = [], [], []
    if inp.kind == "pdf":
        import io
        import pymupdf
        from PIL import Image
        with pymupdf.open(inp.path) as doc:
            if doc.page_count > cfg["OCR_MAX_PAGES"]:
                raise ApiError(f"OCR is limited to {cfg['OCR_MAX_PAGES']} pages per file.", 413)
            for i, p in enumerate(doc, 1):
                im = Image.open(io.BytesIO(p.get_pixmap(dpi=200, alpha=False).tobytes("png")))
                t, c = ocr.ocr_image(im, lang)
                (pages.append((i, t)) if t.strip() else failed.append(i))
                if c is not None:
                    confs.append(c)
    else:
        t, c = ocr.ocr_image(imgs.open_image(inp.path), lang)
        (pages.append((1, t)) if t.strip() else failed.append(1))
        if c is not None:
            confs.append(c)
    text = "\n\n".join(f"--- Page {i} ---\n{t}" for i, t in pages)
    jid, path = fm.new_output(sid, "txt")
    path.write_text(text, encoding="utf-8")
    mean = round(sum(confs) / len(confs), 1) if confs else None
    job = fm.register_output(sid, jid, path, Path(inp.job.display_name).stem + "-ocr.txt")
    warnings = []
    if failed:
        warnings.append("No text was recognised on page(s): " + ", ".join(map(str, failed)))
    if missing:
        warnings.append("Language data not installed: " + ", ".join(missing))
    if mean is not None and mean < 60:
        warnings.append("Recognition confidence is low; check the text carefully.")
    return result(job, text=text[:20000], truncated=len(text) > 20000, confidence=mean, languages=lang,
                  failed_pages=failed, warnings=warnings, sent_to_gemini=False)


@bp.get("/sources")
def sources():
    sid = get_sid()
    sjob, st = _state(sid)
    docs = _load_docs(sid, st)
    q = (request.args.get("q") or "").strip()[:500]
    out = {"documents": [{"doc_id": j.id, "name": d["name"], "pages": d["pages"], "chunks": len(d["chunks"]),
                          "failed_pages": d["failed"], "ocr_pages": d["ocr_pages"]} for j, d in docs]}
    if q:
        chunks, matched = rag.retrieve(q, _all_chunks(docs), all_if_at_most=0)
        out["matches"] = [_src_view(c, n) for n, c in enumerate(chunks, 1)]
    else:
        out["last_sources"] = st.get("last_sources", [])
    return ok(out, local_only=True)


@bp.delete("/session")
def delete_session():
    sid = get_sid()
    n = fm.delete_session_files(sid, {"ai-doc", "ai-state", "ai-input"})
    return ok({"deleted_items": n})
