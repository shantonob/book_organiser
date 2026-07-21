"""Tag each book with the name of its parent source folder.

Usage:
    python tools/folder_tags.py [--db DB_PATH] [--dry-run]

Example:
    python tools/folder_tags.py --dry-run          # preview only
    python tools/folder_tags.py                    # apply tags
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
from db import get_connection, add_custom_tag


def get_parent_folder(source_path):
    """Extract the immediate parent folder name from a file path."""
    parent = os.path.dirname(source_path)
    if not parent:
        return None
    return os.path.basename(parent)


def main():
    parser = argparse.ArgumentParser(description="Tag books with their source folder name")
    parser.add_argument("--db", default=config.DB_PATH, help="Path to the SQLite database")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, don't modify DB")
    args = parser.parse_args()

    if not os.path.isfile(args.db):
        print(f"Database not found: {args.db}")
        sys.exit(1)

    conn = get_connection(args.db)
    rows = conn.execute(
        "SELECT id, source_path FROM files ORDER BY id"
    ).fetchall()

    tagged = 0
    skipped_already = 0
    skipped_no_parent = 0
    folder_counts = {}

    for row in rows:
        folder = get_parent_folder(row["source_path"])
        if not folder:
            skipped_no_parent += 1
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
    print(f"  Total files:       {len(rows)}")
    print(f"  Tagged:            {tagged}")
    print(f"  Skipped (already): {skipped_already}")
    print(f"  Skipped (no parent): {skipped_no_parent}")

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
