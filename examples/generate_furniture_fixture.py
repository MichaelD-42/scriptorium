#!/usr/bin/env python3
"""Generate the synthetic furniture/TOC/heading/figure/list test fixture used
by Track A of the PDF-extraction plan (Task A0 onward).

This is a *second*, purpose-built PDF alongside sample.pdf -- sample.pdf
stays untouched as the existing regression fixture. This one packs, in a
single 9-page document, the cases the furniture/TOC/heading/figure/list
handling needs and sample.pdf does not exercise:

  1. Page frame + furniture (a ruled border, a small logo, a 3-line footer
     with a doc number / revision / "page N (TOTAL)") repeated on every page.
  2. A two-page printed TOC (pages 2-3) with dot leaders, including entries
     where the number and title print on separate lines.
  3. Body headings (pages 4-8) at 4 distinct bold sizes (18/16/14/12pt for
     levels 1-4), each number+title matching a TOC entry exactly.
  4. A vector-drawn flow diagram on a text-heavy body page (page 7).
  5. A vector-drawn bar chart on another text-heavy body page (page 8).
  6. A real ruled table on a body page that does not cover the whole page
     (page 8).
  7. "Figure n" captions near the diagram and the chart.
  8. A nested (2-level) bullet list (page 6).
  9. A paragraph deliberately cut across a page break (page 4 -> page 5),
     with no terminating punctuation at the break.
  10. A page whose only content is a table entirely inside the page-frame
      rectangle (page 9) -- the frame-vs-real-table disambiguation case.

Alongside the PDF this writes a hand-authored answer key,
furniture_golden.json, recording furniture line texts + y-bands, the frame
bbox, TOC entries, heading texts/levels, figure captions, the bullet list,
the table(s), and where the cut paragraph starts/continues. Later tasks'
tests read that JSON as ground truth instead of hand-coding expectations.

Reuses generate_sample.py's reportlab canvas drawing helpers
(draw_wrapped_text, draw_table, draw_flow_diagram) rather than inventing a
new drawing style.

Run with:
    uv run --project plugins/scriptorium python examples/generate_furniture_fixture.py
"""

import json
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

import generate_sample  # reuse draw_wrapped_text / draw_table / draw_flow_diagram

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PDF = ROOT / "plugins" / "scriptorium" / "examples" / "furniture_sample.pdf"
GOLDEN_JSON = ROOT / "plugins" / "scriptorium" / "examples" / "furniture_golden.json"

PAGE_WIDTH, PAGE_HEIGHT = letter
PAGE_COUNT = 9
LEFT_MARGIN = 72

# --- furniture geometry (identical on every page) --------------------------
FRAME_MARGIN = 24
LOGO_X, LOGO_Y, LOGO_SIZE = 40, PAGE_HEIGHT - 60, 26
FOOTER_X = 40
FOOTER_LINES_Y = [58, 46, 34]  # reportlab baselines (bottom-up), top to bottom line
DOC_NUMBER_TEXT = "Doc No. SYN-FUR-0001"
REVISION_TEXT = "Rev. B"

HEADING_SIZES = {1: 18, 2: 16, 3: 14, 4: 12}

# --- TOC / heading source of truth (single list drives TOC text, body
# headings, and the golden headings section, so all three can't drift apart)
TOC_ENTRIES = [
    {"number": "1", "title": "Introduction", "page": 4, "level": 1, "split_line": False},
    {"number": "1.1", "title": "Purpose and Scope", "page": 4, "level": 2, "split_line": False},
    {"number": "1.2", "title": "Document Overview", "page": 5, "level": 2, "split_line": False},
    {"number": "2", "title": "System Requirements", "page": 5, "level": 1, "split_line": False},
    {"number": "2.1", "title": "Functional Requirements", "page": 5, "level": 2, "split_line": False},
    {"number": "2.1.1", "title": "Data Processing Pipeline", "page": 6, "level": 3, "split_line": True},
    {"number": "2.1.2", "title": "Edge Case Handling", "page": 7, "level": 4, "split_line": True},
    {"number": "2.2", "title": "Non-Functional Requirements", "page": 7, "level": 2, "split_line": False},
    {"number": "3", "title": "Process Diagrams", "page": 8, "level": 1, "split_line": False},
    {"number": "3.1", "title": "Workflow Overview", "page": 8, "level": 2, "split_line": True},
]

COVER_PARA = (
    "This synthetic document combines a bordered page frame, running header and footer "
    "furniture, a two-page printed table of contents, four levels of body headings, a "
    "vector diagram, a vector bar chart, a ruled table, and a nested bullet list, all "
    "built purely for automated testing -- it contains no real customer content."
)

P_INTRO_1 = (
    "This section describes the purpose of the furniture fixture and the structural "
    "extraction cases it is designed to exercise across the pages that follow."
)
# The cut paragraph: PART_A ends its page with no terminating punctuation and
# PART_B continues it in prose at the same left margin on the next page,
# before any heading -- the join detector's positive case.
CUT_PART_A = (
    "The scope of this specification covers every furniture element a real document "
    "might carry, including running headers, footers, and a bordered page frame that "
    "must never be mistaken for genuine page content such as"
)
CUT_PART_B = (
    "a ruled table or a printed figure, which is exactly why this paragraph is "
    "deliberately split across a page boundary without terminating punctuation."
)
P_DOC_OVERVIEW = (
    "This document is organized into numbered sections that mirror the printed table "
    "of contents on the preceding two pages, so every heading below can be matched "
    "against its TOC entry by number and title."
)
P_SYS_REQ = (
    "The synthetic body pages that follow combine headings, paragraphs, figures, and "
    "lists to give the extraction pipeline a realistic mixture of structural elements "
    "to classify."
)
P_FUNC_REQ = (
    "Functional requirements in this fixture are limited to reproducing the structural "
    "shapes a real specification exhibits, not to describing any actual product behavior."
)
P_DATA_PROC = (
    "The data processing section below demonstrates a two-level bullet list, used "
    "elsewhere in real specifications to enumerate the sub-steps of a larger procedure."
)
P_EDGE_CASE = (
    "Edge cases recorded here are fixture-generation edge cases only: a heading "
    "printed at the smallest of the four bold sizes used across this document."
)
P_NONFUNC = (
    "Non-functional requirements in this fixture take the form of a vector-drawn flow "
    "diagram placed beside several lines of body text, so the diagram is never the only "
    "content on its page -- the case the old whole-page rule misses."
)
P_PROCESS_DIAG = (
    "This section pairs a vector-drawn bar chart with a short caption, again "
    "surrounded by body paragraph text rather than standing alone on an otherwise "
    "blank page."
)
P_WORKFLOW = (
    "The ruled table below summarizes a short set of values and is positioned so that "
    "it does not cover the entire page, distinguishing it from the page-frame border "
    "drawn around every page."
)

BULLET_ITEMS = [
    (1, "Ingestion"),
    (2, "Normalize incoming documents before parsing."),
    (2, "Validate structural markers such as headings and page numbers."),
    (1, "Transformation"),
    (2, "Apply extraction rules for each recognized element type."),
]

WORKFLOW_TABLE_ROWS = [
    ["Stage", "Input", "Output"],
    ["Triage", "Raw document", "Tier assignment"],
    ["Extract", "Tier assignment", "Element shards"],
]
LONE_TABLE_ROWS = [
    ["Field", "Value"],
    ["Status", "Draft"],
    ["Owner", "Fixture"],
]


def make_logo_bytes() -> bytes:
    img = Image.new("RGB", (64, 64), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle((4, 4, 60, 60), fill=(60, 60, 60), outline="black", width=2)
    draw.ellipse((18, 18, 46, 46), fill=(230, 230, 230))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_unique_icon_bytes() -> bytes:
    """A second, visually distinct bitmap placed on exactly one page (Task
    A2) -- unlike the logo (repeated on every page), this one is not
    furniture: it should survive extract-images.py's furniture-xref skip
    since it never clears REPEATED_IMAGE_MIN_PAGE_FRACTION."""
    img = Image.new("RGB", (64, 64), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle((4, 4, 60, 60), fill=(200, 200, 60), outline="black", width=2)
    draw.polygon([(32, 10), (54, 54), (10, 54)], fill=(80, 80, 200))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def rect_bbox(x: float, y: float, w: float, h: float) -> list[float]:
    """Convert a reportlab-coordinate rect (bottom-left x,y + width/height,
    y increasing upward) to a fitz/pdfplumber-style bbox [x0, top, x1,
    bottom] (top-left origin, y increasing downward) -- matching what
    PyMuPDF/pdfplumber report elsewhere in this pipeline (see
    extract_text.py's block/table bboxes)."""
    return [round(x, 2), round(PAGE_HEIGHT - (y + h), 2), round(x + w, 2), round(PAGE_HEIGHT - y, 2)]


def y_band(top_rl: float, bottom_rl: float) -> list[float]:
    """Page-fraction y-band (top-down: 0.0 = page top, 1.0 = page bottom)
    for a reportlab y-range [bottom_rl, top_rl]."""
    return [
        round((PAGE_HEIGHT - top_rl) / PAGE_HEIGHT, 4),
        round((PAGE_HEIGHT - bottom_rl) / PAGE_HEIGHT, 4),
    ]


def toc_line(entry: dict, width: int = 60) -> str:
    left = f"{entry['number']} {entry['title']}"
    dots = "." * max(3, width - len(left))
    return f"{left} {dots} {entry['page']}"


def toc_split_lines(entry: dict, width: int = 60) -> tuple[str, str]:
    dots = "." * max(3, width - len(entry["title"]))
    return entry["number"], f"{entry['title']} {dots} {entry['page']}"


def draw_furniture(c: canvas.Canvas, logo_reader: ImageReader, page_num: int, total_pages: int) -> None:
    c.setLineWidth(0.75)
    c.rect(FRAME_MARGIN, FRAME_MARGIN, PAGE_WIDTH - 2 * FRAME_MARGIN, PAGE_HEIGHT - 2 * FRAME_MARGIN, stroke=1, fill=0)
    c.drawImage(logo_reader, LOGO_X, LOGO_Y, LOGO_SIZE, LOGO_SIZE)
    c.setFont("Helvetica", 8)
    c.drawString(FOOTER_X, FOOTER_LINES_Y[0], DOC_NUMBER_TEXT)
    c.drawString(FOOTER_X, FOOTER_LINES_Y[1], REVISION_TEXT)
    c.drawString(FOOTER_X, FOOTER_LINES_Y[2], f"page {page_num} ({total_pages})")


def draw_heading(c: canvas.Canvas, x: float, y: float, entry: dict) -> float:
    size = HEADING_SIZES[entry["level"]]
    c.setFont("Helvetica-Bold", size)
    c.drawString(x, y, f"{entry['number']} {entry['title']}")
    return y - size * 1.6


def draw_bar_chart(c: canvas.Canvas, x: float, y: float, bars: list[tuple[str, float]], bar_width: float = 30, gap: float = 20, max_height: float = 90) -> None:
    """A simple vertical bar chart: a few rectangles of different heights
    plus x/y axis lines, in the same rect+line style as draw_table/
    draw_flow_diagram. `y` is the baseline (bottom) of the bars."""
    axis_right = x + len(bars) * (bar_width + gap)
    c.setLineWidth(1)
    c.line(x - 10, y, axis_right, y)
    c.line(x - 10, y, x - 10, y + max_height + 15)
    c.setFillGray(0.6)
    c.setFont("Helvetica", 8)
    for i, (label, frac) in enumerate(bars):
        bx = x + i * (bar_width + gap)
        bh = frac * max_height
        c.rect(bx, y, bar_width, bh, stroke=1, fill=1)
        c.setFillGray(0)
        c.drawCentredString(bx + bar_width / 2, y - 12, label)
        c.setFillGray(0.6)
    c.setFillGray(0)


def generate(output_pdf: Path = OUTPUT_PDF, output_json: Path = GOLDEN_JSON) -> dict:
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    logo_reader = ImageReader(Image.open(BytesIO(make_logo_bytes())))
    unique_icon_reader = ImageReader(Image.open(BytesIO(make_unique_icon_bytes())))

    c = canvas.Canvas(str(output_pdf), pagesize=letter)

    headings_golden = []
    figures_golden = []
    bullet_golden = []

    def entry(i):
        return TOC_ENTRIES[i]

    # Page 1: cover
    y = PAGE_HEIGHT - 220
    c.setFont("Helvetica-Bold", 24)
    c.drawCentredString(PAGE_WIDTH / 2, y, "Synthetic Furniture Fixture")
    y -= 30
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(PAGE_WIDTH / 2, y, "A Golden Extraction Test Document")
    y -= 40
    generate_sample.draw_wrapped_text(c, COVER_PARA, LEFT_MARGIN, y, 90, 11, 15)
    draw_furniture(c, logo_reader, 1, PAGE_COUNT)
    c.showPage()

    # Pages 2-3: two-page printed TOC, with dot leaders. Entries 5, 6, 9
    # (2.1.1 / 2.1.2 / 3.1) print number-alone-then-title -- the case where
    # the number and title are on separate lines.
    c.setFont("Helvetica-Bold", 18)
    c.drawString(LEFT_MARGIN, PAGE_HEIGHT - 110, "Table of Contents")
    y = PAGE_HEIGHT - 150
    c.setFont("Helvetica", 11)
    for e in TOC_ENTRIES[0:5]:
        c.drawString(LEFT_MARGIN, y, toc_line(e))
        y -= 24
    draw_furniture(c, logo_reader, 2, PAGE_COUNT)
    c.showPage()

    y = PAGE_HEIGHT - 110
    c.setFont("Helvetica", 11)
    for e in TOC_ENTRIES[5:10]:
        if e["split_line"]:
            line1, line2 = toc_split_lines(e)
            c.drawString(LEFT_MARGIN, y, line1)
            y -= 16
            c.drawString(LEFT_MARGIN, y, line2)
            y -= 24
        else:
            c.drawString(LEFT_MARGIN, y, toc_line(e))
            y -= 24
    draw_furniture(c, logo_reader, 3, PAGE_COUNT)
    c.showPage()

    # Page 4: "1 Introduction", "1.1 Purpose and Scope", then the cut
    # paragraph -- ends the page with no terminating punctuation.
    y = PAGE_HEIGHT - 100
    y = draw_heading(c, LEFT_MARGIN, y, entry(0))
    headings_golden.append({**entry(0), "font_size": HEADING_SIZES[entry(0)["level"]]})
    y -= 6
    y = generate_sample.draw_wrapped_text(c, P_INTRO_1, LEFT_MARGIN, y, 90, 11, 15)
    y -= 20
    y = draw_heading(c, LEFT_MARGIN, y, entry(1))
    headings_golden.append({**entry(1), "font_size": HEADING_SIZES[entry(1)["level"]]})
    y -= 6
    generate_sample.draw_wrapped_text(c, CUT_PART_A, LEFT_MARGIN, y, 90, 11, 15)
    # A second, unique (non-repeated) bitmap -- top-right corner, clear of
    # the heading/body text and the frame border -- Task A2's negative case
    # for extract-images.py's furniture-xref skip (this one must NOT be
    # skipped, unlike the logo).
    c.drawImage(unique_icon_reader, PAGE_WIDTH - 40 - 26, PAGE_HEIGHT - 60, 26, 26)
    draw_furniture(c, logo_reader, 4, PAGE_COUNT)
    c.showPage()

    # Page 5: continuation of the cut paragraph (same left margin, before
    # any heading), then "1.2", "2", "2.1".
    y = PAGE_HEIGHT - 100
    y = generate_sample.draw_wrapped_text(c, CUT_PART_B, LEFT_MARGIN, y, 90, 11, 15)
    y -= 20
    y = draw_heading(c, LEFT_MARGIN, y, entry(2))
    headings_golden.append({**entry(2), "font_size": HEADING_SIZES[entry(2)["level"]]})
    y -= 6
    y = generate_sample.draw_wrapped_text(c, P_DOC_OVERVIEW, LEFT_MARGIN, y, 90, 11, 15)
    y -= 20
    y = draw_heading(c, LEFT_MARGIN, y, entry(3))
    headings_golden.append({**entry(3), "font_size": HEADING_SIZES[entry(3)["level"]]})
    y -= 6
    y = generate_sample.draw_wrapped_text(c, P_SYS_REQ, LEFT_MARGIN, y, 90, 11, 15)
    y -= 20
    y = draw_heading(c, LEFT_MARGIN, y, entry(4))
    headings_golden.append({**entry(4), "font_size": HEADING_SIZES[entry(4)["level"]]})
    y -= 6
    generate_sample.draw_wrapped_text(c, P_FUNC_REQ, LEFT_MARGIN, y, 90, 11, 15)
    draw_furniture(c, logo_reader, 5, PAGE_COUNT)
    c.showPage()

    # Page 6: "2.1.1 Data Processing Pipeline" + a nested (2-level) bullet list.
    y = PAGE_HEIGHT - 100
    y = draw_heading(c, LEFT_MARGIN, y, entry(5))
    headings_golden.append({**entry(5), "font_size": HEADING_SIZES[entry(5)["level"]]})
    y -= 6
    y = generate_sample.draw_wrapped_text(c, P_DATA_PROC, LEFT_MARGIN, y, 90, 11, 15)
    y -= 15
    for level, text in BULLET_ITEMS:
        x = LEFT_MARGIN + (level - 1) * 18
        width_chars = 90 - (level - 1) * 10
        y = generate_sample.draw_wrapped_text(c, f"- {text}", x, y, width_chars, 11, 15)
        y -= 4
        bullet_golden.append({"level": level, "text": text})
    draw_furniture(c, logo_reader, 6, PAGE_COUNT)
    c.showPage()

    # Page 7: "2.1.2 Edge Case Handling", then "2.2 Non-Functional
    # Requirements" with a vector flow diagram + "Figure 1" caption on an
    # otherwise text-heavy page.
    y = PAGE_HEIGHT - 100
    y = draw_heading(c, LEFT_MARGIN, y, entry(6))
    headings_golden.append({**entry(6), "font_size": HEADING_SIZES[entry(6)["level"]]})
    y -= 6
    y = generate_sample.draw_wrapped_text(c, P_EDGE_CASE, LEFT_MARGIN, y, 90, 11, 15)
    y -= 25
    y = draw_heading(c, LEFT_MARGIN, y, entry(7))
    headings_golden.append({**entry(7), "font_size": HEADING_SIZES[entry(7)["level"]]})
    y -= 6
    y = generate_sample.draw_wrapped_text(c, P_NONFUNC, LEFT_MARGIN, y, 90, 11, 15)
    y -= 20
    box_w, box_h = 85, 30
    boxes = [
        (LEFT_MARGIN, y - 40, box_w, box_h, "Start"),
        (LEFT_MARGIN + 140, y - 40, box_w, box_h, "Process"),
        (LEFT_MARGIN + 280, y - 40, box_w, box_h, "Decision"),
        (LEFT_MARGIN + 140, y - 110, box_w, box_h, "End"),
    ]
    generate_sample.draw_flow_diagram(c, boxes)
    caption_y = y - 130
    c.setFont("Helvetica-Oblique", 9)
    c.drawString(LEFT_MARGIN, caption_y, "Figure 1: Process Diagram")
    figures_golden.append({"caption": "Figure 1: Process Diagram", "page": 7, "kind": "diagram"})
    draw_furniture(c, logo_reader, 7, PAGE_COUNT)
    c.showPage()

    # Page 8: "3 Process Diagrams" with a vector bar chart + "Figure 2"
    # caption, then "3.1 Workflow Overview" with a ruled table that does
    # NOT cover the whole page.
    y = PAGE_HEIGHT - 100
    y = draw_heading(c, LEFT_MARGIN, y, entry(8))
    headings_golden.append({**entry(8), "font_size": HEADING_SIZES[entry(8)["level"]]})
    y -= 6
    y = generate_sample.draw_wrapped_text(c, P_PROCESS_DIAG, LEFT_MARGIN, y, 90, 11, 15)
    y -= 20
    chart_x, chart_y = LEFT_MARGIN + 20, y - 110
    bars = [("Q1", 0.5), ("Q2", 0.7), ("Q3", 0.9), ("Q4", 0.65)]
    draw_bar_chart(c, chart_x, chart_y, bars, bar_width=30, gap=20, max_height=90)
    caption_y2 = y - 150  # clear of the bar chart's axis labels (drawn at chart_y - 12)
    c.setFont("Helvetica-Oblique", 9)
    c.drawString(LEFT_MARGIN, caption_y2, "Figure 2: Revenue by Quarter")
    figures_golden.append({"caption": "Figure 2: Revenue by Quarter", "page": 8, "kind": "chart"})
    y = caption_y2 - 30
    y = draw_heading(c, LEFT_MARGIN, y, entry(9))
    headings_golden.append({**entry(9), "font_size": HEADING_SIZES[entry(9)["level"]]})
    y -= 6
    y = generate_sample.draw_wrapped_text(c, P_WORKFLOW, LEFT_MARGIN, y, 90, 11, 15)
    y -= 15
    table_col_widths = [110, 110, 110]
    table_row_height = 22
    generate_sample.draw_table(c, WORKFLOW_TABLE_ROWS, x=LEFT_MARGIN, y=y, col_widths=table_col_widths, row_height=table_row_height)
    table_bbox = rect_bbox(LEFT_MARGIN, y - table_row_height * len(WORKFLOW_TABLE_ROWS), sum(table_col_widths), table_row_height * len(WORKFLOW_TABLE_ROWS))
    draw_furniture(c, logo_reader, 8, PAGE_COUNT)
    c.showPage()

    # Page 9: only content is a small ruled table, entirely inside the page
    # frame rectangle -- the frame-vs-real-table disambiguation case.
    lone_x = PAGE_WIDTH / 2 - 150
    lone_y = PAGE_HEIGHT / 2 + 40
    lone_col_widths = [150, 150]
    lone_row_height = 22
    generate_sample.draw_table(c, LONE_TABLE_ROWS, x=lone_x, y=lone_y, col_widths=lone_col_widths, row_height=lone_row_height)
    lone_table_bbox = rect_bbox(lone_x, lone_y - lone_row_height * len(LONE_TABLE_ROWS), sum(lone_col_widths), lone_row_height * len(LONE_TABLE_ROWS))
    draw_furniture(c, logo_reader, 9, PAGE_COUNT)
    c.showPage()

    c.save()

    furniture_golden = {
        "pages": list(range(1, PAGE_COUNT + 1)),
        "frame_bbox": rect_bbox(FRAME_MARGIN, FRAME_MARGIN, PAGE_WIDTH - 2 * FRAME_MARGIN, PAGE_HEIGHT - 2 * FRAME_MARGIN),
        "logo_bbox": rect_bbox(LOGO_X, LOGO_Y, LOGO_SIZE, LOGO_SIZE),
        "lines": [
            {"text": DOC_NUMBER_TEXT, "y_band": y_band(FOOTER_LINES_Y[0] + 7, FOOTER_LINES_Y[0] - 2)},
            {"text": REVISION_TEXT, "y_band": y_band(FOOTER_LINES_Y[1] + 7, FOOTER_LINES_Y[1] - 2)},
            {"text_template": "page {n} ({total})", "y_band": y_band(FOOTER_LINES_Y[2] + 7, FOOTER_LINES_Y[2] - 2)},
        ],
    }

    golden = {
        "page_count": PAGE_COUNT,
        "page_size": {"width": PAGE_WIDTH, "height": PAGE_HEIGHT},
        "furniture": furniture_golden,
        "toc": {"pages": [2, 3], "entries": TOC_ENTRIES},
        "headings": headings_golden,
        "figures": figures_golden,
        "bullet_list": {"page": 6, "items": bullet_golden},
        "table": {
            "content_page": 8,
            "content_bbox": table_bbox,
            "note": "positioned mid-page; does not cover the full page",
            "frame_only_page": 9,
            "frame_only_bbox": lone_table_bbox,
        },
        "cut_paragraph": {
            "start_page": 4,
            "continues_page": 5,
            "start_text": CUT_PART_A,
            "continuation_text": CUT_PART_B,
        },
    }

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(golden, indent=2))
    return golden


def main() -> None:
    generate()
    print(f"wrote {OUTPUT_PDF}")
    print(f"wrote {GOLDEN_JSON}")


if __name__ == "__main__":
    main()
