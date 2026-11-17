"""A small table inside a large diagram does not hide the diagram; a
table's own ruling stays a table."""

import fitz  # PyMuPDF
from conftest import load_script
from test_fill_rects import _state_diagram_page
from test_header_row_table import _header_row_page

W, H = 595.0, 842.0

figures = load_script("../lib/figures.py", "figures_table_in_figure")


def test_state_diagram_with_label_backgrounds_is_a_figure(tmp_path):
    pdf_path = tmp_path / "diagram.pdf"
    _state_diagram_page(pdf_path)
    with fitz.open(pdf_path) as doc:
        regions, excluded = figures.detect_figure_regions_with_exclusions(doc[0], 1, pdf_path)
    assert any(r["bbox"][0] <= 50 and r["bbox"][3] >= 340 for r in regions), excluded


def _diagram_with_small_table_page(path) -> None:
    """A large diagram (boxes and connector lines) with a small ruled 2x2
    legend table in one corner."""
    pdf = fitz.open()
    page = pdf.new_page(width=W, height=H)
    shape = page.new_shape()
    for box in (fitz.Rect(80, 200, 200, 260), fitz.Rect(320, 200, 440, 260), fitz.Rect(200, 380, 320, 440)):
        shape.draw_rect(box, radius=0.1)
        shape.finish(color=(0, 0, 0), fill=(0.8, 0.9, 1.0), width=0.8)
    for a, b in (((200, 230), (320, 230)), ((140, 260), (240, 380)), ((380, 260), (280, 380))):
        shape.draw_line(a, b)
        shape.finish(color=(0, 0, 0), width=0.8)
    shape.commit()
    page.insert_text((100, 235), "Source", fontsize=9)
    page.insert_text((340, 235), "Target", fontsize=9)
    page.insert_text((220, 415), "Store", fontsize=9)
    for x in (380, 420, 460):
        page.draw_line((x, 400), (x, 430), width=0.5)
    for y in (400, 415, 430):
        page.draw_line((380, y), (460, y), width=0.5)
    for x, y, t in ((382, 411, "Key"), (422, 411, "Val"), (382, 426, "a"), (422, 426, "b")):
        page.insert_text((x, y), t, fontsize=7)
    pdf.save(str(path))
    pdf.close()


def test_small_table_inside_a_diagram_does_not_hide_it(tmp_path):
    pdf_path = tmp_path / "legend.pdf"
    _diagram_with_small_table_page(pdf_path)
    with fitz.open(pdf_path) as doc:
        regions, excluded = figures.detect_figure_regions_with_exclusions(doc[0], 1, pdf_path)
    assert any(r["bbox"][0] <= 80 and r["bbox"][3] >= 440 for r in regions), excluded
    assert [r["reason"] for r in excluded if "table" in r["reason"]] == ["table_in_figure"], excluded


def test_ruled_table_row_stays_excluded_as_table(tmp_path):
    pdf_path = tmp_path / "row.pdf"
    _header_row_page(pdf_path, data_rows=0)
    with fitz.open(pdf_path) as doc:
        regions, excluded = figures.detect_figure_regions_with_exclusions(doc[0], 1, pdf_path)
    assert regions == [], regions
    assert [r["reason"] for r in excluded] == ["table_overlap"], excluded


def test_page_border_with_a_small_table_is_no_figure(tmp_path):
    """A one-page document with a border near the page edges: the border
    joins every drawing into one page-sized cluster, which a small table
    in it must not turn into a figure."""
    pdf = fitz.open()
    page = pdf.new_page(width=W, height=H)
    page.draw_rect(fitz.Rect(20, 20, W - 20, H - 20), width=1)
    page.draw_line((60, 120), (535, 120), width=0.5)
    for i in range(10):
        page.insert_text((60, 150 + 14 * i), f"Body text line {i} of the bordered page.", fontsize=10)
    for x in (60, 160, 260):
        page.draw_line((x, 400), (x, 430), width=0.5)
    for y in (400, 415, 430):
        page.draw_line((60, y), (260, y), width=0.5)
    for x, y, t in ((62, 411, "Key"), (162, 411, "Val"), (62, 426, "a"), (162, 426, "b")):
        page.insert_text((x, y), t, fontsize=8)
    pdf.save(str(tmp_path / "border.pdf"))
    pdf.close()
    with fitz.open(tmp_path / "border.pdf") as doc:
        regions, excluded = figures.detect_figure_regions_with_exclusions(doc[0], 1, tmp_path / "border.pdf")
    assert regions == [], (regions, excluded)
    assert [r["reason"] for r in excluded] == ["table_overlap"], excluded
