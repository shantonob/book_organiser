from .cbz import extract_cbz
from .epub import extract_epub
from .mobi import extract_mobi
from .pdf import extract_pdf

EXTRACTORS = {
    ".epub": extract_epub,
    ".pdf":  extract_pdf,
    ".mobi": extract_mobi,
    ".azw3": extract_mobi,
    ".cbz":  extract_cbz,
    ".cbr":  extract_cbz,
}


def extract_metadata(filepath):
    import os
    ext = os.path.splitext(filepath)[1].lower()
    fn = EXTRACTORS.get(ext)
    if fn is None:
        return {}
    try:
        return fn(filepath)
    except Exception as e:
        return {"_error": str(e)}
