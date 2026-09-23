#!/usr/bin/env python3
"""Classify each page of a PDF into an extraction tier (text|ocr) and the
document into a loop size (tight|loose). See SKILL.md for the schema."""

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import paths  # noqa: E402

import fitz  # PyMuPDF
import pdfplumber

TEXT_CHAR_THRESHOLD = 20  # fewer non-whitespace chars than this => treat page as scanned

# Furniture thresholds (see SKILL.md).
FURNITURE_EDGE_BAND = 0.12  # top/bottom 12% of page height counts as "near an edge"
LINE_PATTERN_MIN_PAGE_FRACTION = 0.60
FRAME_TABLE_MIN_AREA_FRACTION = 0.60
FRAME_TABLE_MIN_PAGE_FRACTION = 0.50
FRAME_TABLE_BBOX_TOLERANCE = 2.0  # pt
REPEATED_IMAGE_MIN_PAGE_FRACTION = 0.50


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

                if y_bottom_frac <= FURNITURE_EDGE_BAND:
                    edge = "top"
                elif y_top_frac >= 1 - FURNITURE_EDGE_BAND:
                    edge = "bottom"
                else:
                    continue

                masked = re.sub(r"\d+", "#", text)
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
    of pages. A plain ruled rectangle with no internal lines is often not
    detected as a table at all by pdfplumber's heuristics -- that's a
    legitimate empty result, not a bug."""
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
                    (
                        g
                        for g in groups
                        if all(abs(a - b) <= FRAME_TABLE_BBOX_TOLERANCE for a, b in zip(g["bboxes"][0], bbox))
                    ),
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
        if page_count and matched_page_count / page_count >= FRAME_TABLE_MIN_PAGE_FRACTION:
            n = len(group["bboxes"])
            avg_bbox = [round(sum(b[i] for b in group["bboxes"]) / n, 2) for i in range(4)]
            frame_tables.append({"bbox": avg_bbox, "page_count": matched_page_count})
    return frame_tables


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


def detect_furniture(document, pdf_path: Path) -> tuple[dict, str | None]:
    """Runs once per document (not per page): finds repeated header/footer
    lines, repeated full-page-covering tables, and repeated images. Returns
    `(furniture, furniture_text)` for folding into triage.json."""
    line_patterns, line_occurrences = _find_repeated_lines(document)
    frame_tables = _find_frame_tables(pdf_path, document.page_count)
    image_xrefs = _find_repeated_images(document)

    furniture = {
        "line_patterns": line_patterns,
        "frame_tables": frame_tables,
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
    furniture, furniture_text = detect_furniture(document, pdf_path)
    document.close()

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


if __name__ == "__main__":
    main()
