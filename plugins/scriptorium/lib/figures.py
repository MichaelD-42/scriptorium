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
   single item is dropped *before* clustering when its own rect matches
   (within `FRAME_MATCH_TOLERANCE`) an entry of one of two triage lists:
   - `triage.json["furniture"]["frame_drawings"]` (Task A5b,
     `triage.py`'s `_find_frame_drawings`): one drawing covering more than
     60% of the page that repeats at the same bbox on at least half the
     pages AND on at least `FRAME_MIN_PAGE_COUNT` (3) pages. Recorded per
     drawing as `reason: "frame_drawing"`.
   - `triage.json["furniture"]["repeated_drawings"]` (fix wave B1,
     `triage.py`'s `_find_repeated_drawings`): any drawing, of any size
     and any fill/stroke type, whose rect (and drawing type) repeats on at
     least `REPEATED_DRAWING_MIN_PAGE_FRACTION` (80%) of the body pages
     AND on at least `FRAME_MIN_PAGE_COUNT` pages. This catches a frame
     drawn from many parts (border lines, title-block rules, a filled inner
     rect). Recorded as ONE summary entry
     per page, `reason: "repeated_drawing"`, with the union bbox and a
     `count`.

   Repetition is the only signal, on purpose. Task A5b fix round 1 also
   required a frame drawing to be stroke-only and to touch the page edge.
   Fix wave B1 dropped both checks, because they are no longer needed and
   one of them was wrong for real documents:
   - A real page frame can be a FILLED rect (a white body panel). The
     stroke-only check kept it, and it then joined every drawing on the
     page into one page-sized cluster.
   - The removal is per drawing, not per region. A real figure drawn
     inside a repeated box still clusters from its own drawings, which do
     not repeat. Only a drawing that is identical on 80% of the body
     pages is removed, and such a drawing carries no page-specific
     content. The fraction is 80%, not 50%, because a figure can recur
     at one position on a few pages of a short document (follow-up R1).
   - The 1- and 2-page cases that fix round 1 guarded against are covered
     by the `FRAME_MIN_PAGE_COUNT` floor in triage, which both lists use.
   Every removal is still recorded in `excluded_regions`, so nothing
   vanishes without a trace.

   This matters more than it looks: left unfiltered, a full-page-frame
   border (a single stroked rectangle drawn near the page edges, which this
   plugin's own `furniture_sample.pdf` fixture has on every page) makes
   `page.cluster_drawings()` merge *every other drawing on the page* into
   one page-spanning cluster, because the border's bbox geometrically
   contains everything drawn inside it and `cluster_drawings()` joins
   overlapping items transitively. Confirmed empirically against the
   fixture: with the border left in, every page collapses to a single
   cluster exactly matching the border's own bbox; filtering it out first,
   the real diagram/chart/table clusters resolve correctly and separately.
   Task A5b replaced this step's *original* rule -- drop any single drawing
   over 60% of the page area, regardless of repetition -- because that
   older rule silently dropped a genuinely large, one-off real figure (e.g.
   a full-width block diagram on its own page) with no trace at all. Only a
   drawing that *repeats* (i.e. is actually furniture, not content) is
   removed now; everything a filter still removes shows up in
   `excluded_regions` instead of vanishing (see `detect_figure_regions`'s
   own docstring).
2. `page.cluster_drawings()` on what is left groups the remaining vector
   items into candidate regions, then each candidate bbox is padded by
   `REGION_PADDING` points on every side (clamped to the page). Padding
   exists because `cluster_drawings()` only ever looks at vector *drawing*
   items -- axis-label text sitting just below a bar chart's bars, e.g., is
   a few points outside the drawings-only bbox, and would otherwise be
   excluded from both the crop-render (a chart image with its labels cut
   off) and `figure_text` (missing the labels entirely).
3. Each padded candidate is dropped if it:
   - is "tiny" -- smaller than `MIN_CLUSTER_AREA_FRACTION` of the page
     area, almost certainly a stray rule/line rather than a real figure;
   - is a "text_box" (fix wave I1) -- its drawings form exactly one
     axis-aligned rectangle (one `re` item, or at most
     `TEXT_BOX_MAX_LINE_ITEMS` axis-aligned lines, no curves) and at least
     one text-layer line lies inside it. A boxed requirement paragraph or a
     shaded ID row is body text, not a figure; excluding the cluster keeps
     its lines in the body. A multi-item figure (a flow diagram, a bar
     chart) is never a text box. Follow-up R2: before this test, nearby
     would-be text boxes are grouped, and a group (or a single box) with a
     "Figure n" caption line directly next to it is a figure region (a box
     diagram drawn without connectors). See BOX_GROUP_MAX_GAP;
   - has *more than half its own area* inside the top/bottom furniture edge
     band (reuses the same `FURNITURE_EDGE_BAND` convention
     `lib/furniture.py`'s `in_furniture_band` and `extract_text.py`'s `furniture_filtered_lines`
     use, but as a majority-area test rather than either a containment or a
     bare-overlap test -- see `_furniture_band_overlap_fraction`'s
     docstring for why Task A5b tightened this from "any overlap at all");
   - or overlaps a real (non-frame) table's bbox, queried fresh via
     `pdfplumber` and filtered the same way `extract_text.py`'s
     `furniture_lib.matches_any_frame()` filters `frame_tables` out of its own table query.
     Follow-up R11: not when every overlapping table is a grid table
     (`is_grid_table`: mostly empty cells, a chart's grid). Then the
     cluster is a figure and each such table is recorded as "grid_table".
     Follow-up R16: a cluster that covers more than
     GRID_TABLE_MAX_CLUSTER_FRACTION of the page (or content rect) never
     uses the grid-table rule; a page-sized form stays a table.

Task A5b: every candidate this pipeline drops -- a pre-filtered frame
drawing, the page's repeated drawings, or an excluded cluster -- is also
returned as an "excluded region" (`{"bbox": [...], "reason":
"frame_drawing"|"repeated_drawing"|"tiny"|"text_box"|"furniture_band"|
"table_overlap"|"grid_table"}`; a "repeated_drawing" entry also has a `count`) via
`detect_figure_regions_with_exclusions`, so a large
region that a filter removes is never silently dropped -- it's visible to
`extract-images` (which writes it into the page's image shard as
`excluded_regions`) and to `grade-output`'s `large_region_excluded` gate.
`detect_figure_regions` itself keeps its original signature/return shape
(regions only) for existing callers that only need the survivors.

Task A6 adds caption detection on top of the same region bboxes (plus
bitmap placement bboxes, via `bitmap_bboxes()`): `find_caption_line()`
searches the text layer just above/below a given image element's own bbox
for a line matching `CAPTION_PATTERN` ("Figure 1: ...", "Table 2 ..."). Both
`extract_images.py` (to fill the element's script-authoritative `caption`
field) and `extract_text.py` (to exclude that same line from paragraph/
heading extraction) call it, again so the two scripts can never disagree
about which line is the caption.
"""

import re
from pathlib import Path

import pdfplumber

import furniture as furniture_lib
import toc as toc_lib

# The furniture band (FURNITURE_EDGE_BAND) and the frame matching tolerance
# (FRAME_MATCH_TOLERANCE, 3pt; triage groups with 2pt) are in
# lib/furniture.py, shared with every other stage.
FURNITURE_EDGE_BAND = furniture_lib.FURNITURE_EDGE_BAND


# Task A5b: a cluster is dropped for the furniture band only if MORE THAN
# HALF its own area lies inside the top/bottom edge band -- tightened from
# the original "any overlap at all" rule, which excluded a genuinely tall
# real figure just for reaching into the band (see
# _furniture_band_overlap_fraction's docstring).
FURNITURE_BAND_AREA_THRESHOLD = 0.5

# A single candidate region's raw vector-drawings bbox, padded this many
# points on every side before it's used for either the crop-render or the
# figure_text text-overlap query. See module docstring step 2.
REGION_PADDING = 10.0

# A cluster smaller than this fraction of the page area is treated as stray
# line-art (a short rule, an underline) rather than a real figure. A judgment
# call, not a derived constant -- a census of real documents is expected
# to tune it; 1% gives a reasonable ballpark against this repo's fixtures today (the
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

# Follow-up R11: pdfplumber reads a chart's grid lines as a table. Before the
# table_overlap exclusion, the overlapping table is tested: with more than
# GRID_TABLE_EMPTY_FRACTION of its cells empty, or more than
# GRID_TABLE_EMPTY_FRACTION_WITH_CURVES when the cluster has curves or
# non-axis-aligned lines, it is a grid table (is_grid_table). The cluster is
# then a figure, the table is recorded in excluded_regions as "grid_table",
# and extract_text emits no table for it.
GRID_TABLE_EMPTY_FRACTION = 0.60
GRID_TABLE_EMPTY_FRACTION_WITH_CURVES = 0.40

# Follow-up R16: the grid-table rule is skipped for a cluster that covers
# more than this fraction of the page area (or of the content rect, when
# there is one). A page-sized ruled form or cover page with sparse cells is
# a table, not a chart; the cluster is excluded as table_overlap.
GRID_TABLE_MAX_CLUSTER_FRACTION = 0.60

# Follow-up R12: a table detected inside the content rect that covers more
# than this fraction of it (and matches it within FRAME_MATCH_TOLERANCE) is
# the page frame, not a table. See page_tables.
FRAME_TABLE_CONTENT_FRACTION = 0.60

# Fix wave I1: a cluster is a text box when its drawings form one
# axis-aligned rectangle -- one `re` item (stroked, filled or both; the same
# rect drawn twice still counts as one), or at most this many axis-aligned
# `l` items (a box drawn as 4 separate sides) -- and it holds at least one
# text-layer line. A line counts as axis-aligned when its two ends differ by
# at most TEXT_BOX_AXIS_TOLERANCE in x or in y.
TEXT_BOX_MAX_LINE_ITEMS = 4
TEXT_BOX_AXIS_TOLERANCE = 0.5  # pt

# Follow-up R2: a diagram of separate labelled boxes (a row of components, a
# stack of layers) has no connectors, so each box is its own cluster and
# would pass the text-box test above. Before that test, the would-be text
# boxes are grouped: two boxes join a group when they are at most
# BOX_GROUP_MAX_GAP apart on one axis and overlap on the other. A group, or
# a single box, is a figure region when a figure-caption line
# (is_figure_caption) lies directly below or above it, at most
# BOX_CAPTION_MAX_GAP from its edge. A box with no caption next to it stays a
# text box, so a boxed paragraph or a shaded ID row stays body text.
BOX_GROUP_MAX_GAP = 24.0  # pt
BOX_CAPTION_MAX_GAP = 36.0  # pt

# Task A6: a caption line's text pattern -- "Figure 1: ...", "Fig. 2 ...",
# "Table 3: ..." (case-insensitive, optional trailing period/colon after the
# number). Checked against furniture_sample.pdf's real caption text
# ("Figure 1: Process Diagram", "Figure 2: Revenue by Quarter") in
# furniture_golden.json's "figures" entries.
#
# Follow-up R17: the number may also end the line ("Fig. 11" printed as its
# own span, with the title in a second span at the same y; _page_lines joins
# the two).
CAPTION_PATTERN = re.compile(r"^(figure|fig\.?|table)\s+\d+\.?:?(?=\s|$)", re.IGNORECASE)


def is_figure_caption(text: str) -> bool:
    """True when `text` starts like a figure caption: it matches
    CAPTION_PATTERN in its "Figure n" or "Fig. n" form. The "Table n" form
    is left out, because a table caption belongs to a table, not to an
    image."""
    match = CAPTION_PATTERN.match(text or "")
    return bool(match) and match.group(1).lower() != "table"


# How far above/below an image element's own bbox to search for a caption
# line, in points. A judgment call (documented per the brief), not a
# derived constant: verified against furniture_sample.pdf's real layout --
# the diagram's caption sits ~10pt below its region's padded bbox, the
# chart's caption ~30pt below its region's padded bbox -- both comfortably
# inside this window with room to spare. A generous window is safe here
# because CAPTION_PATTERN, not distance, is the real filter: ordinary body
# text never matches it, so widening the search window risks a slow query,
# not a false match. A census of real documents is expected to tune this,
# same as this module's other constants.
CAPTION_SEARCH_DISTANCE = 60.0

# How far inside an image element's bbox edge a caption line may start
# (follow-up R2, probe 2): a vector region's bbox is the drawing padded by
# REGION_PADDING, so a caption printed 5-10 pt below the drawing starts
# inside the padded bbox. The line must still not be majority-inside the
# bbox (line_in_region), or it is figure text.
CAPTION_EDGE_SLACK = REGION_PADDING


def page_tables(
    pdf_path: Path, page_number: int, frame_tables: list[dict] | None = None,
    content_rect: list[float] | None = None,
) -> list[dict]:
    """Real (non-frame) tables on this page, queried fresh via pdfplumber
    -- not read from any shard, on purpose: extract_images.py and
    extract_text.py may run in either order, or in parallel, for the same
    page (see module docstring), so neither script can assume the other's
    shard already exists. Each entry is `{"bbox", "rows", "empty_fraction"}`:
    `rows` with None cells as "", and the fraction of cells that are empty
    (follow-up R11, `is_grid_table`). extract_text builds its `table`
    elements from this same list.

    Follow-up R12: with a `content_rect` (triage's
    `furniture["content_rect"]`), tables are detected on the page cropped
    to that rect (pdfplumber keeps page coordinates), so the frame's title
    block never joins a table. A table found there that covers more than
    FRAME_TABLE_CONTENT_FRACTION of the rect and matches it within
    FRAME_MATCH_TOLERANCE is the frame again, and is dropped. This catches
    a frame table whose bbox is a few points off the repeated
    `frame_tables` entry on one page."""
    frame_tables = frame_tables or []
    found = []
    with pdfplumber.open(pdf_path) as pl_doc:
        pl_page = pl_doc.pages[page_number - 1]
        crop = None
        if content_rect:
            x0, top, x1, bottom = pl_page.bbox
            crop = [max(content_rect[0], x0), max(content_rect[1], top), min(content_rect[2], x1), min(content_rect[3], bottom)]
            if crop[2] > crop[0] and crop[3] > crop[1]:
                pl_page = pl_page.crop(crop)
            else:
                crop = None
        for table in pl_page.find_tables():
            if furniture_lib.matches_any_frame(table.bbox, frame_tables):
                continue
            if crop is not None and _is_content_frame(table.bbox, crop):
                continue
            rows = [[cell if cell is not None else "" for cell in row] for row in table.extract()]
            cells = [cell for row in rows for cell in row]
            empty = sum(1 for cell in cells if not str(cell).strip())
            found.append({
                "bbox": list(table.bbox),
                "rows": rows,
                "empty_fraction": empty / len(cells) if cells else 1.0,
            })
    return found


def _is_content_frame(table_bbox, rect) -> bool:
    """Follow-up R12: a table on the cropped page that is the content frame
    itself (see page_tables)."""
    rect_area = max(1e-6, (rect[2] - rect[0]) * (rect[3] - rect[1]))
    table_area = max(0.0, table_bbox[2] - table_bbox[0]) * max(0.0, table_bbox[3] - table_bbox[1])
    return table_area / rect_area > FRAME_TABLE_CONTENT_FRACTION and furniture_lib.bbox_matches(table_bbox, rect)


def real_table_bboxes(
    pdf_path: Path, page_number: int, frame_tables: list[dict] | None = None,
    content_rect: list[float] | None = None,
) -> list[list[float]]:
    """The bboxes of `page_tables`."""
    return [t["bbox"] for t in page_tables(pdf_path, page_number, frame_tables, content_rect)]


def is_grid_table(table: dict, cluster_has_curves: bool) -> bool:
    """Follow-up R11: True when `table` is a chart's grid, not a table: more
    than GRID_TABLE_EMPTY_FRACTION of its cells are empty, or the
    overlapping drawing cluster has curves or non-axis-aligned lines and
    more than GRID_TABLE_EMPTY_FRACTION_WITH_CURVES are empty."""
    empty = table["empty_fraction"]
    if empty > GRID_TABLE_EMPTY_FRACTION:
        return True
    return cluster_has_curves and empty > GRID_TABLE_EMPTY_FRACTION_WITH_CURVES


def _has_curves_or_diagonals(drawings: list[dict]) -> bool:
    """True when any path item of `drawings` is a curve or a line that is
    not axis-aligned (within TEXT_BOX_AXIS_TOLERANCE)."""
    for d in drawings:
        for item in d.get("items", []):
            op = item[0]
            if op == "c":
                return True
            if op == "l":
                p1, p2 = item[1], item[2]
                if abs(p1.x - p2.x) > TEXT_BOX_AXIS_TOLERANCE and abs(p1.y - p2.y) > TEXT_BOX_AXIS_TOLERANCE:
                    return True
    return False


def _matches_repeated_drawing(drawing: dict, bbox, repeated_drawings: list[dict]) -> bool:
    """True when `drawing` matches a `repeated_drawings` entry: the same
    drawing type (when the entry records one) and a rect within
    FRAME_MATCH_TOLERANCE."""
    dtype = drawing.get("type")
    return any(
        (entry.get("type") is None or entry.get("type") == dtype)
        and furniture_lib.bbox_matches(bbox, entry["bbox"])
        for entry in repeated_drawings
    )


def _furniture_band_overlap_fraction(bbox, page_height: float, content_rect: list[float] | None = None) -> float:
    """Fraction of `bbox`'s own area that lies within the top or bottom
    furniture band of the page (0.0-1.0): `furniture.band_limits`, the
    FURNITURE_EDGE_BAND or, follow-up R13, the area outside the content
    rect.

    Task A5b tightened this from a bare *overlap* test (any part of bbox in
    the band at all excluded the whole cluster) to this majority-area test,
    because the bare-overlap version excluded a genuinely tall real figure
    just for reaching into the band -- the brief's example is a tall
    diagram that mostly sits outside the band but grazes it at one edge.
    Requiring MORE than half the cluster's own area to be inside the band
    (see FURNITURE_BAND_AREA_THRESHOLD) still catches a region-sized
    page-frame border reliably (its bbox spans nearly the whole page, so
    even just its two band-height strips are a large fraction of a
    genuinely small candidate, and a real frame is caught primarily by
    frame_drawings now, not this rule) while keeping a real figure that
    only grazes the band."""
    if page_height <= 0:
        return 0.0
    x0, y0, x1, y1 = bbox
    width = max(0.0, x1 - x0)
    total_height = max(0.0, y1 - y0)
    area = width * total_height
    if area <= 0:
        return 0.0
    top_limit, bottom_limit = furniture_lib.band_limits(page_height, content_rect)
    top_overlap = max(0.0, min(y1, top_limit) - max(y0, 0.0))
    bottom_overlap = max(0.0, min(y1, page_height) - max(y0, bottom_limit))
    return (width * (top_overlap + bottom_overlap)) / area


_overlap_ratio = furniture_lib.overlap_ratio


def _overlaps_table(bbox, table_bbox) -> bool:
    return (
        _overlap_ratio(bbox, table_bbox) > TABLE_OVERLAP_THRESHOLD
        or _overlap_ratio(table_bbox, bbox) > TABLE_OVERLAP_THRESHOLD
    )


def _overlaps_any_table(bbox, table_bboxes: list[list[float]]) -> bool:
    return any(_overlaps_table(bbox, t) for t in table_bboxes)


def _drawings_in_cluster(cluster_rect, drawings: list[dict]) -> list[dict]:
    """The drawings whose own rect lies inside `cluster_rect` (1pt slack):
    `cluster_drawings()` returns only the cluster rects, not which drawings
    formed each one."""
    slack = 1.0
    return [
        d for d in drawings
        if d["rect"].x0 >= cluster_rect.x0 - slack and d["rect"].y0 >= cluster_rect.y0 - slack
        and d["rect"].x1 <= cluster_rect.x1 + slack and d["rect"].y1 <= cluster_rect.y1 + slack
    ]


def _forms_one_rectangle(drawings: list[dict]) -> bool:
    """True when every path item of `drawings` together draws exactly one
    axis-aligned rectangle: one distinct `re` (or rectangular `qu`) item,
    or 1..TEXT_BOX_MAX_LINE_ITEMS axis-aligned `l` items, and nothing else
    (no curve, no diagonal line, no second rectangle). See
    TEXT_BOX_MAX_LINE_ITEMS."""
    rects = []
    line_count = 0
    for d in drawings:
        for item in d.get("items", []):
            op = item[0]
            if op == "re":
                rects.append(list(item[1]))
            elif op == "qu" and item[1].is_rectangular:
                rects.append(list(item[1].rect))
            elif op == "l":
                p1, p2 = item[1], item[2]
                if abs(p1.x - p2.x) > TEXT_BOX_AXIS_TOLERANCE and abs(p1.y - p2.y) > TEXT_BOX_AXIS_TOLERANCE:
                    return False
                line_count += 1
            else:
                return False
    if rects:
        return line_count == 0 and all(furniture_lib.bbox_matches(r, rects[0]) for r in rects)
    return 1 <= line_count <= TEXT_BOX_MAX_LINE_ITEMS


def _is_text_box(cluster_rect, drawings: list[dict], page_lines: list[dict]) -> bool:
    """Fix wave I1: see TEXT_BOX_MAX_LINE_ITEMS. `page_lines` is the page's
    `_page_lines()` scan; a line counts as inside when it is majority-inside
    the unpadded cluster rect (`line_in_region`)."""
    members = _drawings_in_cluster(cluster_rect, drawings)
    if not members or not _forms_one_rectangle(members):
        return False
    raw_bbox = [cluster_rect.x0, cluster_rect.y0, cluster_rect.x1, cluster_rect.y1]
    return any(line_in_region(line["bbox"], raw_bbox) for line in page_lines)


def _boxes_adjacent(a, b, max_gap: float = BOX_GROUP_MAX_GAP) -> bool:
    """True when bboxes `a` and `b` are at most `max_gap` apart on one axis
    and overlap on the other (see BOX_GROUP_MAX_GAP)."""
    x_gap = max(a[0], b[0]) - min(a[2], b[2])
    y_gap = max(a[1], b[1]) - min(a[3], b[3])
    return (x_gap <= max_gap and y_gap < 0) or (y_gap <= max_gap and x_gap < 0)


def group_boxes(boxes: list[list[float]], max_gap: float = BOX_GROUP_MAX_GAP) -> list[list[list[float]]]:
    """`boxes` split into groups of adjacent boxes (`_boxes_adjacent`,
    joined transitively). A box with no neighbour is a group of one. Groups
    keep the input order of their first box."""
    parent = list(range(len(boxes)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            if _boxes_adjacent(boxes[i], boxes[j], max_gap):
                parent[root(j)] = root(i)
    groups: dict[int, list[list[float]]] = {}
    for i, box in enumerate(boxes):
        groups.setdefault(root(i), []).append(box)
    return list(groups.values())


def _union_bbox(boxes: list[list[float]]) -> list[float]:
    return [
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    ]


def line_in_region(line_bbox, region_bbox, threshold: float = LINE_OVERLAP_THRESHOLD) -> bool:
    """True if `line_bbox` (a text line's own bbox) is majority-inside
    `region_bbox` -- the single overlap test both extract_text.py (to drop
    the line from paragraph/heading extraction) and this module's own
    region_text_lines() (to collect it into figure_text) use, so the two
    scripts' answers can never drift apart from each other."""
    return _overlap_ratio(line_bbox, region_bbox) > threshold


def detect_figure_regions_with_exclusions(
    page, page_number: int, pdf_path: Path,
    frame_tables: list[dict] | None = None,
    frame_drawings: list[dict] | None = None,
    repeated_drawings: list[dict] | None = None,
    content_rect: list[float] | None = None,
) -> tuple[list[dict], list[dict]]:
    """The full detection pipeline (see module docstring): returns
    `(regions, excluded_regions)`.

    `regions`: candidate figure regions that survived every exclusion rule,
    `[{"bbox": [x0, y0, x1, y1]}, ...]`, sorted top-to-bottom by bbox y0.

    `excluded_regions`: Task A5b -- every drawing/cluster a filter removed,
    `[{"bbox": [...], "reason": "frame_drawing"|"repeated_drawing"|"tiny"|
    "text_box"|"furniture_band"|"table_overlap"|"grid_table"}]`, sorted the same way.
    A "grid_table" entry is a pdfplumber table that is a chart's grid; its
    cluster is in `regions`. The page's
    repeated drawings give one summary entry (union bbox plus `count`), not
    one entry per line. This is the "no silent drops"
    record: `extract_images.py` writes it into the page's image shard so a
    large dropped region is visible to `grade-output`'s
    `large_region_excluded` gate and to a human reviewer, instead of simply
    vanishing the way the pre-A5b size-based filter did."""
    frame_tables = frame_tables or []
    frame_drawings = frame_drawings or []
    repeated_drawings = repeated_drawings or []
    page_width, page_height = page.rect.width, page.rect.height
    page_area = page_width * page_height
    if page_area <= 0:
        return [], []

    drawings = page.get_drawings()
    significant = []
    excluded_regions = []
    repeated_bboxes = []
    for d in drawings:
        rect = d["rect"]
        bbox = [rect.x0, rect.y0, rect.x1, rect.y1]
        if furniture_lib.matches_any_frame(bbox, frame_drawings):
            excluded_regions.append({"bbox": bbox, "reason": "frame_drawing"})
            continue
        if _matches_repeated_drawing(d, bbox, repeated_drawings):
            repeated_bboxes.append(bbox)
            continue
        significant.append(d)
    if repeated_bboxes:
        union = list(repeated_bboxes[0])
        for b in repeated_bboxes[1:]:
            union = [min(union[0], b[0]), min(union[1], b[1]), max(union[2], b[2]), max(union[3], b[3])]
        excluded_regions.append({"bbox": union, "reason": "repeated_drawing", "count": len(repeated_bboxes)})

    if not significant:
        excluded_regions.sort(key=lambda r: r["bbox"][1])
        return [], excluded_regions

    clusters = page.cluster_drawings(drawings=significant)
    tables = page_tables(pdf_path, page_number, frame_tables, content_rect)
    page_lines = _page_lines(page)
    reference_area = page_area
    if content_rect:
        reference_area = max(1e-6, (content_rect[2] - content_rect[0]) * (content_rect[3] - content_rect[1]))

    def padded(raw) -> list[float]:
        return [
            max(0.0, raw[0] - REGION_PADDING),
            max(0.0, raw[1] - REGION_PADDING),
            min(page_width, raw[2] + REGION_PADDING),
            min(page_height, raw[3] + REGION_PADDING),
        ]

    regions = []

    def keep_unless_band_or_table(bbox, members: list[dict] | None = None) -> None:
        if _furniture_band_overlap_fraction(bbox, page_height, content_rect) > FURNITURE_BAND_AREA_THRESHOLD:
            excluded_regions.append({"bbox": bbox, "reason": "furniture_band"})
            return
        overlapping = [t for t in tables if _overlaps_table(bbox, t["bbox"])]
        if overlapping:
            # Follow-up R11: a chart's grid read as a table does not hide
            # the chart. Only when every overlapping table is a grid table,
            # and (R16) the cluster is not page-sized.
            curves = _has_curves_or_diagonals(members or [])
            area = max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])
            page_sized = area / reference_area > GRID_TABLE_MAX_CLUSTER_FRACTION
            if page_sized or not all(is_grid_table(t, curves) for t in overlapping):
                excluded_regions.append({"bbox": bbox, "reason": "table_overlap"})
                return
            for t in overlapping:
                excluded_regions.append({"bbox": list(t["bbox"]), "reason": "grid_table"})
        regions.append({"bbox": bbox})

    box_candidates = []  # raw [x0, y0, x1, y1] of each would-be text box
    for rect in clusters:
        raw = [rect.x0, rect.y0, rect.x1, rect.y1]
        bbox = padded(raw)
        area = max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])
        if area / page_area < MIN_CLUSTER_AREA_FRACTION:
            excluded_regions.append({"bbox": bbox, "reason": "tiny"})
            continue
        if _is_text_box(rect, significant, page_lines):
            box_candidates.append(raw)
            continue
        keep_unless_band_or_table(bbox, _drawings_in_cluster(rect, significant))

    # Follow-up R2: a group of nearby boxes, or a single box, with a figure
    # caption next to it is a box diagram, not body text.
    for group in group_boxes(box_candidates):
        union = _union_bbox(group)
        if _nearest_caption_line(page_lines, union, BOX_CAPTION_MAX_GAP, is_figure_caption):
            keep_unless_band_or_table(padded(union))
        else:
            for raw in group:
                excluded_regions.append({"bbox": padded(raw), "reason": "text_box"})

    regions.sort(key=lambda r: r["bbox"][1])
    excluded_regions.sort(key=lambda r: r["bbox"][1])
    return regions, excluded_regions


def detect_figure_regions(
    page, page_number: int, pdf_path: Path,
    frame_tables: list[dict] | None = None,
    frame_drawings: list[dict] | None = None,
    repeated_drawings: list[dict] | None = None,
    content_rect: list[float] | None = None,
) -> list[dict]:
    """Candidate figure regions for one page -- the `regions` half of
    `detect_figure_regions_with_exclusions`, for the (majority of) callers
    that only need the survivors, not the exclusion record. See that
    function's docstring, and the module docstring, for the full pipeline."""
    regions, _excluded = detect_figure_regions_with_exclusions(
        page, page_number, pdf_path, frame_tables=frame_tables, frame_drawings=frame_drawings,
        repeated_drawings=repeated_drawings, content_rect=content_rect,
    )
    return regions


def _page_lines(page) -> list[dict]:
    """Every non-empty text-layer line on `page`, verbatim, as `{"text":
    ..., "bbox": [x0, y0, x1, y1]}` -- the single raw scan both
    region_text_lines() (filtered to lines inside a region) and
    find_caption_line() (filtered to lines near an arbitrary bbox) build
    on, so the two never derive slightly different line sets from the same
    page. A fresh, independent scan of `page.get_text("dict")` (not shared
    state with extract_text.py's own block/line extraction), matching this
    codebase's existing convention of small independent derivations over
    cross-script imports."""
    lines = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans_text = "".join(span["text"] for span in line.get("spans", []))
            stripped = spans_text.strip()
            if not stripped:
                continue
            lines.append({"text": stripped, "bbox": list(line["bbox"])})
    return _join_split_captions(lines)


def _is_lone_caption_number(text: str) -> bool:
    """True when `text` is only a caption number ("Fig. 11", "Figure 3:"),
    with no title after it."""
    match = CAPTION_PATTERN.match(text)
    return bool(match) and not text[match.end():].strip()


def _join_split_captions(lines: list[dict]) -> list[dict]:
    """Follow-up R17: a lone caption-number line ("Fig. 11") joined with
    the nearest text line to its right at the same y (tops within
    toc.SAME_Y_TOLERANCE) into one caption line: text "Fig. 11 <title>",
    the union bbox, and `parts`, the two source line bboxes (extract_text
    excludes those from the body). A lone number with no such line stays as
    it is."""
    used: set[int] = set()
    joined: dict[int, dict] = {}
    for i, line in enumerate(lines):
        if i in used or not _is_lone_caption_number(line["text"]):
            continue
        partners = [
            j for j, other in enumerate(lines)
            if j != i and j not in used
            and abs(other["bbox"][1] - line["bbox"][1]) <= toc_lib.SAME_Y_TOLERANCE
            and other["bbox"][0] >= line["bbox"][2]
            and not CAPTION_PATTERN.match(other["text"])
        ]
        if not partners:
            continue
        j = min(partners, key=lambda k: lines[k]["bbox"][0])
        other = lines[j]
        used.update((i, j))
        joined[i] = {
            "text": f"{line['text']} {other['text']}",
            "bbox": [
                min(line["bbox"][0], other["bbox"][0]), min(line["bbox"][1], other["bbox"][1]),
                max(line["bbox"][2], other["bbox"][2]), max(line["bbox"][3], other["bbox"][3]),
            ],
            "parts": [list(line["bbox"]), list(other["bbox"])],
        }
    return [joined[i] if i in joined else line for i, line in enumerate(lines) if i in joined or i not in used]


def region_text_lines(page, region_bbox, threshold: float = LINE_OVERLAP_THRESHOLD) -> list[dict]:
    """Text-layer lines on `page` whose own bbox is majority-inside
    `region_bbox` (per line_in_region) -- top-to-bottom, left-to-right
    order. Each entry is `{"text": ..., "bbox": [x0, y0, x1, y1]}`."""
    lines = [l for l in _page_lines(page) if line_in_region(l["bbox"], region_bbox, threshold)]
    lines.sort(key=lambda l: (l["bbox"][1], l["bbox"][0]))
    return lines


def _x_overlaps(bbox_a, bbox_b) -> bool:
    """True if the two bboxes' x-ranges intersect at all -- a caption line
    must sit in roughly the same horizontal position as the figure it
    describes, not just anywhere within the vertical search window. This
    repo's fixtures are all single-column, so it rarely changes the answer
    in practice, but it's a cheap, correct guard against picking up an
    unrelated line in a hypothetical multi-column layout."""
    return bbox_a[0] < bbox_b[2] and bbox_b[0] < bbox_a[2]


def find_caption_line(page, bbox: list[float], distance: float = CAPTION_SEARCH_DISTANCE) -> dict | None:
    """A figure/table caption line near `bbox` (an image element's own
    bbox -- a vector region's padded cluster bbox, or a bitmap's placement
    bbox): a text-layer line matching CAPTION_PATTERN within `distance`
    points directly below or above `bbox`, and horizontally overlapping it
    at all (per _x_overlaps). Checks below first (the more common
    convention -- a caption follows the figure it describes), nearest
    match first, then above the same way. `None` if nothing in range
    matches -- the caller leaves `caption` absent rather than guessing, so
    a false match never overwrites a genuinely uncaptioned figure with
    unrelated nearby text.

    A caption line may start up to CAPTION_EDGE_SLACK inside `bbox`'s edge,
    as long as it is not majority-inside `bbox` (then it is figure text).
    A vector region's bbox is padded by REGION_PADDING, so a caption printed
    closer than that to the drawing reaches into the padding."""
    lines = _page_lines(page)
    # Follow-up R17: the nearest figure caption wins over a "Table n"
    # caption; a table caption is used only when no figure caption is near.
    return _nearest_caption_line(
        lines, bbox, distance, is_figure_caption, edge_slack=CAPTION_EDGE_SLACK
    ) or _nearest_caption_line(lines, bbox, distance, CAPTION_PATTERN.match, edge_slack=CAPTION_EDGE_SLACK)


def _nearest_caption_line(
    lines: list[dict], bbox: list[float], distance: float, is_caption, edge_slack: float = 0.0
) -> dict | None:
    """find_caption_line's search over an already-scanned line list: the
    nearest line below `bbox` (then above it) within `distance` points that
    overlaps it horizontally and for which `is_caption(text)` is true. With
    `edge_slack`, a line may start that far inside the edge, but never
    majority-inside `bbox`."""
    x0, y0, x1, y1 = bbox

    def outside(line) -> bool:
        return not edge_slack or not line_in_region(line["bbox"], bbox)

    below = sorted(
        (
            l for l in lines
            if y1 - edge_slack <= l["bbox"][1] <= y1 + distance and _x_overlaps(bbox, l["bbox"]) and outside(l)
        ),
        key=lambda l: l["bbox"][1],
    )
    above = sorted(
        (
            l for l in lines
            if y0 - distance <= l["bbox"][3] <= y0 + edge_slack and _x_overlaps(bbox, l["bbox"]) and outside(l)
        ),
        key=lambda l: -l["bbox"][3],
    )
    for line in below + above:
        if is_caption(line["text"]):
            return line
    return None


def bitmap_bboxes(page, furniture_xrefs: set[int] | None = None) -> list[list[float]]:
    """Placement bbox for every bitmap XObject on `page`, skipping any xref
    in `furniture_xrefs` (a repeated logo, etc.) -- the same universe
    extract_images.py's own extract_bitmaps() turns into `image` elements,
    factored out here (bbox only, no image bytes) so extract_text.py can
    compute the same set independently to find + exclude each bitmap's
    caption line, without waiting on extract_images.py's shard."""
    furniture_xrefs = furniture_xrefs or set()
    bboxes = []
    for img in page.get_images(full=True):
        xref = img[0]
        if xref in furniture_xrefs:
            continue
        try:
            bboxes.append(list(page.get_image_bbox(img)))
        except Exception:
            continue
    return bboxes


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
