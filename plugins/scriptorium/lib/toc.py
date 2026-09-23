"""Table-of-contents detection and parsing (Task A3).

Two strategies, tried in order, against a `fitz.Document`:

  1. **PDF outline** (`document.get_toc()`) -- if the document carries a
     real outline/bookmark tree, use it directly. PyMuPDF's own
     `(level, title, page)` tuples map straight onto this module's entry
     shape; a leading `"<number> "` in `title` is split off into `number`
     when present, otherwise `number` is `None` (not omitted -- keeping the
     key present gives every entry the same shape regardless of which
     strategy produced it).
  2. **Printed TOC page detection** (fallback, when there is no outline):
     scan the first TOC_SEARCH_MAX_PAGES pages of the document for a
     contiguous run of pages with at least MIN_QUALIFYING_LINES lines that
     look like dot-leader TOC entries ("Title .......... 4"), then parse
     entries off of just those pages. Handles both "number and title on one
     line" and "number alone on one line, title+leader+page on the next"
     (PyMuPDF's line-grouping sometimes puts a printed TOC's number on its
     own line when it's right-aligned or otherwise laid out apart from the
     title). Both the line-count threshold and the front-of-document bound
     exist to keep a false positive here from being silent, gate-passing
     data loss -- see MIN_QUALIFYING_LINES's and TOC_SEARCH_MAX_PAGES's
     comments below.

`detect_toc(document)` is the main entry point: returns
`(entries, toc_pages)`, where `toc_pages` is the list of 1-indexed page
numbers identified as printed TOC pages (always `[]` when the outline path
was used, since outline entries don't correspond to any particular rendered
page). `get_toc(document)` is a thin convenience wrapper for callers that
only want the entries list.

`normalize_toc_text(text)` and `toc_entry_heading_text(entry)` (Task A4) are
the shared normalization this module's "does this printed text match this
TOC entry" comparisons use — currently just `extract_text.py`'s TOC-driven
heading classification, but kept here rather than duplicated in that script
so any future caller with the same need reuses it instead of inventing its
own.
"""

import re

# A page qualifies as a printed TOC page once it has at least this many
# lines matching DOT_LEADER_RE. This is the brief's original spec'd value.
#
# An earlier revision of this module calibrated this down to 3 to fit
# furniture_sample.pdf's then-5-line-per-page TOC. That was unsafe for
# production: a `role: "toc"` page's extraction is silently skipped
# (`skipped: "toc"`, zero elements) and `no_empty_pages` exempts it -- so a
# false positive here is silent, gate-passing data loss. A threshold of 3 is
# easily tripped by an ordinary dot-leader-aligned pricing/spec table (real
# RFQ documents contain exactly that shape), which would then vanish from
# the extracted output without any error. Fixed by extending the fixture's
# TOC pages to a more realistic >=15 dot-leader lines each (see
# examples/generate_furniture_fixture.py and task-A3-report.md's fix note)
# and raising this constant back to match, rather than lowering the
# production threshold to fit a small fixture.
MIN_QUALIFYING_LINES = 15

# "........ 4" -- three or more dots, optional whitespace, a trailing page
# number, optional trailing whitespace, end of line.
DOT_LEADER_RE = re.compile(r"\.{3,}\s*\d+\s*$")

# "<title> .......... <page>" -- same shape as DOT_LEADER_RE but capturing
# the title and page number separately.
TITLE_LEADER_PAGE_RE = re.compile(r"^(.*?)\s*\.{3,}\s*(\d+)\s*$")

# A bare section number on its own line, e.g. "2.1.1".
NUMBER_ONLY_RE = re.compile(r"^(\d+(?:\.\d+)*)$")

# A leading section number followed by the rest of the text, e.g.
# "1.2 Document Overview" -> ("1.2", "Document Overview").
NUMBER_PREFIX_RE = re.compile(r"^(\d+(?:\.\d+)*)\s+(.+)$")

# A TOC is always near the front of a document -- find_printed_toc_pages
# only scans this many pages from the start. Without a bound, a page deep in
# a long document whose lines coincidentally match DOT_LEADER_RE often
# enough (e.g. a dense pricing/spec table) could be accepted as a TOC page
# purely on pattern-matching the line count, regardless of MIN_QUALIFYING_LINES
# -- a real risk given `role: "toc"` pages are silently skipped by the
# extractors (see MIN_QUALIFYING_LINES's comment above). A fixed page count,
# rather than a fraction of the document's length, is used deliberately so
# the scan doesn't become more permissive just because the rest of the
# document happens to be long. 20 pages comfortably covers realistic front
# matter (a cover page, a short revision history, a multi-page TOC itself)
# for the RFQ-sized specification documents this toolkit targets.
TOC_SEARCH_MAX_PAGES = 20


def _level_from_number(number: str) -> int:
    """"1" -> 1, "1.2" -> 2, "1.2.3" -> 3, ... -- dot-depth, no hardcoded cap."""
    return number.count(".") + 1


def _split_leading_number(text: str) -> tuple[str | None, str]:
    match = NUMBER_PREFIX_RE.match(text.strip())
    if match:
        return match.group(1), match.group(2).strip()
    return None, text.strip()


def toc_from_outline(document) -> list[dict]:
    """`document.get_toc()` entries, mapped onto this module's shape. Empty
    list if the document has no outline."""
    entries = []
    for level, title, page in document.get_toc():
        number, clean_title = _split_leading_number(title)
        entries.append({"number": number, "title": clean_title, "page": page, "level": level})
    return entries


def _page_lines(page) -> list[str]:
    return [line.strip() for line in page.get_text("text").splitlines() if line.strip()]


def _qualifying_line_count(lines: list[str]) -> int:
    return sum(1 for line in lines if DOT_LEADER_RE.search(line))


def find_printed_toc_pages(document) -> list[int]:
    """The contiguous run of pages, scanning from the start of the document
    and bounded to the first TOC_SEARCH_MAX_PAGES pages, whose dot-leader
    line count meets MIN_QUALIFYING_LINES. Pages before the first qualifying
    page are skipped (a title/cover page); the run stops at the first page
    after that point that doesn't qualify -- a TOC is always near the front
    and contiguous, never resuming after a gap, and a qualifying-looking page
    outside the front-of-document bound is never treated as one."""
    toc_pages = []
    started = False
    search_limit = min(document.page_count, TOC_SEARCH_MAX_PAGES)
    for page_number in range(1, search_limit + 1):
        page = document[page_number - 1]
        qualifies = _qualifying_line_count(_page_lines(page)) >= MIN_QUALIFYING_LINES
        if qualifies:
            started = True
            toc_pages.append(page_number)
        elif started:
            break
    return toc_pages


def _parse_toc_page_lines(lines: list[str]) -> list[dict]:
    entries = []
    i = 0
    while i < len(lines):
        line = lines[i]

        full_match = TITLE_LEADER_PAGE_RE.match(line)
        if full_match:
            left, target_page = full_match.group(1).strip(), int(full_match.group(2))
            number, title = _split_leading_number(left)
            if number is not None:
                entries.append({"number": number, "title": title, "page": target_page, "level": _level_from_number(number)})
            i += 1
            continue

        number_match = NUMBER_ONLY_RE.match(line)
        if number_match and i + 1 < len(lines):
            next_match = TITLE_LEADER_PAGE_RE.match(lines[i + 1])
            if next_match:
                number = number_match.group(1)
                title, target_page = next_match.group(1).strip(), int(next_match.group(2))
                entries.append({"number": number, "title": title, "page": target_page, "level": _level_from_number(number)})
                i += 2
                continue

        i += 1
    return entries


def parse_printed_toc(document, toc_pages: list[int]) -> list[dict]:
    entries = []
    for page_number in toc_pages:
        entries.extend(_parse_toc_page_lines(_page_lines(document[page_number - 1])))
    return entries


def detect_toc(document) -> tuple[list[dict], list[int]]:
    """Returns `(entries, toc_pages)`. Tries the PDF outline first; falls
    back to printed-TOC-page detection only if the outline is empty.
    `toc_pages` is always `[]` for the outline path."""
    outline_entries = toc_from_outline(document)
    if outline_entries:
        return outline_entries, []

    toc_pages = find_printed_toc_pages(document)
    if not toc_pages:
        return [], []
    return parse_printed_toc(document, toc_pages), toc_pages


def get_toc(document) -> list[dict]:
    """Convenience wrapper for callers that only need the entries list."""
    entries, _toc_pages = detect_toc(document)
    return entries


# A run of whitespace and/or these punctuation marks at the end of a string
# -- ".", ":", ";", "," and both dash variants (hyphen, en dash, em dash),
# the marks a printed heading/TOC line is likely to trail with.
_TRAILING_PUNCT_RE = re.compile(r"[\s.:;,\-–—]+$")


def normalize_toc_text(text: str) -> str:
    """Case-fold, collapse internal whitespace to a single space, and strip
    trailing punctuation -- the one normalization every "does this printed
    text match this TOC entry" comparison in this codebase uses (Task A4's
    heading-classification match against toc.json). Picked once, here, so
    nothing duplicates it: a candidate heading block's own text and a TOC
    entry's "number + title" text (see `toc_entry_heading_text`) both go
    through this same function before being compared for equality."""
    collapsed = re.sub(r"\s+", " ", text.strip())
    return _TRAILING_PUNCT_RE.sub("", collapsed).casefold()


def toc_entry_heading_text(entry: dict) -> str:
    """The "number + title" text a TOC entry's matching body heading is
    expected to be printed as (see generate_furniture_fixture.py's
    `draw_heading`: `f"{number} {title}"`) -- `title` alone when the entry
    has no number (e.g. an outline entry with no leading number)."""
    number = entry.get("number")
    title = entry["title"]
    return f"{number} {title}" if number else title
