#!/usr/bin/env python3
"""Classify an HTML document as a single page, tier "text" (HTML is
digital-native, no OCR needed). See SKILL.md."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import html_pages  # noqa: E402
import paths  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", required=True, help="document name (without .html)")
    args = parser.parse_args()

    html_path = paths.input_file(args.doc)
    if html_path is None or html_path.suffix != ".html":
        print(f"error: input/{args.doc}.html not found", file=sys.stderr)
        sys.exit(1)

    soup = html_pages.parse(html_path)
    has_table = soup.find("table") is not None
    image_count = len(html_pages.saveable_images(soup, html_path.parent))

    page_info = {
        "page_number": 1,
        "tier": "text",
        "has_table": has_table,
        "image_count": image_count,
        "reason": "native HTML content (digital-native, no OCR needed)",
    }

    result = {
        "doc": args.doc,
        "page_count": 1,
        "pages": [page_info],
        "loop_size": "tight" if has_table or image_count > 0 else "loose",
    }

    out_path = paths.triage_json(args.doc)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8", newline="")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
