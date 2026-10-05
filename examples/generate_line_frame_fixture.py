#!/usr/bin/env python3
"""Generate a small fixture PDF for the repeated-drawing tests (fix wave B1).

`furniture_sample.pdf` draws its page frame as one `c.rect()`, and
`frame_table_sample.pdf` adds one internal ruling. Real documents often
draw the frame from many separate parts instead. This fixture has that
shape, on every page:

- a filled inner rect (the page's body area, fill only, no stroke);
- an outer border drawn as 4 separate thin lines;
- a title block below the inner rect, drawn as 31 separate thin lines
  (rules and cell walls), with 3 short furniture text lines in it.

None of these parts covers 60% of the page on its own, except the filled
inner rect. So the frame is only found by repetition (`triage.py`'s
`repeated_drawings`). Left in, the parts touch each other and join every
other drawing on the page into one page-sized cluster.

Four pages (letter size):
  1. Heading and body text only.
  2. Heading, body text and a real vector diagram with a caption.
  3. Heading, body text and a real ruled table inside the frame.
  4. Heading and body text only.

Run with:
    uv run --project plugins/scriptorium python examples/generate_line_frame_fixture.py
"""

from itertools import pairwise
from pathlib import Path

import generate_sample  # reuse draw_wrapped_text / draw_table / draw_flow_diagram
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PDF = ROOT / "plugins" / "scriptorium" / "examples" / "line_frame_sample.pdf"

PAGE_WIDTH, PAGE_HEIGHT = letter
PAGE_COUNT = 4
LEFT_MARGIN = 72

# All y values below are measured from the TOP of the page (the PyMuPDF
# convention the tests use); `_y()` converts them for reportlab.
# The inner rect's bottom edge meets the title block's top rule, so
# pdfplumber reads the inner rect and the title block as one page-covering
# table (a `frame_tables` entry).
INNER_RECT = (40, 24, 572, 692)  # x0, top, x1, bottom
BORDER = (28, 16, 584, 776)
TITLE_BLOCK_ROWS = [692, 712, 732, 752, 772]
TITLE_BLOCK_COLS = [40, 300, 436, 572]

DIAGRAM_BOXES = [  # reportlab coordinates, as draw_flow_diagram expects
    (100, 470, 90, 32, "Receive"),
    (260, 470, 90, 32, "Check"),
    (420, 470, 90, 32, "Route"),
    (260, 380, 90, 32, "Close"),
]
DIAGRAM_CAPTION = "Figure 1: Line Frame Diagram"

TABLE_ROWS = [["Item", "Value"], ["Mode", "Normal"], ["Limit", "Ten"]]
TABLE_X, TABLE_TOP = 150, 300  # TABLE_TOP from the page top
TABLE_COL_WIDTHS = [110, 110]
TABLE_ROW_HEIGHT = 22

HEADINGS = [
    "Line Frame Overview",
    "Line Frame Diagram Page",
    "Line Frame Table Page",
    "Line Frame Closing Page",
]
PARAGRAPHS = [
    (
        "This page holds only a heading and body text inside a page frame that is drawn "
        "from many separate thin lines and one filled inner rectangle."
    ),
    (
        "This page adds a small flow diagram between two paragraphs. The diagram must be "
        "found as one region of about its own size, not as the whole page."
    ),
    (
        "This page adds a small ruled table inside the page frame. The table must still "
        "extract as a table and must not merge with the frame."
    ),
    (
        "This last page repeats the frame once more with different body text, so every "
        "frame part repeats on all pages of the document."
    ),
]
SECOND_PARAGRAPH = (
    "A second paragraph of ordinary body text sits further down the page, well away "
    "from the frame and from the title block at the bottom."
)

DOC_NUMBER = "SYN-LF-0001"
REVISION = "Revision A"


def _y(top: float) -> float:
    """A distance from the page top, as a reportlab y coordinate."""
    return PAGE_HEIGHT - top


def draw_line_frame(c: canvas.Canvas, page_number: int) -> None:
    """The page frame: a filled inner rect, 4 border lines and a 31-line
    title block, each drawn as its own path."""
    x0, top, x1, bottom = INNER_RECT
    c.setFillColorRGB(1, 1, 1)
    c.rect(x0, _y(bottom), x1 - x0, bottom - top, stroke=0, fill=1)
    c.setFillColorRGB(0, 0, 0)

    c.setLineWidth(0.8)
    bx0, btop, bx1, bbottom = BORDER
    c.line(bx0, _y(btop), bx1, _y(btop))
    c.line(bx0, _y(bbottom), bx1, _y(bbottom))
    c.line(bx0, _y(btop), bx0, _y(bbottom))
    c.line(bx1, _y(btop), bx1, _y(bbottom))

    for row in TITLE_BLOCK_ROWS:
        for left, right in pairwise(TITLE_BLOCK_COLS):
            c.line(left, _y(row), right, _y(row))
    for col in TITLE_BLOCK_COLS:
        for upper, lower in pairwise(TITLE_BLOCK_ROWS):
            c.line(col, _y(upper), col, _y(lower))

    c.setFont("Helvetica", 8)
    c.drawString(306, _y(726), DOC_NUMBER)
    c.drawString(306, _y(746), REVISION)
    c.drawString(306, _y(766), f"page {page_number} ({PAGE_COUNT})")


def draw_body(c: canvas.Canvas, page_number: int) -> None:
    c.setFont("Helvetica-Bold", 16)
    c.drawString(LEFT_MARGIN, _y(70), HEADINGS[page_number - 1])
    generate_sample.draw_wrapped_text(
        c, PARAGRAPHS[page_number - 1], LEFT_MARGIN, _y(100), 90, 11, 15
    )
    generate_sample.draw_wrapped_text(
        c, SECOND_PARAGRAPH, LEFT_MARGIN, _y(560), 90, 11, 15
    )


def generate(output_pdf: Path = OUTPUT_PDF) -> None:
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(output_pdf), pagesize=letter)
    for page_number in range(1, PAGE_COUNT + 1):
        draw_line_frame(c, page_number)
        draw_body(c, page_number)
        if page_number == 2:
            generate_sample.draw_flow_diagram(c, DIAGRAM_BOXES)
            c.setFont("Helvetica", 10)
            c.drawString(100, 330, DIAGRAM_CAPTION)
        if page_number == 3:
            c.setLineWidth(0.8)
            generate_sample.draw_table(
                c,
                TABLE_ROWS,
                x=TABLE_X,
                y=_y(TABLE_TOP),
                col_widths=TABLE_COL_WIDTHS,
                row_height=TABLE_ROW_HEIGHT,
            )
        c.showPage()
    c.save()


def main() -> None:
    generate()
    print(f"wrote {OUTPUT_PDF}")


if __name__ == "__main__":
    main()
