#!/usr/bin/env python3
"""Classify a standalone image document as a single page, tier "ocr" (an
image has no text layer, so it starts on the same ocr->vision ladder a
scanned PDF page uses). See SKILL.md."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import paths  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", required=True, help="document name (without extension)")
    args = parser.parse_args()

    image_path = paths.input_file(args.doc)
    if image_path is None or paths.detect_input_format(args.doc) != "image":
        print(f"error: no image input found for doc '{args.doc}' in input/", file=sys.stderr)
        sys.exit(1)

    page_info = {
        "page_number": 1,
        "tier": "ocr",
        "image_count": 1,
        "reason": "raster image, no text layer — OCR then escalate to vision",
    }

    result = {
        "doc": args.doc,
        "page_count": 1,
        "pages": [page_info],
        "loop_size": "tight",
    }

    out_path = paths.triage_json(args.doc)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8", newline="")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
