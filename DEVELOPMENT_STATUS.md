# DASTAVEJ - Development Status

Last verified: 2026-11-06 (Linux sandbox, Python 3.12, LibreOffice + Tesseract eng/hin installed).

## Test results (real runs)
| Suite | Result |
|---|---|
| `pytest tests` (Flask test client, real generated files) | **110 passed, 0 failed** |
| - core 5, image 14, passport 8, scanner 4, PDF 10, converter 12, AI 18, resume 9, security 19, pages 11 | |
| `node tests/js/ui.test.js` (the real front-end JS run in jsdom against a live server) | **31 passed, 0 failed** |
| Gunicorn production start + `/health` + security headers | manual smoke test OK |

No test was disabled or weakened to pass. Real bugs found and fixed while building: OOXML (xlsx) validation rejected valid files; custom PDF page sizes were rotated by "auto" orientation; `form.role` on the Resume page was shadowed by the browser's ARIA `role` property (found only by running the JS); OpenCV 5 removed the face-detection API (pinned to 4.x).

## Module status
| Module | Status | Notes |
|---|---|---|
| Foundation: app factory, blueprints, SQLite job records, file manager, cleanup, security headers, CSRF, rate limiting | Done, tested | |
| Homepage + 7 tool pages | Done, tested (HTML crawl + jsdom) | Not reviewed in a real browser |
| Image tools (resize, compress-to-target, convert, crop, rotate, enhance, batch ZIP) | Done, tested | Target size verified on the real output file |
| Document scanner | Done, tested | Edge detection tested on a synthetic skewed page only |
| PDF Studio (merge, split, compress, rotate, reorder, delete, extract, duplicate, watermark, page numbers, drawn signature, text, AES-256 protect, unlock, to images/text, previews) | Done, tested | |
| File converter (10 conversions) | Done, tested with real LibreOffice | Unavailable conversions are disabled in the UI automatically |
| Passport photo studio | Done, tested | Face pixels proven identical when background changes |
| OCR Hindi + English | Done, tested | Synthetic rendered text only |
| AI Document Assistant (RAG + Gemini) | Done, tested with a **mocked** Gemini | **Never run against the live Gemini API** (no key available) |
| Resume analyzer | Done, tested | Rule-based; no Gemini used |
| Docker / Gunicorn / docs | Written | **Docker image not built here** (no Docker in sandbox) |

## Known limitations
1. **Logo:** `app/static/images/dastavej-logo.png` was NOT present in the workspace, so it could not be inspected. Templates use that exact path automatically once the file exists; until then a plain text wordmark shows. The app never recreates the logo.
2. **Gemini live path untested.** Prompting, parsing, consent gating, failure handling and Python calculation checking are tested with a fake model; real model behaviour (JSON compliance, citation quality) is unverified.
3. **Browser behaviour untested:** dragging crop/corner handles, the signature pad, camera capture and visual styling were not exercised in a real browser (jsdom has no layout or real canvas).
4. **Passport background change** uses GrabCut: best on plain backgrounds; hair edges may need touch-up. It refuses to run without a detected face. Face detection is the classic Haar detector (front-facing photos only).
5. **Hindi OCR** accuracy on real scans/handwriting is unknown. Uses the Tesseract "fast" Hindi model in `./tessdata`.
6. **Watermark, page numbers and PDF text annotations are Latin-only** (built-in PDF fonts); Devanagari there is rejected with a clear message.
7. **DOCX has no real pages**, so AI sources for DOCX are labelled by section.
8. **Office to PDF fidelity** depends on fonts installed on the server.
9. **Resume score** is an estimate from open rules, not any employer's ATS. Grammar checks are heuristics. Course/certificate names are suggestions; verify availability.
10. **Limits:** per-request timeout is enforced by Gunicorn (180 s); LibreOffice also has its own timeout plus CPU, file-size and address-space limits. In-process work (OpenCV, PyMuPDF) is not individually memory-capped; use container memory limits in production.
11. **Rate limiting** is in-memory per worker by default; use `RATELIMIT_STORAGE_URI` (Redis) with several workers.
12. Session isolation relies on a signed cookie; anyone holding the cookie can access that session's files until they expire.
13. The Windows setup script and `docker compose` were not run here.

## Next steps
1. Put the official logo at `app/static/images/dastavej-logo.png` and check navbar/footer proportions.
2. Add `GEMINI_API_KEY` to `.env`; run a live check (upload PDF, ask, verify citations and the calculation check).
3. Click through every tool in a real browser on desktop and phone (camera needs HTTPS or localhost).
4. `docker compose up --build`; confirm `/health` reports LibreOffice and Hindi OCR.
5. Try real documents (scanned Hindi page, multi-column resume, large PDF) and report failures.
