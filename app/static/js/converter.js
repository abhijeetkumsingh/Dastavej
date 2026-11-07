(function () {
  "use strict";
  const show = DV.tabs(document.getElementById("tabs"));
  document.querySelectorAll("form.tool-form").forEach((f) => DV.initToolForm(f));
  DV.get("/api/convert/capabilities").then((d) => {
    d.conversions.forEach((c) => {
      const lim = document.querySelector('[data-limit="' + c.id + '"]');
      if (lim) lim.textContent = "Good to know: " + c.limitations;
      if (!c.available) {
        const btn = document.querySelector('[data-tab="' + c.id + '"]');
        if (btn) { btn.disabled = true; btn.title = "Not available on this server"; }
        const form = document.querySelector('[data-panel="' + c.id + '"] form');
        if (form) form.querySelectorAll("button.btn-run").forEach((b) => (b.disabled = true));
        const n = document.querySelector('[data-unavailable="' + c.id + '"]');
        if (n) { n.hidden = false; n.textContent = "Unavailable: this conversion needs LibreOffice, which isn't installed on this server."; }
      }
    });
  }).catch(() => {});
  DV.preload();
})();
