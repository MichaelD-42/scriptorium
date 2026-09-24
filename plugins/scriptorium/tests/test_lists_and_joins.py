"""Task A4b -- list items (nested bullets/enumerators, up to 5 indent
levels) and paragraph/list-item joins across a page break.

Three pieces, each with its own test classes below:

1. **List items -- `extract_text.py`.** `parse_list_marker` recognizes a
   bullet-glyph or enumerator token at the start of a line, followed by
   real text on the same line. `build_block_element` uses it (when given a
   `list_level_lookup`) to classify a single block as `list_item` instead
   of `paragraph`, including same-block wrapped continuation lines.
   `merge_list_and_paragraph_blocks` resolves the two CROSS-block cases a
   single block can't see on its own: a bullet glyph drawn as its own
   PyMuPDF block next to its text block on the same line, and a wrapped
   continuation block at the open item's text x-position. Level is derived
   from the marker's x-position, clustered document-wide
   (`cluster_x_positions`/`level_for_x`/`document_list_marker_levels`).
2. **Page-break joins -- `lib/elements.py`'s `merge_shards`
   (`apply_page_break_joins`).** Controller-ruled: detected at merge time
   (which sees every page), not in the extractor. A page's last
   paragraph/list_item with no terminal punctuation joins with the next
   page's first plain paragraph at the same left x -- one element,
   `pages: [n, n+1]`, verbatim concatenation (no de-hyphenation).
3. **Rendering -- `assemble.py`/the HTML template/`reqif_builder.py`.**
   Markdown: `"  " * (level - 1)` + rendered marker (`-` for a glyph,
   verbatim for an enumerator) + text; consecutive items have no blank
   line between them, one blank line before/after the whole list. Same
   rule for md-tree (`elements_to_markdown_with_anchors`, no headings in
   the run so its output is byte-identical to `elements_to_markdown`'s).
   HTML: one shared `<ul>` per run of consecutive `list_item`s, each `<li
   class="level-N">`. ReqIF: the rendered marker+text as a plain paragraph.

Fix round 1 (reviewer Finding 1, Blocking): the real document's actual
marker shape -- a bullet glyph drawn at a LARGER font size than its text,
"on the same line" -- lands as TWO separate `lines` of ONE PyMuPDF
`block`, not one span of one line (the original inline-marker check's
assumption) and not two top-level blocks (the original cross-block
merge's assumption). `_block_marker_start`/`parse_block_list_items`
(`extract_text.py`) recognize this shape at the LINE level within a
single block, including several items end to end in one block (glyph,
text, glyph, text, ...) and wrapped continuation lines with no x check
(they're already grouped in one PyMuPDF block). `document_list_marker_levels`
now collects marker x-positions the same way, so the document-wide level
ranking agrees with what the real per-page pass detects.
"""

import json
import shutil
from pathlib import Path

import fitz  # PyMuPDF
import pytest

import paths
from conftest import load_script, run_script

EXAMPLES_ROOT = Path(__file__).resolve().parent.parent / "examples"

import elements as elements_lib  # noqa: E402  (lib/ already on sys.path via conftest)

extract_text = load_script("extract-text/scripts/extract_text.py", "extract_text_a4b_module")
assemble = load_script("assemble-output/scripts/assemble.py", "assemble_a4b_module")
reqif_builder = load_script("assemble-output/scripts/reqif_builder.py", "reqif_builder_a4b_module")


def _golden() -> dict:
    return json.loads((EXAMPLES_ROOT / "furniture_golden.json").read_text())


def _run_ok(relpath: str, *args: str, cwd) -> str:
    result = run_script(relpath, *args, cwd=cwd)
    assert result.returncode == 0, (
        f"{relpath} {' '.join(args)} failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    return result.stdout


def _run_triage(doc: str, cwd) -> dict:
    _run_ok("pdf-triage/scripts/triage.py", "--doc", doc, cwd=cwd)
    return json.loads(paths.triage_json(doc).read_text())


@pytest.fixture
def furniture_doc(tmp_project):
    dest = tmp_project / "input" / "furniture_sample.pdf"
    shutil.copyfile(EXAMPLES_ROOT / "furniture_sample.pdf", dest)
    return "furniture_sample"


def _line(text: str, bbox: list[float], max_size: float = 11.0, bold: bool = False) -> dict:
    return {"text": text, "masked": text, "bbox": bbox, "max_size": max_size, "bold": bold}


def _block(bbox: list[float], lines: list[dict]) -> dict:
    return {"bbox": bbox, "lines": lines}


# ---------------------------------------------------------------------------
# 1a. parse_list_marker -- pure unit tests
# ---------------------------------------------------------------------------

class TestParseListMarker:
    @pytest.mark.parametrize("glyph", list(extract_text.LIST_BULLET_GLYPHS))
    def test_every_bullet_glyph_recognized(self, glyph):
        assert extract_text.parse_list_marker(f"{glyph} Some text") == (glyph, "Some text")

    def test_private_use_glyph(self):
        # The brief's own worked example: U+F02D, a Symbol-font private-use
        # bullet glyph found on the real (customer) golden document --
        # PyMuPDF/reportlab can't reliably draw this via a base-14 font, so
        # it's only ever exercised as plain Python text here, never rendered.
        assert extract_text.parse_list_marker(" Ingestion step") == ("", "Ingestion step")

    def test_enumerator_digit_paren(self):
        assert extract_text.parse_list_marker("1) First item") == ("1)", "First item")

    def test_enumerator_digit_dot(self):
        assert extract_text.parse_list_marker("1. First item") == ("1.", "First item")

    def test_enumerator_letter_paren(self):
        assert extract_text.parse_list_marker("a) First item") == ("a)", "First item")

    def test_enumerator_paren_digit(self):
        assert extract_text.parse_list_marker("(1) First item") == ("(1)", "First item")

    def test_enumerator_paren_letter(self):
        assert extract_text.parse_list_marker("(a) First item") == ("(a)", "First item")

    def test_enumerator_roman_numeral(self):
        assert extract_text.parse_list_marker("ii) Second item") == ("ii)", "Second item")

    def test_lone_number_with_no_text_after_is_not_a_marker(self):
        assert extract_text.parse_list_marker("10") is None

    def test_lone_glyph_with_no_text_after_is_not_a_marker(self):
        assert extract_text.parse_list_marker("-") is None

    def test_ordinary_word_is_not_a_marker(self):
        assert extract_text.parse_list_marker("The system shall respond within 200ms.") is None

    def test_dotted_multi_level_number_with_no_space_is_not_a_marker(self):
        # "10.1" (no space between the "." and what follows -- a dotted
        # multi-level number like a TOC entry's own number, or a printed
        # split-line TOC number "2.1.1" alone on its own line) is NOT a
        # marker match: every enumerator shape requires whitespace
        # immediately after the marker before any real text.
        assert extract_text.parse_list_marker("10.1") is None
        assert extract_text.parse_list_marker("2.1.1") is None


class TestDocumentListMarkerLevelsSkipsTocPages:
    """A realistic TOC line CAN look like an enumerator marker when its
    number and title ARE separated by whitespace (e.g. "1. Introduction
    .......... 4") -- document_list_marker_levels must not let a TOC page
    seed a spurious marker-x cluster, since main() never emits any elements
    for a TOC-role page in the first place (see load_page_roles/main())."""

    def test_toc_role_page_never_contributes_a_marker_cluster(self, tmp_path):
        document = fitz.open()
        toc_page = document.new_page()
        toc_page.insert_text((200, 150), "1. Not A Real List Item", fontsize=11, fontname="helv")
        body_page = document.new_page()
        body_page.insert_text((72, 150), "- Real bullet item", fontsize=11, fontname="helv")
        out = tmp_path / "toc_skip.pdf"
        document.save(out)
        document.close()

        doc = fitz.open(out)
        clusters = extract_text.document_list_marker_levels(
            doc, body_size=11.0, furniture_masked=set(), toc_lookup={}, heading_size_ranks={},
            page_roles={1: "toc"},
        )
        doc.close()
        # Only the real bullet's x (72.0) seeds a cluster -- the TOC page's
        # "1. ..." line (at x=200) is skipped entirely because page 1 is
        # marked role "toc".
        assert clusters == [72.0]


# ---------------------------------------------------------------------------
# 1b. cluster_x_positions / level_for_x
# ---------------------------------------------------------------------------

class TestClusterAndLevel:
    def test_two_well_separated_positions_rank_ascending(self):
        clusters = extract_text.cluster_x_positions([90.0, 72.0, 72.1])
        assert clusters == [72.0, 90.0]
        assert extract_text.level_for_x(72.0, clusters) == 1
        assert extract_text.level_for_x(90.0, clusters) == 2

    def test_within_tolerance_collapses_to_one_cluster(self):
        clusters = extract_text.cluster_x_positions([72.0, 74.5, 72.9])
        assert clusters == [72.0]

    def test_level_for_x_empty_lookup_defaults_to_one(self):
        assert extract_text.level_for_x(100.0, []) == 1


# ---------------------------------------------------------------------------
# 1c. build_block_element -- single-block marker-as-first-token, including
#     same-block wrapped continuation lines, and the heading-wins ordering.
# ---------------------------------------------------------------------------

class TestBuildBlockElementListItems:
    def test_glyph_marker_as_first_token_of_the_line(self):
        block = _block([72.0, 100.0, 200.0, 115.0], [_line("- Ingestion", [72.0, 100.0, 200.0, 115.0])])
        el = extract_text.build_block_element(block, block["lines"], body_size=11.0, toc_lookup={}, heading_size_ranks={}, list_level_lookup=[72.0])
        assert el == {"type": "list_item", "marker": "-", "level": 1, "text": "Ingestion", "bbox": [72.0, 100.0, 200.0, 115.0]}

    def test_enumerator_marker_verbatim(self):
        block = _block([72.0, 100.0, 250.0, 115.0], [_line("1) Requirement text here", [72.0, 100.0, 250.0, 115.0])])
        el = extract_text.build_block_element(block, block["lines"], body_size=11.0, toc_lookup={}, heading_size_ranks={}, list_level_lookup=[72.0])
        assert el["type"] == "list_item"
        assert el["marker"] == "1)"
        assert el["text"] == "Requirement text here"

    def test_wrapped_continuation_line_in_the_same_block_stays_in_the_item(self):
        block = _block(
            [72.0, 100.0, 300.0, 130.0],
            [
                _line("- First line of the item", [72.0, 100.0, 300.0, 115.0]),
                _line("continues here with no marker", [72.0, 115.0, 300.0, 130.0]),
            ],
        )
        el = extract_text.build_block_element(block, block["lines"], body_size=11.0, toc_lookup={}, heading_size_ranks={}, list_level_lookup=[72.0])
        assert el["type"] == "list_item"
        assert el["marker"] == "-"
        assert el["text"] == "First line of the item continues here with no marker"

    def test_list_level_lookup_none_skips_list_detection_entirely(self):
        # Backward-compat default: build_block_element's pre-A4b callers
        # (test_furniture_removal.py) never pass list_level_lookup.
        block = _block([72.0, 100.0, 200.0, 115.0], [_line("- Ingestion", [72.0, 100.0, 200.0, 115.0])])
        el = extract_text.build_block_element(block, block["lines"], body_size=11.0, toc_lookup={}, heading_size_ranks={})
        assert el["type"] == "paragraph"
        assert el["text"] == "- Ingestion"


class TestListItemNegatives:
    def test_toc_matched_heading_never_becomes_a_list_item(self):
        # A block classified as a heading (bold, large enough to clear the
        # fallback-ranking gate here) whose text also happens to start with
        # an enumerator-shaped prefix must stay a heading -- the heading
        # check runs first and always wins.
        block = _block(
            [72.0, 100.0, 300.0, 125.0],
            [_line("1) Introduction", [72.0, 100.0, 300.0, 125.0], max_size=20.0, bold=True)],
        )
        el = extract_text.build_block_element(
            block, block["lines"], body_size=11.0, toc_lookup={}, heading_size_ranks={20.0: 1}, list_level_lookup=[72.0],
        )
        assert el["type"] == "heading"
        assert el["level"] == 1

    def test_lone_number_with_no_text_after_is_a_paragraph_not_a_list_item(self):
        block = _block([72.0, 100.0, 90.0, 115.0], [_line("10", [72.0, 100.0, 90.0, 115.0])])
        el = extract_text.build_block_element(block, block["lines"], body_size=11.0, toc_lookup={}, heading_size_ranks={}, list_level_lookup=[72.0])
        assert el["type"] == "paragraph"
        assert el["text"] == "10"

    def test_ordinary_paragraph_is_not_a_list_item(self):
        block = _block([72.0, 100.0, 400.0, 115.0], [_line("The system shall respond within 200ms.", [72.0, 100.0, 400.0, 115.0])])
        el = extract_text.build_block_element(block, block["lines"], body_size=11.0, toc_lookup={}, heading_size_ranks={}, list_level_lookup=[72.0])
        assert el["type"] == "paragraph"


# ---------------------------------------------------------------------------
# 1d. merge_list_and_paragraph_blocks -- the glyph-as-separate-block case
# ---------------------------------------------------------------------------

class TestSeparateGlyphBlockMerge:
    def test_glyph_block_plus_adjacent_text_block_becomes_one_list_item(self):
        glyph_block = _block([72.0, 100.0, 84.0, 118.0], [_line("", [72.0, 100.0, 84.0, 118.0], max_size=14.0)])
        text_block = _block([95.0, 101.0, 300.0, 116.0], [_line("Normalize incoming documents", [95.0, 101.0, 300.0, 116.0])])
        blocks_and_lines = [(glyph_block, glyph_block["lines"]), (text_block, text_block["lines"])]

        elements = extract_text.merge_list_and_paragraph_blocks(
            blocks_and_lines, body_size=11.0, toc_lookup={}, heading_size_ranks={}, list_level_lookup=[95.0],
        )
        assert len(elements) == 1
        el = elements[0]
        assert el["type"] == "list_item"
        assert el["marker"] == ""
        assert el["level"] == 1
        assert el["text"] == "Normalize incoming documents"
        # bbox is the union of both blocks
        assert el["bbox"] == [72.0, 100.0, 300.0, 118.0]

    def test_glyph_block_on_a_different_line_does_not_merge(self):
        glyph_block = _block([72.0, 100.0, 84.0, 118.0], [_line("", [72.0, 100.0, 84.0, 118.0], max_size=14.0)])
        text_block = _block([95.0, 300.0, 300.0, 315.0], [_line("Unrelated text elsewhere on the page", [95.0, 300.0, 300.0, 315.0])])
        blocks_and_lines = [(glyph_block, glyph_block["lines"]), (text_block, text_block["lines"])]

        elements = extract_text.merge_list_and_paragraph_blocks(
            blocks_and_lines, body_size=11.0, toc_lookup={}, heading_size_ranks={}, list_level_lookup=[72.0, 95.0],
        )
        # Not merged: the lone glyph becomes its own (marker-less, one
        # character) paragraph, and the unrelated text its own paragraph.
        assert len(elements) == 2
        assert elements[0]["type"] == "paragraph"
        assert elements[0]["text"] == ""
        assert elements[1]["type"] == "paragraph"

    def test_cross_block_wrapped_continuation_absorbed_into_the_open_item(self):
        # Cross-block continuation-absorption only fires for a list item
        # produced by the separate-glyph-block merge (case 1) -- that's the
        # only shape with a real, trustworthy "item text x" (the actual
        # text block's own x0). See merge_list_and_paragraph_blocks'
        # docstring: the inline-marker path deliberately does NOT support
        # this, since its only available x is the marker's x, which
        # coincides with the ordinary body-text left margin on a real
        # document and would risk swallowing unrelated paragraphs.
        glyph_block = _block([72.0, 100.0, 84.0, 118.0], [_line("", [72.0, 100.0, 84.0, 118.0], max_size=14.0)])
        text_block = _block([95.0, 101.0, 300.0, 116.0], [_line("First line", [95.0, 101.0, 300.0, 116.0])])
        continuation_block = _block([95.0, 117.0, 300.0, 132.0], [_line("continuation text with no marker", [95.0, 117.0, 300.0, 132.0])])
        blocks_and_lines = [
            (glyph_block, glyph_block["lines"]),
            (text_block, text_block["lines"]),
            (continuation_block, continuation_block["lines"]),
        ]

        elements = extract_text.merge_list_and_paragraph_blocks(
            blocks_and_lines, body_size=11.0, toc_lookup={}, heading_size_ranks={}, list_level_lookup=[95.0],
        )
        assert len(elements) == 1
        assert elements[0]["type"] == "list_item"
        assert elements[0]["text"] == "First line continuation text with no marker"

    def test_inline_marker_list_item_never_absorbs_a_following_ordinary_paragraph(self):
        # Regression for the false-merge risk above: an inline-marker item
        # ("- ..." as the first token of its own block) at the document's
        # ordinary left margin must NOT swallow a following unrelated
        # paragraph that merely starts at that same margin.
        item_block = _block([72.0, 100.0, 200.0, 115.0], [_line("- Ingestion", [72.0, 100.0, 200.0, 115.0])])
        unrelated_para = _block([72.0, 130.0, 400.0, 145.0], [_line("This is an unrelated new paragraph.", [72.0, 130.0, 400.0, 145.0])])
        blocks_and_lines = [(item_block, item_block["lines"]), (unrelated_para, unrelated_para["lines"])]

        elements = extract_text.merge_list_and_paragraph_blocks(
            blocks_and_lines, body_size=11.0, toc_lookup={}, heading_size_ranks={}, list_level_lookup=[72.0],
        )
        assert len(elements) == 2
        assert elements[0] == {"type": "list_item", "marker": "-", "level": 1, "text": "Ingestion", "bbox": [72.0, 100.0, 200.0, 115.0]}
        assert elements[1]["type"] == "paragraph"
        assert elements[1]["text"] == "This is an unrelated new paragraph."

    def test_next_list_item_does_not_get_absorbed_as_a_continuation(self):
        item1 = _block([72.0, 100.0, 200.0, 115.0], [_line("- First item", [72.0, 100.0, 200.0, 115.0])])
        item2 = _block([72.0, 116.0, 200.0, 131.0], [_line("- Second item", [72.0, 116.0, 200.0, 131.0])])
        blocks_and_lines = [(item1, item1["lines"]), (item2, item2["lines"])]

        elements = extract_text.merge_list_and_paragraph_blocks(
            blocks_and_lines, body_size=11.0, toc_lookup={}, heading_size_ranks={}, list_level_lookup=[72.0],
        )
        assert len(elements) == 2
        assert [e["text"] for e in elements] == ["First item", "Second item"]


# ---------------------------------------------------------------------------
# 1d2. Fix round 1 (reviewer Finding 1, Blocking): the glyph and its text as
#      TWO LINES of ONE block -- the real document's actual shape.
# ---------------------------------------------------------------------------

def _build_glyph_size_jump_pdf(tmp_path: Path, name: str) -> Path:
    """A 2-level nested list, each item's bullet glyph drawn at a LARGER
    font size (13pt Symbol) than its text (11pt Helvetica) on the same
    insertion y -- the brief's own real-document shape ("drawn at a larger
    size than the text ... y differs by about 1 pt"). One level-2 item's
    text is split across two insert_text calls at the same x, simulating a
    wrapped line. Confirmed directly against PyMuPDF's own output (see
    TestGlyphAndTextAsTwoLinesOfOneBlock's own sanity check below) that
    this lands the glyph and its text as two separate `lines` of the SAME
    block -- not two spans of one line, and not two top-level blocks.    The glyph is inserted as U+F02D (a private-use Symbol-font code point,
    matching the brief's own real-document example) -- but PyMuPDF's
    built-in "Symbol" base-14 font round-trips every private-use bullet
    input tried (F02D/F0B7/F0A7/F0D8) back through get_text() as the SAME
    real Unicode character, U+00B7 (middle dot), not the PUA input
    verbatim -- confirmed empirically while building this fixture (a real
    document's own embedded font, with its own ToUnicode CMap, actually
    maps back to PUA on extraction; PyMuPDF's built-in font doesn't). The
    input glyph is still both a valid LIST_BULLET_GLYPHS member and the
    private-use glyph the brief calls out; the PUA-preserving round-trip
    itself is separately and precisely exercised via hand-built block
    dicts in TestParseBlockListItemsSeveralItemsInOneBlock below, which
    doesn't depend on PyMuPDF's font rendering at all."""
    out_path = tmp_path / name
    document = fitz.open()
    page = document.new_page()
    level1_x, level2_x = 72.0, 100.0
    # Content starts at y=150 (well below pdf-triage's top-12% furniture
    # edge band on a letter-size page) -- same precaution test_heading_levels.py
    # documents for its own single-page synthetic fixtures.
    page.insert_text((level1_x, 150), "", fontsize=13, fontname="Symbol")
    page.insert_text((level1_x + 18, 151), "Ingestion", fontsize=11, fontname="helv")
    page.insert_text((level2_x, 170), "", fontsize=13, fontname="Symbol")
    page.insert_text((level2_x + 18, 171), "Normalize incoming documents before parsing and validating markers", fontsize=11, fontname="helv")
    page.insert_text((level2_x + 18, 185), "that wraps onto a second physical line", fontsize=11, fontname="helv")
    page.insert_text((level1_x, 205), "", fontsize=13, fontname="Symbol")
    page.insert_text((level1_x + 18, 206), "Transformation", fontsize=11, fontname="helv")
    page.insert_text((level2_x, 225), "", fontsize=13, fontname="Symbol")
    page.insert_text((level2_x + 18, 226), "Apply extraction rules", fontsize=11, fontname="helv")
    document.save(out_path)
    document.close()
    return out_path


class TestGlyphAndTextAsTwoLinesOfOneBlock:
    """Reproduces the reviewer's exact finding end to end. Must fail
    against the pre-fix-round code (verified via `git stash` on
    `extract_text.py` before committing this fix -- see task-A4b-report.md's
    "Fix round 1" section)."""

    def test_pymupdf_really_does_put_glyph_and_text_on_separate_lines_of_one_block(self, tmp_path):
        # Sanity check pinning the actual PyMuPDF shape this fix targets --
        # confirms the premise rather than assuming it, and fails loudly
        # (not silently) if a future PyMuPDF version segments differently.
        pdf_path = _build_glyph_size_jump_pdf(tmp_path, "glyph_size_jump_sanity.pdf")
        doc = fitz.open(pdf_path)
        page = doc[0]
        text_blocks = [b for b in page.get_text("dict")["blocks"] if b.get("type") == 0]
        doc.close()

        found = False
        for b in text_blocks:
            lines = b["lines"]
            if len(lines) >= 2:
                first_text = "".join(s["text"] for s in lines[0]["spans"]).strip()
                if len(first_text) == 1 and lines[1]["bbox"][0] > lines[0]["bbox"][0]:
                    found = True
                    break
        assert found, "expected at least one block with a lone-glyph line followed by a further-right text line"

    def test_list_items_recovered_end_to_end_with_correct_levels_and_text(self, tmp_path, tmp_project):
        pdf_path = _build_glyph_size_jump_pdf(tmp_path, "glyph_size_jump.pdf")
        shutil.copyfile(pdf_path, tmp_project / "input" / "glyph_size_jump.pdf")

        triage = _run_triage("glyph_size_jump", tmp_project)
        _run_ok(
            "extract-text/scripts/extract_text.py", "--doc", "glyph_size_jump",
            "--pages", "1", "--body-size", str(triage["body_size"]),
            cwd=tmp_project,
        )
        shard = json.loads(paths.shard_path("glyph_size_jump", 1, "text").read_text())
        list_items = [e for e in shard["elements"] if e["type"] == "list_item"]

        assert len(list_items) == 4, f"expected 4 list items, got {shard['elements']}"
        assert [e["text"] for e in list_items] == [
            "Ingestion",
            "Normalize incoming documents before parsing and validating markers that wraps onto a second physical line",
            "Transformation",
            "Apply extraction rules",
        ]
        # Two distinct indent levels: x=72 (level 1) shallower than x=100 (level 2).
        assert [e["level"] for e in list_items] == [1, 2, 1, 2]
        # PyMuPDF's built-in Symbol font round-trips the PUA input glyph
        # to U+00B7 (middle dot) on extraction -- see _build_glyph_size_jump_pdf's
        # own docstring. Still a valid LIST_BULLET_GLYPHS member either way.
        assert list_items[0]["marker"] == "·"
        assert list_items[3]["marker"] == "·"

        # No leftover paragraph mangles the marker onto the front of the
        # text (the bug: a lone-glyph LINE with no text after it on that
        # same line read as "no marker" -- the real text was one line
        # down, not absent -- so the whole block fell through to a
        # paragraph instead).
        paragraph_texts = " ".join(e.get("text", "") for e in shard["elements"] if e["type"] == "paragraph")
        assert "Ingestion" not in paragraph_texts
        assert "Normalize incoming documents" not in paragraph_texts
        assert "Transformation" not in paragraph_texts
        assert "Apply extraction rules" not in paragraph_texts


class TestParseBlockListItemsSeveralItemsInOneBlock:
    """Requirement 2 (several items in one block) + requirement 3 (a
    private-use glyph variant), via hand-built block dicts -- matching this
    repo's own precedent for line shapes PyMuPDF/reportlab can't reliably
    reproduce via a base-14 font on their own (see
    test_furniture_removal.py's TestMixedFurnitureAndRealLineBlock)."""

    def test_four_items_two_distinct_glyphs_in_one_block(self):
        lines = [
            _line("", [72.0, 100.0, 78.0, 118.0], max_size=14.0),
            _line("Ingestion", [90.0, 101.0, 160.0, 116.0]),
            _line("", [72.0, 120.0, 78.0, 138.0], max_size=14.0),
            _line("Normalize incoming documents", [90.0, 121.0, 260.0, 136.0]),
            _line("continuation with no marker", [90.0, 137.0, 260.0, 152.0]),
            _line("·", [72.0, 154.0, 78.0, 172.0], max_size=14.0),
            _line("Transformation", [90.0, 155.0, 200.0, 170.0]),
        ]
        items = extract_text.parse_block_list_items(lines, [72.0])
        assert len(items) == 3
        assert items[0] == {
            "type": "list_item", "marker": "", "level": 1, "text": "Ingestion",
            "bbox": [72.0, 100.0, 160.0, 118.0],
        }
        assert items[1]["marker"] == ""
        assert items[1]["text"] == "Normalize incoming documents continuation with no marker"
        assert items[1]["bbox"] == [72.0, 120.0, 260.0, 152.0]
        assert items[2]["marker"] == "·"
        assert items[2]["text"] == "Transformation"

    def test_block_not_starting_with_a_marker_returns_none(self):
        lines = [_line("Ordinary paragraph text.", [72.0, 100.0, 300.0, 115.0])]
        assert extract_text.parse_block_list_items(lines, [72.0]) is None

    def test_empty_lines_returns_none(self):
        assert extract_text.parse_block_list_items([], [72.0]) is None

    def test_single_inline_marker_line_still_works(self):
        # The original inline-marker shape (one span, one line) is a
        # degenerate case of the same function -- one item, no glyph pair.
        lines = [_line("- Ingestion", [72.0, 100.0, 200.0, 115.0])]
        items = extract_text.parse_block_list_items(lines, [72.0])
        assert items == [{"type": "list_item", "marker": "-", "level": 1, "text": "Ingestion", "bbox": [72.0, 100.0, 200.0, 115.0]}]


class TestDocumentListMarkerLevelsSeesWithinBlockMarkers:
    """Requirement 4: document_list_marker_levels must see the within-
    block glyph/text-line-pair shape too, not just the original single-
    line-per-block and separate-top-level-block shapes."""

    def test_within_block_glyph_text_pairs_contribute_both_levels(self, tmp_path):
        pdf_path = _build_glyph_size_jump_pdf(tmp_path, "glyph_size_jump_levels.pdf")
        doc = fitz.open(pdf_path)
        clusters = extract_text.document_list_marker_levels(
            doc, body_size=11.0, furniture_masked=set(), toc_lookup={}, heading_size_ranks={},
            page_roles={},
        )
        doc.close()
        assert clusters == [72.0, 100.0]


# ---------------------------------------------------------------------------
# 1e. Real fixture: furniture_sample.pdf's nested 2-level "-" list (page 6)
# ---------------------------------------------------------------------------

class TestFurnitureSampleBulletList:
    def test_bullet_items_come_out_as_list_items_matching_golden(self, furniture_doc, tmp_project):
        golden = _golden()
        bullet_page = golden["bullet_list"]["page"]
        triage = _run_triage(furniture_doc, tmp_project)
        pages = list(range(1, triage["page_count"] + 1))
        _run_ok(
            "extract-text/scripts/extract_text.py", "--doc", furniture_doc,
            "--pages", ",".join(map(str, pages)), "--body-size", str(triage["body_size"]),
            cwd=tmp_project,
        )
        shard = json.loads(paths.shard_path(furniture_doc, bullet_page, "text").read_text())
        list_items = [e for e in shard["elements"] if e["type"] == "list_item"]

        expected = golden["bullet_list"]["items"]
        assert len(list_items) == len(expected)
        for got, want in zip(list_items, expected):
            assert got["level"] == want["level"]
            assert got["text"] == want["text"]
            assert got["marker"] == "-"

        # No bullet-list text leaked out as a plain paragraph.
        paragraph_texts = {e["text"] for e in shard["elements"] if e["type"] == "paragraph"}
        for item in expected:
            assert item["text"] not in paragraph_texts

    def test_level_1_items_indent_less_than_level_2(self, furniture_doc, tmp_project):
        golden = _golden()
        bullet_page = golden["bullet_list"]["page"]
        triage = _run_triage(furniture_doc, tmp_project)
        pages = list(range(1, triage["page_count"] + 1))
        _run_ok(
            "extract-text/scripts/extract_text.py", "--doc", furniture_doc,
            "--pages", ",".join(map(str, pages)), "--body-size", str(triage["body_size"]),
            cwd=tmp_project,
        )
        shard = json.loads(paths.shard_path(furniture_doc, bullet_page, "text").read_text())
        list_items = [e for e in shard["elements"] if e["type"] == "list_item"]
        level1_x = {e["bbox"][0] for e in list_items if e["level"] == 1}
        level2_x = {e["bbox"][0] for e in list_items if e["level"] == 2}
        assert level1_x and level2_x
        assert max(level1_x) < min(level2_x)


# ---------------------------------------------------------------------------
# 2. Page-break joins -- lib/elements.py's merge_shards / apply_page_break_joins
# ---------------------------------------------------------------------------

def _write_page_shard(shards_dir: Path, page_number: int, elements: list[dict]) -> None:
    elements_lib.write_shard(shards_dir / f"page{page_number}.text.json", page_number, elements)


class TestPageBreakJoinUnit:
    def test_paragraph_without_terminal_punctuation_joins_next_pages_paragraph(self, tmp_path):
        shards_dir = tmp_path / "shards"
        _write_page_shard(shards_dir, 1, [
            {"type": "heading", "level": 1, "text": "1 Introduction", "bbox": [72.0, 50.0, 300.0, 70.0]},
            {"type": "paragraph", "text": "This sentence runs on without a period at the page break such as", "bbox": [72.0, 100.0, 500.0, 130.0]},
        ])
        _write_page_shard(shards_dir, 2, [
            {"type": "paragraph", "text": "this continuation, which completes the thought.", "bbox": [72.0, 90.0, 480.0, 110.0]},
            {"type": "paragraph", "text": "An unrelated following paragraph.", "bbox": [72.0, 130.0, 480.0, 150.0]},
        ])

        pages = elements_lib.merge_shards(shards_dir, page_count=2)

        assert len(pages[1]["elements"]) == 2
        joined = pages[1]["elements"][-1]
        assert joined["type"] == "paragraph"
        assert joined["text"] == (
            "This sentence runs on without a period at the page break such as "
            "this continuation, which completes the thought."
        )
        assert joined["pages"] == [1, 2]
        # The joined element's bbox is the union of both source bboxes:
        # x0/y0 = min of each, x1/y1 = max of each.
        assert joined["bbox"] == [72.0, 90.0, 500.0, 130.0]

        # The consumed element is gone from page 2; the unrelated one remains.
        assert [e["text"] for e in pages[2]["elements"]] == ["An unrelated following paragraph."]

    def test_list_item_without_terminal_punctuation_can_join_too(self, tmp_path):
        shards_dir = tmp_path / "shards"
        _write_page_shard(shards_dir, 1, [
            {"type": "list_item", "marker": "-", "level": 1, "text": "an item that runs on such as", "bbox": [72.0, 100.0, 400.0, 115.0]},
        ])
        _write_page_shard(shards_dir, 2, [
            {"type": "paragraph", "text": "this continuation.", "bbox": [72.0, 90.0, 300.0, 110.0]},
        ])
        pages = elements_lib.merge_shards(shards_dir, page_count=2)
        assert len(pages[1]["elements"]) == 1
        joined = pages[1]["elements"][0]
        assert joined["type"] == "list_item"
        assert joined["text"] == "an item that runs on such as this continuation."
        assert joined["pages"] == [1, 2]
        assert pages[2]["elements"] == []

    def test_images_are_ignored_when_finding_the_last_last_element(self, tmp_path):
        shards_dir = tmp_path / "shards"
        _write_page_shard(shards_dir, 1, [
            {"type": "paragraph", "text": "Runs on without punctuation such as", "bbox": [72.0, 100.0, 400.0, 115.0]},
            {"type": "image", "asset": "assets/a.png", "bbox": [72.0, 120.0, 200.0, 220.0]},
        ])
        _write_page_shard(shards_dir, 2, [
            {"type": "paragraph", "text": "this continuation.", "bbox": [72.0, 90.0, 300.0, 110.0]},
        ])
        pages = elements_lib.merge_shards(shards_dir, page_count=2)
        joined = [e for e in pages[1]["elements"] if e["type"] == "paragraph"][0]
        assert joined["text"] == "Runs on without punctuation such as this continuation."
        assert joined["pages"] == [1, 2]


class TestPageBreakJoinNegatives:
    def test_terminal_punctuation_prevents_join(self, tmp_path):
        shards_dir = tmp_path / "shards"
        _write_page_shard(shards_dir, 1, [
            {"type": "paragraph", "text": "This sentence is complete.", "bbox": [72.0, 100.0, 400.0, 115.0]},
        ])
        _write_page_shard(shards_dir, 2, [
            {"type": "paragraph", "text": "A brand new paragraph.", "bbox": [72.0, 90.0, 300.0, 110.0]},
        ])
        pages = elements_lib.merge_shards(shards_dir, page_count=2)
        assert "pages" not in pages[1]["elements"][0]
        assert pages[2]["elements"][0]["text"] == "A brand new paragraph."

    def test_next_page_starting_with_a_heading_prevents_join(self, tmp_path):
        shards_dir = tmp_path / "shards"
        _write_page_shard(shards_dir, 1, [
            {"type": "paragraph", "text": "Runs on without punctuation such as", "bbox": [72.0, 100.0, 400.0, 115.0]},
        ])
        _write_page_shard(shards_dir, 2, [
            {"type": "heading", "level": 1, "text": "2 Next Section", "bbox": [72.0, 90.0, 300.0, 110.0]},
        ])
        pages = elements_lib.merge_shards(shards_dir, page_count=2)
        assert "pages" not in pages[1]["elements"][0]
        assert pages[2]["elements"][0]["type"] == "heading"

    def test_next_page_starting_with_a_new_list_item_prevents_join(self, tmp_path):
        shards_dir = tmp_path / "shards"
        _write_page_shard(shards_dir, 1, [
            {"type": "paragraph", "text": "Runs on without punctuation such as", "bbox": [72.0, 100.0, 400.0, 115.0]},
        ])
        _write_page_shard(shards_dir, 2, [
            {"type": "list_item", "marker": "-", "level": 1, "text": "A new bullet item", "bbox": [72.0, 90.0, 300.0, 110.0]},
        ])
        pages = elements_lib.merge_shards(shards_dir, page_count=2)
        assert "pages" not in pages[1]["elements"][0]
        assert pages[2]["elements"][0]["type"] == "list_item"

    def test_different_indent_prevents_join(self, tmp_path):
        shards_dir = tmp_path / "shards"
        _write_page_shard(shards_dir, 1, [
            {"type": "paragraph", "text": "Runs on without punctuation such as", "bbox": [72.0, 100.0, 400.0, 115.0]},
        ])
        _write_page_shard(shards_dir, 2, [
            {"type": "paragraph", "text": "An indented continuation.", "bbox": [108.0, 90.0, 300.0, 110.0]},
        ])
        pages = elements_lib.merge_shards(shards_dir, page_count=2)
        assert "pages" not in pages[1]["elements"][0]
        assert pages[2]["elements"][0]["text"] == "An indented continuation."

    def test_a_table_at_the_page_end_never_joins(self, tmp_path):
        shards_dir = tmp_path / "shards"
        _write_page_shard(shards_dir, 1, [
            {"type": "table", "rows": [["a", "b"]], "bbox": [72.0, 100.0, 400.0, 130.0]},
        ])
        _write_page_shard(shards_dir, 2, [
            {"type": "paragraph", "text": "Some text.", "bbox": [72.0, 90.0, 300.0, 110.0]},
        ])
        pages = elements_lib.merge_shards(shards_dir, page_count=2)
        assert pages[1]["elements"][0]["type"] == "table"
        assert "pages" not in pages[1]["elements"][0]
        assert pages[2]["elements"][0]["type"] == "paragraph"

    def test_next_page_first_element_is_a_table_never_joins(self, tmp_path):
        shards_dir = tmp_path / "shards"
        _write_page_shard(shards_dir, 1, [
            {"type": "paragraph", "text": "Runs on without punctuation such as", "bbox": [72.0, 100.0, 400.0, 115.0]},
        ])
        _write_page_shard(shards_dir, 2, [
            {"type": "table", "rows": [["a", "b"]], "bbox": [72.0, 90.0, 400.0, 120.0]},
        ])
        pages = elements_lib.merge_shards(shards_dir, page_count=2)
        assert "pages" not in pages[1]["elements"][0]
        assert pages[2]["elements"][0]["type"] == "table"


# ---------------------------------------------------------------------------
# 2b. Real fixture: furniture_sample.pdf's cut paragraph (pages 4 -> 5)
# ---------------------------------------------------------------------------

class TestFurnitureSampleCutParagraph:
    def _extract_and_merge(self, doc: str, tmp_project):
        triage = _run_triage(doc, tmp_project)
        pages = list(range(1, triage["page_count"] + 1))
        _run_ok(
            "extract-text/scripts/extract_text.py", "--doc", doc,
            "--pages", ",".join(map(str, pages)), "--body-size", str(triage["body_size"]),
            cwd=tmp_project,
        )
        _run_ok(
            "extract-images/scripts/extract_images.py", "--doc", doc,
            "--pages", ",".join(map(str, pages)), cwd=tmp_project,
        )
        _run_ok("assemble-output/scripts/merge.py", "--doc", doc, cwd=tmp_project)
        return json.loads(paths.elements_json(doc).read_text())

    def test_cut_paragraph_becomes_one_element_spanning_both_pages(self, furniture_doc, tmp_project):
        golden = _golden()
        start_page = golden["cut_paragraph"]["start_page"]
        continues_page = golden["cut_paragraph"]["continues_page"]
        doc_data = self._extract_and_merge(furniture_doc, tmp_project)
        pages = {p["page_number"]: p for p in doc_data["pages"]}

        joined = [e for e in pages[start_page]["elements"] if e.get("pages") == [start_page, continues_page]]
        assert len(joined) == 1, f"expected exactly one joined element on page {start_page}, got {pages[start_page]['elements']}"
        expected_text = golden["cut_paragraph"]["start_text"] + " " + golden["cut_paragraph"]["continuation_text"]
        assert joined[0]["text"] == expected_text
        assert joined[0]["type"] == "paragraph"

        # The continuation text no longer appears as its own element on the
        # next page.
        next_page_texts = [e.get("text") for e in pages[continues_page]["elements"]]
        assert golden["cut_paragraph"]["continuation_text"] not in next_page_texts


# ---------------------------------------------------------------------------
# 3. Rendering -- Markdown / md-tree / HTML / ReqIF
# ---------------------------------------------------------------------------

NESTED_LIST_ELEMENTS = [
    {"type": "paragraph", "text": "Intro paragraph before the list.", "bbox": [72.0, 50.0, 400.0, 65.0]},
    {"type": "list_item", "marker": "-", "level": 1, "text": "Ingestion", "bbox": [72.0, 100.0, 200.0, 115.0]},
    {"type": "list_item", "marker": "-", "level": 2, "text": "Normalize incoming documents.", "bbox": [90.0, 116.0, 300.0, 131.0]},
    {"type": "list_item", "marker": "1)", "level": 2, "text": "Validate structural markers.", "bbox": [90.0, 132.0, 300.0, 147.0]},
    {"type": "list_item", "marker": "-", "level": 1, "text": "Transformation", "bbox": [72.0, 148.0, 200.0, 163.0]},
    {"type": "paragraph", "text": "Outro paragraph after the list.", "bbox": [72.0, 180.0, 400.0, 195.0]},
]

EXPECTED_LIST_MARKDOWN = (
    "Intro paragraph before the list.\n"
    "\n"
    "- Ingestion\n"
    "  - Normalize incoming documents.\n"
    "  1) Validate structural markers.\n"
    "- Transformation\n"
    "\n"
    "Outro paragraph after the list.\n"
)


class TestMarkdownListRendering:
    def test_nested_list_matches_the_documented_rule_exactly(self):
        md = assemble.elements_to_markdown(NESTED_LIST_ELEMENTS)
        assert md == EXPECTED_LIST_MARKDOWN

    def test_md_tree_renders_the_same_list_the_same_way(self):
        # No headings in this element set, so elements_to_markdown_with_anchors
        # (md-tree's per-file renderer) must produce byte-identical output --
        # anchors are only emitted for headings.
        md = assemble.elements_to_markdown(NESTED_LIST_ELEMENTS)
        md_tree = assemble.elements_to_markdown_with_anchors(NESTED_LIST_ELEMENTS)
        assert md == md_tree

    def test_glyph_marker_always_renders_as_ascii_hyphen(self):
        el = {"type": "list_item", "marker": "•", "level": 1, "text": "Some item"}
        assert assemble.render_list_item_markdown(el) == "- Some item"

    def test_enumerator_marker_renders_verbatim(self):
        el = {"type": "list_item", "marker": "(a)", "level": 1, "text": "Some item"}
        assert assemble.render_list_item_markdown(el) == "(a) Some item"

    def test_only_a_single_list_item_still_gets_surrounding_blank_lines(self):
        elements = [
            {"type": "paragraph", "text": "Before.", "bbox": [72.0, 50.0, 200.0, 65.0]},
            {"type": "list_item", "marker": "-", "level": 1, "text": "Only item", "bbox": [72.0, 70.0, 200.0, 85.0]},
            {"type": "paragraph", "text": "After.", "bbox": [72.0, 90.0, 200.0, 105.0]},
        ]
        md = assemble.elements_to_markdown(elements)
        assert md == "Before.\n\n- Only item\n\nAfter.\n"


class TestHtmlListRendering:
    def test_consecutive_list_items_share_one_ul_with_level_classes(self):
        pages = [{"page_number": 1, "elements": NESTED_LIST_ELEMENTS}]
        doc_data = {"doc": "test", "pages": {1: pages[0]}}
        rendered = assemble.to_html(doc_data)
        assert rendered.count("<ul>") == 1
        assert rendered.count("</ul>") == 1
        assert '<li class="level-1">Ingestion</li>' in rendered
        assert '<li class="level-2">Normalize incoming documents.</li>' in rendered
        assert '<li class="level-2">Validate structural markers.</li>' in rendered
        assert '<li class="level-1">Transformation</li>' in rendered


class TestReqifListRendering:
    def test_list_item_renders_as_a_paragraph_with_indent_and_marker(self):
        doc_data = {
            "doc": "test",
            "pages": {1: {"page_number": 1, "elements": [
                {"type": "list_item", "marker": "-", "level": 2, "text": "Nested item"},
            ]}},
        }
        xml = reqif_builder.build_reqif_xml("test", doc_data)
        assert "  - Nested item" in xml
        assert "List Item" in xml


# ---------------------------------------------------------------------------
# 4. Regression
# ---------------------------------------------------------------------------

class TestSampleUnaffected:
    def test_sample_pdf_produces_no_list_items(self, pdf_doc, tmp_project):
        triage = _run_triage(pdf_doc, tmp_project)
        pages = list(range(1, triage["page_count"] + 1))
        _run_ok(
            "extract-text/scripts/extract_text.py", "--doc", pdf_doc,
            "--pages", ",".join(map(str, pages)), "--body-size", str(triage["body_size"]),
            cwd=tmp_project,
        )
        for n in pages:
            shard_path = paths.shard_path(pdf_doc, n, "text")
            if not shard_path.exists():
                continue
            shard = json.loads(shard_path.read_text())
            assert not any(e["type"] == "list_item" for e in shard["elements"]), f"page {n}: unexpected list_item in sample.pdf"
