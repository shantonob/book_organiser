"""BL-006: backfill series/series_num/volume/issue from filenames.

Idempotent; only fills NULL/empty fields. Run inside the container:

    sudo docker exec book-organiser python tools/backfill_series.py --db /data/catalog.db
"""
import argparse
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from enrich_filename import enrich_from_filename  # noqa: E402

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(os.getcwd(), "data", "catalog.db"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""
            SELECT f.id, f.filename, f.format, f.stage, m.series, m.series_num, m.volume, m.issue
            FROM files f LEFT JOIN metadata m ON m.file_id = f.id
            WHERE f.stage IN ('cataloged','copied','survivor')
              AND (m.series IS NULL OR m.series = ''
                OR m.series_num IS NULL OR m.volume IS NULL OR m.issue IS NULL)
        """).fetchall()

        candidates = 0
        updates = 0
        for r in rows:
            if _UUID_RE.match(os.path.splitext(r["filename"])[0]):
                continue  # processed/internal auto-renamed files — no real series
            e = enrich_from_filename(r["filename"])
            series = e.get("series") or r["series"]
            num = e.get("series_num") or r["series_num"]
            vol = e.get("volume") or r["volume"]
            iss = e.get("issue") or r["issue"]
            if not (series or num or vol or iss):
                continue
            if not series:
                continue  # a lone number without a series name is not meaningful
            if (series == r["series"] and num == r["series_num"]
                    and vol == r["volume"] and iss == r["issue"]):
                continue
            s_low = (series or "").lower()
            if len(series or "") > 60 or "(z-" in s_low or ".sk," in s_low or "1lib" in s_low:
                continue  # spammy download-site names, not real series
            tail = "".join(part for part in
                           ((series and series) or None,
                            (num and f" #{num}") or None,
                            (vol and f" v{vol}") or None,
                            (iss and f" i{iss}") or None) if part)
            candidates += 1
            if args.dry_run:
                print(f"[{r['id']}] {r['filename']!r} -> {tail}")
                continue
            conn.execute(
                "UPDATE metadata SET series=?, series_num=?, volume=?, issue=? WHERE file_id=?",
                (series, num, vol, iss, r["id"]),
            )
            updates += 1

        if not args.dry_run:
            conn.commit()
        print(f"{'would update' if args.dry_run else 'updated'} {candidates} rows "
              f"({updates} committed)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()