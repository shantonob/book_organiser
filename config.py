import os
import hashlib

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Mode detection ──
IN_DOCKER = os.environ.get("BOOK_ORGANISER_DOCKER", "").lower() in ("1", "true", "yes")

# ── machine.json (P6.1 Portable Config) ──
_MACHINE_JSON = os.path.join(BASE_DIR, "machine.json")
MACHINE_CONFIG = {}
if os.path.isfile(_MACHINE_JSON):
    try:
        import json as _json
        with open(_MACHINE_JSON, encoding="utf-8") as _f:
            MACHINE_CONFIG = _json.load(_f)
    except Exception:
        pass

# ── Data & Config directories ──
# In Docker: DATA_DIR is the SSD mount, CONFIG_DIR is the SD card mount
# In native: machine.json data_dir overrides, else BASE_DIR/data
if IN_DOCKER:
    DATA_DIR = os.environ.get("BOOK_DATA_DIR", MACHINE_CONFIG.get("data_dir", "/data"))
    CONFIG_DIR = os.environ.get("BOOK_CONFIG_DIR", MACHINE_CONFIG.get("data_dir", "/config"))
else:
    DATA_DIR = MACHINE_CONFIG.get("data_dir") or os.environ.get("BOOK_DATA_DIR") or os.path.join(BASE_DIR, "data")
    CONFIG_DIR = os.environ.get("BOOK_CONFIG_DIR") or DATA_DIR

# ── All paths are blank by default — user provides them via Settings tab ──
# Required: source_dirs, flat_dir, inbox_dir
# Optional with derived defaults: archive_dir (flat_dir/archive), watch_dir (inbox_dir)
SOURCE_DIR = ""
SOURCE_DIRS = []
INBOX_DIR = ""
WATCH_DIR = ""
WATCH_RECURSIVE = True
PROCESSED_DIR = ""
FLAT_DIR = ""
ARCHIVE_DIR = ""
_DEFAULT_DB = os.path.join(DATA_DIR, "catalog.db")
DB_PATH = os.environ.get("BOOK_DB_PATH", _DEFAULT_DB)
# If default DB is on a network/SMB path, use a local copy for performance
ORIGINAL_DB_PATH = None
if not os.environ.get("BOOK_DB_PATH") and "\\\\" in DB_PATH:
    ORIGINAL_DB_PATH = DB_PATH
    _LOCAL_DB = os.path.join(os.path.expanduser("~"), "book_organiser_data", "catalog.db")
    DB_PATH = _LOCAL_DB
LOCAL_DB_REDIRECTED = ORIGINAL_DB_PATH is not None


def seed_local_db(original_path, local_path):
    """If the local working-copy DB is missing but the remote original exists,
    copy the original down so a fresh machine boots with real data instead of
    silently creating an empty catalog (root cause of 'no books' on other hosts)."""
    import shutil as _shutil
    if (original_path and local_path
            and not os.path.isfile(local_path) and os.path.isfile(original_path)):
        try:
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            _shutil.copy2(original_path, local_path)
            return True
        except Exception:
            return False
    return False


if LOCAL_DB_REDIRECTED:
    seed_local_db(ORIGINAL_DB_PATH, DB_PATH)
EXCLUDE_DIRS = set(
    os.environ.get("BOOK_EXCLUDE_DIRS", ".git,__pycache__,data,templates,extractors").split(",")
)
# Store the base set to avoid accumulation on reload (D7.28)
_BASE_EXCLUDE_DIRS = set(EXCLUDE_DIRS)
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
SECRET_KEY = os.environ.get("BOOK_SECRET_KEY", os.environ.get("BOOK_AUTH_PASSWORD", hashlib.sha256((os.environ.get("COMPUTERNAME", "book_organiser") + "::book_organiser").encode()).hexdigest()))

# ── External enrichment ──
GOOGLE_BOOKS_API_KEY = os.environ.get("GOOGLE_BOOKS_API_KEY", "")
ENRICH_CACHE_PATH = os.environ.get("BOOK_ENRICH_CACHE", os.path.join(DATA_DIR, "enrich_cache.json"))
ENRICH_RATE_LIMIT = float(os.environ.get("BOOK_ENRICH_RATE_LIMIT", "1.0"))
