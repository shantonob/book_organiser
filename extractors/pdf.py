import os
import re


def extract_pdf(filepath):
    meta = {}
    filename = os.path.splitext(os.path.basename(filepath))[0]
    meta["title"] = filename

    try:
        with open(filepath, "rb") as f:
            content = f.read(4096 * 100)
    except Exception:
        return meta

    text = content.decode("latin-1", errors="replace")

    info_patterns = {
        "title": r"/Title\s*\(([^)]*)\)",
        "authors": r"/Author\s*\(([^)]*)\)",
        "subject": r"/Subject\s*\(([^)]*)\)",
    }

    for key, pat in info_patterns.items():
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            if val:
                meta[key] = val

    pages_match = re.search(r"/Type\s*/Page[^s]", text, re.IGNORECASE)
    if pages_match:
        page_count = text.count("/Type /Page") - text.count("/Type /Pages")
        if page_count > 0:
            meta["pages"] = page_count

    return meta
