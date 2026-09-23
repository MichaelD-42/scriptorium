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
     scan pages from the front of the document for a contiguous run of
     pages whose lines mostly look like dot-leader TOC entries
     ("Title .......... 4"), then parse entries off of just those pages.
     Handles both "number and title on one line" and "number alone on one
     line, title+leader+page on the next" (PyMuPDF's line-grouping
     sometimes puts a printed TOC's number on its own line when it's
     right-aligned or otherwise laid out apart from the title).

`detect_toc(document)` is the main entry point: returns
`(entries, toc_pages)`, where `toc_pages` is the list of 1-indexed page
numbers identified as printed TOC pages (always `[]` when the outline path
was used, since outline entries don't correspond to any particular rendered
page). `get_toc(document)` is a thin convenience wrapper for callers that
only want the entries list.
"""

import re

# A page qualifies as a printed TOC page once it has at least this many
# lines matching DOT_LEADER_RE. The brief's suggested default (15) is sized
# for a dense, real-world TOC; this repo's synthetic fixture
# (furniture_sample.pdf) deliberately keeps its two TOC pages small (5
# dot-leader-bearing lines each) to stay a quick, hand-checkable fixture, so
# 15 would never fire here. Calibrated down to comfortably clear the
# fixture's 5-per-page while still requiring more than one or two stray
# matches elsewhere in a document (see task-A3-report.md).
MIN_QUALIFYING_LINES = 3

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
    """The contiguous run of pages, scanning from the start of the document,
    whose dot-leader line count meets MIN_QUALIFYING_LINES. Pages before the
    first qualifying page are skipped (a title/cover page); the run stops at
    the first page after that point that doesn't qualify -- a TOC is always
    near the front and contiguous, never resuming after a gap."""
    toc_pages = []
    started = False
    for page_number, page in enumerate(document, start=1):
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
