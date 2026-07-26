import json
import os
import time
import hashlib
import urllib.request
import urllib.parse
import urllib.error

import config

_LAST_CALL = 0


def _rate_limit():
    global _LAST_CALL
    elapsed = time.time() - _LAST_CALL
    if elapsed < config.ENRICH_RATE_LIMIT:
        time.sleep(config.ENRICH_RATE_LIMIT - elapsed)
    _LAST_CALL = time.time()


def _cache_key(isbn=None, title=None, author=None):
    raw = isbn or f"{title or ''}|{author or ''}"
    return hashlib.md5(raw.encode()).hexdigest()


def _load_cache():
    try:
        with open(config.ENRICH_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_cache(cache):
    os.makedirs(os.path.dirname(config.ENRICH_CACHE_PATH), exist_ok=True)
    with open(config.ENRICH_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)


def _fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "BookOrganiser/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


# ── Open Library ─────────────────────────────────────────────

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
    return {
        "title": doc.get("title"),
        "authors": ", ".join(doc.get("author_name", [])),
        "publisher": ", ".join(doc.get("publisher", [])) if doc.get("publisher") else None,
        "year": doc.get("first_publish_year"),
        "subjects": ", ".join(doc.get("subject", [])[:10]) if doc.get("subject") else None,
        "isbn": (doc.get("isbn", []) or [None])[0],
        "pages": doc.get("number_of_pages_median"),
        "source": "openlibrary_search",
    }


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
    """Download a cover image URL to dest_dir, return the local path or None."""
    if not cover_url:
        return None
    try:
        os.makedirs(dest_dir, exist_ok=True)
        fname = hashlib.md5(cover_url.encode()).hexdigest() + ".jpg"
        dest = os.path.join(dest_dir, fname)
        if os.path.exists(dest):
            return dest
        req = urllib.request.Request(cover_url, headers={"User-Agent": "BookOrganiser/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            with open(dest, "wb") as f:
                f.write(resp.read())
        return dest
    except Exception:
        return None


# ── Public API ───────────────────────────────────────────────

def enrich_book(isbn=None, title=None, author=None):
    """Query external APIs to fill missing metadata.

    Lookup chain: Open Library (ISBN or title+author), then Google Books (ISBN or title+author).
    Google Books is tried when OL returns nothing OR when OL results lack description.
    Returns dict with any enriched fields, or empty dict.
    """
    cache = _load_cache()
    key = _cache_key(isbn=isbn, title=title, author=author)
    cached = cache.get(key)
    if cached:
        return cached

    result = {}

    # 1. Open Library search (ISBN if available, else title+author)
    if isbn or title or author:
        _rate_limit()
        result = _ol_search(isbn=isbn, title=title, author=author) or {}

    # 2. Google Books fallback — try when OL returned nothing, or when description is missing
    need_gb = not result.get("title") or not result.get("description")
    if need_gb and (isbn or title or author):
        _rate_limit()
        gb_result = _gb_search(title=title, author=author, isbn=isbn) or {}
        if gb_result:
            # Merge: fill gaps from OL with GB data, but prefer OL for fields OL already has
            for field in ("title", "authors", "publisher", "year", "subjects", "isbn", "pages", "language", "description", "cover_url"):
                if not result.get(field) and gb_result.get(field):
                    result[field] = gb_result[field]
            result["source"] = result.get("source") or gb_result.get("source", "google_books")

    if result:
        cache[key] = result
        _save_cache(cache)

    return result
