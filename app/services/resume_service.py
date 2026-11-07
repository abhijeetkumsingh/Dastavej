"""Transparent, rule-based resume analysis. Every score point is explained in the output."""
import re
from collections import Counter

import pymupdf

from ..utils.responses import ApiError
from . import rag
from .resume_data import ACTION_VERBS, ROADMAP_PHASES, ROLES, SKILLS, WEAK_PHRASES

WEIGHTS = {"keywords": 25, "skills": 25, "experience": 15, "projects": 15, "structure": 10, "readability": 10}
DISCLAIMER = ("This is an ESTIMATED ATS-compatibility score produced by DASTAVEJ's own open scoring rules. It is not the "
              "score of any employer's actual ATS, and no ATS vendor's algorithm is used.")

SECTION_PATTERNS = {
    "summary": r"(?:professional |career )?(?:summary|objective|profile|about me|about)",
    "experience": r"(?:work |professional |relevant )?(?:experience|employment(?: history)?|internships?|work history)",
    "projects": r"(?:academic |personal |key )?projects?",
    "education": r"education(?:al)?(?: qualifications?| background)?|academics?|qualifications?",
    "skills": r"(?:technical |core |key )?skills(?: summary)?|technologies|tech stack|competencies",
    "certifications": r"certifications?|licen[sc]es|courses",
    "achievements": r"achievements?|awards?|accomplishments?|honou?rs|extra[- ]?curricular",
}
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"(?:\+?\d{1,3}[\s-]?)?(?:\(?\d{3,5}\)?[\s-]?)?\d{3,5}[\s-]?\d{4,5}")
URL = re.compile(r"(?:https?://|www\.)\S+|(?:github|linkedin|gitlab|behance|dribbble)\.com/\S+", re.I)
MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
DATE_RANGE = re.compile(rf"((?:{MONTHS})[a-z]*\.?\s*,?\s*\d{{4}}|\d{{1,2}}/\d{{4}}|\d{{4}})\s*(?:-|–|—|to)\s*((?:{MONTHS})[a-z]*\.?\s*,?\s*\d{{4}}|\d{{1,2}}/\d{{4}}|\d{{4}}|present|current|ongoing|now)", re.I)
NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?\s*(?:%|\+|x\b|k\b|lakh|crore|million|users|customers|students|records|ms|seconds|hours|days)|[$₹]\s?\d|\b\d{2,}\b")
BULLET = re.compile(r"^\s*(?:[-•*▪●◦‣·]|\d+[.)])\s+")


# ---------------------------------------------------------------- parsing
def split_sections(text):
    lines = [l.rstrip() for l in text.splitlines()]
    sections, cur = {"header": []}, "header"
    for ln in lines:
        s = ln.strip().strip(":").strip()
        found = None
        if s and len(s.split()) <= 4 and len(s) <= 40 and not BULLET.match(ln):
            for name, pat in SECTION_PATTERNS.items():
                if re.fullmatch(pat, s, re.I):
                    found = name
                    break
        if found:
            cur = found
            sections.setdefault(cur, [])
        else:
            sections.setdefault(cur, []).append(ln)
    return {k: "\n".join(v).strip() for k, v in sections.items() if "\n".join(v).strip() or k != "header"}


def find_skills(text):
    low = text.lower()
    found = {}
    for name, (cat, pats) in SKILLS.items():
        for p in pats:
            try:
                if re.search(p, low):
                    found[name] = cat
                    break
            except re.error:
                continue
    return found


def bullets_of(text):
    out = []
    for ln in text.splitlines():
        if BULLET.match(ln):
            out.append(BULLET.sub("", ln).strip())
    if not out:  # sentences-as-bullets fallback
        out = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n", text) if len(s.split()) >= 5]
    return [b for b in out if b]


def syllables(word):
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 0
    n = len(re.findall(r"[aeiouy]+", w))
    if w.endswith("e") and n > 1:
        n -= 1
    return max(1, n)


def flesch(text):
    sents = [s for s in re.split(r"[.!?\n]+", text) if len(s.split()) >= 3]
    words = re.findall(r"[A-Za-z']+", text)
    if not sents or not words:
        return None
    syl = sum(syllables(w) for w in words)
    return round(206.835 - 1.015 * (len(words) / len(sents)) - 84.6 * (syl / len(words)), 1)


# ---------------------------------------------------------------- formatting
def formatting_analysis(path, kind, text):
    info = {"file_type": kind, "issues": [], "good": []}
    if kind == "pdf":
        with pymupdf.open(path) as d:
            pages = d.page_count
            images = sum(len(p.get_images()) for p in d)
            fonts = {f[3] for p in d for f in p.get_fonts()}
            tables = 0
            multi_col = False
            for p in d:
                try:
                    tables += len(p.find_tables().tables)
                except Exception:
                    pass
                blocks = [b for b in p.get_text("blocks") if b[6] == 0 and len(b[4].split()) > 6]
                if len(blocks) >= 4:
                    mid = p.rect.width / 2
                    left = [b for b in blocks if b[2] < mid * 1.05]
                    right = [b for b in blocks if b[0] > mid * 0.95]
                    if len(left) >= 2 and len(right) >= 2:
                        multi_col = True
        info.update(pages=pages, images=images, fonts=len(fonts), tables=tables, multi_column=multi_col)
        if pages > 2:
            info["issues"].append(f"Resume is {pages} pages; 1-2 pages is the norm (1 page for freshers).")
        else:
            info["good"].append(f"Length is {pages} page(s).")
        if images:
            info["issues"].append(f"{images} image(s) found. Photos, icons and graphics are ignored by most ATS and can hide text.")
        if tables:
            info["issues"].append("Tables detected. Some ATS read tables out of order; prefer simple headings and bullets.")
        if multi_col:
            info["issues"].append("A multi-column layout was detected. ATS often read columns in the wrong order.")
        if len(fonts) > 4:
            info["issues"].append(f"{len(fonts)} different fonts used; stick to 1-2 for a clean, parseable look.")
    else:
        import docx
        d = docx.Document(str(path))
        xml = d.element.xml
        tables = len(d.tables)
        images = len(d.inline_shapes)
        textboxes = "txbxContent" in xml
        cols = bool(re.search(r'<w:cols[^>]*w:num="[2-9]"', xml))
        words = len(text.split())
        pages = max(1, round(words / 500))
        info.update(pages_estimated=pages, tables=tables, images=images, text_boxes=textboxes, multi_column=cols)
        if tables:
            info["issues"].append("Tables detected. Some ATS read tables out of order.")
        if images:
            info["issues"].append("Images detected; ATS ignore them.")
        if textboxes:
            info["issues"].append("Text boxes detected. Many ATS skip text inside text boxes entirely.")
        if cols:
            info["issues"].append("Multiple columns detected; ATS may read them out of order.")
        if pages > 2:
            info["issues"].append(f"Resume looks about {pages} pages (estimated from word count).")
    if len(text.strip()) < 300:
        info["issues"].append("Very little text could be extracted. If this is a scanned/image resume, ATS cannot read it.")
    info["word_count"] = len(text.split())
    return info


# ---------------------------------------------------------------- analysis parts
def contact_info(header_text, full):
    head = header_text + "\n" + full[:600]
    return {"email": bool(EMAIL.search(head)), "phone": bool(PHONE.search(head)),
            "links": [m.group(0).rstrip(".,)") for m in URL.finditer(full)][:6],
            "linkedin": bool(re.search(r"linkedin\.com", full, re.I)), "github": bool(re.search(r"github\.com", full, re.I))}


def education_analysis(txt):
    out = {"present": bool(txt.strip()), "degrees": [], "years": [], "scores": [], "suggestions": []}
    if not txt.strip():
        out["suggestions"].append("Add an Education section with degree, institution and year.")
        return out
    degs = re.findall(r"\b(b\.?\s?tech|b\.?\s?e\.?|b\.?\s?sc|b\.?\s?ca|b\.?\s?com|b\.?\s?a\b|m\.?\s?tech|m\.?\s?sc|m\.?\s?ca|mba|bachelor[^,\n]{0,30}|master[^,\n]{0,30}|diploma[^,\n]{0,20}|ph\.?d|12th|10th|hsc|ssc|intermediate|matriculation)", txt, re.I)
    out["degrees"] = sorted({d.strip() for d in degs})[:8]
    out["years"] = sorted(set(re.findall(r"\b(?:19|20)\d{2}\b", txt)))
    out["scores"] = re.findall(r"(?:cgpa|gpa|percentage|score)\s*[:\-]?\s*\d+(?:\.\d+)?\s*(?:%|/\s*\d+)?|\d{2}(?:\.\d+)?\s?%|\d(?:\.\d+)?\s*/\s*10", txt, re.I)[:6]
    if not out["degrees"]:
        out["suggestions"].append("Name your degree explicitly (e.g. B.Tech in Computer Science).")
    if not out["years"]:
        out["suggestions"].append("Add graduation / expected graduation years.")
    if not out["scores"]:
        out["suggestions"].append("Add CGPA or percentage if it is strong (many Indian campus recruiters filter on it).")
    return out


def _months(m1, m2):
    def parse(s):
        s = s.lower().strip()
        if s in ("present", "current", "ongoing", "now"):
            return 2026 * 12 + 10
        y = re.search(r"\d{4}", s)
        if not y:
            return None
        mo = 6
        mm = re.search(MONTHS, s)
        if mm:
            mo = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"].index(mm.group(0)[:3]) + 1
        sl = re.match(r"(\d{1,2})/(\d{4})", s)
        if sl:
            mo = int(sl.group(1))
        return int(y.group(0)) * 12 + mo
    a, b = parse(m1), parse(m2)
    return max(0, b - a) if a and b else 0


def experience_analysis(txt, role_kw):
    out = {"present": bool(txt.strip()), "entries": 0, "estimated_months": 0, "internship_mentioned": False,
           "bullets": 0, "action_verb_bullets": 0, "suggestions": []}
    if not txt.strip():
        out["suggestions"].append("No Experience/Internship section found. Freshers can add internships, freelance work or open-source contributions.")
        return out
    ranges = DATE_RANGE.findall(txt)
    out["entries"] = len(ranges)
    out["estimated_months"] = min(sum(_months(a, b) for a, b in ranges), 480)
    out["internship_mentioned"] = bool(re.search(r"intern", txt, re.I))
    bl = bullets_of(txt)
    out["bullets"] = len(bl)
    out["action_verb_bullets"] = sum(1 for b in bl if b.split() and b.split()[0].lower().strip(",.") in ACTION_VERBS)
    if not ranges:
        out["suggestions"].append("Add start and end dates (e.g. Jun 2025 - Aug 2025) to each experience entry.")
    if bl and out["action_verb_bullets"] < len(bl) / 2:
        out["suggestions"].append("Start more bullets with strong action verbs (Built, Reduced, Automated, Led...).")
    return out


def project_analysis(txt, role_skills):
    out = {"present": bool(txt.strip()), "count": 0, "projects": [], "suggestions": []}
    if not txt.strip():
        out["suggestions"].append("Add a Projects section: 2-4 projects with tech stack, what you built and the outcome.")
        return out
    blocks, cur = [], []
    for ln in txt.splitlines():
        if not ln.strip():
            if cur:
                blocks.append(cur); cur = []
            continue
        if cur and not BULLET.match(ln) and len(ln.split()) <= 12 and any(BULLET.match(x) for x in cur):
            blocks.append(cur); cur = []
        cur.append(ln)
    if cur:
        blocks.append(cur)
    for b in blocks:
        body = "\n".join(b)
        title = re.sub(r"[|\-–—:].*$", "", BULLET.sub("", b[0])).strip()[:70] or "Project"
        skills = sorted(find_skills(body))
        out["projects"].append({"title": title, "skills": skills, "has_link": bool(URL.search(body)),
                                "has_metric": bool(NUMBER_RE.search(body)), "bullets": len(bullets_of(body))})
    out["projects"] = [p for p in out["projects"] if p["skills"] or p["bullets"] or p["has_link"]][:8] or out["projects"][:8]
    out["count"] = len(out["projects"])
    if out["count"] < 2:
        out["suggestions"].append("Aim for 2-4 well-described projects.")
    if out["projects"] and not any(p["has_link"] for p in out["projects"]):
        out["suggestions"].append("Add GitHub or live-demo links to your projects.")
    if out["projects"] and not any(p["has_metric"] for p in out["projects"]):
        out["suggestions"].append("Quantify project outcomes (users, speed-ups, accuracy, size of data).")
    if out["projects"] and sum(1 for p in out["projects"] if not p["skills"]) > 0:
        out["suggestions"].append("Name the technologies used in every project.")
    return out


def achievement_analysis(text):
    bl = bullets_of(text)
    quant = [b for b in bl if NUMBER_RE.search(b)]
    weak = [b for b in bl if any(w in b.lower() for w in WEAK_PHRASES)]
    return {"bullets_total": len(bl), "quantified": len(quant), "quantified_ratio": round(len(quant) / len(bl), 2) if bl else 0,
            "strongest": [q[:160] for q in quant[:3]], "needs_work": [w[:160] for w in weak[:4]],
            "suggestions": (["Add numbers to more bullets (percent improved, users, time saved, records processed)."] if bl and len(quant) / len(bl) < 0.3 else [])
            + (["Replace vague phrases like 'responsible for' / 'worked on' with specific actions and results."] if weak else [])}


def grammar_readability(text):
    """Heuristic checks only - not a full grammar checker."""
    issues = []
    for m in re.finditer(r"\b(\w+)\s+\1\b", text, re.I):
        w = m.group(1)
        if w.isalpha() and w.lower() not in ("that", "had"):
            issues.append(f"Repeated word: '{w} {w}'")
    if re.search(r"[^\S\n]{3,}", text) and False:
        pass
    if re.search(r"\bi\b(?! am)", text) and re.search(r"\bI (?:am|have|did|was)\b|\bmy\b", text):
        issues.append("Avoid first-person pronouns (I, my) in resume bullets.")
    for ln in text.splitlines():
        s = BULLET.sub("", ln).strip()
        if s and BULLET.match(ln) and s[0].islower():
            issues.append(f"Bullet starts with a lowercase letter: '{s[:50]}'")
            break
    passive = re.findall(r"\b(?:was|were|been|being)\s+\w+ed\b", text, re.I)
    if len(passive) >= 3:
        issues.append(f"{len(passive)} possible passive-voice phrases; active verbs read stronger.")
    long_bullets = [b for b in bullets_of(text) if len(b.split()) > 35]
    if long_bullets:
        issues.append(f"{len(long_bullets)} very long bullet(s) (over 35 words). Keep bullets to 1-2 lines.")
    weak = [w for w in WEAK_PHRASES if w in text.lower()]
    if weak:
        issues.append("Weak/cliché phrases found: " + ", ".join(weak[:5]))
    return {"flesch_reading_ease": flesch(text), "issues": issues[:12],
            "note": "Rule-based checks for common problems; use a proofreader or grammar tool for a full review."}


# ---------------------------------------------------------------- JD handling
def jd_keywords(jd, n=25):
    skills = sorted(find_skills(jd))
    toks = Counter(t for t in rag.tokens(jd) if len(t) > 3 and not t.isdigit())
    common = [w for w, c in toks.most_common(60) if c >= 2 and w not in {"experience", "work", "team", "will", "ability", "years", "strong", "skills", "role", "job", "candidate", "required", "preferred", "knowledge", "working", "good", "company", "responsibilities", "requirements", "including"}]
    kws = []
    for k in skills + common:
        if k not in kws:
            kws.append(k)
    return kws[:n], skills


def kw_present(kw, low, tokset):
    if " " in kw or any(c in kw for c in ".+#/"):
        return kw in low
    return kw in tokset or any(t.startswith(kw) for t in tokset if len(kw) >= 5)


# ---------------------------------------------------------------- main
def analyze_resume(text, path, kind, role, jd=None, custom_role=None):
    if len(text.strip()) < 80:
        raise ApiError("Very little text could be read from this resume. Use a text-based PDF or DOCX.", 422, "no_text")
    if role == "Custom":
        if not (jd and jd.strip()):
            raise ApiError("For a custom job role, paste the job description so skills can be matched.")
        profile = {"required": [], "optional": [], "keywords": [], "projects": [], "courses": [], "certs": []}
        role_name = (custom_role or "Custom role").strip()[:60] or "Custom role"
    elif role in ROLES:
        profile, role_name = ROLES[role], role
    else:
        raise ApiError("Unknown job role.")
    low = text.lower()
    tokset = set(rag.TOKEN.findall(low))
    sections = split_sections(text)
    resume_skills = find_skills(text)
    jd = (jd or "").strip()[:20000]
    jd_kws, jd_skills = jd_keywords(jd) if jd else ([], [])

    # target sets
    if jd:
        req = jd_skills or profile["required"]
        opt = [s for s in profile["required"] + profile["optional"] if s not in req] if profile["required"] else []
        keywords = jd_kws
        basis = "job description"
    else:
        req, opt, keywords, basis = profile["required"], profile["optional"], profile["keywords"] + profile["required"], f"{role_name} role profile"
    req_found = [s for s in req if s in resume_skills]
    opt_found = [s for s in opt if s in resume_skills]
    kw_hit = [k for k in keywords if kw_present(k, low, tokset)]
    kw_miss = [k for k in keywords if k not in kw_hit]

    exp = experience_analysis(sections.get("experience", ""), keywords)
    proj = project_analysis(sections.get("projects", ""), req)
    edu = education_analysis(sections.get("education", ""))
    contact = contact_info("\n".join(sections.get("header", "").splitlines()[:8]), text)
    ach = achievement_analysis(sections.get("experience", "") + "\n" + sections.get("projects", "") + "\n" + sections.get("achievements", ""))
    gr = grammar_readability(text)
    fmt = formatting_analysis(path, kind, text)

    # ---- scoring (each component explains itself)
    breakdown = []

    def comp(key, name, score, notes):
        mx = WEIGHTS[key]
        breakdown.append({"key": key, "name": name, "max": mx, "score": round(max(0, min(mx, score)), 1), "notes": notes})

    kscore = (len(kw_hit) / len(keywords) * 25) if keywords else 0
    comp("keywords", "Keyword match", kscore, [f"{len(kw_hit)} of {len(keywords)} target keywords found (basis: {basis})."]
         + ([f"Missing: {', '.join(kw_miss[:8])}"] if kw_miss else []))
    denom = len(req) + 0.5 * len(opt)
    sscore = ((len(req_found) + 0.5 * len(opt_found)) / denom * 25) if denom else 0
    comp("skills", "Skills match", sscore, [f"{len(req_found)} of {len(req)} required skills found; {len(opt_found)} of {len(opt)} optional (worth half)."])

    e_notes, e = [], 0.0
    if exp["present"]:
        e += 5; e_notes.append("Experience/Internship section present (+5).")
        role_terms = [k for k in (req + opt + keywords) if kw_present(k, sections.get("experience", "").lower(), set(rag.TOKEN.findall(sections.get("experience", "").lower())))]
        r = min(5, len(set(role_terms)) / max(1, min(6, len(set(req + keywords)))) * 5)
        e += r; e_notes.append(f"{len(set(role_terms))} role-relevant term(s) inside experience (+{r:.1f}).")
        if exp["entries"]:
            e += 2; e_notes.append("Dated entries found (+2).")
        if exp["bullets"] and exp["action_verb_bullets"] >= max(1, exp["bullets"] // 2):
            e += 3; e_notes.append("Most bullets start with action verbs (+3).")
    else:
        e_notes.append("No experience section. Fresher profiles lose points here; internships and freelance work help.")
    comp("experience", "Experience relevance", e, e_notes)

    p_notes, p = [], 0.0
    if proj["present"]:
        a = min(6, proj["count"] * 1.5); p += a; p_notes.append(f"{proj['count']} project(s) found (+{a:.1f}, max 6 for 4 projects).")
        ptxt = sections.get("projects", "").lower()
        pt = set(rag.TOKEN.findall(ptxt))
        rel = [k for k in set(req + opt) if kw_present(k, ptxt, pt)]
        b = min(6, len(rel) / max(1, len(set(req))) * 6); p += b; p_notes.append(f"{len(rel)} role skill(s) shown in projects (+{b:.1f}).")
        if any(x["has_link"] for x in proj["projects"]):
            p += 3; p_notes.append("Project link(s) present (+3).")
    else:
        p_notes.append("No Projects section found.")
    comp("projects", "Project relevance", p, p_notes)

    s_notes, s = [], 0.0
    for key, label, pts in (("education", "Education", 2), ("skills", "Skills section", 2), ("summary", "Summary/Objective", 1)):
        if key in sections:
            s += pts; s_notes.append(f"{label} present (+{pts}).")
        else:
            s_notes.append(f"{label} missing.")
    if contact["email"] and contact["phone"]:
        s += 2; s_notes.append("Email and phone found (+2).")
    else:
        s_notes.append("Email and/or phone not detected near the top.")
    if "experience" in sections or "projects" in sections:
        s += 2; s_notes.append("Experience or Projects present (+2).")
    pages = fmt.get("pages") or fmt.get("pages_estimated") or 1
    if pages <= 2 and not fmt["issues"][:0]:
        s += 1; s_notes.append("Length within 2 pages (+1).")
    s -= min(2, 0.5 * len([i for i in fmt["issues"] if any(w in i for w in ("Tables", "multi-column", "Text boxes", "Multiple columns"))]))
    comp("structure", "Structure & formatting", s, s_notes + (["Formatting penalties: " + "; ".join(fmt["issues"][:3])] if fmt["issues"] else []))

    r_notes, r = [], 0.0
    bl = bullets_of(text)
    if bl:
        avg = sum(len(b.split()) for b in bl) / len(bl)
        if 8 <= avg <= 25:
            r += 4; r_notes.append(f"Average bullet length {avg:.0f} words (+4).")
        else:
            r_notes.append(f"Average bullet length {avg:.0f} words; aim for 8-25.")
        r += 2; r_notes.append("Bullet points used (+2).")
    else:
        r_notes.append("No bullet points detected.")
    if ach["quantified"] >= 3:
        r += 2; r_notes.append("3+ quantified achievements (+2).")
    elif ach["quantified"]:
        r += 1; r_notes.append("Some quantified achievements (+1).")
    if not ach["needs_work"]:
        r += 1; r_notes.append("No weak/vague phrases (+1).")
    if not any("first-person" in i for i in gr["issues"]):
        r += 1; r_notes.append("No first-person pronouns (+1).")
    comp("readability", "Readability & impact", r, r_notes)

    total = round(sum(b["score"] for b in breakdown))
    label = "Strong" if total >= 75 else "Good" if total >= 60 else "Needs work" if total >= 40 else "Weak match"

    # ---- suggestions & recommendations
    missing_req = [s for s in req if s not in resume_skills]
    missing_opt = [s for s in opt if s not in resume_skills][:8]
    skills_text = sections.get("skills", "").lower()
    evidence = (sections.get("experience", "") + sections.get("projects", "")).lower()
    unevidenced = [s for s in find_skills(skills_text) if s not in find_skills(evidence)] if skills_text and evidence else []
    by_cat = {}
    for s, c in resume_skills.items():
        by_cat.setdefault(c, []).append(s)
    suggestions = []
    for sec in (exp, proj, edu, ach):
        suggestions += sec.get("suggestions", [])
    if missing_req:
        suggestions.insert(0, "Add (only if true) or learn these core skills: " + ", ".join(missing_req[:6]) + ".")
    if unevidenced:
        suggestions.append("These skills are listed but not backed by a project or job: " + ", ".join(unevidenced[:6]) + ".")
    if "summary" not in sections:
        suggestions.append("Add a 2-3 line summary tailored to the target role.")
    if not contact["linkedin"] or not contact["github"] and role_name not in ("Digital Marketing", "UI/UX Designer"):
        suggestions.append("Include LinkedIn and GitHub links near the top.")
    suggestions += fmt["issues"]

    gaps = (missing_req + missing_opt)[:7]
    roadmap = []
    per = 0
    for (title, n) in ROADMAP_PHASES:
        items = []
        chunk = gaps[per:per + n]
        per += n
        for g in chunk:
            items.append(f"Learn {g} and show it in a small project or in an existing one.")
        if title.startswith("Months 4") or not items:
            items.append("Polish resume with quantified results and apply to 5-10 targeted roles per week.")
        if title.startswith("Months 2") and profile.get("projects"):
            items.append("Build: " + profile["projects"][0])
        roadmap.append({"phase": title, "actions": items})

    result = {
        "role": role_name, "score": total, "score_label": label, "score_basis": basis, "disclaimer": DISCLAIMER,
        "breakdown": breakdown, "weights": WEIGHTS,
        "sections_found": [k for k in sections if k != "header"],
        "contact": contact,
        "skills": {"found": sorted(resume_skills), "by_category": by_cat, "required_target": req, "missing_required": missing_req,
                   "missing_optional": missing_opt, "listed_but_unevidenced": unevidenced},
        "keywords": {"matched": kw_hit, "missing": kw_miss, "basis": basis},
        "formatting": fmt, "education": edu, "experience": exp, "projects": proj, "achievements": ach, "grammar": gr,
        "suggestions": suggestions[:20],
        "recommendations": {
            "projects": profile["projects"], "courses": profile["courses"], "certifications": profile["certs"],
            "note": "Suggestions only - check each course/certificate's current availability and cost."
            if profile["courses"] else "Custom role: recommendations are derived from the job description gaps above."},
        "roadmap": roadmap,
    }
    if jd:
        result["jd_match"] = {"matched_keywords": kw_hit, "missing_keywords": kw_miss, "matched_skills": req_found,
                              "missing_skills": missing_req, "match_percent_keywords": round(100 * len(kw_hit) / max(1, len(keywords))),
                              "match_percent_skills": round(100 * len(req_found) / max(1, len(req)))}
    return result
