#!/usr/bin/env python3
"""Classify each page of a PDF into an extraction tier (text|ocr) and the
document into a loop size (tight|loose). See SKILL.md for the schema."""

import argparse
import itertools
import json
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import furniture as furniture_lib  # noqa: E402
import paths  # noqa: E402
import toc as toc_lib  # noqa: E402

import fitz  # PyMuPDF
import pdfplumber

TEXT_CHAR_THRESHOLD = 20  # fewer non-whitespace chars than this => treat page as scanned

# Furniture thresholds (see SKILL.md). The edge band and the bbox
# tolerances are in lib/furniture.py: FURNITURE_EDGE_BAND (top/bottom 12% of
# the page height) and FRAME_GROUP_TOLERANCE (2pt, the grouping tolerance
# used here to decide whether two pages' bboxes are the same frame; see that
# module for why the later matching tolerance is 3pt).
LINE_PATTERN_MIN_PAGE_FRACTION = 0.60
FRAME_TABLE_MIN_AREA_FRACTION = 0.60
FRAME_TABLE_MIN_PAGE_FRACTION = 0.50
REPEATED_IMAGE_MIN_PAGE_FRACTION = 0.50

# Task A5b fix round 1 (controller finding 1): a document with fewer than
# this many pages can never have a "repeated" frame_table/frame_drawing at
# all, no matter how high FRAME_TABLE_MIN_PAGE_FRACTION's *fraction* is
# satisfied -- a single large drawing/table on a 1-page document trivially
# "repeats" on 100% of that one page, and on a 2-page document a drawing on
# just page 1 already clears the 50% fraction. Both are real documents A5b's
# original fraction-only gate would have silently misclassified as page
# furniture on the strength of a single occurrence. Requiring at least
# FRAME_MIN_PAGE_COUNT independent occurrences is a second, page-count-based
# gate alongside the fraction, applied identically by both
# _find_frame_tables and _find_frame_drawings (one named constant, so they
# can't drift apart from each other).
FRAME_MIN_PAGE_COUNT = 3

# Task A5b: a single vector drawing (page.get_drawings()) whose own bbox
# covers more than FRAME_TABLE_MIN_AREA_FRACTION of the page, repeating at
# (approximately) the same bbox on at least FRAME_TABLE_MIN_PAGE_FRACTION of
# pages -- the same two thresholds _find_frame_tables uses, reused rather
# than duplicated under a new name since the brief specifies the identical
# 60%/50% values. This is what lets lib/figures.py identify a page-frame
# border BY REPETITION instead of by size alone: a plain unruled c.rect()
# border (this plugin's furniture_sample.pdf fixture, and presumably many
# real documents) is invisible to pdfplumber's table heuristics
# (_find_frame_tables), so frame_tables alone was never enough -- but a
# genuinely large, one-off real diagram that happens to be large is NOT a
# frame_drawing, because it doesn't repeat.


def document_body_size(document) -> float:
    """The document's dominant running-text font size, character-weighted
    across every page. Computed once, document-wide, because a per-page
    median is unstable on sparse pages (a page with only a heading and one
    caption line has no reliable "body" sample of its own) — extract_text.py
    uses this as a stable reference for classifying headings by relative
    size instead of recomputing it per page."""
    weighted_sizes = []
    for page in document:
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text_len = len(span["text"].strip())
                    if text_len:
                        weighted_sizes.extend([span["size"]] * text_len)
    return statistics.median(weighted_sizes) if weighted_sizes else 0.0


def classify_page(page) -> dict:
    text = page.get_text("text")
    non_ws = len(text.strip())
    image_count = len(page.get_images(full=True))
    text_ratio = min(1.0, non_ws / 500) if non_ws else 0.0

    if non_ws >= TEXT_CHAR_THRESHOLD:
        return {
            "tier": "text",
            "text_ratio": round(text_ratio, 3),
            "image_count": image_count,
            "reason": "native text layer present",
        }
    return {
        "tier": "ocr",
        "text_ratio": round(text_ratio, 3),
        "image_count": image_count,
        "reason": "no extractable text, likely scanned",
    }


def _find_repeated_lines(document) -> tuple[list[dict], dict]:
    """Text lines whose digit-masked form repeats, at the same document
    edge, on at least LINE_PATTERN_MIN_PAGE_FRACTION of pages.

    Returns `(line_patterns, occurrences)` -- `occurrences` maps each kept
    (masked_text, edge) key to its per-page raw text and y-position, so
    `_furniture_text_for_first_page` can reuse it without a second pass."""
    page_count = document.page_count
    occurrences: dict[tuple[str, str], dict] = {}

    for page_number, page in enumerate(document, start=1):
        height = page.rect.height
        if height <= 0:
            continue
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                text = "".join(span["text"] for span in line["spans"]).strip()
                if not text:
                    continue
                y0, y1 = line["bbox"][1], line["bbox"][3]
                y_top_frac = y0 / height
                y_bottom_frac = y1 / height

                edge = furniture_lib.furniture_edge(y0, y1, height)
                if edge is None:
                    continue

                masked = furniture_lib.mask_digits(text)
                key = (masked, edge)
                entry = occurrences.setdefault(
                    key, {"pages": {}, "y_mins": [], "y_maxs": []}
                )
                # (raw text, top-of-line y fraction) -- the y fraction lets
                # furniture_text order same-page lines top-to-bottom later.
                entry["pages"][page_number] = (text, y_top_frac)
                entry["y_mins"].append(y_top_frac)
                entry["y_maxs"].append(y_bottom_frac)

    line_patterns = []
    kept_occurrences = {}
    for (masked, edge), entry in sorted(occurrences.items()):
        matched_page_count = len(entry["pages"])
        if page_count and matched_page_count / page_count >= LINE_PATTERN_MIN_PAGE_FRACTION:
            line_patterns.append(
                {
                    "masked": masked,
                    "edge": edge,
                    "y_min": round(min(entry["y_mins"]), 4),
                    "y_max": round(max(entry["y_maxs"]), 4),
                    "page_count": matched_page_count,
                }
            )
            kept_occurrences[(masked, edge)] = entry

    line_patterns.sort(key=lambda p: (p["edge"], p["y_min"]))
    return line_patterns, kept_occurrences


def _find_frame_tables(pdf_path: Path, page_count: int) -> list[dict]:
    """Tables (per pdfplumber's `find_tables()`) whose bbox covers more than
    FRAME_TABLE_MIN_AREA_FRACTION of the page area, and that repeat at
    (approximately) the same bbox on at least FRAME_TABLE_MIN_PAGE_FRACTION
    of pages AND at least FRAME_MIN_PAGE_COUNT distinct pages (both gates
    must hold -- see that constant's docstring for why the fraction alone
    isn't enough on a short document). A plain ruled rectangle with no
    internal lines is often not detected as a table at all by pdfplumber's
    heuristics -- that's a legitimate empty result, not a bug."""
    groups: list[dict] = []  # [{"bboxes": [...], "pages": set()}]

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_area = page.width * page.height
            if page_area <= 0:
                continue
            try:
                tables = page.find_tables()
            except Exception:
                tables = []
            for table in tables:
                bbox = table.bbox
                area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
                if area / page_area <= FRAME_TABLE_MIN_AREA_FRACTION:
                    continue

                group = next(
                    (g for g in groups if furniture_lib.bbox_matches(g["bboxes"][0], bbox, furniture_lib.FRAME_GROUP_TOLERANCE)),
                    None,
                )
                if group is None:
                    group = {"bboxes": [], "pages": set()}
                    groups.append(group)
                group["bboxes"].append(bbox)
                group["pages"].add(page.page_number)

    frame_tables = []
    for group in groups:
        matched_page_count = len(group["pages"])
        if (
            page_count
            and matched_page_count >= FRAME_MIN_PAGE_COUNT
            and matched_page_count / page_count >= FRAME_TABLE_MIN_PAGE_FRACTION
        ):
            n = len(group["bboxes"])
            avg_bbox = [round(sum(b[i] for b in group["bboxes"]) / n, 2) for i in range(4)]
            frame_tables.append({"bbox": avg_bbox, "page_count": matched_page_count})
    return frame_tables


def _find_frame_drawings(document) -> list[dict]:
    """Single vector drawings (`page.get_drawings()`) whose bbox covers more
    than FRAME_TABLE_MIN_AREA_FRACTION of the page area, repeating at
    (approximately, within FRAME_GROUP_TOLERANCE) the same bbox on at
    least FRAME_TABLE_MIN_PAGE_FRACTION of pages AND at least
    FRAME_MIN_PAGE_COUNT distinct pages (both gates must hold). Mirrors
    `_find_frame_tables`'s grouping shape exactly, over a different item
    source (fitz drawings, not pdfplumber tables) -- see the constants'
    docstring above for why this exists alongside frame_tables rather than
    replacing it."""
    page_count = document.page_count
    groups: list[dict] = []  # [{"bboxes": [...], "pages": set()}]

    for page_number, page in enumerate(document, start=1):
        page_area = page.rect.width * page.rect.height
        if page_area <= 0:
            continue
        for d in page.get_drawings():
            rect = d["rect"]
            area = rect.width * rect.height
            if area / page_area <= FRAME_TABLE_MIN_AREA_FRACTION:
                continue
            bbox = [rect.x0, rect.y0, rect.x1, rect.y1]

            group = next(
                (g for g in groups if furniture_lib.bbox_matches(g["bboxes"][0], bbox, furniture_lib.FRAME_GROUP_TOLERANCE)),
                None,
            )
            if group is None:
                group = {"bboxes": [], "pages": set()}
                groups.append(group)
            group["bboxes"].append(bbox)
            group["pages"].add(page_number)

    frame_drawings = []
    for group in groups:
        matched_page_count = len(group["pages"])
        if (
            page_count
            and matched_page_count >= FRAME_MIN_PAGE_COUNT
            and matched_page_count / page_count >= FRAME_TABLE_MIN_PAGE_FRACTION
        ):
            n = len(group["bboxes"])
            avg_bbox = [round(sum(b[i] for b in group["bboxes"]) / n, 2) for i in range(4)]
            frame_drawings.append({"bbox": avg_bbox, "page_count": matched_page_count})
    return frame_drawings


def _find_repeated_drawings(document, body_pages: set[int] | None = None) -> list[dict]:
    """Every vector drawing (`page.get_drawings()`), of any size and any
    fill/stroke type, whose rect repeats (within FRAME_GROUP_TOLERANCE, same
    drawing type) on at least FRAME_TABLE_MIN_PAGE_FRACTION of the body
    pages AND on at least FRAME_MIN_PAGE_COUNT body pages.

    This finds a page frame that is drawn from many separate parts: border
    lines, title-block rules, a filled inner rect. Each part is small or
    thin, so `_find_frame_drawings` (one large drawing) misses most of them.
    Left in, the parts touch each other and the page content, and
    `cluster_drawings()` joins everything into one page-sized cluster.
    Repetition, not size, is the signal: a real figure does not sit at the
    same position on half the pages.

    `body_pages` is the set of page numbers to count (every page that is
    not a printed TOC page); None means every page. Near-identical rects
    are grouped into one entry, so the list has one entry per distinct
    repeated part, not one per occurrence. Each entry is
    `{"bbox", "type", "page_count"}`; `bbox` is the average over all
    occurrences."""
    tolerance = furniture_lib.FRAME_GROUP_TOLERANCE
    if body_pages is None:
        body_pages = set(range(1, document.page_count + 1))
    if not body_pages:
        return []

    groups: list[dict] = []  # [{"type", "bboxes": [...], "pages": set()}]
    # Grid index over the rounded-down coordinates (cell size = tolerance),
    # so each lookup checks only the neighbouring cells, not every group.
    index: dict[tuple, list[dict]] = {}

    def cell(bbox) -> tuple:
        return tuple(math.floor(v / tolerance) for v in bbox)

    for page_number, page in enumerate(document, start=1):
        if page_number not in body_pages:
            continue
        for d in page.get_drawings():
            rect = d["rect"]
            bbox = [rect.x0, rect.y0, rect.x1, rect.y1]
            dtype = d.get("type")
            base = cell(bbox)
            group = None
            for offset in itertools.product((-1, 0, 1), repeat=4):
                key = (dtype, *(c + o for c, o in zip(base, offset)))
                group = next(
                    (g for g in index.get(key, []) if furniture_lib.bbox_matches(g["bboxes"][0], bbox, tolerance)),
                    None,
                )
                if group is not None:
                    break
            if group is None:
                group = {"type": dtype, "bboxes": [], "pages": set()}
                groups.append(group)
                index.setdefault((dtype, *base), []).append(group)
            group["bboxes"].append(bbox)
            group["pages"].add(page_number)

    repeated = []
    for group in groups:
        matched_page_count = len(group["pages"])
        if (
            matched_page_count >= FRAME_MIN_PAGE_COUNT
            and matched_page_count / len(body_pages) >= FRAME_TABLE_MIN_PAGE_FRACTION
        ):
            n = len(group["bboxes"])
            avg_bbox = [round(sum(b[i] for b in group["bboxes"]) / n, 2) for i in range(4)]
            repeated.append({"bbox": avg_bbox, "type": group["type"], "page_count": matched_page_count})
    repeated.sort(key=lambda r: (r["bbox"][1], r["bbox"][0], r["bbox"][3], r["bbox"][2]))
    return repeated


def _find_repeated_images(document) -> list[int]:
    """Image xrefs (PyMuPDF's `page.get_images(full=True)`) present on at
    least REPEATED_IMAGE_MIN_PAGE_FRACTION of pages."""
    page_count = document.page_count
    xref_pages: dict[int, set] = {}
    for page_number, page in enumerate(document, start=1):
        for image in page.get_images(full=True):
            xref = image[0]
            xref_pages.setdefault(xref, set()).add(page_number)

    return sorted(
        xref
        for xref, pages in xref_pages.items()
        if page_count and len(pages) / page_count >= REPEATED_IMAGE_MIN_PAGE_FRACTION
    )


def _furniture_text_for_first_page(line_occurrences: dict) -> str | None:
    """Verbatim (unmasked) text of the furniture lines as found on the first
    page of the document, top-to-bottom, newline-joined. `None` if no line
    furniture was detected at all."""
    if not line_occurrences:
        return None

    first_page_lines = [
        entry["pages"][1] for entry in line_occurrences.values() if 1 in entry["pages"]
    ]
    if not first_page_lines:
        return None

    first_page_lines.sort(key=lambda text_and_y: text_and_y[1])
    return "\n".join(text for text, _y in first_page_lines)


def detect_furniture(document, pdf_path: Path, body_pages: set[int] | None = None) -> tuple[dict, str | None]:
    """Runs once per document (not per page): finds repeated header/footer
    lines, repeated full-page-covering tables and drawings, repeated
    drawings of any size (counted over `body_pages`, see
    `_find_repeated_drawings`), and repeated images. Returns
    `(furniture, furniture_text)` for folding into triage.json."""
    line_patterns, line_occurrences = _find_repeated_lines(document)
    frame_tables = _find_frame_tables(pdf_path, document.page_count)
    frame_drawings = _find_frame_drawings(document)
    repeated_drawings = _find_repeated_drawings(document, body_pages)
    image_xrefs = _find_repeated_images(document)

    furniture = {
        "line_patterns": line_patterns,
        "frame_tables": frame_tables,
        "frame_drawings": frame_drawings,
        "repeated_drawings": repeated_drawings,
        "image_xrefs": image_xrefs,
    }
    furniture_text = _furniture_text_for_first_page(line_occurrences)
    return furniture, furniture_text


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", required=True, help="document name (without .pdf)")
    args = parser.parse_args()

    pdf_path = paths.input_pdf(args.doc)
    if not pdf_path.exists():
        print(f"error: {pdf_path} not found", file=sys.stderr)
        sys.exit(1)

    document = fitz.open(pdf_path)
    pages = []
    for i, page in enumerate(document, start=1):
        classification = classify_page(page)
        pages.append({"page_number": i, **classification})
    body_size = document_body_size(document)
    toc_entries, toc_pages, toc_unparsed = toc_lib.detect_toc_with_unparsed(document)
    body_pages = {p["page_number"] for p in pages} - set(toc_pages)
    furniture, furniture_text = detect_furniture(document, pdf_path, body_pages)
    document.close()

    for page in pages:
        if page["page_number"] in toc_pages:
            page["role"] = "toc"

    loop_size = "tight" if any(p["tier"] != "text" for p in pages) else "loose"
    result = {
        "doc": args.doc,
        "page_count": len(pages),
        "pages": pages,
        "loop_size": loop_size,
        "body_size": round(body_size, 1),
        "furniture": furniture,
        "furniture_text": furniture_text,
    }

    out_path = paths.triage_json(args.doc)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))

    toc_out_path = paths.toc_json(args.doc)
    toc_out_path.parent.mkdir(parents=True, exist_ok=True)
    toc_out_path.write_text(
        json.dumps({"doc": args.doc, "entries": toc_entries, "unparsed": toc_unparsed}, indent=2)
    )


if __name__ == "__main__":
    main()
