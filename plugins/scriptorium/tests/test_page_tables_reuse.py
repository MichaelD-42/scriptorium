"""`figures.page_tables` opens a PDF with pdfplumber once per file, not once
per call: pdfplumber parses every page object when a page is indexed, so a
reopen per page made a whole-document extraction quadratic in page count.
"""

import figures as figures_lib
import fitz  # PyMuPDF
import pdfplumber


def _pdf(path, pages: int, table: bool) -> None:
    pdf = fitz.open()
    for _ in range(pages):
        page = pdf.new_page(width=595, height=842)
        if table:
            for x in (64, 160, 450):
                page.draw_line((x, 40), (x, 100), width=0.8)
            for y in (40, 70, 100):
                page.draw_line((64, y), (450, y), width=0.8)
            page.insert_text((68, 60), "A", fontsize=10)
            page.insert_text((164, 60), "B", fontsize=10)
            page.insert_text((68, 90), "C", fontsize=10)
            page.insert_text((164, 90), "D", fontsize=10)
        else:
            page.insert_text((64, 60), "Plain body text, no table here.", fontsize=10)
    pdf.save(str(path))
    pdf.close()


def test_one_open_per_file_across_pages(tmp_path, monkeypatch):
    path = tmp_path / "doc.pdf"
    _pdf(path, pages=3, table=True)
    opens = []
    real_open = pdfplumber.open
    monkeypatch.setattr(
        pdfplumber, "open", lambda p, *a, **k: opens.append(p) or real_open(p, *a, **k)
    )
    for n in (1, 2, 3, 1):
        assert len(figures_lib.page_tables(path, n)) == 1
    assert len(opens) == 1


def test_rewritten_file_is_read_again(tmp_path):
    path = tmp_path / "doc.pdf"
    _pdf(path, pages=1, table=True)
    assert len(figures_lib.page_tables(path, 1)) == 1
    _pdf(path, pages=2, table=False)
    assert figures_lib.page_tables(path, 1) == []
