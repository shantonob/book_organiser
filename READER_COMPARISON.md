# Reader UI Comparison: Book Organiser vs BookOrbit

## Implementation Summary (BL-020 → BL-030)

All 11 items implemented and deployed 2026-08-23:

| Item | Feature | Status |
|------|---------|--------|
| BL-020 | Chrome auto-hide (edge-zone triggers, tap-to-pin, panel-open lock) | Done |
| BL-021 | Persistent reader settings (per-format + per-book cascade) | Done |
| BL-022 | Glass footer scrubber (chapter ticks, page-jump, chapter nav) | Done |
| BL-023 | Expanded themes & typography (8 themes, font family, justify, hyphen, content width) | Done |
| BL-024 | Selection popup actions (Copy + Translate + Define + Search) | Done |
| BL-025 | Resume toast on book open | Done |
| BL-026 | Format-specific reader settings panel (gear dropdown) | Done |
| BL-027 | Mobile/responsive improvements | Done |
| BL-028 | Keyboard shortcuts modal + Home/End | Done |
| BL-029 | Bookmark ribbon (animated visual indicator) | Done |
| BL-030 | Reading analytics (time tracking) | Done |

## Major Design Gaps

### 1. Chrome Auto-Hide (immersion) — CRITICAL
**BookOrbit:** 24px edge trigger zones at top/bottom reveal header/footer. 3s auto-hide timer. Middle-tap pins chrome (stays visible until tapped again). Opening settings panel locks chrome visible. Escape cascade closes panels in priority order (search → sidebar → settings → toggle pin).
**BookOrganiser:** Mousemove anywhere triggers the floating fullscreen toolbar. 2.6s auto-hide. No middle-tap-to-pin. Sidebars revealed by hovering a 12px hotzone on left/right edge. No panel-open lock.
**Gap:** BookOrganiser's global mousemove trigger is too sensitive (toolbar flickers during reading). No tap-to-pin on touch. No panel-open lock.

### 2. Reader Settings Cascade — HIGH
**BookOrbit:** Three-layer cascade: built-in defaults → per-format defaults saved in Settings → per-book delta captured while reading. Explicit "overrideBookFormatting" opt-out preserves publisher embedded fonts/layout. Changing settings reopens the book at the same spot.
**BookOrganiser:** Per-session only. No per-format defaults. No per-book memory. No publisher formatting opt-out. Settings reset on reader close.
**Gap:** No persistent settings. Users must reconfigure font/zoom/theme every time they open a book.

### 3. Theme & Typography — HIGH
**BookOrbit:** 13 page themes (Default, Gray, Sepia, Crimson, Meadow, Rosewood, Azure, Dawnlight, Ember, Aurora, Ocean, Mist, AMOLED). Typography: serif/sans-serif/monospace/Georgia/Palatino + user-uploaded custom fonts. Font size 10–32px. Line height 0.8–3.0. Justify toggle. Hyphenation toggle. Weight/style setters. Max content width 400–1600px. Column gap 0–50% padding.
**BookOrganiser:** 4 themes (Dark, Light, Sepia, Night). Font size via epub.js defaults. Line height dropdown (4 options). No custom fonts, no justify toggle, no hyphenation, no content width, no column gap.
**Gap:** 4 themes vs 13. No custom fonts. No typography fine-tuning.

### 4. Footer / Progress Scrubber — HIGH
**BookOrbit:** 40px glass bar (blurred) with: prev/next-chapter chevrons flanking a custom range slider. Chapter-progress highlight segment (25%-opacity primary tint). Thin tick marks at every section boundary. Gradient fill tracks current fraction. Click percentage chip → input accepts `42` (%), `42%`, or `p123` (page number). Cycleable footer modes (locations vs percentage) persisted per book.
**BookOrganiser:** Thin progress bar + page number text. No chapter ticks. No scrubber. No page-jump input. No footer mode cycling.
**Gap:** No interactive scrubber. No page-jump. No chapter awareness in progress display.

### 5. Annotation / Highlight Flow — HIGH
**BookOrbit:** Text selection → SelectionPopup with actions: Copy · Highlight · Search · Translate · Define · Note · Delete (if overlapping existing). Styles: highlight, underline, strikethrough, squiggly, inverted. Multiple colors. CFI-anchored. Tapping existing highlight re-opens popup. Cross-book Annotations hub with stat counts, search, filters (book/color/style/source), sort (date/book), export (Markdown/CSV/JSON). Per-book Highlights tab with chapter grouping, bulk actions.
**BookOrganiser:** Text selection → color picker popup with note input. Highlight only (no underline/strikethrough/squiggly/inverted). 7 colors. CFI/bbox anchored. Cross-book export (Markdown only). No search, no filters, no source badges, no bulk actions.
**Gap:** No style variety. No translate/define/search from selection. No cross-book annotation hub with filters. No CSV/JSON export.

### 6. Resume Toast — MEDIUM
**BookOrbit:** Reopening a book shows "Resumed at N% — {chapter}" toast for 2.5s.
**BookOrganiser:** Silent resume. No feedback.
**Gap:** User doesn't know where they left off without checking the progress bar.

### 7. Dedicated Format Readers — MEDIUM
**BookOrbit:** Four specialized readers: eBook (paginated vs scrolled, 1–4 columns, fixed-layout spread), PDF (scroll mode, spread None/Odd/Even, fit Page/Width/Custom 25–400%), Comics (Paginated/Infinite/Long-strip, single vs two-page, fit Page/Width/Height/Actual, L→R vs R→L, canvas background color), Audiobook (speed 0.75–2x, volume, skip 5–60s). Each has its own settings panel.
**BookOrganiser:** One unified reader with format-specific controls toggled by visibility. No columns. No infinite/long-strip comic mode. No audiobook support. No PDF scroll mode options.
**Gap:** No format-specific reader views. Limited comic modes. No audiobook.

### 8. Mobile / Responsive — MEDIUM
**BookOrbit:** Platform-adaptive overlays (TranslationPopover on desktop, TranslationSheet on touch). Touch detection via `'ontouchstart' in window || navigator.maxTouchPoints > 0`. Responsive footer (h-10 sm:h-11). Desktop: thumbnail click opens directly. Touch: first tap reveals overlay, second acts. Two-page-on-small-screens override for comics.
**BookOrganiser:** Single `@media (max-width: 768px)` breakpoint. Sidebars stack vertically. Collapse buttons hidden. No touch-specific overlays. No platform-adaptive components.
**Gap:** Minimal responsive handling. No touch-specific UI adaptations.

### 9. Keyboard Shortcuts Modal — LOW
**BookOrbit:** `?` key opens KeyboardShortcutsModal showing all shortcuts. `T` sidebar, `S` search, `B` bookmark, `F` fullscreen, `M` cycle footer, `Home/End` jump to start/end.
**BookOrganiser:** Arrow keys + Space only. No shortcuts modal. No Home/End. No single-key shortcuts (suppressed by typing in inputs).
**Gap:** Very limited keyboard navigation. No discoverable shortcut reference.

### 10. Bookmark Ribbon — LOW
**BookOrbit:** Animated ribbon bookmark drops from top-left of content area (clip-path shape, primary-colored, 200ms fade).
**BookOrganiser:** Plain button in toolbar.
**Gap:** No visual bookmark indicator on the reading area.

### 11. Reading Analytics — LOW (for reading experience)
**BookOrbit:** Daily reading time, heatmaps, streaks, goals, achievements. Reading DNA profiling. Continue Reading widget with progress bars.
**BookOrganiser:** Basic last-opened timestamp. No reading time tracking, no streaks, no goals.
**Gap:** No reading statistics or engagement features.

---

## Test Cases: Reading Experience

### TC-01: EPUB Basic Navigation (Laptop)
**Objective:** Verify EPUB reader opens and navigates correctly with keyboard and mouse.
**Steps:**
1. Open a book from the Library (EPUB format)
2. Verify the book title and format appear in the toolbar
3. Press Arrow Right to advance to the next page
4. Press Arrow Left to go back
5. Press Space to advance one page
6. Press Arrow Down to scroll down (scrolled mode)
7. Click the ← and → buttons in the toolbar
8. Verify progress bar updates with each navigation
**Expected:** All navigation methods work. Progress bar advances. No visual glitches.

### TC-02: EPUB Theme Switching (Laptop)
**Objective:** Verify all four themes render correctly and persist.
**Steps:**
1. Open an EPUB book
2. Switch theme to Light via the dropdown
3. Verify background changes to white, text to dark
4. Switch to Sepia — verify warm background
5. Switch to Night — verify very dark background
6. Switch back to Dark — verify default slate background
7. Close the reader and reopen the same book
8. Verify theme persists from the previous session
**Expected:** All 4 themes apply instantly. Theme persists across sessions.

### TC-03: EPUB Font Size & Line Height (Laptop)
**Objective:** Verify typography controls work and text reflows.
**Steps:**
1. Open an EPUB book
2. Click A+ 3 times — verify font grows each time
3. Verify the percentage display updates (130%)
4. Click A− 2 times — verify font shrinks
5. Change line height dropdown to "Loose"
6. Verify text spacing increases
7. Change line height to "Compact"
8. Verify text spacing decreases
**Expected:** Font size and line height adjust smoothly. Text reflows without overlap.

### TC-04: EPUB In-Book Search (Laptop)
**Objective:** Find text within an EPUB and navigate to results.
**Steps:**
1. Open an EPUB book
2. Click the search icon (🔍) or press a keyboard shortcut
3. Type a word that appears in the book (e.g., "chapter")
4. Press Enter to search
5. Verify results appear with context snippets
6. Click a result — verify reader jumps to that location
7. Verify the search highlight appears briefly
**Expected:** Search finds matches across all spine items. Click navigates correctly.

### TC-05: PDF Page Navigation & Zoom (Laptop)
**Objective:** Verify PDF reader handles page turning and zoom.
**Steps:**
1. Open a PDF book
2. Navigate pages with Arrow Right/Left
3. Verify page number display updates (e.g., "3 / 24")
4. Zoom in with Ctrl+scroll wheel
5. Verify zoom percentage display updates
6. Click zoom reset button (↻) — verify 100% restored
7. Verify the PDF renders clearly at 150% zoom
8. Navigate to last page and verify no crash
**Expected:** PDF pages render correctly. Zoom is smooth. Page counter accurate.

### TC-06: PDF Two-Page Spread (Laptop)
**Objective:** Verify two-page mode displays pages side by side.
**Steps:**
1. Open a PDF book
2. Click the two-page toggle button (☯)
3. Verify two pages appear side by side
4. Navigate forward — verify both pages advance
5. Toggle off — verify single page returns
6. Verify page numbers are correct in both modes
**Expected:** Two-page mode renders correctly. Navigation works in both modes.

### TC-07: CBZ Comic Reader (Laptop)
**Objective:** Verify comic reader handles page images and navigation.
**Steps:**
1. Open a CBZ book
2. Verify the first comic page renders as an image
3. Navigate pages with Arrow Right/Left
4. Verify page thumbnails strip shows below the toolbar
5. Click a thumbnail — verify jump to that page
6. Verify page counter shows "Page X / Y"
7. Test RTL toggle (⇄) — verify page order reverses
**Expected:** Comic pages render correctly. Thumbnails load. RTL works.

### TC-08: CBZ Drawing Overlay (Laptop)
**Objective:** Verify drawing mode works on comics.
**Steps:**
1. Open a CBZ book
2. Click the pencil button (✎) to enter drawing mode
3. Draw a line on the page with the mouse
4. Verify the drawing appears in the selected color
5. Change the color using the color picker
6. Draw another line — verify new color
7. Change pen size to "Thick" — draw a thick line
8. Click the clear button (🧹) — verify drawing is removed
9. Draw something, navigate to next page, navigate back
10. Verify the drawing persists
**Expected:** Drawing works with correct color/size. Persists per page. Clear works.

### TC-09: Fullscreen Mode (Laptop)
**Objective:** Verify immersive fullscreen with zero chrome and toolbar reveal.
**Steps:**
1. Open any book
2. Click the fullscreen button (⛶)
3. Verify the screen goes fullscreen with ONLY the reading content visible
4. Verify no toolbar, buttons, or sidebars are visible
5. Move the mouse — verify the floating toolbar appears
6. Wait 3 seconds — verify toolbar auto-hides
7. Hover left edge — verify reading list sidebar slides in
8. Move mouse away from sidebar — verify it hides
9. Hover right edge — verify annotations sidebar slides in
10. Press ESC — verify fullscreen exits, reader stays open
**Expected:** Zero chrome. Toolbar auto-hides. Sidebars reveal on edge hover. ESC exits fullscreen only.

### TC-10: Fullscreen Sidebars & Pin (Laptop)
**Objective:** Verify sidebar pinning in fullscreen mode.
**Steps:**
1. Enter fullscreen on a book
2. Hover left edge — reading list sidebar appears
3. Click the sidebar toggle button in the floating toolbar
4. Verify sidebar stays visible (pinned)
5. Hover right edge — annotations sidebar appears
6. Click annotations toggle — verify it pins
7. Verify both sidebars visible simultaneously
8. Click toggle again to unpin — verify sidebar hides when mouse moves away
**Expected:** Pin/unpin works for both sidebars. Both can be visible at once.

### TC-11: Annotations — Create & View (Laptop)
**Objective:** Create highlights and notes, verify they appear in the sidebar.
**Steps:**
1. Open an EPUB book
2. Select a passage of text with the mouse
3. Verify the highlight popup appears
4. Choose a color (e.g., green) and add a note ("Important point")
5. Save — verify the highlighted text appears with a green background
6. Open the annotations sidebar (📝)
7. Verify the highlight appears in the sidebar with text, note, and date
8. Click the highlight in the sidebar — verify it navigates to the passage
9. Add a page note via the ✏ button — verify it appears in Notes tab
**Expected:** Highlights and notes create correctly. Sidebar shows them. Navigation works.

### TC-12: Annotations — Edit & Delete (Laptop)
**Objective:** Edit annotation notes and delete annotations.
**Steps:**
1. Open a book with existing annotations
2. Open the annotations sidebar
3. Click the edit icon on a note — verify inline editing
4. Change the note text and save
5. Verify the updated note appears
6. Click the × delete button on an annotation
7. Confirm deletion — verify the annotation is removed
8. Verify the annotation count updates
**Expected:** Edit and delete work correctly. Count updates.

### TC-13: Bookmarks — Create & Navigate (Laptop)
**Objective:** Create bookmarks and navigate to them.
**Steps:**
1. Open a book and navigate to a page
2. Click the bookmark button (🔖) in the toolbar
3. Verify the bookmark is saved (button state changes)
4. Navigate to a different page
5. Open the reading list sidebar → Bookmarks tab
6. Verify the bookmark appears with page info
7. Click the bookmark — verify navigation to bookmarked position
8. Create a second bookmark at another location
9. Verify both bookmarks appear in the list
**Expected:** Bookmarks save with position. Navigation works. Multiple bookmarks supported.

### TC-14: Bookmark Auto-Save on Close (Laptop)
**Objective:** Verify auto-bookmark when closing with reading progress.
**Steps:**
1. Open a book and read past 5% progress
2. Navigate to a page far from any existing bookmark
3. Close the reader (✕ button)
4. Reopen the same book
5. Verify the book resumes from the last position
6. Check bookmarks — verify an auto-bookmark was created
**Expected:** Auto-bookmark created within 3% of close position. Resume works.

### TC-15: TOC Navigation (Laptop)
**Objective:** Open and use the table of contents.
**Steps:**
1. Open an EPUB book
2. Open the reading list sidebar
3. Verify the "Contents" section shows chapter titles
4. Click a chapter — verify reader navigates to that chapter
5. Verify the active chapter is highlighted in the TOC
6. Navigate to a different chapter — verify the highlight updates
7. Test with a PDF — verify TOC loads from PDF outline (if present)
**Expected:** TOC renders correctly. Navigation works. Active chapter tracked.

### TC-16: Progress Tracking Persistence (Laptop)
**Objective:** Verify reading position saves and restores.
**Steps:**
1. Open a book and read to approximately 30%
2. Close the reader
3. Wait 3 seconds (for server save)
4. Reopen the same book
5. Verify it resumes at approximately 30%
6. Read to 60%, close, reopen
7. Verify resume at 60%
8. Verify the progress bar in the Library tab reflects the reading progress
**Expected:** Position persists across sessions. Library shows progress.

### TC-17: iPad Portrait — Touch Navigation (iPad)
**Objective:** Verify touch-based reading on iPad (portrait).
**Steps:**
1. Open an EPUB book in Safari on iPad
2. Swipe left to turn page forward
3. Swipe right to turn page backward
4. Pinch-to-zoom to increase page size
5. Verify zoom percentage updates
6. Double-tap center — verify toolbar toggles
7. Open annotations sidebar — verify it stacks below (responsive)
8. Create a highlight by selecting text — verify popup appears at correct position
**Expected:** Touch navigation smooth. Zoom works. Responsive layout correct.

### TC-18: iPad Landscape — Two-Page & Fullscreen (iPad)
**Objective:** Verify two-page mode and fullscreen on iPad landscape.
**Steps:**
1. Rotate iPad to landscape
2. Open a PDF book
3. Toggle two-page mode — verify pages side by side
4. Enter fullscreen — verify immersive mode
5. Tap center to reveal toolbar
6. Wait 3s — verify auto-hide
7. Swipe from left edge — verify sidebar slides in
8. Exit fullscreen — verify normal view returns
**Expected:** Two-page works in landscape. Fullscreen immersive. Touch reveals work.

### TC-19: Mobile — Reading on Phone (Mobile)
**Objective:** Verify the reader works on a small phone screen.
**Steps:**
1. Open a book on a phone (375px width)
2. Verify the toolbar wraps correctly (no overflow)
3. Swipe left/right to navigate
4. Verify the reading content fills the screen width
5. Open annotations sidebar — verify it stacks vertically
6. Create a highlight — verify popup doesn't overflow screen
7. Enter fullscreen — verify toolbar fits on small screen
8. Verify text is readable at default zoom
**Expected:** No horizontal scroll. Touch targets large enough. Text readable.

### TC-20: Cross-Format Consistency (Laptop)
**Objective:** Verify consistent behavior across EPUB, PDF, and CBZ readers.
**Steps:**
1. Open an EPUB — note the toolbar layout and button positions
2. Close and open a PDF — verify same toolbar layout
3. Close and open a CBZ — verify same toolbar layout
4. Verify the close button (✕) works identically in all three
5. Verify theme switching works in all three
6. Verify fullscreen entry/exit works in all three
7. Verify keyboard navigation (Arrow keys) works in all three
8. Verify progress tracking works in all three
9. Create a highlight in EPUB, bookmark in PDF, and drawing in CBZ
10. Verify each feature persists independently
**Expected:** Consistent UI and behavior across formats. No format-specific regressions.
