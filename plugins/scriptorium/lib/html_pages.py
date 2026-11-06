"""Shared HTML block-iteration and image-resolution helpers, used by
html-triage, html-extract, and text_mode_grade.py so their view of a
document's content can never drift between triage/extraction and grading.

HTML has no page concept at all (worse than docx, which at least has
Heading-1 sections to split on) — this plugin's convention: **the whole
file is one page**. There is no `split_pages()` here the way there is in
`docx_pages.py`; `triage.json`'s `page_count` is always 1.
"""

import base64
import mimetypes
from pathlib import Path
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup
from PIL import Image
from bs4.element import NavigableString, Tag

BLOCK_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "table", "pre", "blockquote", "li"}
SKIP_TAGS = {"script", "style", "head", "template"}


def parse(html_path: Path) -> BeautifulSoup:
    soup = BeautifulSoup(html_path.read_text(encoding="utf-8", errors="replace"), "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")  # a line break separates words; block_text turns it into a space
    return soup


def _texts(tag: Tag) -> list[str]:
    """Every text node under `tag` outside SKIP_TAGS, comments left out."""
    return [
        s for s in tag.find_all(string=True)
        if type(s) is NavigableString and not any(p.name in SKIP_TAGS for p in s.parents)
    ]


def block_text(tag: Tag) -> str:
    """A tag's text with its whitespace collapsed. get_text(strip=True)
    would glue "Hello <b>world</b>" into "Helloworld"."""
    return " ".join("".join(_texts(tag)).split())


def iter_block_items(root: Tag):
    """Yield block-level tags (see BLOCK_TAGS) in document order. Does not
    recurse into a yielded block (its own get_text() already covers nested
    inline content); does recurse into plain containers so blocks nested
    inside divs/sections/lists are still found. A container with text of
    its own and no block inside (`<div>Notice</div>`) is yielded as a block
    too. `<img>` is not a block tag here — images are collected
    independently via saveable_images(), mirroring the pipeline's separate
    body-shard/image-shard split."""
    for child in root.find_all(recursive=False):
        if not isinstance(child, Tag) or child.name in SKIP_TAGS:
            continue
        own_text = any(type(c) is NavigableString and c.strip() for c in child.children)
        if child.name in BLOCK_TAGS or (own_text and not child.find(BLOCK_TAGS)):
            yield child
        else:
            # shortcut: text beside a block in one container (<div>Intro <p>..</p></div>) is skipped; text_mode_grade's coverage check reports it as dropped_text.
            yield from iter_block_items(child)


def visible_text(soup: BeautifulSoup) -> str:
    """The document's whole text, read without iter_block_items, for the
    grader's coverage check. Text nodes are space-joined: two blocks' words
    never glue, at the cost of splitting a word cut by inline markup."""
    return " ".join(" ".join(_texts(soup)).split())


def heading_level(tag: Tag) -> int | None:
    if tag.name and len(tag.name) == 2 and tag.name[0] == "h" and tag.name[1].isdigit():
        return int(tag.name[1])
    return None


def table_rows(table: Tag) -> list[list[str]]:
    rows = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["td", "th"], recursive=False)
        rows.append([block_text(cell) for cell in cells])
    return rows


def _ext_from_mime(mime: str) -> str:
    ext = mimetypes.guess_extension(mime) or ".png"
    return ext.lstrip(".")


def _is_image(path: Path) -> bool:
    try:
        with Image.open(path) as img:
            img.verify()
        return True
    except Exception:  # UnidentifiedImageError, truncated or not an image at all
        return False


def saveable_images(soup: BeautifulSoup, base_dir: Path) -> list[tuple[bytes, str]]:
    """(bytes, ext) for every <img> whose src is a data: URI or a local
    file (relative to base_dir, or an absolute local path), in document
    order. Remote (http(s):// or protocol-relative //) sources are skipped
    — an offline, deterministic gap, documented like xlsx's missing charts."""
    found = []
    for img in soup.find_all("img"):
        src = (img.get("src") or "").strip()
        if not src:
            continue
        if src.startswith("data:"):
            header, _, data = src.partition(",")
            if ";base64" not in header:
                continue
            mime = header[len("data:"):].split(";")[0] or "image/png"
            try:
                found.append((base64.b64decode(data), _ext_from_mime(mime)))
            except (ValueError, base64.binascii.Error):
                continue
            continue

        parsed = urlsplit(src)
        if parsed.scheme in ("http", "https") or src.startswith("//"):
            continue  # remote — not fetched, see module docstring

        local_path = Path(unquote(parsed.path))
        if not local_path.is_absolute():
            local_path = base_dir / local_path
        # Untrusted input: only image files inside the HTML file's own folder.
        if local_path.is_file() and local_path.resolve().is_relative_to(base_dir.resolve()) and _is_image(local_path):
            found.append((local_path.read_bytes(), local_path.suffix.lstrip(".") or "png"))

    return found
