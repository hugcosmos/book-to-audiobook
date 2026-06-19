"""Minimal EPUB reader using zipfile + lxml.

Replaces ebooklib to avoid AGPL-3.0 dependency.
Supports EPUB 2 (toc.ncx) and EPUB 3 (nav.xhtml).
"""
from __future__ import annotations

import os
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from lxml import etree

# XML namespaces
_NS_CONTAINER = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
_NS_OPF = {"opf": "http://www.idpf.org/2007/opf"}
_NS_DC = {"dc": "http://purl.org/dc/elements/1.1/"}
_NS_NCX = {"ncx": "http://www.daisy.org/z3986/2005/ncx/"}
_NS_XHTML = {"x": "http://www.w3.org/1999/xhtml"}

# EPUB media types
XHTML_TYPES = {"application/xhtml+xml", "text/html"}
IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/svg+xml"}


@dataclass
class EpubItem:
    """An item from the EPUB manifest."""
    id: str
    href: str  # relative to OPF directory
    media_type: str
    properties: str = ""
    _zip: zipfile.ZipFile = field(repr=False, default=None)
    _opf_dir: str = field(repr=False, default="")
    _cached_content: bytes | None = field(repr=False, default=None)

    @property
    def zip_path(self) -> str:
        """Full path inside the ZIP archive."""
        if self._opf_dir:
            return f"{self._opf_dir}/{self.href}"
        return self.href

    @property
    def is_document(self) -> bool:
        return self.media_type in XHTML_TYPES

    @property
    def is_image(self) -> bool:
        return self.media_type.startswith("image/")

    def get_content(self) -> bytes:
        # Return cached bytes if the zip has been closed (content pre-extracted
        # in read_epub). Otherwise read lazily from the still-open zip.
        if self._cached_content is not None:
            return self._cached_content
        return self._zip.read(self.zip_path)

    def get_name(self) -> str:
        return self.href

    def get_id(self) -> str:
        return self.id

    def get_type_name(self) -> str:
        if self.is_document:
            return "document"
        if self.is_image:
            return "image"
        return "other"


@dataclass
class TocEntry:
    """A single TOC entry."""
    title: str
    href: str  # src from NCX/nav, may contain #fragment


@dataclass
class EpubBook:
    """Parsed EPUB book — replaces ebooklib.epub.EpubBook."""
    spine: list[EpubItem] = field(default_factory=list)
    toc: list[TocEntry] = field(default_factory=list)
    manifest: dict[str, EpubItem] = field(default_factory=dict)
    metadata: dict[str, list[str]] = field(default_factory=dict)
    _zip: zipfile.ZipFile | None = field(repr=False, default=None)

    def get_item_with_id(self, item_id: str) -> EpubItem | None:
        return self.manifest.get(item_id)

    def get_items(self) -> list[EpubItem]:
        return list(self.manifest.values())

    def get_metadata(self, ns: str, tag: str) -> list[tuple[str, dict]]:
        key = f"{ns}:{tag}"
        values = self.metadata.get(key, [])
        return [(v, {}) for v in values]


def read_epub(path: str | Path) -> EpubBook:
    """Parse an EPUB file and return an EpubBook.

    Opens the zip with a context manager and pre-extracts every manifest
    item's content into the item's cache before closing, so the returned
    EpubBook holds no open file descriptor. This avoids leaking a ZipFile FD
    on every parse (get_chapter_text re-parses on demand, which over a long
    session could exhaust the FD limit).
    """
    with zipfile.ZipFile(str(path)) as zf:
        book = EpubBook(_zip=zf)

        # 1. Find OPF path from container.xml
        container_xml = zf.read("META-INF/container.xml")
        container = etree.fromstring(container_xml)
        opf_path = container.find(".//c:rootfile", _NS_CONTAINER).get("full-path")
        opf_dir = os.path.dirname(opf_path)

        # 2. Parse content.opf
        opf_xml = zf.read(opf_path)
        opf = etree.fromstring(opf_xml)

        # 2a. Metadata
        for elem in opf.iter("{%s}creator" % _NS_DC["dc"]):
            _add_meta(book, "DC", "creator", elem.text or "")
        for elem in opf.iter("{%s}title" % _NS_DC["dc"]):
            _add_meta(book, "DC", "title", elem.text or "")
        for elem in opf.iter("{%s}author" % _NS_DC["dc"]):
            _add_meta(book, "DC", "author", elem.text or "")

        # 2b. Manifest → items
        for item_elem in opf.iter("{%s}item" % _NS_OPF["opf"]):
            item = EpubItem(
                id=item_elem.get("id", ""),
                href=item_elem.get("href", ""),
                media_type=item_elem.get("media-type", ""),
                properties=item_elem.get("properties", ""),
                _zip=zf,
                _opf_dir=opf_dir,
            )
            book.manifest[item.id] = item

        # 2c. Spine → ordered items
        for itemref in opf.iter("{%s}itemref" % _NS_OPF["opf"]):
            idref = itemref.get("idref", "")
            item = book.manifest.get(idref)
            if item:
                book.spine.append(item)

        # 3. Parse TOC
        _parse_toc(book, zf, opf, opf_dir)

        # 4. Pre-extract all item contents into memory, so we can close the zip.
        #    EPUBs are typically a few MB; this trades a little RAM for not
        #    leaking file descriptors and not re-decompressing on repeated reads.
        for item in book.manifest.values():
            try:
                item._cached_content = zf.read(item.zip_path)
            except KeyError:
                # Some manifest entries (e.g. #anchor-only hrefs) have no real
                # zip entry; leave them uncached and let get_content() handle it.
                item._cached_content = b""

        return book


def _add_meta(book: EpubBook, ns: str, tag: str, value: str) -> None:
    key = f"{ns}:{tag}"
    book.metadata.setdefault(key, []).append(value)


def _parse_toc(book: EpubBook, zf: zipfile.ZipFile, opf: etree._Element, opf_dir: str) -> None:
    """Parse TOC from toc.ncx (EPUB2) or nav.xhtml (EPUB3)."""
    # Try NCX first (EPUB2)
    spine_elem = opf.find("{%s}spine" % _NS_OPF["opf"])
    ncx_id = spine_elem.get("toc", "") if spine_elem is not None else ""
    if ncx_id:
        ncx_item = book.manifest.get(ncx_id)
        if ncx_item:
            try:
                ncx_xml = zf.read(ncx_item.zip_path)
                _parse_ncx(book, ncx_xml)
                return
            except Exception:
                pass

    # Try EPUB3 nav
    for item in book.manifest.values():
        if "nav" in item.properties:
            try:
                nav_xml = zf.read(item.zip_path)
                _parse_nav(book, nav_xml)
                return
            except Exception:
                pass


def _parse_ncx(book: EpubBook, ncx_xml: bytes) -> None:
    """Parse toc.ncx navMap → flat list of top-level navPoints."""
    ncx = etree.fromstring(ncx_xml)
    nav_map = ncx.find("{%s}navMap" % _NS_NCX["ncx"])
    if nav_map is None:
        return
    for nav_point in nav_map.findall("{%s}navPoint" % _NS_NCX["ncx"]):
        label_el = nav_point.find(".//{%s}text" % _NS_NCX["ncx"])
        content_el = nav_point.find("{%s}content" % _NS_NCX["ncx"])
        if label_el is not None and content_el is not None:
            title = (label_el.text or "").strip()
            href = content_el.get("src", "")
            if title:
                book.toc.append(TocEntry(title=title, href=href))


def _parse_nav(book: EpubBook, nav_xml: bytes) -> None:
    """Parse EPUB3 nav.xhtml → flat list of top-level toc entries.

    Only direct-child ``<li>`` of the toc ``<nav>``'s ``<ol>`` are used, so that
    nested landmark / page-list navs (Cover, Copyright, page numbers) are not
    mistaken for chapter titles. The first ``<a>`` of each top-level li is the
    chapter link; nested sub-chapters under that li are intentionally flattened
    by recursing one level.
    """
    doc = etree.fromstring(nav_xml)
    # Find <nav epub:type="toc">
    toc_nav = None
    for nav in doc.iter("{%s}nav" % _NS_XHTML["x"]):
        if nav.get("{http://www.idpf.org/2007/ops}type") == "toc":
            toc_nav = nav
            break
    if toc_nav is None:
        # Fallback: first <nav> — but only if it has an <ol> (skip pure
        # landmark/page-list navs which use <ol hidden> or no <ol>).
        for nav in doc.iter("{%s}nav" % _NS_XHTML["x"]):
            if nav.find(".//{%s}ol" % _NS_XHTML["x"]) is not None:
                toc_nav = nav
                break
    if toc_nav is None:
        return

    xhtml = _NS_XHTML["x"]

    def _collect_entries(ol_element, depth=0):
        # Only direct-child <li> of this <ol>; recursion handles nested <ol>
        # inside an <li> (sub-chapters), but we cap depth to avoid runaway.
        if depth > 3:
            return
        for li in ol_element.iterfind("x:li", _NS_XHTML):
            a = li.find("x:a", _NS_XHTML)
            if a is not None:
                title = (a.text or "").strip()
                href = a.get("href", "")
                if title and href:
                    book.toc.append(TocEntry(title=title, href=href))
            nested_ol = li.find("x:ol", _NS_XHTML)
            if nested_ol is not None:
                _collect_entries(nested_ol, depth + 1)

    top_ol = toc_nav.find("x:ol", _NS_XHTML)
    if top_ol is None:
        # Some navs wrap the ol differently; fall back to first descendant ol.
        top_ol = toc_nav.find(".//x:ol", _NS_XHTML)
    if top_ol is not None:
        _collect_entries(top_ol)
