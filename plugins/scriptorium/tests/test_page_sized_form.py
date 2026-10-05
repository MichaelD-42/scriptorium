"""Follow-up R16: a page-sized ruled form is a table, not a chart grid.

R11's grid-table rule turns a cluster into a figure when the overlapping
table has mostly empty cells. A cover page or form drawn as one page-sized
ruled grid with a few filled cells fits that, and became one page-sized
image holding all the page's text. The grid-table rule is now skipped when
the cluster covers more than `GRID_TABLE_MAX_CLUSTER_FRACTION` (60%) of the
page area, or of `content_rect` when one exists: the table stays a table and
the cluster is excluded as `table_overlap`, as before R11.
"""

import json

import figures as figures_lib
import fitz  # PyMuPDF
import paths
from conftest import run_script

W, H = 595.0, 842.0
X0, X1, Y0, ROWS, STEP = 40.0, 555.0, 40.0, 15, 50.0


def _form(page) -> None:
    for r in range(ROWS + 1):
        page.draw_line((X0, Y0 + r * STEP), (X1, Y0 + r * STEP), width=0.8)
    for x in (X0, 200.0, X1):
        page.draw_line((x, Y0), (x, Y0 + ROWS * STEP), width=0.8)
    for r in (0, 4, 9):
        page.insert_text((X0 + 6, Y0 + r * STEP + 28), f"Form label {r}", fontsize=10)


class TestPageSizedForm:
    def test_constant(self):
        assert figures_lib.GRID_TABLE_MAX_CLUSTER_FRACTION == 0.60

    def test_sparse_page_sized_form_stays_a_table(self, tmp_project):
        doc = fitz.open()
        _form(doc.new_page(width=W, height=H))
        doc.save(str(tmp_project / "input" / "form.pdf"))
        doc.close()
        for args in (
            ("pdf-triage/scripts/triage.py", "--doc", "form"),
            ("extract-text/scripts/extract_text.py", "--doc", "form", "--pages", "1"),
            (
                "extract-images/scripts/extract_images.py",
                "--doc",
                "form",
                "--pages",
                "1",
            ),
        ):
            result = run_script(*args, cwd=tmp_project)
            assert result.returncode == 0, f"{args[0]}: {result.stderr}"
        text = json.loads(paths.shard_path("form", 1, "text").read_text())
        image = json.loads(paths.shard_path("form", 1, "image").read_text())
        assert [e["type"] for e in text["elements"]].count("table") == 1
        assert [e for e in image["elements"] if e["type"] == "image"] == []
        assert "table_overlap" in [r["reason"] for r in image["excluded_regions"]]
        assert "grid_table" not in [r["reason"] for r in image["excluded_regions"]]
