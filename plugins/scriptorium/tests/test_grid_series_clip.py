"""Drawings a ruled table overhangs its own cell grid with (a fill past
the table edge, a rule outside it) are no data series."""

import itertools

import fitz  # PyMuPDF
from conftest import load_script

W, H = 595.0, 842.0
FRAME = (42.5, 154.7, 558.1, 813.7)

figures = load_script("../lib/figures.py", "figures_series_clip")


def _raw_rect(x0, y0, x1, y1, op) -> str:
    """A PDF `re` operator in top-left page coordinates (Shape.draw_rect
    writes a curve path, which pdfplumber reads differently)."""
    return f"{x0} {H - y1} {x1 - x0} {y1 - y0} re {op}\n"


def _overhanging_table_page(path) -> None:
    """A plain ruled 16x3 data table, every cell filled, inside the content
    frame. Its right rule (561.5) and the grey header fills sit 3.4 pt
    outside the frame's right edge (558.1)."""
    pdf = fitz.open()
    page = pdf.new_page(width=W, height=H)
    xs, top, row_h = (46.4, 290.9, 430.3, 561.5), 219.5, 13.7
    ys = [top + i * row_h for i in range(17)]
    ops = ["q 1 1 1 rg\n", _raw_rect(*FRAME, "f"), "0.82 0.82 0.82 rg\n"]
    ops += [_raw_rect(x0 + 0.5, ys[0] + 0.5, x1 - 0.3, ys[1] - 0.3, "f") for x0, x1 in itertools.pairwise(xs)]
    ops.append("0 0 0 RG 0.84 w\n")
    ops += [f"{x} {H - ys[0]} m {x} {H - ys[-1]} l S\n" for x in xs]
    ops += [f"{xs[0]} {H - y} m {xs[-1]} {H - y} l S\n" for y in ys]
    ops.append("Q\n")
    page.insert_text((46, 100), "Body text above the table.", fontsize=10)  # creates the content stream
    xref = page.get_contents()[0]
    pdf.update_stream(xref, "".join(ops).encode() + pdf.xref_stream(xref))
    for r, y in enumerate(ys[:-1]):
        for c, x in enumerate(xs[:-1]):
            page.insert_text((x + 2, y + 10), f"r{r}c{c}", fontsize=9)
    pdf.save(str(path))
    pdf.close()


def test_table_overhanging_the_frame_is_not_a_figure(tmp_path):
    pdf_path = tmp_path / "table.pdf"
    _overhanging_table_page(pdf_path)
    tables = figures.page_tables(pdf_path, 1, content_rect=list(FRAME))
    assert [(len(t["rows"]), len(t["rows"][0])) for t in tables] == [(16, 3)], tables
    with fitz.open(pdf_path) as doc:
        regions, excluded = figures.detect_figure_regions_with_exclusions(
            doc[0], 1, pdf_path, frame_drawings=[{"bbox": list(FRAME)}], content_rect=list(FRAME)
        )
    assert regions == [], (regions, excluded)
    assert not any(r["reason"] == "grid_table" for r in excluded)


def test_rules_past_the_reported_table_edge_are_no_data_series():
    """A 2x2 table ruled by thin filled rects. Its right rule sits 3.5 pt
    outside the right edge pdfplumber reports, and the row rules run out
    to it."""
    xs, ys, right = (92.0, 368.1, 499.8), (590.0, 613.7, 636.6), 503.6
    rules = [(x - 0.35, ys[0], x + 0.35, ys[-1]) for x in (*xs[:2], right)]
    rules += [(xs[0] - 0.35, y - 0.35, right + 0.35, y + 0.35) for y in ys]
    pdf = fitz.open()
    page = pdf.new_page(width=W, height=H)
    page.insert_text((100, 100), "Body text.", fontsize=10)  # creates the content stream
    xref = page.get_contents()[0]
    ops = "".join(f"q 0 g {_raw_rect(*r, 'f')}Q\n" for r in rules)
    pdf.update_stream(xref, pdf.xref_stream(xref) + ops.encode())
    drawings = pdf[0].get_drawings()
    pdf.close()
    cells = [[x0, y0, x1, y1] for y0, y1 in itertools.pairwise(ys) for x0, x1 in itertools.pairwise(xs)]
    table = {"bbox": [xs[0], ys[0], xs[-1], ys[-1]], "cells": cells, "filled_fraction": 1.0}
    assert len(drawings) == len(rules)
    assert not figures.is_grid_table(table, drawings)
