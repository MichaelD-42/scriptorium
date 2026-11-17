#!/usr/bin/env python3
"""Extract native text, headings, tables, and images from pptx slides.
See README.md."""

import argparse
import functools
import io
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "render-pages" / "scripts"))
import elements as elements_lib  # noqa: E402
import paths  # noqa: E402
import pptx_shapes  # noqa: E402
import render  # noqa: E402
import render_region  # noqa: E402

import openpyxl
from openpyxl.utils.cell import range_boundaries
from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.oxml.ns import qn

STRIKE_VALUES = {"sngStrike", "dblStrike"}
SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
# Picture formats PIL cannot decode everywhere: cropped from the slide PDF.
VECTOR_IMAGE_EXTS = {"emf", "wmf"}
CROP_DPI = 200


def save_cropped(blob: bytes, crop: tuple[float, float, float, float], out: Path) -> bool:
    """Write the part of the picture the slide shows (`a:srcRect`: fractions
    of the source cut from the left, top, right, bottom) to `out`. A
    negative value is an outset: clamped, not padded. False when PIL cannot
    read or write the image."""
    if not any(crop):
        out.write_bytes(blob)
        return True
    left, top, right, bottom = (max(0.0, c) for c in crop)
    try:
        with Image.open(io.BytesIO(blob)) as img:
            w, h = img.size
            img.crop((round(left * w), round(top * h), round(w - right * w), round(h - bottom * h))).save(out)
    except (OSError, ValueError):
        out.unlink(missing_ok=True)
        return False
    return True


def paragraph_text(para) -> str:
    """The paragraph's runs, fields and line breaks (a break as \\v, like
    `para.text`), with each span of struck runs wrapped in `~~...~~`.
    Whitespace at a span's edge goes outside the markers: Markdown does not
    render `~~struck ~~`."""
    spans: list[list] = []  # [struck, text]; adjacent struck runs share one span
    for child in para._p.content_children:
        rpr = child.find(qn("a:rPr"))
        struck = rpr is not None and rpr.get("strike") in STRIKE_VALUES
        if spans and spans[-1][0] == struck:
            spans[-1][1] += child.text
        else:
            spans.append([struck, child.text])
    parts = []
    for struck, text in spans:
        core = text.strip()
        if struck and core:
            text = text[: len(text) - len(text.lstrip())] + f"~~{core}~~" + text[len(text.rstrip()) :]
        parts.append(text)
    return "".join(parts)


def shape_paragraphs(shape) -> list[str]:
    if not shape.has_text_frame:
        return []
    paragraphs = []
    for para in shape.text_frame.paragraphs:
        text = paragraph_text(para).replace("\v", " ").strip()  # python-pptx reads a line break (<a:br/>) as \v
        if text:
            paragraphs.append(text)
    return paragraphs


def table_rows(shape) -> list[list[str]]:
    return [
        ["\n".join(paragraph_text(p) for p in cell.text_frame.paragraphs) for cell in row.cells]
        for row in shape.table.rows
    ]


def ole_worksheet_rows(shape) -> list[list[str]] | None:
    """The cells an embedded Excel worksheet shows on the slide: the active
    sheet's `oleSize` range (xl/workbook.xml), without hidden rows, hidden
    columns and empty rows. Never reads a cell outside `oleSize`: the rest
    of the sheet is not on the slide, and often holds data the author chose
    not to show. None when the object is not an xlsx workbook or names no
    `oleSize`; the caller then crops the frame from the slide PDF."""
    ole = shape.ole_format
    if not (ole.prog_id or "").startswith("Excel.Sheet"):
        return None
    try:
        blob = ole.blob
        with zipfile.ZipFile(io.BytesIO(blob)) as package:
            ole_size = ET.fromstring(package.read("xl/workbook.xml")).find(f"{{{SPREADSHEET_NS}}}oleSize")
        if ole_size is None:
            return None
        min_col, min_row, max_col, max_row = range_boundaries(ole_size.get("ref") or "")
        if None in (min_col, min_row, max_col, max_row):
            return None
        sheet = openpyxl.load_workbook(io.BytesIO(blob), data_only=True).active
    except (zipfile.BadZipFile, KeyError, ValueError, TypeError, ET.ParseError):
        return None
    hidden_cols = {
        c for dim in sheet.column_dimensions.values() if dim.hidden and dim.min for c in range(dim.min, dim.max + 1)
    }
    cols = [c for c in range(min_col, max_col + 1) if c not in hidden_cols]
    rows = []
    for r in range(min_row, max_row + 1):
        if sheet.row_dimensions[r].hidden:
            continue
        row = ["" if (value := sheet.cell(r, c).value) is None else str(value) for c in cols]
        if any(row):
            rows.append(row)
    return rows or None


def pt(emu: float) -> float:
    return round(emu / pptx_shapes.EMU_PER_PT, 1)


def visible_shapes(shapes, figure=None, top_level: bool = True):
    """(shape, figure) for every shape that is not hidden, in z-order, a
    group's members in place of the group; a hidden group hides its
    members. A top-level group that draws a figure
    (`pptx_shapes.is_figure_group`) is yielded itself first, as
    (group, group), and `figure` is that group for each of its members."""
    for shape in shapes:
        if pptx_shapes.is_hidden(shape):
            continue
        if shape.shape_type != MSO_SHAPE_TYPE.GROUP:
            yield shape, figure
        elif top_level and pptx_shapes.is_figure_group(shape):
            yield shape, shape
            yield from visible_shapes(shape.shapes, shape, False)
        else:
            yield from visible_shapes(shape.shapes, figure, False)


def extract_slide(slide, page_number: int, assets_dir: Path, slide_pdf=None) -> tuple[list[dict], list[dict]]:
    """Returns (body_elements, image_elements) for one slide, each in
    reading order. Each element carries its position on the slide in points
    (the slide PDF's unit), so merge.py can interleave the two lists: a body
    element its `top`, an image its `bbox`. Every image records the shape
    it came from as `source_shape_id`.

    `slide_pdf`: a no-argument callable returning the deck's slide PDF (or
    None), called only when a figure must be cropped from the rendered
    slide. Without it such a figure gets no element, and a warning."""
    title_shape = slide.shapes.title
    title_shape_id = title_shape.shape_id if title_shape is not None else None
    body_elements = []
    image_elements = []
    bitmap_idx = 0

    def add_image(shape, bbox, asset: str, kind: str) -> None:
        image_elements.append(
            {"type": "image", "kind": kind, "asset": f"assets/{asset}", "caption": "", "bbox": bbox,
             "source_shape_id": shape.shape_id}
        )

    def add_slide_crop(shape, bbox) -> None:
        """An image element cut from the rendered slide at the shape's bbox:
        what the slide shows, whatever the shape holds."""
        out = assets_dir / f"page{page_number}_shape{shape.shape_id}.png"
        pdf = slide_pdf() if slide_pdf else None
        if pdf is None or render_region.crop_png(pdf, page_number, bbox, out, CROP_DPI) is None:
            print(f"warning: slide {page_number} shape {shape.shape_id}: no slide PDF crop, no image element",
                  file=sys.stderr)
            return
        add_image(shape, bbox, out.name, "vector")

    for shape, figure in visible_shapes(slide.shapes):
        bbox_emu = pptx_shapes.abs_bbox(shape)
        bbox = [pt(v) for v in bbox_emu]
        top = bbox[1]

        if shape is figure:
            add_slide_crop(shape, bbox)  # also shows the overlays and labels drawn on it
            continue
        is_figure_part = pptx_shapes.is_picture(shape) or pptx_shapes.frame_kind(shape) or pptx_shapes.has_picture_fill(shape)
        if figure is not None and is_figure_part:
            continue  # its group's crop shows it; the source would be the uncropped original

        if frame_kind := pptx_shapes.frame_kind(shape):
            if pptx_shapes.is_degenerate(bbox_emu, slide):
                continue
            rows = ole_worksheet_rows(shape) if frame_kind == "ole" else None
            if rows:
                body_elements.append({"type": "table", "rows": rows, "top": top, "source_shape_id": shape.shape_id})
            else:
                add_slide_crop(shape, bbox)
            continue

        if pptx_shapes.is_picture(shape):
            crop = (shape.crop_left, shape.crop_top, shape.crop_right, shape.crop_bottom)
            if crop[0] + crop[2] >= 1 or crop[1] + crop[3] >= 1:
                continue  # cropped away entirely: nothing shows
            image = shape.image
            out_name = f"page{page_number}_bitmap{bitmap_idx + 1}.{image.ext}"
            if image.ext not in VECTOR_IMAGE_EXTS and save_cropped(image.blob, crop, assets_dir / out_name):
                bitmap_idx += 1
                add_image(shape, bbox, out_name, "bitmap")
            else:
                add_slide_crop(shape, bbox)
            continue

        if pptx_shapes.is_furniture_placeholder(shape):
            continue

        if pptx_shapes.has_picture_fill(shape):
            add_slide_crop(shape, bbox)  # its text, if any, is still read below

        if shape.has_table:
            body_elements.append({"type": "table", "rows": table_rows(shape), "top": top})
            continue

        # `slide.shapes.title` and the shapes yielded by iterating
        # `slide.shapes` are separate wrapper objects for the same XML
        # element (python-pptx builds a fresh proxy per access), so identity
        # comparison never matches — compare the stable shape_id instead.
        if title_shape_id is not None and shape.shape_id == title_shape_id:
            title_text = " ".join(shape_paragraphs(shape)).strip()
            if title_text:
                body_elements.append({"type": "heading", "level": 1, "text": title_text, "top": top})
            continue

        for para_text in shape_paragraphs(shape):
            body_elements.append({"type": "paragraph", "text": para_text, "top": top})

    body_elements.sort(key=lambda e: e["top"])
    image_elements.sort(key=lambda e: e["bbox"][1])

    if slide.has_notes_slide:
        notes_text = slide.notes_slide.notes_text_frame.text.strip()
        if notes_text:
            # Below everything on the slide, so merge.py keeps it last.
            body_elements.append(
                {"type": "paragraph", "text": f"Speaker notes: {notes_text}", "top": pt(pptx_shapes.slide_size(slide)[1])}
            )

    return body_elements, image_elements


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", required=True)
    parser.add_argument("--pages", required=True, help="comma-separated 1-indexed slide numbers")
    args = parser.parse_args()

    page_numbers = [int(p) for p in args.pages.split(",") if p.strip()]
    pptx_path = paths.input_file(args.doc)
    if pptx_path is None or paths.detect_input_format(args.doc) != "pptx":
        print(f"error: input/{args.doc}.pptx not found", file=sys.stderr)
        sys.exit(1)

    presentation = Presentation(pptx_path)
    assets_dir = paths.assets_dir(args.doc)
    assets_dir.mkdir(parents=True, exist_ok=True)

    @functools.cache
    def slide_pdf() -> Path | None:
        """Converted on first use only: a deck with no figure to crop needs
        no LibreOffice."""
        try:
            return render.convert_pptx_to_pdf(pptx_path, args.doc)
        except (SystemExit, OSError) as error:  # no soffice, or a failed conversion
            print(f"warning: no slide PDF for {args.doc}: {error}", file=sys.stderr)
            return None

    for page_number in page_numbers:
        slide = presentation.slides[page_number - 1]
        body_elements, image_elements = extract_slide(slide, page_number, assets_dir, slide_pdf)

        elements_lib.write_shard(paths.shard_path(args.doc, page_number, "text"), page_number, body_elements)
        elements_lib.write_shard(paths.shard_path(args.doc, page_number, "image"), page_number, image_elements)

    print(f"extracted pptx slides {page_numbers}")


if __name__ == "__main__":
    main()
