(function () {
  "use strict";
  DV.tabs(document.getElementById("tabs"));
  document.querySelectorAll("form.tool-form").forEach((f) => DV.initToolForm(f));

  async function pdfInfo(file) {
    const fd = new FormData();
    if (file.serverId) fd.append("file_id", file.serverId); else fd.append("file", file, file.name);
    return (await DV.post("/api/pdf/info", fd)).input;
  }

  /* ---------------- Organise pages ---------------- */
  (function organise() {
    const dz = new DV.Dropzone(document.getElementById("org-dz")); document.getElementById("org-dz")._dz = dz;
    const box = document.getElementById("org-thumbs"), actions = document.getElementById("org-actions"), out = document.getElementById("org-result");
    let jid = null, dragEl = null;
    dz.onChange = async (files) => {
      DV.clear(box); DV.clear(out); actions.hidden = true; jid = null;
      if (!files.length) return;
      box.append(DV.h("div", { class: "muted" }, DV.h("span", { class: "spinner me-2" }), "Reading pages…"));
      try {
        const info = await pdfInfo(files[0]);
        DV.clear(box);
        if (!info.pages) throw new Error("This PDF is password-protected. Unlock it first.");
        jid = info.job_id;
        for (let i = 1; i <= info.pages; i++) {
          const t = DV.h("div", { class: "thumb", draggable: "true", "data-page": i, tabindex: "0", role: "button", "aria-pressed": "false", "aria-label": "Page " + i },
            DV.h("img", { src: "/api/pdf/preview/" + jid + "/" + i + "?dpi=50", alt: "Page " + i, loading: "lazy" }),
            DV.h("div", { class: "n", text: "Page " + i }));
          const toggle = () => { t.classList.toggle("sel"); t.setAttribute("aria-pressed", t.classList.contains("sel")); };
          t.addEventListener("click", toggle);
          t.addEventListener("keydown", (e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); toggle(); } });
          t.addEventListener("dragstart", () => { dragEl = t; });
          t.addEventListener("dragover", (e) => { e.preventDefault(); t.classList.add("drag-over"); });
          t.addEventListener("dragleave", () => t.classList.remove("drag-over"));
          t.addEventListener("drop", (e) => {
            e.preventDefault(); t.classList.remove("drag-over");
            if (!dragEl || dragEl === t) return;
            const kids = [...box.children];
            box.insertBefore(dragEl, kids.indexOf(dragEl) < kids.indexOf(t) ? t.nextSibling : t);
          });
          box.append(t);
        }
        actions.hidden = false;
      } catch (e) { DV.clear(box); DV.notice(box, e.message, "err"); }
    };
    const sel = () => [...box.querySelectorAll(".thumb.sel")].map((t) => +t.dataset.page).sort((a, b) => a - b);
    const order = () => [...box.children].map((t) => +t.dataset.page);
    actions.addEventListener("click", async (e) => {
      const act = e.target.dataset.act; if (!act || !jid) return;
      if (act === "all") { box.querySelectorAll(".thumb").forEach((t) => { t.classList.add("sel"); t.setAttribute("aria-pressed", "true"); }); return; }
      const fd = new FormData(); fd.append("file_id", jid);
      let url;
      if (act === "apply") { url = "/api/pdf/reorder"; fd.append("order", JSON.stringify(order())); }
      else {
        const s = sel(); if (!s.length) { DV.clear(out); DV.notice(out, "Select at least one page first.", "err"); return; }
        fd.append("pages", s.join(","));
        url = { rotate: "/api/pdf/rotate", delete: "/api/pdf/delete-pages", extract: "/api/pdf/extract-pages", duplicate: "/api/pdf/duplicate-pages" }[act];
        if (act === "rotate") fd.append("angle", "90");
      }
      DV.clear(out); out.append(DV.h("div", { class: "muted", text: "Working on it…" }));
      try { DV.renderResult(out, await DV.post(url, fd)); } catch (err) { DV.clear(out); DV.notice(out, err.message, "err"); }
    });
  })();

  /* ---------------- Sign & annotate ---------------- */
  (function sign() {
    const dzEl = document.getElementById("sign-dz"), dz = new DV.Dropzone(dzEl); dzEl._dz = dz;
    const ui = document.getElementById("sign-ui"), stage = document.getElementById("sign-stage"), out = document.getElementById("sign-result");
    const pageSel = document.getElementById("sign-page"), itemsEl = document.getElementById("sign-items");
    const pad = document.getElementById("sigpad"), ctx = pad.getContext("2d");
    let jid = null, img = null, overlay = null, drawn = false;
    const placements = [], notes = [];

    // signature pad
    ctx.lineWidth = 6; ctx.lineCap = "round"; ctx.lineJoin = "round"; ctx.strokeStyle = "#0b2a6f";
    let drawing = false;
    const pos = (e) => { const r = pad.getBoundingClientRect(); return [(e.clientX - r.left) * pad.width / r.width, (e.clientY - r.top) * pad.height / r.height]; };
    pad.addEventListener("pointerdown", (e) => { drawing = true; pad.setPointerCapture(e.pointerId); const [x, y] = pos(e); ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + .1, y + .1); ctx.stroke(); drawn = true; });
    pad.addEventListener("pointermove", (e) => { if (!drawing) return; const [x, y] = pos(e); ctx.lineTo(x, y); ctx.stroke(); });
    window.addEventListener("pointerup", () => { drawing = false; });
    document.getElementById("sig-clear").addEventListener("click", () => { ctx.clearRect(0, 0, pad.width, pad.height); drawn = false; });

    function renderItems() {
      DV.clear(itemsEl);
      placements.forEach((p, i) => itemsEl.append(DV.h("li", {}, "Signature on page " + p.page + " ", DV.h("a", { href: "#", onclick: (e) => { e.preventDefault(); placements.splice(i, 1); renderItems(); }, text: "remove" }))));
      notes.forEach((p, i) => itemsEl.append(DV.h("li", {}, "“" + p.text + "” on page " + p.page + " ", DV.h("a", { href: "#", onclick: (e) => { e.preventDefault(); notes.splice(i, 1); renderItems(); }, text: "remove" }))));
      drawMarkers();
    }
    function drawMarkers() {
      if (!overlay || !img) return;
      const r = img.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
      overlay.style.width = r.width + "px"; overlay.style.height = r.height + "px"; overlay.width = r.width * dpr; overlay.height = r.height * dpr;
      const c = overlay.getContext("2d"); c.setTransform(dpr, 0, 0, dpr, 0, 0); c.clearRect(0, 0, r.width, r.height);
      const cur = +pageSel.value, w = +document.getElementById("sig-w").value / 100;
      c.lineWidth = 2; c.strokeStyle = "#00B86B"; c.fillStyle = "rgba(0,184,107,.15)"; c.font = "12px Inter, sans-serif";
      placements.filter((p) => p.page === cur).forEach((p) => { c.fillRect(p.x * r.width, p.y * r.height, p.w * r.width, p.w * r.width * 0.35); c.strokeRect(p.x * r.width, p.y * r.height, p.w * r.width, p.w * r.width * 0.35); });
      c.fillStyle = "#064E3B"; notes.filter((p) => p.page === cur).forEach((p) => c.fillText(p.text, p.x * r.width, p.y * r.height + 12));
    }
    async function showPage() {
      DV.clear(stage); overlay = null;
      img = await DV.loadImage(stage, "/api/pdf/preview/" + jid + "/" + pageSel.value + "?dpi=90");
      overlay = DV.h("canvas", { class: "overlay", "aria-label": "Page. Click to place." }); stage.append(overlay);
      overlay.addEventListener("click", (e) => {
        const r = overlay.getBoundingClientRect(), x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height, page = +pageSel.value;
        DV.clear(out);
        if (document.getElementById("mode-text").checked) {
          const t = document.getElementById("sig-txt").value.trim();
          if (!t) { DV.notice(out, "Type the text first.", "err"); return; }
          notes.push({ page, x: +x.toFixed(4), y: +y.toFixed(4), text: t, size: 12, color: "#000000" });
        } else {
          if (!drawn) { DV.notice(out, "Draw your signature first.", "err"); return; }
          placements.push({ page, x: +x.toFixed(4), y: +y.toFixed(4), w: +document.getElementById("sig-w").value / 100 });
        }
        renderItems();
      });
      drawMarkers();
    }
    pageSel.addEventListener("change", showPage);
    document.getElementById("sig-w").addEventListener("input", drawMarkers);
    window.addEventListener("resize", drawMarkers);
    dz.onChange = async (files) => {
      DV.clear(out); ui.hidden = true; placements.length = 0; notes.length = 0; renderItems();
      if (!files.length) return;
      try {
        const info = await pdfInfo(files[0]);
        if (!info.pages) throw new Error("This PDF is password-protected. Unlock it first.");
        jid = info.job_id; DV.clear(pageSel);
        for (let i = 1; i <= info.pages; i++) pageSel.append(DV.h("option", { value: i, text: "Page " + i }));
        ui.hidden = false; await showPage();
      } catch (e) { DV.notice(out, e.message, "err"); }
    };
    document.getElementById("sign-apply").addEventListener("click", async () => {
      DV.clear(out);
      if (!placements.length && !notes.length) { DV.notice(out, "Click on the page to place a signature or text first.", "err"); return; }
      const fd = new FormData(); fd.append("file_id", jid);
      if (placements.length) fd.append("signature", pad.toDataURL("image/png"));
      fd.append("placements", JSON.stringify(placements)); fd.append("annotations", JSON.stringify(notes));
      out.append(DV.h("div", { class: "muted", text: "Working on it…" }));
      try {
        const data = await DV.post("/api/pdf/sign", fd);
        DV.renderResult(out, data);
        out.firstChild.append(DV.h("div", { class: "note my-2", text: "Reminder: this is a drawn (visual) signature, not a cryptographic digital signature." }));
      } catch (e) { DV.clear(out); DV.notice(out, e.message, "err"); }
    });
  })();

  DV.preload();
})();
