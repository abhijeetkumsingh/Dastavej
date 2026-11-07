(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const form = $("rs-form"), out = $("rs-out"), host = form.querySelector(".dz-host"), dz = new DV.Dropzone(host); host._dz = dz;
  form.elements.role.addEventListener("change", () => { $("rs-custom").hidden = form.elements.role.value !== "Custom"; });
  const H = DV.h;
  const chips = (arr, cls) => H("div", {}, ...(arr && arr.length ? arr.map((s) => H("span", { class: "chip " + (cls || ""), text: s })) : [H("span", { class: "muted small", text: "None" })]));
  const list = (arr) => H("ul", { class: "list-clean" }, ...arr.map((s) => H("li", { text: s })));
  const section = (title, ...kids) => H("div", { class: "panel mt-3" }, H("h3", { class: "h6 mb-2", text: title }), ...kids);

  function render(a) {
    DV.clear(out);
    const head = H("div", { class: "panel" },
      H("div", { class: "d-flex flex-wrap gap-3 align-items-center" },
        H("div", { class: "score-ring", style: "--p:" + a.score }, H("div", {}, H("b", { text: a.score }), H("span", { class: "small muted", text: "/ 100" }))),
        H("div", {}, H("div", { class: "badge-soft mb-1", text: "Estimated ATS compatibility" }), H("h2", { class: "h4 m-0", text: a.score_label }),
          H("div", { class: "muted small", text: "Target: " + a.role + " · scored against the " + a.score_basis }))),
      H("div", { class: "note warn mt-3 small", text: a.disclaimer }));
    if (a.report) head.append(H("a", { class: "btn btn-primary mt-3", href: a.report.download_url, download: a.report.name, text: "Download PDF report" }));
    out.append(head);
    (a.extraction_warnings || []).forEach((w) => out.append(H("div", { class: "note warn mt-3", text: w })));

    const bd = H("div");
    a.breakdown.forEach((b) => bd.append(H("div", { class: "mb-3" },
      H("div", { class: "d-flex justify-content-between" }, H("b", { text: b.name }), H("span", { text: b.score + " / " + b.max })),
      H("div", { class: "bar my-1" }, H("i", { style: "width:" + (b.score / b.max * 100) + "%" })),
      H("div", { class: "small muted", text: b.notes.join(" ") }))));
    out.append(section("How the score was calculated", bd));

    out.append(section("Skills", H("div", { class: "small fw-semibold" }, "Found"), chips(a.skills.found),
      H("div", { class: "small fw-semibold mt-2" }, "Missing core skills for this role"), chips(a.skills.missing_required, "miss"),
      a.skills.missing_optional.length ? H("div", {}, H("div", { class: "small fw-semibold mt-2" }, "Nice to have"), chips(a.skills.missing_optional, "miss")) : "",
      a.skills.listed_but_unevidenced.length ? H("div", { class: "note mt-2 small", text: "Listed but not backed by a project or job: " + a.skills.listed_but_unevidenced.join(", ") }) : ""));

    if (a.jd_match) out.append(section("Job description match",
      H("div", { text: "Keywords matched: " + a.jd_match.match_percent_keywords + "% · Skills matched: " + a.jd_match.match_percent_skills + "%" }),
      H("div", { class: "small fw-semibold mt-2" }, "Missing keywords"), chips(a.jd_match.missing_keywords.slice(0, 20), "miss")));

    if (a.suggestions.length) out.append(section("Top improvements", list(a.suggestions)));

    const e = a.experience, p = a.projects, ed = a.education, ac = a.achievements, g = a.grammar, f = a.formatting;
    out.append(section("Section analysis",
      H("div", { class: "small" },
        H("p", { class: "mb-1" }, H("b", { text: "Education: " }), ed.present ? (ed.degrees.join(", ") || "section found") + (ed.years.length ? " · " + ed.years.join(", ") : "") : "not found"),
        H("p", { class: "mb-1" }, H("b", { text: "Experience: " }), e.present ? e.entries + " dated entr" + (e.entries === 1 ? "y" : "ies") + (e.estimated_months ? " (about " + e.estimated_months + " month(s) in total, estimated)" : "") + (e.internship_mentioned ? " · internship mentioned" : "") : "not found"),
        H("p", { class: "mb-1" }, H("b", { text: "Projects: " }), p.present ? p.count + " found: " + p.projects.map((x) => x.title).join("; ") : "not found"),
        H("p", { class: "mb-1" }, H("b", { text: "Achievements: " }), ac.quantified + " of " + ac.bullets_total + " bullets include numbers"),
        H("p", { class: "mb-1" }, H("b", { text: "Readability: " }), g.flesch_reading_ease == null ? "n/a" : "Flesch reading ease " + g.flesch_reading_ease)),
      g.issues.length ? H("div", {}, H("div", { class: "small fw-semibold mt-2" }, "Wording checks"), list(g.issues), H("div", { class: "form-text", text: g.note })) : "",
      f.issues.length ? H("div", {}, H("div", { class: "small fw-semibold mt-2" }, "Formatting"), list(f.issues)) : ""));

    out.append(section("Recommended projects", list(a.recommendations.projects.length ? a.recommendations.projects : ["Build projects that use the missing skills above and link them in your resume."])));
    if (a.recommendations.courses.length) out.append(section("Courses & certifications", list(a.recommendations.courses.concat(a.recommendations.certifications)), H("div", { class: "form-text", text: a.recommendations.note })));
    const rm = H("div"); a.roadmap.forEach((ph) => rm.append(H("div", { class: "mb-2" }, H("b", { text: ph.phase }), list(ph.actions))));
    out.append(section("Career roadmap", rm));
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault(); DV.clear(out);
    if (!dz.files.length) { DV.notice(out, "Please add your resume first.", "err"); return; }
    const fd = new FormData(form); dz.appendTo(fd, "file");
    const run = $("rs-run"), label = run.textContent; run.disabled = true; run.replaceChildren(H("span", { class: "spinner me-2" }), "Analysing…");
    out.append(H("div", { class: "muted", role: "status", text: "Reading your resume…" }));
    try { render((await DV.post("/api/resume/analyze", fd)).analysis); }
    catch (err) { DV.clear(out); DV.notice(out, err.message, "err"); }
    finally { run.disabled = false; run.textContent = label; }
  });
  $("rs-reset").addEventListener("click", () => { form.reset(); dz.clear(); $("rs-custom").hidden = true; DV.clear(out); out.append(H("div", { class: "panel muted", text: "Your analysis will appear here." })); });
  DV.preload();
})();
