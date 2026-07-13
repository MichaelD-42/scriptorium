#!/usr/bin/env python3
"""Generate the committed sample.{pdf,pptx,docx,xlsx} fixtures in
plugins/scriptorium/examples/ (alongside the existing sample.png and
sample.html), used by the pytest suite (plugins/scriptorium/tests/) as
one-example-per-format test input. Each fixture exercises the same shapes
the pipeline's triage/extract skills look for: a heading, a body paragraph,
a table, and an embedded image — so a single fixture per format is enough
to drive triage -> extract -> merge -> assemble -> gate/grade end to end.

sample.pdf is generate_sample.py's output (that script's own concern is a
golden.md/counterexample.md answer key for manual pipeline evaluation, a
different purpose from this plugin-examples copy) copied here so every
format has its fixture in one place.

Run with:
    uv run --project plugins/scriptorium python examples/generate_fixtures.py
"""

import shutil
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw
from docx import Document
from openpyxl import Workbook
from pptx import Presentation
from pptx.util import Inches

import generate_sample

ROOT = Path(__file__).resolve().parent.parent
PLUGIN_EXAMPLES = ROOT / "plugins" / "scriptorium" / "examples"

PPTX_PATH = PLUGIN_EXAMPLES / "sample.pptx"
DOCX_PATH = PLUGIN_EXAMPLES / "sample.docx"
XLSX_PATH = PLUGIN_EXAMPLES / "sample.xlsx"
PDF_PATH = PLUGIN_EXAMPLES / "sample.pdf"

TABLE_ROWS = [["Quarter", "Revenue"], ["Q1", "120"], ["Q2", "150"]]


def make_icon_bytes() -> bytes:
    img = Image.new("RGB", (80, 80), "white")
    draw = ImageDraw.Draw(img)
    draw.ellipse((10, 10, 70, 70), fill=(30, 120, 200), outline="black", width=2)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def build_pptx(icon_bytes: bytes) -> None:
    prs = Presentation()
    title_layout = prs.slide_layouts[0]
    slide1 = prs.slides.add_slide(title_layout)
    slide1.shapes.title.text = "Sample Deck"
    slide1.placeholders[1].text_frame.text = "An introductory paragraph for slide 1."

    blank_layout = prs.slide_layouts[6]
    slide2 = prs.slides.add_slide(blank_layout)
    rows, cols = len(TABLE_ROWS), len(TABLE_ROWS[0])
    table_shape = slide2.shapes.add_table(rows, cols, Inches(1), Inches(1), Inches(4), Inches(2))
    for r, row in enumerate(TABLE_ROWS):
        for c, cell in enumerate(row):
            table_shape.table.cell(r, c).text = cell
    slide2.shapes.add_picture(BytesIO(icon_bytes), Inches(1), Inches(4), Inches(1), Inches(1))

    prs.save(PPTX_PATH)


def build_docx(icon_bytes: bytes) -> None:
    doc = Document()
    doc.add_heading("Sample Report", level=1)
    doc.add_paragraph("An introductory paragraph describing the report.")
    doc.add_heading("Quarterly Data", level=1)
    table = doc.add_table(rows=len(TABLE_ROWS), cols=len(TABLE_ROWS[0]))
    for r, row in enumerate(TABLE_ROWS):
        for c, cell in enumerate(row):
            table.cell(r, c).text = cell
    doc.add_paragraph("Status indicator image below.")
    doc.add_picture(BytesIO(icon_bytes), width=doc.sections[0].page_width // 8)
    doc.save(DOCX_PATH)


def build_xlsx() -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Data"
    for row in TABLE_ROWS:
        ws.append(row)
    wb.save(XLSX_PATH)


def main() -> None:
    generate_sample.main()
    shutil.copyfile(generate_sample.OUTPUT_PDF, PDF_PATH)

    icon_bytes = make_icon_bytes()
    build_pptx(icon_bytes)
    build_docx(icon_bytes)
    build_xlsx()

    print(f"wrote {PDF_PATH}")
    print(f"wrote {PPTX_PATH}")
    print(f"wrote {DOCX_PATH}")
    print(f"wrote {XLSX_PATH}")


if __name__ == "__main__":
    main()
