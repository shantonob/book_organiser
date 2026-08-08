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
| **External API enrichment** | Open Library + Google Books lookups for sparse metadata; **Refresh Missing Metadata** button backfills missing covers/description/ISBN on demand (cached + rate-limited) |
| **UDC classification** | Multi-tag keyword scoring across 10 UDC classes |
| **Custom tags** | Add your own tags to any book |
| **In-browser reader** | EPUB (ePub.js, incl. continuous scroll), PDF (PDF.js canvas), CBZ/CBR (canvas viewer) — keyboard shortcuts, bookmarks, annotations, mouse-wheel zoom, fit-to-page + scroll mode, per-page drawing overlay (PDF/comic) |
| **Reading list** | Persistent sidebar grouped by Reading / To Read / Finished. Auto-adds books on open |
| **Annotations & highlights** | Add notes, highlight text (EPUB), export as Markdown |
| **Cover gallery** | Visual book browser with UDC/stage filters |
| **Quarantine system** | 5 error buckets for failed files, side-by-side dedup comparison, bulk resolve |
| **Inbox watcher** | Auto-process new files via Watchdog |
| **Excel export** | Download full catalog as `book_catalog.xlsx` |
| **Advanced search** | FTS5 full-text search, faceted filters, saved queries |
| **Metadata editing** | Inline edit + re-process from UI |
| **Status & health dashboard** | Polling-based live pipeline progress (SSE kept disabled), Metrics + health checks in Settings |
| **Portable config** | `machine.json` data_dir override; `--export-pi`/`--import-pi` portable zips; `POST /api/admin/remap-paths` prefix rewrite |
| **Coherence recon** | `--phase recon` / `GET /api/recon` audits DB vs disk (orphans, missing sources, missing covers) |
| **Safe local DB copy** | Network/UNC DB transparently mirrored to a local working copy; auto-seeded on fresh hosts; empty-over-populated syncs refused |
| **Docker + CasaOS** | Multi-arch ARM64/amd64, CasaOS App Store metadata |
| **Cloudflare Tunnel** | Secure HTTPS access via Cloudflare Tunnel |

## Web UI Tabs

| Tab | Access | Description |
|-----|--------|-------------|
| **Library** | Public | Browse/search books, detail panel, filters, UDC Tag Tree sidebar |
| **Reader** | Public | In-browser reading with reading list, bookmarks, annotations, progress bar |
| **Gallery** | Public | Cover grid view with UDC/stage filters |
| **Pipeline** | Admin | Funnel view, phase controls, **Refresh Missing Metadata**, live log, progress, summary tiles |
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
| `BOOK_ENRICH_RATE_LIMIT` | `1.0` | `1.0` | Min seconds between external enrichment API calls |
| `BOOK_ENRICH_CACHE` | `/data/enrich_cache.json` | `<DATA_DIR>/enrich_cache.json` | Cache file for enrichment results |

### Portable config (`machine.json`)

On any machine, a gitignored `machine.json` in the project root overrides the data directory:

```json
{ "data_dir": "/data" }
```

No `machine.json` → falls back to `BOOK_DATA_DIR` env var, then `<project>/data`. If the resulting
DB path is on a network/SMB share, the app transparently mirrors it to a **local working copy**
at `~/book_organiser_data/catalog.db` (auto-seeded from the remote original on fresh hosts, so a
new machine never boots an empty catalog). Use `POST /api/admin/sync-db` to push local changes back;
an empty local DB is never pushed over a populated original.

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
- `drawings` — per-page vector strokes (PDF/comic) for in-reader drawing
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

# Refresh missing metadata (covers + Google Books/Open Library), cap N books per run
python app.py --phase enrich --enrich-limit 500

# Coherence audit (DB vs disk)
python app.py --phase recon

# Portable transfer (laptop ⇄ Raspberry Pi)
python app.py --export-pi book_organiser_data.zip
python app.py --import-pi book_organiser_data.zip

# Daemon mode (separate process)
python daemon.py --status
python daemon.py --run metadata --source "path/to/books"
python daemon.py --watch
```

### Portable transfer workflow (laptop ⇄ Pi)

1. On the laptop: `python app.py --export-pi export.zip`
2. Copy `export.zip` to the Pi.
3. On the Pi: `python app.py --import-pi export.zip` — restores DB, covers, caches, and config overrides.
4. If absolute paths changed between machines (e.g. `Z:\books` → `/books`), rewrite them:
   `curl -X POST http://<pi>:5000/api/admin/remap-paths -H "Content-Type: application/json" -d '{"old_prefix":"Z:\\books","new_prefix":"/books"}'`

### Native frontend deps

EPUB.js and PDF.js are vendored under `static/` (no CDN needed). To (re)generate:

```powershell
# On a machine with internet, from the project root
.\download_deps.ps1
```

### Reader controls

- **Zoom**: Ctrl/Shift + mouse wheel (or the 🔍+ / 🔍− buttons), 30–300%.
- **Scroll mode**: the ⇅ Scroll button toggles fit-to-page vs actual-size scrolling for PDF/comic,
  and continuous vs paginated flow for EPUB (position preserved).
- **Drawing** (PDF/comic): Draw toggles the pen; pick colour/size, strokes are vector-based and
  persisted per page under `/api/book/<id>/drawing/<page>` (visible while reading, editable in draw mode).

## Docker

```bash
# Build and run
docker compose up -d

# Custom password
BOOK_AUTH_PASSWORD=mysecret docker compose up -d

# Stop
docker compose down
```

The container image builds for both `linux/arm64` (Raspberry Pi) and `linux/amd64`.

## Deploying on a Raspberry Pi with CasaOS

1. **Install on the Pi** (64-bit OS recommended), then open CasaOS at `http://<pi-ip>`.
2. **Clone** the repo (or copy `app.py`, `docker-compose.yml`, `casaos/app.yml`,
   `requirements.txt`, `static/`):
   ```bash
   git clone https://.../book_organiser /var/lib/casaos/apps/book_organiser
   ```
3. **Build & run** via SSH or the CasaOS terminal:
   ```bash
   docker compose up -d --build
   ```
   (Optional: import via the CasaOS app store using `casaos/app.yml`.)
4. **Set up storage** to match the container defaults:
   - `/books` — read-only mount of the NAS/media share holding source books
   - `/data` — SSD volume (DB, covers, enrich cache, processed/flat for Phase C)
   - `/config` — config/logs (tiny writes)
5. **Open the UI** at `http://<pi-ip>:5000` (and password with `BOOK_AUTH_PASSWORD` if wanted).
6. **Seed data from the laptop** (metadata & covers follow automatically):
   ```bash
   # laptop
   python app.py --export-pi book_organiser_data.zip
   # pi
   python app.py --import-pi book_organiser_data.zip
   ```
   If source paths differ between machines, remap them after first boot:
   `POST /api/admin/remap-paths` (see *Portable transfer workflow* above).
7. **Expose securely** via Cloudflare Tunnel — see [`casaos/cloudflare-tunnel.md`](casaos/cloudflare-tunnel.md)
   (cloudflared sidecar, bare-metal install, or CasaOS app).

For the two-machine split (laptop does batch discovery + enrichment, Pi does 24/7 serving/
inbox), keep `machine.json` data_dir set to a NAS/SMB path or run the Pi against
`BOOK_DATA_DIR=/data` and sync via `--export-pi`/`--import-pi`.

## Dependencies

Python 3.10+, Flask, EbookLib, lxml, Pillow, spaCy, pandas, requests, watchdog. See `requirements.txt`.
