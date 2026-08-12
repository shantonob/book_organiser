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

### Fix implemented (2026-08-12)

- Added `_refreshReaderScroll()`: toggles the scroll container's `overflow-y`
  and reads `scrollHeight` to force the browser to recompute scroll metrics
  after a canvas resize; preserves scroll position.
- `_applyReaderZoom()` now calls `_refreshReaderScroll()` after resizing.
- `loadComicReader()` set `#readerArea.style.overflowY = "hidden"`, which
  removed the scrollbar entirely for zoomed comics — changed to `"auto"`.
- Verified in a side chat's planning pass and by JS syntax check
  (`node --check` on both inline `<script>` blocks).

---

## BL-002 — (placeholder)

Template for the next item.
