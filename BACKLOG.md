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
- **Status:** implemented + deployed 2026-08-15 — awaiting user verification
- **Reported:** 2026-08-13
- **Fixed:** 2026-08-15

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

### Implemented (2026-08-15)

- Frontend builds the page-array from `data.total` in both the direct and poll
  paths — `/read` returns `{format,total,book_id}` and has no `pages` field
  (index.html:3660-3672, `loadComicReader`).
- Numeric-aware natural sort in `_comic_pages()` (app.py:1691,316) — dirs walked
  in the same order; replaces plain `sorted(files)` which misordered `1,10,2`.
- Extraction cache now persists between opens: delete-on-close removed from
  `closeReader()`, server TTL sweep `_prune_comic_cache()` (14 days, app.py) with
  mtime touch on access (status + page serve); manual
  `/api/book/<id>/read/cache` DELETE still available for forced clears.

### Verified (2026-08-15, book 1670)

- `/read` → `{status:extracting}`; poll → `{status:done,total:14}`;
  `/read/page/0` serves real image bytes (WEBP, 140 KB); ordering numeric
  (`001…014`, trailing watermark image last). Acceptance criteria met for CBZ.

---

## BL-005 — CBR = download-only (no unrar in container)

- **Priority:** High
- **Status:** implemented + deployed 2026-08-15 — awaiting user verification
- **Reported:** 2026-08-13
- **Fixed:** 2026-08-15

### Symptom

Real `.cbr` (RAR) files fail to read in the container — reader shows "This
format needs external tools to extract". Metadata-side they are catalogued
with 0 pages and no error, silently.

### Where

- ~~Dockerfile:5-8 installs only `build-essential`; `rarfile` (requirements.txt:7)
  needs a system `unrar`/`unar`/`bsdtar`, which is absent → `_extract_comic`
  returns `[]`~~ — user decision: keep no-RAR.
- ~~`.cbr` is mapped to the ZIP extractor `extract_cbz` (extractors/__init__.py)~~ —
  replaced by a dedicated `extract_cbr` that fails loudly.
- ~~`openReader` routes `.cbr` to `loadComicReader`~~ — now routed to the
  download-only fallback panel.

### Decision (user, 2026-08-13)

- Do NOT install unrar; `.cbr` is download-only.
- Metadata extraction must fail loudly rather than cataloguing silently.

### Implemented (2026-08-15)

- `extractors/extract_cbr()` raises `ExtractError` with code `NO_RAR_TOOL`
  (extractors/cbr.py); `extract_metadata` now carries `_error_code`, and the
  pipeline quarantines with that code instead of a generic `EXTRACT_FAIL`
  (pipeline.py:291-297).
- `/api/book/<id>/read` rejects `.cbr` with 400 "download-only" (app.py).
- `openReader` routes `.cbr` to a tailored `showReaderFallback("CBR is
  download-only", …)` (templates/index.html) — no extraction attempt/polling;
  a generic fallback helper also cleans up the draw group.

### Verified (2026-08-15)

- `extract_metadata("/tmp/x.cbr")` → `_error_code = "NO_RAR_TOOL"`.
- Real CBR book 6464: `/api/book/6464/read` → HTTP 400 (download-only guard).
- Served page includes the new routing branch.

---

## BL-006 — Series / volume / issue fields + collections + saved searches

- **Priority:** High
- **Status:** closed
- **Reported:** 2026-08-13
- **Closed:** 2026-08-15

### Done

- `metadata.series / series_num / volume / issue` columns added via the existing
  ad-hoc ALTER TABLE migration pattern (db.py:122).
- `enrich_filename.py` now returns `series`, `series_num`, `volume`, `issue`
  (BL-006 block, enrich_filename.py:268); digits-only "series" names (ISBNs /
  catalogue ids) are discarded.
- `pipeline.py` persists all series fields into `metadata`.
- `db.py`: reading-order sort (`series`, then `series_num`, `volume`, `issue`),
  `series` search filter + `/api/search/series` facet endpoint, series facets in
  results, `update_metadata_series` helper.
- `saved_searches` table + GET/POST/DELETE endpoints (app.py:2453-2488);
  `tools/backfill_series.py` backfilled 93 + 8 existing books from filenames
  (UUID-named, digit-only, and z-lib-spam filenames skipped).
- Library UI: series facet/filter, series sort, series badges, editable series
  fields in the detail panel, saved-searches list in the sidebar.

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
- **Status:** implemented + deployed 2026-08-15 — awaiting user verification
- **Reported:** 2026-08-13

### Implemented (2026-08-15)

- **C1 EPUB in-book search** — search box in the left sidebar; iterates
  `book.spine.spineItems`, finds matches, jumps via `rendition.display` and
  highlights the first hit with `annotations.highlight`.
- **C2 PDF TOC** — `buildPdfToc()` uses `pdf.getOutline()` +
  `getDestination`/`getPageIndex` to build a page-numbered TOC in the same
  contents sidebar; `jumpToPdfToc` renders the page and marks the active entry.
  Comics hide the block (no chapter markers available).
- **C3 Themes** — toolbar select (Dark/Light/Sepia/Night), persisted to
  localStorage. EPUB uses `rendition.themes.register/select`; PDF/comic use CSS
  classes on `#readerArea` with a night `invert+hue-rotate` canvas filter.
- **C4 EPUB typography** — A−/A+ font-size (`themes.fontSize`) + line-height
  select (`themes.override`), persisted.
- **C5 Thumbnails** — `#readerThumbs` strip below the toolbar for PDF/comic;
  comic thumbs are lazy `<img>`s, PDF thumbs render lazily via
  IntersectionObserver; click jumps, active page highlighted.
- **C6 Manga/RTL** — `⇄` toggle for comics reverses prev/next direction and
  swaps the two-page spread sides; thumbnail strip reverses.
- **C7 Annotation export** — export button now visible for PDF/comic; backend
  adds `Location: Page N` to page-based highlights (db.py export).

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
- **Status:** implemented + deployed 2026-08-15; optional keep-source enhancement done 2026-08-16
- **Reported:** 2026-08-13
- **Fixed:** 2026-08-15

### Implemented

- `POST /api/book/<id>/delete` (app.py:2321) removes the physical source file,
  cover, comic cache, and all DB entries; `POST /api/bulk/delete` (app.py:2356)
  does the same for a list of IDs.
- `bulk_delete_files()` (db.py:918) cascades books_fts, annotations, bookmarks,
  reader_state, reading_list, quarantined, pipeline_log, tags, metadata,
  files; drawings cascade via `ON DELETE CASCADE` FK (db.py:1008; FKs are ON,
  db.py:12).
- UI: `deleteBook()` with a `showConfirm` dialog (index.html:5016); bulk
  delete in multi-select (index.html:2556).
- Quarantine purge already exists (`/api/quarantine/bulk/delete`, app.py:1137).

### Optional enhancement (done 2026-08-16)

- `POST /api/book/<id>/delete` now accepts `{"keep_source": true}` to leave the
  source file on disk (DB entry, cover and comic cache are still removed).
- `deleteBook()` uses a new `showConfirmCheckbox` dialog with a "Also delete the
  source file from disk" checkbox (unchecked = keep source by default); sends
  `keep_source` accordingly. Bulk delete still always removes files.

---

## BL-010 — No routine database backup

- **Priority:** High
- **Status:** implemented + deployed 2026-08-16
- **Reported:** 2026-08-13
- **Fixed:** 2026-08-16

### Symptom

`catalog.db` is the single source of truth (annotations, reading state,
config overrides) but the app has no backup mechanism. The only backup today is
the `tools/cleanup_processed.py` script (tools/cleanup_processed.py:250-252)
and manual `--export-pi`.

### Implemented

- `_create_db_backup()` (app.py) makes an online SQLite backup via
  `src.backup(dst)` into `<DATA_DIR>/backups/catalog-<timestamp>.db` — safe
  while the app is running.
- Endpoints: `POST /api/backup` (manual trigger), `GET /api/backups` (list with
  size/mtime + retention + dir), `GET /api/backups/<name>/download`.
- Nightly self-healing loop: `_backup_loop` thread starts with the web process,
  checks every 6h and writes a snapshot if the newest is older than 24h.
- Retention: keeps the newest `BOOK_BACKUP_RETENTION` backups (default 14,
  env-overridable), pruned on each backup.
- Settings tab "Database Backup" section: Backup now button, list of snapshots
  with Download links, retention/dir labels.

### Restore procedure

1. Stop the app: `docker compose stop book-organiser`.
2. Copy a snapshot over the live DB (keep a copy of the live one first):
   `cp /data/backups/catalog-<timestamp>.db /data/catalog.db`
3. Start the app: `docker compose start book-organiser`. The pipeline metadata
   enrichment will not re-run automatically; annotations, reading state, tags
   and saved searches are restored as-is from the snapshot.

### Where

- `BOOK_DB_PATH=/data/catalog.db` (docker-compose.yml; DEPLOY_PI.md).
- Backups land in `/data/backups` (same SSD volume, not off-box) — download a
  copy periodically to keep an off-box snapshot.

---

## BL-011 — Auth scope decision (public exposure)

- **Priority:** High
- **Status:** implemented + deployed 2026-08-16
- **Reported:** 2026-08-13
- **Fixed:** 2026-08-16 (decided: **whole app behind login**)

### Symptom

The app runs behind a Cloudflare Tunnel (casaos/cloudflare-tunnel.md).
Authentication protects only the admin tabs; Library, Reader, and Gallery
(containing all book contents + annotations) are public by design
(README.md:57-58). Anyone with the URL can read the whole library and notes.

### Decision

Model (a): **gate the whole app behind login**. The P8.7 whole-app gate was
already implemented and deployed (app.py `_auth_gate`, frontend blocks the
whole UI + re-locks on any 401); this item confirms the decision and brings
the docs in line.

### Implemented (documentation)

- README.md: tabs are "Login required", Authentication section rewritten to
  describe the whole-app gate (only `/`, `/static/*`, `/api/health`,
  `/api/auth/*`, `/api/csrf-token` reachable without a session).
- INSTALLING.md: `BOOK_AUTH_PASSWORD` now described as "whole-app login
  password".
- casaos/cloudflare-tunnel.md: verify step notes the whole app is gated.
- BUILDPLAN.md: P8.7 marked ✅ Done.

---

## BL-012 — Cover management (upload/replace + comic covers)

- **Priority:** Medium
- **Status:** implemented + deployed 2026-08-16
- **Reported:** 2026-08-13
- **Fixed:** 2026-08-16

### Symptom

No way to upload or replace a cover in the UI; comics get no cover at all
(extractors/cbz.py returns title/format_hint/pages only) so they show
placeholders in the gallery.

### Implemented

- `extractors/cbz.py` now extracts the first page image (natural-sorted first
  image entry) as `cover_data`; the pipeline writes it to `COVER_DIR`
  (`<file_id>.jpg`) so comics get a cover at metadata/re-extract time.
- `POST /api/book/<id>/cover` accepts a multipart `cover` field (or raw body),
  sniffs PNG/GIF/WebP/JPEG by magic bytes, writes a temp file then
  `os.replace` into `COVER_DIR`, deletes the old cover, and updates
  `metadata.cover_path`.
- Detail panel: "Replace Cover" button + hidden file input → `uploadCover()`
  posts the image and refreshes the detail view.
- Verified on the Pi: cover upload on book 67116 stored `/data/covers/67116.jpg`
  and served as PNG; cbz extractor produced WebP first-page covers
  (RIFF/WEBP magic, ~170 KB) for three Asterix CBZs.

---

## BL-013 — OPDS feed (e-reader app parity)

- **Priority:** Low
- **Status:** implemented + deployed 2026-08-16
- **Reported:** 2026-08-13
- **Fixed:** 2026-08-16

### Symptom

Calibre's content server exposes OPDS/OPDS-PSE so e-reader apps (KoReader,
Lithium, etc.) can browse and download the library. This app has no such feed.

### Implemented

- New `opds_feed.py` (Atom/OPDS 1.2 builders) + routes in `app.py`:
  - `/opds` — root navigation feed (Catalog, Recent, Reading list, UDC browse,
    top-30 popular UDC classes with counts).
  - `/opds/catalog?startIndex=&count=` — paginated acquisition feed with
    `<link rel="next">`, sorted by title.
  - `/opds/recent`, `/opds/shelf` (reading list), `/opds/udc` + `/opds/udc/<code>`.
  - `/opds/search?q=` — search feed using the existing `search_books` FTS.
  - `/opds/opensearch.xml` — OpenSearch description (search template).
- Entries carry author(s), description, UDC category, cover link
  (`http://opds-spec.org/image`, MIME from actual file ext) and acquisition
  link (`http://opds-spec.org/acquisition` → `/api/book/<id>/download`, correct
  per-format MIME).
- Auth: OPDS routes sit behind the same whole-app gate. `is_authenticated()`
  now also accepts **HTTP Basic auth** (same shared password) so e-reader
  clients that can't do cookie sessions (KoReader, Lithium) can log in.
- Feed scope: books at `cataloged`/`copied`/`survivor` stages (skipped
  duplicates and quarantined excluded).
- XML hygiene: C0/C1 control chars stripped, `& < > " '` escaped, so
  corrupt/binary titles in the DB can't break the feed (seen live).
- Verified on the Pi: all feeds well-formed, pagination `next` link present,
  UDC feeds (630/006/600), search (asterix), Basic-auth download of a CBZ
  (served `application/octet-stream`, zip magic) and cover (image/jpeg).

---

## BL-014 — Online metadata fetch (Calibre parity)

- **Priority:** High
- **Status:** ✅ Done
- **Reported:** 2026-08-15

### Symptom

Metadata comes only from local filename parsing; Calibre auto-fills
title/author/cover/ISBN/description from online sources. Books with sparse
filenames get blank covers and missing fields with no way to auto-fetch.

### Where

- `enrich` is local-only filename parsing: `/api/book/<id>/enrich`
  (app.py:2180) → enrich_filename.py; no network lookup anywhere in the app.
- Metadata fields available for fill: title/authors/publisher/isbn/pages/year/
  description (db.py:35-53).
- Covers: `metadata.cover_path` (db.py:47), `/api/covers` (app.py:819),
  `/api/cover/<id>` (app.py:848) — a downloaded cover writes into the same
  cover store (ties into BL-012).

### Notes

- Add a lookup module (Google Books and/or Open Library/ISBNdb, keyless) keyed
  by ISBN → title/authors query; map API JSON onto the existing columns.
- Manual "Fetch metadata" per book + bulk for a selection; never silently
  overwrite a non-empty field (per-field merge).
- Download the cover when the chosen record has one; skip cleanly on 404 /
  rate-limit with a per-book log entry.

### Resolution

- Online lookup already existed (`enricher.py`: Open Library keyless search +
  Google Books fallback via `GOOGLE_BOOKS_API_KEY`, rate-limit, disk cache);
  the gaps were merge semantics, per-book logging, and bulk-for-selection.
- `enricher.py`: `_ol_work_description()` now fetches the work record so the
  keyless OL path returns real descriptions (search.json has none); stub
  descriptions ("1 online resource :") filtered out; cache key bumped to v2
  so stale pre-description results are ignored.
- `/api/book/<id>/enrich` (app.py:2489): per-field merge — only fills fields
  that are currently empty (title/authors/publisher/year/isbn/pages/language/
  description/cover), never overwrites a non-empty one; downloads a missing
  cover; writes one `pipeline_log` entry per book with filled-field counts.
- `/api/bulk/enrich` (app.py:2959): POST `{book_ids}` (cap 200 default,
  max 1000) — same merge/logging, returns per-book results summary.
- Frontend: "Fetch Metadata" bulk-toolbar button (index.html) using
  `getSelectedIds()`.
- Verified live on the Pi: description filled from Open Library work record
  (book 53548, 561 chars) and 9 fields + 1 cover across 2 books from Google
  Books; re-enrich of an already-filled book changed nothing (merge holds);
  per-book logs present for success/no-data cases.

---

## BL-015 — Format conversion with output profiles

- **Priority:** Medium
- **Status:** open
- **Reported:** 2026-08-15

### Symptom

ebook-convert is only used internally to produce a read-only EPUB
(`_convert_to_epub`). A user cannot download a book in another format
(azw3/mobi/pdf/fb2) or for a specific device profile.

### Where

- `_convert_to_epub(filepath)` (app.py:1753) shells out to
  `shutil.which("ebook-convert")` with fixed EPUB output; conversion disk cache
  at `cache/converted/` (app.py:1788+).
- `/api/book/<id>/download` (app.py:1653) serves the original file only.
- No conversion-request route exists.

### Notes

- `/api/book/<id>/convert` (POST, `format` + optional
  `device=kindle|kobo`) reusing the existing ebook-convert invocation with
  device output-profile args when requested.
- Deliver as a normal download; a "Download as…" menu in the detail panel and
  batch conversion for multi-select.
- Reuse the disk conversion cache; support ebook-convert's own output set.

---

## BL-016 — Device sync (send to e-reader)

- **Priority:** Low
- **Status:** open (candidate — overlaps BL-013)
- **Reported:** 2026-08-15

### Symptom

No way to get books onto an e-reader (Kobo/Kindle). Calibre hands this via a
USB-connected device; a headless server's realistic path is network delivery,
not USB mounting on the Pi.

### Where

- Only raw file download exists: `/api/book/<id>/download` (app.py:1653).
- No device detection / mount / transfer code (app is a Docker container).

### Notes

- Primary path: OPDS/OPDS-PSE (BL-013) so e-reader apps push/pull over Wi-Fi,
  plus a per-device transfer profile that picks compatible formats
  (kindle → azw3/mobi via BL-015-style conversion).
- USB/MTP only if the Pi is expected to host a connected device — note the
  requirement (usb gadget drivers + container device passthrough) before
  committing.
- Decide the model and document it; build only if wanted (same flag as BL-013).

---

## BL-017 — Library catalog generation

- **Priority:** Low
- **Status:** open
- **Reported:** 2026-08-15

### Symptom

The only catalog export is a spreadsheet (`/api/export/excel`). Calibre's
"Generate catalog" produces readable HTML/EPUB catalogs of the whole library
or a saved search.

### Where

- `/api/export/excel` (app.py:2432) is the sole catalog export; it already
  collects the field set a readable catalog needs.

### Notes

- Catalog for a scope (all / current filter / saved search):
  - HTML — printable, with cover, series list, tags;
  - EPUB — a generated book whose TOC is the catalog; CSV optional.
- Reuse the Excel export row-flattening to source data (one query path).

---

## BL-018 — Save-to-disk with folder/file templates

- **Priority:** Medium
- **Status:** open
- **Reported:** 2026-08-15

### Symptom

Files land in the fixed UDC layout at copy time; there is no way to export a
book (or selection) into a user-defined pattern like
`Author/Series/Title.ext` the way Calibre's "Save to disk" does.

### Where

- Pipeline copy is UDC-bound (copy phase / `dir_archive_dir`).
- `/api/book/<id>/download` (app.py:1653) serves single raw files only.

### Notes

- User-configurable template in Settings with tokens (`{title}`, `{authors}`,
  `{series}`, `{series_num}`, `{year}`, `{isbn}`) and an optional folder
  prefix; safe-path sanitisation (slashes in titles, etc.).
- Never rewrite the canonical copy; deliver as a download (zip when more than
  one book) or an on-disk export dir.

---

## BL-019 — Library integrity audit ("Check library")

- **Priority:** Medium
- **Status:** implemented + deployed 2026-08-16
- **Reported:** 2026-08-15
- **Fixed:** 2026-08-16

### Symptom

Calibre's "Check library" reports book-to-disk consistency. This app repairs
DB/file paths manually (`sync-db`, `remap-paths`) and dedups only at ingest,
but has no one-click audit of cover/file/DB consistency.

### Implemented

- `GET /api/audit` runs a read-only sweep (grouped counts + first-20 previews):
  1. DB rows whose stored path/size is missing or differs on disk
     (`missing_or_mismatched` — missing files + size mismatches);
  2. archive-dir files with no DB row (orphans);
  3. metadata with pages=0 or missing cover_path where the source exists
     (`metadata_issues` with per-item reasons);
  4. duplicate report by hash (exact) + fuzzy title (token-Jaccard pre-gate
     then `title_similarity` ≥ 0.95, bucketed by normalized 8-char prefix so
     it stays O(bucket²) instead of O(n²)).
- Performance: on 26k rows the fuzzy check needed a Jaccard pre-gate
  (0.8 threshold) to avoid ~274k `SequenceMatcher` calls — audit runs in ~6 s
  on the Pi (was 122 s naive).
- `POST /api/audit/repair`:
  - fixes size mismatches (updates stored `file_size` from disk);
  - re-extracts covers/pages for affected books, batched with a
    `max_metadata` cap (default 100, `remaining` reports how many are left so
    the user can run it again);
  - missing source files, orphans and duplicate groups are reported only
    (need manual remap/re-import/quarantine).
- Settings tab "Library Integrity Audit" card: Run Audit + Repair buttons with
  inline summary line (missing / size mismatch / orphans / metadata issues /
  duplicate groups) and expandable preview lists.

---

## BL-020 — Chrome auto-hide: edge-zone triggers + tap-to-pin + panel-open lock

- **Priority:** High
- **Status:** implemented + deployed 2026-08-23
- **Reported:** 2026-08-23

### Symptom

Fullscreen toolbar triggered on any mousemove globally — too sensitive, causing
flicker during reading. No way to keep chrome visible while reading. Sidebars
hover-revealed via 12px edge zones were hard to target. No Escape cascade.

### Implemented

- **Edge-zone triggers**: Top/bottom 24px strips reveal toolbar on mouseenter.
- **Wider sidebar hotzones**: Left/right widened from 12px to 24px.
- **Center-tap-to-pin**: Click/tap center toggles toolbar pin (blue dot indicator).
  Drag threshold prevents accidental pin on scroll.
- **Panel-open lock**: Sidebar open → toolbar auto-hide suspended.
- **3-second auto-hide**: Timer only starts when chrome revealed + no panel open.
- **Escape cascade**: search → sidebar unpin → toolbar unpin → fullscreen exit.
- **Pin indicator**: CSS blue dot above toolbar when pinned.

### Acceptance criteria

1. Toolbar does NOT appear when mouse moves over the reading area.
2. Toolbar appears when mouse enters top/bottom 24px edge zone.
3. Clicking center toggles toolbar pin (blue dot indicator).
4. Toolbar stays visible while a sidebar is open.
5. Toolbar auto-hides after 3s idle when no panel is open.
6. ESC closes panels in priority order before exiting fullscreen.
7. Touch: tap center toggles pin; tap top/bottom edge reveals toolbar.

---

## BL-021 — Persistent reader settings (per-format + per-book)

- **Priority:** High
- **Status:** implemented + deployed 2026-08-23
- **Reported:** 2026-08-23

### Symptom

Reader settings (theme, zoom, line height) reset every time the reader is
closed. Users must reconfigure on every book open. No per-format memory.

### Implemented

- Three-layer cascade: per-book override → per-format default → built-in default.
- Stored in localStorage keyed by format and per-book.
- Auto-save on change for theme, zoom, line height.
- Apply on open via `_applyReaderPrefs(fmt, bookId)`.
- EPUB zoom applied after render via `themes.fontSize()`.
- Backward compatible with old localStorage keys.

### Acceptance criteria

1. Set zoom 150% on PDF → close → reopen → zoom is 150%.
2. Set zoom 150% on PDF → open different PDF → zoom is 150% (per-format).
3. Set Sepia on EPUB → open PDF → theme is Dark (per-format).
4. Change theme on specific book → open different book → default theme.
5. Line height persists for EPUB across sessions.

---

## BL-022 — Chapter-aware progress scrubber (glass footer)

- **Priority:** High
- **Status:** implemented + deployed 2026-08-23
- **Reported:** 2026-08-23

### Symptom

The thin 4px progress bar in the toolbar is nearly invisible and offers no
chapter context. Users cannot see where they are relative to chapters, nor
can they scrub to a specific page. No way to jump to a page by number.

### Implemented

- **Glass footer bar**: frosted-glass bar (`backdrop-filter: blur(16px)`) at the
  bottom of the reader, full width, with scrubber + ticks + chip + page-jump.
- **Range slider scrubber**: draggable slider updates position on mouseup/touchend.
- **Chapter tick marks**: vertical lines at chapter boundaries (EPUB) or every
  10 pages (PDF/CBZ). Current chapter tick highlighted in blue.
- **Percentage chip**: click toggles to a number input for page-jump (Enter to
  navigate). Works for EPUB (chapter index), PDF (page), CBZ (image index).
- **Prev/next chapter chevrons**: quick jump to next/previous chapter boundary.
- **Fullscreen version**: separate fixed-position footer bar shown only in
  fullscreen mode. CSS toggles between normal and fullscreen footers.
- **Auto-hide sync**: footer shows when reader is open, hides on close.

### Acceptance criteria

1. Glass footer visible when reader opens.
2. Scrubber drag navigates to correct page/chapter on release.
3. EPUB shows tick marks at each spine item; current tick is blue.
4. PDF/CBZ show ticks every 10 pages.
5. Click percentage chip → type page number → Enter navigates.
6. Prev/next chevrons move by chapter (EPUB) or page (PDF/CBZ).
7. Footer visible in fullscreen with same functionality.
8. Footer hides when reader closes.

---

## BL-023 — Expanded themes & typography

- **Priority:** High
- **Status:** implemented + deployed 2026-08-23
- **Reported:** 2026-08-23

### Symptom

Only 4 themes (Dark, Light, Sepia, Night). No font family selector, no text
justification toggle, no hyphenation toggle, no content-width control.

### Implemented

- **8 themes**: Dark, Light, Sepia, Night, Gray, Rosewood, Azure, Ocean.
  Each has CSS for `readerArea` + epub.js palette for EPUB rendering.
- **Font family selector**: serif, sans-serif, monospace, Georgia, Palatino.
  Persists per-format via `_readerPrefs`.
- **Justify toggle**: toggles `text-align: justify` for EPUB. Blue when active.
- **Hyphenation toggle**: toggles `hyphens: auto` for EPUB. Blue when active.
- **Content width slider**: 400–1600px range input. Overrides `max-width`
  for EPUB body. All prefs persist per-format and per-book (BL-021).
- Controls show only for EPUB, hidden for PDF/CBZ.

### Acceptance criteria

1. All 8 themes apply correctly in both EPUB and PDF/CBZ modes.
2. Font family selector changes EPUB font and persists.
3. Justify toggle applies justify alignment to EPUB text.
4. Hyphenation toggle enables CSS hyphenation.
5. Content width slider restricts EPUB text width.
6. All new settings persist per-format via BL-021 system.

---

## BL-024 — Selection popup actions (Copy + Translate + Define + Search)

- **Priority:** High
- **Status:** implemented + deployed 2026-08-23
- **Reported:** 2026-08-23

### Symptom

Text selection popup only has Highlight + Note + Cancel. No way to copy
selected text, translate it, look up a definition, or search the web.

### Implemented

- **Copy button**: copies selected text to clipboard via `navigator.clipboard`.
  Shows "Copied!" confirmation for 1.5s.
- **Translate button**: opens Google Translate in a new tab with the selected
  text pre-filled as source.
- **Define button**: calls free dictionary API (`dictionaryapi.dev`) and
  displays part-of-speech + definitions inline in the popup. Shows first word
  only for multi-word selections.
- **Search button**: opens Google search in a new tab with the selected text.
- **Action result area**: collapsible div below the action buttons, shows
  API responses or confirmation messages. Cleared when popup closes.

### Acceptance criteria

1. Select text → popup shows Copy/Translate/Define/Search buttons below
   Highlight/Note/Cancel row.
2. Copy copies text to clipboard.
3. Translate opens Google Translate with text pre-filled.
4. Define shows dictionary definition inline.
5. Search opens Google with text as query.
6. Action result area clears when popup closes.

---

## BL-025 — Resume toast on book open

- **Priority:** Medium
- **Status:** implemented + deployed 2026-08-23
- **Reported:** 2026-08-23

### Symptom

When opening a book the reader always starts from the beginning (or restores
via API silently). No visual feedback that a previous position exists.

### Implemented

- **Resume toast**: bottom-center frosted-glass toast appears when a book with
  saved progress (>2%) is opened. Shows "Resume reading at X%?" with Resume
  and Start Fresh buttons.
- **Fetch on open**: `GET /api/book/<id>/reader-state` is fetched after
  `switchTab("reader")`. If location exists and progress > 2%, toast is shown.
- **Resume navigates**: EPUB → `rendition.display(cfi)`, PDF → `renderPage(n)`,
  CBZ → `showComicPage(n)`.
- **Dismiss**: toast hides on Start Fresh, on resume, and on closeReader.
- **Animation**: slide-up keyframe animation for toast appearance.

### Acceptance criteria

1. Open a book previously read to 50% → toast appears "Resume reading at 50%?"
2. Click Resume → navigates to saved position.
3. Click Start fresh → starts from beginning.
4. Open a new unread book → no toast.
5. Close reader → toast is dismissed.

---

## BL-026 — Format-specific reader settings panels

- **Priority:** Medium
- **Status:** implemented + deployed 2026-08-23
- **Reported:** 2026-08-23

### Symptom

Reader settings are scattered across the toolbar as individual controls.
No single place to see and adjust all settings for the current format.

### Implemented

- **Gear button** in the toolbar opens a dropdown panel with all reader
  settings consolidated in one place.
- **Format-aware**: EPUB-only rows (font family, size, spacing, justify,
  hyphenation, content width) show only for EPUB. PDF/CBZ show only theme.
- **Syncs with toolbar controls**: dropdown state is read from the same
  underlying variables as the inline toolbar controls.
- **Toggle highlight**: gear button turns blue when panel is open.
- Panel auto-closes on reader close.

### Acceptance criteria

1. Gear button appears in toolbar for all formats.
2. Click gear → dropdown shows all settings.
3. EPUB-specific settings (font/justify/hyphen/width) only visible for EPUB.
4. Changing a setting in the dropdown updates the reader immediately.
5. Changing a setting in the toolbar updates the dropdown when reopened.

---

## BL-027 — Mobile/responsive improvements

- **Priority:** Medium
- **Status:** implemented + deployed 2026-08-23
- **Reported:** 2026-08-23

### Symptom

Reader toolbar buttons too small on mobile. Glass footer scrubber hard to
touch. Settings dropdown overflows. Inline font controls crowd the toolbar
on small screens.

### Implemented

- Larger touch targets for toolbar buttons (min 36px height, larger padding).
- Glass footer scrubber thumb enlarged on mobile (20px).
- Settings dropdown goes full-width on mobile (left/right aligned).
- Inline font controls hidden on mobile; use settings gear panel instead.
- Resume toast width constrained for mobile.
- Chapter nav chevrons enlarged for touch.

---

## BL-028 — Keyboard shortcuts modal + Home/End

- **Priority:** Low
- **Status:** implemented + deployed 2026-08-23
- **Reported:** 2026-08-23

### Symptom

No keyboard shortcuts reference. Home/End keys don't jump to start/end of book.

### Implemented

- **? key** opens a modal listing all keyboard shortcuts.
- **Home** jumps to start of book (EPUB: spine 0, PDF: page 1, CBZ: image 0).
- **End** jumps to end of book (last spine/page/image).
- Modal closes on click outside or Close button.

---

## BL-029 — Bookmark ribbon (animated visual indicator)

- **Priority:** Low
- **Status:** implemented + deployed 2026-08-23
- **Reported:** 2026-08-23

### Symptom

Bookmark saved silently with no visual feedback. User doesn't know if the
action succeeded.

### Implemented

- Yellow ribbon indicator appears at top-right when bookmark is saved.
- Slide-down animation (1.8s): slides in, stays visible, slides out.
- Re-triggers cleanly on rapid bookmarks (class reflow trick).
- Automatically disappears — no user interaction needed.

---

## BL-030 — Reading analytics (time tracking)

- **Priority:** Low
- **Status:** implemented + deployed 2026-08-23
- **Reported:** 2026-08-23

### Symptom

No tracking of how much time is spent reading each book. No reading
statistics visible to the user.

### Implemented

- **Session timer**: starts when reader opens, pauses on tab hide,
  resumes on tab show, stops on reader close. Accumulates across multiple
  page views within a session.
- **Persistent total**: reading time per book saved to localStorage
  (`reader.readTime.<bookId>`) on every pause/stop.
- **Live display**: MM:SS counter shown in the glass footer (both normal
  and fullscreen). Updates every 5 seconds.
- **Cumulative**: reopening a book shows the accumulated total from the
  start, including previous sessions.
- **Helper**: `_getReadingTime(bookId)` and `_formatReadingTime(ms)` for
  future dashboard use.

---

## BL-031 — Fullscreen reader: buttons unresponsive + prompt modal invisible

- **Priority:** High
- **Status:** implemented + deployed 2026-08-23
- **Reported:** 2026-08-23

### Symptom

In fullscreen mode:
1. All buttons in the normal reader toolbar (bookmark, note, annotations,
   settings, etc.) are unresponsive — clicking does nothing.
2. The prompt modal (for adding bookmarks and notes) does not appear.
3. Exiting the reader or refreshing the page always returns to the Library
   tab instead of the previously active view.

### Root causes

1. **Buttons blocked:** The `fs-center-tap` overlay (z-index 498) covers the
   entire viewport except 24px edges. The normal `#readerToolbar` had no
   z-index, so all clicks hit the center-tap instead of the buttons.
2. **Prompt modal invisible:** `showPromptModal()` appended the overlay to
   `document.body`, which is outside the fullscreen element
   (`.reader-layout`). Elements outside the fullscreen top layer are not
   rendered.
3. **No tab persistence:** `closeReader()` hardcoded
   `switchTab("library")`. No tab state was saved to localStorage.

### Where

`templates/index.html`:
- CSS: `.fs-center-tap` z-index 498 (line ~337).
- CSS: `#readerToolbar` — added `position: relative; z-index: 500` in
  fullscreen context (line ~340).
- JS: `showPromptModal()` — changed `document.body.appendChild(overlay)`
  to `document.fullscreenElement || document.documentElement` (line ~1257).
- JS: `showPromptModal()` — added `e.stopPropagation()` on Escape for
  both input and overlay keydown handlers (lines ~1267, ~1269).
- JS: `switchTab()` — added `_previousTab` tracking and
  `localStorage.setItem("app.activeTab", ...)` persistence (line ~1300+).
- JS: `checkAuth()` — added `_authTabRestored` flag and localStorage
  restore on first successful auth (line ~1438+).
- JS: `closeReader()` — changed `switchTab("library")` to
  `switchTab(_previousTab || "library")` (line ~5565).
- HTML: `readerFsToolbar` — added bookmark (📖), note (✏), and
  annotations (📝) buttons (line ~833).

### Acceptance criteria

1. In fullscreen, all toolbar buttons (bookmark, note, annotations,
   settings) respond to clicks.
2. Adding a bookmark or note via the prompt modal works in fullscreen.
3. Pressing Escape closes the prompt without also exiting fullscreen.
4. Exiting the reader returns to the previously active tab (not always
   Library).
5. Refreshing the page restores the previously active tab.
6. The fullscreen toolbar also has bookmark/note/annotations buttons for
   quick access.
