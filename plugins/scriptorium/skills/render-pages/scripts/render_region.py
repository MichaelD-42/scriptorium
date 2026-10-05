#!/usr/bin/env python3
"""Follow-up R26: render one region of a PDF page at a high resolution.

An agent transcribing `figure_text` by vision reads the element's crop.
Small labels in a crop rendered at the page dpi (or a bitmap's own
resolution) can be too small to read. This script renders just the
element's bbox, with a small margin, at `--dpi` (default 400) to
`work/<doc>/zoom/page{N}_{x0}_{y0}.png` and prints the path. See SKILL.md."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import fitz  # PyMuPDF
import paths

# Points of page around the bbox, so a label on the crop's edge is whole.
REGION_MARGIN = 6.0


def zoom_png(doc: str, page_number: int, bbox: list[float]) -> Path:
    return (
        paths.work_dir(doc)
        / "zoom"
        / f"page{page_number}_{round(bbox[0])}_{round(bbox[1])}.png"
    )


def render_region(doc: str, page_number: int, bbox: list[float], dpi: int) -> Path:
    pdf_path = paths.input_pdf(doc)
    if not pdf_path.exists():
        raise FileNotFoundError(
            f"{pdf_path} not found (render_region renders PDF pages only)"
        )
    with fitz.open(pdf_path) as pdf:
        page = pdf[page_number - 1]
        clip = (
            fitz.Rect(
                bbox[0] - REGION_MARGIN,
                bbox[1] - REGION_MARGIN,
                bbox[2] + REGION_MARGIN,
                bbox[3] + REGION_MARGIN,
            )
            & page.rect
        )
        pixmap = page.get_pixmap(clip=clip, dpi=dpi)
        out = zoom_png(doc, page_number, bbox)
        out.parent.mkdir(parents=True, exist_ok=True)
        pixmap.save(str(out))
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", required=True)
    parser.add_argument("--page", required=True, type=int)
    parser.add_argument(
        "--bbox", required=True, help='the element bbox in PDF points, "x0,y0,x1,y1"'
    )
    parser.add_argument("--dpi", type=int, default=400)
    args = parser.parse_args()
    bbox = [float(v) for v in args.bbox.split(",")]
    if len(bbox) != 4:
        print("error: --bbox needs four numbers, x0,y0,x1,y1", file=sys.stderr)
        sys.exit(1)
    try:
        out = render_region(args.doc, args.page, bbox, args.dpi)
    except FileNotFoundError as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
    print(out)


if __name__ == "__main__":
    main()
