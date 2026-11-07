/* DASTAVEJ shared front-end helpers (no external dependencies). */
(function () {
  "use strict";
  const DV = (window.DV = {});
  const meta = document.querySelector('meta[name="csrf-token"]');
  const CSRF = meta ? meta.content : "";

  DV.fmtBytes = function (n) {
    if (n == null || isNaN(n)) return "";
    if (n < 1024) return n + " B";
    if (n < 1048576) return (n / 1024).toFixed(n < 10240 ? 1 : 0) + " KB";
    return (n / 1048576).toFixed(2) + " MB";
  };
  DV.h = function (tag, attrs, ...kids) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === "class") e.className = v;
      else if (k === "text") e.textContent = v;
      else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2), v);
      else if (v !== false && v != null) e.setAttribute(k, v === true ? "" : v);
    }
    for (const k of kids.flat()) if (k != null) e.append(k.nodeType ? k : document.createTextNode(String(k)));
    return e;
  };
  DV.clear = (el) => { while (el.firstChild) el.removeChild(el.firstChild); };

  DV.request = async function (url, opts) {
    opts = opts || {};
    const init = { method: opts.method || "GET", credentials: "same-origin", headers: {} };
    if (init.method !== "GET") init.headers["X-CSRF-Token"] = CSRF;
    if (opts.body) init.body = opts.body;
    let res;
    try { res = await fetch(url, init); } catch (e) { throw new Error("Network error. Check your connection and try again."); }
    let data = null;
    try { data = await res.json(); } catch (e) { /* non-JSON */ }
    if (!res.ok || (data && data.ok === false)) {
      const msg = data && data.error && data.error.message ? data.error.message : "Request failed (" + res.status + ").";
      const err = new Error(msg);
      err.code = data && data.error && data.error.code;
      err.status = res.status;
      throw err;
    }
    return data;
  };
  DV.post = (url, fd) => DV.request(url, { method: "POST", body: fd });
  DV.get = (url) => DV.request(url);
  DV.del = (url) => DV.request(url, { method: "DELETE" });

  DV.notice = function (container, msg, kind) {
    const n = DV.h("div", { class: "note " + (kind || ""), role: kind === "err" ? "alert" : "status", text: msg });
    container.append(n);
    return n;
  };

  /* ---------- Dropzone ---------- */
  const KIND_EXT = { jpg: [".jpg", ".jpeg"], png: [".png"], webp: [".webp"], pdf: [".pdf"], docx: [".docx"], pptx: [".pptx"], xlsx: [".xlsx"], csv: [".csv"], txt: [".txt"] };
  DV.Dropzone = class {
    constructor(el, opts) {
      this.el = el;
      this.multiple = el.hasAttribute("data-multiple");
      this.accept = (el.dataset.accept || "").split(",").map((s) => s.trim().toLowerCase()).filter(Boolean);
      this.files = [];
      this.onChange = (opts && opts.onChange) || function () {};
      this.input = DV.h("input", { type: "file", hidden: true, accept: this.accept.join(","), multiple: this.multiple });
      this.list = DV.h("ul", { class: "dz-files" });
      const label = el.dataset.label || (this.multiple ? "Drop files here or click to browse" : "Drop a file here or click to browse");
      this.zone = DV.h("div", { class: "dz", tabindex: "0", role: "button", "aria-label": label },
        DV.h("div", { class: "dz-title", text: label }),
        DV.h("div", { class: "dz-sub", text: el.dataset.hint || ("Allowed: " + (this.accept.join(" ") || "any supported file")) }));
      el.append(this.zone, this.input, this.list);
      this.zone.addEventListener("click", () => this.input.click());
      this.zone.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); this.input.click(); } });
      this.input.addEventListener("change", () => { this.addFiles([...this.input.files]); this.input.value = ""; });
      ["dragenter", "dragover"].forEach((t) => this.zone.addEventListener(t, (e) => { e.preventDefault(); this.zone.classList.add("drag"); }));
      ["dragleave", "drop"].forEach((t) => this.zone.addEventListener(t, (e) => { e.preventDefault(); this.zone.classList.remove("drag"); }));
      this.zone.addEventListener("drop", (e) => this.addFiles([...(e.dataTransfer.files || [])]));
    }
    allows(name) {
      if (!this.accept.length) return true;
      const n = name.toLowerCase();
      return this.accept.some((a) => (a.startsWith(".") ? n.endsWith(a) : true));
    }
    acceptsKind(kind) {
      const exts = KIND_EXT[kind] || [];
      return !this.accept.length || exts.some((x) => this.accept.includes(x));
    }
    addFiles(files) {
      const rejected = [];
      for (const f of files) {
        if (!this.allows(f.name)) { rejected.push(f.name); continue; }
        if (!this.multiple) this.files = [];
        this.files.push(f);
      }
      if (rejected.length) this.flash("Not supported here: " + rejected.join(", "));
      this.render();
    }
    addServerFile(sf) { if (!this.multiple) this.files = []; this.files.push(sf); this.render(); }
    flash(msg) {
      const n = DV.h("div", { class: "note warn mt-2", role: "alert", text: msg });
      this.el.append(n);
      setTimeout(() => n.remove(), 4500);
    }
    remove(i) { this.files.splice(i, 1); this.render(); }
    clear() { this.files = []; this.render(); }
    render() {
      DV.clear(this.list);
      this.files.forEach((f, i) => {
        this.list.append(DV.h("li", {},
          DV.h("span", { class: "name", text: f.name }),
          DV.h("span", { class: "size", text: DV.fmtBytes(f.size) }),
          DV.h("button", { type: "button", "aria-label": "Remove " + f.name, text: "×", onclick: () => this.remove(i) })));
      });
      this.onChange(this.files);
    }
    appendTo(fd, field) {
      field = field || "file";
      for (const f of this.files) {
        if (f.serverId) fd.append(field + "_id", f.serverId);
        else fd.append(field, f, f.name);
      }
    }
    previewUrl(i) {
      const f = this.files[i || 0];
      if (!f) return null;
      return f.serverId ? "/api/jobs/" + f.serverId + "/download?inline=1" : URL.createObjectURL(f);
    }
  };

  DV.initDropzones = function (root) {
    const out = [];
    (root || document).querySelectorAll(".dz-host").forEach((el) => { if (!el._dz) { el._dz = new DV.Dropzone(el); } out.push(el._dz); });
    return out;
  };

  /* ---------- Tabs ---------- */
  DV.tabs = function (root, onShow) {
    const btns = [...root.querySelectorAll("[data-tab]")];
    const panels = [...root.querySelectorAll("[data-panel]")];
    function show(id, push) {
      const ok = panels.some((p) => p.dataset.panel === id);
      if (!ok) id = btns[0].dataset.tab;
      btns.forEach((b) => { const on = b.dataset.tab === id; b.classList.toggle("active", on); b.setAttribute("aria-selected", on); });
      panels.forEach((p) => p.classList.toggle("active", p.dataset.panel === id));
      if (push) history.replaceState(null, "", "#" + id);
      if (onShow) onShow(id);
    }
    btns.forEach((b) => b.addEventListener("click", () => !b.disabled && show(b.dataset.tab, true)));
    window.addEventListener("hashchange", () => show(location.hash.slice(1)));
    show(location.hash.slice(1) || btns[0].dataset.tab);
    return show;
  };

  /* ---------- Result rendering ---------- */
  const LABELS = { original_bytes: "Original size", output_bytes: "New size", target_bytes: "Target size", target_met: "Target met", output_size_px: "Output size (px)", original_size_px: "Original size (px)" };
  function label(k) { return LABELS[k] || k.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()); }
  function fmtVal(k, v) {
    if (typeof v === "boolean") return v ? "Yes" : "No";
    if (k.endsWith("_bytes") && typeof v === "number") return DV.fmtBytes(v);
    if (Array.isArray(v)) return v.map((x) => (typeof x === "object" ? JSON.stringify(x) : x)).join(", ") || "none";
    if (v && typeof v === "object") return Object.entries(v).map(([a, b]) => a + ": " + b).join(", ");
    return String(v);
  }
  DV.renderInfo = function (info) {
    const dl = DV.h("dl", { class: "kv" });
    for (const [k, v] of Object.entries(info || {})) {
      if (["warning", "note", "items", "face", "crop", "identity_note", "input"].includes(k) || v == null) continue;
      dl.append(DV.h("dt", { text: label(k) }), DV.h("dd", { text: fmtVal(k, v) }));
    }
    return dl;
  };
  DV.renderResult = function (container, data, ctx) {
    ctx = ctx || {};
    DV.clear(container);
    const r = data.result;
    const card = DV.h("div", { class: "result-card" });
    card.append(DV.h("div", { class: "ok-title", text: "✓ Done" }));
    const info = data.info || {};
    if (r && r.mime && r.mime.startsWith("image/")) {
      const fig = DV.h("div", { class: "compare" });
      const before = ctx.beforeUrl;
      if (before) fig.append(DV.h("figure", {}, DV.h("figcaption", { text: "Before" }), DV.h("img", { src: before, alt: "Original" })));
      fig.append(DV.h("figure", {}, DV.h("figcaption", { text: before ? "After" : "Result" }), DV.h("img", { src: r.preview_url + "&t=" + Date.now(), alt: "Result" })));
      card.append(fig);
    }
    card.append(DV.renderInfo(info));
    if (r) card.append(DV.h("div", { class: "kv" }, DV.h("dt", { text: "File" }), DV.h("dd", { text: r.name + " (" + DV.fmtBytes(r.size) + ")" })));
    const warns = [].concat(info.warning || [], data.warnings || []);
    warns.forEach((w) => card.append(DV.h("div", { class: "note warn my-2", text: w })));
    if (info.note) card.append(DV.h("div", { class: "note my-2", text: info.note }));
    if (info.identity_note) card.append(DV.h("div", { class: "note my-2", text: info.identity_note }));
    if (data.text) {
      card.append(DV.h("label", { class: "form-label mt-2", text: "Recognised text" }),
        DV.h("textarea", { class: "form-control", rows: "8", readonly: true }, data.text));
      card.lastChild.value = data.text;
      if (data.confidence != null) card.append(DV.h("div", { class: "form-text", text: "Average OCR confidence: " + data.confidence + "%" }));
    }
    if (r) {
      const row = DV.h("div", { class: "d-flex flex-wrap gap-2 mt-3" });
      row.append(DV.h("a", { class: "btn btn-primary", href: r.download_url, download: r.name, text: "Download" }));
      if (r.mime === "application/pdf") row.append(DV.h("a", { class: "btn btn-outline-primary", href: r.preview_url, target: "_blank", rel: "noopener", text: "Open preview" }));
      card.append(row);
    }
    container.append(card);
    return card;
  };

  /* ---------- Generic tool form runner ---------- */
  DV.initToolForm = function (form, hooks) {
    hooks = hooks || {};
    const dzEl = form.querySelector(".dz-host");
    const dz = dzEl ? (dzEl._dz || (dzEl._dz = new DV.Dropzone(dzEl))) : null;
    const out = form.querySelector(".result") || DV.h("div", { class: "result" });
    if (!out.parentNode) form.append(out);
    const run = form.querySelector(".btn-run");
    const reset = form.querySelector(".btn-reset");
    form._dz = dz;

    function toggles() {
      form.querySelectorAll("[data-show-if]").forEach((el) => {
        const [name, vals] = el.dataset.showIf.split("=");
        const ctl = form.querySelector('[name="' + name + '"]:checked') || form.querySelector('select[name="' + name + '"],input[name="' + name + '"]:not([type=radio])');
        const val = ctl ? (ctl.type === "checkbox" ? String(ctl.checked) : ctl.value) : "";
        el.hidden = !vals.split("|").includes(val);
      });
    }
    function ranges() { form.querySelectorAll('input[type="range"]').forEach((r) => { const o = r.nextElementSibling; if (o && o.tagName === "OUTPUT") o.textContent = r.value; }); }
    form.addEventListener("input", ranges); ranges();
    form.addEventListener("input", toggles); form.addEventListener("change", toggles); toggles();

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      DV.clear(out);
      if (dz && dz.files.length === 0 && !form.hasAttribute("data-optional-file")) {
        DV.notice(out, dz.multiple ? "Please choose at least one file first." : "Please choose a file first.", "err");
        return;
      }
      const fd = new FormData(form);
      form.querySelectorAll('input[type="checkbox"][name]').forEach((c) => fd.set(c.name, c.checked ? "true" : "false"));
      if (dz) dz.appendTo(fd, form.dataset.field || "file");
      if (hooks.beforeSend) { const stop = hooks.beforeSend(fd, form); if (stop) { DV.notice(out, stop, "err"); return; } }
      const label = run ? run.textContent : "";
      if (run) { run.disabled = true; run.replaceChildren(DV.h("span", { class: "spinner me-2", "aria-hidden": "true" }), "Processing…"); }
      out.append(DV.h("div", { class: "muted", role: "status", text: "Working on it…" }));
      try {
        const data = await DV.post(form.dataset.endpoint, fd);
        const before = dz && dz.files.length ? dz.previewUrl(0) : null;
        DV.renderResult(out, data, { beforeUrl: before });
        if (hooks.onResult) hooks.onResult(data, form);
      } catch (err) {
        DV.clear(out);
        DV.notice(out, err.message, "err");
      } finally {
        if (run) { run.disabled = false; run.textContent = label; }
      }
    });
    if (reset) reset.addEventListener("click", () => { form.reset(); if (dz) dz.clear(); DV.clear(out); toggles(); if (hooks.onReset) hooks.onReset(form); });
    return { dz, out };
  };

  /* Preload a file uploaded on the homepage (?file=<job id>) into every drop zone that accepts it. */
  DV.preload = async function () {
    const id = new URLSearchParams(location.search).get("file");
    if (!id || !/^[0-9a-f]{24}$/.test(id)) return null;
    try {
      const data = await DV.get("/api/jobs/" + id);
      const j = data.job;
      const sf = { serverId: j.job_id, name: j.name, size: j.size, kind: (j.meta && j.meta.kind) || "" };
      document.querySelectorAll(".dz-host").forEach((el) => {
        const dz = el._dz || (el._dz = new DV.Dropzone(el));
        if (dz.acceptsKind(sf.kind)) dz.addServerFile(sf);
      });
      return sf;
    } catch (e) { return null; }
  };

  /* ---------- Canvas helpers: rectangle cropper and quad editor ---------- */
  function fitOverlay(stage, overlay, img) {
    const r = img.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    overlay.style.width = r.width + "px"; overlay.style.height = r.height + "px";
    overlay.width = Math.round(r.width * dpr); overlay.height = Math.round(r.height * dpr);
    return { w: r.width, h: r.height, dpr };
  }
  function pointer(overlay, e) {
    const r = overlay.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top, w: r.width, h: r.height };
  }

  DV.CropBox = class {
    /* Rect in NATURAL image pixels. aspect = w/h or null. */
    constructor(stage, img, opts) {
      this.img = img; this.aspect = (opts && opts.aspect) || null; this.onChange = (opts && opts.onChange) || function () {};
      this.overlay = DV.h("canvas", { class: "overlay", "aria-label": "Crop area" });
      stage.append(this.overlay);
      this.rect = null; this.drag = null;
      this.overlay.addEventListener("pointerdown", (e) => this.down(e));
      this.overlay.addEventListener("pointermove", (e) => this.move(e));
      window.addEventListener("pointerup", () => { this.drag = null; });
      window.addEventListener("resize", () => this.draw());
      this.nat = { w: img.naturalWidth, h: img.naturalHeight };
      this.reset();
    }
    scale() { const r = this.img.getBoundingClientRect(); return r.width / this.nat.w; }
    reset() {
      const { w, h } = this.nat;
      if (this.aspect) {
        let rw = Math.min(w, h * this.aspect) * 0.8, rh = rw / this.aspect;
        this.rect = { x: (w - rw) / 2, y: (h - rh) / 2, w: rw, h: rh };
      } else this.rect = { x: w * 0.1, y: h * 0.1, w: w * 0.8, h: h * 0.8 };
      this.draw(); this.onChange(this.get());
    }
    setAspect(a) { this.aspect = a; this.reset(); }
    set(r) { this.rect = Object.assign({}, r); this.draw(); this.onChange(this.get()); }
    get() { const r = this.rect; return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.w), h: Math.round(r.h) }; }
    draw() {
      if (!this.rect) return;
      const o = this.overlay, { w, h, dpr } = fitOverlay(o.parentNode, o, this.img);
      const c = o.getContext("2d"); c.setTransform(dpr, 0, 0, dpr, 0, 0); c.clearRect(0, 0, w, h);
      const s = this.scale(), r = this.rect;
      c.fillStyle = "rgba(8,11,9,.45)"; c.fillRect(0, 0, w, h);
      c.clearRect(r.x * s, r.y * s, r.w * s, r.h * s);
      c.strokeStyle = "#00B86B"; c.lineWidth = 2; c.strokeRect(r.x * s, r.y * s, r.w * s, r.h * s);
      if (this.guides) this.guides(c, s, r);
      c.fillStyle = "#fff";
      for (const [hx, hy] of this.handles()) { c.beginPath(); c.arc(hx * s, hy * s, 6, 0, 7); c.fill(); c.stroke(); }
    }
    handles() { const r = this.rect; return [[r.x, r.y], [r.x + r.w, r.y], [r.x + r.w, r.y + r.h], [r.x, r.y + r.h]]; }
    down(e) {
      e.preventDefault(); this.overlay.setPointerCapture(e.pointerId);
      const p = pointer(this.overlay, e), s = this.scale(), r = this.rect;
      const hs = this.handles();
      for (let i = 0; i < 4; i++) if (Math.hypot(hs[i][0] * s - p.x, hs[i][1] * s - p.y) < 16) { this.drag = { type: "h", i }; return; }
      const nx = p.x / s, ny = p.y / s;
      if (nx > r.x && nx < r.x + r.w && ny > r.y && ny < r.y + r.h) this.drag = { type: "m", dx: nx - r.x, dy: ny - r.y };
      else if (!this.aspect) { this.drag = { type: "n", x0: nx, y0: ny }; this.rect = { x: nx, y: ny, w: 1, h: 1 }; }
    }
    move(e) {
      if (!this.drag) return;
      const p = pointer(this.overlay, e), s = this.scale(), { w: W, h: H } = this.nat;
      const nx = Math.max(0, Math.min(W, p.x / s)), ny = Math.max(0, Math.min(H, p.y / s)), r = this.rect, d = this.drag;
      if (d.type === "m") { r.x = Math.max(0, Math.min(W - r.w, nx - d.dx)); r.y = Math.max(0, Math.min(H - r.h, ny - d.dy)); }
      else if (d.type === "n") { r.x = Math.min(d.x0, nx); r.y = Math.min(d.y0, ny); r.w = Math.abs(nx - d.x0); r.h = Math.abs(ny - d.y0); }
      else {
        const hs = this.handles(), opp = hs[(d.i + 2) % 4];
        let nw = Math.abs(nx - opp[0]), nh = Math.abs(ny - opp[1]);
        if (this.aspect) { nh = nw / this.aspect; if (ny < opp[1] ? opp[1] - nh < 0 : opp[1] + nh > H) { nh = ny < opp[1] ? opp[1] : H - opp[1]; nw = nh * this.aspect; } }
        if (nw < 20) return;
        r.x = nx < opp[0] ? opp[0] - nw : opp[0]; r.y = ny < opp[1] ? opp[1] - nh : opp[1]; r.w = nw; r.h = nh;
      }
      this.draw(); this.onChange(this.get());
    }
  };

  DV.QuadEditor = class {
    /* Four corners in NORMALISED 0..1 coords: tl, tr, br, bl */
    constructor(stage, img, corners, onChange) {
      this.img = img; this.onChange = onChange || function () {};
      this.overlay = DV.h("canvas", { class: "overlay", "aria-label": "Document corners" });
      stage.append(this.overlay);
      this.pts = corners.map((p) => ({ x: p[0], y: p[1] })); this.sel = -1;
      this.overlay.addEventListener("pointerdown", (e) => this.down(e));
      this.overlay.addEventListener("pointermove", (e) => this.move(e));
      window.addEventListener("pointerup", () => { this.sel = -1; });
      window.addEventListener("resize", () => this.draw());
      this.draw();
    }
    get() { return this.pts.map((p) => [Number(p.x.toFixed(4)), Number(p.y.toFixed(4))]); }
    set(c) { this.pts = c.map((p) => ({ x: p[0], y: p[1] })); this.draw(); this.onChange(this.get()); }
    draw() {
      const o = this.overlay, { w, h, dpr } = fitOverlay(o.parentNode, o, this.img);
      const c = o.getContext("2d"); c.setTransform(dpr, 0, 0, dpr, 0, 0); c.clearRect(0, 0, w, h);
      c.beginPath(); this.pts.forEach((p, i) => (i ? c.lineTo(p.x * w, p.y * h) : c.moveTo(p.x * w, p.y * h))); c.closePath();
      c.fillStyle = "rgba(0,184,107,.18)"; c.fill(); c.strokeStyle = "#00B86B"; c.lineWidth = 2; c.stroke();
      c.fillStyle = "#fff";
      this.pts.forEach((p) => { c.beginPath(); c.arc(p.x * w, p.y * h, 9, 0, 7); c.fill(); c.stroke(); });
    }
    down(e) {
      e.preventDefault(); this.overlay.setPointerCapture(e.pointerId);
      const p = pointer(this.overlay, e); let best = -1, bd = 32;
      this.pts.forEach((q, i) => { const d = Math.hypot(q.x * p.w - p.x, q.y * p.h - p.y); if (d < bd) { bd = d; best = i; } });
      this.sel = best;
    }
    move(e) {
      if (this.sel < 0) return;
      const p = pointer(this.overlay, e);
      this.pts[this.sel] = { x: Math.max(0, Math.min(1, p.x / p.w)), y: Math.max(0, Math.min(1, p.y / p.h)) };
      this.draw(); this.onChange(this.get());
    }
  };

  DV.loadImage = function (stage, url) {
    return new Promise((resolve, reject) => {
      DV.clear(stage);
      const img = DV.h("img", { alt: "Preview", crossorigin: "anonymous" });
      img.onload = () => resolve(img); img.onerror = () => reject(new Error("The image could not be displayed."));
      img.src = url; stage.append(img);
    });
  };
  DV.uploadFile = async function (url, file, extra) {
    const fd = new FormData();
    if (file.serverId) fd.append("file_id", file.serverId); else fd.append("file", file, file.name);
    for (const [k, v] of Object.entries(extra || {})) fd.append(k, v);
    return DV.post(url, fd);
  };
})();
