#!/usr/bin/env python3
"""Extract bitmap images and vector-graphic page regions. See SKILL.md."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import elements as elements_lib  # noqa: E402
import paths  # noqa: E402

import fitz  # PyMuPDF
import pdfplumber

VECTOR_DRAWING_THRESHOLD = 8  # >= this many vector paths on a page => treat as a diagram
VECTOR_TEXT_CHAR_CEILING = 200  # only treat as a standalone diagram if the page isn't mostly text


def extract_bitmaps(fitz_doc, page, page_number: int, assets_dir: Path) -> list[dict]:
    found = []
    for idx, img in enumerate(page.get_images(full=True), start=1):
        xref = img[0]
        try:
            base = fitz_doc.extract_image(xref)
        except Exception:
            continue
        ext = base.get("ext", "png")
        out_name = f"page{page_number}_bitmap{idx}.{ext}"
        out_path = assets_dir / out_name
        out_path.write_bytes(base["image"])
        found.append({"type": "image", "kind": "bitmap", "asset": f"assets/{out_name}", "caption": ""})
    return found


def page_has_table(pdf_path: Path, page_number: int) -> bool:
    """A ruled table's grid lines are vector paths too, and can easily clear
    VECTOR_DRAWING_THRESHOLD on their own — without this check a table gets
    misdetected as a diagram. Tables are extract-text's job, not ours."""
    with pdfplumber.open(pdf_path) as pl_doc:
        return bool(pl_doc.pages[page_number - 1].find_tables())


def extract_vector_region(page, page_number: int, assets_dir: Path, pdf_path: Path, dpi: int = 150) -> list[dict]:
    drawings = page.get_drawings()
    text_len = len(page.get_text("text").strip())
    if len(drawings) < VECTOR_DRAWING_THRESHOLD or text_len > VECTOR_TEXT_CHAR_CEILING:
        return []
    if page_has_table(pdf_path, page_number):
        return []

    out_name = f"page{page_number}_vector1.png"
    out_path = assets_dir / out_name
    zoom = dpi / 72
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    pix.save(out_path)
    return [{"type": "image", "kind": "vector", "asset": f"assets/{out_name}", "caption": ""}]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", required=True)
    parser.add_argument("--pages", required=True, help="comma-separated 1-indexed page numbers")
    args = parser.parse_args()

    page_numbers = [int(p) for p in args.pages.split(",") if p.strip()]
    pdf_path = paths.input_pdf(args.doc)
    if not pdf_path.exists():
        print(f"error: {pdf_path} not found", file=sys.stderr)
        sys.exit(1)

    assets_dir = paths.assets_dir(args.doc)
    assets_dir.mkdir(parents=True, exist_ok=True)

    fitz_doc = fitz.open(pdf_path)
    for page_number in page_numbers:
        page = fitz_doc[page_number - 1]
        image_elements = extract_bitmaps(fitz_doc, page, page_number, assets_dir)
        image_elements += extract_vector_region(page, page_number, assets_dir, pdf_path)

        # Image shards are independent of the page's text/OCR/vision tier —
        # write one even when empty, so a retry can tell "checked, found
        # nothing" apart from "never checked".
        shard_path = paths.shard_path(args.doc, page_number, "image")
        elements_lib.write_shard(shard_path, page_number, image_elements)
        print(f"page {page_number}: {len(image_elements)} image element(s)")

    fitz_doc.close()


if __name__ == "__main__":
    main()
