#!/usr/bin/env python3
"""Extract bitmap images and vector-graphic page regions from a PDF, or
(for a standalone image document) land the whole file as page 1's one
bitmap element. See SKILL.md."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import elements as elements_lib  # noqa: E402
import paths  # noqa: E402

import fitz  # PyMuPDF
import pdfplumber
from PIL import Image

VECTOR_DRAWING_THRESHOLD = 8  # >= this many vector paths on a page => treat as a diagram
VECTOR_TEXT_CHAR_CEILING = 200  # only treat as a standalone diagram if the page isn't mostly text


def extract_image_document(input_path: Path, assets_dir: Path) -> list[dict]:
    """A standalone image document has no embedded XObjects or vector
    regions to hunt for — the whole file *is* the one image. Normalize it
    to PNG (same as render-pages does for page1.png) and land it as a
    single bitmap element, page 1's only image."""
    out_name = "page1_bitmap1.png"
    out_path = assets_dir / out_name
    with Image.open(input_path) as img:
        img.convert("RGB").save(out_path)
    return [{"type": "image", "kind": "bitmap", "asset": f"assets/{out_name}", "caption": ""}]


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
    input_path = paths.input_file(args.doc)
    if input_path is None:
        print(f"error: no input file found for doc '{args.doc}' in input/", file=sys.stderr)
        sys.exit(1)

    assets_dir = paths.assets_dir(args.doc)
    assets_dir.mkdir(parents=True, exist_ok=True)

    input_format = paths.detect_input_format(args.doc)
    if input_format == "image":
        # Whole-file input, always page 1 — no per-page loop over a PDF.
        image_elements = extract_image_document(input_path, assets_dir)
        shard_path = paths.shard_path(args.doc, 1, "image")
        elements_lib.write_shard(shard_path, 1, image_elements)
        print(f"page 1: {len(image_elements)} image element(s)")
        return

    pdf_path = input_path
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
