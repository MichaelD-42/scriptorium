#!/usr/bin/env python3
"""Classify each page of a PDF into an extraction tier (text|ocr) and the
document into a loop size (tight|loose). See README.md for the schema."""

import argparse
import itertools
import json
import math
import statistics
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import furniture as furniture_lib  # noqa: E402
import paths  # noqa: E402
import toc as toc_lib  # noqa: E402

import fitz  # PyMuPDF
import pdfplumber

TEXT_CHAR_THRESHOLD = 20  # fewer non-whitespace chars than this => treat page as scanned
# Preflight: a text layer that exists but cannot be used. GARBLED_MIN_FRACTION
# is the share of non-whitespace chars that are control codes, U+FFFD or
# private-use glyphs: a font with no usable ToUnicode map reads out glyph ids
# ("2VBSUFSMZ\x01SFQPSU" for "Quarterly report"). Real text has almost none;
# Word's private-use list bullets stay near 2%. A page covered at least
# SCAN_MIN_IMAGE_FRACTION by images with fewer than SCAN_MAX_TEXT_CHARS of
# text is a scan with a digital stamp or header on it: the text tier would
# extract the stamp and drop the scanned body.
GARBLED_MIN_FRACTION = 0.10
SCAN_MIN_IMAGE_FRACTION = 0.50
SCAN_MAX_TEXT_CHARS = 200

# Furniture thresholds (see README.md). The edge band and the bbox
# tolerances are in lib/furniture.py: FURNITURE_EDGE_BAND (top/bottom 12% of
# the page height) and FRAME_GROUP_TOLERANCE (2pt, the grouping tolerance
# used here to decide whether two pages' bboxes are the same frame; see that
# module for why the later matching tolerance is 3pt).
LINE_PATTERN_MIN_PAGE_FRACTION = 0.60
# A line on one page only is not repeated, even when that is 100% of a
# one-page document; assemble.py never renders furniture_text, so a wrong
# match is lost from the output.
LINE_PATTERN_MIN_PAGE_COUNT = 2
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


def _image_area_fraction(page) -> float:
    """Share of the page area covered by placed images, capped at 1.0
    (overlapping images are counted twice)."""
    page_area = page.rect.width * page.rect.height
    if page_area <= 0:
        return 0.0
    covered = sum(abs(fitz.Rect(info["bbox"]) & page.rect) for info in page.get_image_info())
    return min(1.0, covered / page_area)


def _garbled_fraction(text: str) -> float:
    chars = [ch for ch in text if not ch.isspace()]
    if not chars:
        return 0.0
    bad = sum(1 for ch in chars if ch == "\ufffd" or unicodedata.category(ch) in ("Cc", "Co"))
    return bad / len(chars)


def classify_page(page) -> dict:
    text = page.get_text("text")
    non_ws = len(text.strip())
    image_count = len(page.get_images(full=True))
    text_ratio = min(1.0, non_ws / 500) if non_ws else 0.0

    if non_ws >= TEXT_CHAR_THRESHOLD:
        reason = "native text layer present"
        tier = "text"
        garbled = _garbled_fraction(text)
        image_fraction = _image_area_fraction(page)
        if garbled >= GARBLED_MIN_FRACTION:
            tier, reason = "ocr", f"text layer garbled ({garbled:.0%} unmappable glyphs)"
        elif non_ws < SCAN_MAX_TEXT_CHARS and image_fraction >= SCAN_MIN_IMAGE_FRACTION:
            tier, reason = "ocr", f"image covers {image_fraction:.0%} of the page with only {non_ws} text chars, likely a stamped scan"
        return {
            "tier": tier,
            "text_ratio": round(text_ratio, 3),
            "image_count": image_count,
            "reason": reason,
        }
    return {
        "tier": "ocr",
        "text_ratio": round(text_ratio, 3),
        "image_count": image_count,
        "reason": "no extractable text, likely scanned",
    }


def _find_repeated_lines(document, rect_furniture: dict | None = None) -> tuple[list[dict], dict]:
    """Text lines whose furniture key (`furniture_lib.furniture_key`: no
    whitespace, digit runs as "#") repeats, at the same document edge, on at
    least LINE_PATTERN_MIN_PAGE_FRACTION of pages. `rect_furniture` holds
    `content_rect` and `content_rect_page_size`; each page's bands use
    `furniture_lib.page_content_rect` (re-review 2 I2).

    Returns `(line_patterns, occurrences)` -- `occurrences` maps each kept
    (masked_text, edge) key to its per-page raw text and y-position, so
    `_furniture_text_for_first_page` can reuse it without a second pass."""
    page_count = document.page_count
    occurrences: dict[tuple[str, str], dict] = {}

    for page_number, page in enumerate(document, start=1):
        height = page.rect.height
        if height <= 0:
            continue
        content_rect = furniture_lib.page_content_rect(rect_furniture, page.rect.width, height)
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

                edge = furniture_lib.furniture_edge(y0, y1, height, content_rect)
                if edge is None:
                    continue

                masked = furniture_lib.furniture_key(text)
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
        if (
            page_count
            and matched_page_count >= LINE_PATTERN_MIN_PAGE_COUNT
            and matched_page_count / page_count >= LINE_PATTERN_MIN_PAGE_FRACTION
        ):
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


def _frame_table_candidate_pages(document) -> set[int]:
    """Pages whose vector drawings span more than FRAME_TABLE_MIN_AREA_FRACTION
    of the page. pdfplumber's default "lines" strategy builds tables only
    from ruling lines and rects, so a page whose drawings all fit in a smaller
    box cannot hold a frame table, and `find_tables()` (most of triage's
    run time) is skipped there."""
    snap = 3  # pt, pdfplumber's default snap/join tolerance
    candidates = set()
    for page_number, page in enumerate(document, start=1):
        page_area = page.rect.width * page.rect.height
        extent = fitz.Rect()
        for d in page.get_drawings():
            extent |= d["rect"]
        if page_area > 0 and not extent.is_empty:
            extent = fitz.Rect(extent.x0 - snap, extent.y0 - snap, extent.x1 + snap, extent.y1 + snap)
            if extent.width * extent.height / page_area > FRAME_TABLE_MIN_AREA_FRACTION:
                candidates.add(page_number)
    return candidates


def _repeating_groups(items, page_total: int, min_fraction: float) -> list[dict]:
    """Group `(page_number, bbox, kind)` items whose bboxes match within
    FRAME_GROUP_TOLERANCE (same kind), and keep the groups found on at
    least FRAME_MIN_PAGE_COUNT pages AND at least `min_fraction` of
    `page_total` pages. Each kept group is `{"bbox", "kind", "page_count"}`;
    `bbox` is the average over all occurrences."""
    tolerance = furniture_lib.FRAME_GROUP_TOLERANCE
    groups: list[dict] = []  # [{"kind", "bboxes": [...], "pages": set()}]
    # Grid index over the rounded-down coordinates (cell size = tolerance),
    # so each lookup checks only the neighbouring cells, not every group.
    index: dict[tuple, list[dict]] = {}

    def cell(bbox) -> tuple:
        return tuple(math.floor(v / tolerance) for v in bbox)

    for page_number, bbox, kind in items:
        base = cell(bbox)
        group = None
        for offset in itertools.product((-1, 0, 1), repeat=4):
            key = (kind, *(c + o for c, o in zip(base, offset)))
            group = next(
                (g for g in index.get(key, []) if furniture_lib.bbox_matches(g["bboxes"][0], bbox, tolerance)),
                None,
            )
            if group is not None:
                break
        if group is None:
            group = {"kind": kind, "bboxes": [], "pages": set()}
            groups.append(group)
            index.setdefault((kind, *base), []).append(group)
        group["bboxes"].append(bbox)
        group["pages"].add(page_number)

    kept = []
    for group in groups:
        matched_page_count = len(group["pages"])
        if (
            page_total
            and matched_page_count >= FRAME_MIN_PAGE_COUNT
            and matched_page_count / page_total >= min_fraction
        ):
            n = len(group["bboxes"])
            avg_bbox = [round(sum(b[i] for b in group["bboxes"]) / n, 2) for i in range(4)]
            kept.append({"bbox": avg_bbox, "kind": group["kind"], "page_count": matched_page_count})
    return kept


def _find_frame_tables(pdf_path: Path, page_count: int, candidate_pages: set[int] | None = None) -> list[dict]:
    """Tables (per pdfplumber's `find_tables()`) whose bbox covers more than
    FRAME_TABLE_MIN_AREA_FRACTION of the page area, and that repeat at
    (approximately) the same bbox on at least FRAME_TABLE_MIN_PAGE_FRACTION
    of pages AND at least FRAME_MIN_PAGE_COUNT distinct pages (both gates
    must hold -- see that constant's docstring for why the fraction alone
    isn't enough on a short document). A plain ruled rectangle with no
    internal lines is often not detected as a table at all by pdfplumber's
    heuristics -- that's a legitimate empty result, not a bug."""
    items = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_number in sorted(candidate_pages) if candidate_pages is not None else range(1, page_count + 1):
            page = pdf.pages[page_number - 1]
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
                if area / page_area > FRAME_TABLE_MIN_AREA_FRACTION:
                    items.append((page_number, list(bbox), None))
    return [
        {"bbox": g["bbox"], "page_count": g["page_count"]}
        for g in _repeating_groups(items, page_count, FRAME_TABLE_MIN_PAGE_FRACTION)
    ]


def _find_frame_drawings(document) -> list[dict]:
    """Single vector drawings (`page.get_drawings()`) whose bbox covers more
    than FRAME_TABLE_MIN_AREA_FRACTION of the page area, repeating at
    (approximately, within FRAME_GROUP_TOLERANCE) the same bbox on at
    least FRAME_TABLE_MIN_PAGE_FRACTION of pages AND at least
    FRAME_MIN_PAGE_COUNT distinct pages (both gates must hold). The same
    test as `_find_frame_tables`, over fitz drawings instead of pdfplumber
    tables -- see the constants' docstring above for why this exists
    alongside frame_tables rather than replacing it."""
    items = []
    for page_number, page in enumerate(document, start=1):
        page_area = page.rect.width * page.rect.height
        if page_area <= 0:
            continue
        for d in page.get_drawings():
            rect = d["rect"]
            if rect.width * rect.height / page_area > FRAME_TABLE_MIN_AREA_FRACTION:
                items.append((page_number, [rect.x0, rect.y0, rect.x1, rect.y1], None))
    return [
        {"bbox": g["bbox"], "page_count": g["page_count"]}
        for g in _repeating_groups(items, document.page_count, FRAME_TABLE_MIN_PAGE_FRACTION)
    ]


def _find_repeated_drawings(document, body_pages: set[int] | None = None) -> list[dict]:
    """Every vector drawing (`page.get_drawings()`), of any size and any
    fill/stroke type, whose rect repeats (within FRAME_GROUP_TOLERANCE, same
    drawing type) on at least furniture_lib.REPEATED_DRAWING_MIN_PAGE_FRACTION
    (80%) of the body pages AND on at least FRAME_MIN_PAGE_COUNT body pages.

    This finds a page frame that is drawn from many separate parts: border
    lines, title-block rules, a filled inner rect. Each part is small or
    thin, so `_find_frame_drawings` (one large drawing) misses most of them.
    Left in, the parts touch each other and the page content, and
    `cluster_drawings()` joins everything into one page-sized cluster.
    Repetition, not size, is the signal. The fraction is 80%, not the 50%
    of the other furniture lists: a figure can recur at one position on a
    few pages of a short document (4 of 6 pages is 67%), but real frame
    parts sit on nearly every body page.

    `body_pages` is the set of page numbers to count (every page that is
    not a printed TOC page); None means every page. Near-identical rects
    are grouped into one entry, so the list has one entry per distinct
    repeated part, not one per occurrence. Each entry is
    `{"bbox", "type", "page_count"}`; `bbox` is the average over all
    occurrences."""
    if body_pages is None:
        body_pages = set(range(1, document.page_count + 1))
    items = [
        (page_number, [d["rect"].x0, d["rect"].y0, d["rect"].x1, d["rect"].y1], d.get("type"))
        for page_number, page in enumerate(document, start=1)
        if page_number in body_pages
        for d in page.get_drawings()
    ]
    repeated = [
        {"bbox": g["bbox"], "type": g["kind"], "page_count": g["page_count"]}
        for g in _repeating_groups(items, len(body_pages), furniture_lib.REPEATED_DRAWING_MIN_PAGE_FRACTION)
    ]
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


def _page_line_bboxes(document, body_pages: set[int] | None) -> dict[int, list[list[float]]]:
    """{body page number: [text line bbox, ...]}, for
    `furniture_lib.find_content_rect`'s inner-rect test (follow-up R13)."""
    found = {}
    for page_number, page in enumerate(document, start=1):
        if body_pages is not None and page_number not in body_pages:
            continue
        found[page_number] = [
            list(line["bbox"])
            for block in page.get_text("dict").get("blocks", [])
            if block.get("type") == 0
            for line in block.get("lines", [])
            if "".join(span["text"] for span in line.get("spans", [])).strip()
        ]
    return found


def _body_page_size(document, body_pages: set[int] | None) -> tuple[float, float] | None:
    """The most common (width, height) of the body pages (all pages when
    `body_pages` is None, the first such size on a tie), or None for an
    empty document."""
    counts: dict[tuple[float, float], int] = {}
    for page_number, page in enumerate(document, start=1):
        if body_pages is not None and page_number not in body_pages:
            continue
        size = (round(page.rect.width, 1), round(page.rect.height, 1))
        counts[size] = counts.get(size, 0) + 1
    if not counts and document.page_count:
        first = document[0].rect
        return first.width, first.height
    return max(counts, key=counts.get) if counts else None


def detect_furniture(document, pdf_path: Path, body_pages: set[int] | None = None) -> tuple[dict, str | None]:
    """Runs once per document (not per page): finds repeated header/footer
    lines, repeated full-page-covering tables and drawings, repeated
    drawings of any size (counted over `body_pages`, see
    `_find_repeated_drawings`), and repeated images. Returns
    `(furniture, furniture_text)` for folding into triage.json."""
    frame_tables = _find_frame_tables(pdf_path, document.page_count, _frame_table_candidate_pages(document))
    frame_drawings = _find_frame_drawings(document)
    repeated_drawings = _find_repeated_drawings(document, body_pages)
    image_xrefs = _find_repeated_images(document)
    # Follow-up R10: a repeated inner frame rect moves the bands to the page
    # area outside it, so the line search runs after the drawing search.
    # Re-review 2 I2: the rect is measured on the most common body page
    # size, and that size is stored with it (furniture.page_content_rect).
    page_size = _body_page_size(document, body_pages)
    content_rect = (
        furniture_lib.find_content_rect(
            frame_drawings, repeated_drawings,
            len(body_pages) if body_pages is not None else document.page_count,
            page_size[0], page_size[1],
            _page_line_bboxes(document, body_pages),
        )
        if page_size is not None
        else None
    )
    content_rect_page_size = [page_size[0], page_size[1]] if content_rect else None
    line_patterns, line_occurrences = _find_repeated_lines(
        document, {"content_rect": content_rect, "content_rect_page_size": content_rect_page_size}
    )

    furniture = {
        "line_patterns": line_patterns,
        "frame_tables": frame_tables,
        "frame_drawings": frame_drawings,
        "repeated_drawings": repeated_drawings,
        "image_xrefs": image_xrefs,
        "content_rect": content_rect,
        "content_rect_page_size": content_rect_page_size,
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

    try:
        document = fitz.open(pdf_path)
    except RuntimeError as e:  # pymupdf.FileDataError: not a PDF, or damaged beyond repair
        print(f"error: {pdf_path} cannot be opened as a PDF ({e})", file=sys.stderr)
        sys.exit(1)
    try:
        # MuPDF repairs a damaged file silently; pdfminer (pdfplumber, used by
        # extract-images) does not, and would fail mid-run instead of here.
        with pdfplumber.open(pdf_path) as pdf:
            pdf.pages[0]
    except Exception as e:
        print(
            f"error: {pdf_path} is damaged ({type(e).__name__}); "
            "a re-saved copy (e.g. `mutool clean in.pdf out.pdf`) may work",
            file=sys.stderr,
        )
        sys.exit(1)
    if document.needs_pass:
        print(f"error: {pdf_path} is password-protected", file=sys.stderr)
        sys.exit(1)
    if document.page_count == 0:
        print(f"error: {pdf_path} has no pages", file=sys.stderr)
        sys.exit(1)
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
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8", newline="")
    # Context-rot rule: the orchestrator reads this stdout, so it gets a
    # summary sized by the pages it must act on, not the whole triage.json.
    summary = {
        "doc": args.doc,
        "page_count": len(pages),
        "loop_size": loop_size,
        "body_size": result["body_size"],
        "non_text_pages": {str(p["page_number"]): p["tier"] for p in pages if p["tier"] != "text"},
        "triage_json": str(out_path),
    }
    print(json.dumps(summary, indent=2))

    toc_out_path = paths.toc_json(args.doc)
    toc_out_path.parent.mkdir(parents=True, exist_ok=True)
    toc_out_path.write_text(
        json.dumps({"doc": args.doc, "entries": toc_entries, "unparsed": toc_unparsed}, indent=2), encoding="utf-8", newline=""
    )


if __name__ == "__main__":
    main()
