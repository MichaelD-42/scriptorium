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

# The input formats whose image `caption` is only the printed caption the
# script extracts. Only these may use describe_image.py's no_visible_text
# flag; for pptx/docx/xlsx/html the agent writes --caption.
NO_VISIBLE_TEXT_FORMATS = frozenset({"pdf", "image"})

_EMPTY_FURNITURE = {
    "line_patterns": [],
    "frame_tables": [],
    "frame_drawings": [],
    "image_xrefs": [],
}


def empty_furniture() -> dict:
    """A fresh no-op furniture record (a new copy on each call)."""
    return copy.deepcopy(_EMPTY_FURNITURE)


def mask_digits(text: str) -> str:
    """Every run of digits becomes one "#". Furniture line patterns are
    compared in this masked form, so "page 3 (9)" matches "page 4 (9)"."""
    return re.sub(r"\d+", "#", text)


def furniture_edge(y0: float, y1: float, page_height: float) -> str | None:
    """ "top" when the span y0..y1 lies in the top band, "bottom" when it
    lies in the bottom band, else None."""
    if not page_height or page_height <= 0:
        return None
    if y1 / page_height <= FURNITURE_EDGE_BAND:
        return "top"
    if y0 / page_height >= 1 - FURNITURE_EDGE_BAND:
        return "bottom"
    return None


def in_furniture_band(bbox, page_height: float | None) -> bool:
    """True when `bbox` ([x0, y0, x1, y1]) lies in the top or bottom
    furniture band of the page. False when the bbox or the page height is
    unknown."""
    if not page_height or page_height <= 0 or not bbox or len(bbox) != 4:
        return False
    return furniture_edge(bbox[1], bbox[3], page_height) is not None


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
    return json.loads(triage_path.read_text())


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
