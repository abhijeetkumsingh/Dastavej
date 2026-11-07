(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const S = { source: null, corners: null, base: null, view: null, rot: 0, pages: [] };
  const dzEl = $("scan-dz"), dz = new DV.Dropzone(dzEl); dzEl._dz = dz;
  let quad = null, cropBox = null, stream = null, timer = null;

  function show(name) {
    $("step-corners").hidden = name !== "corners";
    $("step-enhance").hidden = name !== "enhance";
    $("step-source").hidden = name !== "source";
  }
  function busy(el, msg) { DV.clear(el); if (msg) el.append(DV.h("div", { class: "muted", role: "status" }, DV.h("span", { class: "spinner me-2" }), msg)); }

  /* ----- camera ----- */
  async function startCam() {
    DV.clear($("source-msg"));
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { DV.notice($("source-msg"), "Camera is not available in this browser or connection. Use HTTPS/localhost, or upload a photo instead.", "warn"); return; }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 } }, audio: false });
      $("cam-video").srcObject = stream; await $("cam-video").play(); $("cam-box").hidden = false;
    } catch (e) {
      DV.notice($("source-msg"), e && e.name === "NotAllowedError" ? "Camera permission was denied. Allow it in your browser, or upload a photo." : "Could not start the camera. Upload a photo instead.", "warn");
    }
  }
  function stopCam() { if (stream) stream.getTracks().forEach((t) => t.stop()); stream = null; $("cam-box").hidden = true; }
  $("cam-start").addEventListener("click", startCam);
  $("cam-stop").addEventListener("click", stopCam);
  $("cam-snap").addEventListener("click", () => {
    const v = $("cam-video"); if (!v.videoWidth) return;
    const c = document.createElement("canvas"); c.width = v.videoWidth; c.height = v.videoHeight; c.getContext("2d").drawImage(v, 0, 0);
    c.toBlob((b) => { stopCam(); handle(new File([b], "capture.jpg", { type: "image/jpeg" })); }, "image/jpeg", 0.92);
  });
  window.addEventListener("pagehide", stopCam);

  /* ----- flow ----- */
  dz.onChange = (files) => { if (files.length) { const f = files[0]; dz.clear(); handle(f); } };

  async function handle(file) {
    const msg = $("source-msg"); busy(msg, "Reading your photo…");
    try {
      if ($("quick").checked) {
        const d = await DV.uploadFile("/api/scanner/add-page", file, { auto_scan: "true", mode: "enhanced" });
        addPage(d.result); DV.clear(msg);
        if (!d.edges_found) DV.notice(msg, "Page edges weren't found, so the full image was used. Turn off quick mode to adjust corners manually.", "warn");
        return;
      }
      const d = await DV.uploadFile("/api/scanner/upload", file);
      S.source = d.result; S.corners = d.corners; DV.clear(msg);
      show("corners");
      $("corner-help").textContent = d.edges_found ? "We found the document edges. Drag the dots to fine-tune." : "Edges weren't found automatically. Drag the four dots to the document corners.";
      const stage = $("corner-stage"); DV.clear(stage);
      const img = await DV.loadImage(stage, d.result.preview_url);
      quad = new DV.QuadEditor(stage, img, d.corners);
    } catch (e) { DV.clear(msg); DV.notice(msg, e.message, "err"); }
  }
  async function runScan(corners) {
    const msg = $("corner-msg"); busy(msg, "Straightening the page…");
    try {
      const fd = new FormData(); fd.append("file_id", S.source.job_id); fd.append("corners", JSON.stringify(corners));
      const d = await DV.post("/api/scanner/process", fd);
      S.base = d.result; S.rot = 0; resetControls(); DV.clear(msg); show("enhance"); await refreshView();
    } catch (e) { DV.clear(msg); DV.notice(msg, e.message, "err"); }
  }
  $("do-scan").addEventListener("click", () => runScan(quad.get()));
  $("skip-scan").addEventListener("click", () => runScan([[0, 0], [1, 0], [1, 1], [0, 1]]));
  $("cancel-scan").addEventListener("click", () => { show("source"); quad = null; });

  function resetControls() { $("f-mode").value = "enhanced"; $("f-bri").value = 0; $("f-con").value = 1; leaveCrop(); }
  async function refreshView() {
    const msg = $("view-msg"); busy(msg, "Applying filter…");
    try {
      const fd = new FormData(); fd.append("file_id", S.base.job_id); fd.append("mode", $("f-mode").value);
      fd.append("brightness", $("f-bri").value); fd.append("contrast", $("f-con").value); fd.append("rotate", S.rot);
      const d = await DV.post("/api/scanner/filter", fd); S.view = d.result;
      const img = $("view-img"); img.hidden = false; img.src = d.result.preview_url + "&t=" + Date.now(); DV.clear(msg);
    } catch (e) { DV.clear(msg); DV.notice(msg, e.message, "err"); }
  }
  function later() { clearTimeout(timer); timer = setTimeout(refreshView, 350); }
  ["f-mode", "f-bri", "f-con"].forEach((id) => $(id).addEventListener("input", later));
  $("rot-l").addEventListener("click", () => { S.rot = (S.rot + 270) % 360; refreshView(); });
  $("rot-r").addEventListener("click", () => { S.rot = (S.rot + 90) % 360; refreshView(); });

  function leaveCrop() { cropBox = null; $("crop-bar").hidden = true; const st = $("view-stage"); st.querySelectorAll("canvas.overlay").forEach((c) => c.remove()); }
  $("crop-toggle").addEventListener("click", () => {
    if (cropBox) { leaveCrop(); return; }
    const img = $("view-img"); if (!img.naturalWidth) return;
    cropBox = new DV.CropBox($("view-stage"), img, {}); $("crop-bar").hidden = false;
  });
  $("crop-apply").addEventListener("click", async () => {
    if (!cropBox) return; const r = cropBox.get(), img = $("view-img"), W = img.naturalWidth, H = img.naturalHeight;
    const msg = $("view-msg"); busy(msg, "Cropping…");
    try {
      const fd = new FormData(); fd.append("file_id", S.view.job_id);
      fd.append("x", r.x / W); fd.append("y", r.y / H); fd.append("width", r.w / W); fd.append("height", r.h / H);
      const d = await DV.post("/api/scanner/crop", fd); S.base = d.result; S.rot = 0; resetControls(); $("f-mode").value = "original"; await refreshView();
    } catch (e) { DV.clear(msg); DV.notice(msg, e.message, "err"); }
  });
  $("add-page").addEventListener("click", () => { if (!S.view) return; addPage(S.view); leaveCrop(); S.source = S.base = S.view = null; $("view-img").hidden = true; show("source"); });

  /* ----- page list ----- */
  function addPage(job) { S.pages.push({ id: job.job_id, url: job.preview_url }); renderPages(); }
  function renderPages() {
    const list = $("page-list"); DV.clear(list);
    S.pages.forEach((p, i) => {
      const t = DV.h("div", { class: "thumb", style: "cursor:default" },
        DV.h("a", { href: p.url, target: "_blank", rel: "noopener" }, DV.h("img", { src: p.url, alt: "Page " + (i + 1) })),
        DV.h("div", { class: "n" }, "Page " + (i + 1)),
        DV.h("div", { class: "d-flex justify-content-center gap-1 mt-1" },
          DV.h("button", { class: "btn btn-light btn-sm py-0 px-2", type: "button", "aria-label": "Move page " + (i + 1) + " earlier", disabled: i === 0, onclick: () => { move(i, -1); }, text: "◀" }),
          DV.h("button", { class: "btn btn-light btn-sm py-0 px-2", type: "button", "aria-label": "Move page " + (i + 1) + " later", disabled: i === S.pages.length - 1, onclick: () => { move(i, 1); }, text: "▶" })),
        DV.h("button", { class: "x", type: "button", "aria-label": "Delete page " + (i + 1), onclick: () => { S.pages.splice(i, 1); renderPages(); }, text: "×" }));
      list.append(t);
    });
    $("page-count").textContent = S.pages.length + (S.pages.length === 1 ? " page" : " pages");
    $("empty-note").hidden = S.pages.length > 0; $("export-box").hidden = S.pages.length === 0;
  }
  function move(i, d) { const j = i + d; [S.pages[i], S.pages[j]] = [S.pages[j], S.pages[i]]; renderPages(); }
  $("export").addEventListener("click", async () => {
    const out = $("export-result"); busy(out, "Building your PDF…");
    try {
      const fd = new FormData(); fd.append("pages", JSON.stringify(S.pages.map((p) => p.id))); fd.append("page_size", $("ex-size").value); fd.append("name", $("ex-name").value || "scan");
      DV.renderResult(out, await DV.post("/api/scanner/export", fd));
    } catch (e) { DV.clear(out); DV.notice(out, e.message, "err"); }
  });
  $("new-doc").addEventListener("click", () => { S.pages = []; renderPages(); DV.clear($("export-result")); show("source"); });
  renderPages();
  DV.preload().then((sf) => { /* a file carried from the homepage drop zone */ });
})();
