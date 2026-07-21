# Book Organiser

Ebook catalog, deduplication, enrichment, and in-browser reader with a web UI.

## Quick Start

```bash
docker compose up -d
# Then open http://localhost:5000
```

Or natively:

```bash
pip install -r requirements.txt
python app.py --source "path/to/books"
```

## Features

| Feature | Description |
|---------|-------------|
| **3-phase pipeline** | Metadata extraction → global dedup (hash + title fuzzy) → copy survivors to flat folder. Phases A+B are read-only |
| **Multi-format extractors** | EPUB (ebooklib), PDF (binary), MOBI/AZW3 (binary), CBZ/CBR (zip) |
| **Filename enrichment** | spaCy NER + regex for author/title/year/series extraction |
| **External API enrichment** | Open Library + Google Books lookups for sparse metadata |
| **UDC classification** | Multi-tag keyword scoring across 10 UDC classes |
| **Custom tags** | Add your own tags to any book |
| **In-browser reader** | EPUB (ePub.js), PDF (iframe), CBZ/CBR (image viewer), keyboard shortcuts, bookmarks, annotations |
| **Reading list** | Persistent sidebar grouped by Reading / To Read / Finished. Auto-adds books on open |
| **Annotations & highlights** | Add notes, highlight text (EPUB), export as Markdown |
| **Cover gallery** | Visual book browser with UDC/stage filters |
| **Quarantine system** | 5 error buckets for failed files, side-by-side dedup comparison, bulk resolve |
| **Inbox watcher** | Auto-process new files via Watchdog |
| **Excel export** | Download full catalog as `book_catalog.xlsx` |
| **Advanced search** | FTS5 full-text search, faceted filters, saved queries |
| **Metadata editing** | Inline edit + re-process from UI |
| **SSE live updates** | Real-time pipeline progress in browser |
| **Docker + CasaOS** | Multi-arch ARM64/amd64, CasaOS App Store metadata |
| **Cloudflare Tunnel** | Secure HTTPS access via Cloudflare Tunnel |

## Web UI Tabs

| Tab | Access | Description |
|-----|--------|-------------|
| **Library** | Public | Browse/search books, detail panel, filters, UDC Tag Tree sidebar |
| **Reader** | Public | In-browser reading with reading list, bookmarks, annotations, progress bar |
| **Gallery** | Public | Cover grid view with UDC/stage filters |
| **Pipeline** | Admin | Funnel view, phase controls, live log, SSE progress, summary tiles |
| **Quarantine** | Admin | Error buckets, smart filters, bulk actions, dedup ambiguity comparison |
| **Settings** | Admin | In-app config editor, export/import, restart-required banner |

## Authentication

Authentication is **disabled by default** (no password set). When enabled, it only protects the admin tabs (Pipeline, Quarantine, Settings); the Library, Reader, and Gallery tabs remain public.

### How it works

1. **Server-side**: Flask sessions with a 30-day cookie lifetime
2. **Login modal**: Password input in the browser, authenticates via `POST /api/auth/login`
3. **Session check**: Every page load calls `GET /api/auth/check` which returns `{authenticated, enabled}`
4. **Conditional UI**: Admin tabs are hidden from the tab bar until authenticated. If a non-authenticated user navigates to an admin tab (e.g. via URL), they're redirected to Library

### Enabling auth

Set the `BOOK_AUTH_PASSWORD` environment variable:

```bash
# Docker
docker run -e BOOK_AUTH_PASSWORD=mysecretpassword ...

# Native
$env:BOOK_AUTH_PASSWORD="mysecretpassword"
python app.py

# Docker Compose (.env file)
BOOK_AUTH_PASSWORD=mysecretpassword
BOOK_SECRET_KEY=generate-a-random-key-here
```

### API reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/auth/check` | GET | Returns `{authenticated: bool, enabled: bool}` |
| `/api/auth/login` | POST | Body: `{password: string}`. Returns `{authenticated: bool}` |
| `/api/auth/logout` | POST | Clears session |

### Session security

- `SECRET_KEY` is auto-generated per restart if not set via `BOOK_SECRET_KEY`
- Set `BOOK_SECRET_KEY` to a fixed value in production so sessions survive restarts
- Password is hashed via `hashlib.sha256` before comparison (not plaintext)
- Session is configured as `permanent` with 30-day lifetime (`PERMANENT_SESSION_LIFETIME`)

## Configuration

### Environment variables (Docker)

All settings can be overridden via environment variables:

| Variable | Default (Docker) | Default (Native) | Description |
|----------|-----------------|-------------------|-------------|
| `BOOK_SOURCE_DIR` | `/books` | `Z:\books` | Source directory for ebooks |
| `BOOK_DATA_DIR` | `/data` | `data/` | Directory for DB, cache, processed files |
| `BOOK_CONFIG_DIR` | `/config` | `.` | Directory for logs, config overrides |
| `BOOK_FLAT_DIR` | `/data/processed/flat` | `data/processed/flat` | Flat output for Phase C |
| `BOOK_DB_PATH` | `/data/catalog.db` | `data/catalog.db` | SQLite database path |
| `BOOK_LOG_DIR` | `/config/logs` | `logs/` | Log file directory |
| `BOOK_AUTH_PASSWORD` | — | — | Admin password (empty = no auth) |
| `BOOK_SECRET_KEY` | — | — | Flask session key |
| `GOOGLE_BOOKS_API_KEY` | — | — | Google Books API key for enrichment |

### Storage layout (CasaOS on Raspberry Pi)

| Path | Media | Contents |
|------|-------|----------|
| `/data` | SSD | SQLite DB, enrich cache, processed files |
| `/config` | SD card | Logs, config overrides (tiny writes) |
| `/books` | NAS/media share | Source books (mounted read-only) |

## Pipeline

```
Source ──► Phase A ──► Phase B ──► Phase C ──► Flat output
            Metadata     Dedup        Copy
            (read)       (read)       (write)
                │            │            │
                ▼            ▼            ▼
            SQLite DB (data/catalog.db)
```

### Phase stages

| Stage | Meaning |
|-------|---------|
| `arrived` | File discovered in source, registered in DB |
| `extracted` | Metadata extractor ran (format-specific) |
| `cleaned` | Filename cleaned, year extracted, title normalised |
| `cataloged` | UDC classification applied, inline dedup checked |
| `survivor` | Passed global dedup (hash + title fuzzy) |
| `skipped` | Identified as duplicate |
| `copied` | File copied to flat output folder |
| `quarantined` | Non-recoverable error (see error code in detail) |

## Database

SQLite at `BOOK_DB_PATH` (default: `data/catalog.db`). Tables:

- `files` — source paths, hashes, stages, UUIDs
- `metadata` — title, author, ISBN, publisher, year, language, pages, description, subjects, cover, UDC
- `pipeline_log` — per-file log with status and messages
- `tags` — UDC and custom tags per file
- `quarantined` — error codes, review status, user notes
- `reading_list` — status (Reading/To Read/Finished) per book
- `reader_state` — bookmarks: CFI for EPUB, page index for comics, progress %
- `annotations` — highlights, notes, chapter refs per book
- `config_overrides` — user-edited config values via Settings tab
- `quarantine_rules` — auto-resolve rules for bulk operations
- `daemon_status` — IPC table for daemon process

## UDC Classification (Multi-Tag)

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

Books can have multiple UDC tags simultaneously. Add custom tags for personal categories.

## CLI

```bash
# Web UI
python app.py --source "path/to/books"

# Headless — run specific phase
python app.py --source "path/to/books" --phase metadata
python app.py --source "path/to/books" --phase dedup
python app.py --source "path/to/books" --phase copy
python app.py --source "path/to/books" --phase all

# Daemon mode (separate process)
python daemon.py --status
python daemon.py --run metadata --source "path/to/books"
python daemon.py --watch
```

## Docker

```bash
# Build and run
docker compose up -d

# Custom password
BOOK_AUTH_PASSWORD=mysecret docker compose up -d

# Stop
docker compose down
```

## Dependencies

Python 3.10+, Flask, EbookLib, lxml, Pillow, spaCy, pandas, requests, watchdog. See `requirements.txt`.
