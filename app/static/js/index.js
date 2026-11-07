(function () {
  "use strict";
  const host = document.getElementById("home-dz");
  const out = document.getElementById("home-suggest");
  const dz = new DV.Dropzone(host);
  host._dz = dz;
  const SUGGEST = {
    image: [["Compress to target size", "/image-tools#compress"], ["Resize", "/image-tools#resize"], ["Convert format", "/image-tools#convert"],
      ["Make a passport photo", "/passport-photo"], ["Image to PDF", "/converter#image-to-pdf"], ["Read text (OCR)", "/ai-assistant#ocr"]],
    pdf: [["Compress PDF", "/pdf-tools#compress"], ["Split PDF", "/pdf-tools#split"], ["Organise pages", "/pdf-tools#organize"], ["Sign / annotate", "/pdf-tools#sign"],
      ["PDF to images", "/pdf-tools#to-images"], ["PDF to Word", "/converter#pdf-to-docx"], ["Ask questions (AI)", "/ai-assistant"]],
    docx: [["Convert to PDF", "/converter#docx-to-pdf"], ["Extract text", "/converter#docx-to-txt"], ["Ask questions (AI)", "/ai-assistant"]],
    pptx: [["Convert to PDF", "/converter#pptx-to-pdf"], ["Ask questions (AI)", "/ai-assistant"]],
    xlsx: [["Convert to PDF", "/converter#xlsx-to-pdf"], ["Convert to CSV", "/converter#xlsx-to-csv"], ["Ask questions (AI)", "/ai-assistant"]],
    csv: [["Convert to Excel", "/converter#csv-to-xlsx"], ["Ask questions (AI)", "/ai-assistant"]],
    txt: [["Ask questions (AI)", "/ai-assistant"]],
  };
  dz.onChange = async function (files) {
    DV.clear(out);
    if (!files.length) return;
    const f = files[0];
    out.append(DV.h("div", { class: "muted", role: "status" }, DV.h("span", { class: "spinner me-2" }), "Checking your file…"));
    try {
      const data = await DV.uploadFile("/api/jobs/upload", f);
      const kind = data.file.file_kind;
      const group = ["jpg", "png", "webp"].includes(kind) ? "image" : kind;
      DV.clear(out);
      out.append(DV.h("div", { class: "fw-semibold mb-2", text: "What would you like to do with " + data.file.name + "?" }));
      const row = DV.h("div", { class: "d-flex flex-wrap gap-2" });
      (SUGGEST[group] || []).forEach(([t, href]) => row.append(DV.h("a", { class: "btn btn-outline-primary btn-sm", href: href.replace(/(#.*)?$/, (h) => "?file=" + data.file.job_id + (h || "")), text: t })));
      out.append(row);
    } catch (e) {
      DV.clear(out);
      DV.notice(out, e.message, "err");
    }
  };
})();
