"""Follow-up R7: Word's level-2 and level-3 bullets, "o" and "§".

Word's default bullet chain is "·" (Symbol), "o" (Courier New) and "§"
(Wingdings U+00A7, drawn as a square). "o" and "§" are also ordinary text
("o" a letter, "§ 4.2" a section reference), so they are LONE-ONLY markers
(`extract_text.LIST_LONE_BULLET_GLYPHS`): they count only when the glyph is
its own block or its own line, with the item text at a larger x on the same
visual line. As the first token of a text span they are never a marker.
"""

import json
import shutil
from pathlib import Path

import fitz  # PyMuPDF
import paths
import pytest
from conftest import load_script, run_script

extract_text = load_script(
    "extract-text/scripts/extract_text.py", "extract_text_r7_module"
)
assemble = load_script("assemble-output/scripts/assemble.py", "assemble_r7_module")

LONE_GLYPHS = ["o", "§"]


def _line(
    text: str, bbox: list[float], max_size: float = 11.0, bold: bool = False
) -> dict:
    return {
        "text": text,
        "masked": text,
        "bbox": bbox,
        "max_size": max_size,
        "bold": bold,
    }


def _block(bbox: list[float], lines: list[dict]) -> dict:
    return {"bbox": bbox, "lines": lines}


def _merge(blocks: list[dict], levels: list[float]) -> list[dict]:
    return extract_text.merge_list_and_paragraph_blocks(
        [(b, b["lines"]) for b in blocks],
        body_size=11.0,
        toc_lookup={},
        heading_size_ranks={},
        list_level_lookup=levels,
    )


def test_lone_only_glyphs_are_a_named_constant():
    assert set(extract_text.LIST_LONE_BULLET_GLYPHS) == {"o", "§"}
    assert not set(extract_text.LIST_LONE_BULLET_GLYPHS) & set(
        extract_text.LIST_BULLET_GLYPHS
    )


@pytest.mark.parametrize("glyph", LONE_GLYPHS)
class TestLoneBulletShapes:
    def test_lone_glyph_block_gives_a_list_item(self, glyph):
        glyph_block = _block(
            [100.0, 100.0, 108.0, 116.0],
            [_line(glyph, [100.0, 100.0, 108.0, 116.0], max_size=13.0)],
        )
        text_block = _block(
            [118.0, 101.0, 300.0, 115.0],
            [_line("Second level item", [118.0, 101.0, 300.0, 115.0])],
        )
        elements = _merge([glyph_block, text_block], [72.0, 100.0])
        assert len(elements) == 1
        assert elements[0]["type"] == "list_item"
        assert elements[0]["marker"] == glyph
        assert elements[0]["level"] == 2
        assert elements[0]["text"] == "Second level item"

    def test_glyph_line_plus_text_line_in_one_block_gives_a_list_item(self, glyph):
        block = _block(
            [100.0, 100.0, 300.0, 116.0],
            [
                _line(glyph, [100.0, 100.0, 108.0, 116.0], max_size=13.0),
                _line("Second level item", [118.0, 101.0, 300.0, 115.0]),
            ],
        )
        elements = _merge([block], [72.0, 100.0])
        assert len(elements) == 1
        assert elements[0]["type"] == "list_item"
        assert elements[0]["marker"] == glyph
        assert elements[0]["level"] == 2
        assert elements[0]["text"] == "Second level item"

    def test_inline_glyph_and_word_in_one_span_stays_a_paragraph(self, glyph):
        text = f"{glyph} something ordinary in a sentence"
        assert extract_text.parse_list_marker(text) is None
        block = _block(
            [72.0, 100.0, 300.0, 115.0], [_line(text, [72.0, 100.0, 300.0, 115.0])]
        )
        elements = _merge([block], [72.0, 100.0])
        assert [e["type"] for e in elements] == ["paragraph"]
        assert elements[0]["text"] == text

    def test_inline_section_reference_stays_a_paragraph(self, glyph):
        text = f"{glyph} 5.2 applies to every variant."
        block = _block(
            [72.0, 100.0, 300.0, 115.0], [_line(text, [72.0, 100.0, 300.0, 115.0])]
        )
        elements = _merge([block], [72.0, 100.0])
        assert [e["type"] for e in elements] == ["paragraph"]
        assert elements[0]["text"] == text

    def test_glyph_line_on_a_different_visual_line_stays_a_paragraph(self, glyph):
        block = _block(
            [100.0, 100.0, 300.0, 140.0],
            [
                _line(glyph, [100.0, 100.0, 108.0, 116.0]),
                _line("Text far below", [118.0, 125.0, 300.0, 140.0]),
            ],
        )
        assert all(e["type"] == "paragraph" for e in _merge([block], [72.0, 100.0]))


def _build_word_chain_pdf(path: Path) -> None:
    """A 3-level list in Word's bullet chain: each glyph drawn larger than
    its text (13 pt glyph, 11 pt text), the shape that gives a glyph line
    plus a text line in one PyMuPDF block. The "§" is drawn in Courier: a
    13 pt Helvetica "§" starts 3.2 pt above its text line, just outside
    LIST_MARKER_Y_TOLERANCE."""
    doc = fitz.open()
    page = doc.new_page()
    rows = [
        (72.0, "·", "Symbol", "First level item"),
        (100.0, "o", "cour", "Second level item"),
        (128.0, "§", "cour", "Third level item"),
        (100.0, "o", "cour", "Another second level item"),
    ]
    for i, (x, glyph, font, text) in enumerate(rows):
        y = 150 + i * 20
        page.insert_text((x, y), glyph, fontsize=13, fontname=font)
        page.insert_text((x + 18, y + 1), text, fontsize=11, fontname="helv")
    page.insert_text(
        (72, 260),
        "o is a letter, and this line is a paragraph.",
        fontsize=11,
        fontname="helv",
    )
    page.insert_text(
        (72, 280),
        "§ 5.2 is a section reference in a paragraph.",
        fontsize=11,
        fontname="helv",
    )
    doc.save(str(path))
    doc.close()


class TestWordBulletChainEndToEnd:
    def test_levels_markers_and_rendering(self, tmp_path, tmp_project):
        pdf = tmp_path / "word_chain.pdf"
        _build_word_chain_pdf(pdf)
        shutil.copyfile(pdf, tmp_project / "input" / "word_chain.pdf")
        result = run_script(
            "pdf-triage/scripts/triage.py", "--doc", "word_chain", cwd=tmp_project
        )
        assert result.returncode == 0, result.stderr
        triage = json.loads(paths.triage_json("word_chain").read_text())

        doc = fitz.open(str(pdf))
        try:
            clusters = extract_text.document_list_marker_levels(
                doc,
                body_size=triage["body_size"],
                furniture_masked=set(),
                toc_lookup={},
                heading_size_ranks={},
                page_roles={},
            )
        finally:
            doc.close()
        assert len(clusters) == 3

        result = run_script(
            "extract-text/scripts/extract_text.py",
            "--doc",
            "word_chain",
            "--pages",
            "1",
            "--body-size",
            str(triage["body_size"]),
            cwd=tmp_project,
        )
        assert result.returncode == 0, result.stderr
        shard = json.loads(paths.shard_path("word_chain", 1, "text").read_text())
        items = [e for e in shard["elements"] if e["type"] == "list_item"]
        assert [(e["marker"], e["level"], e["text"]) for e in items] == [
            ("·", 1, "First level item"),
            ("o", 2, "Second level item"),
            ("§", 3, "Third level item"),
            ("o", 2, "Another second level item"),
        ]
        paragraphs = [e["text"] for e in shard["elements"] if e["type"] == "paragraph"]
        assert "o is a letter, and this line is a paragraph." in paragraphs
        assert "§ 5.2 is a section reference in a paragraph." in paragraphs

        rendered = [assemble.render_list_item_markdown(e) for e in items]
        assert all(line.lstrip().startswith("- ") for line in rendered), rendered
