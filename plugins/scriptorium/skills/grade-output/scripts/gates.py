#!/usr/bin/env python3
"""Deterministic structural gates — the hard backpressure layer. See SKILL.md.

These checks never require judgment; anything that needs looking at pixels
belongs in rubric.md instead, applied by the calling agent.
"""

import argparse
import json
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import elements as elements_lib  # noqa: E402
import paths  # noqa: E402

OCR_CONFIDENCE_FLOOR = 0.5
MIN_OUTPUT_BYTES = 20

# Task A5b: an excluded figure region (lib/figures.py's
# detect_figure_regions_with_exclusions, written into a PDF page's image
# shard as excluded_regions -- see lib/elements.py's merge_shards) is
# flagged here if it's more than this fraction of its page's area AND its
# reason isn't one of the two that are expected/benign (a repeated page
# frame, or a stray sliver too small to matter). "frame_drawing"/"tiny" are
# excluded on purpose; "furniture_band"/"table_overlap" are exactly the two
# rules the brief calls out as capable of excluding a genuinely large real
# figure, so those are the ones worth a human's attention.
LARGE_REGION_EXCLUDED_AREA_FRACTION = 0.2
LARGE_REGION_EXCLUDED_BENIGN_REASONS = {"frame_drawing", "tiny"}


def check_page_count_match(doc_data: dict, true_page_count: int) -> dict:
    got = len(doc_data["pages"])
    passed = got == true_page_count
    return {
        "name": "page_count_match",
        "passed": passed,
        "detail": f"expected {true_page_count} pages, elements.json has {got}",
    }


def check_no_empty_pages(doc_data: dict) -> dict:
    empty = [
        p["page_number"]
        for p in doc_data["pages"].values()
        if not p["elements"] and p.get("skipped") != "toc"
    ]
    return {
        "name": "no_empty_pages",
        "passed": not empty,
        "detail": f"empty pages: {empty}" if empty else "every page has at least one element",
    }


def check_image_refs_resolve(doc_data: dict, output_dir: Path) -> dict:
    missing = []
    for page in doc_data["pages"].values():
        for el in page["elements"]:
            if el["type"] == "image":
                if not (output_dir / el["asset"]).exists():
                    missing.append(el["asset"])
    return {
        "name": "image_refs_resolve",
        "passed": not missing,
        "detail": f"missing assets: {missing}" if missing else "all image assets resolve",
    }


def check_ocr_confidence_floor(doc_data: dict) -> dict:
    low = [
        p["page_number"]
        for p in doc_data["pages"].values()
        if p["tier"] == "ocr" and p.get("ocr_confidence", 0) < OCR_CONFIDENCE_FLOOR
    ]
    return {
        "name": "ocr_confidence_floor",
        "passed": not low,
        "detail": f"pages below {OCR_CONFIDENCE_FLOOR} confidence: {low}" if low else "all OCR pages meet the confidence floor",
    }


def check_large_region_excluded(doc_data: dict, page_areas: dict[int, float]) -> list[dict]:
    """Task A5b: a WARNING (never a hard gate failure -- see main()) for
    every page whose image shard recorded an `excluded_regions` entry that
    is both large (more than LARGE_REGION_EXCLUDED_AREA_FRACTION of its
    page) and not one of the benign, expected reasons
    (LARGE_REGION_EXCLUDED_BENIGN_REASONS). `page_areas` maps page_number to
    that page's area in points^2 -- absent/0 for a page this gate can't
    evaluate (no PDF geometry available, e.g. a non-pdf input format), which
    is silently skipped rather than raising, since this check is PDF-vector-
    region-specific and every other input format never writes
    `excluded_regions` at all.

    Deliberately a warning, not a hard failure: the brief's point is
    visibility (the grader/human reviewer must be able to see that a large
    region was dropped and judge whether that was correct), not an
    automatic block -- a large excluded region is very often a correct
    exclusion (a genuinely oversized table, say), and gating hard on it
    would make every one of those a forced escalation for no reason."""
    warnings = []
    for page in doc_data["pages"].values():
        page_number = page.get("page_number")
        page_area = page_areas.get(page_number, 0)
        if not page_area:
            continue
        for region in page.get("excluded_regions", []):
            if region.get("reason") in LARGE_REGION_EXCLUDED_BENIGN_REASONS:
                continue
            bbox = region["bbox"]
            area = max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])
            fraction = area / page_area
            if fraction > LARGE_REGION_EXCLUDED_AREA_FRACTION:
                warnings.append({
                    "name": "large_region_excluded",
                    "page": page_number,
                    "bbox": bbox,
                    "reason": region.get("reason"),
                    "area_fraction": round(fraction, 3),
                    "detail": (
                        f"page {page_number}: a region covering {fraction:.0%} of the page "
                        f"was excluded (reason: {region.get('reason')}) -- verify this wasn't a real figure"
                    ),
                })
    return warnings


def _pdf_page_areas(input_path: Path) -> dict[int, float]:
    """{page_number: width*height in points^2} for a PDF input -- the
    geometry check_large_region_excluded needs to turn an excluded region's
    bbox into a page-area fraction. gates.py otherwise never opens the
    source PDF (it works entirely from elements.json + the independent
    true_page_count oracle), so this import is local to keep that the
    common case."""
    import fitz  # PyMuPDF

    with fitz.open(input_path) as doc:
        return {i: page.rect.width * page.rect.height for i, page in enumerate(doc, start=1)}


def check_output_file_exists(doc: str, fmt: str) -> dict:
    if fmt == "okf":
        index = paths.okf_index(doc)
        sections = list(paths.output_dir(doc).glob("[0-9][0-9]-*.md"))
        if index.exists() and index.stat().st_size >= MIN_OUTPUT_BYTES and sections:
            return {"name": "output_file_exists", "passed": True, "detail": f"{index} + {len(sections)} section file(s)"}
        return {"name": "output_file_exists", "passed": False, "detail": "okf bundle incomplete: missing index.md or section files"}

    if fmt == "reqif":
        candidate = paths.output_file(doc, "reqif")
        if not candidate.exists() or candidate.stat().st_size < MIN_OUTPUT_BYTES:
            return {"name": "output_file_exists", "passed": False, "detail": "no assembled reqif output found"}
        try:
            root_tag = ET.parse(candidate).getroot().tag
        except ET.ParseError as e:
            return {"name": "output_file_exists", "passed": False, "detail": f"{candidate} is not well-formed XML: {e}"}
        if not root_tag.endswith("REQ-IF"):
            return {"name": "output_file_exists", "passed": False, "detail": f"{candidate} root element is {root_tag!r}, expected REQ-IF"}
        return {"name": "output_file_exists", "passed": True, "detail": f"{candidate} exists and is well-formed ReqIF XML"}

    if fmt == "reqifz":
        candidate = paths.output_file(doc, "reqifz")
        if not candidate.exists() or candidate.stat().st_size < MIN_OUTPUT_BYTES:
            return {"name": "output_file_exists", "passed": False, "detail": "no assembled reqifz output found"}
        if not zipfile.is_zipfile(candidate):
            return {"name": "output_file_exists", "passed": False, "detail": f"{candidate} is not a valid zip archive"}
        expected = f"{doc}.reqif"
        with zipfile.ZipFile(candidate) as zf:
            if expected not in zf.namelist():
                return {"name": "output_file_exists", "passed": False, "detail": f"{candidate} missing {expected}"}
        return {"name": "output_file_exists", "passed": True, "detail": f"{candidate} exists and contains {expected}"}

    candidate = paths.output_file(doc, fmt)
    if candidate.exists() and candidate.stat().st_size >= MIN_OUTPUT_BYTES:
        return {"name": "output_file_exists", "passed": True, "detail": f"{candidate} exists ({candidate.stat().st_size} bytes)"}
    return {"name": "output_file_exists", "passed": False, "detail": f"no assembled {fmt} output found"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", required=True)
    parser.add_argument("--format", choices=["md", "html", "okf", "reqif", "reqifz"], default="md")
    args = parser.parse_args()

    input_path = paths.input_file(args.doc)
    if input_path is None:
        print(f"error: no input file found for doc '{args.doc}' in input/", file=sys.stderr)
        sys.exit(1)
    input_format = paths.detect_input_format(args.doc)
    true_page_count = paths.true_page_count(args.doc, input_format)

    elements_path = paths.elements_json(args.doc)
    if not elements_path.exists():
        print(f"error: {elements_path} not found — run extraction first", file=sys.stderr)
        sys.exit(1)
    doc_data = elements_lib.load_doc(elements_path)

    checks = [
        check_page_count_match(doc_data, true_page_count),
        check_no_empty_pages(doc_data),
        check_image_refs_resolve(doc_data, paths.output_dir(args.doc)),
        check_ocr_confidence_floor(doc_data),
        check_output_file_exists(args.doc, args.format),
    ]

    # Task A5b: large_region_excluded is a WARNING, not one of the checks
    # above -- it never affects `passed`. See check_large_region_excluded's
    # docstring for why.
    page_areas = _pdf_page_areas(input_path) if input_format == "pdf" else {}
    warnings = check_large_region_excluded(doc_data, page_areas)

    result = {"doc": args.doc, "passed": all(c["passed"] for c in checks), "checks": checks, "warnings": warnings}

    out_path = paths.gates_report_json(args.doc)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
