"""Helpers shared by API blueprints: form parsing and result formatting."""
import json

from flask import request

from ..utils.responses import ApiError, ok


def form_str(name, default="", choices=None, max_len=500):
    v = (request.form.get(name) if name in request.form else default) or default
    v = str(v).strip()[:max_len]
    if choices and v not in choices:
        raise ApiError(f"Invalid value for '{name}'. Allowed: {', '.join(choices)}.")
    return v


def form_int(name, default=None, lo=None, hi=None):
    raw = request.form.get(name)
    if raw in (None, ""):
        if default is None:
            raise ApiError(f"'{name}' is required.")
        return default
    try:
        v = int(float(raw))
    except ValueError:
        raise ApiError(f"'{name}' must be a number.")
    if lo is not None and v < lo or hi is not None and v > hi:
        raise ApiError(f"'{name}' must be between {lo} and {hi}.")
    return v


def form_float(name, default=None, lo=None, hi=None):
    raw = request.form.get(name)
    if raw in (None, ""):
        if default is None:
            raise ApiError(f"'{name}' is required.")
        return default
    try:
        v = float(raw)
    except ValueError:
        raise ApiError(f"'{name}' must be a number.")
    if v != v or (lo is not None and v < lo) or (hi is not None and v > hi):
        raise ApiError(f"'{name}' must be between {lo} and {hi}.")
    return v


def form_bool(name, default=False):
    raw = request.form.get(name)
    if raw is None:
        return default
    return str(raw).lower() in ("1", "true", "on", "yes")


def form_json(name, default=None, max_len=200_000):
    raw = request.form.get(name)
    if not raw:
        return default
    if len(raw) > max_len:
        raise ApiError(f"'{name}' is too large.")
    try:
        return json.loads(raw)
    except ValueError:
        raise ApiError(f"'{name}' is not valid JSON.")


def parse_page_spec(spec, total, allow_dupes=True):
    """'1-3,5,8-' -> [0,1,2,4,7,...] (zero-based). Validates against page count."""
    spec = (spec or "").replace(" ", "")
    if not spec:
        raise ApiError("Please enter page numbers, e.g. 1-3,5.")
    pages = []
    for part in spec.split(","):
        if not part:
            continue
        try:
            if "-" in part:
                a, b = part.split("-", 1)
                a = int(a) if a else 1
                b = int(b) if b else total
            else:
                a = b = int(part)
        except ValueError:
            raise ApiError(f"Invalid page range '{part}'.")
        if a < 1 or b < a or b > total:
            raise ApiError(f"Page range '{part}' is outside 1-{total}.")
        pages.extend(range(a - 1, b))
    if not pages:
        raise ApiError("No pages selected.")
    if not allow_dupes:
        seen, uniq = set(), []
        for p in pages:
            if p not in seen:
                seen.add(p)
                uniq.append(p)
        pages = uniq
    return pages


def result(job, **extra):
    d = job.to_dict()
    return ok({"result": d}, **extra)
