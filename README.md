# Book Organiser

Catalog, deduplicate, and organise ebooks from a source directory into a clean flat output. Uses **Universal Decimal Classification (UDC)** for automatic categorisation.

## Pipeline Overview

The pipeline is split into **three independent phases**. Phases A and B are **read-only** on source files — no files are moved or copied until Phase C.

```
Source (Z:\books)                  Processed (processed/books/)
       │                                     ▲
       │  ┌──────────┐   ┌────────┐   ┌──────┴──────┐
       ├──► Phase A  ├──► Phase B ├──►  Phase C     │
       │  │ Metadata  │   │ Dedup  │   │ Copy       │
       │  │ (read)    │   │ (read) │   │ (write)    │
       │  └─────┬────┘   └───┬────┘   └──────▲──────┘
       │        │            │               │
       │        ▼            ▼               │
       │    SQLite DB (data/catalog.db) ──────┘
       │    files + metadata + pipeline_log
```

### Phase A — Metadata Extraction

Walks the source directory recursively, hashes every ebook file with SHA-256, and extracts metadata using format-specific extractors.

**Extractors by format:**

| Format | Extractor | Metadata |
|--------|-----------|----------|
| `.epub` | `extractors/epub.py` (ebooklib) | Title, author, publisher, ISBN, language, description, subjects, year, cover |
| `.pdf` | `extractors/pdf.py` (binary parse) | Title, author, subject (from PDF Info dict), page count |
| `.mobi` / `.azw3` | `extractors/mobi.py` (binary parse) | Title (from Palm DB header) |
| `.cbz` / `.cbr` | `extractors/cbz.py` (zip inspect) | Title (filename), page count |

**Filename cleanup** (`filename_cleaner.py`): Strips URLs, brackets, version numbers, edition markers, leading years, and trailing format labels (ebook, epub, pdf, etc.) from filenames. Extracts year from `(2005)`, `[2005]`, or `2005` patterns in filenames.

File stage after Phase A: `cataloged` (with `duplicate_by_hash` or `duplicate_by_title` if an exact inline duplicate was found).

### Phase B — Global Dedup Sweep

Runs two dedup passes across **all** cataloged files in the database:

1. **Hash dedup**: Groups files by SHA-256 hash. For each group with >1 file, keeps the one with the richest metadata (most non-null fields: title, author, ISBN, description, publisher, year, language, pages). Marks others as `skipped` with reason `duplicate_by_hash`.

2. **Title fuzzy dedup**: Within the same UDC class, compares normalised titles using `SequenceMatcher` (threshold: 85%). When a match is found, the file with richer metadata is kept; the other is marked `skipped` with reason `duplicate_by_title`.

Surviving files are marked `survivor`.

### Phase C — Copy Survivors

Copies only files with stage `survivor` to the flat output folder **`Z:\books\processed`** — no subdirectories, no hierarchy. Only files with recognised ebook extensions (`.epub`, `.pdf`, `.mobi`, `.azw3`, `.djvu`, `.cbr`, `.cbz`, `.fb2`) are copied; ancillary files (`.opf`, `.jpg`, `.txt`, `.ini`, etc.) are skipped. Cleans filenames and resolves collisions by appending the database ID. Marks copied files as `copied`.

**Final destination:** `Z:\books\processed` (config: `config.FLAT_DIR`).

This phase is **never included** in the default pipeline — it must be triggered explicitly. Use the **C: Copy Only** button or `--phase copy`.

## Database

SQLite at `data/catalog.db` with four tables:

### `files`

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `source_path` | TEXT UNIQUE | Full path to original file |
| `filename` | TEXT | Original filename |
| `file_size` | INTEGER | Size in bytes |
| `file_hash` | TEXT | SHA-256 hex digest |
| `format` | TEXT | File extension without dot |
| `stage` | TEXT | Current pipeline stage |
| `stage_error` | TEXT | Error message (if any) |
| `created_at` | TEXT | ISO timestamp |
| `updated_at` | TEXT | ISO timestamp |

### `metadata`

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `file_id` | INTEGER FK → files.id | Unique per file |
| `title` | TEXT | Cleaned title |
| `authors` | TEXT | Semicolon-separated |
| `publisher` | TEXT | Publisher name |
| `isbn` | TEXT | ISBN-13 (digits only) |
| `language` | TEXT | Language code |
| `pages` | INTEGER | Page/image count |
| `year` | INTEGER | Publication year |
| `description` | TEXT | Synopsis/blurb |
| `subjects` | TEXT | Subject keywords |
| `udc_code` | TEXT | UDC class number |
| `udc_label` | TEXT | UDC class label |
| `cover_path` | TEXT | Path to extracted cover |

### `pipeline_log`

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `file_id` | INTEGER FK | Associated file |
| `stage` | TEXT | Stage name |
| `status` | TEXT | `done` or `failed` |
| `message` | TEXT | Log message |
| `timestamp` | TEXT | ISO timestamp |

### `tags`

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `file_id` | INTEGER FK → files.id | Associated file |
| `tag` | TEXT | Tag string (e.g. `006`, `custom-tag-name`) |
| `tag_type` | TEXT | `udc` or `custom` |
| `tag_label` | TEXT | Human-readable label (for UDC: e.g. `Applied Sciences`) |
| `score` | REAL | UDC keyword match score |

## File Stages

Each file progresses through stages as it moves along the pipeline:

| Stage | Meaning |
|-------|---------|
| `arrived` | File discovered in source and registered in DB |
| `extracted` | Metadata extractor ran (may have failed) |
| `cleaned` | Metadata cleaned, year extracted |
| `cataloged` | UDC classification applied, inline dedup checked |
| `survivor` | Passed Phase B global dedup |
| `skipped` | Identified as duplicate (hash or title) |
| `copied` | File copied to flat output folder |

## UDC Classification (Multi-Tag)

The classifier (`classifier.py`) uses keyword scoring against 10 main UDC classes. Unlike a single-category system, **every matching class** is assigned as a tag — a single book can belong to multiple UDC classes:

| Code | Class |
|------|-------|
| 000 | Generalities |
| 100 | Philosophy. Psychology |
| 200 | Religion. Theology |
| 300 | Social Sciences |
| 500 | Natural Sciences. Mathematics |
| 600 | Applied Sciences. Medicine. Technology |
| 700 | Arts. Recreation. Sport |
| 800 | Language. Linguistics. Literature |
| 900 | Geography. Biography. History |

Each class has a list of keyword patterns. All classes with positive keyword scores are stored as `udc` tags. For example, a data science book might get tags `006` (Applied Sciences) and `005` (Natural Sciences).

### Custom Tags

You can add your own text tags to any book from the web UI (click a book row → tag editor). Custom tags are stored with `tag_type='custom'` and are independent of UDC tags. Use them for personal categories like `favorite`, `to-read`, `reference`, `archived`, etc.

## File Cleanup

The `filename_cleaner.py` module applies these transformations:

- Removes URLs (`www.*.com`, `http://*`)
- Removes bracketed text `[...]`
- Removes format labels at end of name (`epub`, `pdf`, `mobi`, etc.)
- Removes version numbers (`v1.0`, `v.2.5`)
- Removes edition markers (`edition 3`, `vol 2`)
- Removes leading years (`2025 - Title`)
- Collapses whitespace
- Falls back to `untitled` if filename is empty after cleaning

Duplicate filenames in the output folder are disambiguated by appending `_{database_id}`.

## Usage

```powershell
# Web UI (default port 5000)
python app.py --source "Z:\books"

# Custom port
python app.py --source "\\server\share\books" --port 8080

# Headless — Phase A only (metadata)
python app.py --source "Z:\books" --phase metadata

# Headless — Phase B only (dedup)
python app.py --source "Z:\books" --phase dedup

# Headless — Phase C only (copy survivors)
python app.py --source "Z:\books" --phase copy

# Headless — all three phases
python app.py --source "Z:\books" --phase all
```

### Web UI Tabs

The interface has two tabs:

**Pipeline** — Track processing progress. Stage cards, phase badges, live log, and action buttons:

| Button | Phases | What it does |
|--------|--------|-------------|
| **A+B: Metadata + Dedup** | A + B | Default action. Scans, extracts, cleans, classifies, deduplicates |
| **A: Metadata** | A | Only extract metadata and catalog |
| **B: Dedup** | B | Only run global dedup on already-cataloged files |
| **A+B+C: Full** | A + B + C | Complete pipeline including copy to flat folder |
| **C: Copy** | C | Copy survivors to flat folder (no re-scanning) |

**Library** — Browse, search, and manage books. Click any row to open the detail panel showing full metadata, UDC tags (all matching classes), and custom tags. Add or remove custom tags directly from the detail view.

## Monitoring

- **Browser**: `http://localhost:5000` — two tabs:
  - **Pipeline**: real-time dashboard with Server-Sent Events (updates every 2s). Shows stage counts, phase badges, current file, progress bar, and pipeline log.
  - **Library**: browse all catalogued books by stage, UDC class, or search. Click any book to view full metadata, all assigned UDC tags, and add/remove custom tags.
- **API**: `GET /api/status` returns JSON with pipeline state, stage counts, recent books, and pipeline log.
- **SQLite**: Direct DB queries for detailed analysis:
  ```sql
  SELECT stage, COUNT(*) FROM files GROUP BY stage;
  SELECT f.filename, m.title, m.udc_code, f.stage FROM files f LEFT JOIN metadata m ON m.file_id = f.id;
  ```

## Future Plans

See `BUILDPLAN.md` for the full change log, architecture decisions, and Phase 2 backlog including:

- **Global discovery progress bar** — total file count + completion % in UI
- **Filename metadata enrichment** — spaCy + regex author/title extraction
- **External API enrichment** — Open Library / Google Books lookups
- **Metadata confidence indicators** — source badges per field
- **Manual metadata editing** — inline correction from UI
- **Inbox watcher** — auto-process new files
- **Advanced search, bulk tags, cover gallery, multi-source support**

## Configuration

See `config.py`. Key settings:

- `SOURCE_DIR` — default source path (overridable via `--source` / `BOOK_SOURCE` env var)
- `EBOOK_EXTS` — recognised ebook extensions
- `EXCLUDE_DIRS` — directories to skip during walk
- `DUPLICATE_SIMILARITY_THRESHOLD` — title similarity cutoff (0.0–1.0)

## Dependencies

- Python 3.10+
- Flask (web server)
- EbookLib (EPUB parsing)
- lxml (EPUB XML parsing)
- Pillow (cover image handling)

All listed in `requirements.txt`.
