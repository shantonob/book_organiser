import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SOURCE_DIR = r"Z:\books"
SOURCE_DIRS = [SOURCE_DIR]
INBOX_DIR = os.path.join(BASE_DIR, "inbox")
PROCESSED_DIR = os.path.join(BASE_DIR, "processed")
FLAT_DIR = r"Z:\books\processed"
DB_PATH = os.path.join(BASE_DIR, "data", "catalog.db")
EXCLUDE_DIRS = {".git", "__pycache__", "data", "templates", "extractors",
                "inbox", "processed", "covers"}
EXCLUDE_EXTS = {".ini", ".db", ".lnk", ".url", ".tmp", ".dat", ".exe", ".dll"}
EBOOK_EXTS = {".epub", ".pdf", ".mobi", ".azw3", ".djvu", ".cbr", ".cbz", ".fb2"}
DUPLICATE_SIMILARITY_THRESHOLD = 0.85

# Logging
LOG_DIR = os.path.join(BASE_DIR, "data", "logs")

# External enrichment
GOOGLE_BOOKS_API_KEY = os.environ.get("GOOGLE_BOOKS_API_KEY", "")
ENRICH_CACHE_PATH = os.path.join(BASE_DIR, "data", "enrich_cache.json")
ENRICH_RATE_LIMIT = 1.0  # seconds between API calls
