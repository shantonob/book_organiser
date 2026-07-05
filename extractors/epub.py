import os
from ebooklib import epub


def extract_epub(filepath):
    book = epub.read_epub(filepath, options={"ignore_ncx": True})
    meta = {}

    title = book.get_metadata("DC", "title")
    meta["title"] = title[0][0] if title else os.path.splitext(os.path.basename(filepath))[0]

    creators = book.get_metadata("DC", "creator")
    if creators:
        names = [c[0] for c in creators]
        meta["authors"] = "; ".join(names)

    publisher = book.get_metadata("DC", "publisher")
    if publisher:
        meta["publisher"] = publisher[0][0]

    ident = book.get_metadata("DC", "identifier")
    for i in ident:
        val = i[0]
        if "isbn" in val.lower() or (val.startswith("978") or val.startswith("979")):
            meta["isbn"] = val.replace("urn:isbn:", "").replace("-", "").strip()
            break
        if "://" not in val:
            meta["isbn"] = val.strip()

    lang = book.get_metadata("DC", "language")
    if lang:
        meta["language"] = lang[0][0]

    desc = book.get_metadata("DC", "description")
    if desc:
        meta["description"] = desc[0][0]

    subjects = book.get_metadata("DC", "subject")
    if subjects:
        meta["subjects"] = [s[0] for s in subjects if s[0].strip()]

    date = book.get_metadata("DC", "date")
    if date:
        try:
            meta["year"] = int(date[0][0][:4])
        except (ValueError, IndexError):
            pass

    cover_data = None
    for item in book.get_items_of_type(ebooklib.ITEM_COVER):
        cover_data = item.get_content()
        break
    if not cover_data:
        for item in book.get_items_of_type(ebooklib.ITEM_COVER):
            if hasattr(item, "get_content"):
                cover_data = item.get_content()
                break
    if cover_data:
        meta["cover_data"] = cover_data

    return meta
