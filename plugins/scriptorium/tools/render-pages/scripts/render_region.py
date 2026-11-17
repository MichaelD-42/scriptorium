#!/usr/bin/env python3
"""Follow-up R26: render one region of a PDF page at a high resolution.

An agent transcribing `figure_text` by vision reads the element's crop.
Small labels in a crop rendered at the page dpi (or a bitmap's own
resolution) can be too small to read. This script renders just the
element's bbox, with a small margin, at `--dpi` (default 400) to
`work/<doc>/zoom/page{N}_{x0}_{y0}.png` and prints the path. See README.md."""

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


def crop_png(
    pdf_path: Path, page_number: int, bbox: list[float], out: Path, dpi: int, margin: float = 0.0
) -> Path | None:
    """Render `bbox` (PDF points, plus `margin`) of one page to `out`. None
    when the region lies outside the page."""
    with fitz.open(pdf_path) as pdf:
        page = pdf[page_number - 1]
        clip = (
            fitz.Rect(bbox[0] - margin, bbox[1] - margin, bbox[2] + margin, bbox[3] + margin)
            & page.rect
        )
        if clip.is_empty:
            return None
        pixmap = page.get_pixmap(clip=clip, dpi=dpi)
        out.parent.mkdir(parents=True, exist_ok=True)
        pixmap.save(str(out))
    return out


def source_pdf(doc: str) -> Path:
    """The PDF whose pages the document's bboxes refer to: the input PDF, or
    for a pptx the slide PDF render.py caches at work/<doc>/<doc>.pdf."""
    input_format = paths.detect_input_format(doc)
    if input_format == "pdf":
        return paths.input_file(doc)
    if input_format == "pptx":
        slide_pdf = paths.work_dir(doc) / f"{doc}.pdf"
        if slide_pdf.exists():
            return slide_pdf
        raise FileNotFoundError(f"no {slide_pdf} -- run render-pages/scripts/render.py first")
    raise FileNotFoundError(f"no input/{doc}.pdf or .pptx (render_region renders PDF and pptx pages only)")


def render_region(doc: str, page_number: int, bbox: list[float], dpi: int) -> Path:
    out = crop_png(source_pdf(doc), page_number, bbox, zoom_png(doc, page_number, bbox), dpi, REGION_MARGIN)
    if out is None:
        raise FileNotFoundError(f"bbox {bbox} lies outside page {page_number}")
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
