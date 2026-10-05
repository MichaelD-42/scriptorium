"""Follow-up R27: label/value rows inside a block are their own paragraphs.

A requirement header is often printed as two-column rows -- "HWC
requirement | REQ 12345678-58 v1", then "ASIL Value: | To Be / Selected" --
followed by the body text, all in one PyMuPDF block. It used to become one
paragraph, so a downstream tagger could not tell where the label's value
ends. `split_row_groups` now splits such a block: each row (two or more
lines at one y) starts a group, a line indented to the value column
continues it, and the next line back at the block's left edge starts the
body.
"""

import json

import fitz  # PyMuPDF
import paths
from conftest import load_script, run_script

extract_text = load_script("extract-text/scripts/extract_text.py", "extract_text_r27")

W, H = 595.0, 842.0


def _line(x0, y0, x1, text):
    return {
        "text": text,
        "bbox": [x0, y0, x1, y0 + 11],
        "max_size": 10.0,
        "bold": False,
        "masked": text,
    }


class TestSplitRowGroups:
    def test_header_rows_and_body(self):
        lines = [
            _line(46, 223, 131, "HWC requirement"),
            _line(151, 223, 248, "REQ 12345678-58 v1"),
            _line(46, 234, 98, "ASIL Value:"),
            _line(109, 234, 135, "To Be"),
            _line(109, 246, 148, "Selected"),
            _line(
                46, 257, 520, "This component shall work in the supply voltage range of"
            ),
            _line(46, 268, 300, "code letter B."),
        ]
        groups = extract_text.split_row_groups(lines)
        assert [" ".join(line["text"] for line in g) for g in groups] == [
            "HWC requirement REQ 12345678-58 v1",
            "ASIL Value: To Be Selected",
            "This component shall work in the supply voltage range of code letter B.",
        ]

    def test_plain_paragraph_is_one_group(self):
        lines = [
            _line(46, 100, 520, "One long line of body text that wraps"),
            _line(46, 111, 300, "onto a second line."),
        ]
        assert extract_text.split_row_groups(lines) == [lines]


def test_extracted_paragraphs(tmp_project):
    doc = "row_groups"
    pdf = fitz.open()
    page = pdf.new_page(width=W, height=H)
    writer = fitz.TextWriter(page.rect)
    for x, y, text in [
        (46, 232, "HWC requirement"),
        (151, 232, "REQ 12345678-58 v1"),
        (46, 243, "ASIL Value:"),
        (109, 243, "To Be"),
        (109, 254, "Selected"),
        (46, 265, "This component shall work in the supply voltage range of"),
        (46, 276, "code letter B."),
    ]:
        writer.append((x, y), text, fontsize=10)
    writer.write_text(page)
    pdf.save(str(tmp_project / "input" / f"{doc}.pdf"))
    pdf.close()
    for args in (
        ("pdf-triage/scripts/triage.py", "--doc", doc),
        ("extract-text/scripts/extract_text.py", "--doc", doc, "--pages", "1"),
    ):
        result = run_script(*args, cwd=tmp_project)
        assert result.returncode == 0, f"{args[0]}: {result.stderr}"
    elements = json.loads(paths.shard_path(doc, 1, "text").read_text(encoding="utf-8"))[
        "elements"
    ]
    assert [e["text"] for e in elements if e["type"] == "paragraph"] == [
        "HWC requirement REQ 12345678-58 v1",
        "ASIL Value: To Be Selected",
        "This component shall work in the supply voltage range of code letter B.",
    ]


def test_rows_before_a_bullet_list_are_split():
    def line(x0, y0, x1, text):
        return {"text": text, "bbox": [x0, y0, x1, y0 + 11], "max_size": 10.0, "bold": False, "masked": text}

    lines = [
        line(46, 403, 131, "HWC requirement"), line(151, 402, 248, "REQ 12345678-34 v1"),
        line(46, 414, 98, "ASIL Value:"), line(109, 414, 126, "QM"),
        line(46, 426, 101, "Information"),
        line(46, 448, 442, "• When a material has been heated so that flames are generated."),
    ]
    elements = extract_text.parse_block_list_items(lines, [46.0])
    assert [e["text"] for e in elements if e["type"] == "paragraph"] == [
        "HWC requirement REQ 12345678-34 v1",
        "ASIL Value: QM",
        "Information",
    ]
    assert elements[-1]["type"] == "list_item"
