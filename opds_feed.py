"""OPDS 1.2 catalog feed generation (BL-013).

Builds Atom/OPDS navigation and acquisition feeds over the book catalog so
e-reader apps (KoReader, Lithium, Thorium, ...) can browse, search, and
download the library.

Routes (registered in app.py):
    /opds                    root navigation feed
    /opds/catalog            full catalog (paginated acquisition feed)
    /opds/recent             recently updated books
    /opds/udc                UDC browse (navigation)
    /opds/udc/<code>         books in one UDC code
    /opds/search?q=          search feed (acquisition)
    /opds/opensearch.xml     OpenSearch description
    /opds/shelf              reading list (acquisition)
"""

import os
import re
from xml.sax.saxutils import escape

OPDS_NAV = "application/atom+xml;profile=opds-catalog;kind=navigation"
OPDS_ACQ = "application/atom+xml;profile=opds-catalog;kind=acquisition"
OPDS_ENTRY = "application/atom+xml;type=entry;profile=opds-catalog"

# Strip C0/C1 control characters (except \t \n \r) plus DEL — Expat rejects
# them even though some are nominally legal in XML 1.0.
_XML_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def _esc(value):
    """Escape for XML text/attributes after stripping characters illegal in XML 1.0."""
    cleaned = _XML_ILLEGAL.sub("", str(value or ""))
    return escape(cleaned, {'"': "&quot;", "'": "&apos;"})


_BOOK_MIME = {
    "epub": "application/epub+zip",
    "pdf": "application/pdf",
    "mobi": "application/x-mobipocket-ebook",
    "azw": "application/vnd.amazon.ebook",
    "azw3": "application/vnd.amazon.ebook",
    "kfx": "application/vnd.amazon.ebook",
    "fb2": "application/x-fictionbook+xml",
    "djvu": "image/vnd.djvu",
    "cbz": "application/vnd.comicbook+zip",
    "cbr": "application/x-cbr",
    "cbt": "application/x-cbt",
    "txt": "text/plain",
    "html": "text/html",
    "htm": "text/html",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "rtf": "application/rtf",
    "odt": "application/vnd.oasis.opendocument.text",
}

_IMG_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _book_mime(fmt):
    return _BOOK_MIME.get((fmt or "").lower(), "application/octet-stream")


def _cover_mime(cover_path):
    if cover_path:
        return _IMG_MIME.get(os.path.splitext(cover_path)[1].lower(), "image/jpeg")
    return "image/jpeg"


def _title_of(row):
    return (row.get("title") or row.get("filename") or f"Book #{row.get('id')}").strip()


def _authors_of(row):
    raw = row.get("authors") or ""
    return [a.strip() for a in raw.split("&") if a.strip()]


def _entry(row, base_url, include_cover=True):
    """Render one acquisition <entry> for a book row."""
    book_id = row["id"]
    raw_title = _title_of(row)
    title = _esc(raw_title)
    authors = _authors_of(row)
    description = _esc((row.get("description") or "").strip()[:400])
    udc_code = row.get("udc_code")
    udc_label = row.get("udc_label")
    fmt = row.get("format")

    p = [f'<title>{title}</title>',
         f'<id>tag:book-organiser:book:{book_id}</id>',
         f'<updated>{row.get("updated_at") or row.get("created_at") or ""}</updated>']
    for a in authors:
        p.append(f"<author><name>{_esc(a)}</name></author>")
    if description:
        p.append(f'<content type="text">{description}</content>')
    if udc_label:
        p.append(f'<category term="{_esc(str(udc_code or ""))}" label="{_esc(udc_label)}"/>')
    if include_cover:
        cp = row.get("cover_path")
        if cp and os.path.isfile(cp):
            ct = _cover_mime(cp)
            p.append(f'<link rel="http://opds-spec.org/image" href="{base_url}/api/cover/{book_id}" type="{ct}"/>')
    p.append(f'<link rel="http://opds-spec.org/acquisition" href="{base_url}/api/book/{book_id}/download" '
             f'type="{_book_mime(fmt)}" title="{_esc(raw_title)} ({_esc(str(fmt or "").upper())})"/>')
    return "<entry>" + "".join(p) + "</entry>"


def _feed(title, entries, base_url, self_path, updated, start_url, next_path=None,
          opensearch_url=None):
    p = ['<?xml version="1.0" encoding="utf-8"?>',
         '<feed xmlns="http://www.w3.org/2005/Atom" '
         'xmlns:opds="http://opds-spec.org/2010/catalog">',
         '<id>tag:book-organiser:feed</id>',
         f'<title>{_esc(title)}</title>',
         f'<updated>{updated}</updated>',
         '<author><name>Book Organiser</name></author>',
         f'<link rel="self" href="{_esc(base_url + self_path)}" type="{OPDS_NAV}"/>',
         f'<link rel="start" href="{_esc(base_url + start_url)}" type="{OPDS_NAV}"/>']
    if opensearch_url:
        p.append(f'<link rel="search" href="{_esc(base_url + opensearch_url)}" '
                 'type="application/opensearchdescription+xml"/>')
    if next_path:
        p.append(f'<link rel="next" href="{_esc(base_url + next_path)}" type="{OPDS_ACQ}"/>')
    p.extend(entries)
    p.append("</feed>")
    return "".join(p)


def nav_feed(title, entries, base_url, self_path, updated, start_url="/opds",
             opensearch_url="/opds/opensearch.xml"):
    """Build a navigation feed whose entries link to subsections."""
    p = ['<?xml version="1.0" encoding="utf-8"?>',
         '<feed xmlns="http://www.w3.org/2005/Atom" '
         'xmlns:opds="http://opds-spec.org/2010/catalog">',
         '<id>tag:book-organiser:nav</id>',
         f'<title>{_esc(title)}</title>',
         f'<updated>{updated}</updated>',
         '<author><name>Book Organiser</name></author>',
         f'<link rel="self" href="{_esc(base_url + self_path)}" type="{OPDS_NAV}"/>',
         f'<link rel="start" href="{_esc(base_url + start_url)}" type="{OPDS_NAV}"/>',
         f'<link rel="search" href="{_esc(base_url + (opensearch_url or "/opds/opensearch.xml"))}" '
         'type="application/opensearchdescription+xml"/>']
    p.extend(entries)
    p.append("</feed>")
    return "".join(p)


def nav_entry(title, subsection_url, updated, subtitle="", count=None):
    """Navigation feed entry pointing at an acquisition feed."""
    extra = f" &#8212; {count} books" if count is not None else ""
    return ("<entry>"
            f"<title>{_esc(title)}</title>"
            f"<id>tag:book-organiser:nav:{_esc(subsection_url)}</id>"
            f"<updated>{updated}</updated>"
            f'<content type="text">{_esc(subtitle)}{_esc(extra)}</content>'
            f'<link rel="subsection" href="{_esc(subsection_url)}" type="{OPDS_ACQ}"/>'
            "</entry>")


def opensearch_xml(base_url):
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<OpenSearchDescription xmlns="http://a9.com/-/spec/opensearch/1.1/">'
            "<ShortName>Book Organiser</ShortName>"
            "<Description>Search the Book Organiser catalog</Description>"
            "<Tags>books catalog</Tags>"
            "<Contact>admin@localhost</Contact>"
            f'<Url type="{OPDS_ACQ}" template="{_esc(base_url)}/opds/search?q={{searchTerms}}&amp;startIndex={{startIndex?}}"/>'
            "</OpenSearchDescription>")


def _udc_entry(code, label, count, base_url, now, acq=OPDS_ACQ):
    """Acquisition-navigation entry for one UDC class (escapes label/code)."""
    from urllib.parse import quote
    code = str(code or "")
    label = str(label or code)
    return ("<entry>"
            f"<title>{_esc(label)}</title>"
            f"<id>tag:book-organiser:udc:{_esc(code)}</id>"
            f"<updated>{now}</updated>"
            f'<content type="text">UDC {_esc(code)} &#8212; {int(count or 0)} books</content>'
            f'<link rel="subsection" href="{base_url}/opds/udc/{quote(code)}" type="{acq}"/></entry>')