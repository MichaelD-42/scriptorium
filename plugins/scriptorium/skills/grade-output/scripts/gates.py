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


def check_page_count_match(doc_data: dict, true_page_count: int) -> dict:
    got = len(doc_data["pages"])
    passed = got == true_page_count
    return {
        "name": "page_count_match",
        "passed": passed,
        "detail": f"expected {true_page_count} pages, elements.json has {got}",
    }


def check_no_empty_pages(doc_data: dict) -> dict:
    empty = [p["page_number"] for p in doc_data["pages"].values() if not p["elements"]]
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
    result = {"doc": args.doc, "passed": all(c["passed"] for c in checks), "checks": checks}

    out_path = paths.gates_report_json(args.doc)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
