"""Follow-up R20: a table row at a page edge with no rule on its open side.

A table that continues from the previous page often starts with a row that
has no top rule: its column rules start above the page's first text line,
but no horizontal rule closes the row. pdfplumber builds cells only between
two horizontal edges, so that row was dropped and its text became a loose
paragraph. `figures.page_tables` now adds a cap rule (as an explicit
horizontal line, only across those column rules) where at least two
vertical rules start above the page's first text line (or end below its
last) with no horizontal rule there.
"""

import figures as figures_lib
import fitz  # PyMuPDF

W, H = 595.0, 842.0


def _table_pdf(path, open_top: bool) -> None:
    pdf = fitz.open()
    page = pdf.new_page(width=W, height=H)
    xs = (64, 160, 450)
    top, rows = 40, (60, 80, 100)
    for x in xs:
        page.draw_line((x, top), (x, rows[-1]), width=0.8)
    for y in rows if open_top else (top,) + rows:
        page.draw_line((xs[0], y), (xs[-1], y), width=0.8)
    page.insert_text((68, 54), "IMDS", fontsize=10)
    page.insert_text((164, 54), "Synthetic material data system", fontsize=10)
    page.insert_text((68, 74), "ImSn", fontsize=10)
    page.insert_text((164, 74), "Immersion tin", fontsize=10)
    page.insert_text((68, 94), "ISO", fontsize=10)
    page.insert_text((164, 94), "Standards body", fontsize=10)
    page.insert_text((64, 140), "Body text below the table.", fontsize=10)
    pdf.save(str(path))
    pdf.close()


class TestOpenTopRow:
    def test_open_top_row_is_kept(self, tmp_path):
        pdf = tmp_path / "open_top.pdf"
        _table_pdf(pdf, open_top=True)
        tables = figures_lib.page_tables(pdf, 1)
        assert len(tables) == 1
        assert [row[0] for row in tables[0]["rows"]] == ["IMDS", "ImSn", "ISO"]

    def test_closed_table_is_unchanged(self, tmp_path):
        pdf = tmp_path / "closed.pdf"
        _table_pdf(pdf, open_top=False)
        tables = figures_lib.page_tables(pdf, 1)
        assert len(tables) == 1
        assert [row[0] for row in tables[0]["rows"]] == ["IMDS", "ImSn", "ISO"]

    def test_a_single_vertical_rule_gets_no_cap(self, tmp_path):
        pdf_path = tmp_path / "single.pdf"
        pdf = fitz.open()
        page = pdf.new_page(width=W, height=H)
        page.draw_line((300, 30), (300, 200), width=0.8)
        page.insert_text((64, 54), "Left column text.", fontsize=10)
        page.insert_text((310, 54), "Right column text.", fontsize=10)
        pdf.save(str(pdf_path))
        pdf.close()
        assert figures_lib.page_tables(pdf_path, 1) == []
