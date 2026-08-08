import os
import shutil
import json
import threading
import tempfile
import logging
from datetime import datetime

import config
from db import get_connection, init_db, upsert_file, upsert_metadata, set_stage
from log_utils import setup_logger

logger = setup_logger("pipeline", also_stdout=False)
from db import find_duplicate_by_hash, find_duplicate_by_title, get_pipeline_summary, trim_pipeline_log
from db import get_cataloged_files, mark_duplicate, mark_survivor, get_survivors, get_phase_counts
from db import set_tags, quarantine_file, QUARANTINE_ERRORS
from extractors import extract_metadata
from filename_cleaner import clean_filename, extract_year_from_filename, file_hash, is_duplicate_title, normalize_title, title_similarity
from enrich_filename import enrich_from_filename
from enricher import enrich_book, _download_cover
from classifier import classify, classify_all


class PipelineState:
    _persist_path = None

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

    def _persist(self):
        if not self._persist_path:
            return
        try:
            import json
            data = {
                "stage_counts": dict(self.stage_counts),
                "current_file": self.current_file,
                "current_stage": self.current_stage,
                "current_phase": self.current_phase,
                "phase_progress": self.phase_progress,
                "total_scanned": self.total_scanned,
                "total_discovered": self.total_discovered,
                "running": self.running,
                "log": [e for e in self.log[-50:]],
            }
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=os.path.dirname(self._persist_path), delete=False) as f:
                json.dump(data, f)
                tmp = f.name
            os.replace(tmp, self._persist_path)
        except Exception as e:
            logger.warning(f"state persist failed: {e}")

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
            self._persist()

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
state._persist_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "pipeline_state.json")


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
        config.SOURCE_DIRS = [source]

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

        try:
            h = file_hash(filepath)
            fsize = os.path.getsize(filepath)
        except (OSError, FileNotFoundError):
            state.update(log_msg=f"  ~ skipped (vanished): {fname}")
            continue
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
        subjects = raw_meta.get("subjects")
        if isinstance(subjects, list):
            subjects = "; ".join(subjects)
        upsert_metadata(conn, file_id,
                        title=clean_title,
                        authors=clean_authors,
                        publisher=raw_meta.get("publisher"),
                        isbn=raw_meta.get("isbn"),
                        language=raw_meta.get("language"),
                        pages=raw_meta.get("pages"),
                        year=year,
                        description=raw_meta.get("description"),
                        subjects=subjects,
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

        # External API enrichment (when key metadata is missing)
        enriched = None
        need_enrich = (
            not raw_meta.get("title") or not raw_meta.get("authors")
            or not raw_meta.get("description") or not raw_meta.get("isbn")
            or not raw_meta.get("publisher")
        )
        if need_enrich:
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

        # Download cover from API if no embedded cover exists
        try:
            row_meta = conn.execute("SELECT cover_path FROM metadata WHERE file_id=?", (file_id,)).fetchone()
            if not row_meta or not row_meta["cover_path"]:
                cover_url = enriched.get("cover_url") if enriched else None
                if cover_url:
                    cover_dir = os.path.join(config.PROCESSED_DIR, "covers")
                    downloaded = _download_cover(cover_url, cover_dir)
                    if downloaded:
                        upsert_metadata(conn, file_id, cover_path=downloaded)
        except Exception as e:
            logger.warning("cover download failed for file_id=%s: %s", file_id, e)

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
        state.update(stage="dedup_hash", progress=[0, total], log_msg="  ▶ Pass 1: hash-based dedup")
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
                    mark_duplicate(conn, dup["id"], "duplicate_by_hash", master_id=keeper["id"])
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
                    mark_duplicate(conn, dup["id"], "duplicate_by_isbn", master_id=keeper["id"])
                    skip_ids.add(dup["id"])
                    isbn_dup_count += 1
                    state.update(log_msg=f"    isbn dup: {dup['filename']} ({isbn})")
        conn.commit()

        # ── Pass 3: title fuzzy dedup within same UDC ──
        state.update(stage="dedup_title", log_msg="  ▶ Pass 3: title fuzzy dedup")
        survivors = [r for r in files if r["id"] not in skip_ids]
        survivors.sort(key=lambda r: r["id"])

        # Group survivors by UDC for O(n) within-group comparison
        udc_groups = {}
        for r in survivors:
            udc = r["udc_code"] or ""
            udc_groups.setdefault(udc, []).append(r)

        threshold = config.DUPLICATE_SIMILARITY_THRESHOLD
        ambiguous_min = 0.85

        title_dup_count = 0
        total_survivors = len(survivors)
        checked = 0
        for udc, group in udc_groups.items():
            for i, current in enumerate(group):
                if current["id"] in skip_ids:
                    continue
                cur_title = normalize_title(current["title"] or "")
                if not cur_title:
                    continue
                cur_score = _metadata_richness(current)
                cur_first4 = cur_title[:4]
                cur_len = len(cur_title)

                for j in range(i):
                    prev = group[j]
                    if prev["id"] in skip_ids:
                        continue
                    prev_title = normalize_title(prev["title"] or "")
                    if not prev_title:
                        continue
                    # Fast pre-filter: skip if titles differ too much in length or prefix
                    if abs(cur_len - len(prev_title)) > max(cur_len // 3, 10):
                        continue
                    if cur_first4 and prev_title[:4] != cur_first4:
                        continue
                    # Also require same author for title dedup
                    if (current["authors"] or "").strip().lower() != (prev["authors"] or "").strip().lower():
                        continue
                    sim = title_similarity(prev_title, cur_title)
                    if sim >= threshold:
                        if cur_score <= _metadata_richness(prev):
                            mark_duplicate(conn, current["id"], "duplicate_by_title", master_id=prev["id"])
                            skip_ids.add(current["id"])
                            title_dup_count += 1
                            state.update(log_msg=f"    title dup vs #{prev['id']}: {current['filename']}")
                        else:
                            mark_duplicate(conn, prev["id"], "duplicate_by_title", master_id=current["id"])
                            skip_ids.add(prev["id"])
                            title_dup_count += 1
                            state.update(log_msg=f"    title dup vs #{current['id']}: {prev['filename']}")
                        break
                    elif sim >= ambiguous_min:
                        state.update(log_msg=f"  ~ title ambiguous ({sim:.0%}): {current['filename'][:60]} vs {prev['filename'][:60]}")
                checked += 1
                if checked % 1000 == 0:
                    conn.commit()
                    state.update(progress=[checked, total_survivors], log_msg=f"  title dedup: {checked}/{total_survivors} checked, {title_dup_count} dups found")

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
                        mark_duplicate(conn, current["id"], "duplicate_by_author_year_title", master_id=prev["id"])
                        skip_ids.add(current["id"])
                        author_year_count += 1
                        state.update(log_msg=f"    author+year+title dup vs #{prev['id']}: {current['filename']}")
                    else:
                        mark_duplicate(conn, prev["id"], "duplicate_by_author_year_title", master_id=current["id"])
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

def _acquire_lock():
    """Try to acquire a cross-process pipeline lock. Returns True if acquired."""
    lock_path = os.path.join(config.DATA_DIR, "pipeline.lock")
    try:
        if os.path.exists(lock_path):
            with open(lock_path, "r") as f:
                old_pid = int(f.read().strip())
            try:
                os.kill(old_pid, 0)  # Check if process still exists
                logger.warning(f"Pipeline lock held by PID {old_pid} — refusing concurrent run")
                return False
            except (OSError, ProcessLookupError):
                pass  # Stale lock
        with open(lock_path, "w") as f:
            f.write(str(os.getpid()))
        return True
    except Exception as e:
        logger.error(f"Failed to acquire pipeline lock: {e}")
        return False

def _release_lock():
    lock_path = os.path.join(config.DATA_DIR, "pipeline.lock")
    try:
        if os.path.exists(lock_path):
            os.remove(lock_path)
    except Exception as e:
        logger.error(f"Failed to release pipeline lock: {e}")

def run_pipeline(source=None, inbox_files=None):
    if not _acquire_lock():
        state.update(log_msg="✗ Pipeline already running — concurrent run refused")
        return
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
        _release_lock()

def run_phase_enrich(limit=500):
    """Refresh missing metadata for already-catalogued books.

    Targets books that lack a cover (no cover_path, or the cover file is gone
    from disk), a description, or a title, and fills gaps from Open Library +
    Google Books, downloading cover images. Uses the enrich cache + rate limit.
    """
    if not _acquire_lock():
        state.update(log_msg="✗ Pipeline already running — concurrent run refused")
        return
    state.running = True
    init_db(config.DB_PATH)
    conn = get_connection(config.DB_PATH)
    try:
        state.update(phase="enrich", log_msg="▶ Enrich: refreshing missing metadata started")

        covers_dir = os.path.join(os.path.dirname(config.DB_PATH), "covers")
        os.makedirs(covers_dir, exist_ok=True)

        rows = conn.execute("""
            SELECT f.id, f.is_master,
                   m.title, m.authors, m.isbn, m.description, m.publisher, m.year, m.cover_path
            FROM files f
            LEFT JOIN metadata m ON m.file_id = f.id
            WHERE m.file_id IS NULL
               OR m.cover_path IS NULL OR m.cover_path = ''
               OR m.description IS NULL OR m.description = ''
               OR m.title IS NULL OR m.title = ''
            ORDER BY f.is_master DESC, f.id
            LIMIT ?
        """, (limit,)).fetchall()

        candidates = []
        for row in rows:
            r = dict(row)
            r["_cover_gone"] = bool(r["cover_path"]) and not os.path.isfile(r["cover_path"])
            if (not r["title"] or not r["description"]
                    or not r["cover_path"] or r["_cover_gone"]):
                candidates.append(r)

        state.update(log_msg=f"  {len(candidates)} book(s) need metadata refresh")
        updated = cover_hits = unchanged = failed = 0
        total = max(len(candidates), 1)

        for i, r in enumerate(candidates):
            label = r["title"] or r["isbn"] or f"book #{r['id']}"
            state.update(stage="enriching", progress=(i + 1, total),
                         log_msg=f"  [{i + 1}/{total}] {label}")

            need_cover = not r["cover_path"] or r["_cover_gone"]
            try:
                enriched = enrich_book(isbn=r["isbn"] or None,
                                       title=r["title"] or None,
                                       author=r["authors"] or None)
                if not enriched:
                    unchanged += 1
                    continue

                kw = {}
                if not r["title"] and enriched.get("title"):
                    kw["title"] = enriched["title"]
                if not r["authors"] and enriched.get("authors"):
                    kw["authors"] = enriched["authors"]
                if not r["publisher"] and enriched.get("publisher"):
                    kw["publisher"] = enriched["publisher"]
                if not r["isbn"] and enriched.get("isbn"):
                    kw["isbn"] = enriched["isbn"]
                if not r["year"] and enriched.get("year"):
                    kw["year"] = enriched["year"]
                if not r["description"] and enriched.get("description"):
                    kw["description"] = enriched["description"]

                cover_path = None
                if need_cover and enriched.get("cover_url"):
                    cover_path = _download_cover(enriched["cover_url"], covers_dir)
                    if cover_path:
                        kw["cover_path"] = cover_path
                        cover_hits += 1

                if kw:
                    upsert_metadata(conn, r["id"],
                                    enrich_source=enriched.get("source"),
                                    enriched_at=datetime.utcnow().isoformat(),
                                    **kw)
                    conn.commit()
                    updated += 1
                else:
                    unchanged += 1
                state.update(log_msg=f"  ✓ {label}")
            except Exception as e:
                failed += 1
                logger.warning("enrich failed for file_id=%s: %s", r["id"], e)
                state.update(log_msg=f"  ✗ {label}: {e}")

        state.update(log_msg=(
            f"✓ Enrich complete ({_fmt_dur(state.get_snapshot().get('elapsed'))}): "
            f"{updated} updated, {cover_hits} covers, {unchanged} unchanged, {failed} failed"))
    finally:
        conn.close()
        state.running = False
        _release_lock()


def run_all_phases(source=None, inbox_files=None):
    """Run metadata + dedup + copy sequentially."""
    if not _acquire_lock():
        state.update(log_msg="✗ Pipeline already running — concurrent run refused")
        return
    state.running = True
    init_db(config.DB_PATH)
    try:
        state.update(log_msg="━━━ Pipeline: Metadata + Dedup + Copy ━━━")
        run_phase_metadata(source, inbox_files)
        run_phase_dedup()
        try:
            run_phase_copy()
        except Exception:
            # Compensating tx: revert uncopied survivors back to cataloged (D7.31)
            logger.warning("Phase C (copy) failed — compensating")
            state.update(log_msg="✗ Phase C failed — compensating: reverting uncopied books to cataloged")
            comp = get_connection(config.DB_PATH)
            try:
                comp.execute("UPDATE files SET stage='cataloged' WHERE stage='survivor'")
                comp.commit()
            finally:
                comp.close()
            raise
        # Move originals out of source dir
        if source:
            cleanup_source_dir(source)
    finally:
        state.running = False
        elapsed = _fmt_dur(state.get_snapshot().get("elapsed"))
        state.update(log_msg=f"✓ Full pipeline complete ({elapsed})")
        _release_lock()


def cleanup_source_dir(source_dir):
    """Move processed originals from source_dir to PROCESSED_DIR / ARCHIVE_DIR."""
    if not source_dir or not os.path.isdir(source_dir):
        return
    conn = get_connection(config.DB_PATH)
    try:
        norm_source = os.path.normpath(source_dir)
        real_source = os.path.realpath(norm_source)

        like_pattern = norm_source.rstrip("/\\") + "%"
        rows = conn.execute(
            "SELECT id, source_path, stage FROM files WHERE source_path LIKE ?",
            (like_pattern,)
        ).fetchall()
        matched = []
        for f in rows:
            sp = f["source_path"]
            if not sp:
                continue
            try:
                real_sp = os.path.realpath(sp)
                os.path.relpath(real_sp, real_source)
                matched.append(f)
            except ValueError:
                continue

        if not matched:
            return

        processed_dir = getattr(config, "PROCESSED_DIR", config.FLAT_DIR)
        archive_dir = getattr(config, "ARCHIVE_DIR", os.path.join(processed_dir, "archive"))
        os.makedirs(processed_dir, exist_ok=True)
        os.makedirs(archive_dir, exist_ok=True)

        moved_proc = 0
        moved_arch = 0
        errors = 0
        for row in matched:
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

        removed_dirs = 0
        for dirpath, dirnames, filenames in os.walk(source_dir, topdown=False):
            if os.path.normpath(dirpath) == os.path.normpath(source_dir):
                continue
            try:
                if not os.listdir(dirpath):
                    os.rmdir(dirpath)
                    removed_dirs += 1
            except OSError:
                pass
        if removed_dirs:
            state.update(log_msg=f"  🗑 Cleanup: removed {removed_dirs} empty directories")
    finally:
        conn.close()


# ── Phase Recon: coherence audit ─────────────────────────

def run_recon():
    """Audit DB/filesystem coherence: check all books and directories match up."""
    init_db(config.DB_PATH)
    trim_pipeline_log(config.DB_PATH, days=90)
    conn = get_connection(config.DB_PATH)
    state.update(phase="recon", stage="scanning", log_msg="▶ Recon: coherence audit")
    result = {"summary": {}, "directories": {}, "db_integrity": {}, "anomalies": []}

    try:
        inbox = getattr(config, "WATCH_DIR", config.INBOX_DIR)
        processed = getattr(config, "PROCESSED_DIR", config.FLAT_DIR)
        archive = getattr(config, "ARCHIVE_DIR", os.path.join(processed, "archive")) if processed else None

        for label, scan_dir in [("to_be_sorted", inbox), ("processed", processed), ("archive", archive)]:
            if not scan_dir or not os.path.isdir(scan_dir):
                result["directories"][label] = {"error": "not found"}
                continue
            files_found = []
            for dirpath, _, filenames in os.walk(scan_dir):
                for f in filenames:
                    ext = os.path.splitext(f)[1].lower()
                    if ext in config.EBOOK_EXTS:
                        files_found.append(os.path.join(dirpath, f))
            in_db = []
            not_in_db = []
            for fp in files_found:
                norm = os.path.normpath(fp)
                row = conn.execute("SELECT id FROM files WHERE source_path=?", (norm,)).fetchone()
                if row:
                    in_db.append({"id": row["id"], "path": norm})
                else:
                    not_in_db.append(norm)
            result["directories"][label] = {
                "files_found": len(files_found),
                "in_db": len(in_db),
                "not_in_db": len(not_in_db),
            }
            if not_in_db:
                result["anomalies"].append(f"{label}: {len(not_in_db)} file(s) on disk but not in DB")
            if len(not_in_db) <= 20:
                result["directories"][label]["orphans"] = not_in_db

        all_rows = conn.execute("SELECT id, source_path, stage FROM files").fetchall()
        result["summary"]["total_db_books"] = len(all_rows)
        result["summary"]["total_masters"] = conn.execute("SELECT COUNT(*) FROM files WHERE is_master=1").fetchone()[0]
        result["summary"]["total_duplicates"] = conn.execute("SELECT COUNT(*) FROM files WHERE is_master=0").fetchone()[0]
        stages = conn.execute("SELECT stage, COUNT(*) as c FROM files GROUP BY stage ORDER BY c DESC").fetchall()
        result["summary"]["by_stage"] = {r["stage"]: r["c"] for r in stages}

        missing_source = 0
        for row in all_rows:
            bid, sp, stage = row["id"], row["source_path"], row["stage"]
            if sp and not os.path.isfile(sp):
                missing_source += 1
                if missing_source <= 10:
                    result["anomalies"].append(f"Book #{bid}: source_path not on disk ({sp})")

        result["db_integrity"]["missing_source"] = missing_source

        # Cover integrity: check cover_path existence + orphaned cover files
        covers_dir = os.path.join(os.path.dirname(config.DB_PATH), "covers")
        missing_covers = 0
        orphaned_covers = 0
        if os.path.isdir(covers_dir):
            on_disk = set()
            for fname in os.listdir(covers_dir):
                if fname.endswith(".jpg"):
                    on_disk.add(fname)
            cover_rows = conn.execute("SELECT file_id, cover_path FROM metadata WHERE cover_path IS NOT NULL").fetchall()
            for row in cover_rows:
                if row["cover_path"] and not os.path.isfile(row["cover_path"]):
                    missing_covers += 1
                    if missing_covers <= 10:
                        result["anomalies"].append(f"Book #{row['file_id']}: cover_path not on disk ({row['cover_path']})")
            in_db_md5 = set()
            for row in cover_rows:
                if row["cover_path"]:
                    fname = os.path.basename(row["cover_path"])
                    in_db_md5.add(fname)
            orphaned_covers = len(on_disk - in_db_md5)
            if orphaned_covers > 0:
                result["anomalies"].append(f"{orphaned_covers} cover file(s) on disk but not referenced by any book")
        result["db_integrity"]["missing_covers"] = missing_covers
        result["db_integrity"]["orphaned_covers"] = orphaned_covers

        state.update(log_msg=f"✓ Recon complete — {result['summary']['total_db_books']} books, {len(result['anomalies'])} anomalies")
        return result
    finally:
        conn.close()
