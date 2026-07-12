#!/usr/bin/env python3
"""Split a docx into logical pages (Heading-1 sections) and classify each
as tier "text" (docx is digital-native, no OCR needed). See SKILL.md."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import docx_pages  # noqa: E402
import paths  # noqa: E402

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph


def classify_page(blocks: list, page_number: int, document) -> dict:
    has_table = any(isinstance(b, Table) for b in blocks)
    image_count = sum(
        len(docx_pages.paragraph_images(b, document)) for b in blocks if isinstance(b, Paragraph)
    )
    return {
        "page_number": page_number,
        "tier": "text",
        "has_table": has_table,
        "image_count": image_count,
        "reason": "native docx content (digital-native, no OCR needed)",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", required=True, help="document name (without .docx)")
    args = parser.parse_args()

    docx_path = paths.input_file(args.doc)
    if docx_path is None or docx_path.suffix != ".docx":
        print(f"error: input/{args.doc}.docx not found", file=sys.stderr)
        sys.exit(1)

    document = Document(docx_path)
    pages = docx_pages.split_pages(document)

    page_infos = [classify_page(blocks, i, document) for i, blocks in enumerate(pages, start=1)]
    loop_size = "tight" if any(p["has_table"] or p["image_count"] > 0 for p in page_infos) else "loose"

    result = {
        "doc": args.doc,
        "page_count": len(page_infos),
        "pages": page_infos,
        "loop_size": loop_size,
    }

    out_path = paths.triage_json(args.doc)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
