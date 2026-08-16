import os
import re
import zipfile

_IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp")


def extract_cbz(filepath):
    meta = {}
    meta["title"] = os.path.splitext(os.path.basename(filepath))[0]
    meta["format_hint"] = "comic"

    try:
        with zipfile.ZipFile(filepath, "r") as zf:
            infos = zf.infolist()
            image_infos = [f for f in infos if f.filename.lower().endswith(_IMG_EXTS)]
            if image_infos:
                meta["pages"] = len(image_infos)
                # Natural-sort by filename so the cover is the real first page.
                image_infos.sort(key=lambda f: _nat_key(f.filename))
                first = image_infos[0]
                try:
                    meta["cover_data"] = zf.read(first)
                except Exception:
                    pass
    except Exception:
        pass

    return meta


def _nat_key(name):
    parts = []
    for chunk in re.split(r"(\d+)", name.lower()):
        parts.append(int(chunk) if chunk.isdigit() else chunk)
    return parts
