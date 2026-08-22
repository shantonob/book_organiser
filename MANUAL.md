# Book Organiser — User Manual

A Flask-based single-page web application for cataloging, deduplicating, and organizing ebooks on a headless server (Raspberry Pi). Accessible via any browser; supports OPDS for e-reader devices.

---

## Table of Contents

- [1. Library](#1-library)
  - [1.1 Search & Filter](#11-search--filter)
  - [1.2 Table View vs Gallery View](#12-table-view-vs-gallery-view)
  - [1.3 Bulk Actions](#13-bulk-actions)
  - [1.4 Saved Searches](#14-saved-searches)
  - [1.5 Detail Panel](#15-detail-panel)
  - [1.6 Editing a Book](#16-editing-a-book)
  - [1.7 Downloading & Format Conversion](#17-downloading--format-conversion)
  - [1.8 Cover Management](#18-cover-management)
  - [1.9 Reading Online](#19-reading-online)
  - [1.10 Annotations & Bookmarks](#110-annotations--bookmarks)
  - [1.11 Tags & Classification](#111-tags--classification)
- [2. Pipeline](#2-pipeline)
  - [2.1 What the Pipeline Does](#21-what-the-pipeline-does)
  - [2.2 Running the Pipeline](#22-running-the-pipeline)
  - [2.3 Pipeline Phases](#23-pipeline-phases)
  - [2.4 Quarantine](#24-quarantine)
- [3. Reader](#3-reader)
  - [3.1 Supported Formats](#31-supported-formats)
  - [3.2 Navigation](#32-navigation)
  - [3.3 Themes & Typography](#33-themes--typography)
  - [3.4 Two-Page / Spread View](#34-two-page--spread-view)
  - [3.5 In-Book Search](#35-in-book-search)
  - [3.6 Fullscreen Mode](#36-fullscreen-mode)
  - [3.7 Drawing Overlay](#37-drawing-overlay)
  - [3.8 Progress Tracking](#38-progress-tracking)
- [4. Reading List](#4-reading-list)
- [5. Settings](#5-settings)
  - [5.1 Library Integrity Audit](#51-library-integrity-audit)
  - [5.2 Configuration](#52-configuration)
  - [5.3 Backups](#53-backups)
  - [5.4 Excel Export](#54-excel-export)
- [6. OPDS Catalog](#6-opds-catalog)
- [7. UDC Classification](#7-udc-classification)
- [8. Keyboard Shortcuts](#8-keyboard-shortcuts)
- [9. API Reference](#9-api-reference)
- [10. CLI Options](#10-cli-options)

---

## 1. Library

The Library tab is the primary interface for browsing, searching, and managing your book collection. It occupies the full screen when active and provides two viewing modes, a sidebar for browsing by classification, and a detail panel for inspecting individual books.

### 1.1 Search & Filter

The search bar at the top of the Library tab accepts free-text queries against the full-text search index (SQLite FTS5). Enter a title, author name, ISBN, or any keyword to search across all metadata fields.

**Advanced Filters:**

Below the search bar, expandable filter controls let you narrow results:

| Filter | Description |
|--------|-------------|
| **Stage** | Filter by pipeline stage: Arrived, Extracted, Cleaned, Cataloged, Survivor, Skipped, Copied, Quarantined |
| **UDC** | Filter by Universal Decimal Classification code (e.g. `800` for Literature, `006` for AI) |
| **Format** | Filter by file type: epub, pdf, cbz, cbr, mobi, azw3, fb2, djvu |
| **Year range** | Min/max publication year |
| **Size range** | Min/max file size in MB |
| **Series** | Filter by series name |
| **Source** | Filter by source directory |
| **Masters only** | Show only non-duplicate master copies |
| **Untagged** | Show only books with no custom tags |
| **Duplicates only** | Show only duplicate entries |
| **Archive only** | Show only archived (quarantined) books |

**Sort Options:**

Results can be sorted by title, author, year, size, format, UDC code, stage, created date, or updated date — ascending or descending.

### 1.2 Table View vs Gallery View

Toggle between two display modes using the view-switch buttons:

- **Table View** — Rows showing ID, cover thumbnail, title, author, UDC, format, and stage. Click a row to select it and open the detail panel. Columns are sortable.
- **Gallery View** — Cover image grid (auto-sized). Click a cover to open the detail panel. Hover shows title tooltip.

Both views share the same search results and pagination. Page size can be set to 50, 100, or 200 items per page via the dropdown.

### 1.3 Bulk Actions

Select books using the checkboxes in table view (or the "Select All" checkbox in the header). The bulk toolbar appears above the table with these actions:

| Action | Description |
|--------|-------------|
| **+ Add Tag** | Add a custom tag to all selected books |
| **- Remove Tag** | Remove a custom tag from all selected books |
| **Re-classify UDC** | Apply a UDC classification code to all selected books |
| **Fetch Metadata** | Re-run online metadata enrichment (Open Library + Google Books) for selected books. Never overwrites existing fields — only fills empty ones. Downloads missing covers. Capped at 200 per request. |
| **Convert as...** | Convert selected books to another format (epub, azw3, mobi, pdf, fb2, txt, docx, rtf, htmlz) using calibre's ebook-convert. Optionally specify a device output profile (kindle, kobo, tablet). Runs in the background; download each from its detail panel when ready. |
| **Delete** | Permanently delete selected books (files and database entries) |

### 1.4 Saved Searches

Save any combination of filters for quick re-use:

1. Set your desired filters in the Library tab.
2. Click "Save Search" and give it a name.
3. The saved search appears in the **Saved Searches** sidebar panel.
4. Click any saved search to instantly apply those filters.
5. Delete saved searches via the X button.

### 1.5 Detail Panel

Click any book in the table or gallery to open the detail panel on the right side. It displays:

**Metadata fields:**
- Cover image
- UUID, Title, Author, Series, Series #, Volume, Issue
- Year, UDC code + label, Format, File size
- Publisher, ISBN, Language, Pages
- Description (up to 500 characters)
- Source path, Pipeline stage, Stage errors
- Master/Duplicate status
- Enrichment source badge

**Tags:**
- UDC Tags — automatically assigned by the classifier
- Custom Tags — user-defined; add via the "+" button, remove via X

**Pipeline History** — Log of all pipeline operations on this book (extraction, dedup, enrich, copy, etc.)

### 1.6 Editing a Book

Click the **Edit** button in the detail panel to open an inline editor. Editable fields:

- Title, Author, Publisher, ISBN, Language, Pages, Year
- Description (multi-line)
- Series name, Series number, Volume, Issue
- UDC code (auto-fills label)
- Add custom tags

Click **Save** to persist changes. The FTS index is rebuilt automatically.

### 1.7 Downloading & Format Conversion

**Download Original:**
Click **Download** in the detail panel to download the book in its original format.

**Download As (Format Conversion):**
Click **Download as...** to convert and download in a different format:

1. Choose an output format: epub, azw3, mobi, pdf, fb2, txt, docx, rtf, htmlz
2. Optionally specify a device profile: kindle, kobo, tablet (affects layout/optimization)
3. The conversion runs in the background (uses calibre's ebook-convert)
4. Once ready, the browser downloads the converted file

Supported conversion directions (via calibre):
- Any format → any other format
- AZW3/MOBI/FB2 → EPUB (also available via pure-stdlib fallback without calibre)

### 1.8 Cover Management

**Auto-extraction:**
- EPUB: Cover extracted from the first image in the archive
- CBZ/CBR: First page image used as cover (WebP extraction)
- PDF: First page rendered as cover thumbnail

**Manual replacement:**
Click **Replace Cover** in the detail panel, then select an image file (any format). The image is stored in the covers directory and displayed throughout the app.

**Online covers:**
The enrich metadata function (per-book or bulk) downloads covers from Open Library or Google Books when the book has none.

### 1.9 Reading Online

Click **Read Online** in the detail panel to open the book in the browser reader. Supported formats and their capabilities:

| Format | Reader | Key Features |
|--------|--------|-------------|
| EPUB | epub.js | Full-text search, TOC, highlights, bookmarks, annotations, themes, zoom, two-page mode |
| AZW3/MOBI/FB2 | Auto-converted to EPUB | One-time conversion cached; then full EPUB features |
| PDF | PDF.js | Page navigation, zoom, highlights, bookmarks, TOC (if embedded), two-page mode |
| DJVU | Converted to PDF (ddjvu/calibre) | Then full PDF features |
| CBZ | Image page extraction | Page navigation, thumbnails, zoom, drawing overlay, RTL/manga mode |
| CBR | Download only | No RAR extraction in the container; use Download instead |

The reader opens in a dedicated tab (not an overlay). Use the toolbar buttons or keyboard shortcuts to navigate. Reader state (position, zoom, theme) is saved automatically.

### 1.10 Annotations & Bookmarks

**Highlights:**
- Select text (EPUB/PDF) or drag to select a region (PDF/CBZ) to trigger the highlight popup
- Choose from 7 colors: Yellow, Green, Blue, Red, Purple, Orange, White
- Add an optional note to each highlight
- Highlights are anchored to content (EPUB: CFI; PDF/CBZ: page + coordinates)
- Export all highlights to Markdown via the timeline view

**Notes (Zettelkasten):**
- Add notes with a title, body text, and tags
- Each note gets a unique ZID (e.g., `abc123-def456`)
- Link notes to each other using wiki-style `[[zid]]` syntax with autocomplete
- Notes are anchored to the current reader position
- Backlinks are displayed on notes that are referenced by others

**Bookmarks:**
- Click the bookmark button to save the current position with an optional label
- Bookmarks are auto-created on reader close if reading progress exceeds 5% and no nearby bookmark exists
- Click any bookmark in the timeline to jump to that position

**Timeline View:**
The right-side panel in the reader shows three tabs: Notes, Highlights, and Bookmarks. Use the text filter to search across all items. Click any item to navigate to its location.

### 1.11 Tags & Classification

**UDC Tags (Automatic):**
The classifier automatically assigns Universal Decimal Classification codes based on title, author, subjects, and description. See [Section 7: UDC Classification](#7-udc-classification) for details.

**Custom Tags (Manual):**
User-defined tags for any purpose (e.g., "to-read", "reference", "favorite"). Add via:
- The detail panel's tag section
- Bulk tag action from the Library tab
- Edit mode

Remove tags by clicking the X on any tag badge.

---

## 2. Pipeline

### 2.1 What the Pipeline Does

The pipeline is the automated processing engine that takes raw ebook files from source directories and turns them into a cataloged, deduplicated library. It runs as a background process with real-time progress display.

### 2.2 Running the Pipeline

- **Run Pipeline** button: Runs the full metadata + dedup + copy pipeline
- **Run Metadata** button: Runs only the metadata extraction and enrichment phases
- **Run Dedup** button: Runs only the deduplication phases
- **Run Copy** button: Copies survivors to the flat output directory
- **Run Enrich** button: Refreshes metadata for books missing cover/description/title
- **Refresh Status** button: Updates the status display without running anything

The pipeline uses a PID-based lock file to prevent concurrent runs. If another instance is already running, the start request is rejected.

### 2.3 Pipeline Phases

**Phase A — Metadata Pipeline:**

1. **Discover**: Walk source directories, find ebook files (.epub, .pdf, .cbz, .cbr, .mobi, .azw3, .fb2, .djvu)
2. **Arrive**: Create database record, compute file hash, set stage to "arrived"
3. **Extract**: Read embedded metadata (title, author, ISBN, description, subjects) from the file
4. **Hash Dedup**: Skip if a file with the same hash already exists
5. **Title Dedup**: Skip if a book with the same title already exists
6. **Clean**: Clean filename, extract year, enrich from filename if metadata is sparse
7. **Enrich**: Query Open Library + Google Books for missing fields (title, author, description, ISBN, publisher, cover)
8. **Cover**: Download cover from online API if no embedded cover exists
9. **Classify**: Assign UDC classification based on content analysis
10. **Catalog**: Set stage to "cataloged"

**Phase B — Deduplication:**

1. **Hash Dedup**: Group by file hash, mark all but the richest copy as duplicate
2. **ISBN Dedup**: Group by normalized ISBN, mark duplicates
3. **Title Fuzzy Dedup**: Within same UDC group, compare normalized titles using token-Jaccard + SequenceMatcher similarity (threshold: 0.95); requires same author
4. **Author+Year+Title Dedup**: Match on same author + year + similar title
5. **Survivor Marking**: Remaining non-duplicate files are marked as "survivors"

**Phase C — Copy:**

Copies survivor files to the flat output directory (`/books/processed/`) with cleaned filenames. Updates stage to "copied".

**Phase D — Enrich (Optional):**

Targets books missing cover, description, or title. Queries Open Library + Google Books. Downloads missing cover images. Configurable limit (default 500 books per run).

### 2.4 Quarantine

Books that fail extraction or have no usable metadata are quarantined with a reason code:

| Code | Meaning |
|------|---------|
| `EXTRACT_FAIL` | Metadata extraction failed (corrupt or unsupported file) |
| `NO_METADATA_EMPTY` | No title or author found after extraction and filename parsing |

Quarantined books can be:
- **Resolved & Re-processed**: Re-runs the extraction pipeline from the beginning
- **Dismissed**: Marks as reviewed without re-processing

---

## 3. Reader

Open any book via **Read Online** in the detail panel. The reader opens in a dedicated tab (not an overlay) with a toolbar at the top, the reading area in the center, and optional sidebars for the reading list (left) and annotations/notes (right).

### 3.1 Supported Formats

| Format | Reader Engine | Conversion | Key Features |
|--------|---------------|------------|-------------|
| EPUB | epub.js (scrolled-doc) | None | Full support: TOC, search, highlights, bookmarks, notes, themes, zoom, two-page mode |
| AZW3 | Auto-converted to EPUB | One-time (calibre or pure-stdlib fallback); cached to `cache/converted/` | Then full EPUB features |
| MOBI | Auto-converted to EPUB | One-time; cached | Then full EPUB features |
| FB2 | Auto-converted to EPUB | One-time; cached | Then full EPUB features |
| PDF | PDF.js | None (native) | Page navigation, zoom, highlights, bookmarks, TOC (if embedded), two-page mode |
| DJVU | Converted to PDF (ddjvu or calibre fallback) | Then uses PDF.js | Full PDF features |
| CBZ | Image page extraction | None | Page navigation, thumbnails, zoom, drawing overlay, RTL/manga mode |
| CBR | Download only | No RAR tool in container | Use Download instead |

**Format auto-detection:** The reader detects the file extension and dispatches to the appropriate engine. AZW3/MOBI/FB2 are silently converted to EPUB on first open; the conversion is cached on disk so subsequent opens are instant.

### 3.2 Reader Toolbar

The toolbar sits at the top of the reader and provides these controls (left to right):

| Button | Action |
|--------|--------|
| **✕** | Close reader (saves position, returns to Library tab) |
| **📖** | Toggle reading list sidebar (left panel) |
| **🔍** | Toggle in-book search bar (EPUB only) |
| **🗂** | Toggle table of contents sidebar (EPUB/PDF) |
| **🎨** | Toggle drawing overlay mode (PDF/CBZ) |
| **📝** | Toggle annotations/notes sidebar (right panel) |
| **◀ / ▶** | Previous / next page |
| **Cc** | Toggle two-page spread view |
| **RTL** | Toggle right-to-left reading direction (manga mode) |
| **A− / A+** | Decrease / increase font size (EPUB) or zoom (PDF/comic) |
| **🔍+ / 🔍−** | Zoom in / out (PDF/comic) |
| **⛶** | Enter fullscreen |
| **⚙** | Open settings dropdown panel (BL-026) — consolidates all reader settings in one place |
| **🌙 / ☀ / 📜 / 🌑** | Theme selector: Dark, Light, Sepia, Night |

### 3.3 Navigation

**Keyboard shortcuts (all formats):**

| Key | Action |
|-----|--------|
| Arrow Left | Previous page |
| Arrow Right | Next page |
| Arrow Up / Page Up | Previous page (paginated) or scroll up (EPUB) |
| Arrow Down / Page Down / Space | Next page (paginated) or scroll down (EPUB) |
| Home | Jump to start of book |
| End | Jump to end of book |
| Escape | Close panels / Exit fullscreen |
| ? | Open keyboard shortcuts modal |

**Mouse:**
- Click **◀** / **▶** buttons for previous/next
- Ctrl/Shift + mouse wheel to zoom (PDF/comic)
- Scroll wheel to scroll within EPUB (scrolled-doc mode)

**Touch:**
- Horizontal swipe to turn pages
- Two-finger pinch to zoom in/out
- Tap center of screen to toggle toolbar (in fullscreen)

**Page thumbnails:**
A scrollable strip of page thumbnails appears below the toolbar (PDF/CBZ). Click any thumbnail to jump directly to that page. Thumbnails are lazy-loaded as you scroll. Hidden in fullscreen mode.

**Glass footer scrubber (BL-022):**
A frosted-glass bar at the bottom of the reader shows:
- **Draggable scrubber** — drag to any position; release to navigate.
- **Chapter tick marks** — vertical lines at chapter boundaries (EPUB) or every 10 pages (PDF/CBZ). Current chapter is highlighted in blue.
- **Percentage chip** — click to toggle a number input. Type a page/chapter number and press Enter to navigate directly.
- **Prev/next chevrons** — jump to the start of the next/previous chapter.
- In fullscreen, the same footer appears at the bottom of the screen.

### 3.4 Themes & Typography

**Eight reading themes:**

| Theme | Background | Text | Best for |
|-------|-----------|------|----------|
| Dark (default) | `#1e293b` | Light gray | General reading |
| Light | `#ffffff` | Dark | Bright environments |
| Sepia | `#f4ecd8` | Warm brown | Extended reading sessions |
| Night | `#111318` | Dim gray | Late-night reading |
| Gray | `#2d2d2d` | Medium gray | Neutral tones |
| Rosewood | `#3b1e2e` | Pink-gray | Warm ambiance |
| Azure | `#1a2744` | Light blue | Cool tones |
| Ocean | `#0f2027` | Teal-gray | Deep calm |

Theme selection persists in localStorage across sessions. Settings are saved per-format (EPUB, PDF, CBZ have independent settings) and per-book (each book remembers its own zoom/theme/line-height). When you reopen a book, it resumes with your last-used settings.

**Typography controls (EPUB):**
- Font size: 50%–300% via **A−** / **A+** buttons or keyboard
- Line height: Configurable (Compact/Normal/Relaxed/Loose)
- Font family: Serif, Sans-serif, Monospace, Georgia, Palatino
- **J** button: toggle text justification
- **Hy** button: toggle hyphenation
- Content width slider: 400–1600px (restricts text block width)

**Zoom controls (PDF/Comic):**
- 30%–300% via **🔍+** / **🔍−** buttons
- Reset to fit-to-view with the reset button
- Ctrl/Shift + mouse wheel for fine-grained zoom
- Zoom level displayed in toolbar

### 3.5 Two-Page / Spread View

Toggle the two-page mode via the **Cc** button in the toolbar:

- **PDF/DJVU**: Renders left and right pages side by side (like an open book)
- **CBZ**: Renders two consecutive pages adjacent
- **RTL/Manga mode**: Reverses the page order for right-to-left reading (right page first)
- **EPUB**: Not available (uses scrolled-doc mode instead)

### 3.6 In-Book Search (EPUB only)

Click the **🔍** button to reveal the search bar. Type a search term and press Enter:

- Searches through all spine items in the EPUB
- Results appear with context snippets (max 400 matches)
- Click any result to jump to that location in the book
- The search highlights the matched text briefly

### 3.7 Table of Contents

**EPUB:** The TOC is loaded from the EPUB's navigation document (nav.xhtml or toc.ncx). It displays as a hierarchical tree in the left sidebar. Click any entry to jump to that chapter. The currently active chapter is highlighted.

**PDF:** The TOC is built from the PDF's internal outline (if present). Destination page numbers are resolved and displayed. Click any entry to jump to that page.

**CBZ/CBR:** No TOC support (comics are page-based).

### 3.8 Fullscreen Mode

Click the **⛶** button in the toolbar to enter fullscreen mode. This provides a completely immersive reading experience:

**Default state (zero chrome):**
- Only the reading content is visible
- No toolbar, no buttons, no sidebars
- Page thumbnails are hidden

**Revealing the toolbar:**
- **Desktop:** Hover the mouse into the top or bottom 24px edge zone of the screen — the floating toolbar slides in
- **Mobile:** Tap the top or bottom edge zone — the toolbar appears
- The toolbar auto-hides after 3 seconds of inactivity
- Hovering the toolbar itself keeps it visible and resets the timer

**Pinning the toolbar:**
- **Desktop:** Click anywhere in the center of the reading area — a small blue dot appears above the toolbar indicating it is pinned
- **Mobile:** Tap the center of the reading area to toggle pin
- Pinned toolbar stays visible until you click/tap center again to unpin
- A drag gesture (moving the pointer more than 8px) does NOT trigger pin — this prevents accidental pin while scrolling

**Panel-open lock:**
- When a sidebar (reading list or annotations) is open — either hover-visible or pinned — the toolbar stays visible and the auto-hide timer is suspended
- The timer resumes when all panels are closed

**Sidebar access:**
- **Desktop:** Hover over the left/right screen edge (24px zone) to slide in the reading list or annotations sidebar
- **Mobile:** Swipe from the left/right edge to reveal sidebars

**Escape key cascade (priority order):**
1. Close the search panel (if open)
2. Unpin the left sidebar (if pinned)
3. Unpin the right sidebar (if pinned)
4. Unpin the toolbar (if pinned)
5. Exit browser fullscreen (standard behavior)

**Exiting fullscreen:**
- **ESC key**: Follows the cascade above; at the final step exits fullscreen
- **✕ button**: In the floating toolbar; closes the reader and exits fullscreen

### 3.9 Annotations & Highlights

**Creating highlights:**
- **EPUB:** Select text with the mouse → a popup appears with color choices and an optional note field
- **PDF:** Click and drag to select a rectangular region → the same popup appears
- **CBZ:** Click and drag to select a region (for marking panels or details)

**Selection actions (BL-024):**
Below the highlight buttons, a row of action buttons provides:
- **Copy** — copies the selected text to the clipboard
- **Translate** — opens Google Translate with the selected text pre-filled
- **Define** — looks up the first word in the free dictionary API and shows the definition inline
- **Search** — opens a Google search with the selected text

**Colors (7 choices):**
Yellow, Green, Blue, Red, Purple, Orange, White

**Anchoring:**
- EPUB highlights are anchored by CFI (Canonical Fragment Identifier) — they survive text reflow
- PDF/CBZ highlights are anchored by page number + bounding box coordinates

**Managing highlights:**
- View all highlights in the **Timeline** panel (right sidebar, Highlights tab)
- Click any highlight in the timeline to jump to its location
- Delete individual highlights via the X button
- Export all highlights to Markdown via the export button

### 3.10 Notes (Zettelkasten System)

The notes system implements a lightweight Zettelkasten (slip-box) workflow:

**Creating a note:**
1. Navigate to the desired location in the book
2. Click **+ Note** in the annotations sidebar
3. Enter a title and body text
4. Add comma-separated tags
5. The note is anchored to the current reader position

**Each note receives:**
- A unique ZID (e.g., `abc123-def456`) for linking
- Timestamps (created, updated)
- Page/location anchor (EPUB: CFI; PDF/CBZ: page number)

**Wiki-style links:**
- In any note's body, type `[[zid]]` to link to another note
- An autocomplete dropdown suggests existing notes as you type `[[`
- Backlinks are automatically displayed on notes that are referenced by others

**Managing notes:**
- View all notes in the **Timeline** panel (Notes tab)
- Filter notes by text search
- Click any note to jump to its anchored location
- Edit notes inline
- Delete individual notes

### 3.11 Bookmarks

**Creating bookmarks:**
- Click the **🔖** button in the toolbar to save the current position
- Optionally add a label (e.g., "Chapter 3 intro")

**Auto-bookmarks:**
- When you close the reader, if reading progress exceeds 5% and no bookmark exists near the current position (within 2%), an automatic bookmark is created

**Navigating bookmarks:**
- View all bookmarks in the **Timeline** panel (Bookmarks tab)
- Click any bookmark to jump to that position
- Delete individual bookmarks

### 3.12 Drawing Overlay

For comics (CBZ) and PDFs, toggle drawing mode via the **🎨** button:

**Drawing tools:**
- **Freehand drawing**: Draw directly on the page with pointer or touch
- **Color picker**: Choose from available colors
- **Brush size**: Adjustable line width
- **Eraser**: Remove strokes

**Storage:**
- Drawings are stored per page as normalized coordinate strokes (JSON)
- Persist across sessions (saved to server on page change)
- Each page's drawings load automatically when you navigate to it

**Overlay behavior:**
- The drawing canvas repositions automatically with zoom and page changes
- Drawings are visible in both normal and two-page modes
- Clear all drawings for the current page via the clear button

### 3.13 Progress Tracking

The reader automatically tracks your position in each book:

| Format | Progress method |
|--------|----------------|
| EPUB | Spine index + epub.js locations percentage |
| PDF/DJVU | Page number / total pages |
| CBZ | Current page / total pages |

**Progress display:**
- A progress bar at the bottom of the reader shows percentage complete
- Current page / total pages displayed alongside

**State persistence:**
- Reading position is saved to the server 2 seconds after a page change
- On reader close, the final position is saved immediately
- Reopening a book resumes from the last saved position
- Zoom level, theme, and two-page mode are also saved

**Resume toast (BL-025):** If you've previously read a book (progress > 2%),
a frosted-glass toast appears at the bottom asking "Resume reading at X%?".
Click **Resume** to jump to your saved position, or **Start fresh** to begin
from the beginning. The toast auto-dismisses after you choose or close the
reader.

**Keyboard shortcuts (BL-028):** Press **?** to open the shortcuts modal.
**Home** jumps to the start of the book; **End** jumps to the end.

**Bookmark ribbon (BL-029):** When you save a bookmark, a yellow ribbon
indicator slides down from the top right corner for 1.8 seconds, then
disappears automatically.

**Reading timer (BL-030):** A reading timer in the glass footer tracks time
spent on each book. It accumulates across sessions and pauses when the tab is
hidden. The total time is displayed in MM:SS format in the footer.

**Reader state endpoint:**
- `GET /api/book/<id>/reader-state` — retrieves saved position
- `POST /api/book/<id>/reader-state` — saves current position

---

## 4. Reading List

The Reading List tab manages your reading queue with three status groups:

| Status | Meaning |
|--------|---------|
| **Reading** | Currently reading |
| **To Read** | Queued for later |
| **Finished** | Completed |

**Managing the list:**
- **Add**: Click "+ Reading List" in the detail panel, or the book is auto-added when you open it in the reader
- **Remove**: Click the X on any item
- **Change status**: Use the status dropdown on each item
- **Open**: Click any item to open it in the reader
- **Progress**: A progress bar shows how far you've read

The reading list is also available via the OPDS feed (`/opds/shelf`) for e-reader apps.

---

## 5. Settings

### 5.1 Library Integrity Audit

The Settings tab includes a "Library Integrity Audit" card with two actions:

**Run Audit** — Performs a read-only sweep checking:
1. Database rows whose stored path or size differs from disk (missing files + size mismatches)
2. Archive directory files with no database row (orphans)
3. Metadata with pages=0 or missing cover_path where the source exists
4. Duplicate report by hash (exact) + fuzzy title (token-Jaccard + SequenceMatcher similarity ≥ 0.95)

Results are displayed as grouped counts with expandable preview lists.

**Run Repair** — Fixes issues found by the audit:
- Updates stored file_size from disk
- Re-extracts covers and pages for affected books
- Processes up to 100 books per run (configurable via `max_metadata` parameter)
- Reports remaining issues so you can run again to continue

### 5.2 Configuration

- **Export Config**: Download current configuration as a JSON file
- **Import Config**: Upload a configuration file to apply settings
- Configuration is stored in the `config_overrides` SQLite table and takes precedence over defaults

### 5.3 Backups

- **Automatic**: Backups run every 24 hours in the background
- **Manual**: Click "Create Backup" to create one immediately
- **Retention**: Configurable (default 14 days); older backups are pruned
- **Download**: Click any backup to download it
- **Contents**: Database, covers, pipeline state, enrich cache, config overrides

### 5.4 Excel Export

Click "Export to Excel" in Settings to download a spreadsheet with:
- One sheet per pipeline stage (Arrived, Extracted, Cleaned, Cataloged, Survivor, Skipped, Copied)
- Summary sheet with phase counts
- Columns: ID, UUID, Filename, Title, Author, Year, Format, UDC, UDC_Label, Stage, Stage_Error, Is_Master, Size_MB, ISBN, Publisher, Language, Pages, Hash

---

## 6. OPDS Catalog

The application serves an OPDS 1.2 catalog for e-reader apps (KoReader, Lithium, etc.):

| Endpoint | Description |
|----------|-------------|
| `/opds` | Root navigation feed |
| `/opds/catalog` | All books (paginated, max 200 per page) |
| `/opds/recent` | Recently added books |
| `/opds/shelf` | Books on the reading list |
| `/opds/udc` | Browse by UDC classification |
| `/opds/udc/<code>` | Books in a specific UDC class |
| `/opds/search?q=<query>` | Full-text search |
| `/opds/opensearch.xml` | OpenSearch descriptor |

**Authentication:** OPDS endpoints support HTTP Basic authentication (same password as the web UI). Configure your e-reader app with:
- URL: `http://<host>:5000/opds`
- Username: any (e.g., "book")
- Password: your application password

**Stage filter:** Only books at stages `cataloged`, `copied`, or `survivor` appear in the feed. Skipped duplicates and quarantined books are excluded.

---

## 7. UDC Classification

The Universal Decimal Classification (UDC) system is used to automatically categorize books by subject. The classifier analyzes title, author, subjects, and description to assign the most appropriate UDC code.

**Major categories:**

| Code | Label |
|------|-------|
| 000 | Generalities (encyclopedias, reference) |
| 100 | Philosophy, Psychology |
| 200 | Religion, Theology |
| 300 | Social Sciences (politics, business, economics) |
| 500 | Natural Sciences, Mathematics |
| 600 | Applied Sciences, Medicine, Technology |
| 700 | Arts, Recreation, Sport |
| 800 | Language, Literature |
| 900 | Geography, Biography, History |

**Sub-categories** (examples):

| Code | Label |
|------|-------|
| 004 | Computer Science |
| 005 | Programming |
| 006 | AI / Data Science |
| 150 | Psychology |
| 330 | Economics |
| 530 | Physics |
| 540 | Chemistry |
| 570 | Biology |
| 610 | Medicine |
| 620 | Engineering |
| 780 | Music |
| 820 | English Literature |

**How classification works:**
1. The classifier combines title, author, subjects, and description into a single text string
2. Each UDC pattern is scored (+10 per pattern match)
3. Sub-classifications are scored first (higher specificity wins)
4. Major categories serve as fallback
5. All matching tags are stored, not just the primary one

The UDC tree is browsable in the Library tab sidebar. Click any node to filter the library to books in that classification.

---

## 8. Keyboard Shortcuts

**Reader navigation:**

| Key | Action |
|-----|--------|
| Arrow Left | Previous page |
| Arrow Right | Next page |
| Arrow Up / Page Up | Previous page (paginated) / Scroll up (EPUB) |
| Arrow Down / Page Down / Space | Next page (paginated) / Scroll down (EPUB) |
| ESC | Exit fullscreen (browser standard) |

**Reader controls:**

| Shortcut | Action |
|----------|--------|
| Ctrl/Shift + Mouse Wheel | Zoom in/out (PDF/comic) |
| Touch pinch | Zoom in/out (PDF/comic) |
| Horizontal swipe | Turn pages (touch) |
| Tap center (fullscreen) | Toggle floating toolbar |

---

## 9. API Reference

### Book Operations

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/book/<id>` | Get book details |
| GET | `/api/book/<id>/log` | Get pipeline log |
| POST | `/api/book/<id>/update` | Update metadata |
| POST | `/api/book/<id>/re-extract` | Re-extract metadata from file |
| POST | `/api/book/<id>/re-dedup` | Re-run deduplication |
| POST | `/api/book/<id>/force-keep` | Force keep as master |
| POST | `/api/book/<id>/re-copy` | Re-copy to flat directory |
| POST | `/api/book/<id>/enrich` | Run online enrichment |
| POST | `/api/book/<id>/merge` | Merge into another book |
| POST | `/api/book/<id>/delete` | Delete book |
| GET | `/api/book/<id>/download` | Download original file |
| POST | `/api/book/<id>/cover` | Upload cover image |
| GET | `/api/cover/<id>` | Get cover image |

### Format Conversion

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/book/<id>/convert` | Start conversion (`{format, device}`) |
| GET | `/api/book/<id>/convert/status` | Poll conversion status |
| GET | `/api/book/<id>/convert/download` | Download converted file |

### Annotations & Bookmarks

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/book/<id>/annotations` | List annotations |
| POST | `/api/book/<id>/annotations` | Create annotation |
| PATCH | `/api/book/<id>/annotations/<ann_id>` | Update annotation |
| DELETE | `/api/book/<id>/annotations/<ann_id>` | Delete annotation |
| GET | `/api/book/<id>/annotations/export` | Export highlights as Markdown |
| GET | `/api/book/<id>/bookmarks` | List bookmarks |
| POST | `/api/book/<id>/bookmarks` | Create bookmark |
| DELETE | `/api/book/<id>/bookmarks/<bm_id>` | Delete bookmark |

### Drawings

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/book/<id>/drawing/<page>` | Get drawing data for page |
| POST | `/api/book/<id>/drawing/<page>` | Save drawing data |
| DELETE | `/api/book/<id>/drawing/<page>` | Delete drawing data |

### Reader State

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/book/<id>/reader-state` | Get saved reading position |
| POST | `/api/book/<id>/reader-state` | Save reading position |

### Reading List

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/reading-list` | List all items |
| POST | `/api/reading-list/<book_id>` | Add or update status |
| DELETE | `/api/reading-list/<book_id>` | Remove from list |

### Search & Tags

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/search` | Full-text search with filters |
| GET | `/api/search/series` | Series facet suggestions |
| POST | `/api/tags/<id>/add` | Add custom tag |
| POST | `/api/tags/<id>/remove` | Remove custom tag |

### Saved Searches

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/saved-searches` | List saved searches |
| POST | `/api/saved-searches` | Create saved search |
| DELETE | `/api/saved-searches/<id>` | Delete saved search |

### Bulk Operations

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/bulk/tags/add` | Add tag to multiple books |
| POST | `/api/bulk/tags/remove` | Remove tag from multiple books |
| POST | `/api/bulk/classify` | Classify multiple books |
| POST | `/api/bulk/enrich` | Enrich multiple books |
| POST | `/api/bulk/convert` | Convert multiple books |
| POST | `/api/bulk/delete` | Delete multiple books |

### Pipeline & System

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/status` | Pipeline status |
| POST | `/api/pipeline/run` | Run pipeline |
| GET | `/api/summary` | Phase counts |
| POST | `/api/backup` | Create backup |
| GET | `/api/backups` | List backups |
| GET | `/api/backups/<name>/download` | Download backup |
| GET | `/api/export/excel` | Export to Excel |
| GET | `/api/health` | Health check |
| GET | `/api/quarantine` | List quarantined files |
| POST | `/api/quarantine/resolve` | Resolve quarantine |

### UDC Classification

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/udc` | Browse UDC tree |
| GET | `/api/udc/<code>` | Books in UDC class |

---

## 10. CLI Options

| Option | Description |
|--------|-------------|
| `--source`, `-s` | Source path(s) to scan (semicolon-separated) |
| `--inbox`, `-i` | Inbox directory for ad-hoc files |
| `--port`, `-p` | Web UI port (default: 5000) |
| `--phase` | Run specific phase headless: `metadata`, `dedup`, `copy`, `all`, `recon`, `enrich` |
| `--db` | Path to SQLite database |
| `--watch`, `-w` | Watch inbox directory and auto-trigger pipeline |
| `--run` | Pipeline phase to run with `--daemon` |
| `--daemon`, `-d` | Run as headless daemon (no web UI) |
| `--export-pi` | Export data directory as portable zip |
| `--import-pi` | Import portable zip |
| `--enrich-limit` | Max books to refresh per enrich phase (default: 500) |

**Example usage:**

```bash
# Run with web UI on port 8080
python app.py --source /books --port 8080

# Run pipeline headlessly (no web UI)
python app.py --source /books --phase all --daemon

# Export portable backup
python app.py --export-pi /backups/book_organiser_export.zip

# Import from portable backup
python app.py --import-pi /backups/book_organiser_export.zip

# Watch inbox and auto-process
python app.py --source /books --inbox /inbox --watch
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BOOK_AUTH_PASSWORD` | (empty) | Password for web UI and OPDS Basic auth |
| `BOOK_SECRET_KEY` | (derived) | Flask secret key for sessions |
| `BOOK_DATA_DIR` | `/data` | Database, covers, cache location |
| `BOOK_CONFIG_DIR` | `/config` | Logs, config overrides |
| `BOOK_SOURCE_DIR` | `/books` | Source ebook directories |
| `BOOK_FLAT_DIR` | `/books/processed` | Flat output directory for survivors |
| `BOOK_DB_PATH` | `/data/catalog.db` | SQLite database path |
| `BOOK_COVER_DIR` | `/data/covers` | Cover image storage |
| `GOOGLE_BOOKS_API_KEY` | (empty) | Google Books API key (optional, enables description fetching) |
| `TZ` | `Europe/London` | Container timezone |
| `WITH_CALIBRE` | `0` | Set to `1` in `.env` to install calibre in the container (enables format conversion) |
