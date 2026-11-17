#!/usr/bin/env python3
"""Classify each slide of a pptx into an extraction tier (always "text",
pptx is digital-native) and the document into a loop size (tight|loose).
See README.md for the schema."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import furniture as furniture_lib  # noqa: E402
import paths  # noqa: E402
import pptx_shapes  # noqa: E402
import preflight  # noqa: E402

from pptx import Presentation


def footer_furniture(presentation) -> dict:
    """`furniture` with one `line_patterns` entry per footer, slide-number or
    date placeholder line that has letters. pptx-extract never emits these
    placeholders; the patterns let merge.py and gates.py's
    furniture_absent catch them in a vision transcription. A digit-only
    line (a slide number, a numeric date) is left out: with no page
    geometry it would match any bare number in the body."""
    pages: dict[str, set[int]] = {}
    for n, slide in enumerate(presentation.slides, start=1):
        for shape in slide.placeholders:
            if pptx_shapes.is_furniture_placeholder(shape) and shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    key = furniture_lib.furniture_key(para.text)
                    if key and not furniture_lib.is_digit_only_pattern(key):
                        pages.setdefault(key, set()).add(n)
    return {
        **furniture_lib.empty_furniture(),
        "line_patterns": [{"masked": key, "page_count": len(found)} for key, found in sorted(pages.items())],
    }


def classify_slide(slide, page_number: int) -> dict:
    figures = pptx_shapes.figure_shapes(slide)
    return {
        "page_number": page_number,
        "tier": "text",
        "image_count": len(figures),
        "figure_shapes": figures,
        "reason": "native slide content (pptx is digital-native, no OCR needed)",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", required=True, help="document name (without .pptx)")
    args = parser.parse_args()

    pptx_path = paths.input_file(args.doc)
    if pptx_path is None or paths.detect_input_format(args.doc) != "pptx":
        print(f"error: input/{args.doc}.pptx not found", file=sys.stderr)
        sys.exit(1)

    presentation = preflight.open_office(Presentation, pptx_path)
    if not len(presentation.slides):
        preflight.fail(pptx_path, "has no slides")
    pages = [classify_slide(slide, i) for i, slide in enumerate(presentation.slides, start=1)]

    loop_size = "tight" if any(p["image_count"] for p in pages) else "loose"
    result = {
        "doc": args.doc,
        "page_count": len(pages),
        "pages": pages,
        "loop_size": loop_size,
        "furniture": footer_furniture(presentation),
    }

    out_path = paths.triage_json(args.doc)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8", newline="")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
