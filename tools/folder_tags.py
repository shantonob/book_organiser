"""Tag each book with the top-level source folder name (e.g., "to be sorted", "braingasm").

Tags based on the first subfolder under each SOURCE_DIR.

Usage:
    python tools/folder_tags.py [--db DB_PATH] [--dry-run] [--revert]

Example:
    python tools/folder_tags.py --dry-run          # preview only
    python tools/folder_tags.py                    # apply tags
    python tools/folder_tags.py --revert           # remove all folder tags
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
from db import add_custom_tag, get_connection


def get_top_level_folder(source_path, source_dirs):
    """Given a source_path and list of source_dirs, return the first-level subfolder name.

    E.g. source_path='Z:\\books\\to be sorted\\Book.epub', source_dirs=['Z:\\books']
         -> 'to be sorted'
    """
    norm_path = os.path.normpath(source_path)
    for sdir in source_dirs:
        norm_sdir = os.path.normpath(sdir)
        rel = os.path.relpath(norm_path, norm_sdir)
        # relpath returns the filename itself if source_path is not under sdir
        if rel == norm_path or rel.startswith(".."):
            continue
        parts = rel.split(os.sep)
        if len(parts) >= 2:
            # parts[0] is the top-level subfolder
            return parts[0]
        # File is directly in source_dir (no subfolder) — no folder tag
        return None
    return None


def main():
    parser = argparse.ArgumentParser(description="Tag books with top-level source folder name")
    parser.add_argument("--db", default=config.DB_PATH, help="Path to the SQLite database")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, don't modify DB")
    parser.add_argument("--revert", action="store_true", help="Remove all custom folder tags")
    args = parser.parse_args()

    if not os.path.isfile(args.db):
        print(f"Database not found: {args.db}")
        sys.exit(1)

    conn = get_connection(args.db)

    if args.revert:
        rows = conn.execute("DELETE FROM tags WHERE tag_type = 'custom'").fetchall()
        conn.commit()
        print("All custom tags removed.")
        conn.close()
        return

    source_dirs = config.SOURCE_DIRS if hasattr(config, 'SOURCE_DIRS') and config.SOURCE_DIRS else [config.SOURCE_DIR]
    rows = conn.execute(
        "SELECT id, source_path FROM files ORDER BY id"
    ).fetchall()

    tagged = 0
    skipped_already = 0
    skipped_no_folder = 0
    folder_counts = {}

    for row in rows:
        folder = get_top_level_folder(row["source_path"], source_dirs)
        if not folder:
            skipped_no_folder += 1
            continue

        # Check if already tagged with this folder name
        existing = conn.execute(
            "SELECT id FROM tags WHERE file_id=? AND tag=? AND tag_type='custom'",
            (row["id"], folder)
        ).fetchone()
        if existing:
            skipped_already += 1
            continue

        if not args.dry_run:
            add_custom_tag(conn, row["id"], folder)

        tagged += 1
        folder_counts[folder] = folder_counts.get(folder, 0) + 1

    conn.commit()
    conn.close()

    # Report
    print(f"Database: {args.db}")
    print(f"  Source dirs:       {', '.join(source_dirs)}")
    print(f"  Total files:       {len(rows)}")
    print(f"  Tagged:            {tagged}")
    print(f"  Skipped (already): {skipped_already}")
    print(f"  Skipped (no folder): {skipped_no_folder}")

    if folder_counts and tagged > 0:
        print(f"\n  Tags added by folder ({len(folder_counts)} unique):")
        for folder, count in sorted(folder_counts.items(), key=lambda x: -x[1]):
            print(f"    {folder}: {count}")

    if args.dry_run:
        print("\n  [DRY RUN] No changes were made. Run without --dry-run to apply.")
    else:
        print(f"\n  {tagged} tag{'s' if tagged != 1 else ''} applied.")


if __name__ == "__main__":
    main()
