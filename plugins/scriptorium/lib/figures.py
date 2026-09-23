"""Shared figure-region detection (Task A5).

`extract_images.py` and `extract_text.py` both need to agree on where a
page's vector-graphic figure regions are: the former crop-renders each
region to a PNG asset, the latter must exclude each region's text-layer
lines from paragraph/heading extraction and instead fold them into the
matching image element's `figure_text`. This lives here, not in either
script, because the two run as independent -- and possibly parallel --
subagent batches over the same document (see `commands/extract.md`), so
neither script can wait on the other's shard to exist first. Calling the
same functions from both scripts is what keeps their answers consistent.

Detection pipeline, per page:

1. `page.get_drawings()` lists every vector-graphic item on the page. A
   single item covering more than `LARGE_DRAWING_AREA_FRACTION` of the page
   (the same "this is basically the whole page" threshold `pdf-triage` uses
   for its own `FRAME_TABLE_MIN_AREA_FRACTION`) is dropped *before*
   clustering. This matters more than it looks: left in, a full-page-frame
   border (a single stroked rectangle drawn near the page edges, which this
   plugin's own `furniture_sample.pdf` fixture has on every page) makes
   `page.cluster_drawings()` merge *every other drawing on the page* into
   one page-spanning cluster, because the border's bbox geometrically
   contains everything drawn inside it and `cluster_drawings()` joins
   overlapping items transitively. Confirmed empirically against the
   fixture: with the border left in, every page collapses to a single
   cluster exactly matching the border's own bbox; filtering it out first,
   the real diagram/chart/table clusters resolve correctly and separately.
2. `page.cluster_drawings()` on what is left groups the remaining vector
   items into candidate regions, then each candidate bbox is padded by
   `REGION_PADDING` points on every side (clamped to the page). Padding
   exists because `cluster_drawings()` only ever looks at vector *drawing*
   items -- axis-label text sitting just below a bar chart's bars, e.g., is
   a few points outside the drawings-only bbox, and would otherwise be
   excluded from both the crop-render (a chart image with its labels cut
   off) and `figure_text` (missing the labels entirely).
3. Each padded candidate is dropped if it:
   - overlaps the top/bottom furniture edge band (reuses the same
     `FURNITURE_EDGE_BAND` convention `extract_text.py`'s
     `in_furniture_band`/`furniture_filtered_lines` use, but as an
     *overlap* test rather than a containment test -- see
     `_overlaps_furniture_edge_band`'s docstring for why that distinction
     matters here);
   - overlaps a real (non-frame) table's bbox, queried fresh via
     `pdfplumber` and filtered the same way `extract_text.py`'s
     `is_frame_table()` filters `frame_tables` out of its own table query;
   - or is "tiny" -- smaller than `MIN_CLUSTER_AREA_FRACTION` of the page
     area, almost certainly a stray rule/line rather than a real figure.
"""

from pathlib import Path

import pdfplumber

# Independent copies of constants that already exist, under the same name,
# in triage.py/extract_text.py/extract_images.py -- matching this codebase's
# existing convention (see e.g. extract_images.py's own FRAME_TABLE_BBOX_TOLERANCE
# docstring) of small per-file constant duplication over cross-script imports.
FURNITURE_EDGE_BAND = 0.12
FRAME_TABLE_BBOX_TOLERANCE = 3.0  # pt
LARGE_DRAWING_AREA_FRACTION = 0.6  # matches triage.py's FRAME_TABLE_MIN_AREA_FRACTION

# A single candidate region's raw vector-drawings bbox, padded this many
# points on every side before it's used for either the crop-render or the
# figure_text text-overlap query. See module docstring step 2.
REGION_PADDING = 10.0

# A cluster smaller than this fraction of the page area is treated as stray
# line-art (a short rule, an underline) rather than a real figure. A judgment
# call, not a derived constant -- a later step's document census (a later,
# non-code step) is expected to tune this against the real golden document;
# 1% gives a reasonable ballpark against this repo's fixtures today (the
# smallest real figure region here, furniture_sample.pdf's bar chart, is
# ~4.5% of its page; a single short stray line is two to three orders of
# magnitude smaller).
MIN_CLUSTER_AREA_FRACTION = 0.01

# Overlap-ratio thresholds (see _overlap_ratio) for "this candidate region
# is basically on top of a real table" and "this text line is basically
# inside a figure region" respectively. Not the same value on purpose: a
# region/table pairing that's this codebase's existing >0.5 convention
# (extract_text.py's own table-overlap block-drop) is kept for lines: a text
# line either belongs to the figure or it doesn't, so a straightforward
# majority-overlap test is right. Table-vs-region overlap uses a lower bar
# (0.3) because a real table's grid-line drawings often cluster into a
# region bbox noticeably larger or smaller than pdfplumber's own detected
# table bbox (rounding/stroke-width differences), so demanding >50% overlap
# risked under-excluding a table that should never become a figure.
TABLE_OVERLAP_THRESHOLD = 0.3
LINE_OVERLAP_THRESHOLD = 0.5


def _is_frame_table_bbox(bbox, frame_tables: list[dict]) -> bool:
    """Independent copy of extract_text.py's/extract_images.py's
    is_frame_table -- same tolerance-based bbox match against
    triage.json["furniture"]["frame_tables"]."""
    return any(
        all(abs(a - b) <= FRAME_TABLE_BBOX_TOLERANCE for a, b in zip(bbox, ft["bbox"]))
        for ft in frame_tables
    )


def real_table_bboxes(pdf_path: Path, page_number: int, frame_tables: list[dict] | None = None) -> list[list[float]]:
    """Real (non-frame) table bboxes on this page, queried fresh via
    pdfplumber -- not read from any shard, on purpose: extract_images.py and
    extract_text.py may run in either order, or in parallel, for the same
    page (see module docstring), so neither script can assume the other's
    shard already exists."""
    frame_tables = frame_tables or []
    with pdfplumber.open(pdf_path) as pl_doc:
        tables = pl_doc.pages[page_number - 1].find_tables()
        return [list(t.bbox) for t in tables if not _is_frame_table_bbox(t.bbox, frame_tables)]


def _overlaps_furniture_edge_band(bbox, page_height: float) -> bool:
    """True if any part of `bbox` falls within the top or bottom
    FURNITURE_EDGE_BAND of the page.

    Deliberately a broader *overlap* test than extract_text.py's
    in_furniture_band(), which requires a whole (small) text block to sit
    fully inside one band -- correct for a single line of running-header
    text, but a region-sized cluster (most notably a page-frame border,
    before step 1 above filters it out of the *drawings* pool it would
    otherwise dominate) can span from one edge band to the other without
    ever being fully inside either one. Requiring only overlap is what
    actually excludes anything region-sized that starts or ends in
    furniture territory."""
    if page_height <= 0:
        return False
    return bbox[1] / page_height < FURNITURE_EDGE_BAND or bbox[3] / page_height > 1 - FURNITURE_EDGE_BAND


def _overlap_ratio(a, b) -> float:
    """Fraction of bbox a's area covered by bbox b (same shape as
    extract_text.py's bbox_overlap_ratio, duplicated here for the same
    "these scripts/modules don't share code today" reason as the other
    small helpers above -- this one is used with two different thresholds
    by two different callers in this module, so it's kept local)."""
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    area_a = max(1e-6, (ax1 - ax0) * (ay1 - ay0))
    return inter / area_a


def _overlaps_any_table(bbox, table_bboxes: list[list[float]]) -> bool:
    return any(
        _overlap_ratio(bbox, t) > TABLE_OVERLAP_THRESHOLD or _overlap_ratio(t, bbox) > TABLE_OVERLAP_THRESHOLD
        for t in table_bboxes
    )


def line_in_region(line_bbox, region_bbox, threshold: float = LINE_OVERLAP_THRESHOLD) -> bool:
    """True if `line_bbox` (a text line's own bbox) is majority-inside
    `region_bbox` -- the single overlap test both extract_text.py (to drop
    the line from paragraph/heading extraction) and this module's own
    region_text_lines() (to collect it into figure_text) use, so the two
    scripts' answers can never drift apart from each other."""
    return _overlap_ratio(line_bbox, region_bbox) > threshold


def detect_figure_regions(page, page_number: int, pdf_path: Path, frame_tables: list[dict] | None = None) -> list[dict]:
    """Candidate figure regions for one page: `[{"bbox": [x0, y0, x1, y1]},
    ...]`, sorted top-to-bottom by bbox y0. Empty if the page has no
    qualifying vector-graphic region. See the module docstring for the full
    pipeline."""
    frame_tables = frame_tables or []
    page_width, page_height = page.rect.width, page.rect.height
    page_area = page_width * page_height
    if page_area <= 0:
        return []

    drawings = page.get_drawings()
    significant = [
        d for d in drawings
        if (d["rect"].width * d["rect"].height) / page_area <= LARGE_DRAWING_AREA_FRACTION
    ]
    if not significant:
        return []

    clusters = page.cluster_drawings(drawings=significant)
    table_bboxes = real_table_bboxes(pdf_path, page_number, frame_tables)

    regions = []
    for rect in clusters:
        bbox = [
            max(0.0, rect.x0 - REGION_PADDING),
            max(0.0, rect.y0 - REGION_PADDING),
            min(page_width, rect.x1 + REGION_PADDING),
            min(page_height, rect.y1 + REGION_PADDING),
        ]
        area = max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])
        if area / page_area < MIN_CLUSTER_AREA_FRACTION:
            continue
        if _overlaps_furniture_edge_band(bbox, page_height):
            continue
        if _overlaps_any_table(bbox, table_bboxes):
            continue
        regions.append({"bbox": bbox})

    regions.sort(key=lambda r: r["bbox"][1])
    return regions


def region_text_lines(page, region_bbox, threshold: float = LINE_OVERLAP_THRESHOLD) -> list[dict]:
    """Text-layer lines on `page` whose own bbox is majority-inside
    `region_bbox` (per line_in_region) -- top-to-bottom, left-to-right
    order. Each entry is `{"text": ..., "bbox": [x0, y0, x1, y1]}`. A fresh,
    independent scan of `page.get_text("dict")` (not shared state with
    extract_text.py's own block/line extraction), matching this codebase's
    existing convention of small independent derivations over cross-script
    imports."""
    lines = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans_text = "".join(span["text"] for span in line.get("spans", []))
            stripped = spans_text.strip()
            if not stripped:
                continue
            line_bbox = list(line["bbox"])
            if line_in_region(line_bbox, region_bbox, threshold):
                lines.append({"text": stripped, "bbox": line_bbox})
    lines.sort(key=lambda l: (l["bbox"][1], l["bbox"][0]))
    return lines


def figure_text_for_region(page, region_bbox) -> str | None:
    """The image element's `figure_text` for one region: its text-layer
    lines, top-to-bottom, newline-joined -- the same verbatim/newline-joined
    convention triage.py's furniture_text uses. `None` if the region has no
    text layer at all (per Task A5's brief: a region with no text layer
    leaves figure_text absent/null, so Task A6 knows to fill it via vision
    instead)."""
    lines = region_text_lines(page, region_bbox)
    if not lines:
        return None
    return "\n".join(line["text"] for line in lines)
