"""Follow-up R24: a text line just outside a table is kept.

PyMuPDF can group a caption line printed right above a table ("Actuator pin
table") into one block with the table's header cells. A block that mostly
overlaps a table used to be dropped whole, so the caption line went with
it. The table filter now works per line: only lines inside a table are
dropped, and the rest of the block stays body text.
"""

import json

import fitz  # PyMuPDF
import paths
from conftest import run_script

W, H = 595.0, 842.0


def _pdf(path) -> None:
    pdf = fitz.open()
    page = pdf.new_page(width=W, height=H)
    page.insert_text((46, 100), "The following pin description shall be used.", fontsize=10)
    xs, ys = (44, 160, 300), (130, 142, 154, 166)
    for x in xs:
        page.draw_line((x, ys[0]), (x, ys[-1]), width=0.8)
    for y in ys:
        page.draw_line((xs[0], y), (xs[-1], y), width=0.8)
    # One text object for the caption and every cell, so PyMuPDF reads the
    # caption and the table text as one block (the real document's shape).
    writer = fitz.TextWriter(page.rect)
    writer.append((46, 128), "Synthetic actuator pin table", fontsize=10)
    rows = (("Pin Name", "Function"), ("SUPPLY_01", "Supply 12V"), ("GND_01", "Ground"))
    for (left, right), y in zip(rows, ys[1:]):
        writer.append((46, y - 3), left, fontsize=10)
        writer.append((164, y - 3), right, fontsize=10)
    writer.write_text(page)
    page.insert_text((46, 200), "Body text after the table.", fontsize=10)
    pdf.save(str(path))
    pdf.close()


def test_caption_line_in_a_table_block_is_kept(tmp_project):
    doc = "table_block"
    _pdf(tmp_project / "input" / f"{doc}.pdf")
    for args in (
        ("pdf-triage/scripts/triage.py", "--doc", doc),
        ("extract-text/scripts/extract_text.py", "--doc", doc, "--pages", "1"),
    ):
        result = run_script(*args, cwd=tmp_project)
        assert result.returncode == 0, f"{args[0]}: {result.stderr}"
    elements = json.loads(paths.shard_path(doc, 1, "text").read_text(encoding="utf-8"))[
        "elements"
    ]
    texts = [e.get("text", "") for e in elements if e["type"] != "table"]
    assert "Synthetic actuator pin table" in texts
    assert not any("SUPPLY_01" in t or "Pin Name" in t for t in texts)
    tables = [e for e in elements if e["type"] == "table"]
    assert len(tables) == 1
    assert tables[0]["rows"][0] == ["Pin Name", "Function"]
