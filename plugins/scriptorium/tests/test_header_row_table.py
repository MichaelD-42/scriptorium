"""A ruled header row over unruled data rows is one table: the rows
below join it, and no line of it comes back as a paragraph."""

import itertools
import json

import fitz  # PyMuPDF
import paths
from conftest import load_script, run_script

W, H = 595.0, 842.0
XS = (46.2, 146.2, 262.0, 448.8, 470.2, 554.5)

figures = load_script("../lib/figures.py", "figures_header_row")


def _header_row_page(path, data_rows: int = 8, paragraph_below: bool = False) -> None:
    """A ruled 1-row, 5-column header row, then unruled 8 pt data rows whose
    text is right-aligned to the header cells' right edges. One TextWriter
    call, so PyMuPDF puts the header cells and all data rows in one block."""
    pdf = fitz.open()
    page = pdf.new_page(width=W, height=H)
    page.insert_text((46, 100), "Intro paragraph above the table.", fontsize=10)
    top, bottom = 140.0, 151.8
    for x0, x1 in itertools.pairwise(XS):
        page.draw_rect(fitz.Rect(x0, top, x1, bottom), width=0.12)
    font = fitz.Font("helv")
    writer = fitz.TextWriter(page.rect)
    for x0, label in zip(XS, ("Header A:", "Hb", "Hc", "Hd", "He")):
        writer.append((x0 + 1, bottom - 2), label, font=font, fontsize=10)
    for r in range(data_rows):
        y = bottom + 10 + r * 11
        for x1, cell in zip(
            XS[2:],
            (f"Item name {r}", f"Element title number {r}", "(1)", f"ID-{100 + r}"),
        ):
            width = font.text_length(cell, fontsize=8)
            writer.append((x1 - 1 - width, y), cell, font=font, fontsize=8)
    if paragraph_below:
        writer.append(
            (XS[0] + 1, bottom + 12),
            "A sentence of body text that runs across the columns of the row above.",
            font=font, fontsize=10,
        )
    writer.write_text(page)
    page.insert_text((46, 300), "Body text after the table.", fontsize=10)
    pdf.save(str(path))
    pdf.close()


def test_header_only_table_takes_unruled_rows_and_is_not_duplicated(tmp_project):
    doc = "change_note"
    _header_row_page(tmp_project / "input" / f"{doc}.pdf")
    for args in (
        ("pdf-triage/scripts/triage.py", "--doc", doc),
        ("extract-text/scripts/extract_text.py", "--doc", doc, "--pages", "1"),
    ):
        result = run_script(*args, cwd=tmp_project)
        assert result.returncode == 0, f"{args[0]}: {result.stderr}"
    elements = json.loads(paths.shard_path(doc, 1, "text").read_text(encoding="utf-8"))["elements"]
    texts = [e.get("text", "") for e in elements if e["type"] != "table"]
    assert not any("Header A" in t for t in texts), texts
    assert not any("ID-100" in t for t in texts), texts
    assert any("Body text after" in t for t in texts), texts
    tables = [e for e in elements if e["type"] == "table"]
    assert len(tables) == 1, tables
    rows = tables[0]["rows"]
    assert len(rows) == 9 and len(rows[0]) == 5, rows
    assert rows[1][1:] == ["Item name 0", "Element title number 0", "(1)", "ID-100"], rows[1]


def test_header_row_does_not_take_a_paragraph_below_it(tmp_path):
    pdf_path = tmp_path / "row.pdf"
    _header_row_page(pdf_path, data_rows=0, paragraph_below=True)
    tables = figures.page_tables(pdf_path, 1)
    assert [len(t["rows"]) for t in tables] == [1], tables
