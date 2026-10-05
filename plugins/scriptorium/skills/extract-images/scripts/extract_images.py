#!/usr/bin/env python3
"""Extract bitmap images and vector-graphic page regions from a PDF, or
(for a standalone image document) land the whole file as page 1's one
bitmap element. See SKILL.md."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import elements as elements_lib  # noqa: E402
import figures as figures_lib  # noqa: E402
import furniture as furniture_lib  # noqa: E402
import paths  # noqa: E402

import fitz  # PyMuPDF
from PIL import Image

VECTOR_REGION_DPI = 200  # Task A5: region crops render sharper than the old whole-page 150dpi default

# Furniture removal (Task A2) reads triage.json["furniture"]. The loaders
# and the frame matching rule are in lib/furniture.py.


def extract_image_document(input_path: Path, assets_dir: Path) -> list[dict]:
    """A standalone image document has no embedded XObjects or vector
    regions to hunt for — the whole file *is* the one image. Normalize it
    to PNG (same as render-pages does for page1.png) and land it as a
    single bitmap element, page 1's only image."""
    out_name = "page1_bitmap1.png"
    out_path = assets_dir / out_name
    with Image.open(input_path) as img:
        img = img.convert("RGB")
        img.save(out_path)
        bbox = [0, 0, img.width, img.height]
    # No fitz text layer for a standalone image document -- nothing to
    # search for a caption against, so `caption` stays absent (same
    # convention as a PDF image element with no nearby caption match).
    return [{"type": "image", "kind": "bitmap", "asset": f"assets/{out_name}", "bbox": bbox}]


def extract_bitmaps(fitz_doc, page, page_number: int, assets_dir: Path, furniture_xrefs: set[int]) -> list[dict]:
    found = []
    idx = 0
    for img in page.get_images(full=True):
        xref = img[0]
        if xref in furniture_xrefs:
            # Repeated furniture (e.g. a logo on every page) -- never write
            # an image element for it.
            continue
        idx += 1
        try:
            base = fitz_doc.extract_image(xref)
        except Exception:
            continue
        ext = base.get("ext", "png")
        out_name = f"page{page_number}_bitmap{idx}.{ext}"
        out_path = assets_dir / out_name
        out_path.write_bytes(base["image"])
        try:
            bbox = list(page.get_image_bbox(img))
        except Exception:
            bbox = [0, 0, 0, 0]  # get_image_bbox couldn't resolve a placement (rare); keep the field present anyway
        element = {"type": "image", "kind": "bitmap", "asset": f"assets/{out_name}", "bbox": bbox}
        _set_caption_if_found(element, page, bbox)
        found.append(element)
    return found


def _set_caption_if_found(element: dict, page, bbox: list[float]) -> None:
    """Task A6: `caption` is script-authoritative for a PDF image element --
    a nearby text-layer line matching `lib/figures.py`'s CAPTION_PATTERN
    (`find_caption_line`), verbatim, or absent entirely when nothing nearby
    matches (never a guessed/empty placeholder)."""
    caption_line = figures_lib.find_caption_line(page, bbox)
    if caption_line:
        element["caption"] = caption_line["text"]


def extract_vector_regions(
    page, page_number: int, assets_dir: Path, pdf_path: Path,
    frame_tables: list[dict] | None = None,
    frame_drawings: list[dict] | None = None,
    dpi: int = VECTOR_REGION_DPI,
    repeated_drawings: list[dict] | None = None,
    content_rect: list[float] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Task A5: one image element per surviving figure region (see
    `lib/figures.py`'s `detect_figure_regions_with_exclusions` for the full
    detection pipeline — clustering, frame/table/tiny-cluster/furniture-band
    exclusion, and the small padding applied to each region's bbox). Each
    region is crop-rendered — not the whole page — at `dpi`, named
    `page{N}_vector{k}.png` (k = 1-indexed per page, matching
    `extract_bitmaps`' `page{N}_bitmap{idx}.{ext}` naming convention).

    `figure_text` is set from the region's own text-layer lines (if any) —
    script-authoritative per this task's brief; a region with no text layer
    leaves `figure_text` absent, so Task A6 (vision fallback, not this
    task) knows to fill it in.

    Returns `(image_elements, excluded_regions)` — Task A5b: `excluded_regions`
    is every candidate this page's pipeline dropped (a pre-filtered frame
    drawing, or an excluded cluster), written verbatim into the page's image
    shard by `main()` below so nothing a filter removes vanishes silently."""
    regions, excluded_regions = figures_lib.detect_figure_regions_with_exclusions(
        page, page_number, pdf_path, frame_tables=frame_tables, frame_drawings=frame_drawings,
        repeated_drawings=repeated_drawings, content_rect=content_rect,
    )
    zoom = dpi / 72
    found = []
    for k, region in enumerate(regions, start=1):
        bbox = region["bbox"]
        out_name = f"page{page_number}_vector{k}.png"
        out_path = assets_dir / out_name
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=fitz.Rect(*bbox))
        pix.save(out_path)
        element = {"type": "image", "kind": "vector", "asset": f"assets/{out_name}", "bbox": bbox}
        _set_caption_if_found(element, page, bbox)
        figure_text = figures_lib.figure_text_for_region(page, bbox)
        if figure_text:
            element["figure_text"] = figure_text
        found.append(element)
    return found, excluded_regions


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

    furniture = furniture_lib.load_furniture(args.doc)
    frame_tables = furniture.get("frame_tables", [])
    frame_drawings = furniture.get("frame_drawings", [])
    repeated_drawings = furniture.get("repeated_drawings", [])
    furniture_xrefs = set(furniture.get("image_xrefs", []))
    page_roles = furniture_lib.load_page_roles(args.doc)

    pdf_path = input_path
    fitz_doc = fitz.open(pdf_path)
    for page_number in page_numbers:
        if page_roles.get(page_number) == "toc":
            # A printed TOC page has no real images of its own -- skip
            # straight to an empty, explicitly-marked shard.
            shard_path = paths.shard_path(args.doc, page_number, "image")
            elements_lib.write_shard(shard_path, page_number, [], skipped="toc")
            print(f"page {page_number}: skipped (toc)")
            continue

        page = fitz_doc[page_number - 1]
        content_rect = furniture_lib.page_content_rect(furniture, page.rect.width, page.rect.height)
        image_elements = extract_bitmaps(fitz_doc, page, page_number, assets_dir, furniture_xrefs)
        vector_elements, excluded_regions = extract_vector_regions(
            page, page_number, assets_dir, pdf_path, frame_tables, frame_drawings,
            repeated_drawings=repeated_drawings, content_rect=content_rect,
        )
        image_elements += vector_elements

        # Image shards are independent of the page's text/OCR/vision tier —
        # write one even when empty, so a retry can tell "checked, found
        # nothing" apart from "never checked". excluded_regions (Task A5b)
        # is always present, even when empty, so a page with nothing dropped
        # is distinguishable from a page merge.py hasn't seen an image shard
        # for at all.
        shard_path = paths.shard_path(args.doc, page_number, "image")
        elements_lib.write_shard(shard_path, page_number, image_elements, excluded_regions=excluded_regions)
        print(f"page {page_number}: {len(image_elements)} image element(s), {len(excluded_regions)} excluded region(s)")

    fitz_doc.close()


if __name__ == "__main__":
    main()
