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
        file_id, kw.get("title"), kw.get("authors"), kw.get("publisher"),
        kw.get("isbn"), kw.get("language"), kw.get("pages"), kw.get("year"),
        kw.get("description"), kw.get("subjects"), kw.get("udc_code"),
        kw.get("udc_label"), kw.get("cover_path"), kw.get("enrich_source"),
        kw.get("enriched_at")
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


def mark_duplicate(conn, file_id, reason):
    now = datetime.utcnow().isoformat()
    conn.execute("UPDATE files SET stage='skipped', stage_error=?, is_master=0, updated_at=? WHERE id=?",
                 (reason, now, file_id))
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
    for s in ("arrived", "extracted", "cleaned", "cataloged", "survivor", "skipped", "copied", "quarantined"):
        by_stage.setdefault(s, 0)
    return {
        "total": total,
        "by_stage": by_stage,
        "by_udc": by_udc,
        "by_format": by_format,
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
                 masters_only=False, source=None, limit=100, offset=0):
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

    # Results
    select_sql = f"""
        SELECT DISTINCT f.id, f.uuid, f.filename, f.format, f.stage, f.file_size,
               f.is_master, f.source_path, f.source_group,
               m.title, m.authors, m.year, m.publisher, m.isbn, m.language,
               m.pages, m.description, m.udc_code, m.udc_label, m.enrich_source,
               m.cover_path
        {base}{where}
        ORDER BY f.id DESC
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


def get_quarantined(conn, reviewed=None, limit=100, offset=0):
    where = "WHERE 1=1"
    params = []
    if reviewed is not None:
        where += " AND q.reviewed = ?"
        params.append(reviewed)
    total = conn.execute(f"""
        SELECT COUNT(*) FROM quarantined q {where}
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


def resolve_quarantine(conn, file_id, reviewed=1, user_notes=None):
    now = datetime.utcnow().isoformat()
    conn.execute("""
        UPDATE quarantined SET reviewed=?, reviewed_at=?, user_notes=COALESCE(?, user_notes)
        WHERE file_id=?
    """, (reviewed, now, user_notes, file_id))
    # Remove from quarantined if dismissed
    conn.execute("DELETE FROM quarantined WHERE file_id=? AND reviewed=2", (file_id,))
