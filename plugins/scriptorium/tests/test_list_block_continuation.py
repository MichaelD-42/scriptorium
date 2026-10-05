"""Follow-up R25: a block that starts with the previous item's last line.

PyMuPDF can group the last wrapped line of a bullet item ("OK, if enough
space on label", indented under the item's text) with the NEXT bullet item
into one block. Such a block used to become one paragraph mixing both
items. `parse_block_list_items` now also reads a block whose bullet-glyph
marker comes after one or more leading lines: the leading lines are a
paragraph, and `merge_list_and_paragraph_blocks` appends them to the open
list item when they sit right of that item's marker.
"""

import json

import fitz  # PyMuPDF
import paths
from conftest import run_script

W, H = 595.0, 842.0


def _pdf(path) -> None:
    pdf = fitz.open()
    page = pdf.new_page(width=W, height=H)
    page.insert_text((82, 60), "Marking shall contain:", fontsize=10)
    writer = fitz.TextWriter(page.rect)
    lines = [
        (89, 80, "·"),
        (107, 80, "Part number."),
        (89, 98, "·"),
        (107, 98, "Brand logotype (durable marking required) use the tool to"),
        (107, 109, "choose the right brand distinction."),
        (159, 120, "OK, if enough space on label"),
        (89, 131, "·"),
        (107, 131, "Recycling marking according to STD 1."),
        (89, 149, "·"),
        (107, 149, "Recycling marking according to STD 2."),
    ]
    for x, y, text in lines:
        writer.append((x, y), text, fontsize=10)
    writer.write_text(page)
    pdf.save(str(path))
    pdf.close()


def test_leading_line_joins_the_previous_item(tmp_project):
    doc = "list_continuation"
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
    items = [e["text"] for e in elements if e["type"] == "list_item"]
    assert items[-2:] == [
        "Recycling marking according to STD 1.",
        "Recycling marking according to STD 2.",
    ]
    assert any(
        t.endswith("OK, if enough space on label") and t.startswith("Brand logotype")
        for t in items
    ), items
    paragraphs = [e["text"] for e in elements if e["type"] == "paragraph"]
    assert not any("OK, if enough space" in t for t in paragraphs), paragraphs


def test_wrapped_line_starting_with_a_dash_is_not_an_item():
    from conftest import load_script

    extract_text = load_script("extract-text/scripts/extract_text.py", "extract_text_r25")

    def line(x, y, text):
        return {"text": text, "bbox": [x, y, x + 200, y + 11], "max_size": 10.0, "bold": False, "masked": text}

    lines = [
        line(82, 532, "Additional marking to be defined following STD 103-0013"),
        line(82, 543, "– PT)"),
    ]
    assert extract_text.parse_block_list_items(lines, [82.0]) is None
