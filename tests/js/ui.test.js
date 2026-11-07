// Runs the real front-end JS in jsdom against a live DASTAVEJ test server.
const { JSDOM, VirtualConsole, CookieJar } = require("jsdom");
const fs = require("fs"), path = require("path"), assert = require("assert");
const BASE = process.env.BASE || "http://127.0.0.1:5057";
const FIX = path.join(__dirname, "fixtures");
const results = []; const bufs = new Map(); const bkey = (f) => f.name + ":" + f.size;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitFor(fn, what, ms = 25000) {
  const t = Date.now();
  while (Date.now() - t < ms) { try { const v = fn(); if (v) return v; } catch (e) { /* retry */ } await sleep(60); }
  throw new Error("timed out waiting for: " + what);
}

async function openPage(url) {
  const jar = openPage.jar || (openPage.jar = new CookieJar());
  const errors = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push(String(e.stack || e)));
  vc.on("error", (...a) => errors.push(a.join(" ")));
  const dom = await JSDOM.fromURL(BASE + url, {
    runScripts: "dangerously", resources: "usable", pretendToBeVisual: true, cookieJar: jar, virtualConsole: vc,
    beforeParse(w) {
      const rect = { width: 400, height: 300, left: 0, top: 0, right: 400, bottom: 300, x: 0, y: 0 };
      w.Element.prototype.getBoundingClientRect = () => rect;
      const noop = new Proxy(function () {}, { get: (_, k) => (k === "canvas" ? {} : noop), apply: () => noop, set: () => true });
      w.HTMLCanvasElement.prototype.getContext = () => noop;
      w.HTMLCanvasElement.prototype.setPointerCapture = () => {};
      w.HTMLCanvasElement.prototype.toDataURL = () => "data:image/png;base64,iVBORw0KGgo=";
      Object.defineProperty(w.HTMLImageElement.prototype, "naturalWidth", { get() { return 800; } });
      Object.defineProperty(w.HTMLImageElement.prototype, "naturalHeight", { get() { return 600; } });
      Object.defineProperty(w.HTMLImageElement.prototype, "src", {
        set(v) { this.setAttribute("src", v); setTimeout(() => this.onload && this.onload(), 5); }, get() { return this.getAttribute("src"); } });
      w.URL.createObjectURL = () => "blob:test";
      w.scrollTo = () => {};
      w.fetch = async (u, init = {}) => {
        const url = new URL(u, BASE).href;
        const headers = Object.assign({}, init.headers || {}, { cookie: jar.getCookieStringSync(url) });
        let body = init.body;
        if (body && typeof body.entries === "function") {
          const nf = new FormData();
          for (const [k, v] of body.entries()) {
            if (typeof v === "string") nf.append(k, v);
            else nf.append(k, new Blob([bufs.get(bkey(v)) || Buffer.alloc(0)]), v.name);
          }
          body = nf;
        }
        const res = await fetch(url, { method: init.method || "GET", headers, body });
        for (const c of res.headers.getSetCookie ? res.headers.getSetCookie() : []) jar.setCookieSync(c, url);
        return res;
      };
    },
  });
  await waitFor(() => dom.window.document.readyState === "complete" && dom.window.DV, "page load " + url);
  await sleep(120);
  return { dom, w: dom.window, d: dom.window.document, errors };
}
function file(w, name, type) { const buf = fs.readFileSync(path.join(FIX, name)); const f = new w.File([buf], name, { type }); bufs.set(bkey(f), buf); return f; }
function panel(d, id) { return d.querySelector('[data-panel="' + id + '"]'); }
function setVal(form, name, v) { const el = form.querySelector('[name="' + name + '"]'); el.value = v; el.dispatchEvent(new form.ownerDocument.defaultView.Event("input", { bubbles: true })); }
function submit(w, form) { form.dispatchEvent(new w.Event("submit", { cancelable: true, bubbles: true })); }
async function result(form) { return waitFor(() => form.querySelector(".result .result-card, .result .note.err"), "result in form"); }

async function test(name, fn) {
  if (process.env.ONLY && !name.includes(process.env.ONLY)) return;
  try { await fn(); results.push([name, true]); console.log("  ✓", name); }
  catch (e) { results.push([name, false, e]); console.log("  ✗", name, "\n     ", (e.message || e).toString().split("\n")[0]); }
}

(async () => {
  const pages = ["/", "/image-tools", "/pdf-tools", "/scanner", "/passport-photo", "/converter", "/ai-assistant", "/resume-analyzer"];
  for (const p of pages) await test("loads without JS errors: " + p, async () => {
    const { w, errors } = await openPage(p); assert.deepStrictEqual(errors, []); w.close();
  });

  for (const p of ["/image-tools", "/pdf-tools", "/converter", "/ai-assistant"]) await test("tabs switch panels: " + p, async () => {
    const { w, d, errors } = await openPage(p);
    for (const b of d.querySelectorAll("[data-tab]")) {
      if (b.disabled) continue; b.click();
      assert.ok(panel(d, b.dataset.tab).classList.contains("active"), "panel " + b.dataset.tab);
      assert.strictEqual(d.querySelectorAll(".tool-panel.active").length, 1);
    }
    assert.deepStrictEqual(errors, []); w.close();
  });

  await test("image: resize flow end to end", async () => {
    const { w, d } = await openPage("/image-tools#resize"); const form = panel(d, "resize").querySelector("form");
    form._dz.addFiles([file(w, "photo.png", "image/png")]); setVal(form, "width", "200");
    submit(w, form); await result(form);
    const card = form.querySelector(".result-card"); assert.ok(card, form.querySelector(".result").textContent);
    assert.ok(card.querySelector("a.btn-primary[href*='/api/jobs/']"), "download link");
    assert.ok(/200\s*,\s*150/.test(card.textContent), card.textContent); assert.strictEqual(card.querySelectorAll(".compare figure").length, 2); w.close();
  });
  await test("image: compress to target size reports measured result", async () => {
    const { w, d } = await openPage("/image-tools#compress"); const form = panel(d, "compress").querySelector("form");
    form._dz.addFiles([file(w, "photo.png", "image/png")]); setVal(form, "target_size", "5"); setVal(form, "target_unit", "KB");
    submit(w, form); await result(form);
    const t = form.querySelector(".result-card").textContent; assert.ok(/Target met\s*Yes/.test(t), t); w.close();
  });
  await test("image: empty submit shows friendly error; wrong type is rejected client-side", async () => {
    const { w, d } = await openPage("/image-tools#resize"); const form = panel(d, "resize").querySelector("form");
    submit(w, form); const e = await result(form); assert.ok(/choose/i.test(e.textContent));
    form._dz.addFiles([file(w, "a.pdf", "application/pdf")]); assert.strictEqual(form._dz.files.length, 0);
    assert.ok(d.querySelector(".note.warn").textContent.includes("a.pdf")); w.close();
  });
  await test("image: server error surfaces in UI", async () => {
    const { w, d } = await openPage("/image-tools#resize"); const form = panel(d, "resize").querySelector("form");
    form._dz.addFiles([file(w, "photo.png", "image/png")]); submit(w, form); const e = await result(form);
    assert.ok(e.classList.contains("err") && /width|height/i.test(e.textContent), e.textContent); w.close();
  });
  await test("image: crop tab builds a crop box and fills fields", async () => {
    const { w, d } = await openPage("/image-tools#crop"); const form = d.getElementById("crop-form");
    form._dz.addFiles([file(w, "photo.png", "image/png")]);
    await waitFor(() => !d.getElementById("crop-stage").hidden && d.querySelector("#crop-stage canvas.overlay"), "crop overlay");
    assert.ok(+form.querySelector('[name="width"]').value > 0); w.close();
  });

  await test("pdf: merge two files", async () => {
    const { w, d } = await openPage("/pdf-tools#merge"); const form = panel(d, "merge").querySelector("form");
    form._dz.addFiles([file(w, "a.pdf", "application/pdf"), file(w, "b.pdf", "application/pdf")]); submit(w, form); await result(form);
    const card = form.querySelector(".result-card"); assert.ok(card, form.querySelector(".result").textContent); assert.ok(/Pages\s*5/.test(card.textContent), card.textContent); w.close();
  });
  await test("pdf: protect then wrong-password unlock shows error", async () => {
    const { w, d } = await openPage("/pdf-tools#protect"); const pf = panel(d, "protect").querySelector("form");
    pf._dz.addFiles([file(w, "a.pdf", "application/pdf")]); setVal(pf, "password", "pw12345"); submit(w, pf); await result(pf);
    const link = pf.querySelector("a.btn-primary").getAttribute("href"); assert.ok(link);
    const jid = link.split("/")[3];
    const uf = panel(d, "unlock").querySelector("form"); uf._dz.addServerFile({ serverId: jid, name: "p.pdf", size: 1, kind: "pdf" }); setVal(uf, "password", "wrong");
    submit(w, uf); const e = await result(uf); assert.ok(/password/i.test(e.textContent), e.textContent);
    setVal(uf, "password", "pw12345"); submit(w, uf); await waitFor(() => uf.querySelector(".result-card"), "unlock ok"); w.close();
  });
  await test("pdf: organise shows thumbnails, selection and rotate action", async () => {
    const { w, d } = await openPage("/pdf-tools#organize");
    d.getElementById("org-dz")._dz.addFiles([file(w, "b.pdf", "application/pdf")]);
    await waitFor(() => d.querySelectorAll("#org-thumbs .thumb").length === 3, "3 thumbs");
    d.querySelector('#org-thumbs .thumb[data-page="2"]').click(); assert.ok(d.querySelector(".thumb.sel"));
    d.querySelector('[data-act="rotate"]').click(); await waitFor(() => d.querySelector("#org-result .result-card"), "rotate result");
    d.querySelector('[data-act="apply"]').click(); await waitFor(() => /Pages\s*3/.test(d.getElementById("org-result").textContent), "apply order"); w.close();
  });
  await test("pdf: to-text result", async () => {
    const { w, d } = await openPage("/pdf-tools#to-text"); const form = panel(d, "to-text").querySelector("form");
    form._dz.addFiles([file(w, "a.pdf", "application/pdf")]); submit(w, form); await result(form);
    assert.ok(form.querySelector(".result-card"), form.querySelector(".result").textContent); w.close();
  });

  await test("converter: capabilities enable tabs; docx -> pdf works", async () => {
    const { w, d } = await openPage("/converter#docx-to-pdf");
    await waitFor(() => /Good to know/.test(d.querySelector('[data-limit="docx-to-pdf"]').textContent), "capabilities");
    assert.ok(!d.querySelector('[data-tab="docx-to-pdf"]').disabled);
    const form = panel(d, "docx-to-pdf").querySelector("form");
    form._dz.addFiles([file(w, "doc.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")]); submit(w, form); await result(form);
    assert.ok(form.querySelector(".result-card a[href*='download']"), form.querySelector(".result").textContent); w.close();
  });
  await test("converter: image-to-pdf custom size toggles fields", async () => {
    const { w, d } = await openPage("/converter#image-to-pdf"); const form = panel(d, "image-to-pdf").querySelector("form");
    const cw = form.querySelector('[name="width_mm"]').closest("[data-show-if]"); assert.ok(cw.hidden);
    setVal(form, "page_size", "custom"); assert.ok(!cw.hidden);
    form._dz.addFiles([file(w, "photo.png", "image/png")]); submit(w, form); await result(form); assert.ok(form.querySelector(".result-card")); w.close();
  });

  await test("ai: upload, consent gate, answer with sources + verified calculation, delete", async () => {
    const { w, d } = await openPage("/ai-assistant");
    d.getElementById("ai-dz")._dz.addFiles([file(w, "invoice.pdf", "application/pdf")]);
    d.getElementById("ai-upload").click(); await waitFor(() => d.querySelector("#ai-docs .result-card"), "doc card");
    d.getElementById("ask-q").value = "What is the total?"; submit(w, d.getElementById("ask-form"));
    await waitFor(() => /agree/i.test(d.getElementById("ai-status").textContent), "consent warning");
    assert.strictEqual(d.querySelectorAll(".msg.bot").length, 0, "nothing asked without consent");
    d.getElementById("ai-consent").checked = true; d.getElementById("ask-q").value = "What is the total?"; submit(w, d.getElementById("ask-form"));
    await waitFor(() => d.querySelector(".msg.bot .conf"), "answer");
    const t = d.querySelector(".msg.bot").textContent; assert.ok(/1550/.test(t) && /Sources/.test(t) && /Checked with Python/.test(t) && /sent to Google Gemini/.test(t), t);
    d.getElementById("do-summary").click(); await waitFor(() => d.querySelectorAll(".msg.bot .conf").length === 2, "summary");
    d.getElementById("ai-delete").click(); await waitFor(() => /Session deleted/.test(d.getElementById("chat").textContent), "deleted"); w.close();
  });
  await test("ai: OCR tab is wired", async () => {
    const { w, d } = await openPage("/ai-assistant#ocr"); const form = panel(d, "ocr").querySelector("form");
    form._dz.addFiles([file(w, "face.png", "image/png")]); submit(w, form); await result(form); assert.ok(form.querySelector(".result-card") || form.querySelector(".err")); w.close();
  });

  await test("resume: analyse renders score, breakdown, report link", async () => {
    const { w, d } = await openPage("/resume-analyzer"); const form = d.getElementById("rs-form");
    form.querySelector(".dz-host")._dz.addFiles([file(w, "resume.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")]);
    form.elements.role.value = "Python Developer"; submit(w, form);
    await waitFor(() => d.querySelector("#rs-out .score-ring"), "score ring");
    const t = d.getElementById("rs-out").textContent; assert.ok(/Estimated ATS compatibility/.test(t) && /Keyword match/.test(t) && /not the score of any employer/.test(t), t.slice(0, 300));
    assert.ok(d.querySelector("#rs-out a[href*='download']")); w.close();
  });
  await test("resume: custom role without JD shows error", async () => {
    const { w, d } = await openPage("/resume-analyzer"); const form = d.getElementById("rs-form");
    form.querySelector(".dz-host")._dz.addFiles([file(w, "resume.docx", "x/y")]); form.elements.role.value = "Custom"; form.elements.role.dispatchEvent(new w.Event("change"));
    assert.ok(!d.getElementById("rs-custom").hidden); submit(w, form); await waitFor(() => d.querySelector("#rs-out .note.err"), "error"); w.close();
  });

  await test("home: upload suggests tools, tool page preloads the file", async () => {
    const { w, d } = await openPage("/"); d.getElementById("home-dz")._dz.addFiles([file(w, "photo.png", "image/png")]);
    const link = await waitFor(() => d.querySelector("#home-suggest a[href*='?file=']"), "suggestions");
    const hrefs = [...d.querySelectorAll("#home-suggest a")].map((a) => a.getAttribute("href")); assert.ok(hrefs.some((h) => h.startsWith("/image-tools?file=") && h.endsWith("#compress")), hrefs.join(","));
    const target = link.getAttribute("href").split("#")[0]; w.close();
    const p2 = await openPage(target + "#compress"); await waitFor(() => p2.d.querySelector('[data-panel="compress"] .dz-files li'), "preloaded file");
    assert.ok(!p2.d.querySelector('[data-panel="compress"] form')._dz.files[0].size === false); p2.w.close();
  });

  await test("scanner: quick mode adds pages, reorder + export to PDF", async () => {
    const { w, d } = await openPage("/scanner"); d.getElementById("quick").checked = true;
    const dz = d.getElementById("scan-dz")._dz;
    dz.addFiles([file(w, "scan.jpg", "image/jpeg")]); await waitFor(() => d.querySelectorAll("#page-list .thumb").length === 1, "page 1");
    dz.addFiles([file(w, "scan.jpg", "image/jpeg")]); await waitFor(() => d.querySelectorAll("#page-list .thumb").length === 2, "page 2");
    assert.ok(!d.getElementById("export-box").hidden);
    d.querySelectorAll("#page-list .thumb")[0].querySelectorAll("button")[1].click(); // move page 1 later
    d.querySelectorAll("#page-list .thumb .x")[1].click(); assert.strictEqual(d.querySelectorAll("#page-list .thumb").length, 1);
    d.getElementById("export").click(); await waitFor(() => d.querySelector("#export-result .result-card"), "export result"); w.close();
  });
  await test("scanner: guided flow (corners -> scan -> enhance -> add page)", async () => {
    const { w, d } = await openPage("/scanner"); d.getElementById("scan-dz")._dz.addFiles([file(w, "scan.jpg", "image/jpeg")]);
    await waitFor(() => !d.getElementById("step-corners").hidden && d.querySelector("#corner-stage canvas.overlay"), "corner editor");
    d.getElementById("do-scan").click(); await waitFor(() => !d.getElementById("step-enhance").hidden && d.getElementById("view-img").getAttribute("src"), "enhance step");
    d.getElementById("f-mode").value = "bw"; d.getElementById("f-mode").dispatchEvent(new w.Event("input")); await sleep(900);
    d.getElementById("add-page").click(); await waitFor(() => d.querySelectorAll("#page-list .thumb").length === 1 && !d.getElementById("step-source").hidden, "page added"); w.close();
  });

  await test("passport: detect face, create photo, build print sheet", async () => {
    const { w, d } = await openPage("/passport-photo"); const dz = d.querySelector(".dz-host")._dz;
    dz.addFiles([file(w, "face.png", "image/png")]);
    await waitFor(() => !d.getElementById("pp-stage").hidden && d.querySelector("#pp-stage canvas.overlay"), "stage");
    submit(w, d.getElementById("pp-form")); await waitFor(() => d.querySelector("#pp-result .result-card"), "passport result");
    assert.ok(/413\s*,\s*531/.test(d.getElementById("pp-result").textContent), d.getElementById("pp-result").textContent);
    assert.ok(!d.getElementById("sheet-form").hidden);
    submit(w, d.getElementById("sheet-form")); await waitFor(() => d.querySelector("#sheet-result .result-card"), "sheet result");
    assert.ok(/Copies\s*8/.test(d.getElementById("sheet-result").textContent), d.getElementById("sheet-result").textContent); w.close();
  });

  const failed = results.filter((r) => !r[1]);
  console.log(`\nUI tests: ${results.length - failed.length} passed, ${failed.length} failed`);
  failed.forEach(([n, , e]) => console.log("FAIL:", n, "\n", e && e.stack ? e.stack.split("\n").slice(0, 4).join("\n") : e));
  process.exit(failed.length ? 1 : 0);
})();
