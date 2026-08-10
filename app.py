import os
import sys
import json
import threading
import time
import argparse
import io
import logging
import shutil
import subprocess
import tempfile
import concurrent.futures
from flask import Flask, render_template, jsonify, Response, request, send_file, session, make_response
import pandas as pd

import config
from config import DB_PATH, EBOOK_EXTS, EXCLUDE_EXTS
from log_utils import setup_logger

logger = setup_logger("app", also_stdout=False)

_active_threads = []

# Silence noisy loggers
for noisy in ("werkzeug", "flask"):
    log = logging.getLogger(noisy)
    log.setLevel(logging.WARNING)
    log.handlers.clear()
from db import get_connection, init_db, get_pipeline_summary, get_recent_books, get_pipeline_log, get_book_by_id
from db import get_phase_counts, get_survivors, get_tags, add_custom_tag, remove_custom_tag, search_tags
from db import get_summary, get_book_pipeline_log, rebuild_fts, search_books, get_funnel, get_daemon_status, daemon_heartbeat
from db import get_quarantined, resolve_quarantine, QUARANTINE_ERRORS, get_quarantine_counts_by_error, get_quarantine_formats, bulk_dismiss, bulk_keep_both, bulk_delete_files, get_quarantine_rules, set_quarantine_rule, get_config_overrides, set_config_override, delete_config_override, get_all_config, load_config_overrides
from db import get_reading_list, add_to_reading_list, update_reading_list_status, remove_from_reading_list
from db import get_reader_state, save_reader_state
from db import get_annotations, add_annotation, delete_annotation, export_annotations_markdown
from db import get_drawing, save_drawing, delete_drawing
from db import get_bookmarks, add_bookmark, delete_bookmark
from pipeline import state, run_pipeline, run_all_phases, run_phase_metadata, run_phase_dedup, run_phase_copy, run_recon, discover_source_files, add_to_inbox, run_phase_enrich
from enricher import enrich_book, _download_cover
import enrich_filename

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB limit (D7.13)
app.secret_key = config.SECRET_KEY
app.permanent_session_lifetime = 86400 * 30  # 30 days

# Ensure log directory exists
os.makedirs(config.LOG_DIR, exist_ok=True)

# Route all server output to app.log (local copy to avoid SMB latency)
_local_log = os.path.join(os.path.expanduser("~"), "book_organiser_data", "app.log")
log_handler = logging.FileHandler(_local_log, encoding="utf-8")
log_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
werkz = logging.getLogger("werkzeug")
werkz.setLevel(logging.INFO)
werkz.addHandler(log_handler)
werkz.propagate = False
flask_log = logging.getLogger("flask")
flask_log.addHandler(log_handler)
flask_log.setLevel(logging.INFO)

# Warn if DB was redirected from network to local copy (D7.5)
if getattr(config, "LOCAL_DB_REDIRECTED", False):
    _orig = getattr(config, "ORIGINAL_DB_PATH", "?")
    logging.getLogger("werkzeug").warning(
        "DB redirected from network path %s to local copy %s. "
        "Use POST /api/admin/sync-db to push changes back.",
        _orig, config.DB_PATH
    )


def resolve_book_path(book):
    """Resolve book file path â€” checks original, processed, archive, and flat dirs."""
    sp = book["source_path"]
    if sp and os.path.isfile(sp):
        return sp
    fname = book["filename"] or ""
    if not fname:
        return None
    book_id = book.get("id")
    candidates = [fname]
    if book_id:
        stem, ext = os.path.splitext(fname)
        candidates.append(f"{stem}_{book_id}{ext}")
    for d in (config.FLAT_DIR,
              getattr(config, "PROCESSED_DIR", config.FLAT_DIR),
              getattr(config, "ARCHIVE_DIR", os.path.join(config.FLAT_DIR, "archive"))):
        if not d:
            continue
        for name in candidates:
            candidate = os.path.join(d, name)
            if os.path.isfile(candidate):
                return candidate
    return None


def _safe_send_path(filepath, allowed_base_dirs, **kwargs):
    """Validate filepath is within allowed base dirs before sending (D7.30)."""
    real = os.path.realpath(filepath)
    for base in allowed_base_dirs:
        if base and real.startswith(os.path.realpath(base) + os.sep):
            kwargs.setdefault("conditional", True)
            return send_file(filepath, **kwargs)
    # Also allow temp dir for conversion results
    import tempfile
    if real.startswith(os.path.realpath(tempfile.gettempdir()) + os.sep):
        kwargs.setdefault("conditional", True)
        return send_file(filepath, **kwargs)
    return jsonify({"error": "access denied"}), 403


def _readable_dirs():
    """Directories the read/download endpoints may serve from.

    Includes configured source dirs (books still live at their original location),
    the processed/flat/archive copies, and the data dir for generated files.
    """
    dirs = []
    for d in (config.SOURCE_DIR, *getattr(config, "SOURCE_DIRS", []),
              config.FLAT_DIR, getattr(config, "PROCESSED_DIR", config.FLAT_DIR),
              getattr(config, "ARCHIVE_DIR", ""), getattr(config, "DATA_DIR", "")):
        if d and d not in dirs:
            dirs.append(d)
    return dirs


@app.route("/")
def index():
    resp = make_response(render_template("index.html"))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/api/health")
def api_health():
    """Boot-time health check: DB, config dirs, pipeline lock."""
    checks = {}
    all_ok = True
    # DB check
    try:
        conn = get_connection(DB_PATH)
        conn.execute("SELECT 1").fetchone()
        conn.close()
        checks["db"] = "ok"
    except Exception as e:
        checks["db"] = str(e)
        all_ok = False
    # Config directories
    for name, path in [("source", config.SOURCE_DIR), ("inbox", config.INBOX_DIR),
                       ("flat_dir", config.FLAT_DIR), ("archive_dir", getattr(config, "ARCHIVE_DIR", ""))]:
        if path and os.path.isdir(path):
            checks[f"dir_{name}"] = "ok"
        elif not path:
            checks[f"dir_{name}"] = "not_configured"
        else:
            checks[f"dir_{name}"] = "not_found"
            all_ok = False
    # Pipeline lock check
    lock_path = os.path.join(config.DATA_DIR, "pipeline.lock")
    if os.path.exists(lock_path):
        try:
            with open(lock_path) as f:
                pid = int(f.read().strip())
            try:
                os.kill(pid, 0)
                checks["pipeline_lock"] = f"held_by_pid_{pid}"
            except (OSError, ProcessLookupError):
                checks["pipeline_lock"] = "stale"
        except Exception:
            checks["pipeline_lock"] = "corrupt"
    else:
        checks["pipeline_lock"] = "clear"
    return jsonify({"status": "ok" if all_ok else "degraded", "checks": checks})


@app.route("/api/diagnostics")
def api_diagnostics():
    result = {"status": "ok", "checks": {}}
    all_ok = True
    try:
        conn = get_connection(DB_PATH)
        conn.execute("SELECT 1").fetchone()
        result["checks"]["db_connect"] = "ok"
    except Exception as e:
        result["checks"]["db_connect"] = str(e)
        all_ok = False
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        result["checks"]["db_integrity"] = integrity
        if integrity != "ok":
            all_ok = False
    except Exception as e:
        result["checks"]["db_integrity"] = str(e)
        all_ok = False
    required_tables = ["files", "metadata", "pipeline_log", "tags", "books_fts", "reading_list", "reader_state", "annotations", "quarantined"]
    try:
        present = set(r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())
        missing = [t for t in required_tables if t not in present]
        result["checks"]["db_schema"] = "ok" if not missing else f"missing: {missing}"
        if missing:
            all_ok = False
    except Exception as e:
        result["checks"]["db_schema"] = str(e)
        all_ok = False
    try:
        fts_docs = conn.execute("SELECT COUNT(*) FROM books_fts").fetchone()[0]
        meta_rows = conn.execute("SELECT COUNT(*) FROM metadata WHERE title IS NOT NULL").fetchone()[0]
        result["checks"]["fts"] = {"docs": fts_docs, "metadata_with_title": meta_rows}
        if fts_docs < meta_rows * 0.9:
            result["checks"]["fts"]["warning"] = f"FTS has {fts_docs} docs vs {meta_rows} metadata rows"
            all_ok = False
    except Exception as e:
        result["checks"]["fts"] = str(e)
        all_ok = False
    try:
        stages = {}
        for r in conn.execute("SELECT stage, COUNT(*) as c FROM files GROUP BY stage").fetchall():
            stages[r["stage"]] = r["c"]
        result["checks"]["stage_counts"] = stages
    except Exception as e:
        result["checks"]["stage_counts"] = str(e)
    conn.close()
    dir_checks = [
        ("source_dir", config.SOURCE_DIR), ("inbox_dir", config.INBOX_DIR),
        ("flat_dir", config.FLAT_DIR), ("archive_dir", getattr(config, "ARCHIVE_DIR", "")),
        ("data_dir", config.DATA_DIR), ("processed_dir", getattr(config, "PROCESSED_DIR", "")),
    ]
    for name, path in dir_checks:
        if not path:
            result["checks"][f"dir_{name}"] = "not_configured"
        elif os.path.isdir(path):
            result["checks"][f"dir_{name}"] = "ok"
        else:
            result["checks"][f"dir_{name}"] = "not_found"
            all_ok = False
    covers_dir = config.COVER_DIR
    if os.path.isdir(covers_dir):
        on_disk = set(f.split(".")[0] for f in os.listdir(covers_dir) if f.endswith(".jpg"))
        try:
            conn2 = get_connection(DB_PATH)
            in_db = set(str(r["file_id"]) for r in conn2.execute("SELECT file_id FROM metadata WHERE cover_path IS NOT NULL").fetchall())
            conn2.close()
            orphaned = on_disk - in_db
            missing_covers = in_db - on_disk
            result["checks"]["covers"] = {"on_disk": len(on_disk), "in_db": len(in_db), "orphaned": len(orphaned), "missing": len(missing_covers)}
            if missing_covers:
                result["checks"]["covers"]["warning"] = f"Missing {len(missing_covers)} cover files"
                all_ok = False if len(missing_covers) > 100 else None
        except Exception as e:
            result["checks"]["covers"] = str(e)
    else:
        result["checks"]["covers"] = "not_found"
    lock_path = os.path.join(config.DATA_DIR, "pipeline.lock")
    if os.path.exists(lock_path):
        try:
            with open(lock_path) as f:
                pid = int(f.read().strip())
            try:
                os.kill(pid, 0)
                result["checks"]["pipeline_lock"] = f"held_by_pid_{pid}"
            except (OSError, ProcessLookupError):
                result["checks"]["pipeline_lock"] = "stale"
        except Exception:
            result["checks"]["pipeline_lock"] = "corrupt"
    else:
        result["checks"]["pipeline_lock"] = "clear"
    try:
        import shutil
        usage = shutil.disk_usage(os.path.dirname(DB_PATH))
        gb = 1024 ** 3
        result["checks"]["disk"] = {"total_gb": round(usage.total / gb, 1), "used_gb": round(usage.used / gb, 1), "free_gb": round(usage.free / gb, 1), "free_pct": round(usage.free / usage.total * 100, 1)}
        if usage.free / usage.total < 0.05:
            result["checks"]["disk"]["warning"] = "Less than 5% disk space remaining"
            all_ok = False
    except Exception:
        pass

    # ── File size metrics ──
    def _get_size(path):
        try: return os.path.getsize(path) if os.path.isfile(path) else 0
        except Exception: return 0
    def _get_dir_size(path):
        total = 0
        try:
            for f in os.listdir(path):
                fp = os.path.join(path, f)
                if os.path.isfile(fp): total += os.path.getsize(fp)
        except Exception: pass
        return total
    mb = 1024 * 1024
    result["metrics"] = {
        "db_file_mb": round(_get_size(DB_PATH) / mb, 2),
        "covers_dir_mb": round(_get_dir_size(covers_dir) / mb, 2) if os.path.isdir(covers_dir) else 0,
        "comic_cache_mb": round(_get_dir_size(os.path.join(config.BASE_DIR, "data", "cache", "comic")) / mb, 2),
        "enrich_cache_mb": round(_get_size(getattr(config, "ENRICH_CACHE_PATH", "")) / mb, 2),
        "data_dir_mb": round(_get_dir_size(config.DATA_DIR) / mb, 2),
    }
    result["db_redirect"] = {
        "active": getattr(config, "LOCAL_DB_REDIRECTED", False),
        "local_path": config.DB_PATH,
        "original_path": getattr(config, "ORIGINAL_DB_PATH", None),
    }
    result["status"] = "ok" if all_ok else "degraded"
    return jsonify(result)



# â”€â”€ Auth (P3.2) â”€â”€

def is_authenticated():
    if not config.AUTH_ENABLED:
        return True
    return session.get("authenticated", False)


@app.route("/api/auth/check")
def api_auth_check():
    return jsonify({
        "authenticated": is_authenticated(),
        "enabled": config.AUTH_ENABLED,
    })


@app.route("/api/auth/login", methods=["POST"])
def api_auth_login():
    data = request.json or {}
    pw = data.get("password", "")
    if not config.AUTH_ENABLED:
        return jsonify({"status": "ok", "authenticated": True})
    if pw == config.AUTH_PASSWORD:
        session["authenticated"] = True
        session.permanent = True
        return jsonify({"status": "ok", "authenticated": True})
    return jsonify({"status": "error", "message": "Invalid password"}), 401


@app.route("/api/auth/logout", methods=["POST"])
def api_auth_logout():
    session.pop("authenticated", None)
    return jsonify({"status": "logged_out"})


# ── CSRF Protection (D7.16) ──
import secrets

def _generate_csrf_token():
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(32)
    return session["_csrf_token"]

def _validate_csrf():
    if not config.AUTH_ENABLED:
        return True
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return True
    token = request.headers.get("X-CSRF-Token") or request.form.get("_csrf_token")
    expected = session.get("_csrf_token")
    if not token or not expected or not secrets.compare_digest(token, expected):
        return False
    return True

@app.before_request
def _csrf_check():
    if not _validate_csrf():
        return jsonify({"error": "CSRF token missing or invalid"}), 403

@app.route("/api/csrf-token")
def api_csrf_token():
    return jsonify({"csrf_token": _generate_csrf_token()})


@app.route("/api/status")
def api_status():
    conn = get_connection(DB_PATH)
    try:
        summary = get_pipeline_summary(conn)
        pcounts = get_phase_counts(conn)
        recent = [dict(r) for r in get_recent_books(conn, 20)]
        plog = [dict(r) for r in get_pipeline_log(conn, 20)]
        snap = state.get_snapshot()
        if _pipeline_proc and _pipeline_proc.poll() is None:
            snap["running"] = True
            snap["log_msg"] = f"Pipeline subprocess PID={_pipeline_proc.pid} running"
            # Load persisted state from subprocess
            try:
                import json
                persist_path = os.path.join(config.DATA_DIR, "pipeline_state.json")
                with open(persist_path, "r", encoding="utf-8") as f:
                    sub_snap = json.load(f)
                snap.update(sub_snap)
                snap["running"] = True
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                pass
        return jsonify({
            "pipeline": snap,
            "summary": summary,
            "phase_counts": pcounts,
            "recent": recent,
            "log": plog,
        })
    finally:
        conn.close()


@app.route("/api/recon")
def api_recon():
    from pipeline import run_recon
    result = run_recon()
    return jsonify(result)


@app.route("/api/book/<int:book_id>")
def api_book(book_id):
    conn = get_connection(DB_PATH)
    try:
        book = get_book_by_id(conn, book_id)
        if not book:
            return jsonify({"error": "not found"}), 404
        result = dict(book)
        result["tags"] = get_tags(conn, book_id)
        resp = jsonify(result)
        return resp
    finally:
        conn.close()


@app.route("/api/books")
def api_books():
    conn = get_connection(DB_PATH)
    try:
        limit = request.args.get("limit", 100, int)
        sort = request.args.get("sort", "updated_at")
        order = request.args.get("order", "DESC")
        stage = request.args.get("stage")
        udc = request.args.get("udc")
        q = request.args.get("q")
        master = request.args.get("master")
        source = request.args.get("source")

        sql = """
            SELECT f.id, f.uuid, f.filename, f.format, f.stage, f.source_path, f.is_master,
                   m.title, m.authors, m.udc_code, m.udc_label, m.year, m.enrich_source
            FROM files f
            LEFT JOIN metadata m ON m.file_id = f.id
            WHERE 1=1
        """
        params = []
        if stage:
            sql += " AND f.stage = ?"
            params.append(stage)
        if udc:
            sql += " AND m.udc_code = ?"
            params.append(udc)
        if master == "1":
            sql += " AND f.is_master = 1"
        if source:
            sql += " AND f.source_group = ?"
            params.append(source)
        if q:
            sql += " AND (m.title LIKE ? OR m.authors LIKE ? OR f.filename LIKE ?)"
            like = f"%{q}%"
            params.extend([like, like, like])

        safe_sort = "updated_at" if sort not in ("title", "authors", "year", "format") else sort
        safe_order = "DESC" if order.upper() not in ("ASC", "DESC") else order.upper()
        sql += f" ORDER BY f.{safe_sort} {safe_order} LIMIT ?"
        params.append(limit)

        books = conn.execute(sql, params).fetchall()
        return jsonify([dict(r) for r in books])
    finally:
        conn.close()


@app.route("/api/survivors")
def api_survivors():
    conn = get_connection(DB_PATH)
    try:
        survivors = get_survivors(conn)
        return jsonify([dict(r) for r in survivors])
    finally:
        conn.close()


# â”€â”€ Phase triggers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.route("/api/scan", methods=["POST"])
def api_scan():
    """Run Phase A (metadata) + Phase B (dedup). Copy is NOT included."""
    data = request.json or {}
    source = data.get("source") or config.SOURCE_DIR
    if not source:
        return jsonify({"error": "No source directory configured. Set one in Settings."}), 400
    _start_pipeline_subprocess("metadata", source)
    return jsonify({"status": "started", "source": source, "phases": "metadata+dedup"})

@app.route("/api/scan_all", methods=["POST"])
def api_scan_all():
    """Run all three phases: metadata + dedup + copy."""
    data = request.json or {}
    source = data.get("source") or config.SOURCE_DIR
    if not source:
        return jsonify({"error": "No source directory configured. Set one in Settings."}), 400
    if not config.FLAT_DIR:
        return jsonify({"error": "No output directory configured. Set Flat Output Directory in Settings."}), 400
    _start_pipeline_subprocess("all", source)
    return jsonify({"status": "started", "source": source, "phases": "metadata+dedup+copy"})


@app.route("/api/scan_inbox", methods=["POST"])
def api_scan_inbox():
    data = request.json or {}
    inbox_path = getattr(config, "WATCH_DIR", config.INBOX_DIR)
    if not os.path.isdir(inbox_path):
        inbox_path = os.path.join(os.path.dirname(__file__), "inbox")
    if not os.path.isdir(inbox_path):
        return jsonify({"status": "no_inbox"})
    files = []
    for dirpath, _, filenames in os.walk(inbox_path):
        for f in filenames:
            ext = os.path.splitext(f)[1].lower()
            if ext in EBOOK_EXTS:
                files.append(os.path.join(dirpath, f))
    _start_pipeline_subprocess("all", inbox_path)
    return jsonify({"status": "started", "count": len(files)})


@app.route("/api/upload", methods=["POST"])
def api_upload():
    """Upload ebook files into the inbox (to_be_sorted) and start processing."""
    import werkzeug
    inbox_path = getattr(config, "WATCH_DIR", config.INBOX_DIR)
    if not os.path.isdir(inbox_path):
        inbox_path = os.path.join(os.path.dirname(__file__), "inbox")
    if not os.path.isdir(inbox_path):
        os.makedirs(inbox_path, exist_ok=True)

    files = request.files.getlist("files")
    allowed = EBOOK_EXTS
    saved, rejected = [], []
    for f in files:
        ext = os.path.splitext(f.filename or "")[1].lower()
        if ext not in allowed:
            rejected.append(f.filename)
            continue
        name = werkzeug.utils.secure_filename(os.path.basename(f.filename or ""))
        dst = os.path.join(inbox_path, name)
        if os.path.exists(dst):
            base, e = os.path.splitext(name)
            i = 1
            while os.path.exists(dst):
                dst = os.path.join(inbox_path, f"{base}_{i}{e}")
                i += 1
        f.save(dst)
        saved.append(os.path.basename(dst))
    if saved:
        _start_pipeline_subprocess("all", inbox_path)
    status = "started" if saved else "rejected"
    return jsonify({"status": status, "count": len(saved), "saved": saved, "rejected": rejected})


_pipeline_proc = None

def _start_pipeline_subprocess(phase, source=None, extra_args=None):
    global _pipeline_proc
    if _pipeline_proc and _pipeline_proc.poll() is None:
        logger.warning("Pipeline already running — refusing to start another")
        return
    # Check cross-process lock file
    lock_path = os.path.join(config.DATA_DIR, "pipeline.lock")
    try:
        if os.path.exists(lock_path):
            with open(lock_path, "r") as f:
                old_pid = int(f.read().strip())
            try:
                os.kill(old_pid, 0)
                logger.warning(f"Pipeline lock held by PID {old_pid} — refusing concurrent run")
                return
            except (OSError, ProcessLookupError):
                pass
    except Exception:
        pass
    import sys
    args = [sys.executable, "app.py", "--phase", phase]
    if source:
        args.extend(["--source", source])
    if extra_args:
        args.extend(extra_args)
    log_path = os.path.join(config.LOG_DIR, "pipeline.log")
    os.makedirs(config.LOG_DIR, exist_ok=True)
    log_fh = open(log_path, "a", encoding="utf-8")
    _pipeline_proc = subprocess.Popen(args, cwd=os.path.dirname(os.path.abspath(__file__)),
                                       stdout=log_fh, stderr=subprocess.STDOUT)
    logger.info(f"Started pipeline subprocess PID={_pipeline_proc.pid} phase={phase}")


@app.route("/api/phase/metadata", methods=["POST"])
def api_phase_metadata():
    data = request.json or {}
    source = data.get("source") or config.SOURCE_DIR
    if not source:
        return jsonify({"error": "No source directory configured. Set one in Settings."}), 400
    _start_pipeline_subprocess("metadata", source)
    return jsonify({"status": "started", "phase": "metadata", "source": source})


@app.route("/api/phase/dedup", methods=["POST"])
def api_phase_dedup():
    _start_pipeline_subprocess("dedup")
    return jsonify({"status": "started", "phase": "dedup"})


@app.route("/api/phase/copy", methods=["POST"])
def api_phase_copy():
    if not config.FLAT_DIR:
        return jsonify({"error": "No output directory configured. Set Flat Output Directory in Settings."}), 400
    _start_pipeline_subprocess("copy")
    return jsonify({"status": "started", "phase": "copy"})


@app.route("/api/enrich/missing", methods=["POST"])
def api_enrich_missing():
    """Kick off a background refresh of missing metadata (covers + Google Books)."""
    limit = max(1, min(int((request.json or {}).get("limit") or 500), 5000))
    _start_pipeline_subprocess("enrich", extra_args=["--enrich-limit", str(limit)])
    return jsonify({"status": "started", "phase": "enrich", "limit": limit})


# â”€â”€ Tag endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.route("/api/tags/<int:file_id>")
def api_get_tags(file_id):
    conn = get_connection(DB_PATH)
    try:
        return jsonify(get_tags(conn, file_id))
    finally:
        conn.close()


@app.route("/api/tags/<int:file_id>/add", methods=["POST"])
def api_add_tag(file_id):
    tag = request.json.get("tag", "").strip()
    if not tag:
        return jsonify({"error": "tag required"}), 400
    conn = get_connection(DB_PATH)
    try:
        add_custom_tag(conn, file_id, tag)
        conn.commit()
        return jsonify({"status": "added", "tag": tag})
    finally:
        conn.close()


@app.route("/api/tags/<int:file_id>/remove", methods=["POST"])
def api_remove_tag(file_id):
    tag = request.json.get("tag", "").strip()
    if not tag:
        return jsonify({"error": "tag required"}), 400
    conn = get_connection(DB_PATH)
    try:
        remove_custom_tag(conn, file_id, tag)
        conn.commit()
        return jsonify({"status": "removed", "tag": tag})
    finally:
        conn.close()


@app.route("/api/search/tags")
def api_search_tags():
    q = request.args.get("q", "")
    conn = get_connection(DB_PATH)
    try:
        results = search_tags(conn, q)
        return jsonify([dict(r) for r in results])
    finally:
        conn.close()


# â”€â”€ Summary â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.route("/api/summary")
def api_summary():
    conn = get_connection(DB_PATH)
    try:
        result = get_summary(conn)
        from classifier import UDC_LABELS
        result["udc_labels"] = {k: UDC_LABELS.get(k, "") for k in result["by_udc"]}
        # Archive count: books whose source_path is in the archive dir
        archive_dir = getattr(config, "ARCHIVE_DIR", None)
        if archive_dir:
            result["archive"] = conn.execute(
                "SELECT COUNT(*) FROM files WHERE source_path LIKE ?",
                (f"{archive_dir}%",)
            ).fetchone()[0]
        else:
            result["archive"] = 0
        return jsonify(result)
    finally:
        conn.close()


@app.route("/api/udc-labels")
def api_udc_labels():
    from classifier import UDC_LABELS
    return jsonify(UDC_LABELS)


# â”€â”€ Pipeline funnel â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.route("/api/funnel")
def api_funnel():
    conn = get_connection(DB_PATH)
    try:
        return jsonify(get_funnel(conn))
    finally:
        conn.close()


# â”€â”€ Per-file pipeline log â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.route("/api/book/<int:book_id>/log")
def api_book_log(book_id):
    conn = get_connection(DB_PATH)
    try:
        rows = get_book_pipeline_log(conn, book_id)
        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()


# â”€â”€ Cover gallery â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.route("/api/covers")
def api_covers():
    conn = get_connection(DB_PATH)
    try:
        stage = request.args.get("stage") or None
        udc = request.args.get("udc") or None

        sql = """
            SELECT f.id, f.uuid, f.filename, f.format, f.stage, f.source_path, f.source_group,
                   m.title, m.authors, m.udc_code, m.udc_label, m.year, m.cover_path, m.enrich_source
            FROM files f
            JOIN metadata m ON m.file_id = f.id
            WHERE m.cover_path IS NOT NULL AND m.cover_path != ''
        """
        params = []
        if stage:
            sql += " AND f.stage = ?"
            params.append(stage)
        if udc:
            sql += " AND m.udc_code = ?"
            params.append(udc)
        sql += " ORDER BY f.updated_at DESC LIMIT 200"

        rows = conn.execute(sql, params).fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()


@app.route("/api/cover/<int:book_id>")
def api_cover(book_id):
    conn = get_connection(DB_PATH)
    try:
        row = conn.execute(
            "SELECT cover_path FROM metadata WHERE file_id=? AND cover_path IS NOT NULL",
            (book_id,)
        ).fetchone()
        if not row or not os.path.isfile(row["cover_path"]):
            return jsonify({"error": "cover not found"}), 404
        covers_dir = config.COVER_DIR
        return _safe_send_path(row["cover_path"], [covers_dir], mimetype="image/jpeg")
    finally:
        conn.close()


# â”€â”€ Sources list â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.route("/api/sources")
def api_sources():
    conn = get_connection(DB_PATH)
    try:
        rows = conn.execute(
            "SELECT source_group, COUNT(*) as count FROM files WHERE source_group IS NOT NULL GROUP BY source_group ORDER BY count DESC"
        ).fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()


# â”€â”€ Daemon IPC â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.route("/api/daemon")
def api_daemon_status():
    return jsonify(get_daemon_status(DB_PATH))


# â”€â”€ In-process Watcher â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_watcher_thread = None
_watcher_observer = None


@app.route("/api/daemon/watch", methods=["POST"])
def api_daemon_watch_start():
    global _watcher_thread, _watcher_observer
    if _watcher_thread and _watcher_thread.is_alive():
        return jsonify({"status": "already running"})
    from watcher import start_watcher
    import threading
    watch_dir = getattr(config, "WATCH_DIR", config.INBOX_DIR)
    recursive = getattr(config, "WATCH_RECURSIVE", True)
    init_db(config.DB_PATH)
    if config.FLAT_DIR: os.makedirs(config.FLAT_DIR, exist_ok=True)
    load_config_overrides(get_connection(config.DB_PATH))
    state.watcher_active = True
    _watcher_observer = start_watcher(watch_dir, recursive=recursive)
    def _run():
        global _watcher_observer
        try:
            _watcher_observer.join()
        except Exception:
            pass
    _watcher_thread = threading.Thread(target=_run, daemon=True)
    _watcher_thread.start()
    daemon_heartbeat(config.DB_PATH, "watch", "running", current_phase="watch", current_stage="watching")
    return jsonify({"status": "started", "watch_dir": watch_dir, "recursive": recursive})


@app.route("/api/daemon/watch", methods=["DELETE"])
def api_daemon_watch_stop():
    global _watcher_thread, _watcher_observer
    if not _watcher_observer:
        return jsonify({"status": "not running"})
    try:
        _watcher_observer.stop()
        _watcher_observer.join(timeout=5)
    except Exception:
        pass
    _watcher_observer = None
    _watcher_thread = None
    state.watcher_active = False
    daemon_heartbeat(config.DB_PATH, "watch", "done")
    return jsonify({"status": "stopped"})


@app.route("/api/daemon/watch/running")
def api_daemon_watch_running():
    alive = _watcher_thread is not None and _watcher_thread.is_alive()
    return jsonify({"running": alive})


# â”€â”€ Manual metadata update â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.route("/api/book/<int:book_id>/update", methods=["POST"])
def api_book_update(book_id):
    conn = get_connection(DB_PATH)
    try:
        book = get_book_by_id(conn, book_id)
        if not book:
            return jsonify({"error": "not found"}), 404
        data = request.json or {}
        fields = {}
        for key in ("title", "authors", "publisher", "isbn", "language", "pages", "year", "description"):
            if key in data:
                fields[key] = data[key]
        udc_code = data.get("udc_code")
        if udc_code:
            fields["udc_code"] = udc_code
            from classifier import UDC_LABELS
            fields["udc_label"] = UDC_LABELS.get(udc_code, "")
        if not fields and not data.get("add_tags"):
            return jsonify({"error": "no fields to update"}), 400
        from datetime import datetime
        from db import upsert_metadata, set_tags
        if fields:
            upsert_metadata(conn, book_id, enrich_source="manual",
                            enriched_at=datetime.utcnow().isoformat(), **fields)
            if udc_code:
                set_tags(conn, book_id, [{"tag": udc_code, "tag_label": fields.get("udc_label", "")}], tag_type="udc")
        add_tags = data.get("add_tags")
        if add_tags:
            for tag in add_tags:
                from db import add_custom_tag
                add_custom_tag(conn, book_id, tag)
        from db import update_fts_for_book
        if fields:
            update_fts_for_book(conn, book_id)
        conn.commit()
        return jsonify({"status": "updated", "fields": list(fields.keys())})
    finally:
        conn.close()


# â”€â”€ Quarantine â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.route("/api/quarantine")
def api_quarantine():
    reviewed = request.args.get("reviewed", type=int)
    limit = request.args.get("limit", default=100, type=int)
    offset = request.args.get("offset", default=0, type=int)
    error_code = request.args.get("error_code") or None
    q = request.args.get("q") or None
    fmt = request.args.get("format") or None
    date_from = request.args.get("date_from") or None
    date_to = request.args.get("date_to") or None
    conn = get_connection(DB_PATH)
    try:
        results, total = get_quarantined(conn, reviewed=reviewed, limit=limit, offset=offset,
                                          error_code=error_code, q=q, fmt=fmt,
                                          date_from=date_from, date_to=date_to)
        return jsonify({"results": results, "total": total})
    finally:
        conn.close()


@app.route("/api/quarantine/resolve", methods=["POST"])
def api_quarantine_resolve():
    data = request.json or {}
    file_id = data.get("file_id")
    if not file_id:
        return jsonify({"error": "file_id required"}), 400
    reviewed = data.get("reviewed", 1)  # 1=reviewed, 2=dismissed
    user_notes = data.get("user_notes")
    conn = get_connection(DB_PATH)
    try:
        resolve_quarantine(conn, file_id, reviewed=reviewed, user_notes=user_notes)
        from db import set_stage
        book = get_book_by_id(conn, file_id)
        prev_stage = book["stage"] if book else "arrived"
        # If dismissed, revert to previous stage (or arrived)
        if reviewed == 2:
            set_stage(conn, file_id, prev_stage)
        conn.commit()
        return jsonify({"status": "resolved", "file_id": file_id, "reviewed": reviewed})
    finally:
        conn.close()


@app.route("/api/quarantine/errors")
def api_quarantine_errors():
    return jsonify(QUARANTINE_ERRORS)


@app.route("/api/quarantine/ambiguous")
def api_quarantine_ambiguous():
    conn = get_connection(DB_PATH)
    try:
        rows = conn.execute("""
            SELECT q.file_id, q.detail, q.created_at,
                   f.filename, f.format, f.stage, f.file_size, f.source_path,
                    m.title, m.authors, m.year, m.udc_code, m.udc_label, m.cover_path
            FROM quarantined q
            JOIN files f ON f.id = q.file_id
            LEFT JOIN metadata m ON m.file_id = q.file_id
            WHERE q.error_code = 'DEDUP_AMBIGUOUS' AND q.reviewed = 0
            ORDER BY q.id
        """).fetchall()
        # Group by detail string into pairs
        groups = {}
        for r in rows:
            groups.setdefault(r["detail"], []).append(dict(r))
        pairs = [g for g in groups.values() if len(g) >= 2]
        return jsonify(pairs)
    finally:
        conn.close()


@app.route("/api/quarantine/resolve-ambiguous", methods=["POST"])
def api_quarantine_resolve_ambiguous():
    data = request.json or {}
    keep_id = data.get("keep_id")
    skip_id = data.get("skip_id")
    if not keep_id or not skip_id:
        return jsonify({"error": "keep_id and skip_id required"}), 400
    conn = get_connection(DB_PATH)
    try:
        from db import mark_duplicate
        mark_duplicate(conn, skip_id, "dedup_ambiguous_resolved")
        conn.execute("UPDATE quarantined SET reviewed=2 WHERE file_id IN (?, ?)",
                     (keep_id, skip_id))
        conn.commit()
        return jsonify({"status": "resolved", "keep": keep_id, "skip": skip_id})
    finally:
        conn.close()


@app.route("/api/quarantine/keep-both", methods=["POST"])
def api_quarantine_keep_both():
    data = request.json or {}
    id_a = data.get("id_a")
    id_b = data.get("id_b")
    if not id_a or not id_b:
        return jsonify({"error": "id_a and id_b required"}), 400
    conn = get_connection(DB_PATH)
    try:
        from db import mark_survivor
        mark_survivor(conn, id_a)
        mark_survivor(conn, id_b)
        conn.execute("UPDATE quarantined SET reviewed=1 WHERE file_id IN (?, ?)",
                     (id_a, id_b))
        conn.commit()
        return jsonify({"status": "kept_both", "files": [id_a, id_b]})
    finally:
        conn.close()


@app.route("/api/quarantine/counts")
def api_quarantine_counts():
    conn = get_connection(DB_PATH)
    try:
        by_error = get_quarantine_counts_by_error(conn, reviewed=0)
        by_format = get_quarantine_formats(conn, reviewed=0)
        return jsonify({"by_error": by_error, "by_format": by_format})
    finally:
        conn.close()


@app.route("/api/quarantine/bulk/dismiss", methods=["POST"])
def api_quarantine_bulk_dismiss():
    data = request.json or {}
    file_ids = data.get("file_ids", [])
    if not file_ids:
        return jsonify({"error": "file_ids required"}), 400
    conn = get_connection(DB_PATH)
    try:
        bulk_dismiss(conn, file_ids)
        conn.commit()
        return jsonify({"status": "dismissed", "count": len(file_ids)})
    finally:
        conn.close()


@app.route("/api/quarantine/bulk/keep-both", methods=["POST"])
def api_quarantine_bulk_keep_both():
    data = request.json or {}
    file_ids = data.get("file_ids", [])
    if not file_ids:
        return jsonify({"error": "file_ids required"}), 400
    conn = get_connection(DB_PATH)
    try:
        bulk_keep_both(conn, file_ids)
        conn.commit()
        return jsonify({"status": "kept_both", "count": len(file_ids)})
    finally:
        conn.close()


@app.route("/api/quarantine/bulk/delete", methods=["POST"])
def api_quarantine_bulk_delete():
    data = request.json or {}
    file_ids = data.get("file_ids", [])
    if not file_ids:
        return jsonify({"error": "file_ids required"}), 400
    conn = get_connection(DB_PATH)
    try:
        bulk_delete_files(conn, file_ids)
        conn.commit()
        return jsonify({"status": "deleted", "count": len(file_ids)})
    finally:
        conn.close()


@app.route("/api/quarantine/bulk/reprocess", methods=["POST"])
def api_quarantine_bulk_reprocess():
    data = request.json or {}
    file_ids = data.get("file_ids", [])
    if not file_ids:
        return jsonify({"error": "file_ids required"}), 400
    from pipeline import state
    results = []
    for fid in file_ids:
        try:
            resp = api_book_re_extract(fid)
            results.append({"file_id": fid, "status": "ok"})
        except Exception as e:
            results.append({"file_id": fid, "status": "error", "detail": str(e)})
    conn = get_connection(DB_PATH)
    try:
        for r in results:
            if r["status"] == "ok":
                conn.execute("UPDATE quarantined SET reviewed=1 WHERE file_id=?", (r["file_id"],))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"results": results})


@app.route("/api/quarantine/rules", methods=["GET", "POST"])
def api_quarantine_rules():
    conn = get_connection(DB_PATH)
    try:
        if request.method == "POST":
            data = request.json or {}
            for name, value in data.items():
                set_quarantine_rule(conn, name, value)
            conn.commit()
        rules = get_quarantine_rules(conn)
        return jsonify(rules)
    finally:
        conn.close()


@app.route("/api/quarantine/undo/dismiss", methods=["POST"])
def api_quarantine_undo_dismiss():
    data = request.json or {}
    file_ids = data.get("file_ids", [])
    if not file_ids:
        return jsonify({"error": "file_ids required"}), 400
    conn = get_connection(DB_PATH)
    try:
        from datetime import datetime
        now = datetime.utcnow().isoformat()
        for fid in file_ids:
            conn.execute("""
                INSERT OR IGNORE INTO quarantined (file_id, error_code, detail, reviewed, created_at)
                VALUES (?, 'UNDO_DISMISS', 'Re-quarantined via undo', 0, ?)
            """, (fid, now))
            conn.execute("""
                UPDATE quarantined SET reviewed=0, reviewed_at=NULL, created_at=?
                WHERE file_id=?
            """, (now, fid))
            conn.execute("UPDATE files SET stage='quarantined', updated_at=? WHERE id=?", (now, fid))
        conn.commit()
        return jsonify({"status": "undone", "count": len(file_ids)})
    finally:
        conn.close()


@app.route("/api/quarantine/undo/keep-both", methods=["POST"])
def api_quarantine_undo_keep_both():
    data = request.json or {}
    file_ids = data.get("file_ids", [])
    if not file_ids:
        return jsonify({"error": "file_ids required"}), 400
    conn = get_connection(DB_PATH)
    try:
        from datetime import datetime
        now = datetime.utcnow().isoformat()
        for fid in file_ids:
            conn.execute("""
                INSERT OR IGNORE INTO quarantined (file_id, error_code, detail, reviewed, created_at)
                VALUES (?, 'UNDO_KEEP_BOTH', 'Re-quarantined via undo', 0, ?)
            """, (fid, now))
            conn.execute("""
                UPDATE quarantined SET reviewed=0, reviewed_at=NULL, created_at=?
                WHERE file_id=?
            """, (now, fid))
            conn.execute("UPDATE files SET stage='quarantined', is_master=0, updated_at=? WHERE id=?", (now, fid))
        conn.commit()
        return jsonify({"status": "undone", "count": len(file_ids)})
    finally:
        conn.close()


# â”€â”€ Config â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    conn = get_connection(DB_PATH)
    try:
        if request.method == "POST":
            data = request.json or {}
            overrides = data.get("overrides", {})
            for name, value in overrides.items():
                if value is None or value == "":
                    delete_config_override(conn, name)
                else:
                    set_config_override(conn, name, value)
            conn.commit()
            load_config_overrides(conn)
        config_data = get_all_config(conn)
        return jsonify(config_data)
    finally:
        conn.close()


@app.route("/api/config/export")
def api_config_export():
    from datetime import datetime
    conn = get_connection(DB_PATH)
    try:
        overrides = get_config_overrides(conn)
        config_data = get_all_config(conn)
        return jsonify({
            "app_version": "book_organiser",
            "exported_at": datetime.utcnow().isoformat(),
            "overrides": overrides,
            "full_config": config_data,
        })
    finally:
        conn.close()


@app.route("/api/config/import", methods=["POST"])
def api_config_import():
    data = request.json or {}
    overrides = data.get("overrides", {})
    if not overrides:
        return jsonify({"error": "no overrides in import data"}), 400
    conn = get_connection(DB_PATH)
    try:
        for name, value in overrides.items():
            set_config_override(conn, name, value)
        conn.commit()
        load_config_overrides(conn)
        return jsonify({"status": "imported", "count": len(overrides)})
    finally:
        conn.close()


@app.route("/api/admin/sync-db", methods=["POST"])
def api_admin_sync_db():
    """Push local DB copy back to the original network path (D7.5)."""
    if not getattr(config, "LOCAL_DB_REDIRECTED", False):
        return jsonify({"error": "DB was not redirected — nothing to sync"}), 400
    src = config.DB_PATH
    dst = config.ORIGINAL_DB_PATH
    if not os.path.isfile(src):
        return jsonify({"error": "local DB not found"}), 404
    # Safety: never push an empty local cache over a populated original
    try:
        import sqlite3
        conn = sqlite3.connect(src)
        try:
            local_count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        finally:
            conn.close()
        if os.path.isfile(dst):
            dconn = sqlite3.connect(dst)
            try:
                remote_count = dconn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            finally:
                dconn.close()
            if local_count == 0 and remote_count > 0:
                return jsonify({"error": "refusing to push empty local DB over populated original"}), 409
    except Exception:
        pass
    import shutil
    try:
        dst_dir = os.path.dirname(dst)
        os.makedirs(dst_dir, exist_ok=True)
        shutil.copy2(src, dst)
        return jsonify({"status": "ok", "copied": src, "to": dst})
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@app.route("/api/admin/remap-paths", methods=["POST"])
def api_admin_remap_paths():
    """Bulk-replace path prefixes in config_overrides and files table (P6.1)."""
    data = request.json or {}
    old_prefix = data.get("old_prefix", "")
    new_prefix = data.get("new_prefix", "")
    if not old_prefix or not new_prefix:
        return jsonify({"error": "old_prefix and new_prefix required"}), 400
    conn = get_connection(config.DB_PATH)
    try:
        changes = {"config_overrides": 0, "files_source": 0, "files_archive": 0, "metadata_cover": 0}
        for r in conn.execute("SELECT name, value FROM config_overrides").fetchall():
            if r["value"] and r["value"].startswith(old_prefix):
                new_val = new_prefix + r["value"][len(old_prefix):]
                conn.execute("UPDATE config_overrides SET value=? WHERE name=?", (new_val, r["name"]))
                changes["config_overrides"] += 1
        for r in conn.execute("SELECT id, source_path FROM files").fetchall():
            if r["source_path"] and r["source_path"].startswith(old_prefix):
                new_path = new_prefix + r["source_path"][len(old_prefix):]
                conn.execute("UPDATE files SET source_path=? WHERE id=?", (new_path, r["id"]))
                changes["files_source"] += 1
            if "archive_path" in r.keys() and r["archive_path"] and r["archive_path"].startswith(old_prefix):
                new_path = new_prefix + r["archive_path"][len(old_prefix):]
                conn.execute("UPDATE files SET archive_path=? WHERE id=?", (new_path, r["id"]))
                changes["files_archive"] += 1
        for r in conn.execute("SELECT file_id, cover_path FROM metadata WHERE cover_path IS NOT NULL").fetchall():
            if r["cover_path"] and r["cover_path"].startswith(old_prefix):
                new_path = new_prefix + r["cover_path"][len(old_prefix):]
                conn.execute("UPDATE metadata SET cover_path=? WHERE file_id=?", (new_path, r["file_id"]))
                changes["metadata_cover"] += 1
        conn.commit()
        return jsonify({"status": "ok", "changes": changes, "old_prefix": old_prefix, "new_prefix": new_prefix})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


# Per-book re-processing


@app.route("/api/book/<int:book_id>/re-extract", methods=["POST"])
def api_book_re_extract(book_id):
    conn = get_connection(DB_PATH)
    try:
        book = get_book_by_id(conn, book_id)
        if not book:
            return jsonify({"error": "not found"}), 404
        filepath = book["source_path"]
        if not os.path.isfile(filepath):
            return jsonify({"error": f"source file not found: {filepath}"}), 404

        from pipeline import state
        from extractors import extract_metadata
        from filename_cleaner import clean_filename, extract_year_from_filename, file_hash
        from enrich_filename import enrich_from_filename
        from enricher import enrich_book
        from classifier import classify, classify_all
        from db import upsert_metadata, set_tags, rebuild_fts, set_stage

        state.update(log_msg=f"  â–¶ re-extracting book #{book_id}")

        raw_meta = extract_metadata(filepath)
        if "_error" in raw_meta:
            state.update(log_msg=f"  âœ— re-extract failed: {raw_meta['_error']}")
            return jsonify({"error": raw_meta["_error"]}), 400

        fname = os.path.basename(filepath)
        fname_stem = os.path.splitext(fname)[0]
        enriched = {}
        if not raw_meta.get("title") or not raw_meta.get("authors"):
            enriched = enrich_from_filename(fname)
        clean_title = raw_meta.get("title") or enriched.get("title") or fname_stem
        clean_authors = raw_meta.get("authors") or enriched.get("author") or ""
        year = raw_meta.get("year") or enriched.get("year") or extract_year_from_filename(fname)

        enrich_source = "embedded"
        if not raw_meta.get("title") and enriched.get("title"):
            enrich_source = "filename"

        upsert_metadata(conn, book_id,
                        title=clean_title, authors=clean_authors,
                        publisher=raw_meta.get("publisher"), isbn=raw_meta.get("isbn"),
                        language=raw_meta.get("language"), pages=raw_meta.get("pages"),
                        year=year, description=raw_meta.get("description"),
                        subjects=raw_meta.get("subjects"),
                        enrich_source=enrich_source,
                        enriched_at=datetime.utcnow().isoformat())

        # External enrichment
        need_enrich = (
            not raw_meta.get("title") or not raw_meta.get("authors")
            or not raw_meta.get("description") or not raw_meta.get("isbn")
            or not raw_meta.get("publisher")
        )
        if need_enrich:
            try:
                api_enriched = enrich_book(
                    isbn=raw_meta.get("isbn"),
                    title=clean_title,
                    author=clean_authors,
                )
                api_source = api_enriched.get("source", "openlibrary")
                upsert_metadata(conn, book_id,
                                title=api_enriched.get("title") or None,
                                authors=api_enriched.get("authors") or None,
                                publisher=api_enriched.get("publisher") or None,
                                isbn=api_enriched.get("isbn") or None,
                                language=api_enriched.get("language") or None,
                                pages=api_enriched.get("pages") or None,
                                year=api_enriched.get("year") or None,
                                description=api_enriched.get("description") or None,
                                subjects=api_enriched.get("subjects") or None,
                                enrich_source=api_source,
                                enriched_at=datetime.utcnow().isoformat())
                if api_enriched.get("title"):
                    clean_title = api_enriched["title"]
                if api_enriched.get("authors"):
                    clean_authors = api_enriched["authors"]
                if api_enriched.get("year"):
                    year = api_enriched["year"]
            except Exception:
                pass

        # Classify
        udc_code, udc_label = classify(
            raw_meta.get("title"), raw_meta.get("authors"),
            raw_meta.get("subjects"), raw_meta.get("description"),
        )
        upsert_metadata(conn, book_id, udc_code=udc_code, udc_label=udc_label)
        all_udc_tags = classify_all(
            raw_meta.get("title"), raw_meta.get("authors"),
            raw_meta.get("subjects"), raw_meta.get("description"),
        )
        set_tags(conn, book_id, all_udc_tags, tag_type="udc")
        set_stage(conn, book_id, "cataloged")
        conn.commit()

        rebuilt = rebuild_fts(conn, book_id=book_id)
        conn.commit()

        state.update(log_msg=f"  âœ“ re-extracted book #{book_id} (FTS: {rebuilt} docs)")
        return jsonify({"status": "ok", "stage": "cataloged"})
    finally:
        conn.close()


@app.route("/api/book/<int:book_id>/re-dedup", methods=["POST"])
def api_book_re_dedup(book_id):
    conn = get_connection(DB_PATH)
    try:
        book = get_book_by_id(conn, book_id)
        if not book:
            return jsonify({"error": "not found"}), 404

        from pipeline import state
        from db import get_cataloged_files, mark_survivor, mark_duplicate
        from filename_cleaner import normalize_title, is_duplicate_title

        # Reset the book to cataloged
        from datetime import datetime as dt
        conn.execute("UPDATE files SET stage='cataloged', is_master=NULL, updated_at=? WHERE id=?",
                     (dt.utcnow().isoformat(), book_id))
        conn.execute("INSERT INTO pipeline_log (file_id, stage, status, message) VALUES (?,?,?,?)",
                     (book_id, "cataloged", "done", "reset for re-dedup"))
        conn.commit()

        state.update(log_msg=f"  â–¶ re-dedup book #{book_id}")

        all_cataloged = get_cataloged_files(conn)
        target = None
        for r in all_cataloged:
            if r["id"] == book_id:
                target = r
                break

        if not target:
            return jsonify({"error": "book not at cataloged stage"}), 400

        # Hash check
        th = target["file_hash"]
        if th:
            for r in all_cataloged:
                if r["id"] != book_id and r["file_hash"] == th:
                    mark_duplicate(conn, book_id, "duplicate_by_hash")
                    conn.commit()
                    state.update(log_msg=f"  âœ— re-dedup: hash dup of #{r['id']}")
                    return jsonify({"status": "skipped", "reason": "duplicate_by_hash", "dup_id": r["id"]})

        # ISBN check
        tisbn = (target.get("isbn") or "").strip().replace("-", "")
        if tisbn:
            for r in all_cataloged:
                if r["id"] == book_id:
                    continue
                risbn = (r.get("isbn") or "").strip().replace("-", "")
                if risbn == tisbn:
                    mark_duplicate(conn, book_id, "duplicate_by_isbn")
                    conn.commit()
                    state.update(log_msg=f"  âœ— re-dedup: isbn dup of #{r['id']}")
                    return jsonify({"status": "skipped", "reason": "duplicate_by_isbn", "dup_id": r["id"]})

        # Title + UDC check
        ttitle = normalize_title(target.get("title") or "")
        tcode = target.get("udc_code") or ""
        if ttitle:
            for r in all_cataloged:
                if r["id"] == book_id:
                    continue
                rtitle = normalize_title(r.get("title") or "")
                rcode = r.get("udc_code") or ""
                if rtitle and tcode == rcode:
                    if is_duplicate_title(rtitle, ttitle, config.DUPLICATE_SIMILARITY_THRESHOLD):
                        from pipeline import _metadata_richness
                        if _metadata_richness(target) <= _metadata_richness(r):
                            mark_duplicate(conn, book_id, "duplicate_by_title")
                            conn.commit()
                            state.update(log_msg=f"  âœ— re-dedup: title dup of #{r['id']}")
                            return jsonify({"status": "skipped", "reason": "duplicate_by_title", "dup_id": r["id"]})

        # Author + Year + Title check
        tauthors = (target.get("authors") or "").strip().lower()
        tyear = target.get("year")
        if ttitle and tauthors and tyear:
            for r in all_cataloged:
                if r["id"] == book_id:
                    continue
                rauthors = (r.get("authors") or "").strip().lower()
                ryear = r.get("year")
                rtitle = normalize_title(r.get("title") or "")
                if rtitle and rauthors and ryear:
                    if tauthors == rauthors and tyear == ryear:
                        if is_duplicate_title(rtitle, ttitle, config.DUPLICATE_SIMILARITY_THRESHOLD):
                            from pipeline import _metadata_richness
                            if _metadata_richness(target) <= _metadata_richness(r):
                                mark_duplicate(conn, book_id, "duplicate_by_author_year_title")
                                conn.commit()
                                state.update(log_msg=f"  âœ— re-dedup: author+year+title dup of #{r['id']}")
                                return jsonify({"status": "skipped", "reason": "duplicate_by_author_year_title", "dup_id": r["id"]})

        # Passed all checks
        mark_survivor(conn, book_id)
        conn.commit()
        state.update(log_msg=f"  âœ“ re-dedup: book #{book_id} confirmed survivor")
        return jsonify({"status": "survivor"})
    finally:
        conn.close()


@app.route("/api/book/<int:book_id>/force-keep", methods=["POST"])
def api_book_force_keep(book_id):
    """Mark a book as survivor/master, overriding any dedup decision."""
    conn = get_connection(DB_PATH)
    try:
        book = get_book_by_id(conn, book_id)
        if not book:
            return jsonify({"error": "not found"}), 404
        from datetime import datetime as dt
        now = dt.utcnow().isoformat()
        conn.execute(
            "UPDATE files SET stage='survivor', is_master=1, stage_error=NULL, updated_at=? WHERE id=?",
            (now, book_id))
        conn.execute(
            "INSERT INTO pipeline_log (file_id, stage, status, message) VALUES (?,?,?,?)",
            (book_id, "survivor", "done", "force-kept by user"))
        conn.commit()
        return jsonify({"status": "survivor"})
    finally:
        conn.close()


@app.route("/api/book/<int:book_id>/re-copy", methods=["POST"])
def api_book_re_copy(book_id):
    conn = get_connection(DB_PATH)
    try:
        book = get_book_by_id(conn, book_id)
        if not book:
            return jsonify({"error": "not found"}), 404
        if book["stage"] != "survivor":
            return jsonify({"error": "book must be at survivor stage"}), 400

        import shutil
        from filename_cleaner import clean_filename

        ext = os.path.splitext(book["source_path"])[1].lower()
        if ext not in {f".{f}" for f in set()} | config.EBOOK_EXTS:
            return jsonify({"error": f"non-ebook extension: {ext}"}), 400

        out_dir = config.FLAT_DIR
        os.makedirs(out_dir, exist_ok=True)

        fname = os.path.basename(book["filename"])
        clean_name = clean_filename(fname)
        dest = os.path.join(out_dir, clean_name)
        if os.path.exists(dest):
            base, ext = os.path.splitext(clean_name)
            dest = os.path.join(out_dir, f"{base}_{book_id}{ext}")

        shutil.copy2(book["source_path"], dest)
        from datetime import datetime as dt
        conn.execute("UPDATE files SET stage='copied', updated_at=? WHERE id=?",
                     (dt.utcnow().isoformat(), book_id))
        conn.execute("INSERT INTO pipeline_log (file_id, stage, status, message) VALUES (?,?,?,?)",
                     (book_id, "copied", "done", f"copied to {dest}"))

        from pipeline import state
        state.update(log_msg=f"  âœ“ re-copied book #{book_id} â†’ {dest}")

        conn.commit()
        return jsonify({"status": "copied", "dest": dest})
    finally:
        conn.close()


@app.route("/api/book/<int:book_id>/download")
def api_book_download(book_id):
    conn = get_connection(DB_PATH)
    try:
        book = get_book_by_id(conn, book_id)
        if not book:
            return jsonify({"error": "not found"}), 404

        from filename_cleaner import clean_filename
        import mimetypes

        filepath = resolve_book_path(book)
        if filepath:
            fname = clean_filename(os.path.basename(filepath))
        else:
            fname_orig = book["filename"] or f"book_{book_id}"
            return jsonify({"error": "file not found on disk"}), 404

        mt, _ = mimetypes.guess_type(filepath)
        return _safe_send_path(filepath, _readable_dirs(), as_attachment=True, download_name=fname, mimetype=mt or "application/octet-stream")
    finally:
        conn.close()


COMIC_CACHE = os.path.join(config.BASE_DIR, "data", "cache", "comic")
_comic_extract_cache = {}
_comic_extract_lock = threading.Lock()
_comic_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

def _extract_comic(book_id, filepath):
    """Extract a comic archive (CBZ/CBR) to cache and return sorted image list."""
    cache_dir = os.path.join(COMIC_CACHE, str(book_id))
    os.makedirs(cache_dir, exist_ok=True)
    if not os.listdir(cache_dir):
        if not filepath:
            return []
        ext = os.path.splitext(filepath)[1].lower()
        try:
            if ext == ".cbz":
                import zipfile
                with zipfile.ZipFile(filepath) as zf:
                    zf.extractall(cache_dir)
            elif ext == ".cbr":
                import rarfile
                with rarfile.RarFile(filepath) as rf:
                    rf.extractall(cache_dir)
        except Exception:
            return []
    img_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
    pages = []
    for root, dirs, files in os.walk(cache_dir):
        for f in sorted(files):
            if os.path.splitext(f)[1].lower() in img_exts:
                pages.append(os.path.join(root, f))
    return pages

def _extract_comic_async(book_id, filepath):
    """Run _extract_comic in background and cache result (D7.20)."""
    cache_dir = os.path.join(COMIC_CACHE, str(book_id))
    if os.path.isdir(cache_dir) and os.listdir(cache_dir):
        # Already cached
        pages = _extract_comic(book_id, None)
        with _comic_extract_lock:
            _comic_extract_cache[book_id] = {"pages": pages, "done": True}
        return pages
    future = _comic_executor.submit(_extract_comic, book_id, filepath)
    with _comic_extract_lock:
        _comic_extract_cache[book_id] = {"future": future, "done": False, "pages": None}
    return None

@app.route("/api/comic-status/<int:book_id>")
def api_comic_status(book_id):
    with _comic_extract_lock:
        entry = _comic_extract_cache.get(book_id)
    if not entry:
        return jsonify({"status": "not_found"}), 404
    if entry.get("done") and entry.get("pages") is not None:
        return jsonify({"status": "done", "total": len(entry["pages"])})
    if entry.get("done") and entry.get("pages") is None:
        return jsonify({"status": "error"}), 500
    if entry.get("future"):
        future = entry["future"]
        if future.done():
            try:
                pages = future.result()
                with _comic_extract_lock:
                    _comic_extract_cache[book_id] = {"pages": pages, "done": True, "future": None}
                if pages:
                    return jsonify({"status": "done", "total": len(pages)})
                else:
                    return jsonify({"status": "error"}), 500
            except Exception:
                with _comic_extract_lock:
                    _comic_extract_cache[book_id] = {"pages": None, "done": True, "future": None}
                return jsonify({"status": "error"}), 500
    return jsonify({"status": "extracting"})


# â”€â”€ Ebook conversion (AZW3, MOBI, FB2 â†’ EPUB) via calibre â”€â”€
CONVERT_EXTS = {".azw3", ".mobi", ".fb2"}

def _convert_to_epub(filepath):
    ext = (os.path.splitext(filepath)[1] or ".epub").lower()
    # 1) calibre (full fidelity) if installed
    exe = shutil.which("ebook-convert")
    if exe:
        fd, outpath = tempfile.mkstemp(suffix=".epub")
        os.close(fd)
        try:
            subprocess.run([exe, filepath, outpath], capture_output=True, timeout=120, check=True)
            if os.path.isfile(outpath) and os.path.getsize(outpath) > 0:
                return outpath
        except Exception:
            try:
                os.unlink(outpath)
            except Exception:
                pass
    # 2) pure-stdlib fallback (P8.2) — no external tools
    import mobi_reader
    fd, outpath = tempfile.mkstemp(suffix=".epub")
    os.close(fd)
    result = mobi_reader.render_to_epub(filepath, outpath, ext)
    if result:
        return result
    try:
        os.unlink(outpath)
    except Exception:
        pass
    return None

CONVERT_EXTS = {".azw3", ".mobi", ".fb2"}
_conversion_cache = {}
_conversion_cache_lock = threading.Lock()
_conversion_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

@app.route("/api/conversion-status/<int:book_id>")
def api_conversion_status(book_id):
    with _conversion_cache_lock:
        entry = _conversion_cache.get(book_id)
    if not entry:
        return jsonify({"status": "not_found"}), 404
    if entry.get("path"):
        return jsonify({"status": "done"})
    if entry.get("error"):
        return jsonify({"status": "error", "error": entry["error"]})
    return jsonify({"status": "converting"})


@app.route("/api/book/<int:book_id>/read")
def api_book_read(book_id):
    conn = get_connection(DB_PATH)
    try:
        book = get_book_by_id(conn, book_id)
        if not book:
            return jsonify({"error": "not found"}), 404

        filepath = resolve_book_path(book)
        if not filepath:
            return jsonify({"error": "file not found on disk"}), 404

        ext = os.path.splitext(filepath)[1].lower()
        if ext not in config.EBOOK_EXTS:
            return jsonify({"error": "unsupported format for in-browser reading"}), 400

        if ext == ".epub":
            import tempfile
            allowed = list(_readable_dirs()) + [tempfile.gettempdir()]
            return _safe_send_path(filepath, allowed, mimetype="application/epub+zip")
        elif ext == ".pdf":
            import tempfile
            allowed = list(_readable_dirs()) + [tempfile.gettempdir()]
            return _safe_send_path(filepath, allowed, mimetype="application/pdf")
        elif ext in (".cbz", ".cbr"):
            with _comic_extract_lock:
                cached = _comic_extract_cache.get(book_id)
            if cached and cached.get("done") and cached.get("pages"):
                return jsonify({"format": ext, "total": len(cached["pages"]), "book_id": book_id})
            if cached and cached.get("done") and cached.get("pages") is None:
                return jsonify({"error": "extraction failed"}), 500
            result = _extract_comic_async(book_id, filepath)
            if result is not None:
                return jsonify({"format": ext, "total": len(result), "book_id": book_id})
            return jsonify({"status": "extracting", "book_id": book_id}), 202
        elif ext in CONVERT_EXTS:
            with _conversion_cache_lock:
                entry = _conversion_cache.get(book_id)
            if entry and entry.get("path"):
                return send_file(entry["path"], mimetype="application/epub+zip")
            if entry and entry.get("error"):
                return jsonify({"error": entry["error"]}), 500
            if entry and entry.get("future"):
                future = entry["future"]
                if future.done():
                    try:
                        result = future.result()
                        with _conversion_cache_lock:
                            if result:
                                _conversion_cache[book_id] = {"path": result, "future": None, "error": None}
                                return send_file(result, mimetype="application/epub+zip")
                            else:
                                _conversion_cache[book_id] = {"path": None, "future": None, "error": "conversion failed"}
                                return jsonify({"error": "Conversion failed"}), 500
                    except Exception as exc:
                        with _conversion_cache_lock:
                            _conversion_cache[book_id] = {"path": None, "future": None, "error": str(exc)}
                        return jsonify({"error": str(exc)}), 500
            if not entry:
                future = _conversion_executor.submit(_convert_to_epub, filepath)
                with _conversion_cache_lock:
                    _conversion_cache[book_id] = {"future": future, "path": None, "error": None}
            return jsonify({"status": "converting", "book_id": book_id}), 202
        else:
            return jsonify({"error": "format not supported for in-browser reading, use Download instead"}), 400
    finally:
        conn.close()


@app.route("/api/book/<int:book_id>/read/page/<int:page_num>")
def api_book_read_page(book_id, page_num):
    pages = _extract_comic(book_id, None)
    if not pages or page_num < 0 or page_num >= len(pages):
        return jsonify({"error": "page not found"}), 404
    import mimetypes
    mt, _ = mimetypes.guess_type(pages[page_num])
    return _safe_send_path(pages[page_num], [COMIC_CACHE], mimetype=mt or "image/jpeg")


@app.route("/api/book/<int:book_id>/read/cache", methods=["DELETE"])
def api_book_clear_reader_cache(book_id):
    cache_dir = os.path.join(COMIC_CACHE, str(book_id))
    if os.path.isdir(cache_dir):
        import shutil
        shutil.rmtree(cache_dir, ignore_errors=True)
    return jsonify({"status": "cleared"})


# â”€â”€ Reading List (P3.1) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.route("/api/reading-list")
def api_reading_list():
    status = request.args.get("status")
    conn = get_connection(DB_PATH)
    try:
        items = get_reading_list(conn, status=status)
        return jsonify(items)
    finally:
        conn.close()


@app.route("/api/reading-list/<int:book_id>", methods=["POST", "DELETE"])
def api_reading_list_item(book_id):
    conn = get_connection(DB_PATH)
    try:
        if request.method == "DELETE":
            remove_from_reading_list(conn, book_id)
            conn.commit()
            return jsonify({"status": "removed"})
        data = request.json or {}
        rl_status = data.get("status", "to_read")
        add_to_reading_list(conn, book_id, status=rl_status)
        conn.commit()
        return jsonify({"status": "added", "rl_status": rl_status})
    finally:
        conn.close()


@app.route("/api/book/<int:book_id>/reader-state", methods=["GET", "POST"])
def api_reader_state(book_id):
    conn = get_connection(DB_PATH)
    try:
        if request.method == "POST":
            data = request.json or {}
            location = data.get("location", "")
            progress_pct = data.get("progress_pct", 0)
            save_reader_state(conn, book_id, location, progress_pct)
            conn.commit()
            return jsonify({"status": "saved"})
        state = get_reader_state(conn, book_id)
        return jsonify(dict(state) if state else {})
    finally:
        conn.close()


@app.route("/api/book/<int:book_id>/annotations", methods=["GET", "POST"])
def api_annotations(book_id):
    conn = get_connection(DB_PATH)
    try:
        if request.method == "POST":
            data = request.json or {}
            ann_id = add_annotation(conn, book_id,
                                    ann_type=data.get("type", "highlight"),
                                    cfi_range=data.get("cfi_range", ""),
                                    text=data.get("text", ""),
                                    note=data.get("note"),
                                    color=data.get("color", "#fef08a"),
                                    page=data.get("page"),
                                    bbox=data.get("bbox"))
            conn.commit()
            return jsonify({"id": ann_id, "status": "created"})
        anns = get_annotations(conn, book_id)
        return jsonify(anns)
    finally:
        conn.close()


@app.route("/api/book/<int:book_id>/annotations/<int:ann_id>", methods=["DELETE"])
def api_annotation_delete(book_id, ann_id):
    conn = get_connection(DB_PATH)
    try:
        delete_annotation(conn, ann_id)
        conn.commit()
        return jsonify({"status": "deleted"})
    finally:
        conn.close()


@app.route("/api/book/<int:book_id>/annotations/export")
def api_annotations_export(book_id):
    conn = get_connection(DB_PATH)
    try:
        md = export_annotations_markdown(conn, book_id)
        return Response(md, mimetype="text/markdown",
                        headers={"Content-Disposition": f"attachment; filename=highlights_{book_id}.md"})
    finally:
        conn.close()


@app.route("/api/book/<int:book_id>/drawing/<int:page>", methods=["GET", "POST", "DELETE"])
def api_book_drawing(book_id, page):
    conn = get_connection(DB_PATH)
    try:
        if request.method == "POST":
            data = request.json or {}
            save_drawing(conn, book_id, page, data.get("data") or "")
            conn.commit()
            return jsonify({"status": "ok"})
        if request.method == "DELETE":
            delete_drawing(conn, book_id, page)
            conn.commit()
            return jsonify({"status": "ok"})
        return jsonify({"data": get_drawing(conn, book_id, page) or ""})
    finally:
        conn.close()


@app.route("/api/book/<int:book_id>/bookmarks", methods=["GET", "POST"])
def api_bookmarks(book_id):
    conn = get_connection(DB_PATH)
    try:
        if request.method == "POST":
            data = request.json or {}
            bm_id = add_bookmark(conn, book_id,
                                 label=data.get("label"),
                                 cfi_loc=data.get("cfi_loc"),
                                 page_num=data.get("page_num"),
                                 progress_pct=data.get("progress_pct"))
            conn.commit()
            return jsonify({"id": bm_id, "status": "ok"})
        return jsonify(get_bookmarks(conn, book_id))
    finally:
        conn.close()


@app.route("/api/book/<int:book_id>/bookmarks/<int:bm_id>", methods=["DELETE"])
def api_bookmark_delete(book_id, bm_id):
    conn = get_connection(DB_PATH)
    try:
        delete_bookmark(conn, bm_id)
        conn.commit()
        return jsonify({"status": "ok"})
    finally:
        conn.close()


@app.route("/api/book/<int:book_id>/enrich", methods=["POST"])
def api_book_enrich(book_id):
    """Re-run enrichment (Open Library + Google Books) for a single book."""
    conn = get_connection(DB_PATH)
    try:
        book_row = get_book_by_id(conn, book_id)
        if not book_row:
            return jsonify({"error": "not found"}), 404
        book = dict(book_row)
        isbn = book.get("isbn")
        title = book.get("title") or book.get("filename", "")
        author = book.get("authors")
        result = enrich_book(isbn=isbn, title=title, author=author)
        if not result:
            return jsonify({"error": "enrichment returned no data"}), 404
        from datetime import datetime
        from db import upsert_metadata
        cover_path = None
        if result.get("cover_url"):
            os.makedirs(config.COVER_DIR, exist_ok=True)
            cover_path = _download_cover(result["cover_url"], config.COVER_DIR)
        upsert_metadata(conn, book_id,
                        title=result.get("title"),
                        authors=result.get("authors"),
                        publisher=result.get("publisher"),
                        year=result.get("year"),
                        isbn=result.get("isbn"),
                        pages=result.get("pages"),
                        language=result.get("language"),
                        description=result.get("description"),
                        cover_path=cover_path,
                        enrich_source=result.get("source", "enrich"),
                        enriched_at=datetime.utcnow().isoformat())
        conn.commit()
        updated = get_book_by_id(conn, book_id)
        return jsonify({"status": "ok", "book": dict(updated), "enriched": result})
    finally:
        conn.close()


@app.route("/api/book/<int:book_id>/merge", methods=["POST"])
def api_book_merge(book_id):
    """Merge another book entry into this one (mark target as merged)."""
    data = request.json or {}
    target_id = data.get("target_id")
    if not target_id:
        return jsonify({"error": "target_id required"}), 400
    conn = get_connection(DB_PATH)
    try:
        source = get_book_by_id(conn, book_id)
        target = get_book_by_id(conn, target_id)
        if not source or not target:
            return jsonify({"error": "book not found"}), 404
        conn.execute("UPDATE files SET stage=?, stage_error=?, master_id=? WHERE id=?",
                     ("merged", f"Merged into {book_id}", book_id, target_id))
        conn.execute("UPDATE files SET is_master=1 WHERE id=?", (book_id,))
        conn.commit()
        return jsonify({"status": "ok", "merged_id": target_id, "into_id": book_id})
    finally:
        conn.close()


@app.route("/api/book/<int:book_id>/delete", methods=["POST"])
def api_book_delete(book_id):
    """Delete a book: remove physical file(s) and DB entries."""
    conn = get_connection(DB_PATH)
    try:
        row = get_book_by_id(conn, book_id)
        if not row:
            return jsonify({"error": "not found"}), 404
        book = dict(row)
        removed = []
        if book.get("source_path") and os.path.isfile(book["source_path"]):
            try:
                os.remove(book["source_path"])
                removed.append("source")
            except OSError:
                pass
        if book.get("cover_path") and os.path.isfile(book["cover_path"]):
            try:
                os.remove(book["cover_path"])
                removed.append("cover")
            except OSError:
                pass
        comic_dir = os.path.join(config.BASE_DIR, "data", "cache", "comic", str(book_id))
        if os.path.isdir(comic_dir):
            import shutil
            shutil.rmtree(comic_dir, ignore_errors=True)
            removed.append("comic_cache")
        bulk_delete_files(conn, [book_id])
        conn.commit()
        return jsonify({"status": "ok", "deleted": book_id, "files_removed": removed})
    finally:
        conn.close()


@app.route("/api/bulk/delete", methods=["POST"])
def api_bulk_delete():
    """Delete multiple books by ID."""
    data = request.json or {}
    book_ids = data.get("book_ids", [])
    if not book_ids:
        return jsonify({"error": "book_ids required"}), 400
    conn = get_connection(DB_PATH)
    try:
        import shutil
        placeholders = ",".join("?" * len(book_ids))
        rows = conn.execute(f"""
            SELECT f.id, f.source_path, m.cover_path FROM files f
            LEFT JOIN metadata m ON m.file_id = f.id
            WHERE f.id IN ({placeholders})
        """, book_ids).fetchall()
        for row in rows:
            if row["source_path"] and os.path.isfile(row["source_path"]):
                try: os.remove(row["source_path"])
                except OSError: pass
            if row["cover_path"] and os.path.isfile(row["cover_path"]):
                try: os.remove(row["cover_path"])
                except OSError: pass
            comic_dir = os.path.join(config.BASE_DIR, "data", "cache", "comic", str(row["id"]))
            if os.path.isdir(comic_dir):
                shutil.rmtree(comic_dir, ignore_errors=True)
        bulk_delete_files(conn, book_ids)
        conn.commit()
        return jsonify({"status": "ok", "deleted": len(book_ids)})
    finally:
        conn.close()


# â”€â”€ FTS5 Search â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.route("/api/search")
def api_search():
    q = request.args.get("q", "").strip()
    stage = request.args.get("stage") or None
    udc = request.args.get("udc") or None
    tag = request.args.get("tag") or None
    fmt = request.args.get("format") or None
    year_min = request.args.get("year_min", type=int)
    year_max = request.args.get("year_max", type=int)
    min_size = request.args.get("min_size", type=float)
    max_size = request.args.get("max_size", type=float)
    if min_size is not None:
        min_size = int(min_size)
    if max_size is not None:
        max_size = int(max_size)
    source = request.args.get("source") or None
    masters_only = request.args.get("masters_only", type=int) == 1
    untagged = request.args.get("untagged", type=int) == 1
    duplicate_only = request.args.get("duplicate_only", type=int) == 1
    archive_only = request.args.get("archive_only", type=int) == 1
    limit = request.args.get("limit", default=100, type=int)
    offset = request.args.get("offset", default=0, type=int)
    sort = request.args.get("sort") or None
    order = request.args.get("order") or None

    conn = get_connection(DB_PATH)
    try:
        results, total = search_books(conn, q, stage=stage, udc=udc, tag=tag,
                                       fmt=fmt, year_min=year_min, year_max=year_max,
                                       min_size=min_size, max_size=max_size,
                                       masters_only=masters_only, source=source, limit=limit, offset=offset,
                                       sort=sort, order=order,
                                       untagged=untagged, duplicate_only=duplicate_only,
                                       archive_only=archive_only,
                                       archive_dir=getattr(config, "ARCHIVE_DIR", None))
        return jsonify({"results": results, "total": total, "query": q})
    finally:
        conn.close()


@app.route("/api/rebuild-fts", methods=["POST"])
def api_rebuild_fts():
    conn = get_connection(DB_PATH)
    try:
        count = rebuild_fts(conn)
        conn.commit()
        return jsonify({"status": "ok", "indexed": count})
    finally:
        conn.close()


# â”€â”€ Bulk operations â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.route("/api/bulk/tags/add", methods=["POST"])
def api_bulk_tag_add():
    data = request.json or {}
    book_ids = data.get("book_ids", [])
    tag = (data.get("tag") or "").strip()
    if not book_ids or not tag:
        return jsonify({"error": "book_ids and tag required"}), 400
    conn = get_connection(DB_PATH)
    try:
        from db import add_custom_tags_bulk
        added = add_custom_tags_bulk(conn, book_ids, tag)
        conn.commit()
        return jsonify({"status": "ok", "added": added, "tag": tag})
    finally:
        conn.close()


@app.route("/api/bulk/tags/remove", methods=["POST"])
def api_bulk_tag_remove():
    data = request.json or {}
    book_ids = data.get("book_ids", [])
    tag = (data.get("tag") or "").strip()
    if not book_ids or not tag:
        return jsonify({"error": "book_ids and tag required"}), 400
    conn = get_connection(DB_PATH)
    try:
        from db import remove_custom_tags_bulk
        remove_custom_tags_bulk(conn, book_ids, tag)
        conn.commit()
        return jsonify({"status": "ok", "removed": len(book_ids), "tag": tag})
    finally:
        conn.close()


@app.route("/api/bulk/classify", methods=["POST"])
def api_bulk_classify():
    data = request.json or {}
    book_ids = data.get("book_ids", [])
    udc_code = (data.get("udc_code") or "").strip()
    if not book_ids or not udc_code:
        return jsonify({"error": "book_ids and udc_code required"}), 400
    conn = get_connection(DB_PATH)
    try:
        from db import upsert_metadata, set_tags
        from classifier import UDC_LABELS
        udc_label = UDC_LABELS.get(udc_code, "")
        for bid in book_ids:
            upsert_metadata(conn, bid, udc_code=udc_code, udc_label=udc_label)
            set_tags(conn, bid, [{"tag": udc_code, "tag_label": udc_label}], tag_type="udc")
        conn.commit()
        return jsonify({"status": "ok", "reclassified": len(book_ids), "udc_code": udc_code})
    finally:
        conn.close()


# â”€â”€ Excel export â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

STAGE_LABELS = {
    "arrived": "1_Arrived", "extracted": "2_Extracted", "cleaned": "3_Cleaned",
    "cataloged": "4_Cataloged", "survivor": "5_Survivor", "skipped": "6_Skipped",
    "copied": "7_Copied",
}

EXPORT_COLUMNS = ["ID", "UUID", "Filename", "Title", "Author", "Year", "Format",
                  "UDC", "UDC_Label", "Stage", "Stage_Error", "Is_Master",
                  "Size_MB", "ISBN", "Publisher", "Language", "Pages", "Hash"]

@app.route("/api/export/excel")
def api_export_excel():
    conn = get_connection(DB_PATH)
    try:
        stages = ["arrived", "extracted", "cleaned", "cataloged", "survivor", "skipped", "copied"]
        writer = pd.ExcelWriter(io.BytesIO(), engine="openpyxl")

        for stage in stages:
            rows = conn.execute("""
                SELECT f.id, f.uuid, f.filename, f.file_size, f.file_hash, f.format,
                       f.stage, f.stage_error, f.is_master,
                       m.title, m.authors, m.year, m.udc_code, m.udc_label,
                       m.isbn, m.publisher, m.language, m.pages
                FROM files f
                LEFT JOIN metadata m ON m.file_id = f.id
                WHERE f.stage = ?
                ORDER BY f.id
            """, (stage,)).fetchall()

            data = []
            for r in rows:
                data.append({
                    "ID": r["id"],
                    "UUID": r["uuid"] or "",
                    "Filename": r["filename"],
                    "Title": r["title"] or "",
                    "Author": r["authors"] or "",
                    "Year": r["year"] or "",
                    "Format": r["format"] or "",
                    "UDC": r["udc_code"] or "",
                    "UDC_Label": r["udc_label"] or "",
                    "Stage": r["stage"],
                    "Stage_Error": r["stage_error"] or "",
                    "Is_Master": {1: "Yes", 0: "No", None: ""}.get(r["is_master"], ""),
                    "Size_MB": round((r["file_size"] or 0) / (1024 * 1024), 2),
                    "ISBN": r["isbn"] or "",
                    "Publisher": r["publisher"] or "",
                    "Language": r["language"] or "",
                    "Pages": r["pages"] or "",
                    "Hash": (r["file_hash"] or "")[:16],
                })

            df = pd.DataFrame(data, columns=EXPORT_COLUMNS)
            sheet_name = STAGE_LABELS.get(stage, stage)
            df.to_excel(writer, sheet_name=sheet_name, index=False)

        # Summary sheet
        summary = get_phase_counts(conn)
        summary_df = pd.DataFrame([
            {"Stage": stage.title(), "Count": count}
            for stage, count in sorted(summary.items())
        ])
        summary_df.to_excel(writer, sheet_name="0_Summary", index=False)

        writer.close()
        output = writer.book
        buf = io.BytesIO()
        output.save(buf)
        buf.seek(0)
        return send_file(
            buf,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name="book_catalog.xlsx"
        )
    finally:
        conn.close()


# â”€â”€ SSE events â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€



# SSE events (disabled: using fetchStatus polling instead)


# P6.1 - Portable Config export/import

def _migrate_cover_paths():
    """P8.1: unify cover storage onto COVER_DIR.

    - Rows already under COVER_DIR: leave as-is.
    - Rows pointing at a file that exists elsewhere: copy the image into COVER_DIR
      (preserving the basename, idempotent) and repoint cover_path.
    - Rows pointing at a missing file: repoint to COVER_DIR/<file_id>.jpg if that
      file exists there, else leave untouched for later enrichment.
    """
    os.makedirs(config.COVER_DIR, exist_ok=True)
    import shutil
    try:
        conn = get_connection(config.DB_PATH)
        try:
            rows = conn.execute(
                "SELECT file_id, cover_path FROM metadata WHERE cover_path IS NOT NULL AND cover_path != ''"
            ).fetchall()
            moved = 0
            copied = 0
            cover_abs = os.path.normpath(config.COVER_DIR)
            for r in rows:
                cp = r["cover_path"]
                try:
                    in_cover_dir = os.path.normpath(cp).startswith(cover_abs + os.sep)
                except Exception:
                    in_cover_dir = False
                if in_cover_dir and os.path.isfile(cp):
                    continue
                if os.path.isfile(cp):
                    dst = os.path.join(config.COVER_DIR, os.path.basename(cp))
                    if not os.path.isfile(dst):
                        try:
                            shutil.copy2(cp, dst)
                        except Exception:
                            continue
                    conn.execute("UPDATE metadata SET cover_path=? WHERE file_id=?", (dst, r["file_id"]))
                    copied += 1
                else:
                    candidate = os.path.join(config.COVER_DIR, f"{r['file_id']}.jpg")
                    if os.path.isfile(candidate):
                        conn.execute("UPDATE metadata SET cover_path=? WHERE file_id=?", (candidate, r["file_id"]))
                        moved += 1
            if copied or moved:
                conn.commit()
                logger.info("P8.1 cover migration: copied %d, repointed %d rows to %s",
                            copied, moved, config.COVER_DIR)
        finally:
            conn.close()
    except Exception as e:
        logger.warning("P8.1 cover migration skipped: %s", e)

def _handle_export_pi(zip_path):
    import zipfile, json
    data_dir = config.DATA_DIR
    if not os.path.isdir(data_dir):
        print(f"Error: data_dir not found: {data_dir}")
        sys.exit(1)
    print(f"Exporting from {data_dir} to {zip_path} ...")
    export_items = []
    export_items.append(("catalog.db", os.path.join(data_dir, "catalog.db")))
    covers_dir = config.COVER_DIR
    if os.path.isdir(covers_dir):
        for fname in os.listdir(covers_dir):
            if fname.endswith(".jpg"):
                export_items.append((f"covers/{fname}", os.path.join(covers_dir, fname)))
    for fname in ("pipeline_state.json", "enrich_cache.json"):
        fp = os.path.join(data_dir, fname)
        if os.path.isfile(fp):
            export_items.append((fname, fp))
    manifest = {
        "exported_at": __import__("datetime").datetime.utcnow().isoformat(),
        "original_data_dir": data_dir,
        "original_db_path": config.DB_PATH,
        "overrides": {}
    }
    conn = get_connection(config.DB_PATH)
    try:
        for r in conn.execute("SELECT name, value FROM config_overrides").fetchall():
            manifest["overrides"][r["name"]] = r["value"]
    finally:
        conn.close()
    os.makedirs(os.path.dirname(os.path.abspath(zip_path)), exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for arcname, src_path in export_items:
            if os.path.isfile(src_path):
                zf.write(src_path, arcname)
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
    print(f"Exported {len(export_items)} items to {zip_path}")


def _handle_import_pi(zip_path):
    import zipfile, json
    data_dir = config.DATA_DIR
    os.makedirs(data_dir, exist_ok=True)
    print(f"Importing from {zip_path} into {data_dir} ...")
    with zipfile.ZipFile(zip_path, "r") as zf:
        manifest = json.loads(zf.read("manifest.json"))
        print(f"  Exported from: {manifest.get('original_data_dir')}")
        print(f"  Export time: {manifest.get('exported_at')}")
        for name in zf.namelist():
            if name == "manifest.json":
                continue
            zf.extract(name, data_dir)
            print(f"  Extracted {name}")
        overrides = manifest.get("overrides", {})
        if overrides:
            conn = get_connection(config.DB_PATH)
            try:
                from db import set_config_override
                for k, v in overrides.items():
                    set_config_override(conn, k, v)
                conn.commit()
                print(f"  Applied {len(overrides)} config overrides")
            finally:
                conn.close()
    print("Import complete.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Book Organiser â€” catalog, deduplicate, and organise ebooks")
    parser.add_argument("--source", "-s", default="",
                        help="Source path(s) to scan; separate multiple with semicolon")
    parser.add_argument("--inbox", "-i", default="",
                        help="Inbox directory for ad-hoc files")
    parser.add_argument("--port", "-p", type=int, default=5000,
                        help="Web UI port (default: 5000)")
    parser.add_argument("--phase", choices=["metadata", "dedup", "copy", "all", "recon", "enrich"],
                        help="Run a specific phase headless and exit")
    parser.add_argument("--db", default="",
                        help="Path to SQLite database")
    parser.add_argument("--watch", "-w", action="store_true",
                        help="Watch inbox directory and auto-trigger pipeline on new files")
    parser.add_argument("--run", choices=["metadata", "dedup", "copy", "all"],
                        help="Pipeline phase to run (used with --daemon)")
    parser.add_argument("--daemon", "-d", action="store_true",
                        help="Run as headless daemon (no web UI). Use --run or --watch with --daemon")
    parser.add_argument("--export-pi", metavar="ZIP_PATH", default="",
                        help="Export data dir as portable zip for Raspberry Pi transfer")
    parser.add_argument("--import-pi", metavar="ZIP_PATH", default="",
                        help="Import portable zip from Raspberry Pi into current data dir")
    parser.add_argument("--enrich-limit", type=int, default=500,
                        help="Max books to refresh per enrich phase run (default: 500)")

    args = parser.parse_args()

    # Only override config with CLI args if explicitly provided (non-empty)
    if args.source:
        sources = [s.strip() for s in args.source.split(";") if s.strip()]
        config.SOURCE_DIR = sources[0]
        config.SOURCE_DIRS = sources
    if args.inbox:
        config.INBOX_DIR = args.inbox
    if args.db:
        config.DB_PATH = args.db

    # Apply config overrides from DB (takes precedence over config.py defaults)
    init_db(config.DB_PATH)
    _conn = get_connection(config.DB_PATH)
    load_config_overrides(_conn)
    _conn.close()
    _migrate_cover_paths()

    # Derive WATCH_DIR if not set
    if not config.WATCH_DIR:
        config.WATCH_DIR = config.INBOX_DIR

    # P6.1 — Portable export/import
    if args.export_pi:
        _handle_export_pi(args.export_pi)
        sys.exit(0)
    if args.import_pi:
        _handle_import_pi(args.import_pi)
        sys.exit(0)

    if args.phase:
        init_db(config.DB_PATH)
        if config.FLAT_DIR: os.makedirs(config.FLAT_DIR, exist_ok=True)
        if args.phase == "all":
            run_all_phases(source=args.source)
        elif args.phase == "metadata":
            run_phase_metadata(source=args.source)
        elif args.phase == "dedup":
            run_phase_dedup()
        elif args.phase == "copy":
            run_phase_copy()
        elif args.phase == "recon":
            result = run_recon()
            print(json.dumps(result, indent=2))
        elif args.phase == "enrich":
            run_phase_enrich(limit=args.enrich_limit)
    elif args.daemon:
        # Delegate to daemon.py
        from daemon import cmd_run, cmd_watch, cmd_status
        init_db(config.DB_PATH)
        if config.FLAT_DIR: os.makedirs(config.FLAT_DIR, exist_ok=True)
        if args.watch:
            cmd_watch(args)
        elif args.run:
            cmd_run(args)
        else:
            cmd_status()
    else:
        init_db(config.DB_PATH)
        if config.FLAT_DIR: os.makedirs(config.FLAT_DIR, exist_ok=True)
        if args.watch:
            from watcher import start_watcher
            watch_dir = getattr(config, "WATCH_DIR", config.INBOX_DIR)
            recursive = getattr(config, "WATCH_RECURSIVE", True)
            observer = start_watcher(watch_dir, recursive=recursive)
            try:
                app.run(host="0.0.0.0", port=args.port, debug=False, threaded=True)
            finally:
                observer.stop()
                observer.join()
        else:
            app.run(host="0.0.0.0", port=args.port, debug=False, threaded=True)
