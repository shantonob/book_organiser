import os
import zipfile


def extract_cbz(filepath):
    meta = {}
    meta["title"] = os.path.splitext(os.path.basename(filepath))[0]
    meta["format_hint"] = "comic"

    try:
        with zipfile.ZipFile(filepath, "r") as zf:
            infos = zf.infolist()
            image_count = sum(1 for f in infos if f.filename.lower().endswith((".jpg", ".png", ".jpeg", ".webp")))
            if image_count:
                meta["pages"] = image_count
    except Exception:
        pass

    return meta
