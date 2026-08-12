#!/usr/bin/env python3
"""One-time cleanup of /books/processed (flatten + archive + orphans).

Plan:
  - Flatten masters (is_master=1) into a single flat level under
    /books/processed/ (or /books/processed/archive/ for masters currently
    under an archive subtree).
  - Move every skipped duplicate (is_master=0, stage='skipped') into the flat
    /books/processed/archive/ directory, preserving ALL copies (name suffixes
    added on collision).
  - Move orphaned files (on disk, not in DB) to /books/to be sorted, EXCEPT
    orphans that are byte-identical (sha256) to a kept master -> deleted.
  - Remove now-empty leftover folders under /books/processed and its archive.
  - Update DB source_path for every moved row.

Modes:
  --dry-run   (default) compute + write report, change nothing.
  --execute   back up DB, perform moves/deletes/DB updates.

Usage:
  python tools/cleanup_processed.py --dry-run
  python tools/cleanup_processed.py --execute
"""
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime

DB_DEFAULT = os.path.join("data", "catalog.db")
BOOKS_DEFAULT = "//raspberrypi/media_ssd/books"
TO_SORTED = "to be sorted"
EXT = {".epub", ".pdf", ".mobi", ".azw3", ".djvu", ".cbr", ".cbz", ".fb2"}


def sha256_file(path, chunk=1024 * 1024):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def local_path(books_root, server_path):
    """'/books/x/y.epub' -> '<books_root>/x/y.epub' (OS-native separators)."""
    rel = server_path[len("/books/"):].replace("/", os.sep)
    return os.path.join(books_root, rel)


def server_path(books_root, local):
    """Absolute OS path under books_root -> '/books/...'."""
    rel = os.path.relpath(local, books_root).replace(os.sep, "/")
    return "/books/" + rel


def unique_name(claimed, name):
    """Return a name not in `claimed` (case-insensitive) by appending ' (n)'
    before the extension. `claimed` stores lowercased basenames."""
    low = name.lower()
    if low not in claimed:
        claimed.add(low)
        return name
    base, dot, ext = name.rpartition(".")
    if not dot:
        base, ext = name, ""
    i = 2
    while True:
        cand = f"{base} ({i}){dot}{ext}"
        if cand.lower() not in claimed:
            claimed.add(cand.lower())
            return cand
        i += 1


def scan_files_and_dirs(walk_root, books_root):
    """Return (ebook_files:set[server_path], all_dirs:set[server_path])."""
    files, dirs = set(), set()
    if not os.path.isdir(walk_root):
        return files, dirs
    for base, subdirs, names in os.walk(walk_root):
        for s in subdirs:
            dirs.add(server_path(books_root, os.path.join(base, s)))
        for n in names:
            if os.path.splitext(n)[1].lower() in EXT:
                files.add(server_path(books_root, os.path.join(base, n)))
    return files, dirs


def load_rows(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(
        "SELECT id, source_path, filename, format, stage, is_master, file_hash, master_id "
        "FROM files ORDER BY id"
    )]
    conn.close()
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB_DEFAULT)
    ap.add_argument("--books-root", default=BOOKS_DEFAULT)
    ap.add_argument("--report", default="cleanup_report.json")
    ap.add_argument("--execute", action="store_true", help="Actually perform the cleanup")
    args = ap.parse_args()

    books_root = args.books_root.rstrip("/\\")
    to_sorted = os.path.join(books_root, TO_SORTED)
    proc_root = os.path.join(books_root, "processed")
    arch_root = os.path.join(books_root, "processed", "archive")

    if not os.path.isdir(books_root):
        sys.exit(f"books root not found: {books_root}")
    if not os.path.isfile(args.db):
        sys.exit(f"DB not found: {args.db}")

    rows = load_rows(args.db)
    disk_files, disk_dirs = scan_files_and_dirs(proc_root, books_root)
    print(f"DB rows: {len(rows)}  |  disk ebook files under processed: {len(disk_files)}")

    # ---- classify rows ----
    by_id = {r["id"]: r for r in rows}
    db_paths = set(r["source_path"] for r in rows)
    orphans = sorted(disk_files - db_paths)

    active = [r for r in rows if r["source_path"] and r["source_path"].startswith("/books/")]
    missing = [r for r in rows if r["source_path"] and not os.path.isfile(local_path(books_root, r["source_path"]))]
    missing_ids = {r["id"] for r in missing}
    quarantined_ids = {r["id"] for r in rows if r["stage"] == "quarantined"}

    master_hashes = {r["file_hash"] for r in rows if r["is_master"] == 1 and r["file_hash"]}

    # ---- build plan ----
    plan = {"moves": [], "deletes": [], "rmdirs": [], "db_updates": [], "notes": []}

    # 1) Orphans: delete if byte-identical to a master, else move to 'to be sorted'
    orphan_deleted, orphan_moved = 0, 0
    sorted_claimed = set(os.path.basename(r["source_path"]).lower() for r in rows
                         if r["source_path"] and r["source_path"].startswith(f"/books/{TO_SORTED}/"))
    for i, sp in enumerate(orphans, 1):
        lp = local_path(books_root, sp)
        if i % 200 == 0:
            print(f"  hashing orphans {i}/{len(orphans)}")
        try:
            h = sha256_file(lp)
        except OSError as e:
            plan["notes"].append(f"orphan unreadable {sp}: {e}")
            continue
        if h in master_hashes:
            plan["deletes"].append({"path": sp, "note": "orphan identical to master"})
            orphan_deleted += 1
        else:
            to = f"/books/{TO_SORTED}/" + unique_name(sorted_claimed, os.path.basename(sp))
            plan["moves"].append({"from": sp, "to": to, "note": "orphan -> to be sorted", "row_id": None})
            orphan_moved += 1

    # 2) Already-flat files claim their names in their own namespace first.
    proc_claimed = set()
    arch_claimed = set()
    for sp in disk_files:
        rest = sp[len("/books/processed/"):]
        is_arch = rest.startswith("archive/")
        rel = rest[len("archive/"):] if is_arch else rest
        if "/" not in rel:
            (arch_claimed if is_arch else proc_claimed).add(os.path.basename(sp).lower())
    # DB rows already at their target flat path (no move) claim too.
    for r in active:
        sp = r["source_path"]
        if not sp.startswith("/books/processed/") or r["id"] in missing_ids or r["id"] in quarantined_ids:
            continue
        rest = sp[len("/books/processed/"):]
        is_arch = rest.startswith("archive/")
        rel = rest[len("archive/"):] if is_arch else rest
        if "/" in rel:
            continue  # nested -> will move
        (arch_claimed if is_arch else proc_claimed).add(os.path.basename(sp).lower())

    # 3) Assign moves for DB rows needing a target change.
    for r in active:
        if r["id"] in missing_ids or r["id"] in quarantined_ids:
            continue
        sp = r["source_path"]
        bn = os.path.basename(sp)
        if r["is_master"] == 1:
            if sp.startswith(("/books/processed/archive/", "/books/archive/")):
                target = "/books/processed/archive/"
                claimed = arch_claimed
            else:
                target = "/books/processed/"
                claimed = proc_claimed
        else:  # skipped duplicate -> flat archive
            target = "/books/processed/archive/"
            claimed = arch_claimed
        # already flat at target?
        if sp.startswith(target) and "/" not in sp[len("/books/processed/archive/") if target.endswith("archive/") else len("/books/processed/"):]:
            continue
        to = target + unique_name(claimed, bn)
        plan["moves"].append({"from": sp, "to": to, "note": f"{'master' if r['is_master']==1 else 'skipped'} -> {target}", "row_id": r["id"]})

    # 4) Empty-dir cleanup under processed (bottom-up, deepest first).
    dir_sorted = sorted(disk_dirs, key=lambda p: -p.count("/"))
    for d in dir_sorted:
        if d == "/books/processed" or d == "/books/processed/archive":
            continue
        plan["rmdirs"].append({"path": d})

    # ---- summary ----
    n_move = len(plan["moves"])
    n_del = len(plan["deletes"])
    n_rm = len(plan["rmdirs"])
    print(f"orphans: {len(orphans)}  ->  delete {orphan_deleted}, move-to-sorted {orphan_moved}")
    print(f"moves: {n_move}  deletes: {n_del}  empty dirs to remove: {n_rm}")
    print(f"rows with missing file on disk: {len(missing)}  quarantined (untouched): {len(quarantined_ids)}")

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "books_root": books_root,
        "db": os.path.abspath(args.db),
        "mode": "execute" if args.execute else "dry-run",
        "stats": {
            "rows": len(rows),
            "disk_files": len(disk_files),
            "orphans": len(orphans),
            "orphan_deleted": orphan_deleted,
            "orphan_moved": orphan_moved,
            "moves": n_move,
            "deletes": n_del,
            "empty_dirs": n_rm,
            "missing_files": len(missing),
            "quarantined": len(quarantined_ids),
        },
        "plan": plan,
    }
    with open(args.report, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"report written: {args.report}")

    if not args.execute:
        print("\nDRY-RUN — no changes made. Review the report, then run with --execute.")
        return 0

    # ---- execute ----
    backup = f"{args.db}.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(args.db, backup)
    print(f"DB backed up: {backup}")

    # SQLite over SMB is unreliable for writes. Use a local working copy for
    # the DB, do all file moves on the share, then copy the DB back.
    import tempfile
    workdir = tempfile.mkdtemp(prefix="book_cleanup_")
    work_db = os.path.join(workdir, "catalog.db")
    for suffix in ("", "-wal", "-shm"):
        src = args.db + suffix
        if os.path.isfile(src):
            shutil.copy2(src, work_db + suffix)
    print(f"using local working DB: {work_db}")

    os.makedirs(to_sorted, exist_ok=True)
    conn = sqlite3.connect(work_db, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=60000")
    now = datetime.now().isoformat(timespec="seconds")

    moved = 0
    moved_fail = 0
    resumed = 0
    for i, m in enumerate(plan["moves"], 1):
        lp = local_path(books_root, m["from"])
        lt = local_path(books_root, m["to"])
        if not os.path.isfile(lp):
            if os.path.isfile(lt) and m["row_id"]:
                # Already moved by a prior interrupted run — just sync the DB row.
                conn.execute("UPDATE files SET source_path=?, updated_at=? WHERE id=? AND source_path=?",
                             (m["to"], now, m["row_id"], m["from"]))
                conn.commit()
                resumed += 1
                continue
            plan["notes"].append(f"source missing during execute: {m['from']}")
            continue
        try:
            os.makedirs(os.path.dirname(lt), exist_ok=True)
            os.replace(lp, lt)
        except OSError as e:
            plan["notes"].append(f"move failed: {m['from']} -> {m['to']}: {e}")
            moved_fail += 1
            continue
        if m["row_id"]:
            new_sp = server_path(books_root, lt)
            conn.execute("UPDATE files SET source_path=?, updated_at=? WHERE id=? AND source_path=?",
                         (new_sp, now, m["row_id"], m["from"]))
        conn.commit()  # tiny transaction — resumable across SMB failures
        moved += 1
        if i % 1000 == 0:
            print(f"  moved {moved}/{len(plan['moves'])} (resumed {resumed})")

    deleted = 0
    del_fail = 0
    for d in plan["deletes"]:
        lp = local_path(books_root, d["path"])
        if not os.path.isfile(lp):
            continue
        try:
            os.remove(lp)
            deleted += 1
        except OSError as e:
            plan["notes"].append(f"delete failed: {d['path']}: {e}")
            del_fail += 1
        if deleted % 1000 == 0 and deleted > 0:
            print(f"  deleted {deleted}/{len(plan['deletes'])}")

    removed = 0
    for d in sorted(plan["rmdirs"], key=lambda p: -p["path"].count("/")):
        lp = local_path(books_root, d["path"])
        if os.path.isdir(lp):
            try:
                os.rmdir(lp)
                removed += 1
            except OSError:
                pass  # not empty (unexpected) — leave it
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()

    # Copy the local working DB back over the share DB (WAL checkpointed above).
    for suffix in ("", "-wal", "-shm"):
        src = work_db + suffix
        if os.path.isfile(src):
            shutil.copy2(src, args.db + suffix)

    print(f"executed: {moved} moved ({moved_fail} failed, {resumed} resumed), {deleted} deleted ({del_fail} failed), {removed} empty dirs removed")
    print(f"DB copied back to {args.db}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
