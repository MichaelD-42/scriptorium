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
     least half the body pages AND on at least `FRAME_MIN_PAGE_COUNT`
     pages. This catches a frame drawn from many parts (border lines,
     title-block rules, a filled inner rect). Recorded as ONE summary entry
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
     not repeat. Only a drawing that is identical on half the pages is
     removed, and such a drawing carries no page-specific content.
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
   - has *more than half its own area* inside the top/bottom furniture edge
     band (reuses the same `FURNITURE_EDGE_BAND` convention
     `lib/furniture.py`'s `in_furniture_band` and `extract_text.py`'s `furniture_filtered_lines`
     use, but as a majority-area test rather than either a containment or a
     bare-overlap test -- see `_furniture_band_overlap_fraction`'s
     docstring for why Task A5b tightened this from "any overlap at all");
   - or overlaps a real (non-frame) table's bbox, queried fresh via
     `pdfplumber` and filtered the same way `extract_text.py`'s
     `furniture_lib.matches_any_frame()` filters `frame_tables` out of its own table query.

Task A5b: every candidate this pipeline drops -- a pre-filtered frame
drawing, the page's repeated drawings, or an excluded cluster -- is also
returned as an "excluded region" (`{"bbox": [...], "reason":
"frame_drawing"|"repeated_drawing"|"tiny"|"furniture_band"|
"table_overlap"}`; a "repeated_drawing" entry also has a `count`) via
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

# Task A6: a caption line's text pattern -- "Figure 1: ...", "Fig. 2 ...",
# "Table 3: ..." (case-insensitive, optional trailing period/colon after the
# number). Checked against furniture_sample.pdf's real caption text
# ("Figure 1: Process Diagram", "Figure 2: Revenue by Quarter") in
# furniture_golden.json's "figures" entries.
CAPTION_PATTERN = re.compile(r"^(figure|fig\.?|table)\s+\d+\.?:?\s", re.IGNORECASE)

# How far above/below an image element's own bbox to search for a caption
# line, in points. A judgment call (documented per the brief), not a
# derived constant: verified against furniture_sample.pdf's real layout --
# the diagram's caption sits ~10pt below its region's padded bbox, the
# chart's caption ~30pt below its region's padded bbox -- both comfortably
# inside this window with room to spare. A generous window is safe here
# because CAPTION_PATTERN, not distance, is the real filter: ordinary body
# text never matches it, so widening the search window risks a slow query,
# not a false match. a later step's document census is expected to tune this
# against the real golden document, same as this module's other constants.
CAPTION_SEARCH_DISTANCE = 60.0


def real_table_bboxes(pdf_path: Path, page_number: int, frame_tables: list[dict] | None = None) -> list[list[float]]:
    """Real (non-frame) table bboxes on this page, queried fresh via
    pdfplumber -- not read from any shard, on purpose: extract_images.py and
    extract_text.py may run in either order, or in parallel, for the same
    page (see module docstring), so neither script can assume the other's
    shard already exists."""
    frame_tables = frame_tables or []
    with pdfplumber.open(pdf_path) as pl_doc:
        tables = pl_doc.pages[page_number - 1].find_tables()
        return [list(t.bbox) for t in tables if not furniture_lib.matches_any_frame(t.bbox, frame_tables)]


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


def _furniture_band_overlap_fraction(bbox, page_height: float) -> float:
    """Fraction of `bbox`'s own area that lies within the top or bottom
    FURNITURE_EDGE_BAND of the page (0.0-1.0).

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
    band_height = FURNITURE_EDGE_BAND * page_height
    top_overlap = max(0.0, min(y1, band_height) - max(y0, 0.0))
    bottom_overlap = max(0.0, min(y1, page_height) - max(y0, page_height - band_height))
    return (width * (top_overlap + bottom_overlap)) / area


_overlap_ratio = furniture_lib.overlap_ratio


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


def detect_figure_regions_with_exclusions(
    page, page_number: int, pdf_path: Path,
    frame_tables: list[dict] | None = None,
    frame_drawings: list[dict] | None = None,
    repeated_drawings: list[dict] | None = None,
) -> tuple[list[dict], list[dict]]:
    """The full detection pipeline (see module docstring): returns
    `(regions, excluded_regions)`.

    `regions`: candidate figure regions that survived every exclusion rule,
    `[{"bbox": [x0, y0, x1, y1]}, ...]`, sorted top-to-bottom by bbox y0.

    `excluded_regions`: Task A5b -- every drawing/cluster a filter removed,
    `[{"bbox": [...], "reason": "frame_drawing"|"repeated_drawing"|"tiny"|
    "furniture_band"|"table_overlap"}]`, sorted the same way. The page's
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
            excluded_regions.append({"bbox": bbox, "reason": "tiny"})
            continue
        if _furniture_band_overlap_fraction(bbox, page_height) > FURNITURE_BAND_AREA_THRESHOLD:
            excluded_regions.append({"bbox": bbox, "reason": "furniture_band"})
            continue
        if _overlaps_any_table(bbox, table_bboxes):
            excluded_regions.append({"bbox": bbox, "reason": "table_overlap"})
            continue
        regions.append({"bbox": bbox})

    regions.sort(key=lambda r: r["bbox"][1])
    excluded_regions.sort(key=lambda r: r["bbox"][1])
    return regions, excluded_regions


def detect_figure_regions(
    page, page_number: int, pdf_path: Path,
    frame_tables: list[dict] | None = None,
    frame_drawings: list[dict] | None = None,
    repeated_drawings: list[dict] | None = None,
) -> list[dict]:
    """Candidate figure regions for one page -- the `regions` half of
    `detect_figure_regions_with_exclusions`, for the (majority of) callers
    that only need the survivors, not the exclusion record. See that
    function's docstring, and the module docstring, for the full pipeline."""
    regions, _excluded = detect_figure_regions_with_exclusions(
        page, page_number, pdf_path, frame_tables=frame_tables, frame_drawings=frame_drawings,
        repeated_drawings=repeated_drawings,
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
    return lines


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
    unrelated nearby text."""
    x0, y0, x1, y1 = bbox
    lines = _page_lines(page)
    below = sorted(
        (l for l in lines if y1 <= l["bbox"][1] <= y1 + distance and _x_overlaps(bbox, l["bbox"])),
        key=lambda l: l["bbox"][1],
    )
    above = sorted(
        (l for l in lines if y0 - distance <= l["bbox"][3] <= y0 and _x_overlaps(bbox, l["bbox"])),
        key=lambda l: -l["bbox"][3],
    )
    for line in below + above:
        if CAPTION_PATTERN.match(line["text"]):
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
