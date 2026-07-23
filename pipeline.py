import os
import shutil
import json
import threading
import logging
from datetime import datetime

import config
from db import get_connection, init_db, upsert_file, upsert_metadata, set_stage
from log_utils import setup_logger

logger = setup_logger("pipeline", also_stdout=False)
from db import find_duplicate_by_hash, find_duplicate_by_title, get_pipeline_summary
from db import get_cataloged_files, mark_duplicate, mark_survivor, get_survivors, get_phase_counts
from db import set_tags, quarantine_file, QUARANTINE_ERRORS
from extractors import extract_metadata
from filename_cleaner import clean_filename, extract_year_from_filename, file_hash, is_duplicate_title, normalize_title, title_similarity
from enrich_filename import enrich_from_filename
from enricher import enrich_book
from classifier import classify, classify_all


class PipelineState:
    def __init__(self):
        self.lock = threading.Lock()
        self.stage_counts = {}
        self.current_file = None
        self.current_stage = None
        self.current_phase = None
        self.phase_progress = (0, 0)
        self.log = []
        self.total_scanned = 0
        self.total_discovered = 0
        self.running = False
        self.watcher_active = False

        # timing
        self.phase_start_time = None
        self.stage_start_time = None
        self.phase_timings = []
        self.stage_timings = []

    def _record_phase_end(self, now):
        if self.current_phase and self.phase_start_time:
            dur = (now - self.phase_start_time).total_seconds()
            self.phase_timings.append({
                "phase": self.current_phase,
                "start": self.phase_start_time.isoformat(),
                "end": now.isoformat(),
                "duration": round(dur, 1)
            })
            if len(self.phase_timings) > 20:
                self.phase_timings = self.phase_timings[-20:]

    def _record_stage_end(self, now):
        if self.current_stage and self.stage_start_time:
            dur = (now - self.stage_start_time).total_seconds()
            self.stage_timings.append({
                "stage": self.current_stage,
                "start": self.stage_start_time.isoformat(),
                "end": now.isoformat(),
                "duration": round(dur, 1),
                "file": self.current_file
            })
            if len(self.stage_timings) > 50:
                self.stage_timings = self.stage_timings[-50:]

    def update(self, phase=None, stage=None, file=None, counts=None, log_msg=None, progress=None):
        with self.lock:
            now = datetime.utcnow()
            if phase:
                self._record_phase_end(now)
                self.current_phase = phase
                self.phase_start_time = now
                logger.info(f"[phase] {phase}")
            if stage:
                self._record_stage_end(now)
                self.current_stage = stage
                self.stage_start_time = now
            if file:
                self.current_file = file
            if counts:
                self.stage_counts = counts
            if progress:
                self.phase_progress = progress
            if log_msg:
                self.log.append({
                    "time": now.isoformat(),
                    "msg": log_msg
                })
                if len(self.log) > 500:
                    self.log = self.log[-500:]
                # Mirror important log messages to file
                if log_msg.startswith("▶") or log_msg.startswith("✓") or log_msg.startswith("✗") or log_msg.startswith("  ⚠"):
                    logger.info(log_msg)

    def get_snapshot(self):
        with self.lock:
            now = datetime.utcnow()
            elapsed = None
            stage_elapsed = None
            if self.phase_start_time:
                elapsed = round((now - self.phase_start_time).total_seconds(), 1)
            if self.stage_start_time:
                stage_elapsed = round((now - self.stage_start_time).total_seconds(), 1)
            return {
                "stage_counts": dict(self.stage_counts),
                "current_file": self.current_file,
                "current_stage": self.current_stage,
                "current_phase": self.current_phase,
                "phase_progress": self.phase_progress,
                "log": self.log[-50:],
                "total_scanned": self.total_scanned,
                "total_discovered": self.total_discovered,
                "running": self.running,
                "watcher_active": self.watcher_active,
                "elapsed": elapsed,
                "stage_elapsed": stage_elapsed,
                "phase_timings": list(self.phase_timings),
                "stage_timings": list(self.stage_timings),
            }


state = PipelineState()


def add_to_inbox(filepath):
    dest = os.path.join(config.INBOX_DIR, os.path.basename(filepath))
    shutil.copy2(filepath, dest)
    return dest


def _walk_source(source_dir):
    """Walk a single source directory, yielding (filepath, source_group)."""
    source_group = os.path.basename(os.path.normpath(source_dir))
    if not os.path.isdir(source_dir):
        return
    for root, dirs, names in os.walk(source_dir):
        dirs[:] = [d for d in dirs if d not in config.EXCLUDE_DIRS]
        for name in names:
            ext = os.path.splitext(name)[1].lower()
            if ext in config.EXCLUDE_EXTS or ext not in config.EBOOK_EXTS:
                continue
            yield os.path.join(root, name), source_group


def count_source_files():
    """Fast pre-scan: count discoverable ebook files (no per-file processing)."""
    sources = config.SOURCE_DIRS if hasattr(config, 'SOURCE_DIRS') and config.SOURCE_DIRS else [config.SOURCE_DIR]
    count = 0
    for source_dir in sources:
        if not os.path.isdir(source_dir):
            continue
        for root, dirs, _ in os.walk(source_dir):
            dirs[:] = [d for d in dirs if d not in config.EXCLUDE_DIRS]
            with os.scandir(root) as it:
                for entry in it:
                    if entry.is_file():
                        ext = os.path.splitext(entry.name)[1].lower()
                        if ext not in config.EXCLUDE_EXTS and ext in config.EBOOK_EXTS:
                            count += 1
    return count


def discover_source_files():
    """Generator that yields (filepath, source_group) tuples from all source dirs."""
    sources = config.SOURCE_DIRS if hasattr(config, 'SOURCE_DIRS') and config.SOURCE_DIRS else [config.SOURCE_DIR]
    for source_dir in sources:
        yield from _walk_source(source_dir)


def _metadata_richness(row):
    score = 0
    for field in ("title", "authors", "isbn", "description", "publisher", "year", "language", "pages"):
        try:
            if row[field]:
                score += 1
        except (KeyError, IndexError, TypeError):
            pass
    return score


# ── Phase A: metadata pipeline (read-only on source) ──────────

def _fmt_dur(seconds):
    if seconds is None:
        return ""
    if seconds < 60:
        return f"{seconds:.1f}s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s}s"


def run_phase_metadata(source=None, inbox_files=None):
    init_db(config.DB_PATH)
    conn = get_connection(config.DB_PATH)

    if source is not None:
        config.SOURCE_DIR = source

    state.update(phase="metadata", log_msg="▶ Phase A: Metadata pipeline started")

    # Pre-scan: count discoverable files for progress tracking
    if inbox_files is not None:
        state.total_discovered = len(inbox_files)
    else:
        state.update(log_msg="  Prescanning source directory for progress tracking...")
        state.total_discovered = count_source_files()
    state.update(log_msg=f"  Total discoverable: {state.total_discovered} files")

    source_iter = inbox_files if inbox_files is not None else discover_source_files()
    processed = 0

    for item in source_iter:
        if isinstance(item, tuple):
            filepath, source_group = item
        else:
            filepath, source_group = item, None

        if not os.path.isfile(filepath):
            continue

        fname = os.path.basename(filepath)
        ext = os.path.splitext(fname)[1].lower()

        if ext in config.EXCLUDE_EXTS or ext not in config.EBOOK_EXTS:
            continue

        processed += 1
        total = max(state.total_discovered, processed)
        state.update(file=fname, stage="arriving", progress=(processed, total),
                     log_msg=f"  [{processed}/{total}] {fname}")

        h = file_hash(filepath)
        fsize = os.path.getsize(filepath)
        file_id = upsert_file(conn, filepath, fname, fsize, h, ext.lstrip("."), source_group=source_group)
        conn.commit()
        set_stage(conn, file_id, "arrived")
        conn.commit()

        state.update(stage="extracting", log_msg=f"  ▶ extracting {fname}")
        raw_meta = extract_metadata(filepath)
        if "_error" in raw_meta:
            error = raw_meta["_error"]
            set_stage(conn, file_id, "extracted", error)
            quarantine_file(conn, file_id, "EXTRACT_FAIL", error)
            conn.commit()
            state.update(log_msg=f"  ✗ extract failed — {error}")
            continue

        set_stage(conn, file_id, "extracted")
        conn.commit()

        dup = find_duplicate_by_hash(conn, h) if h else None
        if dup and dup["id"] != file_id:
            set_stage(conn, file_id, "cataloged", "duplicate_by_hash")
            conn.commit()
            state.update(log_msg=f"  ~ skipped (hash dup): {fname}")
            continue

        title = raw_meta.get("title", "")
        if title:
            existing = find_duplicate_by_title(conn, title)
            if existing and existing["id"] != file_id:
                set_stage(conn, file_id, "cataloged", "duplicate_by_title")
                conn.commit()
                state.update(log_msg=f"  ~ skipped (title dup): {fname}")
                continue

        state.update(stage="cleaning", log_msg=f"  ▶ cleaning {fname}")
        # Enrich from filename when raw metadata is sparse
        enriched = {}
        fname_stem = os.path.splitext(fname)[0]
        if not raw_meta.get("title") or not raw_meta.get("authors"):
            enriched = enrich_from_filename(fname)
        clean_title = raw_meta.get("title") or enriched.get("title") or fname_stem
        clean_authors = raw_meta.get("authors") or enriched.get("author") or ""
        year = raw_meta.get("year") or enriched.get("year") or extract_year_from_filename(fname)

        # Determine enrich source
        enrich_source = "embedded"
        if not raw_meta.get("title") and enriched.get("title"):
            enrich_source = "filename"
        elif not raw_meta.get("title") and not enriched.get("title"):
            enrich_source = "filename"  # fallback to fname_stem
        upsert_metadata(conn, file_id,
                        title=clean_title,
                        authors=clean_authors,
                        publisher=raw_meta.get("publisher"),
                        isbn=raw_meta.get("isbn"),
                        language=raw_meta.get("language"),
                        pages=raw_meta.get("pages"),
                        year=year,
                        description=raw_meta.get("description"),
                        subjects=raw_meta.get("subjects"),
                        enrich_source=enrich_source,
                        enriched_at=datetime.utcnow().isoformat())
        set_stage(conn, file_id, "cleaned")
        conn.commit()

        # Quarantine if no metadata found at all
        if not clean_title and not clean_authors:
            quarantine_file(conn, file_id, "NO_METADATA_EMPTY",
                            "Raw extraction + filename parse both returned no title or author")
            conn.commit()
            state.update(log_msg=f"  ⚠ quarantined (no metadata): {fname}")
            continue

        state.update(stage="enriching", log_msg=f"  ▶ enriching {fname}")

        # External API enrichment (only when metadata is sparse)
        if not raw_meta.get("title") or not raw_meta.get("authors") or not raw_meta.get("description"):
            try:
                enriched = enrich_book(
                    isbn=raw_meta.get("isbn"),
                    title=clean_title,
                    author=clean_authors,
                )
                if enriched:
                    api_source = enriched.get("source", "api")
                    upsert_metadata(conn, file_id,
                                    title=enriched.get("title") or None,
                                    authors=enriched.get("authors") or None,
                                    publisher=enriched.get("publisher") or None,
                                    isbn=enriched.get("isbn") or None,
                                    language=enriched.get("language") or None,
                                    pages=enriched.get("pages") or None,
                                    year=enriched.get("year") or None,
                                    description=enriched.get("description") or None,
                                    subjects=enriched.get("subjects") or None,
                                    enrich_source=api_source,
                                    enriched_at=datetime.utcnow().isoformat())
                    # Re-read for classification
                    if enriched.get("title"):
                        clean_title = enriched["title"]
                    if enriched.get("authors"):
                        clean_authors = enriched["authors"]
                    if enriched.get("year"):
                        year = enriched["year"]
                    state.update(log_msg=f"  ✓ API enriched: {fname}")
            except Exception:
                state.update(log_msg=f"  ~ API enrichment failed: {fname}")

        state.update(log_msg=f"  ▶ classifying {fname}")
        udc_code, udc_label = classify(
            raw_meta.get("title"),
            raw_meta.get("authors"),
            raw_meta.get("subjects"),
            raw_meta.get("description"),
        )
        upsert_metadata(conn, file_id, udc_code=udc_code, udc_label=udc_label)

        all_udc_tags = classify_all(
            raw_meta.get("title"),
            raw_meta.get("authors"),
            raw_meta.get("subjects"),
            raw_meta.get("description"),
        )
        set_tags(conn, file_id, all_udc_tags, tag_type="udc")

        cover_data = raw_meta.get("cover_data")
        if cover_data:
            cover_dir = os.path.join(config.PROCESSED_DIR, "covers")
            os.makedirs(cover_dir, exist_ok=True)
            cover_path = os.path.join(cover_dir, f"{file_id}.jpg")
            try:
                with open(cover_path, "wb") as cf:
                    cf.write(cover_data)
                upsert_metadata(conn, file_id, cover_path=cover_path)
            except Exception:
                pass

        set_stage(conn, file_id, "cataloged")
        conn.commit()
        state.update(log_msg=f"  ✓ cataloged {fname}")
        state.update(counts=get_pipeline_summary(conn))

    conn.close()

    elapsed = _fmt_dur(state.get_snapshot().get("elapsed"))
    state.update(phase="metadata_done", stage="idle",
                 log_msg=f"✓ Phase A complete — {processed} files processed ({elapsed})")

    final = get_connection(config.DB_PATH)
    try:
        state.update(counts=get_pipeline_summary(final))
        from db import rebuild_fts
        rebuilt = rebuild_fts(final)
        final.commit()
        state.update(log_msg=f"  ✓ FTS index rebuilt ({rebuilt} docs)")
    finally:
        final.close()


# ── Phase B: global dedup sweep ──────────────────────────────

def run_phase_dedup():
    conn = get_connection(config.DB_PATH)
    state.update(phase="dedup", log_msg="▶ Phase B: Global dedup sweep")

    try:
        files = get_cataloged_files(conn)
        total = len(files)
        state.update(log_msg=f"  {total} cataloged files loaded for dedup")

        if total == 0:
            state.update(log_msg="  (no files to deduplicate)")
            elapsed = _fmt_dur(state.get_snapshot().get("elapsed"))
            state.update(phase="dedup_done", stage="idle",
                         log_msg=f"✓ Phase B complete — 0 dedup ({elapsed})")
            return

        # ── Pass 1: hash dedup ──
        state.update(stage="dedup_hash", log_msg="  ▶ Pass 1: hash-based dedup")
        by_hash = {}
        for row in files:
            h = row["file_hash"]
            by_hash.setdefault(h, []).append(row)

        skip_ids = set()
        hash_dup_count = 0
        for h, group in by_hash.items():
            if len(group) > 1:
                group.sort(key=lambda r: -_metadata_richness(r))
                keeper = group[0]
                for dup in group[1:]:
                    mark_duplicate(conn, dup["id"], "duplicate_by_hash")
                    skip_ids.add(dup["id"])
                    hash_dup_count += 1
                    state.update(log_msg=f"    hash dup: {dup['filename']}")
        conn.commit()

        # ── Pass 2: ISBN dedup ──
        state.update(stage="dedup_isbn", log_msg="  ▶ Pass 2: ISBN-based dedup")
        survivors = [r for r in files if r["id"] not in skip_ids]
        isbn_dup_count = 0
        by_isbn = {}
        for row in survivors:
            isbn = (row["isbn"] or "").strip().replace("-", "")
            if isbn:
                by_isbn.setdefault(isbn, []).append(row)
        for isbn, group in by_isbn.items():
            if len(group) > 1:
                group.sort(key=lambda r: -_metadata_richness(r))
                keeper = group[0]
                for dup in group[1:]:
                    mark_duplicate(conn, dup["id"], "duplicate_by_isbn")
                    skip_ids.add(dup["id"])
                    isbn_dup_count += 1
                    state.update(log_msg=f"    isbn dup: {dup['filename']} ({isbn})")
        conn.commit()

        # ── Pass 3: title fuzzy dedup within same UDC ──
        state.update(stage="dedup_title", log_msg="  ▶ Pass 3: title fuzzy dedup")
        survivors = [r for r in files if r["id"] not in skip_ids]
        survivors.sort(key=lambda r: r["id"])

        title_dup_count = 0
        for i, current in enumerate(survivors):
            if current["id"] in skip_ids:
                continue
            cur_title = normalize_title(current["title"] or "")
            if not cur_title:
                continue
            cur_udc = current["udc_code"] or ""
            cur_score = _metadata_richness(current)

            for j in range(i):
                prev = survivors[j]
                if prev["id"] in skip_ids:
                    continue
                prev_title = normalize_title(prev["title"] or "")
                if not prev_title:
                    continue
                prev_udc = prev["udc_code"] or ""
                if cur_udc != prev_udc:
                    continue
                sim = title_similarity(prev_title, cur_title)
                threshold = config.DUPLICATE_SIMILARITY_THRESHOLD
                ambiguous_min = 0.70
                if sim >= threshold:
                    if cur_score <= _metadata_richness(prev):
                        mark_duplicate(conn, current["id"], "duplicate_by_title")
                        skip_ids.add(current["id"])
                        title_dup_count += 1
                        state.update(log_msg=f"    title dup vs #{prev['id']}: {current['filename']}")
                    else:
                        mark_duplicate(conn, prev["id"], "duplicate_by_title")
                        skip_ids.add(prev["id"])
                        title_dup_count += 1
                        state.update(log_msg=f"    title dup vs #{current['id']}: {prev['filename']}")
                    break
                elif sim >= ambiguous_min:
                    qdetail = f"Title sim {sim:.0%} between #{current['id']} '{cur_title[:40]}' and #{prev['id']} '{prev_title[:40]}'"
                    quarantine_file(conn, prev["id"], "DEDUP_AMBIGUOUS", qdetail)
                    quarantine_file(conn, current["id"], "DEDUP_AMBIGUOUS", qdetail)
                    conn.commit()
                    state.update(log_msg=f"  ⚠ quarantined (ambiguous dedup): {current['filename']} vs #{prev['id']}")

        conn.commit()

        # ── Pass 4: author + year + title matching ──
        state.update(stage="dedup_author_year", log_msg="  ▶ Pass 4: author+year+title dedup")
        survivors = [r for r in files if r["id"] not in skip_ids]
        survivors.sort(key=lambda r: r["id"])

        author_year_count = 0
        for i, current in enumerate(survivors):
            if current["id"] in skip_ids:
                continue
            cur_authors = (current["authors"] or "").strip().lower()
            cur_year = current["year"]
            cur_title = normalize_title(current["title"] or "")
            if not cur_title or not cur_authors or not cur_year:
                continue
            cur_score = _metadata_richness(current)

            for j in range(i):
                prev = survivors[j]
                if prev["id"] in skip_ids:
                    continue
                prev_authors = (prev["authors"] or "").strip().lower()
                prev_year = prev["year"]
                prev_title = normalize_title(prev["title"] or "")
                if not prev_title or not prev_authors or not prev_year:
                    continue
                if cur_authors != prev_authors or cur_year != prev_year:
                    continue
                if is_duplicate_title(prev_title, cur_title, config.DUPLICATE_SIMILARITY_THRESHOLD):
                    if cur_score <= _metadata_richness(prev):
                        mark_duplicate(conn, current["id"], "duplicate_by_author_year_title")
                        skip_ids.add(current["id"])
                        author_year_count += 1
                        state.update(log_msg=f"    author+year+title dup vs #{prev['id']}: {current['filename']}")
                    else:
                        mark_duplicate(conn, prev["id"], "duplicate_by_author_year_title")
                        skip_ids.add(prev["id"])
                        author_year_count += 1
                        state.update(log_msg=f"    author+year+title dup vs #{current['id']}: {prev['filename']}")
                    break

        conn.commit()

        # ── Mark survivors ──
        state.update(stage="survivor_mark", log_msg="  ▶ marking survivors")
        survivor_count = 0
        for row in files:
            if row["id"] not in skip_ids:
                mark_survivor(conn, row["id"])
                survivor_count += 1
        conn.commit()

        total_skipped = total - survivor_count
        elapsed = _fmt_dur(state.get_snapshot().get("elapsed"))
        state.update(log_msg=f"  ✓ {survivor_count} survivors, {total_skipped} skipped "
                             f"({hash_dup_count} hash + {isbn_dup_count} isbn + "
                             f"{title_dup_count} title + {author_year_count} author+year)")
        state.update(counts=get_phase_counts(conn))

    finally:
        conn.close()
        elapsed = _fmt_dur(state.get_snapshot().get("elapsed"))
        state.update(phase="dedup_done", stage="idle",
                     log_msg=f"✓ Phase B complete ({elapsed})")


# ── Phase C: copy survivors to flat folder ───────────────────

def run_phase_copy():
    conn = get_connection(config.DB_PATH)

    try:
        survivors = get_survivors(conn)
        total = len(survivors)
        state.update(phase="copy", log_msg=f"▶ Phase C: Copying {total} survivors to flat folder")

        if total == 0:
            elapsed = _fmt_dur(state.get_snapshot().get("elapsed"))
            state.update(phase="copy_done", stage="idle",
                         log_msg=f"✓ Phase C complete — 0 copies ({elapsed})")
            return

        out_dir = config.FLAT_DIR
        os.makedirs(out_dir, exist_ok=True)

        valid_exts = {f".{f}" for f in set()}
        valid_exts.update(config.EBOOK_EXTS)

        copied = 0
        skipped_ext = 0
        errors = 0
        for idx, row in enumerate(survivors):
            ext = os.path.splitext(row["source_path"])[1].lower()
            if ext not in valid_exts:
                skipped_ext += 1
                state.update(log_msg=f"  ~ skipped (non-ebook): {row['filename']} ({ext})")
                continue

            fname = os.path.basename(row["filename"])
            clean_name = clean_filename(fname)
            dest = os.path.join(out_dir, clean_name)

            if os.path.exists(dest):
                base, ext = os.path.splitext(clean_name)
                dest = os.path.join(out_dir, f"{base}_{row['id']}{ext}")

            state.update(stage="copying", file=fname, progress=(idx + 1, total),
                         log_msg=f"  [{idx+1}/{total}] {fname} → {clean_name}")

            try:
                shutil.copy2(row["source_path"], dest)
                now = datetime.utcnow().isoformat()
                conn.execute("UPDATE files SET stage='copied', updated_at=? WHERE id=?",
                             (now, row["id"]))
                conn.execute("INSERT INTO pipeline_log (file_id, stage, status, message) VALUES (?,?,?,?)",
                             (row["id"], "copied", "done", ""))
                copied += 1
            except Exception as e:
                conn.execute("INSERT INTO pipeline_log (file_id, stage, status, message) VALUES (?,?,?,?)",
                             (row["id"], "copied", "failed", str(e)))
                errors += 1

        conn.commit()
        elapsed = _fmt_dur(state.get_snapshot().get("elapsed"))
        state.update(log_msg=f"  ✓ {copied} copied, {errors} failed, {skipped_ext} skipped ({elapsed})")
        state.update(counts=get_phase_counts(conn))

    finally:
        conn.close()
        elapsed = _fmt_dur(state.get_snapshot().get("elapsed"))
        state.update(phase="copy_done", stage="idle",
                     log_msg=f"✓ Phase C complete ({elapsed})")


# ── Combined run (metadata + dedup only; copy is separate) ───

def run_pipeline(source=None, inbox_files=None):
    state.running = True
    init_db(config.DB_PATH)
    try:
        state.update(log_msg="━━━ Pipeline: Metadata + Dedup ━━━")
        run_phase_metadata(source, inbox_files)
        run_phase_dedup()
    finally:
        state.running = False
        elapsed = _fmt_dur(state.get_snapshot().get("elapsed"))
        state.update(log_msg=f"✓ Pipeline (metadata+dedup) finished ({elapsed})")

def run_all_phases(source=None, inbox_files=None):
    """Run metadata + dedup + copy sequentially."""
    state.running = True
    init_db(config.DB_PATH)
    try:
        state.update(log_msg="━━━ Pipeline: Metadata + Dedup + Copy ━━━")
        run_phase_metadata(source, inbox_files)
        run_phase_dedup()
        run_phase_copy()
        # Move originals out of source dir
        if source:
            cleanup_source_dir(source)
    finally:
        state.running = False
        elapsed = _fmt_dur(state.get_snapshot().get("elapsed"))
        state.update(log_msg=f"✓ Full pipeline complete ({elapsed})")


def cleanup_source_dir(source_dir):
    """Move processed originals from source_dir to PROCESSED_DIR / ARCHIVE_DIR."""
    if not source_dir or not os.path.isdir(source_dir):
        return
    conn = get_connection(config.DB_PATH)
    try:
        norm_source = os.path.normpath(source_dir)
        # Resolve the real device path so Z:\books and \\raspberrypi\...\books compare equal
        real_source = os.path.realpath(norm_source)

        all_files = conn.execute(
            "SELECT id, source_path, stage FROM files"
        ).fetchall()
        rows = []
        for f in all_files:
            sp = f["source_path"]
            if not sp:
                continue
            if not os.path.isfile(sp):
                continue
            # Check if this file lives under source_dir (handles drive ↔ UNC mismatch)
            try:
                real_sp = os.path.realpath(sp)
                os.path.relpath(real_sp, real_source)  # throws ValueError if different drives
                rows.append(f)
            except ValueError:
                continue

        if not rows:
            return

        processed_dir = getattr(config, "PROCESSED_DIR", config.FLAT_DIR)
        archive_dir = getattr(config, "ARCHIVE_DIR", os.path.join(processed_dir, "archive"))
        os.makedirs(processed_dir, exist_ok=True)
        os.makedirs(archive_dir, exist_ok=True)

        moved_proc = 0
        moved_arch = 0
        errors = 0
        for row in rows:
            sp = row["source_path"]
            if not sp or not os.path.isfile(sp):
                continue
            norm_sp = os.path.realpath(sp)
            try:
                rel = os.path.relpath(norm_sp, real_source)
            except ValueError:
                rel = os.path.basename(norm_sp)
            if row["stage"] == "copied":
                dest_dir = os.path.join(processed_dir, os.path.dirname(rel))
            else:
                dest_dir = os.path.join(archive_dir, os.path.dirname(rel))
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, os.path.basename(rel))
            if os.path.exists(dest):
                base, ext = os.path.splitext(os.path.basename(rel))
                dest = os.path.join(dest_dir, f"{base}_{row['id']}{ext}")
            try:
                shutil.move(sp, dest)
                if row["stage"] == "copied":
                    moved_proc += 1
                else:
                    moved_arch += 1
            except Exception as e:
                logger.warning(f"cleanup: failed to move {sp}: {e}")
                errors += 1

        if moved_proc or moved_arch:
            state.update(log_msg=f"  📦 Cleanup: {moved_proc} → processed, {moved_arch} → archive, {errors} errors")
    finally:
        conn.close()
