import os
import json
import threading
import time
import argparse
import io
import logging
from flask import Flask, render_template, jsonify, Response, request, send_file
import pandas as pd

import config
from config import DB_PATH, EBOOK_EXTS, EXCLUDE_EXTS
from log_utils import setup_logger

logger = setup_logger("app", also_stdout=False)

# Silence noisy loggers
for noisy in ("werkzeug", "flask"):
    log = logging.getLogger(noisy)
    log.setLevel(logging.WARNING)
    log.handlers.clear()
from db import get_connection, init_db, get_pipeline_summary, get_recent_books, get_pipeline_log, get_book_by_id
from db import get_phase_counts, get_survivors, get_tags, add_custom_tag, remove_custom_tag, search_tags
from db import get_summary, get_book_pipeline_log, rebuild_fts, search_books, get_funnel, get_daemon_status
from db import get_quarantined, resolve_quarantine, QUARANTINE_ERRORS, get_quarantine_counts_by_error, get_quarantine_formats, bulk_dismiss, bulk_keep_both, bulk_delete_files, get_quarantine_rules, set_quarantine_rule
from pipeline import state, run_pipeline, run_all_phases, run_phase_metadata, run_phase_dedup, run_phase_copy, discover_source_files, add_to_inbox

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Ensure log directory exists
os.makedirs(config.LOG_DIR, exist_ok=True)

# Route all server output to app.log
log_handler = logging.FileHandler(os.path.join(config.LOG_DIR, "app.log"), encoding="utf-8")
log_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
werkz = logging.getLogger("werkzeug")
werkz.setLevel(logging.INFO)
werkz.addHandler(log_handler)
werkz.propagate = False
flask_log = logging.getLogger("flask")
flask_log.addHandler(log_handler)
flask_log.setLevel(logging.INFO)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    conn = get_connection(DB_PATH)
    try:
        summary = get_pipeline_summary(conn)
        pcounts = get_phase_counts(conn)
        recent = [dict(r) for r in get_recent_books(conn, 20)]
        plog = [dict(r) for r in get_pipeline_log(conn, 20)]
        return jsonify({
            "pipeline": state.get_snapshot(),
            "summary": summary,
            "phase_counts": pcounts,
            "recent": recent,
            "log": plog,
        })
    finally:
        conn.close()


@app.route("/api/book/<int:book_id>")
def api_book(book_id):
    conn = get_connection(DB_PATH)
    try:
        book = get_book_by_id(conn, book_id)
        if not book:
            return jsonify({"error": "not found"}), 404
        result = dict(book)
        result["tags"] = get_tags(conn, book_id)
        return jsonify(result)
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


# ── Phase triggers ───────────────────────────────────────────

@app.route("/api/scan")
def api_scan():
    """Run Phase A (metadata) + Phase B (dedup). Copy is NOT included."""
    source = request.args.get("source") or config.SOURCE_DIR
    t = threading.Thread(target=run_pipeline, args=(source,), daemon=True)
    t.start()
    return jsonify({"status": "started", "source": source, "phases": "metadata+dedup"})

@app.route("/api/scan_all")
def api_scan_all():
    """Run all three phases: metadata + dedup + copy."""
    source = request.args.get("source") or config.SOURCE_DIR
    t = threading.Thread(target=run_all_phases, args=(source,), daemon=True)
    t.start()
    return jsonify({"status": "started", "source": source, "phases": "metadata+dedup+copy"})


@app.route("/api/scan_inbox")
def api_scan_inbox():
    inbox_path = os.path.join(os.path.dirname(__file__), "inbox")
    if not os.path.isdir(inbox_path):
        return jsonify({"status": "no_inbox"})
    files = []
    for f in os.listdir(inbox_path):
        fp = os.path.join(inbox_path, f)
        if os.path.isfile(fp):
            ext = os.path.splitext(f)[1].lower()
            if ext in EBOOK_EXTS:
                files.append(fp)
    t = threading.Thread(target=run_pipeline, args=(None, files), daemon=True)
    t.start()
    return jsonify({"status": "started", "count": len(files)})


@app.route("/api/phase/metadata")
def api_phase_metadata():
    source = request.args.get("source") or config.SOURCE_DIR
    t = threading.Thread(target=run_phase_metadata, args=(source,), daemon=True)
    t.start()
    return jsonify({"status": "started", "phase": "metadata", "source": source})


@app.route("/api/phase/dedup")
def api_phase_dedup():
    t = threading.Thread(target=run_phase_dedup, daemon=True)
    t.start()
    return jsonify({"status": "started", "phase": "dedup"})


@app.route("/api/phase/copy")
def api_phase_copy():
    t = threading.Thread(target=run_phase_copy, daemon=True)
    t.start()
    return jsonify({"status": "started", "phase": "copy"})


# ── Tag endpoints ────────────────────────────────────────────

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


# ── Summary ──────────────────────────────────────────────────

@app.route("/api/summary")
def api_summary():
    conn = get_connection(DB_PATH)
    try:
        result = get_summary(conn)
        from classifier import UDC_LABELS
        result["udc_labels"] = {k: UDC_LABELS.get(k, "") for k in result["by_udc"]}
        return jsonify(result)
    finally:
        conn.close()


@app.route("/api/udc-labels")
def api_udc_labels():
    from classifier import UDC_LABELS
    return jsonify(UDC_LABELS)


# ── Pipeline funnel ──────────────────────────────────────────

@app.route("/api/funnel")
def api_funnel():
    conn = get_connection(DB_PATH)
    try:
        return jsonify(get_funnel(conn))
    finally:
        conn.close()


# ── Per-file pipeline log ────────────────────────────────────

@app.route("/api/book/<int:book_id>/log")
def api_book_log(book_id):
    conn = get_connection(DB_PATH)
    try:
        rows = get_book_pipeline_log(conn, book_id)
        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()


# ── Cover gallery ────────────────────────────────────────────

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
            return "", 404
        return send_file(row["cover_path"], mimetype="image/jpeg")
    finally:
        conn.close()


# ── Sources list ─────────────────────────────────────────────

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


# ── Daemon IPC ───────────────────────────────────────────────

@app.route("/api/daemon")
def api_daemon_status():
    return jsonify(get_daemon_status(DB_PATH))


# ── Manual metadata update ───────────────────────────────────

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
        conn.commit()
        return jsonify({"status": "updated", "fields": list(fields.keys())})
    finally:
        conn.close()


# ── Quarantine ────────────────────────────────────────────────

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


# ── Per-book re-processing ───────────────────────────────────

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

        state.update(log_msg=f"  ▶ re-extracting book #{book_id}")

        raw_meta = extract_metadata(filepath)
        if "_error" in raw_meta:
            state.update(log_msg=f"  ✗ re-extract failed: {raw_meta['_error']}")
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
        if not raw_meta.get("title") or not raw_meta.get("authors") or not raw_meta.get("description"):
            try:
                api_enriched = enrich_book(
                    isbn=raw_meta.get("isbn"),
                    title=clean_title,
                    author=clean_authors,
                )
                api_source = api_enriched.get("_source", "openlibrary")
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

        rebuilt = rebuild_fts(conn)
        conn.commit()

        state.update(log_msg=f"  ✓ re-extracted book #{book_id} (FTS: {rebuilt} docs)")
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

        state.update(log_msg=f"  ▶ re-dedup book #{book_id}")

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
                    state.update(log_msg=f"  ✗ re-dedup: hash dup of #{r['id']}")
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
                    state.update(log_msg=f"  ✗ re-dedup: isbn dup of #{r['id']}")
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
                            state.update(log_msg=f"  ✗ re-dedup: title dup of #{r['id']}")
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
                                state.update(log_msg=f"  ✗ re-dedup: author+year+title dup of #{r['id']}")
                                return jsonify({"status": "skipped", "reason": "duplicate_by_author_year_title", "dup_id": r["id"]})

        # Passed all checks
        mark_survivor(conn, book_id)
        conn.commit()
        state.update(log_msg=f"  ✓ re-dedup: book #{book_id} confirmed survivor")
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
        state.update(log_msg=f"  ✓ re-copied book #{book_id} → {dest}")

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

        filepath = book["source_path"]
        if filepath and os.path.isfile(filepath):
            fname = clean_filename(os.path.basename(filepath))
        else:
            fname_orig = book["filename"] or f"book_{book_id}"
            dest = os.path.join(config.FLAT_DIR, clean_filename(os.path.basename(fname_orig)))
            if os.path.isfile(dest):
                filepath = dest
                fname = os.path.basename(dest)
            else:
                return jsonify({"error": "file not found on disk"}), 404

        mt, _ = mimetypes.guess_type(filepath)
        return send_file(filepath, as_attachment=True, download_name=fname, mimetype=mt or "application/octet-stream")
    finally:
        conn.close()


COMIC_CACHE = os.path.join(config.BASE_DIR, "data", "cache", "comic")

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


@app.route("/api/book/<int:book_id>/read")
def api_book_read(book_id):
    conn = get_connection(DB_PATH)
    try:
        book = get_book_by_id(conn, book_id)
        if not book:
            return jsonify({"error": "not found"}), 404

        filepath = book["source_path"]
        if not filepath or not os.path.isfile(filepath):
            return jsonify({"error": "file not found on disk"}), 404

        ext = os.path.splitext(filepath)[1].lower()
        if ext not in config.EBOOK_EXTS:
            return jsonify({"error": "unsupported format for in-browser reading"}), 400

        if ext == ".epub":
            return send_file(filepath, mimetype="application/epub+zip")
        elif ext == ".pdf":
            return send_file(filepath, mimetype="application/pdf")
        elif ext in (".cbz", ".cbr"):
            pages = _extract_comic(book_id, filepath)
            return jsonify({"format": ext, "total": len(pages), "book_id": book_id})
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
    return send_file(pages[page_num], mimetype=mt or "image/jpeg")


@app.route("/api/book/<int:book_id>/read/cache", methods=["DELETE"])
def api_book_clear_reader_cache(book_id):
    cache_dir = os.path.join(COMIC_CACHE, str(book_id))
    if os.path.isdir(cache_dir):
        import shutil
        shutil.rmtree(cache_dir, ignore_errors=True)
    return jsonify({"status": "cleared"})


# ── FTS5 Search ──────────────────────────────────────────────

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
    limit = request.args.get("limit", default=100, type=int)
    offset = request.args.get("offset", default=0, type=int)

    conn = get_connection(DB_PATH)
    try:
        results, total = search_books(conn, q, stage=stage, udc=udc, tag=tag,
                                       fmt=fmt, year_min=year_min, year_max=year_max,
                                       min_size=min_size, max_size=max_size,
                                       masters_only=masters_only, source=source, limit=limit, offset=offset)
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


# ── Bulk operations ─────────────────────────────────────────

@app.route("/api/bulk/tags/add", methods=["POST"])
def api_bulk_tag_add():
    data = request.json or {}
    book_ids = data.get("book_ids", [])
    tag = (data.get("tag") or "").strip()
    if not book_ids or not tag:
        return jsonify({"error": "book_ids and tag required"}), 400
    conn = get_connection(DB_PATH)
    try:
        from db import add_custom_tag
        for bid in book_ids:
            add_custom_tag(conn, bid, tag)
        conn.commit()
        return jsonify({"status": "ok", "added": len(book_ids), "tag": tag})
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
        from db import remove_custom_tag
        for bid in book_ids:
            remove_custom_tag(conn, bid, tag)
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


# ── Excel export ─────────────────────────────────────────────

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


# ── SSE events ───────────────────────────────────────────────

@app.route("/api/events")
def api_events():
    def generate():
        while True:
            conn = get_connection(DB_PATH)
            try:
                summary = get_pipeline_summary(conn)
                funnel = get_funnel(conn)
                data = {
                    "pipeline": state.get_snapshot(),
                    "summary": summary,
                    "funnel": funnel,
                    "recent": [dict(r) for r in get_recent_books(conn, 10)],
                }
                yield f"data: {json.dumps(data)}\n\n"
            finally:
                conn.close()
            time.sleep(2)
    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-store", "Connection": "keep-open"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Book Organiser — catalog, deduplicate, and organise ebooks")
    parser.add_argument("--source", "-s", default=r"Z:\books",
                        help="Source path(s) to scan; separate multiple with semicolon (default: Z:\\books)")
    parser.add_argument("--inbox", "-i", default=config.INBOX_DIR,
                        help="Inbox directory for ad-hoc files (default: ./inbox)")
    parser.add_argument("--port", "-p", type=int, default=5000,
                        help="Web UI port (default: 5000)")
    parser.add_argument("--phase", choices=["metadata", "dedup", "copy", "all"],
                        help="Run a specific phase headless and exit")
    parser.add_argument("--db", default=config.DB_PATH,
                        help="Path to SQLite database (default: ./data/catalog.db)")
    parser.add_argument("--watch", "-w", action="store_true",
                        help="Watch inbox directory and auto-trigger pipeline on new files")
    parser.add_argument("--run", choices=["metadata", "dedup", "copy", "all"],
                        help="Pipeline phase to run (used with --daemon)")
    parser.add_argument("--daemon", "-d", action="store_true",
                        help="Run as headless daemon (no web UI). Use --run or --watch with --daemon")

    args = parser.parse_args()

    sources = [s.strip() for s in args.source.split(";") if s.strip()]
    config.SOURCE_DIR = sources[0] if sources else r"Z:\books"
    config.SOURCE_DIRS = sources
    config.INBOX_DIR = args.inbox
    config.DB_PATH = args.db

    if args.phase:
        init_db(config.DB_PATH)
        os.makedirs(config.FLAT_DIR, exist_ok=True)
        if args.phase == "all":
            run_all_phases(source=args.source)
        elif args.phase == "metadata":
            run_phase_metadata(source=args.source)
        elif args.phase == "dedup":
            run_phase_dedup()
        elif args.phase == "copy":
            run_phase_copy()
    elif args.daemon:
        # Delegate to daemon.py
        from daemon import cmd_run, cmd_watch, cmd_status
        init_db(config.DB_PATH)
        os.makedirs(config.FLAT_DIR, exist_ok=True)
        if args.watch:
            cmd_watch(args)
        elif args.run:
            cmd_run(args)
        else:
            cmd_status()
    else:
        init_db(config.DB_PATH)
        os.makedirs(config.FLAT_DIR, exist_ok=True)
        if args.watch:
            from watcher import start_watcher
            observer = start_watcher(args.inbox)
            try:
                app.run(host="0.0.0.0", port=args.port, debug=False, threaded=True)
            finally:
                observer.stop()
                observer.join()
        else:
            app.run(host="0.0.0.0", port=args.port, debug=False, threaded=True)