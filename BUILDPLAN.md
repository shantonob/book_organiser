# Build Plan — Book Organiser

## Phase 1 — MVP (Complete)

### Features Built

#### Core Pipeline

| Feature | File(s) | Description |
|---------|---------|-------------|
| Config system | `config.py` | Source path, ebook extensions, exclude rules, destination |
| SQLite database | `db.py` | `files`, `metadata`, `pipeline_log`, `tags` tables |
| EPUB extractor | `extractors/epub.py` | Title, author, publisher, ISBN, language, description, subjects, year, cover via ebooklib |
| PDF extractor | `extractors/pdf.py` | Title, author, subject from PDF Info dictionary, page count (binary parse) |
| MOBI/AZW3 extractor | `extractors/mobi.py` | Title from Palm DB header (binary parse) |
| CBZ/CBR extractor | `extractors/cbz.py` | Title from filename, image page count |
| Extractor registry | `extractors/__init__.py` | Maps extensions to extractors, single `extract_metadata()` entry point |
| Filename cleaner | `filename_cleaner.py` | Strips URLs, brackets, format labels, version numbers, edition markers, leading years. SHA-256 hashing, year extraction, title normalisation, title similarity (SequenceMatcher) |
| UDC classifier | `classifier.py` | Multi-tag keyword scoring across 10 UDC classes. Returns all matching classes + single best for backward compat |

#### Pipeline (3-Phase Architecture)

| Phase | Function | Description | Read-only |
|-------|----------|-------------|-----------|
| A — Metadata | `run_phase_metadata()` | Discover source files (generator, no upfront collection), hash, extract metadata, clean filename, classify UDC, store all tags. Inline hash + title dedup skips exact duplicates | ✅ Yes |
| B — Global Dedup | `run_phase_dedup()` | Two-pass: SHA-256 hash groups (keep richest metadata), then title fuzzy dedup within same UDC (85% threshold). Marks survivors | ✅ Yes |
| C — Copy | `run_phase_copy()` | Copies only survivors to flat output folder. Filters by ebook extensions only. Clean filenames, collision resolution via `_{id}` suffix | ❌ Writes |

#### Pipeline Orchestration

| Function | Phases | Purpose |
|----------|--------|---------|
| `run_pipeline()` | A + B | Default — metadata + dedup only |
| `run_all_phases()` | A + B + C | Full pipeline including copy |
| CLI `--phase metadata/dedup/copy/all` | Any | Headless mode, one or all phases |

#### Monitoring State

| Component | File | Description |
|-----------|------|-------------|
| `PipelineState` | `pipeline.py` | Thread-safe state with current phase, stage, file, progress counter, log ring buffer |

#### Web UI

| Feature | Endpoint / File | Description |
|---------|-----------------|-------------|
| Dashboard | `templates/index.html` (Pipeline tab) | Stage cards, phase badges, live progress bar, action buttons, SSE log |
| Library | `templates/index.html` (Library tab) | Book table with search/filter by stage & UDC. Click row for detail panel |
| Book detail panel | Library tab | Full metadata display: title, author, year, ISBN, publisher, format, size, pages, language, description, source path, stage. All UDC tags + custom tags with add/remove |
| Quick search | Page header | Global search bar (any page). Results dropdown with UDC + stage. Click to jump to Library detail |
| Live updates | SSE `/api/events` | Server-Sent Events, 2s interval, pushes stage counts + pipeline state |
| Excel export | `/api/export/excel` | Downloads `book_catalog.xlsx` — one sheet per stage + summary sheet. Columns: ID, Filename, Title, Author, Year, Format, UDC, Stage, Size, ISBN, Publisher, Language, Pages, Hash |

#### REST API

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/status` | GET | Pipeline state + stage counts + log |
| `/api/books` | GET | List books (filters: `q`, `stage`, `udc`, `sort`, `order`, `limit`) |
| `/api/book/<id>` | GET | Single book with full metadata + tags |
| `/api/search` | GET | Quick search by title/author/filename |
| `/api/survivors` | GET | List all survivor files |
| `/api/scan` | GET | Trigger A+B pipeline (param: `source`) |
| `/api/scan_all` | GET | Trigger A+B+C full pipeline |
| `/api/scan_inbox` | GET | Process files in inbox folder |
| `/api/phase/metadata` | GET | Trigger Phase A only |
| `/api/phase/dedup` | GET | Trigger Phase B only |
| `/api/phase/copy` | GET | Trigger Phase C only |
| `/api/tags/<id>` | GET | Get all tags for a book |
| `/api/tags/<id>/add` | POST | Add custom tag |
| `/api/tags/<id>/remove` | POST | Remove custom tag |
| `/api/search/tags` | GET | Search books by tag |
| `/api/export/excel` | GET | Download Excel catalog |

### Architecture Decisions

- **Three-phase pipeline**: Phases A+B are read-only on source files. Copy is always an explicit separate step. Prevents accidental writes during exploration.
- **Generator-based discovery**: Avoids collecting all 28k file paths upfront (slow over SMB). Files are processed as discovered.
- **Multi-tag UDC**: Books belong to multiple UDC classes simultaneously. Stored as tags, not a single category field.
- **Flat output**: `Z:\books\processed` — no subdirectories, no hierarchy. Filename collisions resolved by appending DB ID.
- **Format filtering in Phase C**: Only recognised ebook extensions are copied to output. Ancillary files (.opf, .jpg, .txt, .ini) are skipped.

---

## Change Log

### 2026-07-05 — Initial MVP

- Full 3-phase pipeline implemented
- SQLite schema with files, metadata, pipeline_log
- Extractors for EPUB, PDF, MOBI, CBZ
- Filename cleaner with SHA-256 hashing
- UDC classifier (single best match)
- Flask web app with SSE real-time dashboard
- CLI with `--source`, `--port`, `--phase`

### 2026-07-05 — Phase Separation & Flat Output

- Changed processed output from UDC-subfolder structure to flat `processed/books/`
- Made discovery a generator to avoid upfront collection over slow SMB
- Split pipeline into three independent phases (A: metadata, B: dedup, C: copy)
- Separated copy as explicit step (not part of default pipeline)
- Added CLI arg parsing (`--source`, `--inbox`, `--port`, `--phase`, `--db`)

### 2026-07-05 — Global Dedup & Survivor Tracking

- Added `get_cataloged_files()` (LEFT JOIN to include hash-duplicates without metadata)
- Two-pass dedup: hash groups (keep richest metadata) → title fuzzy within UDC
- Added `survivor`, `skipped` stages and `mark_duplicate()`, `mark_survivor()` functions
- Fixed INNER JOIN bug that missed hash-duplicate files in dedup

### 2026-07-05 — Multi-Tag UDC & Custom Tags

- Added `tags` table (file_id, tag, tag_type: udc|custom, tag_label, score)
- `classify_all()` returns all matching UDC classes, not just the best
- Pipeline stores all UDC tags via `set_tags()`
- Custom tag CRUD: add/remove via API endpoints
- Dark-theme UI: book detail panel with tag display + inline add/remove

### 2026-07-05 — Two-Tab UI & Destination Change

- Final destination changed to `Z:\books\processed`
- UI split into two tabs: **Pipeline** (processing view) and **Library** (browse + manage)
- Phase C format filtering: only ebook extensions copied to output
- Book detail API enhanced to return tags
- Library tab with search, stage filter, UDC filter, row click → detail panel

### 2026-07-05 — Excel Export & Quick Search

- `/api/export/excel` — downloads `book_catalog.xlsx` with one sheet per stage + summary
- Quick search bar in page header with results dropdown (click to jump to Library)
- `/api/search` endpoint for title/author/filename search

---

## Phase 2 — Backlog (Planned)

### P2.1 — Global Discovery Progress Bar

_Add to pipeline state and UI._

**What**: After source discovery completes, show `Total books found: N` in the UI. During processing, show `Completed: X / N (Y%)` with a progress bar that reflects the full discovery count, not just the current phase's file count.

**Changes needed:**
- `PipelineState` — add `total_discovered` field, set after initial scan completes
- `discover_source_files()` — needs a fast first-pass count (or estimate) before yielding files
- UI status bar — show `Discovered: 28400 | Processed: 1234 / 28400 (4.3%)` with progress bar
- SSE event — include total_discovered in status data

**Status**: ✅ Done

---

### P2.2 — Filename Metadata Enrichment (Offline)

_Use spaCy + regex to extract author, title, year, series from filenames._

**Implementation:**
- `enrich_filename.py` with spaCy NER + regex patterns for author/title/year/series extraction
- Improved `_split_author_title()` with multi-heuristic scoring (comma pattern, title articles, apostrophe-s, spaCy POS tagging)
- Stricter `_looks_like_name()` with suffix/word-length checks
- Integrated into pipeline Phase A (fills gaps when raw metadata is sparse)
- Integrated into manual re-extract endpoint

**Status**: ✅ Done

---

### P2.3 — External API Enrichment (Online)

_Query Open Library and Google Books APIs to fill missing metadata._

**Lookup chain:**
1. ISBN (from raw metadata) → Open Library exact match
2. Title + author → Open Library fuzzy match
3. Title + author → Google Books fuzzy match

**Fetched fields:** title, authors, publisher, year, pages, language, subjects, description, cover URL

**Caching:** `data/enrich_cache.json` keyed by ISBN / title hash to avoid repeat API calls.

**Rate limiting:** 1 req/s with configurable delay.

**New file**: `enricher.py`

**Integration:** Integrated into Phase A (not a separate Phase D). Fires when raw metadata is sparse (missing title, author, or description).

**Status**: ✅ Done

---

### P2.4 — Metadata Confidence Indicators

_Show how each field was obtained in the UI._

| Source | Label | Confidence |
|--------|-------|------------|
| Embedded file metadata | `embedded` | Medium |
| Filename parsing | `filename` | Low–Medium |
| Open Library | `openlibrary` | High (ISBN) / Medium (title) |
| Google Books | `googlebooks` | High |
| Manual user edit | `manual` | Highest |

**Changes needed:**
- Add `enriched_at`, `enrich_source`, `enrich_confidence` columns to metadata table
- Show source badges in Library detail panel (e.g. `📖 filename` / `🌐 Open Library`)

**Status**: ✅ Done

---

### P2.5 — Manual Metadata Editing in UI

_Allow users to correct any book's metadata fields directly from the detail panel._

**Changes needed:**
- Edit button in detail panel → inline editing for title, author, year, ISBN, etc.
- Save endpoint: `POST /api/book/<id>/update`
- Mark edited fields as `source: manual`

**Status**: ✅ Done

---

### P2.6 — Enhanced Dedup with Enriched Metadata

_Re-run dedup after enrichment catches more duplicates._

After Phase D enriches metadata, re-run Phase B dedup:
- More accurate title matching (corrected titles from APIs)
- ISBN-based dedup (exact ISBN match = duplicate regardless of filename)
- Author + year threshold matching (same author + year + similar title)

**Status**: ✅ Done

---

### P2.7 — Inbox Watcher

_Monitor inbox folder and auto-trigger pipeline on new files._

- Watchdog-based file system watcher on `inbox/`
- On new file detected → auto-trigger Phase A + B + C
- Configurable: `--watch` flag

**Status**: ✅ Done

---

### P2.8 — Advanced Search

_Full-text search across books with Boolean operators, faceted filtering._

- SQLite FTS5 virtual table on title + author + description
- Filter by stage, UDC, tag, format, year range, file size
- Save search queries as named filters

**Status**: ✅ Done

---

### P2.9 — Bulk Tag Operations

_Apply tags to multiple books at once._

- Select multiple books in Library table (checkboxes)
- Bulk add/remove custom tags
- Bulk re-classify UDC

**Status**: ✅ Done

---

### P2.10 — Cover Gallery View

_Visual book browser with cover thumbnails. Brought back as dedicated Gallery tab._

**Implementation:**
- Fourth tab in the UI with responsive cover grid (`auto-fill, minmax(140px, 1fr)`)
- UDC and Stage filter dropdowns
- Cover images at 180px height, format placeholder fallback on load error
- Clicking a cover opens the book's detail panel in the Library tab
- `/api/covers` endpoint returns books with cover images, accepts `?udc=` and `?stage=` filters

**Status**: ✅ Done

---

### P2.11 — Per-Book Re-Processing

_Re-process individual books without clearing the entire DB._

- Button in detail panel: "Re-extract metadata" → re-runs Phase A for that book
- "Re-dedup" → re-checks duplicates for that book
- "Re-copy" → re-copies to output

**Status**: ✅ Done

---

### P2.12 — Multi-Source Support

_Scan multiple source directories._

- `--source` accepts semicolon-separated paths
- Each source tracked via `source_group` column in DB
- Source filter dropdown in Library tab
- `/api/sources` returns per-source counts

**Status**: ✅ Done

---

### P2.13 — Per-File Pipeline Log in Library

_Show all actions performed on a file when viewing its detail in the Library tab._

- Backend: `GET /api/book/<id>/log` — returns `pipeline_log` entries for that file
- Frontend: "Pipeline History" section in the detail panel, colour-coded by status (✓/✗)
- Auto-refresh on re-process

**Status**: ✅ Done

---

### P2.14 — Intuitive Pipeline Funnel View

_Replace the current flat stage cards with a pipeline flow that shows cumulative progress and has tooltips explaining each stage._

**The problem:** Current stage cards show only the *current* stage count per file. A file that reached `cataloged` is no longer counted in `extracted`, so the numbers look like:
```
Extracted: 802      ← 802 files stuck here
Cataloged: 3475     ← 3475 files that passed through
```
This is confusing because it looks like more files are cataloged than extracted.

**Proposed solution — Funnel view:**

```
                         ┌─────────────────────┐
 Total discovered:  4500 │   ████████████████   │ 100%
                         └─────────┬───────────┘
                                   ▼
                         ┌─────────────────────┐
 Extracted (98%):   4410 │   ████████████████░  │  + tooltip
                         └─────────┬───────────┘
                                   ▼
                         ┌─────────────────────┐
 Cleaned (95%):      4275 │   ██████████████░░  │  + tooltip
                         └─────────┬───────────┘
                                   ▼
                         ┌─────────────────────┐
 Enriched (95%):     4275 │   ██████████████░░  │  + tooltip
                         └─────────┬───────────┘
                                   ▼
                         ┌─────────────────────┐
 Cataloged (95%):    4275 │   ██████████████░░  │  + tooltip
                         └─────────┬───────────┘
                                   ▼
                         ┌─────────────────────┐
 Survivor (84%):     3780 │   █████████████░░░  │  + tooltip
                         └─────────┬───────────┘
                                   ▼
                         ┌─────────────────────┐
 Copied (73%):       3285 │   ██████████░░░░░░  │  + tooltip
                         └─────────────────────┘
```

Each row shows:
- **Label** (stage name) + **cumulative count** (files that *reached* this stage, not stuck here)
- **Percentage** of total discovered
- **Visual bar** showing proportion relative to total
- **Tooltip** on hover explaining what the stage means

**Tooltip content:**

| Stage | Tooltip |
|-------|---------|
| **Arrived** | File discovered in source directory and registered in the database |
| **Extracted** | Metadata extractor ran on the file (title, author, format-specific fields) |
| **Cleaned** | Filename stripped of noise (URLs, brackets, format labels). Year extracted from filename |
| **Enriched** | UDC classification applied. Multiple subject tags assigned |
| **Cataloged** | Fully processed in DB with inline dedup check passed. Ready for global dedup |
| **Survivor** | Passed global dedup (hash + title similarity). Confirmed unique |
| **Skipped** | Identified as duplicate (same SHA-256 hash or similar title within same UDC) |
| **Copied** | File copied to Z:\books\processed with cleaned filename |

**Additional details shown in the funnel:**

- **Drop-off count** next to each stage: `−90 files` (files that stopped at previous stage)
- **Stage column** on the right showing how many files are *currently at* each stage (for debugging)
- **Click any stage row** → filter Library tab to show only books at that stage

**Changes needed:**
- Backend: new `/api/pipeline/funnel` endpoint returning cumulative counts per stage
  ```sql
  -- Cumulative count of files that reached at least 'extracted'
  SELECT COUNT(*) FROM files WHERE stage IN ('extracted','cleaned','cataloged','survivor','copied');
  ```
- Frontend: replace flat stage cards with vertical funnel component
- CSS: tooltip on hover for each stage row
- SSE: include funnel data in event stream

**Status**: ✅ Done

---

### P2.15 — Stage Tooltips on Current Dashboard

_Hotfix: add tooltips to the existing stage cards before the funnel view is built._

**Changes needed:**
- Add `title` attribute or CSS tooltip to each stage card div
- Tooltip text explains what each stage means (same content as P2.14 tooltip table)
- Pure HTML/CSS change, no backend work

**Status**: ✅ Done

---

### P2.16 — Quarantine & Manual Intervention Workflow

**Status**: ✅ Done

**Proposed solution — Quarantine system with 5 error buckets:**

#### 1. Error classification

Standardised error codes replace free-text `stage_error`:

| Stage | Error Code | Meaning | Fix Action |
|-------|-----------|---------|------------|
| Extraction | `EXTRACT_FAIL` | Extractor threw exception or returned empty | Check file integrity / re-download |
| Extraction | `FORMAT_UNSUPPORTED` | Extension not in `EBOOK_EXTS` | Add format to config or skip |
| Cleaning | `NO_METADATA_EMPTY` | Raw extract + filename parse both returned nothing | Manual metadata entry |
| Enrichment | `ENRICH_FAIL` | Filename parser + all API lookups returned nothing | Manual metadata entry |
| Classification | `CLASSIFY_FALLBACK` | UDC scored 0 on all classes, fell back to 000 | Manual tag assignment |
| Classification | `CLASSIFY_LOW_CONF` | Best UDC score < threshold (e.g. < 10), ambiguous | Review and confirm |
| Dedup | `DEDUP_AMBIGUOUS` | Title similarity 70–85% — uncertain if duplicate | Human judgment call |

#### 2. Quarantine tracking

Add to the `files` table or a new `quarantine` table:

```sql
CREATE TABLE IF NOT EXISTS quarantined (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id     INTEGER NOT NULL UNIQUE REFERENCES files(id),
    error_code  TEXT NOT NULL,
    detail      TEXT,
    reviewed    INTEGER DEFAULT 0,   -- 0=pending, 1=reviewed, 2=dismissed
    reviewed_at TEXT,
    user_notes  TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);
```

When a file fails at any stage with a non-recoverable error, it moves to `stage='quarantined'` and a row is inserted into `quarantined` with the error code. Files that have been only partially processed keep whatever metadata was extracted so far.

#### 3. Quarantine workflow in UI

**Pipeline tab** — new counter card:
```
 ⚠️ Quarantined: 23 files needing review
```

**Library tab** — new filter option: `Stage: Quarantined`

**Detail view when a quarantined file is clicked:**

```
┌─────────────────────────────────────────────────┐
│ ⚠️ Needs Manual Intervention                     │
│                                                  │
│ Error:   NO_METADATA_EMPTY                       │
│ Detail:  Raw extraction + filename parse both    │
│          returned no title or author             │
│                                                  │
│ Attempted actions:                               │
│   ✓ File registered (id #1423)                   │
│   ✓ MIME detected: application/epub+zip          │
│   ✓ Raw metadata: empty                         │
│   ✓ Filename parsed: "unknown_2025.epub" → none  │
│   ✗ API lookup: skipped (no title to query with) │
│                                                  │
│ ┌────────── Manual Override ──────────────────┐  │
│ │ Title:  [________________________]          │  │
│ │ Author: [________________________]          │  │
│ │ Year:   [____]   UDC: [___]                │  │
│ │ Tags:   [favorite] [to-review] [+ Add]     │  │
│ │ Notes:  [________________________]          │  │
│ └────────────────────────────────────────────┘  │
│                                                  │
│ [Save & Re-process]  [Dismiss]  [Delete File]   │
└─────────────────────────────────────────────────┘
```

**Button actions:**

| Button | Behaviour |
|--------|-----------|
| **Save & Re-process** | Upsert manual metadata, remove from quarantined, re-run enrichment + classification. If passes → `cataloged`. If fails again → stays quarantined with updated error |
| **Dismiss** | Mark as `reviewed=2` (dismissed). Remove from quarantine. File stays at current stage. Won't appear in "Needs Review" count |
| **Delete File** | Remove from DB entirely. Optionally delete source file |

#### 4. Dedup ambiguity — side-by-side comparison

When title similarity is between 70–85% (configurable `AMBIGUOUS_THRESHOLD`):

```
Dedup ambiguous: 2 files with similar titles
┌─────────────────────┬─────────────────────┐
│ File A (#847)        │ File B (#2311)       │
│ Title: "Python...   │ Title: "Python...    │
│ Author: John Smith  │ Author: J. Smith     │
│ Year: 2020          │ Year: 2020           │
│ Size: 2.4 MB        │ Size: 1.8 MB         │
│ Hash: a1b2...       │ Hash: c3d4...        │
│ Format: epub        │ Format: pdf          │
├─────────────────────┼─────────────────────┤
│ [Keep A, Skip B]    │ [Keep B, Skip A]    │
│ [Keep Both]         │ [Merge Metadata]    │
└─────────────────────┴─────────────────────┘
```

#### 5. Pipeline integration

Each phase step wraps with a quarantine check:

```
Phase A → Extract → [EXTRACT_FAIL? → quarantine]
        → Clean   → [NO_METADATA_EMPTY? → quarantine]
        → Enrich  → [ENRICH_FAIL? → quarantine]
        → Classify → [CLASSIFY_LOW_CONF? → quarantine]

Phase B → Dedup → [DEDUP_AMBIGUOUS? → quarantine]
```

If a file is moved to quarantine, the current phase skips enrichment/classification for that file and continues to the next file.

#### 6. Reports for manual triage

Excel export should include a `Quarantined` sheet showing:
- Error code, detail, file info
- What was attempted before failure
- Whether reviewed, by whom (future multi-user), any notes

**Changes needed:**
- Backend: `quarantine` table, error code constants, quarantine CRUD endpoints
- Backend: modify each phase step to check for non-recoverable errors and move to quarantine
- Backend: `GET /api/quarantine` — list quarantined files with error codes
- Backend: `POST /api/quarantine/resolve` — save manual overrides and re-process
- Frontend: quarantine filter in Library tab + quarantine detail panel
- Frontend: quarantine counter in summary cards
- Frontend: dedup ambiguity side-by-side comparison view (not yet implemented)

**Implementation status:**
- ✅ `quarantined` table added to `db.py` with error code constants
- ✅ `quarantine_file()` / `get_quarantined()` / `resolve_quarantine()` functions in `db.py`
- ✅ Pipeline integration: `EXTRACT_FAIL` on extract error, `NO_METADATA_EMPTY` on empty metadata, `DEDUP_AMBIGUOUS` on 70–85% title similarity
- ✅ API endpoints: `GET /api/quarantine`, `POST /api/quarantine/resolve`, `GET /api/quarantine/errors`, `GET /api/quarantine/ambiguous`, `POST /api/quarantine/resolve-ambiguous`
- ✅ Frontend: `quarantined` stage option in Library filter dropdown
- ✅ Frontend: quarantine count displayed in Format summary card
- ✅ Frontend: quarantine detail panel with error code + Resolve/Dismiss buttons
- ✅ Frontend: dedicated quarantine management tab with table, counts (pending/reviewed/dismissed), inline Resolve/Dismiss
- ✅ Frontend: quarantine badge on tab bar showing pending count, auto-refreshed via periodic status poll
- ✅ Frontend: dedup ambiguity side-by-side comparison view with Keep A/Skip B, Keep B/Skip A, Dismiss Both actions
- ✅ DB migration fix for existing databases missing `quarantined` table

**Status**: ✅ Done

---

### P2.17 — Library Summary Tab

_Add a statistics dashboard to the Library tab showing total counts, stage breakdown, UDC distribution, and format breakdown._

**What it shows:**
```
┌────────────────────────────────────────────┐
│ Library Summary                            │
│                                            │
│ Total books: 4,500                        │
│                                            │
│ By Stage:     By UDC:       By Format:     │
│ Arrived   23  000 General   231  ePub  3201│
│ Extracted 45  100 Philo      89  PDF   1045│
│ Cleaned   12  200 Religion   12  CBZ    132 │
│ Cataloged 802 300 Social    567  CBR     12 │
│ Survivor 3780 500 Science   980  MOBI    56 │
│ Skipped   720 600 Applied  1120  AZW3    34 │
│ Copied     12 700 Arts       34             │
│               800 Lit       876             │
│               900 Hist      456             │
└────────────────────────────────────────────┘
```

**API**: `GET /api/summary` returns `{total, by_stage: {...}, by_udc: {...}, by_format: {...}}`

**UI**: Third tab or collapsible panel at top of Library tab. Stage breakdown links clickable → filter library.

**Status**: ✅ Done

---

### P2.18 — Unique Book Identifier (UUID)

_Add an immutable, externally-referencable UUID to each book._

- Add `uuid` TEXT column to `files` table (UNIQUE, indexed)
- Generate via `uuid.uuid4().hex[:12]` on file creation in `upsert_file()`
- Display in Library table and detail panel
- Included in Excel export

**Status**: ✅ Done

---

### P2.19 — Master Flag for Duplicates

_Track which file is the authoritative copy when duplicates exist._

- Add `is_master` INTEGER column to `files` table
- During Phase B dedup, kept file gets `is_master=1`, duplicates get `is_master=0`
- Library filter: Masters only checkbox in advanced search
- Excel export: includes `Is_Master` column
- UI: Master/Duplicate badges in Library table and detail panel

**Status**: ✅ Done

---

### P2.20 — Headless Processing Daemon + API/UI Separation

_Split the monolithic `app.py` into three separate processes for better reliability, scalability, and development workflow._

**Current architecture:**
```
app.py (Flask)
├── Web UI (templates)
├── API endpoints
├── Pipeline runner (threaded)
└── CLI entry point
```

**Problems:**
- Pipeline blocks the Flask process (even threaded, it competes for resources)
- If the web server goes down, any running pipeline is lost
- Hard to scale: can't run multiple pipelines or serve more users
- Pipeline progress is in-memory (`PipelineState`); a restart loses timing info

**Proposed architecture:**

```
┌─────────────┐     HTTP/SSE      ┌─────────────┐
│   Web UI    │ ◄──────────────► │  API Server │
│  (Flask)    │                   │  (Flask)    │
│  port 5000  │                   │  port 5001  │
└─────────────┘                   └──────┬──────┘
                                         │ SQLite
                                         ▼
                                   ┌─────────────┐
                                   │   Pipeline   │
                                   │   Daemon    │
                                   │ (CLI loop)  │
                                   │  port 5002  │
                                   └─────────────┘
```

**Three components:**

**1. Pipeline Daemon** (`daemon.py`)
- Standalone Python process, runs as a long-lived service
- Listens for pipeline jobs via IPC (SQLite watch row)
- Writes progress to `daemon_status` table and `pipeline_log`
- Can be managed: `start`, `stop`, `status`, `restart`
- Survives web server restarts

**2. API Server** (`app.py` refactored to pure API)
- Flask app, no templates
- All current `/api/*` endpoints
- New: `/api/pipeline/start`, `/api/pipeline/status`, `/api/pipeline/stop`
- SSE reads from `daemon_status` table (SQLite polling)
- CORS headers

**3. Web UI** (separate process)
- Thin Flask or static file server
- All data fetched from API Server via `fetch()`
- Can be developed independently

**IPC mechanism:** SQLite polling (daemon writes to `daemon_status` table, API reads it)

**Daemon status table:**
```sql
CREATE TABLE IF NOT EXISTS daemon_status (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type     TEXT NOT NULL,
    status       TEXT NOT NULL,  -- 'pending','running','done','failed'
    pid          INTEGER,
    started_at   TEXT,
    finished_at  TEXT,
    current_file TEXT,
    current_stage TEXT,
    progress     TEXT,           -- JSON {"done":N,"total":M}
    error        TEXT
);
```

**CLI commands:**
```bash
python daemon.py --start                    # Start daemon
python daemon.py --run metadata --source Z:\books  # Submit job
python daemon.py --status                   # Check status
python daemon.py --stop                     # Stop daemon
```

**Implementation:**
- Created `daemon_status` table in `db.py` (init_db migration) for IPC
- Created `daemon.py` — standalone CLI daemon with `--status`, `--run`, `--watch`, `--reset` commands
- Added `daemon_heartbeat()` and `get_daemon_status()` in `db.py` for read/write IPC
- Added `--daemon` and `--run` flags to `app.py` CLI (delegates to daemon.py)
- Added `/api/daemon` endpoint for UI to read daemon status from SQLite
- Pipeline still runs in-process via embedded mode (default) or daemon mode (`--daemon`)

**CLI usage:**
```bash
python daemon.py --status                    # Check daemon status
python daemon.py --run metadata --source Z:\books  # Run metadata phase
python daemon.py --watch                     # Watch inbox as daemon
python app.py --daemon --status             # Via app entry point
```

**Status**: ✅ Done

---

### P2.21 — Global Backend Status Indicator

_Show a persistent visual indicator in the page header when the server is actively processing (pipeline running, background job, etc.)._

**What:**
- A small dot/indicator in the header bar (always visible, not just on Pipeline tab)
- Shows green/idle or animated amber/red when a pipeline phase is running
- Optional: tooltip with current phase name on hover
- Reuse the existing SSE `pipeline.running` flag or `/api/status` polling
- Current behaviour: only visible inside the Pipeline tab; P2.21 makes it always-visible in the header

**Status**: ✅ Done

---

### P2.22 — Library Tab Reset Button

_Add a "Reset" button to the Library tab that clears all filters and shows all books._

**What:**
- A small button near the search bar (next to "Search" and "Advanced")
- On click: resets all filter controls (stage, UDC, format, tag, year range, size, master-only, source) to defaults, clears the search query, and calls `loadLibrary()`
- Essentially the same behaviour as `switchTab('library')` when called without filters
- Improves UX when users have drilled into a filtered view and want to go back to full catalog

**Status**: ✅ Done

### 2026-07-11 — In-App Configuration UI (P3.4)

- New Settings tab in UI with categorized config form (Paths, Processing, Enrichment)
- config_overrides DB table for persisting changes without modifying config.py
- GET/POST /api/config for reading/writing config overrides
- Config export/import as JSON files
- Restart-required banner for settings needing app restart
- Password field type for API keys (obscured input)
- Overridden fields highlighted with purple border

### 2026-07-11 — Quarantine Bulk Operations (P3.3)

- Q1 Smart Filters: Error code, format, filename search, date range filters on quarantine tab
- Q1 Count badges: Error code counts shown as clickable badges
- Q2 Hybrid Bulk Selection: Select All (applies to filtered results) + individual row checkboxes
- Q3 Bulk Actions: Dismiss, Keep Both, Delete, Re-process with confirmation modal
- Q4 Smart Defaults: Auto-dismiss NO_METADATA_EMPTY toggle, Auto-keep DEDUP_AMBIGUOUS toggle, persisted via quarantine_rules table
- Backend: filtered get_quarantined(), bulk endpoints, quarantine rules CRUD

### 2026-07-11 — UDC/Tag Tree, 3-Panel Layout, Download, Reader, Edit Enhancements

- Summary tiles moved from Library tab to Pipeline tab (below funnel view)
- UDC Tree panel added as left sidebar in Library tab (collapsible, sub-classifications, click-to-filter)
- Renamed "UDC" heading to "Tag Tree" in left panel
- Restored 3-panel layout: UDC Tree (200px left) | Book List (flex:1 center) | Book Detail (320px right)
- Dedup ambiguity view: added "Dismiss Both" (calls resolve with reviewed=2 for both) and "Keep Both" (marks both as survivors, reviewed=1)
- Download button on book detail panel (GET /api/book/<id>/download) with source_path + FLAT_DIR fallback
- In-browser reader tab: EPUB (ePub.js via CDN), PDF (iframe), CBZ/CBR (image page viewer with cache), fallback for unsupported formats
- Reader keyboard shortcuts: arrow keys, space for prev/next; cache cleanup on tab close
- Edit mode enhanced: UDC dropdown selector + custom tag input in edit form
- Backend /update endpoint now accepts udc_code and add_tags

---

### P2.23 — UDC/Tag Tree Panel in Library

Collapsible tree sidebar on the Library tab showing all UDC classes with counts.

**What:**
- Left sidebar in Library tab (200px width)
- Shows major UDC classes (000-900) as root nodes with their labels
- Sub-classifications indented below (e.g. 510, 520 under 500)
- Each node shows code + label + book count
- Clicking any node filters the library by that UDC code and highlights the active node
- Panel labelled "Tag Tree" (renamed from "UDC")

**Status**: Done

---

### P2.24 — Dedup Ambiguity Enhanced Actions

Additional resolution options for the side-by-side dedup ambiguity view.

**What:**
- "Dismiss Both" button: resolves both files with reviewed=2 (dismissed)
- "Keep Both" button: calls mark_survivor() on both files and sets quarantine.reviewed=1
- Purple styling for Keep Both to distinguish from other actions

**Status**: Done

---

### P2.25 — Book Download Endpoint

Download a book file directly from the detail panel.

**What:**
- GET /api/book/<id>/download returns the source file as a download attachment
- Tries source_path first; falls back to FLAT_DIR if source is missing
- Uses clean_filename() for the download filename
- Detects MIME type via mimetypes.guess_type()

**Status**: Done

---

### P2.26 — In-Browser Reader

Read books directly in the browser without downloading.

**Supported formats:**
- EPUB: Rendered via ePub.js (loaded from CDN) with navigation, prev/next, location tracking
- PDF: Embedded via iframe with full-page view
- CBZ/CBR: Extracted to data/cache/comic/<id>, displayed as image pages with prev/next navigation
- Other formats: Fallback message suggesting Download

**Features:**
- Keyboard shortcuts: ArrowLeft/Up for prev, ArrowRight/Down/Space for next
- Format badge showing current book type
- Cache cleanup on tab close (DELETE /api/book/<id>/read/cache)
- "Back to Library" button in toolbar

**Status**: Done

---

### P2.27 — Enhanced Book Edit (UDC + Tags)

Extend the manual edit form to support UDC re-classification and tag management.

**What:**
- Edit form now includes UDC dropdown selector (all 10 major classes) alongside existing fields
- Custom tag input field in edit form (comma-separated or individual)
- Backend /api/book/<id>/update accepts udc_code and add_tags arrays
- On save: UDC tags are replaced, custom tags are appended

**Status**: Done

---

## Phase 3 - Backlog (Planned)

### P3.1 - Enhanced Reader (Reading List, Bookmarks, Notes, Highlights)

Turn the basic reader into a full-featured reading experience.

**Backlog items:**

| Item | Description |
|------|-------------|
| R1 | Reading List sidebar - Persistent sidebar listing all books grouped by status (Reading, To Read, Finished) |
| R2 | Bookmarking - Save reading position per book in DB (reader_state table: book_id, cfi/page, timestamp). Auto-restore on open |
| R3 | Annotations - Highlight text + add notes in EPUB reader. Store in annotations table with book_id, cfi_range, text, note, color, created_at |
| R4 | Reading progress tracking - Visual progress indicator per book. Estimated time remaining based on reading speed |
| R5 | Export highlights - Export all annotations/highlights for a book as Markdown or plain text. "My Clippings" style |

**Status**: Done

---

### 2026-07-21 — Infrastructure & Deployment + Auth (P3.2)

- I1 Docker: Multi-arch Dockerfile (ARM64 + amd64), docker-compose.yml with SSD/SD volume mapping
- I2 Dual-mode config: `config.py` detects `BOOK_ORGANISER_DOCKER` env var. All paths overridable via env vars (`BOOK_DATA_DIR`, `BOOK_SOURCE_DIR`, `BOOK_DB_PATH`, etc.)
- I3 Dashboard: Default landing page is now Library tab (public). Pipeline/Quarantine/Settings marked as admin tabs
- I4 Basic auth: `BOOK_AUTH_PASSWORD` env var. Login modal with session cookie (30-day expiry). `/api/auth/check`, `/api/auth/login`, `/api/auth/logout` endpoints. Admin tabs hidden until authenticated, redirect to library if not
- I5 CasaOS: `casaos/app.yml` metadata for CasaOS App Store. `casaos/cloudflare-tunnel.md` setup guide for Cloudflare Tunnel (Docker sidecar, native install, and CasaOS app approaches)
- Storage split: DB on SSD (`/data`), logs on SD card (`/config`), source books read-only (`/books`)

### 2026-07-21 — Enhanced Reader (P3.1)

- R1 Reading List: Persistent sidebar on Reader tab, grouped by status (Reading/To Read/Finished), click to open. `reading_list` DB table with CRUD. Add/Remove from detail panel and reader toolbar
- R2 Bookmarking: `reader_state` table saves location (CFI for EPUB, page index for comics) + progress %. Auto-restore on open. Position saved every 2s during reading and on tab switch/close
- R3 Annotations: `annotations` table stores highlights and notes per book. Display panel below reader area. Inline "Add Note" button for manual notes. Delete support
- R4 Progress Bar: Visual progress bar in reader toolbar for all formats. Updates on page turn/navigation
- R5 Export Highlights: Markdown export endpoint (`GET /api/book/<id>/annotations/export`) with "Export" button in reader toolbar. Downloads `highlights_<id>.md`
- Backend: `get_reading_list()`, `add_to_reading_list()`, `update_reading_list_status()`, `remove_from_reading_list()`, `get_reader_state()`, `save_reader_state()`, `get_annotations()`, `add_annotation()`, `delete_annotation()`, `export_annotations_markdown()` in db.py
- Backend endpoints: `GET/POST /api/reading-list`, `POST/DELETE /api/reading-list/<id>`, `GET/POST /api/book/<id>/reader-state`, `GET/POST /api/book/<id>/annotations`, `DELETE /api/book/<id>/annotations/<ann_id>`, `GET /api/book/<id>/annotations/export`

### P3.2 - Infrastructure & Deployment

Production-hardening and deployment tooling.

**Backlog items:**

| Item | Description | Status |
|------|-------------|--------|
| I1 | Docker Compose - Dockerfile + docker-compose.yml. Single `docker compose up` | Done |
| I2 | Dual-mode config - Docker uses env vars for paths; native mode unchanged. `BOOK_ORGANISER_DOCKER=1` env var | Done |
| I3 | Dashboard page - Root `/` shows Library/Reader as landing. Pipeline/Quarantine/Settings are admin tabs | Done |
| I4 | Basic auth - Password gate for admin tabs. Config via `BOOK_AUTH_PASSWORD` env var. Login modal + session | Done |
| I5 | CasaOS + Cloudflare - CasaOS app metadata (`casaos/app.yml`), ARM64 Dockerfile, Cloudflare Tunnel docs | Done |

**Storage layout (CasaOS on Pi):**

| Path | Media | Contents |
|------|-------|----------|
| `/data` | SSD mount (`/mnt/ssd/book-organiser/data`) | SQLite DB, enrich cache, processed files |
| `/config` | SD card (`/mnt/sd/book-organiser/config`) | Logs, config overrides |
| `/books` | Media share (`/mnt/media_ssd/books`) | Source books (read-only) |

**Status**: Done

---

### P3.3 - Quarantine Bulk Operations

Bulk-resolve large numbers of quarantined files without manual one-by-one intervention.

**Problem:** 800+ files in quarantine (DEDUP_AMBIGUOUS, NO_METADATA_EMPTY, etc.) cannot be resolved individually.

**Proposed hybrid approach:**

**Q1 - Smart Filters (Phase 1):**
- Quarantine tab gets filter bar: Error Code dropdown, Date Range, File Name search, Format filter
- Count badge on each filter option showing how many files match
- Filter results update the table instantly (client-side or server-side)

**Q2 - Hybrid Bulk Selection (Phase 2):**
- "All N filtered" checkbox + individual row checkboxes coexist
- When "Select All" is checked, actions apply to ALL filtered items (even beyond scroll)
- Individual checkbox selection overrides for targeted actions on visible subset
- Clear selection button

**Q3 - Bulk Actions (Phase 3):**
- Bulk Dismiss - mark reviewed=2 for all selected. Optional: with reason
- Bulk Keep Both - mark_survivor() + reviewed=1 for all selected ambiguous pairs
- Bulk Keep A / Skip B - for ambiguous pairs: keep the left/first file as survivor
- Bulk Delete - remove from DB + optional source file deletion
- Bulk Re-process - re-run metadata extraction + classification
- Confirmation modal before destructive actions

**Q4 - Smart Defaults (Phase 4):**
- "Auto-dismiss NO_METADATA_EMPTY" toggle - these are hopeless without manual input
- "Auto-keep ALL DEDUP_AMBIGUOUS" toggle - keep both as survivors automatically
- Background job that applies rules to newly quarantined files
- Configurable rules saved in DB

**Status**: ✅ Done (Q1-Q4)

---

### P3.4 - In-App Configuration UI

Visualise and edit all application settings directly from the web interface.

**What:**
- New "Settings" tab or modal in the UI
- Displays all config.py attributes: source paths, ebook extensions, exclude rules, flat dir, log dir, DB path, inbox path, enrichment settings, etc.
- Editable fields with validation: path existence checks, extension format validation, numeric bounds
- Underlying SQLite database connection string and WAL/pragma settings visible
- Changes written back to config.py (or a separate settings table in DB) and applied on save
- Optional: restart-required banner for settings that need app restart
- Optional: config backup/restore (export/import JSON of all settings)

**Why:** Eliminates the need to SSH in and edit config.py by hand for routine configuration changes.

**Status**: Done

---

## Phase 4 — Backlog (Planned)

### P4.1 — Source Folder Tagging + Custom Tags in Tag Tree

Add the ability to tag books by their source folder name, and show custom tags alongside UDC tags in the Tag Tree sidebar.

#### P4.1a — Folder Tag Script

A standalone script that walks the source directory and tags each book with the name of its immediate parent folder.

**Implementation:**
- New file: `tools/folder_tags.py` (or extendable via `python tools/folder_tags.py`)
- Reads `source_path` from the `files` table for every book
- Extracts the immediate parent folder name from the path
- Adds it as a custom tag (e.g. `tag_type='custom'`, `tag='2026 reading'`) via `add_custom_tag()`
- Skips books that already have that folder tag (idempotent)
- Reports summary: "Tagged 142 books, skipped 58 already tagged"

**Why:** Users organise books into folders like `2026 reading/`, `reference/`, `fiction/`. This preserves that organisation as searchable/filterable tags in the UI.

**Changes needed:**
- `tools/folder_tags.py` (new) — CLI script
- Optionally integrate as a button in Settings tab or Pipeline actions

#### P4.1b — Custom Tags in Tag Tree

Currently the Tag Tree sidebar (`renderUdcTree()`) only shows UDC classification counts. Custom tags (e.g. `2026 reading`, `favorite`, `to-read`) are invisible in the tree.

**Implementation:**
- Backend: Add `by_custom_tags` to the `/api/summary` response. Query:
  ```sql
  SELECT tag, COUNT(*) as c FROM tags WHERE tag_type='custom' GROUP BY tag ORDER BY c DESC
  ```
- Frontend: In `renderUdcTree()`, after the UDC list, add a **Custom Tags** section with a header and individual tag rows. Each row shows the tag name + book count, and clicking it filters the library by that tag (like UDC nodes do).
- If no custom tags exist, the section is hidden.

**Changes needed:**
- `db.py`: extend `get_summary()` to return `by_custom_tags`
- `app.py`: `api_summary()` already returns the full result dict — no endpoint change needed
- `templates/index.html`: modify `renderUdcTree()` to append a custom-tags section

**Status**: Planned

---

### P4.2 — Fullscreen Reader with Cross-Format Highlighting & Annotation Sidebar

Turn the current reader into a full-featured reading environment with fullscreen mode, cross-format highlighting and annotation, and a right-side annotation sidebar.

#### Current state

- Reader lives in the Reader tab alongside a left reading-list sidebar (200px)
- Annotations panel is below the reader area (`#annotationsPanel`)
- Only EPUB supports highlighting (via ePub.js native selection)
- PDF shows in an iframe, comics show as image pages — no highlighting at all
- Close button navigates back to Library tab (same as Back)
- No fullscreen support

#### P4.2a — Fullscreen Mode

Add a fullscreen button to the reader toolbar that uses the Fullscreen API.

**Implementation:**
- New button in `#readerToolbar`: `⛶ Fullscreen` (or a fullscreen icon)
- On click: `document.querySelector(".reader-layout").requestFullscreen()`
- Style adjustment: in fullscreen, hide the reading list sidebar, **keep the annotations sidebar visible** so the user can refer to notes/highlights while reading
- Maximise the reader area to fill remaining space, adjust heights to `100vh`
- Esc or button click returns to normal layout
- Keyboard shortcuts still work in fullscreen (Arrow keys, Space)

**Changes needed:**
- `templates/index.html`: add fullscreen toggle button + Fullscreen API JS
- CSS: `:fullscreen` override hides `.reading-list-sidebar` only, keeps `.annotations-sidebar` visible, maxes reader area width and height

#### P4.2b — Close (×) Button vs Back

Replace the current "Back" button (which navigates to Library tab) with a proper × close button that dismisses the book from the reading pane without losing state.

**Behaviour:**
- `×` (close) button in the toolbar: hides the reader area, switches to Library tab. The book's reader state (position, annotations) is already saved via the auto-save timer — no data loss.
- "Back" behaviour preserved as a secondary action: the existing `closeReader()` already saves position + switches to Library. Rename the button to a `×` icon for clarity.
- Tooltip: "Close reader (bookmarks & notes are saved)"

**Changes needed:**
- `templates/index.html`: replace `← Back` button text with `✕` symbol, update onclick to `closeReader()` (already done) with a confirmation-free close
- Ensure no unnecessary cache cleanup when simply closing (keep comic cache until explicitly cleared)

#### P4.2c — Right-Side Annotation Sidebar

Move the annotations panel from below the reader area to a right-side sidebar, and show highlights/notes/bookmarks in a scrollable panel alongside the book.

**Layout change:**
```
┌─────────────────────────────────────────────────┐
│ Reader Toolbar                       [⛶][✕]   │
├────────────────────────┬────────────────────────┤
│                        │   Annotations (right)  │
│    Reader Area         │   ─────────────────    │
│    (flex: 1)           │   Highlight "In the   │
│                        │   beginning..."       │
│                        │   Note: Great insight │
│                        │   ─────────            │
│                        │   Bookmark: page 42   │
│                        │   ×                   │
└────────────────────────┴────────────────────────┘
```

**Implementation:**
- Add `#annotationsSidebar` div beside `#readerArea`, initially hidden
- When annotations exist, show it as a right column (280px width)
- Each annotation card shows: highlight colour bar, quoted text, note text, bookmark icon, timestamp, delete button
- Empty state: "No annotations yet. Highlight text to add notes."

**Changes needed:**
- `templates/index.html`: restructure Reader tab layout to 3-column flex (reading list | reader | annotations sidebar)
- CSS: `.annotations-sidebar` with scroll, fixed width, sticky header
- JS: `loadAnnotations()` should render into the sidebar, not the bottom panel. Update `showAnnotation()` and `deleteAnnotation()` accordingly
- Remove old `#annotationsPanel` (or hide it)

#### P4.2d — Cross-Format Highlighting

Enable text selection and highlighting for all supported formats, not just EPUB.

**EPUB** (existing):
- ePub.js has native `annotations` support via `rendition.annotations.highlight()`
- User selects text → popup "Highlight" button → saves CFI range + selected text to `annotations` table
- Already works in current code but only shows annotation after highlighting

**PDF** (new):
- Use PDF.js (CDN: `https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js`) instead of raw iframe
- Render PDF pages to canvas, listen for `mouseup` / selection events
- On text selection → show floating toolbar with "Highlight" + "Note" buttons
- Store page number + selected text + bounding rect (for re-display)
- On reload, overlay highlights on the PDF canvas (draw semi-transparent yellow rectangles at stored positions)

**CBZ/CBR** (new):
- Use `Canvas 2D` approach: render each comic page on a canvas overlay instead of `<img>`
- On mousedown+mousemove+mouseup → allow rectangular area selection
- Store: page index, x/y/w/h (as percentage of image dimensions for scalability)
- On reload, draw semi-transparent yellow rectangles over the selected areas
- User can add a note to each selected area via a floating input popup

**Storage for non-EPUB highlights:**
Extend the `annotations` table or add serialised positions:

| Column | Current (EPUB) | New (PDF/Comic) |
|--------|----------------|-----------------|
| `text` | Highlighted text | Selected text or empty for area |
| `cfi_range` | EPUB CFI range | NULL |
| `page` | NULL | Page number (PDF) / page index (comic) |
| `bbox` | NULL | JSON: `{"x":0.15,"y":0.2,"w":0.7,"h":0.05}` (percentages) |
| `color` | `#fef08a` default | Same |
| `note` | User note text | Same |

**Backend changes:**
- `db.py`: `add_annotation()` already accepts generic fields — just need to pass `page` and `bbox`
- `app.py`: `POST /api/book/<id>/annotations` already accepts arbitrary JSON — extend to accept `page` + `bbox`
- New endpoint: `GET /api/book/<id>/annotations/render` — returns annotation data needed for canvas overlay (page + bbox + color + text)

**Files to modify:**
- `templates/index.html`: new JS modules for PDF.js rendering, comic canvas overlay, floating highlight toolbar
- `db.py`: extend `add_annotation()` signature (optional params already work)
- `app.py`: no structural changes needed

**Status**: Planned

---

---

### P4.3 — Synchronised Scrolling for Library 3-Panel Layout

Fix the scroll behaviour in the Library tab so the two sidebars (Tag Tree, Book Detail) scroll in sync with the main books table, while each panel independently scrolls its own overflow content.

#### Current state

The Library tab uses a 3-column flex layout:

```html
<div style="display:flex;gap:14px">
  <div id="udcTreePanel" style="max-height:80vh;overflow-y:auto">  ← Tag Tree
  <div style="flex:1">                                              ← Books Table
  <div style="width:320px">                                         ← Book Detail
```

**Problems:**
- Left panel (`udcTreePanel`) is capped at `80vh` with `overflow-y:auto` — scrolls independently from the page
- Centre books table has no max-height or overflow-y — its content makes the full page scroll, while the left panel stays fixed in viewport
- Right panel (`detailPanel`) has no overflow control — when book metadata is long (long descriptions, many tags), it spills outside the panel without scrolling
- The three columns feel disconnected when scrolling: the left panel scroll list but the page scrolls the books table

#### Desired behaviour

- **The entire row** (all 3 panels) scrolls as a single unit with the page. No panel is fixed/independent.
- **Each panel** has internal `overflow-y:auto` for its own content when it exceeds the viewport height (e.g. a 200-item tag tree, or a book description with 1000 words in the detail panel)
- **Panel max-heights** align to `calc(100vh - header - filters)` so they fill the viewport but scroll internally

#### Implementation

```css
.library-row {
  display: flex;
  gap: 14px;
  align-items: flex-start;         /* panels grow naturally */
  min-height: calc(100vh - 240px); /* fill viewport */
}

.library-panel {
  max-height: calc(100vh - 240px); /* same as row min-height */
  overflow-y: auto;                /* internal scroll when content overflows */
  overscroll-behavior: contain;    /* prevent scroll chaining */
}
```

**Key change:** Remove `max-height:80vh` from `#udcTreePanel` inline style. Add a shared CSS class for all three panels that constrains height to the viewport minus the header + filter bar (approx 240px). Each panel scrolls internally. The whole row never scrolls the page because each panel caps its height.

**Files to change:**
- `templates/index.html`:
  - CSS: define `.library-row`, `.library-panel` classes
  - HTML: wrap the 3-column `div` in a `.library-row` container. Apply `.library-panel` to `#udcTreePanel`, the books `div`, and `#detailPanel`
  - Remove the inline `max-height:80vh;overflow-y:auto` from `#udcTreePanel`
  - Add `overflow-y:auto` to the books panel and detail panel
  - Add `position:sticky` to panel headers (`<h2>`) so the heading stays visible while the content scrolls

**Status**: Planned

---

---

### P5.1 — Reading Pane Full-Space Layout

Fix the reader pane so it fills the available viewport width and height both on the page and in fullscreen mode.

#### Current state
The reader layout uses a 3-column flex (reading list sidebar | reader | annotations sidebar), but the reader area doesn't expand to consume all available space between the sidebars. On fullscreen the same issue persists.

#### Desired behaviour
- The reader content area should stretch to fill the gap between the left reading list sidebar and the right annotations sidebar
- In fullscreen, after hiding only the reading list sidebar, the reader should expand to fill the full width minus the annotations sidebar
- Heights should use `100vh` minus the toolbar, with no wasted padding/margins
- The EPUB rendition, PDF iframe, and comic image should all use `width:100%; height:100%` within the reader area

#### Implementation
- CSS adjustments to `.reader-layout`, `.reader-main`, `#readerArea`, `.annotations-sidebar`
- Remove fixed `height: window.innerHeight - 200` from EPUB `renderTo()` call — use `<div>` CSS sizing instead
- Ensure `.reader-main` uses `flex:1` or `width:100%` minus sidebar widths

#### Files to modify
- `templates/index.html`: CSS for `.reader-layout`, `.reader-main`, `#readerArea`; JS `loadReader()` height param

**Status**: Pending

---

### P5.2 — Reading List UX Improvements

Upgrade the reading list sidebar to show the currently open book, replace the "Remove" button with an inline ✕ close, show book metadata, and highlight the active book.

#### Current state
- Reading list has a "Remove" button per entry
- No visual indicator for which book is currently open
- No metadata (author, format, tags, UDC) shown in the reading list
- Bookmarks are not directly accessible from the reading list view

#### Desired behaviour
- Replace the "Remove" button with a ✕ icon rendered inline next to the book title (same line, right-aligned)
- The book that is currently open in the reader should have a highlighted background (e.g. `#1e293b` with left accent border `#0ea5e9`)
- Below the reading list entries, show a "Book Info" section that displays metadata of the currently open/open book:
  - Title, Author(s), Format, UDC code + label, Custom tags, Year
  - Reading status
- Reading list items show a small progress indicator (from `reader-state` percentage)

#### Implementation
- CSS: `.rl-item.active` class for highlighting, `.rl-item .rl-close` for ✕ button, `.rl-metadata` panel
- JS: `renderReadingList()` — add active class when `readerBookId` matches, modify HTML template per item
- New panel: `<div id="readingListBookInfo">` below the reading list entries, updated on book open and on list click

#### Files to modify
- `templates/index.html`: CSS classes, JS `renderReadingList()` rewrite, `openReader()` updates metadata section

**Status**: Pending

---

### P5.3 — Enhanced Text Selection, Highlighting, Bookmarks & Notes

Extend the annotation system to support text selection across all formats, automatic bookmark creation at highlighted locations, inline notes on highlights, and sequential display in the annotations sidebar.

#### Current state
- EPUB highlights work via ePub.js native `rendition.annotations.highlight()` and save CFI range + text
- PDF is served as an `<iframe>` — no selection interaction
- Comics show as `<img>` — no selection
- Annotations sidebar shows notes but highlights from non-EPUB formats are not captured
- No bookmark auto-creation when highlighting
- Highlights, notes, bookmarks are displayed separately, not as a unified timeline

#### Desired behaviour
- **EPUB**: Keep existing highlight mechanism; add auto-bookmark at the CFI location when highlighting; show highlight + bookmark + note as a single entry
- **PDF**: Use PDF.js to render pages; enable text selection with `mouseup` listener; on selection show floating toolbar with "Highlight" + "Add Note" buttons; store page number + selected text + bounding box; on reload, overlay highlights
- **CBZ/CBR**: Use canvas overlay; allow rectangular area selection via drag; store percentage-based coordinates; show floating input for notes
- **All formats**: Each annotation entry in the sidebar shows: highlight colour bar, quoted/selected text (truncated), bookmark icon + location reference (page/CFI), note text, timestamp, edit/delete buttons
- Annotations are ordered chronologically (newest first or by location — user toggle?)

#### Storage
- Extend `annotations` table with `page` (INT), `bbox` (TEXT JSON), `bookmark_cfi` (TEXT), `location_label` (TEXT e.g. "p.110 · line 22")
- Existing `text`, `note`, `color`, `created_at` columns reused

#### Files to modify
- `templates/index.html`: PDF.js integration, comic canvas, floating toolbar, updated annotation rendering
- `db.py`: may need migration for new columns
- `app.py`: minor endpoint changes

**Status**: Pending

---

### P5.4 — Export Annotations & Highlights as Markdown

Add the ability to export all annotations, highlights, and notes for a book as a well-formatted Markdown file, including book metadata.

#### Desired behaviour
- Button in the annotations sidebar or reader toolbar: "Export .md"
- Generates a Markdown file with frontmatter (book title, author, format, UDC, tags, reading dates)
- Body contains sequential annotation entries:
  - Each entry: highlight text (quoted), note text, location reference (page/CFI), timestamp, colour
- File downloads automatically with filename: `<book-title>-annotations.md`
- The same "Export" button should trigger `.md` export alongside the existing highlight export

#### Implementation
- Frontend JS: `exportAnnotationsMd()` — fetches all annotations for the book, formats markdown, triggers download via Blob
- Could use an API endpoint `GET /api/book/<id>/annotations/export?format=md` or do it entirely client-side

#### Files to modify
- `templates/index.html`: new export function, button text/style update

**Status**: Pending

---

### P5.5 — Reader View Controls

Add zoom, page layout, and scroll mode controls to the reader toolbar for all formats.

**Zoom controls:**
- Zoom in/out buttons in the reader toolbar (`+` / `-` / reset)
- Keyboard shortcuts: `Ctrl+=` / `Ctrl+-` / `Ctrl+0`
- Zoom level indicator (e.g. "125%")
- For PDF: adjusts the render scale and re-renders the page
- For comics: scales the canvas/image via CSS transform
- For EPUB: uses ePub.js `rendition.themes.fontSize()` or viewport width adjustment

**Page mode:**
- Toggle between `single page` and `two-page spread` (side-by-side)
- For EPUB: `spread: "auto"` vs `spread: "none"` in `renderTo()`
- For PDF: render two pages side by side when in spread mode
- For comics: show two comic pages adjacent when in spread mode
- Visual toggle button with icon showing current mode

**Fit mode:**
- `fit-to-page` (default): scale content to fill the viewport width/height
- `original-size`: render at 100% with scrollbars
- Toggle button that cycles or shows a dropdown

**Scroll mode:**
- `page-by-page` (default): arrow keys / buttons move one page at a time
- `continuous-scroll`: all pages rendered vertically in a single scrollable container
- For EPUB: ePub.js has `flow: "scrolled-doc"` vs `flow: "paginated"`
- For PDF: render all pages stacked vertically
- For comics: render all pages stacked, use Img or canvas for each
- Toggle button in toolbar

**Implementation notes:**
- States stored in reader-level JS variables:
  - `readerZoom` (float, default 1.0)
  - `readerSpread` (bool, default false for single page)
  - `readerFitMode` ("fit" | "original")
  - `readerScrollMode` ("page" | "continuous")
- On toggle, re-render current book with new settings
- Persist preferences in `reader_state` table or localStorage for per-user memory
- Toolbar buttons should be visible only for appropriate formats (e.g. spread mode only for EPUB/PDF)

**Files to modify:**
- `templates/index.html`: toolbar buttons, mode state variables, re-render logic per format
- CSS for continuous scroll layout

**Status**: Planned

---


When viewing a duplicate book (skipped, merged, or `is_master=0`), show a clickable link to the original/master book in the detail panel.

**Current state:**
- Duplicate books show `stage: skipped` or `stage: merged` with a text error description, but no direct link to the master/original
- The `stage_error` field contains unstructured text like "Duplicates f=<hash>, d=<master_id>" or "Merged into <master_id>"
- No `master_id` column exists for direct foreign-key lookup

**Desired behaviour:**
- In the book detail panel, when a book is a duplicate (not master), show a prominent badge/label: `🔁 Duplicate of Book #<id>` where `<id>` is a clickable link to the master book
- Clicking the link opens the master book's detail panel (or navigates to it in the Library table)
- Works for both dedup-skipped books (Phase B) and merged books (Merge endpoint)

**Implementation options:**

**Option A — Parse `stage_error` (minimal, no schema change):**
- In the detail panel JS, check if `stage === 'skipped'` or `stage === 'merged'`
- Parse the master ID from `stage_error` using regex (e.g. `d=(\d+)` for dedup, `Merged into (\d+)` for merge)
- Render a link: `<a href="#" onclick="showBookDetail(<id>)">Book #<id></a>`
- Drawback: fragile text parsing, no server-side validation

**Option B — Add `master_id` column (proper):**
- Add `master_id INTEGER REFERENCES files(id)` to the `files` table
- `mark_duplicate()` sets `master_id` on the skipped file pointing to the kept master
- Merge endpoint sets `master_id` on the merged file pointing to the target
- Backend: expose `master_id` in the book API response (already returned as part of `dict(row)`)
- Frontend: if `book.master_id` is set, show link
- Cleaner, queryable (can list all duplicates of a master), no brittle text parsing

**Changes needed:**
- `db.py`: add `master_id` column migration in `init_db()`
- `pipeline.py`: update `mark_duplicate()` to set `master_id`
- `app.py`: merge endpoint sets `master_id`
- `templates/index.html`: detail panel shows link when `master_id` is set

**Status**: ✅ Done

Implementation: Option B — added `master_id` column, updated `mark_duplicate()`, merge endpoint, and frontend link in detail panel (`← Master #N`). a104df9

### P5.1 — Reading Pane Full-Space Layout

**Status**: ✅ Done (a104df9)


## Phase 7 — Stability & Quality (Design Gap Fixes)

| # | Item | Severity | Status | Description |
|---|------|----------|--------|-------------|
| 1 | **D7.1** — GET endpoints trigger mutations | **High** | ⬜ Pending | `api_scan`, `api_scan_all`, `api_scan_inbox`, `api_phase_*` are GET but start pipelines. Browsers pre-fetch GET — causes duplicate runs |
| 2 | **D7.2** — Pipeline no mutual exclusion | **High** | ⬜ Pending | No lock prevents concurrent pipeline runs; state corruption risk |
| 3 | **D7.3** — FTS stale after metadata edits | **High** | ⬜ Pending | `books_fts` not updated when title/author edited via API; search returns stale results |
| 4 | **D7.4** — Delete doesn't clean covers + flat_path | **High** | ⬜ Pending | `flat_path`/`archive_path` columns don't exist in schema; cover images orphaned; processed copy not deleted |
| 5 | **D7.5** — Network DB silently redirected | **High** | ⬜ Pending | UNC path auto-switched to local copy with no sync mechanism |
| 6 | **D7.6** — Config overrides not live-applied | **High** | ⬜ Pending | Path changes stored to DB but not applied until Flask restart |
| 7 | **D7.7** — Default secret key | **High** | ⬜ Pending | `"change-me-in-production"` — session forgery trivial if not overridden |
| 8 | **D7.8** — Conversion blocks Flask worker | **High** | ⬜ Pending | MOBI→EPUB `subprocess.run` blocks worker up to 2 minutes synchronously |
| 9 | **D7.9** — Event listener leaks | **High** | ⬜ Pending | `keydown` readers accumulate on re-open; interval timers never cleaned up on tab switch |
| 10 | **D7.10** — Pipeline state write not atomic | **Medium** | ⬜ Pending | `json.dump` directly to file — crash mid-write leaves corrupted file |
| 11 | **D7.11** — Cover download failures silent | **Medium** | ⬜ Pending | Bare `except: pass` swallows cover fetch errors |
| 12 | **D7.12** — Run recon skips cover integrity | **Medium** | ⬜ Pending | Doesn't check cover_path existence or orphaned covers |
| 13 | **D7.13** — No request body size limit | **Medium** | ⬜ Pending | `MAX_CONTENT_LENGTH` not set — OOM risk from large payloads |
| 14 | **D7.14** — SSE endpoint broken | **Medium** | ⬜ Pending | Yields once then hangs; client waits forever. Legacy — replace with polling |
| 15 | **D7.15** — Inconsistent error response format | **Medium** | ⬜ Pending | Some return `{"error":"msg"}`, others empty body or plain text |
| 16 | **D7.16** — All POST missing CSRF | **Medium** | ⬜ Pending | No CSRF token; malicious site could trigger actions on authenticated session |
| 17 | **D7.17** — N+1 in bulk delete | **Medium** | ⬜ Pending | Calls `get_book_by_id` per book_id instead of single `WHERE id IN (...)` |
| 18 | **D7.18** — Missing indexes on foreign keys | **Medium** | ⬜ Pending | `pipeline_log.file_id`, `quarantined.file_id` unindexed — full table scans |
| 19 | **D7.19** — Daemon status no unique process key | **Medium** | ⬜ Pending | Two daemons overwrite each other's status rows |
| 20 | **D7.20** — Comic cache extraction blocks worker | **Medium** | ⬜ Pending | CBZ/CBR extract synchronous in request thread |
| 21 | **D7.21** — Library search no pagination | **Medium** | ⬜ Pending | `limit=200` hardcoded, no prev/next controls |
| 22 | **D7.22** — Enrichment cache not thread-safe | **Medium** | ⬜ Pending | JSON file read/rewrite not atomic; concurrent writes corrupt cache |
| 23 | **D7.23** — FTS rebuild scans all rows | **Medium** | ⬜ Pending | `DELETE+INSERT` all rows instead of incremental upsert |
| 24 | **D7.24** — Bulk tag ops N individual queries | **Medium** | ⬜ Pending | Loops per book_id instead of `executemany` or batch INSERT |
| 25 | **D7.25** — Grid view hides bulk toolbar | **Medium** | ⬜ Pending | No checkboxes in grid view; toolbar hidden but book selection persists |
| 26 | **D7.26** — fetchStatus interval never cleaned | **Medium** | ⬜ Pending | `setInterval` runs 24/7 even when tab hidden |
| 27 | **D7.27** — Silent promise rejections | **Medium** | ⬜ Pending | `.catch(() => {})` everywhere — network errors invisible to user |
| 28 | **D7.28** — Archive exclusion leaks on re-load | **Medium** | ⬜ Pending | `EXCLUDE_DIRS` mutates on each `load_config_overrides` call — accumulates stale entries |
| 29 | **D7.29** — Resolve book path no cover cache | **Medium** | ⬜ Pending | Doesn't check covers directory; download may fail for orphaned files |
| 30 | **D7.30** — Path traversal not fully mitigated | **Low** | ⬜ Pending | `send_file` path not validated against allowed base dirs |
| 31 | **D7.31** — Compensating tx for 3-phase pipeline | **Medium** | ⬜ Pending | Phase A+B commit before C runs; C failure leaves inconsistent state |
| 32 | **D7.32** — Inconsistent confirm dialogs | **Low** | ⬜ Pending | Mix of native `confirm()` and styled modals for destructive actions |

**Status**: In progress — D7.1 and D7.2 being fixed first (most impactful for stability)

CSS: `.reader-layout` uses `min-height: calc(100vh - 160px)`, `#readerArea` uses `flex:1`, EPUB rendition height reads container `offsetHeight` dynamically. Fullscreen handler simplified.

### P5.2 — Reading List UX Improvements

| Order | Feature | Effort | Status | Rationale |
|-------|---------|--------|--------|-----------|
| 1 | **P4.1a** — Folder Tag Script | Low | ✅ Done | Standalone Python script, no UI changes. Quick win |
| 2 | **P4.1b** — Custom Tags in Tag Tree | Low | ✅ Done | Small backend query + minor frontend change. Builds on P4.1a |
| 3 | **P4.2c** — Right-Side Annotation Sidebar | Medium | ✅ Done | Restructures reader layout. Good foundation for P4.2d |
| 4 | **P4.2a** — Fullscreen Mode | Low | ✅ Done | Fullscreen API. Hides reading list, keeps annotations sidebar visible for immersive reading |
| 5 | **P4.2b** — Close (×) Button | Trivial | ✅ Done | Replaced "Back" with ✕. Saves state on close |
| 6 | **P4.3** — Synchronised Scrolling | Low | ✅ Done | CSS-only. All 3 Library panels capped to viewport with internal scroll |
| 7 | **P4.2d** — Cross-Format Highlighting | High | ✅ Done | PDF.js canvas rendering + comic canvas overlay + floating toolbar |
| 8 | **P4.4** — Duplicate Link to Original | Low | ✅ Done | `master_id` column + clickable link in detail panel |
| 9 | **P5.1** — Reading Pane Full-Space Layout | Low | ✅ Done | CSS flex fix, dynamic reader height |
| 10 | **P5.2** — Reading List UX (✕ close, active highlight, metadata panel) | Medium | ✅ Done | Inline ✕ close, active highlight, current book info panel |
| 11 | **P5.3** — Enhanced Highlighting & Bookmarks | High | ⬜ Pending | Text selection for PDF/comic, auto-bookmarks, unified timeline in annotations sidebar |
| 12 | **P5.4** — Export Annotations as Markdown | Low | ⬜ Pending | Download .md with book metadata + all highlights/notes in sequence |
| 13 | **P5.5** — Reader View Controls (zoom, page mode, scroll) | Medium | ⬜ Pending | Zoom in/out, single/2-page spread, fit-to-page/original, page-by-page/continuous scroll |
| 14 | **P6.1** — Portable Config Module | Medium | ⬜ Pending | Split config/data from code for laptop→Pi transfer workflow |
| 15 | **P6.2** — Coherence Recon Tool | Low | ✅ Done | `GET /api/recon`, `--phase recon` CLI; scans inbox/processed/archive + DB integrity checks |

---

## Phase 6 — Backlog (Planned)

### P6.1 — Portable Config Module

Allow the application to be split across two machines: a powerful laptop for batch metadata discovery + enrichment, and a Raspberry Pi for 24/7 serving and light inbox processing.

**Design:**

- `machine.json` (gitignored) in the project root contains one key: `data_dir` pointing to where DB, logs, covers, and pipeline state live
- On laptop: `{"data_dir": "C:/Users/shant/book_organiser_data"}`
- On Pi: `{"data_dir": "/mnt/storage/book_organiser_data"}`
- If `machine.json` absent, fall back to current auto-detect logic

**CLI sync commands:**
- `python app.py --export-pi export.zip` — zips data dir with path remapping (`Z:\books` → `/mnt/storage/books`)
- `python app.py --import-pi export.zip` — unzips into current `machine.json`'s data_dir, applies remapping

**Path remap endpoint:**
- `POST /api/admin/remap-paths` — bulk-replaces path prefixes in `config_overrides` and `files` table columns

**DB changes:**
- WAL mode (`PRAGMA journal_mode=WAL`) for concurrent read/write on Pi
- `RotatingFileHandler` for logs (5MB max, 3 backups) to avoid SD card fill-up

**Workflow:**
1. Laptop: scan inbox + enrich via API (fast CPU + internet)
2. Laptop: `python app.py --export-pi data.zip`
3. Copy zip to Pi
4. Pi: `python app.py --import-pi data.zip`
5. Pi: serves books 24/7, processes small inbox batches locally

**Status**: Planned


### P6.2 — Coherence Recon Tool

`GET /api/recon` endpoint and `--phase recon` CLI command that audits DB/filesystem consistency.

**What it checks:**
- Scans `to_be_sorted` (inbox), `processed`, and `archive` directories
- For each file found, checks if its path exists in the DB (via `source_path`)
- Reports orphans: files on disk not tracked in DB
- Checks all DB books (20k+): reports any whose `source_path` no longer exists on disk
- Summary: total books, masters, duplicates, breakdown by stage

**Implemented in:** `run_recon()` in `pipeline.py`. Invoked via `GET /api/recon` or `python app.py --phase recon`.

**Status**: ✅ Done (a104df9)
