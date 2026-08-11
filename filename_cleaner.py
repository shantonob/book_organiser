import hashlib
import os
import re
from difflib import SequenceMatcher

BANNED_PATTERNS = [
    r"www\.\S+\.(com|net|org|info|biz)",
    r"http[s]?://\S+",
    r"\[[^\]]*\]",                        # [xxxx]
    r"\([^)]*\d{4}[^)]*\)",              # (c)2005, (2005)
    r"(ebook|epub|pdf|mobi|azw3|djvu)\s*$",
    r"[-–—]+\s*(free\s*)?(download|ebook|book)\s*$",
    r"\b\d{3,4}p\b",                      # 300p, 1200p
    r"\bv\.?\s*\d+\.\d+\b",              # v1.0, v.2.5
    r"\b(edition|ed|vol|volume|part|pt)\s*\.?\s*\d+\b",
    r"[#_]+",
    r"^\d{3,4}\s*[-–—]\s*",              # leading year
]

YEAR_PATTERN = re.compile(r"\b(1[89]\d{2}|20[0-2]\d)\b")
TITLE_CLEAN = re.compile(r"[^\w\s'\-À-ÿ]")


def clean_filename(filename):
    name, ext = os.path.splitext(filename)
    for pat in BANNED_PATTERNS:
        name = re.sub(pat, "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+", " ", name).strip(" ._-")
    if not name:
        name = "untitled"
    return f"{name}{ext}"


def extract_year_from_filename(filename):
    m = YEAR_PATTERN.search(filename)
    return int(m.group(0)) if m else None


def normalize_title(title):
    if not title:
        return ""
    t = title.strip().lower()
    t = TITLE_CLEAN.sub("", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()[:200]


def file_hash(filepath, blocksize=65536):
    h = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            while True:
                buf = f.read(blocksize)
                if not buf:
                    break
                h.update(buf)
        return h.hexdigest()
    except Exception:
        return None


def title_similarity(a, b):
    return SequenceMatcher(None, normalize_title(a), normalize_title(b)).ratio()


def is_duplicate_title(existing_title, new_title, threshold=0.85):
    if not existing_title or not new_title:
        return False
    return title_similarity(existing_title, new_title) >= threshold
