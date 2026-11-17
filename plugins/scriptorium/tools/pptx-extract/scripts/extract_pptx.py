#!/usr/bin/env python3
"""Extract native text, headings, tables, and images from pptx slides.
See README.md."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import elements as elements_lib  # noqa: E402
import paths  # noqa: E402
import pptx_shapes  # noqa: E402

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.oxml.ns import qn

STRIKE_VALUES = {"sngStrike", "dblStrike"}


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


def pt(emu: float) -> float:
    return round(emu / pptx_shapes.EMU_PER_PT, 1)


def visible_shapes(shapes):
    """Every shape that is not hidden, a group's members in place of the
    group, in z-order. A hidden group hides its members."""
    for shape in shapes:
        if pptx_shapes.is_hidden(shape):
            continue
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from visible_shapes(shape.shapes)
        else:
            yield shape


def extract_slide(slide, page_number: int, assets_dir: Path) -> tuple[list[dict], list[dict]]:
    """Returns (body_elements, image_elements) for one slide, each in
    reading order. Each element carries its position on the slide in points
    (the slide PDF's unit), so merge.py can interleave the two lists: a body
    element its `top`, an image its `bbox`."""
    title_shape = slide.shapes.title
    title_shape_id = title_shape.shape_id if title_shape is not None else None
    body_elements = []
    image_elements = []
    bitmap_idx = 0

    for shape in visible_shapes(slide.shapes):
        bbox = [pt(v) for v in pptx_shapes.abs_bbox(shape)]
        top = bbox[1]

        if pptx_shapes.is_picture(shape):
            bitmap_idx += 1
            image = shape.image
            out_name = f"page{page_number}_bitmap{bitmap_idx}.{image.ext}"
            (assets_dir / out_name).write_bytes(image.blob)
            image_elements.append(
                {"type": "image", "kind": "bitmap", "asset": f"assets/{out_name}", "caption": "", "bbox": bbox}
            )
            continue

        if pptx_shapes.is_furniture_placeholder(shape):
            continue

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

    for page_number in page_numbers:
        slide = presentation.slides[page_number - 1]
        body_elements, image_elements = extract_slide(slide, page_number, assets_dir)

        elements_lib.write_shard(paths.shard_path(args.doc, page_number, "text"), page_number, body_elements)
        elements_lib.write_shard(paths.shard_path(args.doc, page_number, "image"), page_number, image_elements)

    print(f"extracted pptx slides {page_numbers}")


if __name__ == "__main__":
    main()
