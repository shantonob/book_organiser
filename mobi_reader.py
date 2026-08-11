"""Pure-stdlib reader fallback for formats that calibre would otherwise convert.

P8.2 — no external binaries, no runtime services, no third-party packages.
- FB2  -> real EPUB (FictionBook XML body mapped to XHTML)
- MOBI (KF7/PalmDOC) -> best-effort EPUB from the PalmDOC-compressed HTML stream
- AZW3/KF8 -> best-effort via the raw HTML stream when it is PalmDOC-compressed

Anything that can't be parsed returns None (caller shows a Download fallback).
References: PalmDOC spec (calibre format_docs), KindleUnpack mobi_header/mobi_uncompress.

Structure of this module mirrors a subset of the Mobipocket "BOOK" database:
PDB header -> record 0 holds PalmDOC+MOBI headers -> records 1..N hold compressed
text. Each text record is PalmDOC-compressed independently.
"""

import os
import re
import struct
import xml.etree.ElementTree as ET
import zipfile

# ── shared EPUB builder ────────────────────────────────────────────────────

def _build_epub(out_path, title, author, chapters):
    """chapters: list of (id, heading, xhtml_body). Writes an EPUB2 zip to out_path."""
    import uuid
    book_uuid = uuid.uuid4().hex
    manifest = []
    spine = []
    xhtml_files = []
    for i, (cid, heading, body) in enumerate(chapters):
        fid = f"ch{i}"
        href = f"chapter{i + 1}.xhtml"
        manifest.append(('item', fid, href, 'application/xhtml+xml'))
        spine.append(('itemref', fid))
        xhtml_files.append((href, f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>{_xml_esc(heading)}</title></head>
<body>{body}</body>
</html>
"""))
    if not manifest:
        return None
    manifest_xml = "\n".join(
        f'<item id="{iid}" href="{href}" media-type="{mt}"/>'
        for kind, iid, href, mt in manifest)
    spine_xml = "\n".join(f'<itemref idref="{iid}"/>' for kind, iid in spine)
    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="uid" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:identifier id="uid">{book_uuid}</dc:identifier>
    <dc:title>{_xml_esc(title)}</dc:title>
    <dc:creator>{_xml_esc(author) or 'Unknown'}</dc:creator>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    {manifest_xml}
  </manifest>
  <spine toc="ncx">
    {spine_xml}
  </spine>
</package>
"""
    ncx = f"""<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head><meta content="{book_uuid}" name="dtb:uid"/></head>
  <docTitle><text>{_xml_esc(title)}</text></docTitle>
  <navMap>
    {chr(10).join(f'<navPoint id="np{i}" playOrder="{i + 1}"><navLabel><text>{_xml_esc(heading)}</text></navLabel><content src="{href}"/></navPoint>' for i, (href, _) in enumerate(xhtml_files))}
  </navMap>
</ncx>
"""
    container = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>
"""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with zipfile.ZipFile(out_path, "w") as zf:
            zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
            zf.writestr("META-INF/container.xml", container)
            zf.writestr("OEBPS/content.opf", opf)
            zf.writestr("OEBPS/toc.ncx", ncx)
            for href, xml_body in xhtml_files:
                zf.writestr("OEBPS/" + href, xml_body)
        return out_path
    except Exception:
        try:
            os.unlink(out_path)
        except Exception:
            pass
        return None


def _xml_esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&apos;"))


def _read(fp):
    with open(fp, "rb") as fh:
        return fh.read()


# ── FB2 ────────────────────────────────────────────────────────────────────

_FB2_NS = "{http://www.gribuser.ru/xml/fictionbook/2.0}"


def _fb2_to_epub(fb2_path, out_path):
    root = ET.fromstring(_read(fb2_path))

    def text_of(el, fallback=""):
        return _xml_esc("".join(node.text or "" for node in el.iter()) if el is not None else fallback)

    title = "FB2 book"
    author = ""
    desc = root.find(f"{_FB2_NS}description")
    if desc is not None:
        ti = desc.find(f"{_FB2_NS}title")
        if ti is not None:
            title = " ".join((t.text or "").strip() for t in ti.iter() if t.text and _strip_ns(t.tag) == "p").strip() or "FB2 book"
        for pa in desc.findall(f"{_FB2_NS}document-info"):
            pass  # structural; author usually in title-info/publish-info
        ta = desc.find(f"{_FB2_NS}title-info")
        if ta is not None:
            names = [n.text or "" for n in ta.iter() if _strip_ns(n.tag) in ("first-name", "last-name", "middle-name")]
            author = " ".join(s for s in names if s).strip()

    def render_body(body, depth=0):
        out = []
        for el in body:
            tag = _strip_ns(el.tag)
            if tag == "title":
                out.append(f"<h{depth + 2}>" + _xml_esc(" ".join(t.text or "" for t in el.iter() if t.text)) + f"</h{depth + 2}>")
            elif tag == "p":
                out.append("<p>" + _xml_esc(" ".join(t.text or "" for t in el.iter() if t.text)) + "</p>")
            elif tag == "epigraph":
                out.append("<blockquote>" + _xml_esc(" ".join(t.text or "" for t in el.iter() if t.text)) + "</blockquote>")
            elif tag == "empty-line":
                out.append("<br/>")
            elif tag == "section":
                out.append(render_body(el, depth + 1))
            elif tag == "poem":
                out.append("<pre>" + _xml_esc(" ".join(t.text or "" for t in el.iter() if t.text)) + "</pre>")
            elif tag == "subtitle":
                out.append("<h4>" + _xml_esc(" ".join(t.text or "" for t in el.iter() if t.text)) + "</h4>")
            elif el.text and el.text.strip():
                out.append("<p>" + _xml_esc(el.text) + "</p>")
        return "".join(out)

    bodies = []
    for i, body in enumerate(root.findall(f"{_FB2_NS}body")):
        body_html = render_body(body)
        bodies.append((f"body{i}", title if i == 0 else f"Section {i}", body_html or "<p></p>"))

    if not bodies:
        return None
    return _build_epub(out_path, title, author, bodies)


def _strip_ns(tag):
    return tag.rsplit("}", 1)[-1]


# ── PalmDOC decompression ──────────────────────────────────────────────────

def _palmdoc_unpack(data):
    o, p = bytearray(), 0
    n = len(data)
    while p < n:
        c = data[p]
        p += 1
        if 1 <= c <= 8:
            o += data[p:p + c]
            p += c
        elif c < 128:
            o.append(c)
        elif c >= 192:
            o.append(0x20)
            o.append(c ^ 0x80)
        else:
            # 0x80..0xbf: 14-bit distance:length pair
            if p >= n:
                break
            c = (c << 8) | data[p]
            p += 1
            dist = (c >> 3) & 0x7FF
            ln = (c & 7) + 3
            if dist < 1:
                continue
            for _ in range(ln):
                if len(o) >= dist:
                    o.append(o[len(o) - dist])
                else:
                    break
    return bytes(o)


# ── MOBI header + text extraction ──────────────────────────────────────────

def _u16(b, off):
    return struct.unpack(">H", b[off:off + 2])[0] if off + 2 <= len(b) else 0


def _u32(b, off):
    return struct.unpack(">I", b[off:off + 4])[0] if off + 4 <= len(b) else 0


def _mobi_raw_text(path):
    data = _read(path)
    if len(data) < 78:
        return None
    try:
        rec_count = _u16(data, 76)
    except Exception:
        rec_count = 0
    if rec_count == 0:
        return None
    # PDB record table: 8 bytes per record after the 78-byte PalmDB header
    offsets = []
    base = 78
    for i in range(rec_count):
        off = base + i * 8
        if off + 4 <= len(data):
            r0, = struct.unpack_from(">I", data, off)
            offsets.append(r0)
        else:
            offsets.append(len(data))
    if len(offsets) < 2:
        return None
    def sec(r):
        return data[offsets[r]: offsets[r + 1]] if r + 1 < len(offsets) else data[offsets[r]:]

    h0 = sec(0)
    if h0[16:20] != b"MOBI":
        return None

    text_records = _u16(h0, 0x08)
    compression = _u16(h0, 0x00)
    codepage = _u32(h0, 0x1C)
    crypto = _u16(h0, 0x0C)
    if crypto != 0:
        return None  # DRM'd
    if compression not in (1, 2):
        return None  # HuffDic (0x4448) or unknown

    # title from header (offset 0x54/0x58 relative to section start)
    toff = _u32(h0, 0x54)
    tlen = _u32(h0, 0x58)
    title = ""
    if toff and tlen and toff + tlen <= len(h0):
        try:
            title = h0[toff:toff + tlen].decode("utf-8", errors="replace").strip() or ""
        except Exception:
            title = ""

    chunks = []
    for i in range(1, min(text_records + 1, rec_count)):
        rec = sec(i)
        if compression == 1:
            chunks.append(rec)
        else:
            try:
                chunks.append(_palmdoc_unpack(rec))
            except Exception:
                # tolerate one bad record; append raw and keep going
                chunks.append(rec)
    raw = b"".join(chunks)
    if not raw:
        return None

    if codepage == 65001:
        text = raw.decode("utf-8", errors="replace")
    elif codepage == 1252:
        text = raw.decode("cp1252", errors="replace")
    elif codepage in (0, 0x190):
        # try utf-8 first, then cp1252
        try:
            text = raw.decode("utf-8", errors="strict")
        except Exception:
            text = raw.decode("charmap", errors="replace")
    else:
        text = raw.decode("charmap", errors="replace")
    return {"title": title, "html": text}


def _html_to_body(html):
    """Safely embed extracted HTML into an XHTML body (best-effort)."""
    # strip <html>/<head>/<body> wrappers if present
    m = re.search(r"<body[^>]*>(.*)</body>", html, re.DOTALL | re.IGNORECASE)
    if m:
        html = m.group(1)
    m = re.search(r"<html.*?>(.*)</html>", html, re.DOTALL | re.IGNORECASE)
    if m:
        html = m.group(1)
    html = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", html, flags=re.DOTALL)
    return html


def _mobi_to_epub(path, out_path):
    info = _mobi_raw_text(path)
    if not info:
        return None
    body = _html_to_body(info["html"])
    if not body.strip():
        return None
    title = info["title"] or "MOBI book"
    return _build_epub(out_path, title, "", [("body", title, body)])


# ── public entry point ─────────────────────────────────────────────────────

def render_to_epub(file_path, out_path, ext):
    """Convert file_path (as .fb2/.mobi/.azw3) to a temp .epub at out_path.

    Returns out_path on success, None on failure (or DRM/unsupported).
    """
    try:
        if not os.path.isfile(file_path):
            return None
        ext = (ext or os.path.splitext(file_path)[1]).lower()
        if ext == ".fb2":
            return _fb2_to_epub(file_path, out_path)
        elif ext in (".mobi", ".azw3", ".azw"):
            return _mobi_to_epub(file_path, out_path)
        return None
    except Exception:
        try:
            os.unlink(out_path)
        except Exception:
            pass
        return None