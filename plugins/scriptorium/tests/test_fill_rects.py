"""Fill-only rects that draw no table edge (white label backgrounds,
text highlights) do not make or split tables."""

import itertools

import fitz  # PyMuPDF
from conftest import load_script

W, H = 595.0, 842.0
TX, TY = (100.0, 250.0, 400.0, 500.0), (300.0, 330.0, 370.0, 400.0)

figures = load_script("../lib/figures.py", "figures_fill_rects")


def _raw_rect(x0, y0, x1, y1, op) -> str:
    """A PDF `re` operator in top-left page coordinates (Shape.draw_rect
    writes a curve path, which pdfplumber reads differently)."""
    return f"{x0} {H - y1} {x1 - x0} {y1 - y0} re {op}\n"


def _append_ops(pdf, page, ops: str) -> None:
    xref = page.get_contents()[-1]
    pdf.update_stream(xref, pdf.xref_stream(xref) + ops.encode())


def _state_diagram_page(path) -> None:
    """A vector state diagram: an outer frame with a name tab, two rounded
    state boxes, axis-aligned arrows, and transition labels each printed
    over a white fill-only rect (three stacked rects per label). Every
    stroke is its own path. Caption below."""
    pdf = fitz.open()
    page = pdf.new_page(width=W, height=H)
    shape = page.new_shape()
    strokes = [
        ((48.7, 160.9), (48.7, 343.8)), ((48.7, 343.8), (348.6, 343.8)), ((348.6, 160.9), (348.6, 343.8)),
        ((48.7, 160.9), (348.6, 160.9)), ((48.7, 172.8), (127.4, 172.8)), ((127.4, 172.8), (135.6, 164.0)),
        ((135.6, 160.9), (135.6, 164.0)),  # frame + name tab
        ((157.0, 218.0), (157.0, 280.0)), ((180.0, 218.0), (180.0, 280.0)),  # arrows
    ]
    for a, b in strokes:
        shape.draw_line(a, b)
        shape.finish(color=(0, 0, 0), width=0.12)
    for box in (fitz.Rect(120.6, 181.0, 194.9, 217.9), fitz.Rect(120.6, 280.0, 194.9, 316.9)):
        shape.draw_rect(box, radius=0.2)
        shape.finish(color=(0, 0, 0), fill=(0.98, 0.94, 0.88), width=0.6)
    shape.commit()
    labels = [(52.0, 162.8), (64.0, 242.0), (64.0, 250.6), (64.0, 259.2), (213.0, 249.0), (213.0, 257.6), (213.0, 266.2)]
    page.insert_text((54, 169), "Frame tab", fontsize=6, fontname="hebo")  # creates the content stream
    _append_ops(pdf, page, "q 1 1 1 rg\n" + "".join(_raw_rect(x, y, x + 75, y + 7.6, "f") for x, y in labels) + "Q\n")
    page.insert_text((140, 200), "State A", fontsize=7)
    page.insert_text((140, 300), "State B", fontsize=7)
    for x, y in ((65, 248), (65, 256.6), (65, 265.2), (214, 255), (214, 263.6), (214, 272.2)):
        page.insert_text((x, y), "labelText", fontsize=6)
    page.insert_text((46, 360), "Figure 1: Synthetic state diagram caption.", fontsize=10)
    page.insert_text((46, 400), "Body text after the figure.", fontsize=10)
    pdf.save(str(path))
    pdf.close()


def test_white_label_backgrounds_make_no_table(tmp_path):
    pdf_path = tmp_path / "diagram.pdf"
    _state_diagram_page(pdf_path)
    assert figures.page_tables(pdf_path, 1) == []


def _ruled_table_page(path, fills: list[tuple]) -> None:
    """A 3x3 table ruled by thin filled rects (as word processors draw
    them), with the fill-only rects `fills` (x0, y0, x1, y1) behind its
    text. Cell (1, 0) holds two lines."""
    pdf = fitz.open()
    page = pdf.new_page(width=W, height=H)
    page.insert_text((100, 200), "Body text above the table.", fontsize=10)
    ops = ["q 1 1 0 rg\n"] + [_raw_rect(*f, "f") for f in fills] + ["0 0 0 rg\n"]
    ops += [_raw_rect(x - 0.25, TY[0], x + 0.25, TY[-1], "f") for x in TX]
    ops += [_raw_rect(TX[0], y - 0.25, TX[-1], y + 0.25, "f") for y in TY]
    _append_ops(pdf, page, "".join(ops) + "Q\n")
    for r, (y0, _y1) in enumerate(itertools.pairwise(TY)):
        for c, x0 in enumerate(TX[:-1]):
            if (r, c) == (1, 0):
                page.insert_text((x0 + 3, y0 + 14), "first line", fontsize=9)
                page.insert_text((x0 + 3, y0 + 28), "second line", fontsize=9)
            else:
                page.insert_text((x0 + 3, y0 + 14), f"cell {r}{c}", fontsize=9)
    page.insert_text((100, 450), "Body text after the table.", fontsize=10)
    pdf.save(str(path))
    pdf.close()


def test_highlight_rects_do_not_split_table_cells(tmp_path):
    pdf_path = tmp_path / "highlight.pdf"
    highlights = [(102, 333, 160, 346), (102, 347, 170, 360), (252, 302, 320, 328)]
    _ruled_table_page(pdf_path, highlights)
    tables = figures.page_tables(pdf_path, 1)
    assert len(tables) == 1, tables
    rows = tables[0]["rows"]
    assert len(rows) == 3 and len(rows[0]) == 3, rows
    assert rows[1][0] == "first line\nsecond line", rows


def test_cell_aligned_shading_keeps_table_shape(tmp_path):
    pdf_path = tmp_path / "shaded.pdf"
    _ruled_table_page(pdf_path, [(TX[0], TY[0], TX[-1], TY[1]), (TX[1], TY[1], TX[2], TY[2])])
    tables = figures.page_tables(pdf_path, 1)
    assert [(len(t["rows"]), len(t["rows"][0])) for t in tables] == [(3, 3)], tables


def test_table_drawn_only_by_shading_is_still_found(tmp_path):
    """No rules at all: every fill is off any rule, so the filtered page has
    no table and the unfiltered one is used."""
    pdf = fitz.open()
    page = pdf.new_page(width=W, height=H)
    page.insert_text((100, 200), "Body text above the table.", fontsize=10)
    fills = [(x0, y0, x1, y1) for y0, y1 in itertools.pairwise(TY) for x0, x1 in itertools.pairwise(TX)]
    ops = "".join(f"q {0.7 + 0.1 * (i % 2)} g\n" + _raw_rect(*f, "f") + "Q\n" for i, f in enumerate(fills))
    _append_ops(pdf, page, ops)
    for y0, _y1 in itertools.pairwise(TY):
        for x0 in TX[:-1]:
            page.insert_text((x0 + 3, y0 + 14), "value", fontsize=9)
    pdf.save(str(tmp_path / "zebra.pdf"))
    pdf.close()
    tables = figures.page_tables(tmp_path / "zebra.pdf", 1)
    assert [(len(t["rows"]), len(t["rows"][0])) for t in tables] == [(3, 3)], tables
