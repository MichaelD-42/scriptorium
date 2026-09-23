#!/usr/bin/env python3
"""Extract native text (headings/paragraphs) and tables for tier-1 pages.
See SKILL.md."""

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import elements as elements_lib  # noqa: E402
import figures as figures_lib  # noqa: E402
import paths  # noqa: E402
import toc as toc_lib  # noqa: E402

import fitz  # PyMuPDF
import pdfplumber

# Furniture removal (Task A2) -- reads triage.json["furniture"], written by
# pdf-triage's detect_furniture(). FURNITURE_EDGE_BAND matches triage.py's
# constant of the same name; FRAME_TABLE_BBOX_TOLERANCE is a looser,
# independent "couple points" tolerance for matching a pdfplumber-found
# table against a frame_tables bbox that may be an average across pages.
FURNITURE_EDGE_BAND = 0.12
FRAME_TABLE_BBOX_TOLERANCE = 3.0  # pt

EMPTY_FURNITURE = {"line_patterns": [], "frame_tables": [], "image_xrefs": []}


def load_furniture(doc: str) -> dict:
    """triage.json["furniture"], or an empty/no-op default if triage hasn't
    run for this document (or predates furniture detection) -- extract_text.py
    must still work standalone, per its own docstring."""
    triage_path = paths.triage_json(doc)
    if not triage_path.exists():
        return dict(EMPTY_FURNITURE)
    triage = json.loads(triage_path.read_text())
    return triage.get("furniture", dict(EMPTY_FURNITURE))


def load_page_roles(doc: str) -> dict[int, str]:
    """{page_number: role} for every page triage.py marked with a non-default
    role (currently only "toc") -- empty dict if triage hasn't run for this
    document (extract_text.py must still work standalone)."""
    triage_path = paths.triage_json(doc)
    if not triage_path.exists():
        return {}
    triage = json.loads(triage_path.read_text())
    return {p["page_number"]: p["role"] for p in triage.get("pages", []) if p.get("role")}


def load_toc_entries(doc: str) -> list[dict]:
    """toc.json's `entries` list (Task A3's `lib/toc.py`/`pdf-triage`
    output) -- empty list if `toc.json` doesn't exist (triage hasn't run) or
    this document has none (no printed TOC, no outline). Drives Task A4's
    TOC-driven heading classification; extract_text.py must still work
    standalone without it, same convention as `load_furniture`/
    `load_page_roles` above."""
    toc_path = paths.toc_json(doc)
    if not toc_path.exists():
        return []
    return json.loads(toc_path.read_text()).get("entries", [])


def build_toc_heading_lookup(toc_entries: list[dict]) -> dict[str, int]:
    """{normalize_toc_text(entry's "number + title" text): entry["level"]}
    -- the primary (TOC-driven) heading-classification table. Empty exactly
    when this document has no TOC entries at all, which is what signals
    `classify_heading_level` to use the fallback (rank-by-size) path
    instead."""
    lookup = {}
    for entry in toc_entries:
        key = toc_lib.normalize_toc_text(toc_lib.toc_entry_heading_text(entry))
        lookup[key] = entry["level"]
    return lookup


def is_frame_table(bbox, frame_tables: list[dict]) -> bool:
    """True if `bbox` (a pdfplumber table bbox) matches one of
    triage.json["furniture"]["frame_tables"] within FRAME_TABLE_BBOX_TOLERANCE
    -- these are page frames, not real tables, and must never become a
    `table` element."""
    return any(
        all(abs(a - b) <= FRAME_TABLE_BBOX_TOLERANCE for a, b in zip(bbox, ft["bbox"]))
        for ft in frame_tables
    )


def in_furniture_band(bbox, page_height: float) -> bool:
    """True if `bbox` (a fitz-style [x0, y0, x1, y1]) falls inside the top or
    bottom FURNITURE_EDGE_BAND of the page -- same bands pdf-triage's
    _find_repeated_lines() used to find the patterns in the first place."""
    if page_height <= 0:
        return False
    top_frac, bottom_frac = bbox[1] / page_height, bbox[3] / page_height
    return bottom_frac <= FURNITURE_EDGE_BAND or top_frac >= 1 - FURNITURE_EDGE_BAND


def furniture_filtered_lines(block: dict, furniture_masked: set[str], page_height: float) -> list[dict]:
    """The subset of `block["lines"]` that survive furniture filtering.

    A line is dropped only if the block sits in a top/bottom edge band
    *and* that specific line's digit-masked text matches a known furniture
    line pattern -- matched lines are the unit of exclusion, not the whole
    block. A block that mixes one furniture-matching line with unrelated
    real content on an adjacent line (e.g. PyMuPDF merging a footer note
    next to a page number into one block) keeps its real line(s); the whole
    block is only dropped if every one of its lines matches (the caller
    sees an empty list back). A block outside the edge band, or one with no
    matching lines, is returned unchanged."""
    if not furniture_masked or not in_furniture_band(block["bbox"], page_height):
        return block["lines"]
    return [line for line in block["lines"] if line["masked"] not in furniture_masked]


def figure_region_filtered_lines(lines: list[dict], figure_regions: list[dict]) -> list[dict]:
    """The subset of `lines` that do NOT fall inside any of this page's
    figure regions (Task A5, `lib/figures.py`'s `detect_figure_regions`).
    Same per-line-is-the-unit-of-exclusion shape as `furniture_filtered_lines`
    -- a block that mixes a figure-region line (e.g. a diagram box's "Start"
    label) with unrelated surrounding paragraph text on an adjacent line
    keeps its real line(s). Excluded lines are exactly the ones
    `extract_images.py`'s `figure_text_for_region` collects for the
    matching image element, via the same `figures_lib.line_in_region` test,
    so a line is never dropped here without also appearing there, and never
    duplicated as both a `paragraph` and part of `figure_text`."""
    if not figure_regions:
        return lines
    return [
        line for line in lines
        if not any(figures_lib.line_in_region(line["bbox"], region["bbox"]) for region in figure_regions)
    ]


def caption_filtered_lines(lines: list[dict], caption_bboxes: set[tuple]) -> list[dict]:
    """The subset of `lines` whose bbox does NOT exactly match one of this
    page's caption lines (Task A6, `lib/figures.py`'s `find_caption_line`,
    called once per image bbox -- vector region or bitmap -- in `main()`).
    Same per-line-is-the-unit-of-exclusion shape as
    `furniture_filtered_lines`/`figure_region_filtered_lines`. `caption`
    is script-authoritative on the matching image element now, so the
    caption text must not also survive as a `paragraph`/`heading` element."""
    if not caption_bboxes:
        return lines
    return [line for line in lines if tuple(line["bbox"]) not in caption_bboxes]


def build_block_element(
    block: dict,
    kept_lines: list[dict],
    body_size: float,
    toc_lookup: dict[str, int],
    heading_size_ranks: dict[float, int],
) -> dict | None:
    """Reassemble a `heading`/`paragraph` element from `kept_lines` (a
    possibly-trimmed subset of `block["lines"]`, per `furniture_filtered_lines`).
    Returns None if nothing survived (the whole block was furniture).

    When lines were dropped, the bbox and heading-classification size are
    recomputed from just the surviving lines, so a partially-furniture
    block doesn't keep reporting the discarded line's geometry/size."""
    if not kept_lines:
        return None
    if len(kept_lines) == len(block["lines"]):
        bbox = list(block["bbox"])  # nothing dropped -- keep PyMuPDF's own block bbox
    else:
        bbox = [
            min(line["bbox"][0] for line in kept_lines),
            min(line["bbox"][1] for line in kept_lines),
            max(line["bbox"][2] for line in kept_lines),
            max(line["bbox"][3] for line in kept_lines),
        ]
    text = " ".join(line["text"] for line in kept_lines)
    max_size = max(line["max_size"] for line in kept_lines)
    is_bold_block = all(line["bold"] for line in kept_lines)

    level = classify_heading_level(text, is_bold_block, max_size, body_size, toc_lookup, heading_size_ranks)
    if level:
        return {"type": "heading", "level": level, "text": text, "bbox": bbox}
    return {"type": "paragraph", "text": text, "bbox": bbox}


def bbox_overlap_ratio(a, b) -> float:
    """Fraction of bbox a's area covered by bbox b."""
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    area_a = max(1e-6, (ax1 - ax0) * (ay1 - ay0))
    return inter / area_a


# Task A4: heading-level classification is TOC-driven when this document
# has TOC entries at all, with a rank-by-distinct-bold-size fallback when it
# doesn't. The old fixed-ratio thresholds (1.9/1.45/1.15) are gone --
# ranking replaces ratio comparison entirely, even in the fallback path.

# The fallback path's "does this block carry real heading text, not just a
# bullet glyph or stray mark" gate: a candidate block needs at least this
# many alphanumeric characters. "Non-glyph" is defined here as simply
# `str.isalnum()` (unicode-aware) -- a lone bullet glyph ("-", "•", or a
# private-use-area dingbat) has zero alphanumeric characters and never
# qualifies, regardless of its font size or boldness. This is the simple
# heuristic the brief calls out as an acceptable choice, over building a
# printable-character-range table.
FALLBACK_NON_GLYPH_MIN_CHARS = 3

# The fallback path ranks at most this many distinct bold-heading sizes;
# the 6th-largest and every smaller distinct size all collapse to level 6
# rather than growing unbounded.
FALLBACK_MAX_LEVELS = 6

# PyMuPDF span flag bit for bold (TEXT_FONT_BOLD). Some fonts don't set it
# reliably (e.g. non-embedded/substituted fonts), so this is combined with a
# "bold" substring check on the font name as a second, independent signal --
# both this fixture's and typical real documents' bold fonts are literally
# named e.g. "Helvetica-Bold".
_BOLD_FLAG_BIT = 16


def is_bold_span(span: dict) -> bool:
    flags = span.get("flags", 0) or 0
    font = span.get("font", "") or ""
    return bool(flags & _BOLD_FLAG_BIT) or "bold" in font.lower()


def non_glyph_char_count(text: str) -> int:
    """See FALLBACK_NON_GLYPH_MIN_CHARS -- count of alphanumeric characters
    in `text`."""
    return sum(1 for ch in text if ch.isalnum())


def is_fallback_heading_candidate(text: str, is_bold_block: bool, max_size: float, body_size: float) -> bool:
    """Fallback-path (no TOC) candidacy gate: bold, strictly larger than the
    document's body size, and carrying at least FALLBACK_NON_GLYPH_MIN_CHARS
    of real (non-glyph) text. Used both to build the document-wide size
    ranking (`document_heading_size_ranks`) and to classify each block
    against it, so the two stay consistent with each other."""
    if body_size <= 0 or not is_bold_block or max_size <= body_size:
        return False
    return non_glyph_char_count(text) >= FALLBACK_NON_GLYPH_MIN_CHARS


def document_heading_size_ranks(fitz_doc, body_size: float, furniture_masked: set[str]) -> dict[float, int]:
    """Fallback-path (no TOC) heading-level ranking: every DISTINCT font
    size used by a fallback-candidate bold block anywhere in the document
    (not just the pages this invocation's --pages batch covers), ranked
    largest-first -- the largest distinct size is level 1, the next is
    level 2, and so on, with the 6th and any smaller distinct size all
    collapsing to level 6 (FALLBACK_MAX_LEVELS) instead of growing
    unbounded.

    Scans the WHOLE document rather than just the current batch's pages on
    purpose: the elastic-loop pipeline can invoke this script once per page
    batch, as separate subprocesses, and the ranking (and therefore the
    levels a heading of a given size gets) must be identical regardless of
    which batch happens to run -- a per-batch-local ranking would disagree
    with itself across batches of the same document.

    `furniture_masked` (triage.json's furniture["line_patterns"], masked
    text -- same set the per-page loop's `furniture_filtered_lines` uses)
    is applied here too, via the same helper, before a block is even
    considered as a candidate. Fix round 1: without this, a real no-TOC
    document's bold running header/title (a plausible convention for this
    toolkit's actual RFQ-spec target documents) would itself be bold,
    larger than body size, and long enough to clear the 3-alphanumeric-
    character gate -- so it would silently consume a rank slot and shift
    every genuine heading's level down by one (or force an extra collapse
    into level 6), even though the header itself never becomes a heading
    (or any) element on its own page."""
    sizes = set()
    for page in fitz_doc:
        page_height = page.rect.height
        text_blocks, _ = extract_page_text_blocks(page, body_size)
        for block in text_blocks:
            kept_lines = furniture_filtered_lines(block, furniture_masked, page_height)
            if not kept_lines:
                continue
            text = " ".join(line["text"] for line in kept_lines)
            max_size = max(line["max_size"] for line in kept_lines)
            is_bold_block = all(line["bold"] for line in kept_lines)
            if is_fallback_heading_candidate(text, is_bold_block, max_size, body_size):
                sizes.add(max_size)
    ranked = sorted(sizes, reverse=True)
    return {size: min(i + 1, FALLBACK_MAX_LEVELS) for i, size in enumerate(ranked)}


def classify_heading_level(
    text: str,
    is_bold_block: bool,
    max_size: float,
    body_size: float,
    toc_lookup: dict[str, int],
    heading_size_ranks: dict[float, int],
) -> int | None:
    """Primary: TOC-driven, whenever this document has any TOC entries at
    all (`toc_lookup` non-empty). A block becomes a heading at its matching
    TOC entry's level only if its normalized text matches a TOC entry's
    normalized "number + title" text exactly -- no match means `paragraph`,
    no matter the block's size or boldness. This is what stops a lone
    bullet glyph, or any other large/bold text that isn't an actual
    TOC-listed heading, from being misclassified as a heading.

    Fallback: only reached when this document has zero TOC entries (no
    printed TOC, no outline) -- rank-by-distinct-bold-size instead, gated by
    `is_fallback_heading_candidate`."""
    if toc_lookup:
        return toc_lookup.get(toc_lib.normalize_toc_text(text))
    if not is_fallback_heading_candidate(text, is_bold_block, max_size, body_size):
        return None
    return heading_size_ranks.get(max_size)


def extract_page_tables(pdf_path: Path, page_number: int) -> list[dict]:
    tables = []
    with pdfplumber.open(pdf_path) as pl_doc:
        pl_page = pl_doc.pages[page_number - 1]
        for table in pl_page.find_tables():
            rows = table.extract()
            rows = [[cell if cell is not None else "" for cell in row] for row in rows]
            tables.append({"bbox": table.bbox, "rows": rows})
    return tables


def extract_page_text_blocks(page, body_size: float | None) -> tuple[list[dict], float]:
    """`body_size`, if given, comes from pdf-triage's document-wide,
    character-weighted measurement (`triage.json`'s `body_size` field) and
    is used as-is. A single page's own text is often too sparse (e.g. just
    a heading and one caption line) for a reliable per-page median, so this
    per-page fallback exists only for standalone/manual use of this script
    without triage having run first."""
    raw = page.get_text("dict")
    text_blocks = []
    sizes = []
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        lines = []
        for line in block.get("lines", []):
            spans_text = "".join(span["text"] for span in line.get("spans", []))
            stripped = spans_text.strip()
            if not stripped:
                continue
            line_max_size = 0.0
            line_spans = line.get("spans", [])
            for span in line_spans:
                sizes.append(span["size"])
                line_max_size = max(line_max_size, span["size"])
            lines.append({
                "text": stripped,
                "masked": re.sub(r"\d+", "#", stripped),
                "bbox": line["bbox"],
                "max_size": line_max_size,
                "bold": bool(line_spans) and all(is_bold_span(s) for s in line_spans),
            })
        if lines:
            text_blocks.append({"bbox": block["bbox"], "lines": lines})
    resolved_body_size = body_size if body_size else (statistics.median(sizes) if sizes else 0.0)
    return text_blocks, resolved_body_size


def resolve_document_body_size(fitz_doc) -> float:
    """Document-wide, character-weighted median body text size -- the same
    computation as `pdf-triage`'s `document_body_size()`, duplicated here
    (rather than imported cross-skill) so this script stays runnable
    standalone without triage having run, same convention as
    `load_furniture`/`load_page_roles`/`load_toc_entries` above. Only used
    to size the fallback (no-TOC) heading ranking document-wide when
    `--body-size` wasn't passed in; per-page extraction keeps its own
    existing sparser per-page fallback in `extract_page_text_blocks`,
    unchanged."""
    weighted_sizes = []
    for page in fitz_doc:
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text_len = len(span["text"].strip())
                    if text_len:
                        weighted_sizes.extend([span["size"]] * text_len)
    return statistics.median(weighted_sizes) if weighted_sizes else 0.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", required=True)
    parser.add_argument("--pages", required=True, help="comma-separated 1-indexed page numbers")
    parser.add_argument("--body-size", type=float, default=None, help="document-wide body text size from triage.json's body_size field; falls back to a per-page estimate if omitted")
    args = parser.parse_args()

    page_numbers = [int(p) for p in args.pages.split(",") if p.strip()]
    pdf_path = paths.input_pdf(args.doc)
    if not pdf_path.exists():
        print(f"error: {pdf_path} not found", file=sys.stderr)
        sys.exit(1)

    furniture = load_furniture(args.doc)
    frame_tables = furniture.get("frame_tables", [])
    furniture_masked = {p["masked"] for p in furniture.get("line_patterns", [])}
    furniture_xrefs = set(furniture.get("image_xrefs", []))
    page_roles = load_page_roles(args.doc)
    toc_lookup = build_toc_heading_lookup(load_toc_entries(args.doc))

    fitz_doc = fitz.open(pdf_path)

    # Fallback-path (no TOC) heading ranking is document-wide (see
    # document_heading_size_ranks's docstring) and only ever needed when
    # there's no TOC to drive classification instead -- skip the extra
    # whole-document scan otherwise.
    heading_size_ranks: dict[float, int] = {}
    if not toc_lookup:
        ranking_body_size = args.body_size if args.body_size else resolve_document_body_size(fitz_doc)
        heading_size_ranks = document_heading_size_ranks(fitz_doc, ranking_body_size, furniture_masked)

    for page_number in page_numbers:
        if page_roles.get(page_number) == "toc":
            # A printed TOC page carries no real content of its own -- skip
            # straight to an empty, explicitly-marked shard instead of
            # running text/table extraction on it.
            shard_path = paths.shard_path(args.doc, page_number, "text")
            elements_lib.write_shard(shard_path, page_number, [], skipped="toc")
            continue

        page = fitz_doc[page_number - 1]
        page_height = page.rect.height
        text_blocks, body_size = extract_page_text_blocks(page, args.body_size)
        tables = extract_page_tables(pdf_path, page_number)
        # Drop page-frame tables (furniture, not real content) before doing
        # anything else with the table list -- must happen before the
        # overlap-drop below, or a frame "table" would swallow real text
        # blocks that merely sit underneath it.
        tables = [t for t in tables if not is_frame_table(t["bbox"], frame_tables)]
        # Task A5: figure regions detected the same way extract_images.py
        # detects them (same shared helper, so the two scripts can never
        # disagree about where a page's figures are) -- their text-layer
        # lines belong to figure_text, not to a paragraph/heading element.
        figure_regions = figures_lib.detect_figure_regions(page, page_number, pdf_path, frame_tables)

        # Task A6: caption lines -- one find_caption_line() search per
        # image bbox on the page (every vector region above, plus every
        # bitmap placement), the exact same universe extract_images.py
        # turns into `image` elements and searches for a caption against.
        # A matched line's bbox is excluded from paragraph/heading
        # extraction below, since its text is now script-authoritative on
        # the matching image element's `caption` field instead.
        image_bboxes = [r["bbox"] for r in figure_regions] + figures_lib.bitmap_bboxes(page, furniture_xrefs)
        caption_bboxes = {
            tuple(line["bbox"])
            for line in (figures_lib.find_caption_line(page, bbox) for bbox in image_bboxes)
            if line
        }

        page_elements = []
        # Drop text blocks that mostly overlap a detected table; the table
        # element replaces them so cell text isn't duplicated as prose.
        for block in text_blocks:
            if any(bbox_overlap_ratio(block["bbox"], t["bbox"]) > 0.5 for t in tables):
                continue
            kept_lines = furniture_filtered_lines(block, furniture_masked, page_height)
            kept_lines = figure_region_filtered_lines(kept_lines, figure_regions)
            kept_lines = caption_filtered_lines(kept_lines, caption_bboxes)
            element = build_block_element(block, kept_lines, body_size, toc_lookup, heading_size_ranks)
            if element is not None:
                page_elements.append(element)

        for table in tables:
            page_elements.append({"type": "table", "rows": table["rows"], "bbox": list(table["bbox"])})

        page_elements.sort(key=lambda e: e["bbox"][1])

        shard_path = paths.shard_path(args.doc, page_number, "text")
        elements_lib.write_shard(shard_path, page_number, page_elements)

    fitz_doc.close()
    print(f"extracted text for pages {page_numbers}")


if __name__ == "__main__":
    main()
