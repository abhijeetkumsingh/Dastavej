(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  DV.tabs(document.getElementById("tabs"));
  document.querySelectorAll("form.tool-form").forEach((f) => DV.initToolForm(f));

  const dzEl = $("ai-dz"), dz = new DV.Dropzone(dzEl); dzEl._dz = dz;
  const chat = $("chat"), status = $("ai-status");
  let hasDocs = false;

  function consent() { return $("ai-consent").checked; }
  function setBusy(b) { ["ask-btn", "do-summary", "do-analyze", "ai-upload"].forEach((id) => ($(id).disabled = b)); }
  function bubble(kind, node) { const e = $("chat-empty"); if (e) e.remove(); const m = DV.h("div", { class: "msg " + kind }); m.append(node); chat.append(m); chat.scrollTop = chat.scrollHeight; return m; }

  $("ai-upload").addEventListener("click", async () => {
    const box = $("ai-docs"); DV.clear(box);
    if (!dz.files.length) { DV.notice(box, "Choose at least one document.", "err"); return; }
    setBusy(true); box.append(DV.h("div", { class: "muted" }, DV.h("span", { class: "spinner me-2" }), "Reading and (if needed) running OCR… large scans can take a minute."));
    try {
      const fd = new FormData(); dz.appendTo(fd, "file"); fd.append("ocr_languages", $("ai-lang").value);
      const d = await DV.post("/api/ai/upload", fd);
      DV.clear(box);
      d.documents.forEach((doc) => {
        const c = DV.h("div", { class: "result-card mb-2" },
          DV.h("div", { class: "fw-semibold", text: doc.name }),
          DV.h("div", { class: "small muted", text: (doc.pages ? doc.pages + " page(s) · " : "") + doc.chunks + " sections · " + doc.characters.toLocaleString() + " characters" + (doc.ocr_pages.length ? " · OCR on page(s) " + doc.ocr_pages.join(", ") : "") }));
        doc.warnings.forEach((w) => c.append(DV.h("div", { class: "note warn mt-2 small", text: w })));
        box.append(c);
      });
      hasDocs = true; $("ai-delete").hidden = false; dz.clear();
    } catch (e) { DV.clear(box); DV.notice(box, e.message, "err"); }
    finally { setBusy(false); }
  });

  function render(d) {
    const wrap = DV.h("div");
    wrap.append(DV.h("div", {}, d.answer));
    const meta = DV.h("div", { class: "mt-2 d-flex flex-wrap gap-2 align-items-center" });
    if (d.confidence) meta.append(DV.h("span", { class: "conf " + d.confidence, text: "Confidence: " + d.confidence }));
    if (d.sent_to_gemini === false) meta.append(DV.h("span", { class: "badge-soft", text: "Nothing was sent to Gemini" }));
    wrap.append(meta);
    (d.warnings || []).forEach((w) => wrap.append(DV.h("div", { class: "note warn mt-2 small", text: w })));
    if (d.calculations && d.calculations.length) {
      const l = DV.h("div", { class: "src mt-2" }, DV.h("b", { text: "Checked with Python: " }));
      d.calculations.forEach((c) => l.append(DV.h("div", {}, c.expression + " = " + (c.verified == null ? "could not verify" : c.verified) + (c.status === "corrected" ? " (corrected)" : ""))));
      wrap.append(l);
    }
    if (d.sources && d.sources.length) {
      const det = DV.h("details", { class: "mt-2" }, DV.h("summary", { class: "small fw-semibold", text: "Sources (" + d.sources.length + ")" }));
      d.sources.forEach((s) => det.append(DV.h("div", { class: "src" + (s.used ? " used" : "") },
        DV.h("span", { class: "ref", text: "[" + s.ref + "] " }), DV.h("b", { text: s.doc }), " · " + s.label + (s.page ? " (page " + s.page + ")" : ""),
        DV.h("div", { class: "muted mt-1", text: s.excerpt }))));
      wrap.append(det);
    }
    if (d.disclosure) wrap.append(DV.h("div", { class: "small muted mt-2", text: d.disclosure }));
    return wrap;
  }

  async function call(url, label, extra) {
    status.textContent = "";
    if (!hasDocs) { DV.clear(status); DV.notice(status, "Add and read a document first.", "err"); return; }
    if (!consent()) { DV.clear(status); DV.notice(status, "Please tick the box to agree to send excerpts to Gemini.", "err"); return; }
    bubble("user", document.createTextNode(label));
    const thinking = bubble("bot", DV.h("span", {}, DV.h("span", { class: "spinner me-2" }), "Thinking…")); setBusy(true);
    try {
      const fd = new FormData(); fd.append("gemini_consent", "true"); for (const [k, v] of Object.entries(extra || {})) fd.append(k, v);
      const d = await DV.post(url, fd); thinking.replaceChildren(render(d));
    } catch (e) { thinking.replaceChildren(DV.h("div", { class: "note err", text: e.message })); }
    finally { setBusy(false); chat.scrollTop = chat.scrollHeight; }
  }
  $("ask-form").addEventListener("submit", (e) => { e.preventDefault(); const q = $("ask-q").value.trim(); if (!q) return; $("ask-q").value = ""; call("/api/ai/ask", q, { question: q }); });
  $("do-summary").addEventListener("click", () => call("/api/ai/summary", "Summarise the document", { length: "medium" }));
  $("do-analyze").addEventListener("click", () => call("/api/ai/analyze", "Analyse the document"));
  $("ai-delete").addEventListener("click", async () => {
    try { await DV.del("/api/ai/session"); } catch (e) { /* ignore */ }
    hasDocs = false; DV.clear($("ai-docs")); DV.clear(chat); chat.append(DV.h("div", { class: "muted small", id: "chat-empty", text: "Session deleted. Add a document to start again." })); $("ai-delete").hidden = true;
  });
  DV.preload().then((sf) => { if (sf) { const n = DV.notice($("ai-docs"), "Your file is ready: press “Read documents”.", ""); } });
})();
