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

**Status**: ⏳ Pending

---

### P2.22 — Library Tab Reset Button

_Add a "Reset" button to the Library tab that clears all filters and shows all books._

**What:**
- A small button near the search bar (next to "Search" and "Advanced")
- On click: resets all filter controls (stage, UDC, format, tag, year range, size, master-only, source) to defaults, clears the search query, and calls `loadLibrary()`
- Essentially the same behaviour as `switchTab('library')` when called without filters
- Improves UX when users have drilled into a filtered view and want to go back to full catalog

**Status**: ⏳ Pending
