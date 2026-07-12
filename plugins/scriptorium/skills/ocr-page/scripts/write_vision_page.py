#!/usr/bin/env python3
"""Write a Tier-3 (Claude vision) shard for a single page.

This is not a script that does OCR itself — the calling agent (the
`extractor` role, when it escalates a page) reads the rendered page PNG with
its own vision and decides the text. This script just lands that judgment
into the shared shard schema, the same way the tesseract backend in ocr.py
does for Tier 2.

Elements (a JSON array, same shape as any other tier's elements) are read
from stdin, e.g.:

    echo '[{"type": "paragraph", "text": "..."}]' | uv run ... write_vision_page.py --doc sample --page 5
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import elements as elements_lib  # noqa: E402
import paths  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", required=True)
    parser.add_argument("--page", required=True, type=int)
    args = parser.parse_args()

    page_elements = json.load(sys.stdin)

    shard_path = paths.shard_path(args.doc, args.page, "vision")
    elements_lib.write_shard(shard_path, args.page, page_elements)
    print(f"page {args.page}: {len(page_elements)} vision-tier element(s) written")


if __name__ == "__main__":
    main()
