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
import paths  # noqa: E402

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


def is_furniture_block(block: dict, furniture_masked: set[str], page_height: float) -> bool:
    """A text block is furniture if it sits in a top/bottom edge band *and*
    at least one of its lines' digit-masked text matches a known furniture
    line pattern. Both conditions must hold -- a real body table or
    paragraph that happens to sit near the bottom margin, but doesn't match
    a known furniture pattern, is kept. Matching is per-line (not on the
    block's combined text) because PyMuPDF groups the fixture's whole
    multi-line footer into a single block."""
    if not furniture_masked:
        return False
    if not in_furniture_band(block["bbox"], page_height):
        return False
    return any(masked in furniture_masked for masked in block["lines_masked"])


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


def classify_heading_level(block_max_size: float, body_size: float) -> int | None:
    if body_size <= 0:
        return None
    ratio = block_max_size / body_size
    if ratio >= 1.9:
        return 1
    if ratio >= 1.45:
        return 2
    if ratio >= 1.15:
        return 3
    return None


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
        lines_text = []
        lines_masked = []
        max_size = 0.0
        for line in block.get("lines", []):
            spans_text = "".join(span["text"] for span in line.get("spans", []))
            lines_text.append(spans_text)
            stripped = spans_text.strip()
            if stripped:
                lines_masked.append(re.sub(r"\d+", "#", stripped))
            for span in line.get("spans", []):
                sizes.append(span["size"])
                max_size = max(max_size, span["size"])
        text = " ".join(t.strip() for t in lines_text if t.strip())
        if text:
            text_blocks.append({"bbox": block["bbox"], "text": text, "max_size": max_size, "lines_masked": lines_masked})
    resolved_body_size = body_size if body_size else (statistics.median(sizes) if sizes else 0.0)
    return text_blocks, resolved_body_size


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

    fitz_doc = fitz.open(pdf_path)

    for page_number in page_numbers:
        page = fitz_doc[page_number - 1]
        page_height = page.rect.height
        text_blocks, body_size = extract_page_text_blocks(page, args.body_size)
        tables = extract_page_tables(pdf_path, page_number)
        # Drop page-frame tables (furniture, not real content) before doing
        # anything else with the table list -- must happen before the
        # overlap-drop below, or a frame "table" would swallow real text
        # blocks that merely sit underneath it.
        tables = [t for t in tables if not is_frame_table(t["bbox"], frame_tables)]

        page_elements = []
        # Drop text blocks that mostly overlap a detected table; the table
        # element replaces them so cell text isn't duplicated as prose.
        for block in text_blocks:
            if any(bbox_overlap_ratio(block["bbox"], t["bbox"]) > 0.5 for t in tables):
                continue
            if is_furniture_block(block, furniture_masked, page_height):
                continue
            level = classify_heading_level(block["max_size"], body_size)
            bbox = list(block["bbox"])
            if level:
                page_elements.append({"type": "heading", "level": level, "text": block["text"], "bbox": bbox})
            else:
                page_elements.append({"type": "paragraph", "text": block["text"], "bbox": bbox})

        for table in tables:
            page_elements.append({"type": "table", "rows": table["rows"], "bbox": list(table["bbox"])})

        page_elements.sort(key=lambda e: e["bbox"][1])

        shard_path = paths.shard_path(args.doc, page_number, "text")
        elements_lib.write_shard(shard_path, page_number, page_elements)

    fitz_doc.close()
    print(f"extracted text for pages {page_numbers}")


if __name__ == "__main__":
    main()
