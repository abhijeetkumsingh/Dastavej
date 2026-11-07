(function () {
  "use strict";
  DV.tabs(document.getElementById("tabs"));
  document.querySelectorAll("form.tool-form").forEach((f) => DV.initToolForm(f));

  // quick-angle buttons
  document.querySelectorAll("[data-angle]").forEach((b) => b.addEventListener("click", () => { b.closest("form").querySelector('[name="angle"]').value = b.dataset.angle; }));

  // visual crop
  const form = document.getElementById("crop-form"), stage = document.getElementById("crop-stage"), help = document.getElementById("crop-help");
  const f = (n) => form.querySelector('[name="' + n + '"]');
  let box = null;
  async function showCrop(files) {
    box = null; DV.clear(stage); stage.hidden = true; help.hidden = true;
    if (!files.length) return;
    stage.hidden = false;
    try {
      const img = await DV.loadImage(stage, form._dz.previewUrl(0));
      help.hidden = false;
      box = new DV.CropBox(stage, img, { onChange: (r) => { f("x").value = r.x; f("y").value = r.y; f("width").value = r.w; f("height").value = r.h; } });
    } catch (e) { stage.hidden = true; }
  }
  form._dz.onChange = showCrop;
  ["x", "y", "width", "height"].forEach((n) => f(n).addEventListener("change", () => {
    if (box) box.set({ x: +f("x").value, y: +f("y").value, w: +f("width").value, h: +f("height").value });
  }));
  DV.preload();
})();
