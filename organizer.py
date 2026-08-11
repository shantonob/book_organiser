import os
import shutil

from config import FLAT_DIR
from filename_cleaner import clean_filename


def copy_to_flat(source_path, file_id=None):
    os.makedirs(FLAT_DIR, exist_ok=True)
    clean_name = clean_filename(os.path.basename(source_path))
    dest = os.path.join(FLAT_DIR, clean_name)
    if os.path.exists(dest):
        base, ext = os.path.splitext(clean_name)
        tag = f"_{file_id}" if file_id else f"_{hash(source_path) % 10000}"
        dest = os.path.join(FLAT_DIR, f"{base}{tag}{ext}")
    shutil.copy2(source_path, dest)
    return dest
