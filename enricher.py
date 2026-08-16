import hashlib
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import config

logger = logging.getLogger("enricher")
_LAST_CALL = 0
_cache_lock = threading.Lock()


def _rate_limit():
    global _LAST_CALL
    elapsed = time.time() - _LAST_CALL
    if elapsed < config.ENRICH_RATE_LIMIT:
        time.sleep(config.ENRICH_RATE_LIMIT - elapsed)
    _LAST_CALL = time.time()


def _cache_key(isbn=None, title=None, author=None):
    # Version 2: added work-record descriptions + stub filtering (BL-014).
    raw = "v2|" + (isbn or (title or "") + "|" + (author or ""))
    return hashlib.md5(raw.encode()).hexdigest()


def _with_cache(callback, default=None):
    """Thread-safe read-modify-write on enrich cache (D7.22)."""
    with _cache_lock:
        try:
            with open(config.ENRICH_CACHE_PATH, encoding="utf-8") as f:
                cache = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            cache = {}
        result = callback(cache)
        os.makedirs(os.path.dirname(config.ENRICH_CACHE_PATH), exist_ok=True)
        with open(config.ENRICH_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
        return result if result is not None else default


def _fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "BookOrganiser/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


# ── Open Library ─────────────────────────────────────────────

def _ol_work_description(work_key):
    """Fetch a work record's description (search.json docs don't include it).

    Rejects catalog stubs like "1 online resource :" or "3 v. : ill.".
    """
    if not work_key:
        return None
    url = f"https://openlibrary.org{work_key}.json"
    data = _fetch_json(url)
    if not data:
        return None
    desc = data.get("description")
    if isinstance(desc, dict):
        desc = desc.get("value")
    if not isinstance(desc, str):
        return None
    desc = desc.strip()
    if len(desc) < 40:
        return None
    stub = r"^[\s\d]+(online resource|v\.|vol\.|volumes|p\.|p\. cm|cm\.)"
    if re.search(stub, desc, re.IGNORECASE):
        return None
    return desc


def _ol_search(isbn=None, title=None, author=None):
    query = ""
    if isbn:
        query = f"isbn:{isbn}"
    else:
        query = title or ""
        if author:
            query += f" {author}"
    url = f"https://openlibrary.org/search.json?q={urllib.parse.quote(query, safe=':')}"
    data = _fetch_json(url)
    if not data or not data.get("docs"):
        return None
    doc = data["docs"][0]
    ol_cover_isbn = (doc.get("isbn", []) or [None])[0]
    result = {
        "title": doc.get("title"),
        "authors": ", ".join(doc.get("author_name", [])),
        "publisher": ", ".join(doc.get("publisher", [])) if doc.get("publisher") else None,
        "year": doc.get("first_publish_year"),
        "subjects": ", ".join(doc.get("subject", [])[:10]) if doc.get("subject") else None,
        "isbn": ol_cover_isbn,
        "pages": doc.get("number_of_pages_median"),
        "cover_url": f"https://covers.openlibrary.org/b/isbn/{ol_cover_isbn}-L.jpg" if ol_cover_isbn else None,
        "source": "openlibrary_search",
    }
    # search.json has no description; pull it from the work record when cheap
    desc = _ol_work_description(doc.get("key"))
    if desc:
        result["description"] = desc
    return result


# ── Google Books ─────────────────────────────────────────────

def _gb_search(title=None, author=None, isbn=None):
    if not config.GOOGLE_BOOKS_API_KEY:
        return None
    # Prefer ISBN lookup for precision
    if isbn:
        query = f"isbn:{isbn}"
    else:
        query = title or ""
        if author:
            query += f" {author}"
    url = f"https://www.googleapis.com/books/v1/volumes?q={urllib.parse.quote(query)}&key={config.GOOGLE_BOOKS_API_KEY}"
    data = _fetch_json(url)
    if not data or not data.get("items"):
        return None
    vol = data["items"][0].get("volumeInfo", {})
    result = {
        "title": vol.get("title"),
        "authors": ", ".join(vol.get("authors", [])),
        "publisher": vol.get("publisher"),
        "year": vol.get("publishedDate", "")[:4] if vol.get("publishedDate") else None,
        "subjects": ", ".join(vol.get("categories", [])),
        "isbn": next((id_["identifier"] for id_ in vol.get("industryIdentifiers", [])
                      if id_.get("type") in ("ISBN_13", "ISBN_10")), None),
        "pages": vol.get("pageCount"),
        "language": vol.get("language"),
        "description": vol.get("description"),
        "cover_url": vol.get("imageLinks", {}).get("thumbnail"),
        "source": "google_books",
    }
    return result


def _download_cover(cover_url, dest_dir):
    if not cover_url:
        return None
    try:
        os.makedirs(dest_dir, exist_ok=True)
        fname = hashlib.md5(cover_url.encode()).hexdigest() + ".jpg"
        dest = os.path.join(dest_dir, fname)
        if os.path.exists(dest):
            return dest
        req = urllib.request.Request(cover_url, headers={"User-Agent": "BookOrganiser/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp, open(dest, "wb") as f:
            f.write(resp.read())
        return dest
    except Exception as e:
        logger.warning("cover download failed for %s: %s", cover_url, e)
        return None


# ── Public API ───────────────────────────────────────────────

def enrich_book(isbn=None, title=None, author=None):
    """Query external APIs to fill missing metadata.

    Lookup chain: Open Library (ISBN or title+author), then Google Books (ISBN or title+author).
    Google Books is tried when OL returns nothing OR when OL results lack description.
    Returns dict with any enriched fields, or empty dict.
    """
    key = _cache_key(isbn=isbn, title=title, author=author)
    cached = _with_cache(lambda c: c.get(key))
    if cached:
        return cached

    result = {}

    # 1. Open Library search (ISBN if available, else title+author)
    if isbn or title or author:
        _rate_limit()
        result = _ol_search(isbn=isbn, title=title, author=author) or {}

    # 2. Google Books fallback
    need_gb = not result.get("title") or not result.get("description")
    if need_gb and (isbn or title or author):
        _rate_limit()
        gb_result = _gb_search(title=title, author=author, isbn=isbn) or {}
        if gb_result:
            for field in ("title", "authors", "publisher", "year", "subjects", "isbn", "pages", "language", "description", "cover_url"):
                if not result.get(field) and gb_result.get(field):
                    result[field] = gb_result[field]
            result["source"] = result.get("source") or gb_result.get("source", "google_books")

    if result:
        _with_cache(lambda c: c.update({key: result}) or c)

    return result
