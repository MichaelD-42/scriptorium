"""Shared docx block-iteration and pagination helpers, used by both
docx-triage and docx-extract so segmentation can never drift between them.

Word's own pagination is layout-computed and invisible to python-docx —
there is no "page" concept in the file at all. This plugin's convention:
split on Heading-1 paragraphs (content before the first one is page 1's
front matter; a document with no Heading-1 at all is a single page).
triage.json records the result of split_pages() and is the single source
of truth for "how many pages does this docx have" — see paths.true_page_count.
"""

from docx.document import Document as _Document
from docx.oxml.ns import qn
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph


def iter_block_items(parent):
    """Yield each Paragraph/Table child of `parent` in document order.

    python-docx's own `.paragraphs` and `.tables` are separate flat lists
    with no interleaving order, so this walks the underlying XML body
    directly — the standard recipe for docx documents that mix prose and
    tables."""
    if isinstance(parent, _Document):
        parent_elm = parent.element.body
    elif isinstance(parent, _Cell):
        parent_elm = parent._tc
    else:
        raise ValueError(f"iter_block_items: unsupported parent type {type(parent)!r}")

    for child in parent_elm.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, parent)
        elif isinstance(child, CT_Tbl):
            yield Table(child, parent)


def heading_level(paragraph: Paragraph) -> int | None:
    """The paragraph's heading level (1-9), or None if it isn't a heading.
    "Title" style counts as level 1."""
    name = paragraph.style.name if paragraph.style else ""
    if name == "Title":
        return 1
    if name.startswith("Heading "):
        try:
            return int(name.rsplit(" ", 1)[1])
        except ValueError:
            return None
    return None


def split_pages(document: _Document) -> list[list]:
    """Split the document's block items into logical "pages": everything
    before the first Heading-1 is page 1 (front matter, if any); each
    Heading-1 paragraph after that starts a new page. No Heading-1
    anywhere -> the whole document is a single page."""
    blocks = list(iter_block_items(document))
    pages: list[list] = [[]]
    for block in blocks:
        if isinstance(block, Paragraph) and heading_level(block) == 1 and pages[-1]:
            pages.append([])
        pages[-1].append(block)
    non_empty = [p for p in pages if p]
    return non_empty or [[]]


def paragraph_images(paragraph: Paragraph, document: _Document) -> list:
    """Inline picture parts referenced by this paragraph's runs.

    python-docx has no per-paragraph inline-image API, so this walks each
    run's <w:drawing>//<a:blip> and resolves the relationship id against
    the document part to get the actual image part (bytes + extension)."""
    found = []
    for run in paragraph.runs:
        for blip in run._element.findall(".//" + qn("a:blip")):
            rId = blip.get(qn("r:embed"))
            if not rId:
                continue
            image_part = document.part.related_parts.get(rId)
            if image_part is not None:
                found.append(image_part)
    return found
