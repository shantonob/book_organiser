# Book Organiser — Raspberry Pi deployment & dev workflow.
# Pi is the single source of truth. All code/data live here.

## Deploy (production)

The container is `book-organiser:latest` (built from this repo). On the Pi:

```bash
cd /mnt/extssd/media_ssd/rwik-shanto/rwik/1.Projects/book_organiser
docker compose up -d --build
```

- Books: `/mnt/extssd/media_ssd/books` → `/books` (writable — the pipeline
  copies survivors into `/books/processed` and moves originals out of
  `to be sorted`; was wrongly `:ro`).
- DB: `/mnt/extssd/.../book_organiser/data/catalog.db` → `/data`.
- Config/logs: `/home/rwikpi/book-organiser/config` → `/config`.

Health: `curl http://<pi-ip>:5000/api/health`.

## Dev loop (edit code without image rebuilds)

The source is served from this same directory. Two modes:

### 1. Rebuild (small changes are cheap)
```bash
docker compose up -d --build
```

### 2. Live bind-mount (no rebuild per edit)
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```
`docker-compose.dev.yml` bind-mounts the repo to `/app` and sets
`BOOK_DEV_MODE=1`. Code/template edits are seen on container restart.

## Single source of truth

- The **Pi DB** (`/data/catalog.db`) is canonical.
- Windows `machine.json` → `C:/Users/shant/book_organiser_data` is a *stale
  snapshot*, not authoritative. Do not run a second pipeline against the same
  source from Windows — it produces a second divergent DB.

## Watcher / pipeline notes

- `/books` must stay writable for `run_phase_copy` and `cleanup_source_dir`
  (they copy survivors to `/books/processed` and move originals).
- Pipeline buttons spawn a subprocess whose log goes to
  `$BOOK_LOG_DIR/pipeline.log` (fixed: was writing to non-existent
  `/app/data/logs`).