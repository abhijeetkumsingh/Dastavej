"""Local retrieval: chunking + BM25 (no external service, Devanagari-aware tokenisation)."""
import math
import re
from collections import Counter

TOKEN = re.compile(r"[\w\u0900-\u097F]+", re.UNICODE)
STOP = set("a an the and or of to in on for with is are was were be been it this that as at by from i you we they he she what which who how when where why do does did not no yes if then than so can could should would will".split())


def tokens(text):
    return [t for t in TOKEN.findall(text.lower()) if t not in STOP and len(t) > 1 or t.isdigit()]


def chunk_units(units, doc_id, doc_name, size=900, overlap=120):
    chunks = []
    for u in units:
        text = u["text"]
        if len(text) <= size:
            parts = [text]
        else:
            parts, i = [], 0
            while i < len(text):
                end = min(len(text), i + size)
                if end < len(text):  # try to end on a sentence/line boundary
                    cut = max(text.rfind("\n", i, end), text.rfind(". ", i, end), text.rfind("।", i, end))
                    if cut > i + size // 2:
                        end = cut + 1
                parts.append(text[i:end])
                if end >= len(text):
                    break
                i = max(end - overlap, i + 1)
        for p in parts:
            if p.strip():
                chunks.append({"doc_id": doc_id, "doc": doc_name, "page": u["page"], "label": u["label"],
                               "source": u["source"], "text": p.strip()})
    for n, c in enumerate(chunks):
        c["id"] = n
    return chunks


def bm25_rank(query, chunks, k1=1.4, b=0.75):
    q = tokens(query)
    if not chunks:
        return []
    docs = [Counter(tokens(c["text"] + " " + c["label"])) for c in chunks]
    lens = [sum(d.values()) or 1 for d in docs]
    avg = sum(lens) / len(lens)
    N = len(chunks)
    df = Counter()
    for d in docs:
        for t in set(q):
            if t in d:
                df[t] += 1
    scores = []
    for i, d in enumerate(docs):
        s = 0.0
        for t in set(q):
            if df[t] == 0:
                continue
            idf = math.log(1 + (N - df[t] + 0.5) / (df[t] + 0.5))
            f = d.get(t, 0)
            s += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * lens[i] / avg))
        scores.append(s)
    order = sorted(range(N), key=lambda i: scores[i], reverse=True)
    return [(chunks[i], scores[i]) for i in order]


def retrieve(query, chunks, k=8, all_if_at_most=10):
    """Return (chunks_selected, any_match). Small docs are passed whole."""
    ranked = bm25_rank(query, chunks)
    any_match = bool(ranked) and ranked[0][1] > 0
    if len(chunks) <= all_if_at_most:
        return list(chunks), any_match
    if not any_match:
        return [], False
    top = [c for c, s in ranked[:k] if s > 0]
    top.sort(key=lambda c: c["id"])  # keep document order for readability
    return top, True
