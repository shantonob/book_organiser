# Backlog — Book Organiser

Feature/fix requests recorded for planning. Each item is a short spec so a
fresh chat can pick it up without re-discovering the codebase.

Format per item:
- **ID**, **Title**, **Priority**, **Status** (open / planned / in progress / done)
- **Symptom**: what the user actually observes
- **Where**: file:line anchors
- **Notes**: suspected cause, constraints, acceptance criteria

---

## BL-001 — Reader zoom: scrollbar does not update (can't reach bottom of page)

- **Priority:** High
- **Status:** done
- **Reported:** 2026-08-11
- **Fixed:** 2026-08-12

### Symptom

When zooming in (or out) in the PDF / comic book reader, the page content is
resized but the scrollbar range of the scroll container does not update.
After zooming in, the page cannot be scrolled all the way to the bottom —
content past the visible bottom edge is unreachable. Zoom is triggered by the
toolbar `+/−/reset` buttons and by Ctrl/Shift+wheel.

### Where

All in `templates/index.html`:

- Toolbar controls: `readerZoomGroup` (line ~686), `readerZoomIn/Out/Reset`
  (lines ~3656–3667).
- `_applyReaderZoom()` (line ~3674) — resizes the canvas via inline
  `el.style.width/height` from `_readerPageW/_readerPageH * z`.
- `_onReaderPageLoaded()` (line ~3694) — computes `_readerFitScale`.
- Scroll container: `#readerArea` has `overflow-y:auto` (line ~714).
- CSS: `.pdf-canvas-wrap { position: relative; margin: 0 auto 8px auto; }`
  and `.pdf-canvas-wrap canvas { display: block; width: 100%; height: auto; }`
  (lines ~288–289); `.comic-canvas-wrap` (lines ~293–294).
- `setupReaderWheelZoom()` (line ~3738) — Ctrl/Shift+wheel zoom path.
- PDF render: `_renderPdfPage()` builds `wrap.pdf-canvas-wrap > canvas`
  (lines ~3280–3294).

### Notes / suspected cause

- Inline `width/height` on the canvas may conflict with the CSS
  `width:100%; height:auto` rule; the wrapper's layout height (and therefore
  `#readerArea`'s `scrollHeight`) may not grow with the canvas, leaving stale
  scroll metrics. CSS `width:100%` (not `max-width`) on the canvas is the
  prime suspect — it may clamp the rendered element size even after inline
  styles are set, and the browser may not recompute the scrollbar range.
- After zoom, no code forces a scrollbar/metrics refresh
  (e.g. no `scrollHeight` read, no reflow, no `overflow` toggle).
- The overlay `_syncDrawOverlay()` runs after resize but positions the draw
  canvas, not the scroll container.
- EPUB zoom uses `readerRendition.themes.fontSize(...)` and is unaffected;
  this bug is for PDF/comic only.

### Acceptance criteria

1. Zoom in on a multi-page PDF: the scrollbar grows and the last page's
   bottom edge is reachable.
2. Zoom out: scrollbar shrinks accordingly; current view stays sensible.
3. Ctrl/Shift+wheel zoom behaves the same as the toolbar buttons.
4. No regression in drawing overlay alignment or page-fit zoom.
5. Works in scroll mode and page-fit mode.

### Fix attempted (2026-08-12) — STILL OPEN

- Added `_refreshReaderScroll()`: toggles the scroll container's `overflow-y`
  and reads `scrollHeight` to force the browser to recompute scroll metrics
  after a canvas resize; preserves scroll position.
- `_applyReaderZoom()` now calls `_refreshReaderScroll()` after resizing.
- `loadComicReader()` set `#readerArea.style.overflowY = "hidden"`, which
  removed the scrollbar entirely for zoomed comics — changed to `"auto"`.

**Reported still broken 2026-08-13.** Reopened.

### Re-analysis (2026-08-13)

- PDF reader uses a **nested scroll container**: `#pdfViewer`
  (`.pdf-viewer { height:100%; overflow-y:auto }`) inside `#readerArea`, and
  `loadPdfReader()` forces `#readerArea.style.overflowY = "hidden"`.
  Zooming grows the canvas inside `#pdfViewer`, and only an overflow-style
  toggle tries to fix the (reliably flaky) scrollbar recompute.
- Comic reader correctly uses `#readerArea` itself as the single scroller
  (`overflow-y:auto`, canvas flows in the area). That works.
- **Fix:** unify on `#readerArea` as the one scroll container. Drop the
  `overflow-y:hidden` override in `loadPdfReader()`, make `.pdf-viewer` flow
  (`height:auto; overflow:visible`), and make `_refreshReaderScroll()` operate
  on `#readerArea` instead of `#pdfViewer`.

### Fix applied (2026-08-13) — pending deploy/verify

- `.pdf-viewer` now flows: `width:100%; height:auto; overflow:visible`.
- `loadPdfReader()` sets `#readerArea.style.overflowY = "auto"` (single
  scroll container for both PDF and comic).
- `_refreshReaderScroll()` operates on `#readerArea` and preserves scroll
  top. `_applyReaderZoom()` calls it after every resize.
- `_onReaderScroll()` (BL-002) also shows sub-page progress while zoomed.

### Acceptance criteria (unchanged)

1. Zoom in on a multi-page PDF: the scrollbar grows and the last page's
   bottom edge is reachable.
2. Zoom out: scrollbar shrinks accordingly; current view stays sensible.
3. Ctrl/Shift+wheel zoom behaves the same as the toolbar buttons.
4. No regression in drawing overlay alignment or page-fit zoom.
5. Works in scroll mode and page-fit mode.

---

## BL-002 — Reader progress bar shows full/meaningless value (always "completely blue")

- **Priority:** High
- **Status:** implemented + deployed 2026-08-13 — awaiting user verification
- **Reported:** 2026-08-13

### Symptom

The blue reading progress bar in the reader toolbar (`#readerProgressFill`)
does not represent the actual reading position — it is effectively always
full/blue and does not move as you page or scroll through a PDF/comic.

### Where

`templates/index.html`:

- Toolbar bar: `.reader-progress-wrap` / `.reader-progress-fill` (lines ~228,
  699–700).
- `pdfRenderPage()` line ~3381 sets width to `pageNum / numPages * 100`.
- `showComicPage()` line ~3575 sets width to `(idx+1)/len*100`.
- `saveReaderState()` line ~2920 and `_trackEpubProgress()` line ~2967 also
  poke the same element directly.
- No code updates the bar from the scrolled view position.

### Notes / desired behaviour

- Bar should reflect **where the view currently is**: the fraction of the
  whole book = (current page + intra-page scroll fraction) / total, updated
  live on scroll, zoom, and page change.
- When the whole page fits (no scrolling possible), in-page fraction is 1.
- Clamp to 0–100 and always write a valid CSS width (guard NaN).
- Keep `.rl-item.active .rl-progress-fill` (reading list) in sync.

### Acceptance criteria

1. Opening a multi-page PDF shows a partial bar at page 1, growing to full
   only at the very end.
2. Scrolling within a zoomed page moves the bar continuously.
3. Values persist/save correctly (reader-state POST uses the same %).

---

## BL-003 — Two-page (opposite page) reader view

- **Priority:** Medium
- **Status:** implemented + deployed 2026-08-13 — awaiting user verification
- **Reported:** 2026-08-13

### Symptom

Feature request: the reading area should be able to show **two pages side by
side** (book spread / opposite-page view), like a real book, for PDF, DJVU
and CBZ/CBR.

### Notes / scope

- Add a toggle button in the reader toolbar (regular + fullscreen toolbar).
- PDF/DJVU: pair pages (1-2, 3-4, …) — render both canvases in a flex row,
  fit the combined width, keep zoom + scroll working on the spread.
- Comics: pair adjacent images the same way.
- Navigation advances two pages at a time while in two-page view.
- Highlights draw per-canvas; drawing overlay may be hidden in two-page view.

### Acceptance criteria

1. Toggling two-page view on a PDF shows pages N and N+1 side by side and
   fits them together in the viewport.
2. Next/Prev move by a full spread (2 pages).
3. Zoom still works and the spread stays scrollable to its end.
4. Single-page behaviour (default) is unchanged.

---

## BL-004 — Comic reader broken for all CBZ/CBR

- **Priority:** High
- **Status:** open
- **Reported:** 2026-08-13

### Symptom

Opening any CBZ/CBR in the reader shows the error panel ("Could not extract
this comic archive … Use the Download button instead") even when server-side
extraction succeeded — the reader is blank with prev/next hidden.

### Where

- Contract mismatch: `readerPages = data.pages || []` (templates/index.html:~3605)
  vs backend `/api/book/<id>/read` returning only `{format, total, book_id}`
  (app.py:1877, 1882) and `/api/comic-status` returning only `{status, total}`
  (app.py:1729). `readerPages` is therefore always empty.
- Poll path on success also returns `total` only (templates/index.html:3591-3595).
- Page sorting is plain `sorted(files)` (app.py:1702) — `1,10,2` misordering for
  non-zero-padded page names; nested folder walk unsorted.
- Extraction cache deleted on reader close (templates/index.html:3841) → every
  open re-extracts.

### Notes / acceptance criteria

- Fix the frontend to build the page array from `data.total`/`total`
  (both the direct and the poll path). Optionally return an explicit
  `pages` list from the backend.
- Natural/numeric-aware page sort (and folder-walk order).
- Keep the extraction cache between opens; add a TTL sweep instead of the
  delete-on-close.
- Verify: opening a multi-page CBZ renders page 1, prev/next/progress/zoom/draw/
  highlights work, page order is correct (`1,2,…,10`).

---

## BL-005 — CBR = download-only (no unrar in container)

- **Priority:** High
- **Status:** open
- **Reported:** 2026-08-13

### Symptom

Real `.cbr` (RAR) files fail to read in the container — reader shows "This
format needs external tools to extract". Metadata-side they are catalogued
with 0 pages and no error, silently.

### Where

- Dockerfile:5-8 installs only `build-essential`; `rarfile` (requirements.txt:7)
  needs a system `unrar`/`unar`/`bsdtar`, which is absent → `_extract_comic`
  returns `[]` (app.py:1694-1699).
- `.cbr` is mapped to the ZIP extractor `extract_cbz` (extractors/__init__.py:11-12);
  `zipfile.BadZipFile` is swallowed (extractors/cbz.py:16-17) → silent success.
- `openReader` routes `.cbr` to `loadComicReader` (templates/index.html:3011-3012).

### Notes / decision

- **CBZ-only decision (user, 2026-08-13):** do NOT install unrar. Route `.cbr`
  to the download/fallback panel instead of attempting extraction.
- Update the extractor mapping so CBR metadata extraction fails loudly
  (quarantine with an explicit error code, e.g. `NO_RAR_TOOL`) instead of
  silently cataloguing with zero pages.

---

## BL-006 — Series / volume / issue fields + collections + saved searches

- **Priority:** High
- **Status:** open
- **Reported:** 2026-08-13

### Symptom

No way to group a book series (e.g. "Batman vol 2 issue 5") or keep reading
order; no shelves/collections or saved (virtual-library) views. Comic and book
series metadata is parsed but never stored.

### Where

- `metadata` table has title/authors/publisher/isbn/pages/year/udc etc. but no
  series/volume/issue/collection columns (db.py:35-53).
- Schema migrations use the ad-hoc `ALTER TABLE … ADD COLUMN` try/except pattern
  (db.py:89-116) — follow it, do not introduce a new framework.
- `enrich_filename.py` parses `series_num` (enrich_filename.py:12-15, 222-223)
  but `pipeline.py:324-326` only consumes title/author/year → series dropped.
- Docstring claims `series_name` output (enrich_filename.py:188) but code never
  sets it.
- Sort map is title/authors/year/format/file_size/stage/created_at only
  (db.py:704-706); no series reading-order sort.
- Library UI: no series filter/group (templates/index.html).

### Notes

- Add `series`, `series_num`, `volume`, `issue` (and `collection` if not via
  tags) to `metadata`; backfill from filenames on migration.
- Collections/shelves: reuse `tags` with a `collection` tag type, or add
  `collections`/`collection_books` tables.
- Library: filter by series; group/sort by series reading order
  (series_num → volume → issue); editable series fields in the detail panel.
- Saved searches: persist named query strings, list them in the sidebar.

---

## BL-007 — Reader comfort (all formats)

- **Priority:** Medium
- **Status:** open
- **Reported:** 2026-08-13

### Symptom

Missing reader amenities vs Calibre: no in-book search, no TOC for PDF/comic,
no light/sepia/night themes, no font-size/line-spacing controls, no page
thumbnails, no manga/RTL reading order, and no annotation export for PDF/comic.

### Where

- In-book search: none — only library FTS and annotation filter exist.
- TOC: EPUB only (`loadToc`, index.html:2793-2833); PDF could use
  `pdf.getOutline()` (pdf.js present); comics have none.
- Themes: UI is a fixed dark palette; no sepia/night; EPUB uses
  `themes.fontSize` only for zoom (index.html:3948).
- Font/line-spacing: only EPUB font-size via zoom; no line-height control.
- Thumbnails: none (no strip/grid).
- Reading order: always LTR, spread always `[idx, idx+1]` (showComicSpread
  index.html:3662-3705).
- Annotation export button shown only for epub-like formats
  (index.html:2994; backend export app.py:2081-2089 is format-agnostic).

### Acceptance criteria

1. EPUB in-book search finds and jumps to/highlights matches.
2. PDF TOC in the contents sidebar; comic TOC from folder/chapter markers (best-effort).
3. Theme toggle (light/sepia/night) applies to all formats (canvas filter for night).
4. EPUB font-size and line-spacing controls.
5. Page thumbnail strip for PDF and comic.
6. Manga/RTL toggle reverses page/spread order.
7. Markdown export includes PDF/comic page-based highlights.

---

## BL-008 — Catalog power tools

- **Priority:** Medium
- **Status:** open
- **Reported:** 2026-08-13

### Symptom

Library editing is single-book only. No batch multi-select editing, no
on-demand duplicate finder, no user-defined custom columns.

### Where

- No batch edit UI; detail-panel inline edit is the only path.
- Duplicate logic exists only in the pipeline (hash: filename_cleaner.py:48-59;
  title fuzzy: filename_cleaner.py:62-63; passes: pipeline.py:482-626) but has no
  on-demand UI.
- `db.py` schema has no user-defined columns.

### Notes

- Batch multi-select edit (tags/series/collection/reading status).
- On-demand duplicate finder reusing hash + title-fuzzy over a chosen scope.
- Custom columns: user-defined metadata fields (schema + UI + config).

---

## BL-009 — Cannot delete a book from the library

- **Priority:** High
- **Status:** open
- **Reported:** 2026-08-13

### Symptom

There is no way to remove a book from the library or purge a quarantined file.
Only reading-list entries, annotations, drawings, bookmarks, and the comic
cache have DELETE endpoints.

### Where

- No `DELETE /api/book/...` route (existing DELETE routes: app.py:1956, 1978,
  2058, 2092, 2128 — none delete a book record).
- Cascade tables: reader_state, annotations, drawings, bookmarks, tags,
  pipeline_log, reading_list reference file/book ids (db.py).

### Notes / acceptance criteria

- Add delete with confirmation; cascade-remove book metadata + annotations +
  drawings + bookmarks + tags + reading-list/state; keep the source file on
  disk by default (option to also remove it).
- Add a "purge" action for quarantined entries.
- Expose in Library detail panel (and Quarantine) with an admin check.

---

## BL-010 — No routine database backup

- **Priority:** High
- **Status:** open
- **Reported:** 2026-08-13

### Symptom

`catalog.db` is the single source of truth (annotations, reading state,
config overrides) but the app has no backup mechanism. The only backup today is
the `tools/cleanup_processed.py` script (tools/cleanup_processed.py:250-252)
and manual `--export-pi`.

### Where

- `BOOK_DB_PATH=/data/catalog.db` (docker-compose.yml; DEPLOY_PI.md).
- No `VACUUM INTO` / sqlite backup anywhere in app.py/db.py.

### Notes / acceptance criteria

- Scheduled/snapshot backup of catalog.db (e.g. `VACUUM INTO` or sqlite3
  offline backup) with retention; a manual trigger in Settings; optionally a
  nightly cron job in compose.
- Restore procedure documented.

---

## BL-011 — Auth scope decision (public exposure)

- **Priority:** High
- **Status:** open
- **Reported:** 2026-08-13

### Symptom

The app runs behind a Cloudflare Tunnel (casaos/cloudflare-tunnel.md).
Authentication protects only the admin tabs; Library, Reader, and Gallery
(containing all book contents + annotations) are public by design
(README.md:57-58). Anyone with the URL can read the whole library and notes.

### Notes

- Decide the intended model and implement it:
  a. gate the whole app behind login, or
  b. explicit read-only public mode, or
  c. shared-link token access.
- Update README/DEPLOY docs accordingly. `.env` currently has
  `BOOK_AUTH_PASSWORD` set (admin-only gate).

---

## BL-012 — Cover management (upload/replace + comic covers)

- **Priority:** Medium
- **Status:** open
- **Reported:** 2026-08-13

### Symptom

No way to upload or replace a cover in the UI; comics get no cover at all
(extractors/cbz.py returns title/format_hint/pages only) so they show
placeholders in the gallery.

### Where

- `extractors/cbz.py:5-19` — no cover extraction (first page image).
- `metadata.cover_path` exists (db.py:47) but no replace/upload endpoint or UI.

### Notes

- Delete current cover + upload a new one (or repick from file) in the detail
  panel.
- For comics: extract the first page image as the cover during metadata
  extraction.

---

## BL-013 — OPDS feed (e-reader app parity)

- **Priority:** Low
- **Status:** open (candidate — not committed)
- **Reported:** 2026-08-13

### Symptom

Calibre's content server exposes OPDS/OPDS-PSE so e-reader apps (KoReader,
Lithium, etc.) can browse and download the library. This app has no such feed.

### Notes

- Add an OPDS/OPDS-PSE catalog feed (`/opds`, `/opds/shelf`, search) so
  e-reader apps can consume the library and push reading position back.
- Flag as a decision; build only if wanted.
