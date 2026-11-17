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


def _pdf(path, lines_above: int = 0) -> None:
    pdf = fitz.open()
    page = pdf.new_page(width=W, height=H)
    if not lines_above:
        page.insert_text((46, 100), "The following pin description shall be used.", fontsize=10)
    xs, ys = (44, 160, 300), (130, 142, 154, 166)
    for x in xs:
        page.draw_line((x, ys[0]), (x, ys[-1]), width=0.8)
    for y in ys:
        page.draw_line((xs[0], y), (xs[-1], y), width=0.8)
    # One text object for the caption and every cell, so PyMuPDF reads the
    # caption and the table text as one block (the real document's shape).
    writer = fitz.TextWriter(page.rect)
    for i in range(lines_above):
        writer.append((46, 128 - 12 * (lines_above - i)), f"Body line number {i} above the table.", fontsize=10)
    writer.append((46, 128), "Synthetic actuator pin table", fontsize=10)
    rows = (("Pin Name", "Function"), ("SUPPLY_01", "Supply 12V"), ("GND_01", "Ground"))
    for (left, right), y in zip(rows, ys[1:]):
        writer.append((46, y - 3), left, fontsize=10)
        writer.append((164, y - 3), right, fontsize=10)
    writer.write_text(page)
    page.insert_text((46, 200), "Body text after the table.", fontsize=10)
    pdf.save(str(path))
    pdf.close()


def _extract(tmp_project, doc: str) -> list[dict]:
    for args in (
        ("pdf-triage/scripts/triage.py", "--doc", doc),
        ("extract-text/scripts/extract_text.py", "--doc", doc, "--pages", "1"),
    ):
        result = run_script(*args, cwd=tmp_project)
        assert result.returncode == 0, f"{args[0]}: {result.stderr}"
    return json.loads(paths.shard_path(doc, 1, "text").read_text(encoding="utf-8"))["elements"]


def test_caption_line_in_a_table_block_is_kept(tmp_project):
    doc = "table_block"
    _pdf(tmp_project / "input" / f"{doc}.pdf")
    elements = _extract(tmp_project, doc)
    texts = [e.get("text", "") for e in elements if e["type"] != "table"]
    assert "Synthetic actuator pin table" in texts
    assert not any("SUPPLY_01" in t or "Pin Name" in t for t in texts)
    tables = [e for e in elements if e["type"] == "table"]
    assert len(tables) == 1
    assert tables[0]["rows"][0] == ["Pin Name", "Function"]


def test_table_lines_in_a_block_mostly_outside_the_table_are_dropped(tmp_project):
    """The block holds more body lines than table lines, so it overlaps the
    table by far less than half; its table lines still go."""
    doc = "tall_block"
    _pdf(tmp_project / "input" / f"{doc}.pdf", lines_above=6)
    elements = _extract(tmp_project, doc)
    texts = " ".join(e.get("text", "") for e in elements if e["type"] != "table")
    assert "Body line number 0" in texts and "Synthetic actuator pin table" in texts
    assert "SUPPLY_01" not in texts and "Pin Name" not in texts, texts


def test_line_in_an_open_table_cell_is_kept(tmp_project):
    """Column 1's second cell has a left and an inner rule but no bottom
    rule, so pdfplumber makes no cell for it. Its line is in the table bbox
    and must not be lost."""
    doc = "open_cell"
    pdf = fitz.open()
    page = pdf.new_page(width=W, height=H)
    page.insert_text((46, 100), "Body text above the table.", fontsize=10)
    xs, ys = (44, 160, 300, 420), (130, 150, 170, 190)
    page.draw_line((44, 130), (44, 170), width=0.8)
    for x in xs[1:]:
        page.draw_line((x, ys[0]), (x, ys[-1]), width=0.8)
    for y in ys[:2]:
        page.draw_line((xs[0], y), (xs[-1], y), width=0.8)
    for y in ys[2:]:
        page.draw_line((xs[1], y), (xs[-1], y), width=0.8)
    for x, text in ((46, "Name"), (164, "Value"), (304, "Unit")):
        page.insert_text((x, 145), text, fontsize=10)
    page.insert_text((46, 163), "Openrowlabel", fontsize=10)
    for y in (165, 185):
        page.insert_text((164, y), f"value{y}", fontsize=10)
        page.insert_text((304, y), f"unit{y}", fontsize=10)
    page.insert_text((46, 240), "Body text after the table.", fontsize=10)
    pdf.save(str(tmp_project / "input" / f"{doc}.pdf"))
    pdf.close()
    elements = _extract(tmp_project, doc)
    out = " ".join(
        [e.get("text", "") for e in elements] + [str(c) for e in elements for row in e.get("rows", []) for c in row]
    )
    assert "Openrowlabel" in out, elements
    assert out.count("value165") == 1, elements
