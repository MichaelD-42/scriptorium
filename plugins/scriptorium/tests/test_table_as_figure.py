"""Re-review 2 I1: a table becomes a grid_table (a figure) only with real
chart evidence.

Before, a ruled table with more than 60% empty cells (40% with one curve in
the cluster) became a vector image. A sparse requirements matrix with a few
"X" marks lost its structure without a warning. Now `figures.is_grid_table`
asks for one of:

- (a) a data series: a drawing in the cluster with segments that are not on
  the table's cell boundaries (within FRAME_MATCH_TOLERANCE) and that do not
  stay inside one cell (a check mark drawn as a curve is inside one cell);
- (b) at most GRID_TABLE_MAX_FILLED_FRACTION (10%) of the table's cells
  hold text.

Positions that pdfplumber reports as covered by a spanned (merged) cell are
not cells, so they never count as empty. gates.py adds a `table_as_figure`
warning when a grid_table exclusion had filled cells, or when an image
claims a "Table n" caption.
"""

import json

import figures as figures_lib
import fitz  # PyMuPDF
import paths
from conftest import load_script, run_script

gates = load_script("grade-output/scripts/gates.py", "gates_table_as_figure")

W, H = 595.0, 842.0
MX0, MY0, MRH, VARIANTS, MROWS = 60.0, 160.0, 22.0, 8, 8
MWIDTHS = [50, 170] + [36] * VARIANTS


def _matrix_xs() -> list[float]:
    xs = [MX0]
    for w in MWIDTHS:
        xs.append(xs[-1] + w)
    return xs


def _matrix(page, marks: set[tuple[int, int]]) -> None:
    """A ruled variant matrix: ID, requirement text and 8 variant columns,
    8 rows; an "X" in each (row, variant) of `marks`."""
    xs = _matrix_xs()
    page.insert_text((72, 100), "4.2 Variant applicability", fontsize=12)
    for r in range(MROWS + 1):
        page.draw_line((xs[0], MY0 + r * MRH), (xs[-1], MY0 + r * MRH), width=0.5)
    for x in xs:
        page.draw_line((x, MY0), (x, MY0 + MROWS * MRH), width=0.5)
    header = ["ID", "Requirement"] + [f"V{i + 1}" for i in range(VARIANTS)]
    for c, h in enumerate(header):
        page.insert_text((xs[c] + 3, MY0 + 15), h, fontsize=8)
    for r in range(1, MROWS):
        page.insert_text((xs[0] + 3, MY0 + r * MRH + 15), f"REQ-{r:03d}", fontsize=7)
        page.insert_text(
            (xs[1] + 3, MY0 + r * MRH + 15), f"Synthetic requirement {r}", fontsize=7
        )
        for c in range(VARIANTS):
            if (r, c) in marks:
                page.insert_text((xs[2 + c] + 14, MY0 + r * MRH + 15), "X", fontsize=8)
    page.insert_text(
        (72, MY0 + MROWS * MRH + 20), "Table 7: Variant matrix", fontsize=10
    )


SIX_MARKS = {(1, 0), (2, 1), (3, 2), (4, 0), (5, 4), (6, 5)}


def _six_marks(page) -> None:
    _matrix(page, SIX_MARKS)


def _marks_and_curved_check(page) -> None:
    marks = sorted(
        (r, c) for r in range(1, MROWS) for c in range(VARIANTS) if (r + c) % 2 == 0
    )[:20]
    _matrix(page, set(marks))
    # One check mark drawn as a Bezier curve inside the last cell.
    x, y = _matrix_xs()[-2] + 10, MY0 + MRH * 7 + 6
    shape = page.new_shape()
    shape.draw_bezier((x, y + 6), (x + 3, y + 12), (x + 6, y + 4), (x + 14, y))
    shape.finish(width=0.8)
    shape.commit()


GX0, GY0, COLS, ROWS, STEP = 100.0, 200.0, 6, 5, 50.0


def _labelled_line_chart(page) -> None:
    """A line chart on a 6x5 grid, with a value label in 6 of its 30 cells
    (20% filled): only the data series (rule a) makes it a chart."""
    for r in range(ROWS + 1):
        page.draw_line(
            (GX0, GY0 + r * STEP), (GX0 + COLS * STEP, GY0 + r * STEP), width=0.5
        )
    for c in range(COLS + 1):
        page.draw_line(
            (GX0 + c * STEP, GY0), (GX0 + c * STEP, GY0 + ROWS * STEP), width=0.5
        )
    points = [
        (GX0 + c * STEP, GY0 + ROWS * STEP - (20 + 35 * (c % 3)) - 10 * c)
        for c in range(COLS + 1)
    ]
    shape = page.new_shape()
    shape.draw_polyline(points)
    shape.finish(width=1.5, closePath=False)
    shape.commit()
    for c in range(COLS):
        page.insert_text((GX0 + c * STEP + 4, GY0 + 14), f"{10 * c}", fontsize=8)
    page.insert_text(
        (GX0, GY0 + ROWS * STEP + 30), "Fig. 4: Labelled trend", fontsize=10
    )


def _run(tmp_project, doc: str, draw) -> tuple[dict, dict, dict]:
    pdf = fitz.open()
    draw(pdf.new_page(width=W, height=H))
    pdf.save(str(tmp_project / "input" / f"{doc}.pdf"))
    pdf.close()
    for args in (
        ("pdf-triage/scripts/triage.py", "--doc", doc),
        ("extract-text/scripts/extract_text.py", "--doc", doc, "--pages", "1"),
        ("extract-images/scripts/extract_images.py", "--doc", doc, "--pages", "1"),
        ("assemble-output/scripts/merge.py", "--doc", doc),
        ("assemble-output/scripts/assemble.py", "--doc", doc, "--format", "md"),
    ):
        result = run_script(*args, cwd=tmp_project)
        assert result.returncode == 0, f"{args[0]}: {result.stderr}"
    report = run_script(
        "grade-output/scripts/gates.py", "--doc", doc, "--format", "md", cwd=tmp_project
    )
    text = json.loads(paths.shard_path(doc, 1, "text").read_text())
    image = json.loads(paths.shard_path(doc, 1, "image").read_text())
    return text, image, json.loads(report.stdout)


def _tables(shard: dict) -> list[dict]:
    return [e for e in shard["elements"] if e["type"] == "table"]


def _images(shard: dict) -> list[dict]:
    return [e for e in shard["elements"] if e["type"] == "image"]


class TestSparseMatrixStaysATable:
    def test_constant(self):
        assert figures_lib.GRID_TABLE_MAX_FILLED_FRACTION == 0.10

    def test_matrix_with_six_marks_is_a_table(self, tmp_project):
        text, image, report = _run(tmp_project, "matrix6", _six_marks)
        tables = _tables(text)
        assert len(tables) == 1
        assert len(tables[0]["rows"]) == MROWS and len(tables[0]["rows"][0]) == len(
            MWIDTHS
        )
        assert _images(image) == []
        assert "grid_table" not in [r["reason"] for r in image["excluded_regions"]]
        assert not [w for w in report["warnings"] if w["name"] == "table_as_figure"]

    def test_matrix_with_a_curved_check_mark_is_a_table(self, tmp_project):
        text, image, _report = _run(
            tmp_project, "matrix_curve", _marks_and_curved_check
        )
        assert len(_tables(text)) == 1
        assert _images(image) == []
        assert "grid_table" not in [r["reason"] for r in image["excluded_regions"]]


class TestChartOnAGrid:
    def test_line_chart_with_labels_in_cells_is_a_figure(self, tmp_project):
        text, image, report = _run(tmp_project, "labelled_chart", _labelled_line_chart)
        images = _images(image)
        assert len(images) == 1 and images[0]["kind"] == "vector"
        assert images[0]["caption"] == "Fig. 4: Labelled trend"
        assert _tables(text) == []
        grid = [r for r in image["excluded_regions"] if r["reason"] == "grid_table"]
        assert len(grid) == 1 and grid[0]["filled_cells"] == COLS
        # The grid table had filled cells, so the warning fires and reaches
        # the gates report.
        warnings = [w for w in report["warnings"] if w["name"] == "table_as_figure"]
        assert [w["page"] for w in warnings] == [1]


class TestSpannedCells:
    def test_spanned_positions_are_not_cells(self, tmp_project):
        """A 4-column table whose section rows span all columns: the
        spanned positions do not count, so every real cell is filled."""
        pdf_path = tmp_project / "input" / "spans.pdf"
        pdf = fitz.open()
        page = pdf.new_page(width=W, height=H)
        xs, y0, rh, rows, span_rows = [60, 130, 330, 420, 520], 160.0, 22.0, 6, {1, 4}
        for r in range(rows + 1):
            page.draw_line((xs[0], y0 + r * rh), (xs[-1], y0 + r * rh), width=0.5)
        for r in range(rows):
            for i, x in enumerate(xs):
                if r in span_rows and 0 < i < len(xs) - 1:
                    continue
                page.draw_line((x, y0 + r * rh), (x, y0 + (r + 1) * rh), width=0.5)
        for r in range(rows):
            if r in span_rows:
                page.insert_text(
                    (xs[0] + 3, y0 + r * rh + 15), f"Section {r}", fontsize=8
                )
            else:
                for c in range(4):
                    page.insert_text(
                        (xs[c] + 3, y0 + r * rh + 15), f"v{r}{c}", fontsize=7
                    )
        pdf.save(str(pdf_path))
        pdf.close()
        tables = figures_lib.page_tables(pdf_path, 1)
        assert len(tables) == 1
        assert tables[0]["filled_fraction"] == 1.0
        assert tables[0]["filled_cells"] == 4 * (rows - len(span_rows)) + len(span_rows)


def _doc_data(page: dict) -> dict:
    return {"doc": "sample", "pages": {1: {"page_number": 1, **page}}}


class TestTableAsFigureWarning:
    def test_fires_for_a_grid_table_with_filled_cells(self):
        doc_data = _doc_data(
            {
                "elements": [],
                "excluded_regions": [
                    {"bbox": [0, 0, 10, 10], "reason": "grid_table", "filled_cells": 3}
                ],
            }
        )
        warnings = gates.check_table_as_figure(doc_data)
        assert [(w["name"], w["page"]) for w in warnings] == [("table_as_figure", 1)]

    def test_silent_for_an_empty_grid_table(self):
        doc_data = _doc_data(
            {
                "elements": [],
                "excluded_regions": [
                    {"bbox": [0, 0, 10, 10], "reason": "grid_table", "filled_cells": 0}
                ],
            }
        )
        assert gates.check_table_as_figure(doc_data) == []

    def test_fires_for_an_image_with_a_table_caption(self):
        doc_data = _doc_data(
            {"elements": [{"type": "image", "caption": "Table 3: Limits"}]}
        )
        warnings = gates.check_table_as_figure(doc_data)
        assert len(warnings) == 1 and warnings[0]["caption"] == "Table 3: Limits"

    def test_silent_for_an_image_with_a_figure_caption(self):
        doc_data = _doc_data(
            {"elements": [{"type": "image", "caption": "Figure 3: Diagram"}]}
        )
        assert gates.check_table_as_figure(doc_data) == []
