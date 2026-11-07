import io
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from tests.conftest import png_bytes

PAGES = ["/", "/image-tools", "/pdf-tools", "/scanner", "/passport-photo", "/converter", "/ai-assistant", "/resume-analyzer"]
STATIC = Path(__file__).resolve().parent.parent / "app" / "static"


class P(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.assets, self.tabs, self.ids, self.forms, self.inline_scripts, self.handlers = [], [], set(), set(), [], 0, []
        self.csrf = None
        self.in_script = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
        if "data-tab" in a:
            self.tabs.add(a["data-tab"])
        if "data-endpoint" in a:
            self.forms.append(a["data-endpoint"])
        for k in a:
            if k.startswith("on") and k not in ("onclick_",):
                self.handlers.append((tag, k))
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
        if tag == "link" and a.get("href"):
            self.assets.append(a["href"])
        if tag == "img" and a.get("src"):
            self.assets.append(a["src"])
        if tag == "script":
            if a.get("src"):
                self.assets.append(a["src"])
            else:
                self.inline_scripts += 1
        if tag == "meta" and a.get("name") == "csrf-token":
            self.csrf = a.get("content")


def parse(client, url):
    r = client.get(url)
    assert r.status_code == 200, url
    p = P()
    p.feed(r.get_data(as_text=True))
    return p


@pytest.fixture()
def client(api):
    return api.c


def test_all_pages_render_with_brand_and_security(client):
    for url in PAGES:
        p = parse(client, url)
        assert p.csrf, url
        assert p.inline_scripts == 0, f"inline script on {url} would violate CSP"
        assert not p.handlers, f"inline event handlers on {url}: {p.handlers}"
        html = client.get(url).get_data(as_text=True)
        assert "DASTAVEJ" in html and "All Your Document Needs, One Place." in html
        for nav in ("Image Tools", "PDF Tools", "Document Scanner", "AI Assistant", "Resume Analyzer", "File Converter"):
            assert nav in html, (url, nav)


def test_all_assets_exist(client):
    for url in PAGES:
        for a in parse(client, url).assets:
            if a.startswith("data:"):
                continue
            assert a.startswith("/static/"), a
            assert client.get(a).status_code == 200, f"{url} -> {a}"


def test_no_dead_links_or_dead_anchors(client):
    tabs = {u: parse(client, u).tabs for u in PAGES}
    ids = {u: parse(client, u).ids for u in PAGES}
    for url in PAGES:
        for href in parse(client, url).links:
            assert not href.startswith("http"), f"external link {href} on {url}"
            assert href not in ("#", ""), f"empty link on {url}"
            path, _, frag = href.partition("#")
            path = path or url
            path = path.split("?")[0]
            assert path in PAGES, f"dead link {href} on {url}"
            if frag:
                assert frag in tabs[path] or frag in ids[path], f"dead anchor {href} on {url}"


def test_every_form_and_js_endpoint_is_a_real_route(app, client):
    rules = {(r.rule, m) for r in app.url_map.iter_rules() for m in r.methods}
    posts = {r for r, m in rules if m == "POST"}
    for url in PAGES:
        for ep in parse(client, url).forms:
            assert ep in posts, f"form on {url} posts to missing {ep}"
    found = set()
    for js in (STATIC / "js").glob("*.js"):
        for m in re.finditer(r'["\'`](/api/[a-z0-9\-/]+)["\'`]', js.read_text()):
            found.add((js.name, m.group(1)))
    assert found
    all_rules = {r for r, _ in rules}
    for name, ep in found:
        ok = ep in all_rules or any(r.startswith(ep.rstrip("/") + "/") or r.replace("<job_id>", "").startswith(ep) for r in all_rules)
        assert ok, f"{name} references unknown API {ep}"


def test_tool_tabs_have_panels(client):
    for url in ("/image-tools", "/pdf-tools", "/converter", "/ai-assistant"):
        html = client.get(url).get_data(as_text=True)
        for t in parse(client, url).tabs:
            assert f'data-panel="{t}"' in html, (url, t)


def test_homepage_content_requirements(client):
    html = client.get("/").get_data(as_text=True)
    for s in ("All Your Documents. One Simple Place.", "Scan, convert, compress and manage your documents with simple and powerful tools.",
              "Popular tools", "All tools", "How it works", 'id="privacy"', "Supported:", "Drag &amp; drop", "JPG, PNG, WebP, PDF"):
        assert s in html, s
    assert re.search(r"\d+\+?\s*(million|users)", html, re.I) is None  # no fake statistics
    assert "testimonial" not in html.lower()


def test_logo_fallback_and_real_logo(app, client):
    html = client.get("/").get_data(as_text=True)
    logo = STATIC / "images" / "dastavej-logo.png"
    if logo.exists():
        assert "dastavej-logo.png" in html
    else:
        assert 'class="wordmark"' in html and "dastavej-logo.png" not in html
    # Logo slot: template must reference the exact reserved path when the file exists
    logo.parent.mkdir(parents=True, exist_ok=True)
    existed = logo.exists()
    if not existed:
        logo.write_bytes(png_bytes(200, 60))
    try:
        html = client.get("/").get_data(as_text=True)
        assert html.count("images/dastavej-logo.png") >= 2  # navbar + footer
        assert 'alt="DASTAVEJ"' in html
    finally:
        if not existed:
            logo.unlink()


def test_brand_palette_in_css():
    css = (STATIC / "css" / "style.css").read_text().lower()
    for c in ("#00b86b", "#008f55", "#007a48", "#064e3b", "#080b09", "#f7fbf8", "#e5f5ec", "#ddf5e9", "#17211c", "#64736a", "#dde9e1", "#15803d", "#dc2626"):
        assert c in css, c
    assert "plus jakarta sans" in css and "inter" in css


def test_passport_presets_match_backend(client):
    from app.services.passport_service import PRESETS
    html = client.get("/passport-photo").get_data(as_text=True)
    for key in PRESETS:
        assert f'value="{key}"' in html, key


def test_homepage_upload_endpoint_and_preload(api):
    j = api.post("/api/jobs/upload", {"file": (io.BytesIO(png_bytes()), "photo.png")}).get_json()
    assert j["ok"] and j["file"]["file_kind"] == "png"
    jid = j["file"]["job_id"]
    g = api.get(f"/api/jobs/{jid}").get_json()
    assert g["job"]["meta"]["kind"] == "png"
    r = api.post("/api/image/resize", {"file_id": jid, "width": "40"})
    assert r.status_code == 200
    assert api.post("/api/jobs/upload", {"file": (io.BytesIO(b"MZ\x00\x01"), "x.exe")}).status_code == 415


def test_js_files_reference_existing_element_ids(client):
    """Cheap DOM contract check: every getElementById('x') in a page script exists in that page's HTML."""
    mapping = {"/scanner": "scanner.js", "/passport-photo": "passport.js", "/ai-assistant": "ai.js", "/resume-analyzer": "resume.js", "/": "index.js"}
    for url, js in mapping.items():
        html = client.get(url).get_data(as_text=True)
        src = (STATIC / "js" / js).read_text()
        used = set(re.findall(r'getElementById\("([\w-]+)"\)', src)) | set(re.findall(r'\$\("([\w-]+)"\)', src))
        dynamic = {"chat-empty"}  # created at runtime
        for i in used - dynamic:
            assert f'id="{i}"' in html, f"{js} uses #{i} which is missing in {url}"
    for url, js in (("/pdf-tools", "pdf.js"), ("/image-tools", "image.js")):
        html = client.get(url).get_data(as_text=True)
        src = (STATIC / "js" / js).read_text()
        for i in set(re.findall(r'getElementById\("([\w-]+)"\)', src)):
            assert f'id="{i}"' in html, f"{js} uses #{i} which is missing in {url}"
