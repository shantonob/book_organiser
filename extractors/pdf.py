import os
import re


def _clean_info_val(val):
    # PDF Info strings are frequently UTF-16 (BE or LE). The raw bytes were
    # decoded as latin-1, so a UTF-16 BOM now reads as "\u00fe\u00ff" / "\u00ff\u00fe"
    # followed by NUL-interleaved text. Re-encode back to raw bytes and decode
    # properly, dropping stray control characters.
    try:
        if val.startswith("\u00fe\u00ff"):
            val = val.encode("latin-1").decode("utf-16-be", errors="replace")
        elif val.startswith("\u00ff\u00fe"):
            val = val.encode("latin-1").decode("utf-16-le", errors="replace")
    except Exception:
        pass
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", val).replace("\ufeff", "").replace("\ufffe", "").strip()


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
                meta[key] = _clean_info_val(val)

    pages_match = re.search(r"/Type\s*/Page[^s]", text, re.IGNORECASE)
    if pages_match:
        page_count = text.count("/Type /Page") - text.count("/Type /Pages")
        if page_count > 0:
            meta["pages"] = page_count

    return meta
