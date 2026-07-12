#!/usr/bin/env python3
"""Extract native headings, paragraphs, tables, and images from an HTML
document's single page (per lib/html_pages.py). See SKILL.md."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import elements as elements_lib  # noqa: E402
import html_pages  # noqa: E402
import paths  # noqa: E402


def extract_page(soup, html_dir: Path, assets_dir: Path) -> tuple[list[dict], list[dict]]:
    """Returns (body_elements, image_elements) for the document's one page."""
    body_elements = []
    for block in html_pages.iter_block_items(soup):
        if block.name == "table":
            body_elements.append({"type": "table", "rows": html_pages.table_rows(block)})
            continue

        level = html_pages.heading_level(block)
        text = block.get_text(strip=True)
        if not text:
            continue
        if level is not None:
            body_elements.append({"type": "heading", "level": min(level, 3), "text": text})
        else:
            body_elements.append({"type": "paragraph", "text": text})

    image_elements = []
    for idx, (data, ext) in enumerate(html_pages.saveable_images(soup, html_dir), start=1):
        out_name = f"page1_bitmap{idx}.{ext}"
        (assets_dir / out_name).write_bytes(data)
        image_elements.append({"type": "image", "kind": "bitmap", "asset": f"assets/{out_name}", "caption": ""})

    return body_elements, image_elements


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", required=True)
    parser.add_argument("--pages", required=True, help="comma-separated 1-indexed page numbers (always '1' for html)")
    args = parser.parse_args()

    page_numbers = [int(p) for p in args.pages.split(",") if p.strip()]
    html_path = paths.input_file(args.doc)
    if html_path is None or html_path.suffix != ".html":
        print(f"error: input/{args.doc}.html not found", file=sys.stderr)
        sys.exit(1)
    if page_numbers != [1]:
        print(f"error: html-extract only supports page 1 (got {args.pages!r})", file=sys.stderr)
        sys.exit(1)

    soup = html_pages.parse(html_path)
    assets_dir = paths.assets_dir(args.doc)
    assets_dir.mkdir(parents=True, exist_ok=True)

    body_elements, image_elements = extract_page(soup, html_path.parent, assets_dir)

    elements_lib.write_shard(paths.shard_path(args.doc, 1, "text"), 1, body_elements)
    elements_lib.write_shard(paths.shard_path(args.doc, 1, "image"), 1, image_elements)

    print("extracted html page [1]")


if __name__ == "__main__":
    main()
