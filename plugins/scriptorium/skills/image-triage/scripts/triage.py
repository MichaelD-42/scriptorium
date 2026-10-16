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
import preflight  # noqa: E402

from PIL import Image


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", required=True, help="document name (without extension)")
    args = parser.parse_args()

    image_path = paths.input_file(args.doc)
    if image_path is None or paths.detect_input_format(args.doc) != "image":
        print(f"error: no image input found for doc '{args.doc}' in input/", file=sys.stderr)
        sys.exit(1)

    try:
        with Image.open(image_path) as img:
            img.load()
            frames = getattr(img, "n_frames", 1)
    except Exception as e:  # UnidentifiedImageError, truncated data, DecompressionBombError
        preflight.fail(image_path, f"cannot be opened as an image ({type(e).__name__}: {e})")
    if frames > 1:
        # render-pages saves the first frame only.
        preflight.fail(image_path, f"has {frames} pages; convert it to a PDF (one page per frame) instead")

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
