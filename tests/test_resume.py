import io

import docx
import pymupdf
import pytest

from app.services import resume_service as rs

GOOD = """Abhijeet Kumar
abhijeet@example.com | +91 98765 43210 | github.com/abhijeet | linkedin.com/in/abhijeet

Summary
Computer science student building web applications with Python and Flask.

Education
B.Tech in Computer Science and Engineering (AI), Government Engineering College, 2023 - 2027
CGPA: 8.1/10

Skills
Python, Flask, SQL, PostgreSQL, Git, HTML, CSS, JavaScript, REST API, Docker, pytest

Experience
Data Analyst Intern, CivicAtlas (Jun 2025 - Aug 2025)
- Built dashboards in Python and SQL that reduced reporting time by 40%
- Automated data cleaning for 12,000 records using pandas
- Presented insights to 3 stakeholders weekly

Projects
RoomBandhu - Student room listing platform
- Developed a Flask and Firebase web app with authentication and an admin panel used by 150 students
- Deployed with Docker, wrote unit tests with pytest. github.com/abhijeet/roombandhu
JalSeva - Civic water issue tracker
- Created REST API with PostgreSQL to track 500 complaints and improved response visibility by 30%
"""

WEAK = """Ravi
Responsible for many things. Worked on stuff. I am a hard working team player and i like computers.
Education
10th pass
"""


def mkdocx(text):
    d = docx.Document()
    for ln in text.splitlines():
        d.add_paragraph(ln)
    b = io.BytesIO(); d.save(b); return b.getvalue()


def mkpdf(text):
    doc = pymupdf.open()
    page = doc.new_page()
    y = 50
    for ln in text.splitlines():
        if y > 800:
            page = doc.new_page(); y = 50
        page.insert_text((50, y), ln, fontsize=9)
        y += 12
    return doc.tobytes()


def post(api, url, content, name, **data):
    d = dict(data); d["file"] = (io.BytesIO(content), name)
    return api.post(url, d)


def test_score_range_and_weights():
    assert sum(rs.WEIGHTS.values()) == 100
    assert rs.WEIGHTS == {"keywords": 25, "skills": 25, "experience": 15, "projects": 15, "structure": 10, "readability": 10}


def test_analyze_good_resume_docx(api):
    j = post(api, "/api/resume/analyze", mkdocx(GOOD), "r.docx", role="Python Developer").get_json()
    assert j["ok"] and j["estimated"] is True, j
    a = j["analysis"]
    assert 55 <= a["score"] <= 100
    assert "ESTIMATED" in a["disclaimer"] and "not the score of any employer" in a["disclaimer"]
    assert {b["key"] for b in a["breakdown"]} == set(rs.WEIGHTS)
    assert all(b["score"] <= b["max"] for b in a["breakdown"]) and all(b["notes"] for b in a["breakdown"])
    assert abs(sum(b["score"] for b in a["breakdown"]) - a["score"]) <= 3
    assert {"python", "flask", "sql", "git"} <= set(a["skills"]["found"])
    assert a["experience"]["estimated_months"] == 2 and a["experience"]["internship_mentioned"]
    assert a["projects"]["count"] >= 2 and a["education"]["scores"]
    assert a["achievements"]["quantified"] >= 4
    assert a["roadmap"] and a["recommendations"]["courses"]
    pdf = api.download(a["report"])
    assert pdf[:5] == b"%PDF-" and "Estimated ATS" in pymupdf.open(stream=pdf, filetype="pdf")[0].get_text()


def test_pdf_resume_and_ordering_good_beats_weak(api):
    good = post(api, "/api/resume/ats-score", mkpdf(GOOD), "r.pdf", role="Python Developer").get_json()
    weak = post(api, "/api/resume/ats-score", mkpdf(GOOD.split("Summary")[0] + WEAK * 3), "w.pdf", role="Python Developer").get_json()
    assert good["ok"] and weak["ok"]
    assert good["score"] > weak["score"] + 15


def test_missing_skills_for_role(api):
    j = post(api, "/api/resume/skills", mkdocx(GOOD), "r.docx", role="Data Scientist").get_json()
    miss = j["skills"]["missing_required"]
    assert "machine learning" in miss and "scikit-learn" in miss and "python" not in miss


def test_jd_match(api):
    jd = "We need a Python Flask developer with PostgreSQL, Docker and Kubernetes experience. Kubernetes is mandatory. Strong REST API design."
    j = post(api, "/api/resume/jd-match", mkdocx(GOOD), "r.docx", role="Backend Developer", job_description=jd).get_json()
    assert j["ok"], j
    m = j["jd_match"]
    assert "kubernetes" in m["missing_skills"] and "flask" in m["matched_skills"]
    assert 0 < m["match_percent_skills"] < 100
    assert post(api, "/api/resume/jd-match", mkdocx(GOOD), "r.docx", role="Backend Developer").status_code == 400


def test_custom_role_needs_jd(api):
    assert post(api, "/api/resume/analyze", mkdocx(GOOD), "r.docx", role="Custom").status_code == 400
    j = post(api, "/api/resume/analyze", mkdocx(GOOD), "r.docx", role="Custom", custom_role="Civic Tech Engineer",
             job_description="Looking for a civic technology engineer with Flask, Firebase and data skills.").get_json()
    assert j["ok"] and j["analysis"]["role"] == "Civic Tech Engineer"


def test_formatting_flags_tables_and_images(api):
    d = docx.Document(); d.add_paragraph(GOOD); t = d.add_table(rows=2, cols=2); t.cell(0, 0).text = "x"
    b = io.BytesIO(); d.save(b)
    j = post(api, "/api/resume/analyze", b.getvalue(), "t.docx", role="Python Developer").get_json()
    assert any("Tables" in i for i in j["analysis"]["formatting"]["issues"])


def test_roadmap_projects_endpoints_and_upload(api):
    assert post(api, "/api/resume/roadmap", mkdocx(GOOD), "r.docx", role="AI/ML Engineer").get_json()["roadmap"]
    assert post(api, "/api/resume/projects", mkdocx(GOOD), "r.docx", role="Frontend Developer").get_json()["projects"]["count"] >= 2
    u = post(api, "/api/resume/upload", mkdocx(GOOD), "r.docx").get_json()
    assert u["input"]["characters"] > 300
    a = api.post("/api/resume/analyze", {"file_id": u["input"]["job_id"], "role": "Software Developer", "report": "false"}).get_json()
    assert a["ok"] and "report" not in a["analysis"]


def test_invalid_inputs(api):
    assert post(api, "/api/resume/analyze", mkdocx(GOOD), "r.docx", role="Astronaut").status_code == 400
    assert post(api, "/api/resume/analyze", b"just text", "r.txt", role="Python Developer").status_code == 415
    assert post(api, "/api/resume/analyze", mkdocx("tiny"), "r.docx", role="Python Developer").status_code == 422
    assert post(api, "/api/resume/analyze", mkpdf(GOOD)[:300], "bad.pdf", role="Python Developer").status_code == 400
