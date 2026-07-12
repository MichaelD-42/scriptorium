#!/usr/bin/env python3
"""Classify each page of a PDF into an extraction tier (text|ocr) and the
document into a loop size (tight|loose). See SKILL.md for the schema."""

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import paths  # noqa: E402

import fitz  # PyMuPDF

TEXT_CHAR_THRESHOLD = 20  # fewer non-whitespace chars than this => treat page as scanned


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
    document.close()

    loop_size = "tight" if any(p["tier"] != "text" for p in pages) else "loose"
    result = {
        "doc": args.doc,
        "page_count": len(pages),
        "pages": pages,
        "loop_size": loop_size,
        "body_size": round(body_size, 1),
    }

    out_path = paths.triage_json(args.doc)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
