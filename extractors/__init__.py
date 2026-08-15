from .cbz import extract_cbz
from .cbr import extract_cbr
from .epub import extract_epub
from .mobi import extract_mobi
from .pdf import extract_pdf

EXTRACTORS = {
    ".epub": extract_epub,
    ".pdf":  extract_pdf,
    ".mobi": extract_mobi,
    ".azw3": extract_mobi,
    ".cbz":  extract_cbz,
    ".cbr":  extract_cbr,
}


class ExtractError(Exception):
    """Extraction failure that carries a quarantine error code."""

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def extract_metadata(filepath):
    import os
    ext = os.path.splitext(filepath)[1].lower()
    fn = EXTRACTORS.get(ext)
    if fn is None:
        return {}
    try:
        return fn(filepath)
    except ExtractError as e:
        out = {"_error": str(e)}
        if e.code:
            out["_error_code"] = e.code
        return out
    except Exception as e:
        return {"_error": str(e)}
