(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const SIZES = { "india-passport": [35, 45], "uk-eu": [35, 45], us: [50.8, 50.8], "china-visa": [33, 48], "pan-card": [25, 35], stamp: [20, 25] };
  const host = document.querySelector(".dz-host"), dz = new DV.Dropzone(host); host._dz = dz;
  const form = $("pp-form"), stage = $("pp-stage"), msg = $("pp-msg"), out = $("pp-result");
  let box = null, face = null, inputId = null, passportJpgId = null;

  function aspect() {
    const p = form.elements.preset.value;
    if (p !== "custom") return SIZES[p][0] / SIZES[p][1];
    const w = +form.elements.width.value, h = +form.elements.height.value;
    return w > 0 && h > 0 ? w / h : 35 / 45;
  }
  function fields() { $("pp-custom").hidden = form.elements.preset.value !== "custom"; $("pp-bgc").hidden = form.elements.background.value !== "custom"; }
  form.addEventListener("change", (e) => {
    fields();
    if (box && ["preset", "width", "height"].includes(e.target.name)) box.setAspect(aspect());
  });
  form.addEventListener("input", () => form.querySelectorAll('input[type="range"]').forEach((r) => { const o = r.nextElementSibling; if (o && o.tagName === "OUTPUT") o.textContent = r.value; }));
  fields();

  function dimsFields() { const fd = new FormData(); fd.append("preset", form.elements.preset.value); if (form.elements.preset.value === "custom") { fd.append("width", form.elements.width.value); fd.append("height", form.elements.height.value); fd.append("unit", form.elements.unit.value); } return fd; }

  dz.onChange = async (files) => {
    box = null; face = null; inputId = null; DV.clear(msg); DV.clear(out); DV.clear(stage); stage.hidden = true; $("pp-help").hidden = true; $("sheet-form").hidden = true;
    if (!files.length) return;
    msg.append(DV.h("div", { class: "muted", role: "status" }, DV.h("span", { class: "spinner me-2" }), "Looking for the face…"));
    try {
      const fd = dimsFields(); fd.append("detect_only", "true");
      const f = files[0]; if (f.serverId) fd.append("file_id", f.serverId); else fd.append("file", f, f.name);
      const d = await DV.post("/api/image/passport", fd);
      inputId = d.input.job_id; face = d.face; DV.clear(msg);
      stage.hidden = false;
      const img = await DV.loadImage(stage, "/api/jobs/" + inputId + "/download?inline=1");
      $("pp-help").hidden = false;
      box = new DV.CropBox(stage, img, { aspect: aspect() });
      box.guides = (c, s) => {
        if (!face) return;
        c.save(); c.setLineDash([6, 4]); c.strokeStyle = "#f59e0b"; c.lineWidth = 2; c.strokeRect(face.x * s, face.y * s, face.w * s, face.h * s); c.restore();
      };
      // start from the detected crop
      const dc = d.default_crop; box.set({ x: Math.max(0, dc.x), y: Math.max(0, dc.y), w: Math.min(dc.w, img.naturalWidth), h: Math.min(dc.h, img.naturalHeight) });
      if (!d.detected) DV.notice(msg, "No face was detected. Position the box by hand. Changing the background is disabled without a detected face.", "warn");
    } catch (e) { DV.clear(msg); DV.notice(msg, e.message, "err"); }
  };

  form.addEventListener("submit", async (e) => {
    e.preventDefault(); DV.clear(out);
    if (!inputId || !box) { DV.notice(out, "Please upload a photo first.", "err"); return; }
    const fd = new FormData(form); fd.set("file_id", inputId);
    const r = box.get(); fd.set("crop_x", r.x); fd.set("crop_y", r.y); fd.set("crop_w", r.w);
    if (form.elements.background.value !== "custom") fd.delete("bg_color");
    const run = $("pp-run"), label = run.textContent; run.disabled = true; run.replaceChildren(DV.h("span", { class: "spinner me-2" }), "Processing…");
    try {
      const d = await DV.post("/api/image/passport", fd);
      const jpg = d.result.mime === "image/jpeg" ? d.result : d.jpg; passportJpgId = jpg.job_id;
      const card = DV.renderResult(out, d, { beforeUrl: "/api/jobs/" + inputId + "/download?inline=1" });
      if (d.jpg) card.append(DV.h("a", { class: "btn btn-outline-primary mt-2", href: d.jpg.download_url, download: d.jpg.name, text: "Also download JPG" }));
      if (!d.info.face_detected) card.prepend(DV.h("div", { class: "note warn my-2", text: "No face was detected, so this is a centred crop. Check the framing before printing." }));
      $("sheet-form").hidden = false;
    } catch (err) { DV.notice(out, err.message, "err"); }
    finally { run.disabled = false; run.textContent = label; }
  });

  $("sheet-form").addEventListener("submit", async (e) => {
    e.preventDefault(); const o = $("sheet-result"); DV.clear(o);
    if (!passportJpgId) { DV.notice(o, "Create a passport photo first.", "err"); return; }
    const fd = new FormData($("sheet-form")); fd.set("guides", $("sh-g").checked ? "true" : "false"); fd.set("file_id", passportJpgId);
    try {
      const d = await DV.post("/api/image/print-sheet", fd);
      DV.renderResult(o, d);
    } catch (err) { DV.notice(o, err.message, "err"); }
  });
  $("pp-reset").addEventListener("click", () => { form.reset(); fields(); dz.clear(); DV.clear(out); $("sheet-form").hidden = true; passportJpgId = null; });
  DV.preload();
})();
