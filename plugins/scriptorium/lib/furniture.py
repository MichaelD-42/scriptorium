"""Shared page-furniture constants and helpers.

pdf-triage finds the furniture (repeated header/footer lines, page-frame
tables and drawings, repeated images) and writes it to
`triage.json["furniture"]`. extract-text, extract-images, `lib/figures.py`
and grade-output then remove or check it. All of them use the rules in this
module, so that they cannot drift apart.
"""

import copy
import json
import re

import paths

# The top and bottom fraction of the page height that counts as a furniture
# band (a header or footer zone).
FURNITURE_EDGE_BAND = 0.12

# Two tolerances, on purpose not the same value:
# - FRAME_GROUP_TOLERANCE: triage decides if two raw per-page bboxes are the
#   same frame occurrence.
# - FRAME_MATCH_TOLERANCE: a later stage matches a fresh bbox against a
#   triage entry. The entry is an average over all matched pages, so it can
#   be a little further from one page's raw bbox. That is why this one has
#   one more point of slack.
FRAME_GROUP_TOLERANCE = 2.0  # pt
FRAME_MATCH_TOLERANCE = 3.0  # pt

# A drawing is a `repeated_drawings` part (a piece of the page frame or title
# block) only when its rect repeats on at least this fraction of the body
# pages, and on at least triage's FRAME_MIN_PAGE_COUNT pages. Real frame parts
# sit on nearly every body page. A figure that recurs at one position on some
# pages (the same small diagram on 4 of 6 pages is 67%) stays below it, so it
# stays a figure. The other furniture lists keep their 50% in triage.py.
REPEATED_DRAWING_MIN_PAGE_FRACTION = 0.80

# The input formats whose image `caption` is only the printed caption the
# script extracts. Only these may use describe_image.py's no_visible_text
# flag; for pptx/docx/xlsx/html the agent writes --caption.
NO_VISIBLE_TEXT_FORMATS = frozenset({"pdf", "image"})

_EMPTY_FURNITURE = {
    "line_patterns": [],
    "frame_tables": [],
    "frame_drawings": [],
    "repeated_drawings": [],
    "image_xrefs": [],
}


def empty_furniture() -> dict:
    """A fresh no-op furniture record (a new copy on each call)."""
    return copy.deepcopy(_EMPTY_FURNITURE)


def mask_digits(text: str) -> str:
    """Every run of digits becomes one "#". The second step of
    `furniture_key`; compare furniture lines with that function, not this
    one."""
    return re.sub(r"\d+", "#", text)


def furniture_key(text: str) -> str:
    """The form in which every stage compares furniture lines (follow-up
    R6): all whitespace removed, then every run of digits made one "#".

    PyMuPDF can return one footer line in different shapes on different
    pages: letter-spaced ("1 0 ( 1 2 0 )"), compact ("100(120)"), or
    letter-spaced with one digit ("9 ( 1 2 0 )"). Masking the digits alone
    gives three patterns, and none may reach triage's page fraction. With
    the whitespace removed first, all three give "#(#)". Letter patterns
    change too ("Legal Owner" gives "LegalOwner"); that is safe because
    triage stores this key in `line_patterns[].masked`, and extract_text, the
    merge filter and the gates all compare with this same function."""
    return mask_digits(re.sub(r"\s+", "", text))


def is_digit_only_pattern(masked: str) -> bool:
    """A furniture key with no letters, e.g. "#" or "#/#" (a footer that is
    only the page number)."""
    return not re.search(r"[^\W\d_]", masked)


# Follow-up R10: a frame rect (`frame_drawings`, or a `repeated_drawings`
# rect that covers more than this fraction of the page) that repeats on at
# least REPEATED_DRAWING_MIN_PAGE_FRACTION of the body pages bounds the
# content area. Triage stores it as `furniture["content_rect"]`, and the
# bands become the page area outside it (see band_limits).
CONTENT_RECT_MIN_AREA_FRACTION = 0.60


def _center_inside(line_bbox, rect) -> bool:
    cx = (line_bbox[0] + line_bbox[2]) / 2
    cy = (line_bbox[1] + line_bbox[3]) / 2
    return rect[0] <= cx <= rect[2] and rect[1] <= cy <= rect[3]


def _is_inner_rect(rect, page_line_bboxes: dict[int, list] | None, body_page_count: int) -> bool:
    """Follow-up R13: True when, on more than half of the body pages, `rect`
    holds body text (a line whose center is inside it) AND text lies
    outside it (the title block). An outer page border holds the title
    block too, so it fails this test."""
    if not page_line_bboxes:
        return False
    qualifying = 0
    for lines in page_line_bboxes.values():
        inside = any(_center_inside(b, rect) for b in lines)
        outside = any(not _center_inside(b, rect) for b in lines)
        qualifying += inside and outside
    return qualifying / body_page_count > 0.5


def find_content_rect(
    frame_drawings: list[dict], repeated_drawings: list[dict], body_page_count: int,
    page_width: float, page_height: float,
    page_line_bboxes: dict[int, list] | None = None,
) -> list[float] | None:
    """Follow-up R10/R13: the INNER content rect for
    `furniture["content_rect"]`, or None. Candidates are the
    `frame_drawings` entries and the `repeated_drawings` rects that cover
    more than CONTENT_RECT_MIN_AREA_FRACTION of the page; each must repeat
    on at least REPEATED_DRAWING_MIN_PAGE_FRACTION of the `body_page_count`
    body pages, and must be an inner rect (`_is_inner_rect`, from
    `page_line_bboxes`: {body page number: [text line bbox, ...]}): body
    text inside it and text outside it on most body pages. Of several, the
    smallest (innermost) wins."""
    page_area = page_width * page_height
    if body_page_count <= 0 or page_area <= 0:
        return None

    def area(b) -> float:
        return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])

    candidates = [
        list(entry["bbox"])
        for entry in list(frame_drawings or []) + list(repeated_drawings or [])
        if area(entry["bbox"]) / page_area > CONTENT_RECT_MIN_AREA_FRACTION
        and entry.get("page_count", 0) / body_page_count >= REPEATED_DRAWING_MIN_PAGE_FRACTION
        and _is_inner_rect(entry["bbox"], page_line_bboxes, body_page_count)
    ]
    if not candidates:
        return None
    return min(candidates, key=area)


def content_rect(furniture: dict | None) -> list[float] | None:
    """`furniture["content_rect"]`, or None (no frame, or a triage.json that
    predates follow-up R10)."""
    rect = (furniture or {}).get("content_rect")
    return list(rect) if rect and len(rect) == 4 else None


def band_limits(page_height: float, rect: list[float] | None = None) -> tuple[float, float]:
    """Follow-up R10: `(top_limit, bottom_limit)` in points. A span is in the
    top band when it ends at or above `top_limit`, and in the bottom band
    when it starts at or below `bottom_limit`.

    With no content rect, the bands are the fixed FURNITURE_EDGE_BAND (12%)
    of the page height. With one (follow-up R13), they are exactly the page
    area outside it: above rect.y0 and below rect.y1, with no 12% minimum.
    `find_content_rect` only accepts an inner rect, never an outer page
    border. Every stage that tests the band (triage, extract_text, the merge
    filter, the gates, lib/figures.py's cluster band test) calls this
    function."""
    if rect and rect[3] <= page_height:
        return rect[1], rect[3]
    return FURNITURE_EDGE_BAND * page_height, (1 - FURNITURE_EDGE_BAND) * page_height


def furniture_edge(y0: float, y1: float, page_height: float, rect: list[float] | None = None) -> str | None:
    """ "top" when the span y0..y1 lies in the top band, "bottom" when it
    lies in the bottom band, else None. `rect` is the content rect
    (band_limits)."""
    if not page_height or page_height <= 0:
        return None
    top, bottom = band_limits(page_height, rect)
    if y1 <= top:
        return "top"
    if y0 >= bottom:
        return "bottom"
    return None


def in_furniture_band(bbox, page_height: float | None, rect: list[float] | None = None) -> bool:
    """True when `bbox` ([x0, y0, x1, y1]) lies in the top or bottom
    furniture band of the page (band_limits, with the content rect `rect`).
    False when the bbox or the page height is unknown."""
    if not page_height or page_height <= 0 or not bbox or len(bbox) != 4:
        return False
    return furniture_edge(bbox[1], bbox[3], page_height, rect) is not None


# Two furniture rules, on purpose not the same (follow-up R3):
# - extract_text (`furniture_filtered_lines`) removes a line only when its
#   BLOCK lies in the furniture band AND the line matches any pattern. It
#   has the exact text-layer geometry, so it can be strict: a body line that
#   happens to equal a title-block label is kept.
# - The merge-time filter for `ocr`/`vision` bodies (`lib/elements.py`) and
#   the `furniture_absent` gate both use `patterns_for_element` below: a
#   letter-bearing pattern matches ANYWHERE, a digit-only pattern only inside
#   the band. The merge filter must use the gate's rule, so that an escalated
#   page passes the gate; and an OCR or vision element often has no bbox, so
#   a band test alone could not remove its title block.
# Two effects follow. A digit-only footer line in an OCR or vision body (no
# bbox) is never removed, and the gate cannot flag it either, so the two
# stay consistent. A mid-page body line that equals a letter-bearing
# furniture line is removed on an `ocr`/`vision` page but kept on a `text`
# page.


def patterns_for_element(
    all_patterns: set[str], bbox, page_height: float | None, rect: list[float] | None = None
) -> set[str]:
    """The band plus pattern rule: the masked line patterns that may match
    one element's text.

    A letter-bearing pattern matches anywhere on the page. A digit-only
    pattern also matches any bare number in the body (a table cell "3", a
    quantity), so it applies only when the element's bbox lies in a
    furniture band of its page (band_limits, with the content rect
    `rect`). With no bbox or no page height, only the letter-bearing
    patterns apply."""
    letter_patterns = {m for m in all_patterns if not is_digit_only_pattern(m)}
    if letter_patterns != all_patterns and in_furniture_band(bbox, page_height, rect):
        return set(all_patterns)
    return letter_patterns


def furniture_line_hits(text: str, masked_patterns: set[str]) -> list[str]:
    """Every line of `text` (and the whole text) whose `furniture_key`
    equals a furniture pattern."""
    hits = []
    for candidate in [text] + text.splitlines():
        stripped = candidate.strip()
        if stripped and furniture_key(stripped) in masked_patterns and stripped not in hits:
            hits.append(stripped)
    return hits


def strip_furniture_lines(text: str, masked_patterns: set[str]) -> tuple[str, int]:
    """`text` without the lines whose `furniture_key` equals a furniture
    pattern, and the number of lines removed."""
    kept, removed = [], 0
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and furniture_key(stripped) in masked_patterns:
            removed += 1
        else:
            kept.append(line)
    if not removed:
        return text, 0
    return "\n".join(kept).strip(), removed


def pdf_page_heights(pdf_path) -> dict[int, float]:
    """{page_number: height in points} for a PDF, the geometry the band
    rule needs."""
    import fitz  # PyMuPDF

    with fitz.open(pdf_path) as doc:
        return {i: page.rect.height for i, page in enumerate(doc, start=1)}


def bbox_matches(a, b, tolerance: float = FRAME_MATCH_TOLERANCE) -> bool:
    """True when every coordinate of `a` is within `tolerance` of `b`."""
    a, b = list(a or []), list(b or [])
    return len(a) == 4 and len(b) == 4 and all(abs(x - y) <= tolerance for x, y in zip(a, b))


def matches_any_frame(bbox, frames: list[dict], tolerance: float = FRAME_MATCH_TOLERANCE) -> bool:
    """True when `bbox` matches the `bbox` of one entry of `frames` (a
    `frame_tables`, `frame_drawings` or `repeated_drawings` list)."""
    return any(bbox_matches(bbox, f["bbox"], tolerance) for f in frames or [])


def overlap_ratio(a, b) -> float:
    """The fraction of bbox a's area that bbox b covers."""
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    area_a = max(1e-6, (ax1 - ax0) * (ay1 - ay0))
    return inter / area_a


def _load_triage(doc: str) -> dict:
    triage_path = paths.triage_json(doc)
    if not triage_path.exists():
        return {}
    return json.loads(triage_path.read_text(encoding="utf-8"))


def load_furniture(doc: str) -> dict:
    """`triage.json["furniture"]`, or a no-op default when triage has not
    run for this document, predates furniture detection, or (like the
    non-PDF triage scripts) never writes the field. Every script must still
    work standalone."""
    furniture = _load_triage(doc).get("furniture")
    if not furniture:
        return empty_furniture()
    return furniture


def load_page_roles(doc: str) -> dict[int, str]:
    """{page_number: role} for every page triage marked with a role
    (currently only "toc"). Empty when triage has not run."""
    triage = _load_triage(doc)
    return {p["page_number"]: p["role"] for p in triage.get("pages", []) if p.get("role")}
