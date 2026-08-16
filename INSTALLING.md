# Installing Book Organiser

Three paths, same app. Pick the one that fits your host.

| Path | Best for | TL;DR |
|------|----------|-------|
| [Docker (Pi)](#a-docker-docker-compose) | Raspberry Pi / NAS, own mount plan | `install_pi.sh` or `docker compose up -d --build` |
| [CasaOS](#b-casaos-app-store) | Pi with CasaOS (installs as a store app) | `casaos/app.yml` + UI settings |
| [Standalone (no Docker)](#c-standalone-python) | Playing on a desktop / none in Docker | `python start_app.py` |

> All options read the same `BOOK_*` environment variables, so the app behaves
> identically wherever it runs.

---

## 0. What you must decide up front

**Books source.** Your library stays where it is; the app reads it read-only and
writes a *processed* copy. Point `BOOK_SOURCE_DIR` at your NAS/share.

**Storage split (Pi recommendation).**
- **SSD** → DB, covers, cache, processed output (`/data`).
- **SD card** → logs + config overrides (`/config`), tiny writes.
- **Media drive** → source books, read-only.

---

## A. Docker + docker compose

### A1. One-command (Raspberry Pi / Linux)

```bash
curl -fsSL <repo>/install_pi.sh | bash
```

The script (idempotent):

1. checks Docker + compose;
2. creates the default SSD/SD/data mounts (unless `DATA_HOST_PATH`,
   `CONFIG_HOST_PATH`, `BOOKS_HOST_PATH` are already set);
3. copies `.env.example` → `.env` (never overwrites an existing `.env`);
4. builds or pulls the image (`BUILD_OR_PULL=pull` + `BOOK_ORGANISER_IMAGE` set
   → pull; otherwise build);
5. `docker compose up -d` and waits for `/api/health`.

### A2. Manual

```bash
cp .env.example .env          # then edit values
docker compose up -d --build
docker compose logs -f        # watch startup
curl http://<host>:5000/api/health
```

### A3. Volume / port mapping (from `.env`)

```dotenv
DATA_HOST_PATH=/mnt/ssd/book-organiser/data      # → /data   (SSD: DB+files)
CONFIG_HOST_PATH=/mnt/sd/book-organiser/config   # → /config (logs+overrides)
BOOKS_HOST_PATH=/mnt/media_ssd/books             # → /books:ro (source)
BOOK_PORT=5000
```

`WITH_CALIBRE=1` (image build arg) installs calibre for high-fidelity
AZW3/MOBI/FB2→EPUB conversion; the default slim image falls back to the
built-in pure-stdlib reader.

---

## B. CasaOS

CasaOS is the easiest way to manage a Pi Docker stack.

1. Copy `casaos/app.yml` to your CasaOS app source dir and install, **or**
   import the app through the CasaOS store editor.
   The manifest ships sane defaults and exposes: `BOOK_AUTH_PASSWORD`,
   `BOOK_SECRET_KEY`, `GOOGLE_BOOKS_API_KEY`, `WITH_CALIBRE`, plus the three
   host volumes (`/data`, `/config`, `/books:ro`).
2. In the CasaOS **Settings → App volumes** tab set the real host paths.
3. Set `BOOK_AUTH_PASSWORD` to gate the whole app behind login.
4. Open the app on `http://<pi-ip>:5000`.

Remote access guide → `casaos/cloudflare-tunnel.md` (cloudflared Docker
sidecar, bare-metal, or CasaOS cloudflared).

---

## C. Standalone (no Docker)

For development or Windows:

```bash
pip install -r requirements.txt     # needs Python ≥ 3.10, may pull calibre-depends
python start_app.py
```

On Windows some PDF/covers features need Poppler/calibre binaries — see
`download_deps.ps1`. Env fallback: unset `BOOK_*` vars → defaults next to the
repo root (`data/`, `inbox/`, etc.).

---

## Environment reference

| Variable | Used for | Example |
|----------|----------|---------|
| `BOOK_ORGANISER_IMAGE` | Docker image tag | `ghcr.io/you/book:latest` |
| `BOOK_PORT` | host port → 5000 | `5000` |
| `WITH_CALIBRE` | build arg (0/1) | `0` |
| `DATA_HOST_PATH` / `CONFIG_HOST_PATH` / `BOOKS_HOST_PATH` | bind mounts | see above |
| `BOOK_AUTH_PASSWORD` | whole-app login password (empty = no auth) | `s3cret` |
| `BOOK_SECRET_KEY` | session signing key | change me |
| `GOOGLE_BOOKS_API_KEY` | enrichment lookups (optional) | `AIza…` |
| `TZ` | timezone | `Europe/London` |

Full BE/overrides list in `config.py` (loaded via `BOOK_`-prefixed env each
start).

---

## Post-install smoke test

```bash
curl http://<host>:5000/api/health          # {"status":"ok"}
curl http://<host>:5000/api/auth/check      # auth state
```

Then open the web UI, go to **Pipeline**, hit **Upload**, pick `.epub`/`.pdf`/…,
and confirm they land in the inbox and start pipeline A (metadata).