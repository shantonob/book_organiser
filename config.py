import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Mode detection ──
IN_DOCKER = os.environ.get("BOOK_ORGANISER_DOCKER", "").lower() in ("1", "true", "yes")

# ── Data & Config directories ──
# In Docker: DATA_DIR is the SSD mount, CONFIG_DIR is the SD card mount
# In native: both default to BASE_DIR/data
if IN_DOCKER:
    DATA_DIR = os.environ.get("BOOK_DATA_DIR", "/data")
    CONFIG_DIR = os.environ.get("BOOK_CONFIG_DIR", "/config")
else:
    DATA_DIR = os.path.join(BASE_DIR, "data")
    CONFIG_DIR = os.path.join(BASE_DIR, "data")

SOURCE_DIR = os.environ.get("BOOK_SOURCE_DIR", r"Z:\books")
SOURCE_DIRS = [d.strip() for d in SOURCE_DIR.split(";") if d.strip()]
INBOX_DIR = os.environ.get("BOOK_INBOX_DIR", os.path.join(DATA_DIR, "inbox"))
WATCH_DIR = os.environ.get("BOOK_WATCH_DIR", INBOX_DIR)
WATCH_RECURSIVE = os.environ.get("BOOK_WATCH_RECURSIVE", "true").lower() in ("true", "1", "yes")
PROCESSED_DIR = os.environ.get("BOOK_PROCESSED_DIR", os.path.join(DATA_DIR, "processed"))
FLAT_DIR = os.environ.get("BOOK_FLAT_DIR", os.path.join(PROCESSED_DIR, "flat"))
ARCHIVE_DIR = os.environ.get("BOOK_ARCHIVE_DIR", os.path.join(PROCESSED_DIR, "archive"))
DB_PATH = os.environ.get("BOOK_DB_PATH", os.path.join(DATA_DIR, "catalog.db"))
EXCLUDE_DIRS = set(
    os.environ.get("BOOK_EXCLUDE_DIRS", ".git,__pycache__,data,templates,extractors,inbox,processed,covers").split(",")
)
EXCLUDE_EXTS = set(
    os.environ.get("BOOK_EXCLUDE_EXTS", ".ini,.db,.lnk,.url,.tmp,.dat,.exe,.dll").split(",")
)
EBOOK_EXTS = set(
    os.environ.get("BOOK_EBOOK_EXTS", ".epub,.pdf,.mobi,.azw3,.djvu,.cbr,.cbz,.fb2").split(",")
)
DUPLICATE_SIMILARITY_THRESHOLD = float(
    os.environ.get("BOOK_DUP_SIMILARITY", "0.85")
)

# ── Logging (on CONFIG_DIR = SD card) ──
LOG_DIR = os.environ.get("BOOK_LOG_DIR", os.path.join(CONFIG_DIR, "logs"))
LOG_FILE = os.path.join(LOG_DIR, "app.log")

# ── Auth ──
AUTH_PASSWORD = os.environ.get("BOOK_AUTH_PASSWORD", "")
AUTH_ENABLED = bool(AUTH_PASSWORD)
SECRET_KEY = os.environ.get("BOOK_SECRET_KEY", "change-me-in-production")

# ── External enrichment ──
GOOGLE_BOOKS_API_KEY = os.environ.get("GOOGLE_BOOKS_API_KEY", "")
ENRICH_CACHE_PATH = os.environ.get("BOOK_ENRICH_CACHE", os.path.join(DATA_DIR, "enrich_cache.json"))
ENRICH_RATE_LIMIT = float(os.environ.get("BOOK_ENRICH_RATE_LIMIT", "1.0"))
