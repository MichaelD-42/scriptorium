#!/usr/bin/env python3
"""Extract native text, headings, tables, and images from docx pages
(Heading-1 sections, per lib/docx_pages.split_pages()). See SKILL.md."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import docx_pages  # noqa: E402
import elements as elements_lib  # noqa: E402
import paths  # noqa: E402

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph


def table_rows(table: Table) -> list[list[str]]:
    return [[cell.text for cell in row.cells] for row in table.rows]


def extract_page(blocks: list, page_number: int, document, assets_dir: Path) -> tuple[list[dict], list[dict]]:
    """Returns (body_elements, image_elements) for one page's block items."""
    body_elements = []
    image_elements = []
    bitmap_idx = 0

    for block in blocks:
        if isinstance(block, Table):
            body_elements.append({"type": "table", "rows": table_rows(block)})
            continue

        # block is a Paragraph
        level = docx_pages.heading_level(block)
        text = block.text.strip()
        if level is not None:
            if text:
                body_elements.append({"type": "heading", "level": min(level, 3), "text": text})
        elif text:
            body_elements.append({"type": "paragraph", "text": text})

        for image_part in docx_pages.paragraph_images(block, document):
            bitmap_idx += 1
            ext = Path(image_part.partname).suffix.lstrip(".") or "png"
            out_name = f"page{page_number}_bitmap{bitmap_idx}.{ext}"
            (assets_dir / out_name).write_bytes(image_part.blob)
            image_elements.append({"type": "image", "kind": "bitmap", "asset": f"assets/{out_name}", "caption": ""})

    return body_elements, image_elements


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", required=True)
    parser.add_argument("--pages", required=True, help="comma-separated 1-indexed page numbers")
    args = parser.parse_args()

    page_numbers = [int(p) for p in args.pages.split(",") if p.strip()]
    docx_path = paths.input_file(args.doc)
    if docx_path is None or docx_path.suffix != ".docx":
        print(f"error: input/{args.doc}.docx not found", file=sys.stderr)
        sys.exit(1)

    document = Document(docx_path)
    pages = docx_pages.split_pages(document)
    assets_dir = paths.assets_dir(args.doc)
    assets_dir.mkdir(parents=True, exist_ok=True)

    for page_number in page_numbers:
        blocks = pages[page_number - 1]
        body_elements, image_elements = extract_page(blocks, page_number, document, assets_dir)

        elements_lib.write_shard(paths.shard_path(args.doc, page_number, "text"), page_number, body_elements)
        elements_lib.write_shard(paths.shard_path(args.doc, page_number, "image"), page_number, image_elements)

    print(f"extracted docx pages {page_numbers}")


if __name__ == "__main__":
    main()
