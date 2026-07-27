import sqlite3
import os
import json
import uuid
from datetime import datetime


def get_connection(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path):
    conn = get_connection(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS files (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            uuid            TEXT UNIQUE,
            source_path     TEXT NOT NULL UNIQUE,
            filename        TEXT NOT NULL,
            file_size       INTEGER,
            file_hash       TEXT,
            format          TEXT,
            stage           TEXT DEFAULT 'arrived',
            stage_error     TEXT,
            is_master       INTEGER,
            source_group    TEXT,
            created_at      TEXT DEFAULT (datetime('now')),
            updated_at      TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS metadata (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id         INTEGER NOT NULL UNIQUE,
            title           TEXT,
            authors         TEXT,
            publisher       TEXT,
            isbn            TEXT,
            language        TEXT,
            pages           INTEGER,
            year            INTEGER,
            description     TEXT,
            subjects        TEXT,
            udc_code        TEXT,
            udc_label       TEXT,
            cover_path      TEXT,
            enrich_source   TEXT,
            enriched_at     TEXT,
            FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS pipeline_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id         INTEGER,
            stage           TEXT NOT NULL,
            status          TEXT NOT NULL,
            message         TEXT,
            timestamp       TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS tags (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id         INTEGER NOT NULL,
            tag             TEXT NOT NULL,
            tag_type        TEXT NOT NULL DEFAULT 'udc',
            tag_label       TEXT,
            score           REAL,
            FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_files_stage ON files(stage);
        CREATE INDEX IF NOT EXISTS idx_files_hash ON files(file_hash);
        CREATE INDEX IF NOT EXISTS idx_files_uuid ON files(uuid);
        CREATE INDEX IF NOT EXISTS idx_files_master ON files(is_master);
        CREATE INDEX IF NOT EXISTS idx_metadata_udc ON metadata(udc_code);
        CREATE INDEX IF NOT EXISTS idx_tags_file ON tags(file_id);
        CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag);
        CREATE INDEX IF NOT EXISTS idx_metadata_year ON metadata(year);

        CREATE VIRTUAL TABLE IF NOT EXISTS books_fts USING fts5(
            title, authors, description, publisher, isbn,
            tokenize='porter unicode61'
        );
    """)
    # Migration: add source_group if not present
    try:
        conn.execute("ALTER TABLE files ADD COLUMN source_group TEXT")
    except Exception:
        pass

    # Migration: add master_id (pointer to original book for duplicates)
    try:
        conn.execute("ALTER TABLE files ADD COLUMN master_id INTEGER REFERENCES files(id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_files_master_id ON files(master_id)")
    except Exception:
        pass

    # Daemon status table for IPC (headless daemon ↔ API)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daemon_status (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            job_type     TEXT NOT NULL,
            status       TEXT NOT NULL DEFAULT 'idle',
            pid          INTEGER,
            current_file TEXT,
            current_stage TEXT,
            current_phase TEXT,
            progress     TEXT,
            error        TEXT,
            started_at   TEXT,
            updated_at   TEXT DEFAULT (datetime('now'))
        )
    """)

    # Quarantine table for manual intervention workflow
    conn.execute("""
        CREATE TABLE IF NOT EXISTS quarantined (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id     INTEGER NOT NULL UNIQUE REFERENCES files(id),
            error_code  TEXT NOT NULL,
            detail      TEXT,
            reviewed    INTEGER DEFAULT 0,
            reviewed_at TEXT,
            user_notes  TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        )
    """)

    ensure_reading_tables(conn)

    conn.commit()
    conn.close()
    # Re-open and re-init to ensure all migrations are applied
    conn = get_connection(db_path)
    # Migration: quarantined table (if old schema didn't have it)
    try:
        conn.execute("SELECT 1 FROM quarantined LIMIT 1")
    except Exception:
        conn.execute("""
            CREATE TABLE quarantined (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id     INTEGER NOT NULL UNIQUE REFERENCES files(id),
                error_code  TEXT NOT NULL,
                detail      TEXT,
                reviewed    INTEGER DEFAULT 0,
                reviewed_at TEXT,
                user_notes  TEXT,
                created_at  TEXT DEFAULT (datetime('now'))
            )
        """)
    conn.commit()
    conn.close()


def upsert_file(conn, source_path, filename, file_size, file_hash, fmt, source_group=None):
    now = datetime.utcnow().isoformat()
    book_uuid = uuid.uuid4().hex[:12]
    conn.execute("""
        INSERT INTO files (uuid, source_path, filename, file_size, file_hash, format, source_group, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_path) DO UPDATE SET
            uuid          = COALESCE(files.uuid, excluded.uuid),
            filename      = excluded.filename,
            file_size     = excluded.file_size,
            file_hash     = excluded.file_hash,
            format        = excluded.format,
            source_group  = COALESCE(excluded.source_group, files.source_group),
            updated_at    = excluded.updated_at
    """, (book_uuid, source_path, filename, file_size, file_hash, fmt, source_group, now, now))
    return conn.execute("SELECT id FROM files WHERE source_path = ?", (source_path,)).fetchone()["id"]


def upsert_metadata(conn, file_id, **kw):
    def _str(v):
        if isinstance(v, list):
            return "; ".join(str(x) for x in v)
        return v
    conn.execute("""
        INSERT INTO metadata (file_id, title, authors, publisher, isbn, language, pages, year, description, subjects, udc_code, udc_label, cover_path, enrich_source, enriched_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(file_id) DO UPDATE SET
            title       = COALESCE(excluded.title, metadata.title),
            authors     = COALESCE(excluded.authors, metadata.authors),
            publisher   = COALESCE(excluded.publisher, metadata.publisher),
            isbn        = COALESCE(excluded.isbn, metadata.isbn),
            language    = COALESCE(excluded.language, metadata.language),
            pages       = COALESCE(excluded.pages, metadata.pages),
            year        = COALESCE(excluded.year, metadata.year),
            description = COALESCE(excluded.description, metadata.description),
            subjects    = COALESCE(excluded.subjects, metadata.subjects),
            udc_code    = COALESCE(excluded.udc_code, metadata.udc_code),
            udc_label   = COALESCE(excluded.udc_label, metadata.udc_label),
            cover_path  = COALESCE(excluded.cover_path, metadata.cover_path),
            enrich_source = COALESCE(excluded.enrich_source, metadata.enrich_source),
            enriched_at   = COALESCE(excluded.enriched_at, metadata.enriched_at)
    """, (
        file_id, _str(kw.get("title")), _str(kw.get("authors")), _str(kw.get("publisher")),
        _str(kw.get("isbn")), _str(kw.get("language")), kw.get("pages"), kw.get("year"),
        _str(kw.get("description")), _str(kw.get("subjects")), _str(kw.get("udc_code")),
        _str(kw.get("udc_label")), _str(kw.get("cover_path")), _str(kw.get("enrich_source")),
        _str(kw.get("enriched_at"))
    ))


def set_stage(conn, file_id, stage, error=None):
    now = datetime.utcnow().isoformat()
    conn.execute("UPDATE files SET stage=?, stage_error=?, updated_at=? WHERE id=?",
                 (stage, error, now, file_id))
    status = "failed" if error else "done"
    conn.execute("INSERT INTO pipeline_log (file_id, stage, status, message) VALUES (?,?,?,?)",
                 (file_id, stage, status, error or ""))


def get_pipeline_summary(conn):
    rows = conn.execute("""
        SELECT stage, COUNT(*) as count FROM files GROUP BY stage
    """).fetchall()
    summary = {r["stage"]: r["count"] for r in rows}
    for s in ("arrived", "extracted", "cleaned", "cataloged",
              "survivor", "skipped", "copied"):
        summary.setdefault(s, 0)
    return summary


def get_recent_books(conn, limit=50):
    return conn.execute("""
        SELECT f.id, f.filename, f.format, f.stage, f.source_path,
               m.title, m.authors, m.udc_code, m.udc_label, m.year
        FROM files f
        LEFT JOIN metadata m ON m.file_id = f.id
        ORDER BY f.updated_at DESC LIMIT ?
    """, (limit,)).fetchall()


def get_book_by_id(conn, book_id):
    return conn.execute("""
        SELECT f.*, m.* FROM files f
        LEFT JOIN metadata m ON m.file_id = f.id
        WHERE f.id = ?
    """, (book_id,)).fetchone()


def find_duplicate_by_hash(conn, file_hash):
    return conn.execute("SELECT id, source_path FROM files WHERE file_hash = ?", (file_hash,)).fetchone()


def find_duplicate_by_title(conn, title):
    return conn.execute("""
        SELECT f.id, f.source_path, m.title FROM files f
        JOIN metadata m ON m.file_id = f.id
        WHERE LOWER(m.title) = LOWER(?) AND m.title IS NOT NULL
    """, (title,)).fetchone()


def get_pipeline_log(conn, limit=100):
    return conn.execute("""
        SELECT pl.*, f.filename FROM pipeline_log pl
        JOIN files f ON f.id = pl.file_id
        ORDER BY pl.timestamp DESC LIMIT ?
    """, (limit,)).fetchall()


# ── Phase B: batch dedup helpers ──────────────────────────────

def get_cataloged_files(conn):
    """Return all files at 'cataloged' stage with their metadata (may be sparse)."""
    return conn.execute("""
        SELECT f.id, f.source_path, f.filename, f.file_hash, f.file_size, f.format,
               m.title, m.authors, m.year, m.isbn, m.description, m.publisher,
               m.language, m.pages, m.subjects, m.udc_code, m.udc_label
        FROM files f
        LEFT JOIN metadata m ON m.file_id = f.id
        WHERE f.stage = 'cataloged'
        ORDER BY f.id
    """).fetchall()


def mark_duplicate(conn, file_id, reason, master_id=None):
    now = datetime.utcnow().isoformat()
    conn.execute("UPDATE files SET stage='skipped', stage_error=?, is_master=0, master_id=?, updated_at=? WHERE id=?",
                 (reason, master_id, now, file_id))
    conn.execute("INSERT INTO pipeline_log (file_id, stage, status, message) VALUES (?,?,?,?)",
                 (file_id, 'skipped', 'done', reason))


def mark_survivor(conn, file_id):
    now = datetime.utcnow().isoformat()
    conn.execute("UPDATE files SET stage='survivor', is_master=1, updated_at=? WHERE id=?",
                 (now, file_id))
    conn.execute("INSERT INTO pipeline_log (file_id, stage, status, message) VALUES (?,?,?,?)",
                 (file_id, 'survivor', 'done', ''))
    conn.execute("DELETE FROM pipeline_log WHERE file_id=? AND stage='survivor' AND id NOT IN "
                 "(SELECT id FROM pipeline_log WHERE file_id=? AND stage='survivor' ORDER BY id DESC LIMIT 1)",
                 (file_id, file_id))


def get_survivors(conn):
    """Return survivor files ready for copy, with metadata richness score."""
    return conn.execute("""
        SELECT f.id, f.source_path, f.filename, f.file_hash, f.format,
               m.title, m.authors, m.year, m.isbn, m.description, m.publisher,
               m.udc_code, m.udc_label
        FROM files f
        JOIN metadata m ON m.file_id = f.id
        WHERE f.stage = 'survivor'
        ORDER BY f.id
    """).fetchall()


def get_phase_counts(conn):
    rows = conn.execute("""
        SELECT stage, COUNT(*) as count FROM files GROUP BY stage
    """).fetchall()
    counts = {r["stage"]: r["count"] for r in rows}
    for s in ("arrived", "extracted", "cleaned", "cataloged",
              "survivor", "skipped", "copied"):
        counts.setdefault(s, 0)
    return counts


# ── Tags ─────────────────────────────────────────────────────

def set_tags(conn, file_id, tags, tag_type="udc"):
    """Replace all tags of a given type for a file_id with the new set.
    Each tag is a dict with keys: tag, tag_label (optional), score (optional)."""
    conn.execute("DELETE FROM tags WHERE file_id=? AND tag_type=?", (file_id, tag_type))
    for t in tags:
        conn.execute(
            "INSERT INTO tags (file_id, tag, tag_type, tag_label, score) VALUES (?,?,?,?,?)",
            (file_id, t["tag"], tag_type, t.get("tag_label"), t.get("score"))
        )


def get_tags(conn, file_id):
    """Return all tags for a file, grouped by type."""
    rows = conn.execute(
        "SELECT tag, tag_type, tag_label, score FROM tags WHERE file_id=? ORDER BY tag_type, score DESC",
        (file_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def add_custom_tag(conn, file_id, tag):
    """Add a single custom text tag."""
    existing = conn.execute(
        "SELECT id FROM tags WHERE file_id=? AND tag=? AND tag_type='custom'",
        (file_id, tag)
    ).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO tags (file_id, tag, tag_type) VALUES (?,?,?)",
            (file_id, tag, "custom")
        )


def remove_custom_tag(conn, file_id, tag):
    conn.execute(
        "DELETE FROM tags WHERE file_id=? AND tag=? AND tag_type='custom'",
        (file_id, tag)
    )


# ── Summary / Stats ──────────────────────────────────────────

def get_summary(conn):
    total = conn.execute("SELECT COUNT(*) as c FROM files").fetchone()["c"]
    by_stage = dict(conn.execute(
        "SELECT stage, COUNT(*) as c FROM files GROUP BY stage"
    ).fetchall())
    by_udc = dict(conn.execute(
        "SELECT COALESCE(m.udc_code, '?') as k, COUNT(*) as c FROM files f "
        "LEFT JOIN metadata m ON m.file_id = f.id GROUP BY k ORDER BY c DESC"
    ).fetchall())
    by_format = dict(conn.execute(
        "SELECT COALESCE(format, '?') as k, COUNT(*) as c FROM files GROUP BY k ORDER BY c DESC"
    ).fetchall())
    by_custom_tags = dict(conn.execute(
        "SELECT t.tag, COUNT(*) as c FROM tags t "
        "JOIN files f ON f.id = t.file_id "
        "JOIN metadata m ON m.file_id = f.id "
        "WHERE t.tag_type='custom' GROUP BY t.tag ORDER BY c DESC"
    ).fetchall())
    for s in ("arrived", "extracted", "cleaned", "cataloged", "survivor", "skipped", "copied", "quarantined"):
        by_stage.setdefault(s, 0)
    untagged = conn.execute(
        "SELECT COUNT(*) FROM files f WHERE NOT EXISTS (SELECT 1 FROM tags t WHERE t.file_id = f.id AND t.tag_type='custom')"
    ).fetchone()[0]
    return {
        "total": total,
        "untagged": untagged,
        "by_stage": by_stage,
        "by_udc": by_udc,
        "by_format": by_format,
        "by_custom_tags": by_custom_tags,
    }


def get_funnel(conn):
    """Return cumulative + current counts for the pipeline funnel.

    Stages in order: arrived -> extracted -> cleaned -> cataloged -> survivor -> copied.
    Skipped is a dead-end (duplicates).
    """
    by_stage = dict(conn.execute(
        "SELECT stage, COUNT(*) as c FROM files GROUP BY stage"
    ).fetchall())
    for s in ("arrived", "extracted", "cleaned", "cataloged", "survivor", "skipped", "copied"):
        by_stage.setdefault(s, 0)

    stages = ["arrived", "extracted", "cleaned", "cataloged", "survivor", "copied"]
    stage_order = {s: i for i, s in enumerate(stages)}
    total_all = by_stage.get("arrived", 0) + by_stage.get("extracted", 0) + by_stage.get("cleaned", 0) + by_stage.get("cataloged", 0) + by_stage.get("survivor", 0) + by_stage.get("skipped", 0) + by_stage.get("copied", 0)

    funnel = []
    cumulative = 0
    for s in reversed(stages):
        cumulative += by_stage.get(s, 0)
    total_cumulative = cumulative

    cumulative = 0
    for s in reversed(stages):
        cumulative += by_stage.get(s, 0)
        stuck = by_stage.get(s, 0)
        pct = round(cumulative / total_cumulative * 100, 1) if total_cumulative > 0 else 0
        funnel.append({
            "stage": s,
            "cumulative": cumulative,
            "stuck": stuck,
            "pct": pct,
        })
    funnel.reverse()

    return {
        "total": total_all,
        "stages": funnel,
    }


def get_book_pipeline_log(conn, file_id):
    return conn.execute("""
        SELECT stage, status, message, timestamp
        FROM pipeline_log
        WHERE file_id = ?
        ORDER BY timestamp ASC
    """, (file_id,)).fetchall()


# ── FTS5 Search ──────────────────────────────────────────────

def rebuild_fts(conn):
    """Re-populate the FTS5 index from all metadata rows."""
    conn.execute("DELETE FROM books_fts")
    rows = conn.execute("""
        SELECT f.id, m.title, m.authors, m.description, m.publisher, m.isbn
        FROM files f
        JOIN metadata m ON m.file_id = f.id
        WHERE m.title IS NOT NULL OR m.authors IS NOT NULL
    """).fetchall()
    for r in rows:
        conn.execute(
            "INSERT INTO books_fts (rowid, title, authors, description, publisher, isbn) VALUES (?,?,?,?,?,?)",
            (r["id"], r["title"] or "", r["authors"] or "", r["description"] or "",
             r["publisher"] or "", r["isbn"] or "")
        )
    return len(rows)


def search_books(conn, fts_query, stage=None, udc=None, tag=None, fmt=None,
                 year_min=None, year_max=None, min_size=None, max_size=None,
                 masters_only=False, source=None, limit=100, offset=0,
                 sort=None, order=None):
    """Full-text search across books with faceted filters.

    Returns (results_list, total_count).
    """
    base = """
        FROM files f
        JOIN metadata m ON m.file_id = f.id
        LEFT JOIN tags t ON t.file_id = f.id AND t.tag_type = 'custom'
    """
    where_clauses = []
    params = []

    if fts_query:
        base = """
            FROM files f
            JOIN metadata m ON m.file_id = f.id
            JOIN books_fts bfts ON bfts.rowid = f.id
            LEFT JOIN tags t ON t.file_id = f.id AND t.tag_type = 'custom'
        """
        where_clauses.append("books_fts MATCH ?")
        params.append(fts_query)

    if stage:
        where_clauses.append("f.stage = ?")
        params.append(stage)

    if udc:
        where_clauses.append("m.udc_code = ?")
        params.append(udc)

    if tag:
        where_clauses.append("t.tag = ?")
        params.append(tag)

    if fmt:
        where_clauses.append("f.format = ?")
        params.append(fmt)

    if year_min is not None:
        where_clauses.append("m.year >= ?")
        params.append(year_min)

    if year_max is not None:
        where_clauses.append("m.year <= ?")
        params.append(year_max)

    if min_size is not None:
        where_clauses.append("f.file_size >= ?")
        params.append(min_size)

    if max_size is not None:
        where_clauses.append("f.file_size <= ?")
        params.append(max_size)

    if masters_only:
        where_clauses.append("f.is_master = 1")

    if source:
        where_clauses.append("f.source_group = ?")
        params.append(source)

    where = ""
    if where_clauses:
        where = " WHERE " + " AND ".join(where_clauses)

    # Count
    count_sql = f"SELECT COUNT(DISTINCT f.id) as c {base}{where}"
    total = conn.execute(count_sql, params).fetchone()["c"]

    # Results — map sort columns to correct table alias
    _sort_map = {"title": "m.title", "authors": "m.authors", "year": "m.year",
                 "format": "f.format", "file_size": "f.file_size", "stage": "f.stage",
                 "created_at": "f.created_at"}
    safe_sort = _sort_map.get(sort, "f.id")
    safe_order = "DESC" if (order or "").upper() not in ("ASC", "DESC") else order.upper()
    if not sort:
        safe_order = "DESC"

    select_sql = f"""
        SELECT DISTINCT f.id, f.uuid, f.filename, f.format, f.stage, f.file_size,
               f.is_master, f.source_path, f.source_group,
               m.title, m.authors, m.year, m.publisher, m.isbn, m.language,
               m.pages, m.description, m.udc_code, m.udc_label, m.enrich_source,
               m.cover_path
        {base}{where}
        ORDER BY {safe_sort} {safe_order}
        LIMIT ? OFFSET ?
    """
    results = conn.execute(select_sql, params + [limit, offset]).fetchall()

    return [dict(r) for r in results], total


def search_tags(conn, query):
    """Search files by tag (both UDC and custom)."""
    like = f"%{query}%"
    return conn.execute("""
        SELECT DISTINCT f.id, f.filename, f.stage, m.title, m.authors
        FROM files f
        JOIN tags t ON t.file_id = f.id
        LEFT JOIN metadata m ON m.file_id = f.id
        WHERE t.tag LIKE ?
        ORDER BY f.id
    """, (like,)).fetchall()


# ── Daemon IPC ───────────────────────────────────────────────

def daemon_heartbeat(db_path, job_type, status, pid=None, current_file=None,
                     current_stage=None, current_phase=None, progress=None, error=None):
    """Write daemon status for IPC between daemon and API."""
    conn = get_connection(db_path)
    try:
        now = datetime.utcnow().isoformat()
        # Upsert: keep only the most recent row
        existing = conn.execute("SELECT id FROM daemon_status ORDER BY id DESC LIMIT 1").fetchone()
        if existing:
            conn.execute("""
                UPDATE daemon_status SET status=?, pid=?, current_file=?, current_stage=?,
                   current_phase=?, progress=?, error=?, updated_at=?
                WHERE id=?
            """, (status, pid, current_file, current_stage, current_phase,
                  json.dumps(progress) if progress else None, error, now, existing["id"]))
        else:
            conn.execute("""
                INSERT INTO daemon_status (job_type, status, pid, current_file, current_stage,
                    current_phase, progress, error, started_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (job_type, status, pid, current_file, current_stage, current_phase,
                  json.dumps(progress) if progress else None, error, now, now))
        conn.commit()
    finally:
        conn.close()


def get_daemon_status(db_path):
    """Read current daemon status."""
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT * FROM daemon_status ORDER BY id DESC LIMIT 1").fetchone()
        if row:
            d = dict(row)
            if d.get("progress"):
                try:
                    d["progress"] = json.loads(d["progress"])
                except (json.JSONDecodeError, TypeError):
                    d["progress"] = None
            return d
        return {"status": "idle"}
    finally:
        conn.close()


# ── Quarantine ─────────────────────────────────────────────

QUARANTINE_ERRORS = {
    "EXTRACT_FAIL": "Extractor threw exception or returned empty metadata",
    "FORMAT_UNSUPPORTED": "File extension not in EBOOK_EXTS",
    "NO_METADATA_EMPTY": "Raw extraction + filename parse both returned nothing",
    "ENRICH_FAIL": "Filename parser + all API lookups returned nothing",
    "CLASSIFY_FALLBACK": "UDC scored 0 on all classes, fell back to 000",
    "CLASSIFY_LOW_CONF": "Best UDC score below confidence threshold",
    "DEDUP_AMBIGUOUS": "Title similarity 70-85% — uncertain if duplicate",
}


def quarantine_file(conn, file_id, error_code, detail=None):
    conn.execute("""
        INSERT OR REPLACE INTO quarantined (file_id, error_code, detail, reviewed, created_at)
        VALUES (?, ?, ?, 0, datetime('now'))
    """, (file_id, error_code, detail))
    set_stage(conn, file_id, "quarantined", error_code)


def get_quarantined(conn, reviewed=None, limit=100, offset=0,
                    error_code=None, q=None, fmt=None,
                    date_from=None, date_to=None):
    where = "WHERE 1=1"
    params = []
    if reviewed is not None:
        where += " AND q.reviewed = ?"
        params.append(reviewed)
    if error_code:
        where += " AND q.error_code = ?"
        params.append(error_code)
    if q:
        where += " AND f.filename LIKE ?"
        params.append(f"%{q}%")
    if fmt:
        where += " AND f.format = ?"
        params.append(fmt if fmt.startswith(".") else f".{fmt}")
    if date_from:
        where += " AND q.created_at >= ?"
        params.append(date_from)
    if date_to:
        where += " AND q.created_at <= ?"
        params.append(date_to)
    total = conn.execute(f"""
        SELECT COUNT(*) FROM quarantined q
        JOIN files f ON f.id = q.file_id
        LEFT JOIN metadata m ON m.file_id = q.file_id
        {where}
    """, params).fetchone()[0]
    rows = conn.execute(f"""
        SELECT q.*, f.filename, f.stage, f.source_path, f.format, f.file_size,
               m.title, m.authors, m.year, m.udc_code, m.udc_label
        FROM quarantined q
        JOIN files f ON f.id = q.file_id
        LEFT JOIN metadata m ON m.file_id = q.file_id
        {where}
        ORDER BY q.id DESC
        LIMIT ? OFFSET ?
    """, params + [limit, offset]).fetchall()
    return [dict(r) for r in rows], total


def get_quarantine_counts_by_error(conn, reviewed=0):
    rows = conn.execute("""
        SELECT q.error_code, COUNT(*) as cnt
        FROM quarantined q
        WHERE q.reviewed = ?
        GROUP BY q.error_code
        ORDER BY cnt DESC
    """, (reviewed,)).fetchall()
    return {r["error_code"]: r["cnt"] for r in rows}


def get_quarantine_formats(conn, reviewed=0):
    rows = conn.execute("""
        SELECT f.format, COUNT(*) as cnt
        FROM quarantined q
        JOIN files f ON f.id = q.file_id
        WHERE q.reviewed = ?
        GROUP BY f.format
        ORDER BY cnt DESC
    """, (reviewed,)).fetchall()
    return {r["format"]: r["cnt"] for r in rows}


def bulk_dismiss(conn, file_ids):
    now = datetime.utcnow().isoformat()
    placeholders = ",".join("?" * len(file_ids))
    conn.execute(f"""
        UPDATE quarantined SET reviewed=2, reviewed_at=?
        WHERE file_id IN ({placeholders})
    """, [now] + file_ids)
    conn.execute(f"""
        DELETE FROM quarantined WHERE file_id IN ({placeholders}) AND reviewed=2
    """, file_ids)


def bulk_keep_both(conn, file_ids):
    for fid in file_ids:
        mark_survivor(conn, fid)
    placeholders = ",".join("?" * len(file_ids))
    conn.execute(f"""
        UPDATE quarantined SET reviewed=1, reviewed_at=datetime('now')
        WHERE file_id IN ({placeholders})
    """, file_ids)


def bulk_delete_files(conn, file_ids):
    placeholders = ",".join("?" * len(file_ids))
    conn.execute(f"DELETE FROM quarantined WHERE file_id IN ({placeholders})", file_ids)
    conn.execute(f"DELETE FROM pipeline_log WHERE file_id IN ({placeholders})", file_ids)
    conn.execute(f"DELETE FROM tags WHERE file_id IN ({placeholders})", file_ids)
    conn.execute(f"DELETE FROM metadata WHERE file_id IN ({placeholders})", file_ids)
    conn.execute(f"DELETE FROM files WHERE id IN ({placeholders})", file_ids)


def get_quarantine_rules(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS quarantine_rules (
            name  TEXT PRIMARY KEY,
            value INTEGER DEFAULT 0,
            updated_at TEXT
        )
    """)
    rows = conn.execute("SELECT * FROM quarantine_rules").fetchall()
    return {r["name"]: r["value"] for r in rows}


def set_quarantine_rule(conn, name, value):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS quarantine_rules (
            name  TEXT PRIMARY KEY,
            value INTEGER DEFAULT 0,
            updated_at TEXT
        )
    """)
    now = datetime.utcnow().isoformat()
    conn.execute("""
        INSERT OR REPLACE INTO quarantine_rules (name, value, updated_at)
        VALUES (?, ?, ?)
    """, (name, int(bool(value)), now))


def resolve_quarantine(conn, file_id, reviewed=1, user_notes=None):
    now = datetime.utcnow().isoformat()
    conn.execute("""
        UPDATE quarantined SET reviewed=?, reviewed_at=?, user_notes=COALESCE(?, user_notes)
        WHERE file_id=?
    """, (reviewed, now, user_notes, file_id))
    # Remove from quarantined if dismissed
    conn.execute("DELETE FROM quarantined WHERE file_id=? AND reviewed=2", (file_id,))


# ── Reading List (P3.1) ────────────────────────────────────

def ensure_reading_tables(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reading_list (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id     INTEGER NOT NULL UNIQUE REFERENCES files(id) ON DELETE CASCADE,
            status      TEXT NOT NULL DEFAULT 'to_read' CHECK(status IN ('reading','to_read','finished')),
            added_at    TEXT DEFAULT (datetime('now')),
            updated_at  TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reader_state (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id     INTEGER NOT NULL UNIQUE REFERENCES files(id) ON DELETE CASCADE,
            location    TEXT,
            progress_pct REAL DEFAULT 0,
            updated_at  TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS annotations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id     INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            type        TEXT NOT NULL DEFAULT 'highlight' CHECK(type IN ('highlight','note')),
            cfi_range   TEXT,
            text        TEXT,
            note        TEXT,
            color       TEXT DEFAULT '#fef08a',
            created_at  TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reading_list_book ON reading_list(book_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reader_state_book ON reader_state(book_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_annotations_book ON annotations(book_id)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bookmarks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id     INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            label       TEXT,
            cfi_loc     TEXT,
            page_num    INTEGER,
            progress_pct REAL,
            created_at  TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bookmarks_book ON bookmarks(book_id)")


def get_reading_list(conn, status=None):
    where = ""
    params = []
    if status:
        where = " WHERE rl.status = ?"
        params.append(status)
    rows = conn.execute(f"""
        SELECT rl.*, f.filename, f.format, f.stage, f.source_path,
               m.title, m.authors, m.udc_code, m.udc_label, m.cover_path,
               COALESCE(rs.progress_pct, 0) as progress_pct
        FROM reading_list rl
        JOIN files f ON f.id = rl.book_id
        LEFT JOIN metadata m ON m.file_id = rl.book_id
        LEFT JOIN reader_state rs ON rs.book_id = rl.book_id
        {where}
        ORDER BY rl.updated_at DESC
    """, params).fetchall()
    return [dict(r) for r in rows]


def add_to_reading_list(conn, book_id, status='to_read'):
    conn.execute("""
        INSERT OR REPLACE INTO reading_list (book_id, status, updated_at)
        VALUES (?, ?, datetime('now'))
    """, (book_id, status))


def update_reading_list_status(conn, book_id, status):
    conn.execute("""
        UPDATE reading_list SET status=?, updated_at=datetime('now')
        WHERE book_id=?
    """, (status, book_id))


def remove_from_reading_list(conn, book_id):
    conn.execute("DELETE FROM reading_list WHERE book_id=?", (book_id,))


def get_reader_state(conn, book_id):
    return conn.execute("""
        SELECT * FROM reader_state WHERE book_id=?
    """, (book_id,)).fetchone()


def save_reader_state(conn, book_id, location, progress_pct=0):
    conn.execute("""
        INSERT OR REPLACE INTO reader_state (book_id, location, progress_pct, updated_at)
        VALUES (?, ?, ?, datetime('now'))
    """, (book_id, location, progress_pct))


def get_annotations(conn, book_id):
    rows = conn.execute("""
        SELECT * FROM annotations WHERE book_id=? ORDER BY created_at ASC
    """, (book_id,)).fetchall()
    return [dict(r) for r in rows]


def add_annotation(conn, book_id, ann_type, cfi_range, text, note=None, color='#fef08a'):
    conn.execute("""
        INSERT INTO annotations (book_id, type, cfi_range, text, note, color)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (book_id, ann_type, cfi_range, text, note, color))
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def delete_annotation(conn, ann_id):
    conn.execute("DELETE FROM annotations WHERE id=?", (ann_id,))


def export_annotations_markdown(conn, book_id):
    """Return annotations as markdown text."""
    anns = get_annotations(conn, book_id)
    book = conn.execute("""
        SELECT m.title, m.authors FROM files f
        LEFT JOIN metadata m ON m.file_id = f.id
        WHERE f.id=?
    """, (book_id,)).fetchone()
    title = book["title"] if book and book["title"] else f"Book #{book_id}"
    authors = book["authors"] if book and book["authors"] else "Unknown"
    lines = [f"# {title}", f"*By {authors}*", "", "---", ""]
    for a in anns:
        if a["type"] == "highlight":
            lines.append(f"> {a['text']}")
            if a.get("note"):
                lines.append(f"  — {a['note']}")
            lines.append("")
        else:
            lines.append(f"**Note:** {a['text'] or a.get('note', '')}")
            lines.append("")
    return "\n".join(lines)


def get_bookmarks(conn, book_id):
    rows = conn.execute(
        "SELECT * FROM bookmarks WHERE book_id=? ORDER BY created_at DESC", (book_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def add_bookmark(conn, book_id, label=None, cfi_loc=None, page_num=None, progress_pct=None):
    conn.execute(
        "INSERT INTO bookmarks (book_id, label, cfi_loc, page_num, progress_pct) VALUES (?,?,?,?,?)",
        (book_id, label, cfi_loc, page_num, progress_pct)
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def delete_bookmark(conn, bm_id):
    conn.execute("DELETE FROM bookmarks WHERE id=?", (bm_id,))


# ── Config overrides ───────────────────────────────────────

CONFIG_SCHEMA = [
    {"name": "source_dirs", "default": "", "type": "text", "category": "paths",
     "label": "Source Directories", "desc": "Semicolon-separated list of directories to scan for ebooks"},
    {"name": "inbox_dir", "default": "", "type": "path", "category": "paths",
     "label": "Inbox / To Be Sorted", "desc": "Incoming unprocessed books (e.g. Z:\\books\\to be sorted)"},
    {"name": "flat_dir", "default": "", "type": "path", "category": "paths",
     "label": "Flat Output Directory", "desc": "Where processed/survivor books are copied (e.g. Z:\\books\\processed)"},
    {"name": "archive_dir", "default": "", "type": "path", "category": "paths",
     "label": "Archive Directory", "desc": "Non-processed files moved here (leave empty = flat_dir/archive)"},
    {"name": "watch_dir", "default": "", "type": "path", "category": "paths",
     "label": "Watch Directory", "desc": "Directory the daemon watches for new files (leave empty = inbox_dir)"},
    {"name": "watch_recursive", "default": "true", "type": "boolean", "category": "daemon",
     "label": "Watch Recursive", "desc": "Scan subdirectories when watching for new files"},
    {"name": "db_path", "default": "", "type": "path", "category": "paths",
     "label": "Database Path", "desc": "SQLite database file location", "restart": True},
    {"name": "log_dir", "default": "", "type": "path", "category": "paths",
     "label": "Log Directory", "desc": "Where application logs are stored", "restart": True},
    {"name": "ebook_exts", "default": ".epub,.pdf,.mobi,.azw3,.djvu,.cbr,.cbz,.fb2",
     "type": "text", "category": "processing", "label": "Ebook Extensions",
     "desc": "Comma-separated recognised ebook file extensions"},
    {"name": "exclude_exts", "default": ".ini,.db,.lnk,.url,.tmp,.dat,.exe,.dll",
     "type": "text", "category": "processing", "label": "Exclude Extensions",
     "desc": "Comma-separated file extensions to skip during scan"},
    {"name": "exclude_dirs", "default": ".git,__pycache__,data,templates,extractors",
     "type": "text", "category": "processing", "label": "Exclude Directories",
     "desc": "Comma-separated directory names to skip during scan"},
    {"name": "dup_similarity", "default": "0.85", "type": "number", "category": "processing",
     "label": "Duplicate Similarity Threshold",
     "desc": "Title similarity ratio (0-1) for fuzzy dedup"},
    {"name": "enrich_rate_limit", "default": "1.0", "type": "number", "category": "enrichment",
     "label": "Enrichment Rate Limit (s)", "desc": "Seconds between external API calls"},
    {"name": "google_books_api_key", "default": "", "type": "password", "category": "enrichment",
     "label": "Google Books API Key", "desc": "API key for Google Books enrichment"},
]


def ensure_config_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS config_overrides (
            name  TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT
        )
    """)


def get_config_overrides(conn):
    ensure_config_table(conn)
    rows = conn.execute("SELECT name, value FROM config_overrides").fetchall()
    return {r["name"]: r["value"] for r in rows}


def set_config_override(conn, name, value):
    ensure_config_table(conn)
    now = datetime.utcnow().isoformat()
    conn.execute("""
        INSERT OR REPLACE INTO config_overrides (name, value, updated_at)
        VALUES (?, ?, ?)
    """, (name, str(value), now))


def delete_config_override(conn, name):
    ensure_config_table(conn)
    conn.execute("DELETE FROM config_overrides WHERE name=?", (name,))


def load_config_overrides(conn):
    """Apply config overrides from DB to the config module."""
    import config as cfg
    overrides = get_config_overrides(conn)
    attr_map = {
        "source_dirs": "SOURCE_DIRS",
        "flat_dir": "FLAT_DIR",
        "archive_dir": "ARCHIVE_DIR",
        "inbox_dir": "INBOX_DIR",
        "watch_dir": "WATCH_DIR",
        "watch_recursive": "WATCH_RECURSIVE",
        "db_path": "DB_PATH",
        "log_dir": "LOG_DIR",
        "ebook_exts": "EBOOK_EXTS",
        "exclude_exts": "EXCLUDE_EXTS",
        "exclude_dirs": "EXCLUDE_DIRS",
        "dup_similarity": "DUPLICATE_SIMILARITY_THRESHOLD",
        "enrich_rate_limit": "ENRICH_RATE_LIMIT",
        "google_books_api_key": "GOOGLE_BOOKS_API_KEY",
    }
    for name, value in overrides.items():
        attr = attr_map.get(name)
        if not attr or not value:
            continue
        if name == "source_dirs":
            cfg.SOURCE_DIRS = [d.strip() for d in value.split(";") if d.strip()]
            if cfg.SOURCE_DIRS:
                cfg.SOURCE_DIR = cfg.SOURCE_DIRS[0]
        elif name == "watch_dir":
            cfg.WATCH_DIR = value
        elif name == "watch_recursive":
            cfg.WATCH_RECURSIVE = value.lower() in ("true", "1", "yes")
        elif name == "ebook_exts":
            cfg.EBOOK_EXTS = set(e.strip() for e in value.split(",") if e.strip())
        elif name == "exclude_exts":
            cfg.EXCLUDE_EXTS = set(e.strip() for e in value.split(",") if e.strip())
        elif name == "exclude_dirs":
            cfg.EXCLUDE_DIRS = set(e.strip() for e in value.split(",") if e.strip())
        elif name == "dup_similarity":
            try: cfg.DUPLICATE_SIMILARITY_THRESHOLD = float(value)
            except ValueError: pass
        elif name == "enrich_rate_limit":
            try: cfg.ENRICH_RATE_LIMIT = float(value)
            except ValueError: pass
        else:
            setattr(cfg, attr.upper() if name == "google_books_api_key" else attr, value)

    # Derive dependent paths from their parents if not overridden
    if cfg.FLAT_DIR:
        cfg.PROCESSED_DIR = cfg.FLAT_DIR
        if not overrides.get("archive_dir"):
            cfg.ARCHIVE_DIR = os.path.join(cfg.FLAT_DIR, "archive")
        if not overrides.get("watch_dir"):
            cfg.WATCH_DIR = cfg.INBOX_DIR if cfg.INBOX_DIR else cfg.WATCH_DIR
    # If archive_dir is set, exclude it from source scanning
    if cfg.ARCHIVE_DIR:
        cfg.EXCLUDE_DIRS.add(os.path.normpath(cfg.ARCHIVE_DIR))
    # If archive_dir override was set but flat_dir was not, derive processed from flat
    # (both point to the same root)


def get_all_config(conn):
    import config as cfg
    overrides = get_config_overrides(conn)
    result = []
    for field in CONFIG_SCHEMA:
        entry = dict(field)
        key = field["name"]
        # "default" in the schema is the hardcoded default — show that to the user
        entry["value"] = overrides.get(key, "")
        entry["overridden"] = key in overrides
        result.append(entry)
    return result
