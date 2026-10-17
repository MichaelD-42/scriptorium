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

# The body element types assemble.py renders, and the keys it reads from each.
# Images are not body elements: they live in the page's image shard.
REQUIRED_KEYS = {
    "heading": ("text", "level"),
    "paragraph": ("text",),
    "list_item": ("text", "marker", "level"),
    "table": ("rows",),
}


def element_error(el) -> str | None:
    if not isinstance(el, dict) or el.get("type") not in REQUIRED_KEYS:
        return f"type must be one of {sorted(REQUIRED_KEYS)}"
    missing = [k for k in REQUIRED_KEYS[el["type"]] if k not in el]
    if missing:
        return f"{el['type']} needs {missing}"
    if "text" in el and not isinstance(el["text"], str):
        return "text must be a string"
    if "level" in el and not (isinstance(el["level"], int) and 1 <= el["level"] <= 6):
        return "level must be an integer 1-6"
    if el["type"] == "table" and not (isinstance(el["rows"], list) and all(isinstance(r, list) for r in el["rows"])):
        return "rows must be a list of lists"
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", required=True)
    parser.add_argument("--page", required=True, type=int)
    args = parser.parse_args()

    # Follow-up R8: stdin is UTF-8, whatever the locale (a test may pass a
    # StringIO, which is already text).
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    page_elements = json.load(sys.stdin)
    errors = [f"element {i}: {e}" for i, el in enumerate(page_elements) if (e := element_error(el))]
    if errors:
        print("error: " + "; ".join(errors), file=sys.stderr)
        sys.exit(1)

    shard_path = paths.shard_path(args.doc, args.page, "vision")
    elements_lib.write_shard(shard_path, args.page, page_elements)
    print(f"page {args.page}: {len(page_elements)} vision-tier element(s) written")


if __name__ == "__main__":
    main()
