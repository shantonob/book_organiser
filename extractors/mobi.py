import os
import struct


def extract_mobi(filepath):
    meta = {}
    meta["title"] = os.path.splitext(os.path.basename(filepath))[0]

    try:
        with open(filepath, "rb") as f:
            header = f.read(78)
    except Exception:
        return meta

    if len(header) < 78:
        return meta

    try:
        name_len = struct.unpack_from(">I", header, 76)[0]
        with open(filepath, "rb") as f:
            f.seek(78)
            raw_name = f.read(min(name_len, 256))
        name = raw_name.decode("utf-8", errors="replace").strip("\x00").strip()
        if name:
            meta["title"] = name
    except Exception:
        pass

    return meta
