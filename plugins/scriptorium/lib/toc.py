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
page). `detect_toc_with_unparsed(document)` returns the same plus
`unparsed`: every dot-leader line on a TOC page that gave no entry (fix
wave I2), so a lost entry is visible instead of silent. `get_toc(document)`
is a thin convenience wrapper for callers that only want the entries list.

Fix wave I2 also accepts a short last TOC page (see
CONTINUATION_MIN_QUALIFYING_LINES) and joins a title that wraps onto
further lines (see WRAP_MAX_LINES).

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

# Fix wave I2: the last page of a printed TOC often holds only a few
# entries. A page with fewer than MIN_QUALIFYING_LINES leader lines is
# still a TOC page when it directly follows a detected TOC page, has at
# least CONTINUATION_MIN_QUALIFYING_LINES leader lines, and its leader lines
# plus number-only lines are at least CONTINUATION_MIN_LINE_FRACTION of its
# non-empty lines. The first TOC page still needs MIN_QUALIFYING_LINES, so
# the A3 guard against a dot-leader pricing table starting a TOC is kept.
CONTINUATION_MIN_QUALIFYING_LINES = 3
CONTINUATION_MIN_LINE_FRACTION = 0.30

# Fix wave I2: a TOC title can wrap. After a number-only line, or a numbered
# title line with no leader, up to this many further lines without a leader
# are joined to the title, until a leader line closes the entry.
WRAP_MAX_LINES = 3


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


def _is_continuation_page(lines: list[str], qualifying: int) -> bool:
    """See CONTINUATION_MIN_QUALIFYING_LINES. Only called for the page
    directly after a detected TOC page."""
    if qualifying < CONTINUATION_MIN_QUALIFYING_LINES or not lines:
        return False
    number_only = sum(1 for line in lines if NUMBER_ONLY_RE.match(line))
    return (qualifying + number_only) / len(lines) >= CONTINUATION_MIN_LINE_FRACTION


def find_printed_toc_pages(document) -> list[int]:
    """The contiguous run of pages, scanning from the start of the document
    and bounded to the first TOC_SEARCH_MAX_PAGES pages, whose dot-leader
    line count meets MIN_QUALIFYING_LINES. Pages before the first qualifying
    page are skipped (a title/cover page); the run stops at the first page
    after that point that doesn't qualify -- a TOC is always near the front
    and contiguous, never resuming after a gap, and a qualifying-looking page
    outside the front-of-document bound is never treated as one. Once the
    run has started, a page directly after a TOC page also qualifies as a
    continuation page (fix wave I2, see CONTINUATION_MIN_QUALIFYING_LINES)."""
    toc_pages = []
    started = False
    search_limit = min(document.page_count, TOC_SEARCH_MAX_PAGES)
    for page_number in range(1, search_limit + 1):
        page = document[page_number - 1]
        lines = _page_lines(page)
        qualifying = _qualifying_line_count(lines)
        if qualifying >= MIN_QUALIFYING_LINES:
            started = True
            toc_pages.append(page_number)
        elif started and _is_continuation_page(lines, qualifying):
            toc_pages.append(page_number)
        elif started:
            break
    return toc_pages


def _entry(number: str, title: str, target_page: int) -> dict:
    return {"number": number, "title": title, "page": target_page, "level": _level_from_number(number)}


def _starts_entry(line: str) -> bool:
    """True when `line` opens a TOC entry of its own: a bare number, or a
    numbered title (with or without a leader)."""
    return bool(NUMBER_ONLY_RE.match(line) or NUMBER_PREFIX_RE.match(line))


def _close_wrapped_entry(lines: list[str], i: int, number: str, title_parts: list[str]) -> tuple[dict, int] | None:
    """Fix wave I2: the entry that `lines[i]` opens (a number-only line, or
    a numbered title with no leader), closed by a leader line within the
    next WRAP_MAX_LINES + 1 lines. Lines in between must have no leader and
    must not open an entry of their own; they are joined to the title. The
    closing leader line must not carry its own number. Returns
    `(entry, next_index)`, or None when no leader line closes the entry."""
    parts = list(title_parts)
    j = i + 1
    while j < len(lines) and j - i <= WRAP_MAX_LINES + 1:
        line = lines[j]
        leader = TITLE_LEADER_PAGE_RE.match(line)
        if leader:
            left = leader.group(1).strip()
            if _split_leading_number(left)[0] is not None:
                return None  # the next entry, not this one's closing line
            parts.append(left)
            title = " ".join(p for p in parts if p)
            return _entry(number, title, int(leader.group(2))), j + 1
        if _starts_entry(line) or j - i > WRAP_MAX_LINES:
            return None
        parts.append(line.strip())
        j += 1
    return None


def parse_toc_page_lines(lines: list[str]) -> tuple[list[dict], list[str]]:
    """`(entries, unparsed)` for one printed TOC page's lines. An entry is
    one of:
    - a numbered title with a leader on one line ("1 Introduction .... 4");
    - a number-only line, then the title with the leader ("2" / "Scope ....
      5"), with up to WRAP_MAX_LINES wrapped title lines in between;
    - a numbered title with no leader, then up to WRAP_MAX_LINES further
      wrapped lines and the line with the leader.
    `unparsed` (fix wave I2) is every dot-leader line that gave no entry,
    verbatim -- for example a leader line with no section number."""
    entries: list[dict] = []
    unparsed: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]

        full_match = TITLE_LEADER_PAGE_RE.match(line)
        if full_match:
            left, target_page = full_match.group(1).strip(), int(full_match.group(2))
            number, title = _split_leading_number(left)
            if number is not None:
                entries.append(_entry(number, title, target_page))
            else:
                unparsed.append(line)
            i += 1
            continue

        number_match = NUMBER_ONLY_RE.match(line)
        prefix_match = None if number_match else NUMBER_PREFIX_RE.match(line)
        if number_match or prefix_match:
            if number_match:
                closed = _close_wrapped_entry(lines, i, number_match.group(1), [])
            else:
                closed = _close_wrapped_entry(lines, i, prefix_match.group(1), [prefix_match.group(2).strip()])
            if closed is not None:
                entry, i = closed
                entries.append(entry)
                continue

        i += 1
    return entries, unparsed


def _parse_toc_page_lines(lines: list[str]) -> list[dict]:
    """The entries half of `parse_toc_page_lines`."""
    entries, _unparsed = parse_toc_page_lines(lines)
    return entries


def parse_printed_toc_with_unparsed(document, toc_pages: list[int]) -> tuple[list[dict], list[str]]:
    entries: list[dict] = []
    unparsed: list[str] = []
    for page_number in toc_pages:
        page_entries, page_unparsed = parse_toc_page_lines(_page_lines(document[page_number - 1]))
        entries.extend(page_entries)
        unparsed.extend(page_unparsed)
    return entries, unparsed


def parse_printed_toc(document, toc_pages: list[int]) -> list[dict]:
    entries, _unparsed = parse_printed_toc_with_unparsed(document, toc_pages)
    return entries


def detect_toc_with_unparsed(document) -> tuple[list[dict], list[int], list[str]]:
    """Returns `(entries, toc_pages, unparsed)`. Tries the PDF outline
    first; falls back to printed-TOC-page detection only if the outline is
    empty. `toc_pages` and `unparsed` are always `[]` for the outline
    path."""
    outline_entries = toc_from_outline(document)
    if outline_entries:
        return outline_entries, [], []

    toc_pages = find_printed_toc_pages(document)
    if not toc_pages:
        return [], [], []
    entries, unparsed = parse_printed_toc_with_unparsed(document, toc_pages)
    return entries, toc_pages, unparsed


def detect_toc(document) -> tuple[list[dict], list[int]]:
    """Returns `(entries, toc_pages)`: `detect_toc_with_unparsed` without
    the unparsed lines."""
    entries, toc_pages, _unparsed = detect_toc_with_unparsed(document)
    return entries, toc_pages


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
