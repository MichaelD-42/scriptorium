"""Follow-up R11: a chart drawn on a ruled grid is a figure, not a table.

pdfplumber reads a chart's grid lines as a table, so the chart's drawing
cluster used to be excluded as `table_overlap` and lost. Before that
exclusion, `lib/figures.py` now tests the overlapping table: when more than
`GRID_TABLE_EMPTY_FRACTION` (60%) of its cells are empty, or the cluster has
curves or non-axis-aligned lines and more than
`GRID_TABLE_EMPTY_FRACTION_WITH_CURVES` (40%) are empty, it is a grid table.
The cluster is then a figure, the table is dropped (recorded in
`excluded_regions` as `grid_table`), and extract_text emits no table for
it. A table whose cells are mostly filled stays a table.
"""

import json

import fitz  # PyMuPDF
import paths
from conftest import run_script

W, H = 595.0, 842.0
GX0, GY0, COLS, ROWS, STEP = 100.0, 200.0, 6, 5, 50.0


def _grid(page) -> None:
    for r in range(ROWS + 1):
        y = GY0 + r * STEP
        page.draw_line((GX0, y), (GX0 + COLS * STEP, y), width=0.5)
    for c in range(COLS + 1):
        x = GX0 + c * STEP
        page.draw_line((x, GY0), (x, GY0 + ROWS * STEP), width=0.5)


def _line_chart(page) -> None:
    _grid(page)
    points = [
        (GX0 + c * STEP, GY0 + ROWS * STEP - (20 + 35 * (c % 3)) - 10 * c)
        for c in range(COLS + 1)
    ]
    for a, b in zip(points, points[1:]):
        page.draw_line(a, b, width=1.5)
    page.insert_text(
        (GX0, GY0 + ROWS * STEP + 30), "Fig. 1: Trend over time", fontsize=10
    )


def _step_chart(page) -> None:
    _grid(page)
    y = GY0 + ROWS * STEP - 25
    for c in range(COLS):
        x0, x1 = GX0 + c * STEP, GX0 + (c + 1) * STEP
        page.draw_line((x0, y), (x1, y), width=1.5)
        y_next = y - 30 if c % 2 == 0 else y + 10
        page.draw_line((x1, y), (x1, y_next), width=1.5)
        y = y_next
    page.insert_text(
        (GX0, GY0 + ROWS * STEP + 30), "Fig. 2: Step response", fontsize=10
    )


def _real_table(page) -> None:
    _grid(page)
    for r in range(ROWS):
        for c in range(COLS):
            page.insert_text(
                (GX0 + c * STEP + 5, GY0 + r * STEP + 28), f"v{r}{c}", fontsize=9
            )
    page.insert_text((GX0, GY0 - 12), "Table 1: Values", fontsize=10)


def _run(tmp_project, doc: str, draw) -> tuple[dict, dict, dict]:
    pdf = fitz.open()
    page = pdf.new_page(width=W, height=H)
    page.insert_text((72, 120), "Ordinary body text above the figure.", fontsize=11)
    draw(page)
    page.insert_text((72, 600), "Ordinary body text below the figure.", fontsize=11)
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
    gates = run_script(
        "grade-output/scripts/gates.py", "--doc", doc, "--format", "md", cwd=tmp_project
    )
    text = json.loads(paths.shard_path(doc, 1, "text").read_text())
    image = json.loads(paths.shard_path(doc, 1, "image").read_text())
    return text, image, json.loads(gates.stdout)


def _types(shard: dict) -> list[str]:
    return [e["type"] for e in shard["elements"]]


class TestGridCharts:
    def test_line_chart_on_a_grid_is_one_vector_image(self, tmp_project):
        text, image, report = _run(tmp_project, "line_chart", _line_chart)
        images = [e for e in image["elements"] if e["type"] == "image"]
        assert len(images) == 1 and images[0]["kind"] == "vector"
        assert images[0]["caption"] == "Fig. 1: Trend over time"
        assert "table" not in _types(text)
        assert [r["reason"] for r in image["excluded_regions"]] == ["grid_table"]
        assert not [
            w for w in report["warnings"] if w["name"] == "orphan_figure_caption"
        ]

    def test_step_chart_with_axis_aligned_lines_is_one_vector_image(self, tmp_project):
        text, image, report = _run(tmp_project, "step_chart", _step_chart)
        images = [e for e in image["elements"] if e["type"] == "image"]
        assert len(images) == 1
        assert images[0]["caption"] == "Fig. 2: Step response"
        assert "table" not in _types(text)
        assert not [
            w for w in report["warnings"] if w["name"] == "orphan_figure_caption"
        ]


class TestRealTable:
    def test_ruled_table_with_filled_cells_stays_a_table(self, tmp_project):
        text, image, _report = _run(tmp_project, "real_table", _real_table)
        tables = [e for e in text["elements"] if e["type"] == "table"]
        assert len(tables) == 1 and len(tables[0]["rows"]) == ROWS
        assert [e for e in image["elements"] if e["type"] == "image"] == []
        assert [r["reason"] for r in image["excluded_regions"]] == ["table_overlap"]
