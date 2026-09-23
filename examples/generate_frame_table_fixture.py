#!/usr/bin/env python3
"""Generate a small fixture PDF for Task A2's frame-table exclusion tests.

`furniture_sample.pdf`'s page frame (Task A0) is a plain, unruled
`c.rect()` border -- pdfplumber's `find_tables()` does not pick that up as
a table (confirmed by Task A0/A1's manual checks and its own
`frame_tables: []` test), so that fixture never exercises `triage.py`'s
`_find_frame_tables()` detector or Task A2's frame-table-removal code path
(item 1/2 of the A2 brief).

This second, purpose-built fixture adds one internal ruling line across the
frame border. An empirical probe (see task-A2-report.md) confirmed
pdfplumber's line-based table heuristic *does* then pick up the frame as a
single table covering ~87% of the page area, without merging it with a
separately-drawn real table elsewhere on the page (the two line clusters
don't touch, so pdfplumber keeps them as distinct tables).

Kept deliberately small and separate from `furniture_sample.pdf` -- Task A0's
fixture is already reviewed/approved with several tests asserting byte-exact
equality against `furniture_golden.json`, and this task's brief explicitly
allows a second small fixture instead of risking that geometry.

Three pages:
  1. Frame (ruled) only, plus a body paragraph -- no real table. Exercises
     `page_has_table() == False` and "frame table never becomes an
     element" when the page's only pdfplumber table is the frame.
  2. Frame (ruled) plus a real, separate ruled table -- the
     frame-vs-real-table disambiguation case. Exercises
     `page_has_table() == True` and "the real table survives extraction".
  3. Frame (ruled) only again, with different body text -- repeats the same
     frame bbox so triage.py's >=50%-of-pages repetition threshold for
     `frame_tables` is met (3/3 pages here).

Run with:
    uv run --project plugins/scriptorium python examples/generate_frame_table_fixture.py
"""

from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

import generate_sample  # reuse draw_wrapped_text / draw_table

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PDF = ROOT / "plugins" / "scriptorium" / "examples" / "frame_table_sample.pdf"

PAGE_WIDTH, PAGE_HEIGHT = letter
PAGE_COUNT = 3
LEFT_MARGIN = 72

FRAME_MARGIN = 24

REAL_TABLE_ROWS = [["Field", "Value"], ["Status", "Draft"]]
REAL_TABLE_X, REAL_TABLE_Y = 200, 300
REAL_TABLE_COL_WIDTHS = [90, 90]
REAL_TABLE_ROW_HEIGHT = 20

PARA_1 = (
    "This page's only content besides the ruled page frame is this paragraph -- "
    "there is no real table here, only the frame itself."
)
PARA_2 = (
    "This page adds a small, separately-ruled table below, distinct from the "
    "page frame that surrounds it."
)
PARA_3 = (
    "This page repeats the ruled page frame a second time with different body "
    "text, so the frame's bounding box is seen on a majority of pages."
)


def draw_frame_with_ruling(c: canvas.Canvas) -> None:
    """A page frame with one internal horizontal ruling line -- unlike
    furniture_sample.pdf's plain c.rect() border, this gives pdfplumber's
    line-based table heuristic a real row structure (top half / bottom
    half) to detect as a table, rather than just four unconnected border
    segments."""
    c.setLineWidth(0.75)
    c.rect(FRAME_MARGIN, FRAME_MARGIN, PAGE_WIDTH - 2 * FRAME_MARGIN, PAGE_HEIGHT - 2 * FRAME_MARGIN, stroke=1, fill=0)
    mid_y = PAGE_HEIGHT / 2
    c.line(FRAME_MARGIN, mid_y, PAGE_WIDTH - FRAME_MARGIN, mid_y)


def generate(output_pdf: Path = OUTPUT_PDF) -> None:
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(output_pdf), pagesize=letter)

    # Page 1: frame (ruled) only -- no real table.
    draw_frame_with_ruling(c)
    generate_sample.draw_wrapped_text(c, PARA_1, LEFT_MARGIN, PAGE_HEIGHT - 100, 90, 11, 15)
    c.showPage()

    # Page 2: frame (ruled) + a real, separate ruled table.
    draw_frame_with_ruling(c)
    generate_sample.draw_wrapped_text(c, PARA_2, LEFT_MARGIN, PAGE_HEIGHT - 100, 90, 11, 15)
    generate_sample.draw_table(
        c, REAL_TABLE_ROWS, x=REAL_TABLE_X, y=REAL_TABLE_Y,
        col_widths=REAL_TABLE_COL_WIDTHS, row_height=REAL_TABLE_ROW_HEIGHT,
    )
    c.showPage()

    # Page 3: frame (ruled) only again -- repeats the bbox for the
    # >=50%-of-pages repetition threshold.
    draw_frame_with_ruling(c)
    generate_sample.draw_wrapped_text(c, PARA_3, LEFT_MARGIN, PAGE_HEIGHT - 100, 90, 11, 15)
    c.showPage()

    c.save()


def main() -> None:
    generate()
    print(f"wrote {OUTPUT_PDF}")


if __name__ == "__main__":
    main()
