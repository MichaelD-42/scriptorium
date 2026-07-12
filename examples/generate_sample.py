#!/usr/bin/env python3
"""Generate the synthetic multi-feature sample PDF used to test the
scriptorium pipeline end to end, plus a hand-authored golden.md (the
"correct" answer key) and a counterexample.md (deliberately broken, used to
verify the grader actually fails bad output instead of rubber-stamping it).

Five pages, one per extraction path:
  1. native text (title + subheading + body paragraphs)          -> Tier 1
  2. native text + a ruled table                                 -> Tier 1
  3. native text + an embedded bitmap image                      -> Tier 1 + image-extractor
  4. native text + a vector-drawn diagram (no embedded image)    -> Tier 1 + image-extractor
  5. a full-page scan with NO text layer                          -> Tier 2/3 (OCR/vision)

Run with:
    uv run --project plugins/scriptorium python examples/generate_sample.py
"""

import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PDF = ROOT / "input" / "sample.pdf"
GOLDEN_MD = ROOT / "examples" / "golden.md"
COUNTEREXAMPLE_MD = ROOT / "examples" / "counterexample.md"

PAGE1_TITLE = "Elastic Loop Extraction Sample"
PAGE1_SUBHEAD = "Introduction"
PAGE1_PARA1 = (
    "This document exercises every tier of the scriptorium pipeline: native text, "
    "a table, an embedded bitmap image, a vector diagram, and one image-only scanned page."
)
PAGE1_PARA2 = (
    "Each page targets a specific extraction path so the pipeline's tiered escalation "
    "and independent grading can be verified end to end."
)

PAGE2_HEADING = "Quarterly Results"
TABLE_ROWS = [
    ["Quarter", "Revenue", "Growth"],
    ["Q1", "120", "-"],
    ["Q2", "150", "25%"],
    ["Q3", "180", "20%"],
]

PAGE3_HEADING = "Figure: Status Indicator"
PAGE3_CAPTION_HINT = "Status indicator image below."

PAGE4_HEADING = "Figure: Process Diagram"
PAGE4_BOXES = [
    (100, 480, 90, 32, "Start"),
    (260, 480, 90, 32, "Process"),
    (420, 480, 90, 32, "Decision"),
    (260, 380, 90, 32, "End"),
]

PAGE5_LINES = [
    "This page is a scanned image with no PDF text layer.",
    "It exists to force Tier 2/3 OCR extraction in the pipeline.",
    "Tesseract should transcribe most of this text correctly.",
]


def make_bitmap_asset() -> Image.Image:
    img = Image.new("RGB", (300, 300), "white")
    draw = ImageDraw.Draw(img)
    draw.ellipse((60, 60, 240, 240), fill=(200, 30, 30), outline="black", width=3)
    font = ImageFont.load_default(size=36)
    draw.text((115, 135), "OK", fill="white", font=font)
    return img


def make_scanned_page_image() -> Image.Image:
    width, height = 1224, 1584  # letter @ ~144dpi
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=30)
    y = 150
    for line in PAGE5_LINES:
        draw.text((100, y), line, fill="black", font=font)
        y += 60
    return img


def draw_wrapped_text(c: canvas.Canvas, text: str, x: float, y: float, width_chars: int, size: int, leading: int) -> float:
    c.setFont("Helvetica", size)
    text_obj = c.beginText(x, y)
    text_obj.setLeading(leading)
    for line in textwrap.wrap(text, width_chars):
        text_obj.textLine(line)
    c.drawText(text_obj)
    lines = textwrap.wrap(text, width_chars)
    return y - leading * len(lines)


def draw_table(c: canvas.Canvas, rows: list[list[str]], x: float, y: float, col_widths: list[int], row_height: int) -> None:
    n_rows = len(rows)
    xs = [x]
    for cw in col_widths:
        xs.append(xs[-1] + cw)
    total_height = row_height * n_rows

    for r in range(n_rows + 1):
        yy = y - r * row_height
        c.line(xs[0], yy, xs[-1], yy)
    for xv in xs:
        c.line(xv, y, xv, y - total_height)

    c.setFont("Helvetica", 10)
    for r, row in enumerate(rows):
        for col_idx, cell in enumerate(row):
            cx = xs[col_idx] + 6
            cy = y - r * row_height - row_height + 8
            c.drawString(cx, cy, str(cell))


def draw_flow_diagram(c: canvas.Canvas, boxes: list[tuple[int, int, int, int, str]]) -> None:
    c.setLineWidth(1.5)
    for bx, by, bw, bh, label in boxes:
        c.rect(bx, by, bw, bh, stroke=1, fill=0)
        c.setFont("Helvetica", 9)
        c.drawCentredString(bx + bw / 2, by + bh / 2 - 3, label)

    start, process, decision, end = boxes
    c.line(start[0] + start[2], start[1] + start[3] / 2, process[0], process[1] + process[3] / 2)
    c.line(process[0] + process[2], process[1] + process[3] / 2, decision[0], decision[1] + decision[3] / 2)
    c.line(process[0] + process[2] / 2, process[1], end[0] + end[2] / 2, end[1] + end[3])
    c.line(decision[0] + decision[2] / 2, decision[1], decision[0] + decision[2] / 2, decision[1] - 20)


def build_pdf(bitmap_img: Image.Image, scanned_img: Image.Image) -> None:
    OUTPUT_PDF.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(OUTPUT_PDF), pagesize=letter)
    width, height = letter

    # Page 1: native text, title + subheading + body
    c.setFont("Helvetica-Bold", 24)
    c.drawString(72, height - 100, PAGE1_TITLE)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(72, height - 135, PAGE1_SUBHEAD)
    y = draw_wrapped_text(c, PAGE1_PARA1, 72, height - 165, 90, 11, 15)
    draw_wrapped_text(c, PAGE1_PARA2, 72, y - 15, 90, 11, 15)
    c.showPage()

    # Page 2: native text + ruled table
    c.setFont("Helvetica-Bold", 18)
    c.drawString(72, height - 90, PAGE2_HEADING)
    draw_table(c, TABLE_ROWS, x=72, y=height - 120, col_widths=[110, 110, 110], row_height=24)
    c.showPage()

    # Page 3: native text + embedded bitmap image
    c.setFont("Helvetica-Bold", 18)
    c.drawString(72, height - 90, PAGE3_HEADING)
    c.setFont("Helvetica", 11)
    c.drawString(72, height - 120, PAGE3_CAPTION_HINT)
    c.drawImage(ImageReader(bitmap_img), 72, height - 420, width=200, height=200)
    c.showPage()

    # Page 4: native text + vector-drawn diagram (no embedded image)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(72, height - 80, PAGE4_HEADING)
    draw_flow_diagram(c, PAGE4_BOXES)
    c.showPage()

    # Page 5: full-page scan, no text layer at all
    c.drawImage(ImageReader(scanned_img), 0, 0, width=width, height=height)
    c.showPage()

    c.save()


def write_golden() -> None:
    table_md = "\n".join(
        "| " + " | ".join(row) + " |" if i != 1 else "| " + " | ".join("---" for _ in row) + " |"
        for i, row in enumerate([TABLE_ROWS[0], ["---"] * 3] + TABLE_ROWS[1:])
    )
    content = f"""# {PAGE1_TITLE}

## {PAGE1_SUBHEAD}

{PAGE1_PARA1}

{PAGE1_PARA2}

## {PAGE2_HEADING}

{table_md}

## {PAGE3_HEADING}

{PAGE3_CAPTION_HINT}

![a red circle icon labeled OK, indicating an active/operational status](assets/page3_bitmap1.png)

### {PAGE4_HEADING}

![a flowchart with four connected boxes: Start, Process, Decision, and End](assets/page4_vector1.png)

## Scanned Page

{" ".join(PAGE5_LINES)}
"""
    GOLDEN_MD.write_text(content)


def write_counterexample() -> None:
    """A deliberately broken output: drops the scanned page's content entirely
    (dropped_text) and duplicates a paragraph (duplicated_text) — the grader
    must fail this, or the rubric application is miscalibrated."""
    golden = GOLDEN_MD.read_text()
    broken = golden.split("## Scanned Page")[0]  # drop the OCR'd page entirely
    broken += f"\n{PAGE1_PARA1}\n"  # duplicate a paragraph from page 1
    COUNTEREXAMPLE_MD.write_text(broken)


def main() -> None:
    bitmap_img = make_bitmap_asset()
    scanned_img = make_scanned_page_image()
    build_pdf(bitmap_img, scanned_img)
    write_golden()
    write_counterexample()
    print(f"wrote {OUTPUT_PDF}")
    print(f"wrote {GOLDEN_MD}")
    print(f"wrote {COUNTEREXAMPLE_MD}")


if __name__ == "__main__":
    main()
