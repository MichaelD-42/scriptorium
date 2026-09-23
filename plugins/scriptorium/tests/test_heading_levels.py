"""Task A4 -- heading levels driven by the TOC, with a rank-by-distinct-
bold-size fallback when a document has no TOC at all.

Two heading-classification layers in `extract_text.py`, replacing the old
fixed-ratio `classify_heading_level` (1.9/1.45/1.15) entirely:

  1. **TOC-driven (primary)**, whenever `toc.json` has any entries for this
     document: a candidate block becomes a `heading` at its matching TOC
     entry's level only if its normalized text exactly matches a TOC
     entry's normalized "number + title" text (`lib/toc.py`'s
     `normalize_toc_text`/`toc_entry_heading_text`, Task A4). No match =>
     `paragraph`, no matter the block's size or boldness -- this is the
     rule that fixes the bullet-glyph/false-heading problem from A0-A3.
  2. **Fallback**, only reached when `toc.json` has zero entries at all (no
     printed TOC, no outline): rank the DISTINCT bold, larger-than-body-size
     text sizes across the whole document, largest = level 1, next = level
     2, etc., capped at 6 (`FALLBACK_MAX_LEVELS`). A candidate block also
     needs >= 3 alphanumeric characters (`FALLBACK_NON_GLYPH_MIN_CHARS`) --
     a lone bullet glyph never qualifies.

`furniture_sample.pdf` (has a real 2-page printed TOC + 4 distinct bold
heading sizes, per earlier tasks) exercises the TOC-driven path;
`sample.pdf` (no TOC, no outline, pre-existing) is the fallback-path
regression check; small inline-built PDFs (same "safer choice" pattern as
`test_toc.py`) exercise the fallback ranking, the 6-level collapse, and the
3-character minimum without touching either committed fixture.
"""

import json
import shutil
from pathlib import Path
from xml.etree import ElementTree as ET

import fitz  # PyMuPDF
import pytest

import paths
from conftest import load_script, run_script

EXAMPLES_ROOT = Path(__file__).resolve().parent.parent / "examples"

extract_text = load_script("extract-text/scripts/extract_text.py", "extract_text_a4_module")
assemble = load_script("assemble-output/scripts/assemble.py", "assemble_a4_module")
reqif_builder = load_script("assemble-output/scripts/reqif_builder.py", "reqif_builder_a4_module")


def _golden() -> dict:
    return json.loads((EXAMPLES_ROOT / "furniture_golden.json").read_text())


def _level_from_number(number: str) -> int:
    """Same dot-depth computation as lib/toc.py's `_level_from_number` --
    duplicated here (matching test_toc.py's own precedent) because it's what
    toc.json's entries actually carry as `level`, which is what
    classify_heading_level's TOC-driven path reads. See the module-level
    docstring's note in test_toc.py: this differs from
    furniture_golden.json's `headings` list `level` field for exactly one
    entry ("2.1.2" -- golden says 4, dot-depth says 3); this task's
    heading-level assignment follows toc.json (dot-depth), so the same
    divergence carries forward here."""
    return number.count(".") + 1


def _expected_toc_driven_heading_levels() -> dict[str, int]:
    """{heading block text as drawn ("<number> <title>"): expected level},
    from furniture_golden.json's `headings` list, with level recomputed
    from the number's dot-depth (matching toc.json's actual output) rather
    than taken from golden's own `level` field -- see this module's and
    test_toc.py's docstrings for why they differ for "2.1.2"."""
    return {
        f"{h['number']} {h['title']}": _level_from_number(h["number"])
        for h in _golden()["headings"]
    }


@pytest.fixture
def furniture_doc(tmp_project):
    dest = tmp_project / "input" / "furniture_sample.pdf"
    shutil.copyfile(EXAMPLES_ROOT / "furniture_sample.pdf", dest)
    return "furniture_sample"


def _run_ok(relpath: str, *args: str, cwd) -> str:
    result = run_script(relpath, *args, cwd=cwd)
    assert result.returncode == 0, (
        f"{relpath} {' '.join(args)} failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    return result.stdout


def _run_triage(doc: str, cwd) -> dict:
    _run_ok("pdf-triage/scripts/triage.py", "--doc", doc, cwd=cwd)
    return json.loads(paths.triage_json(doc).read_text())


def _run_extract_text(doc: str, pages: list[int], body_size: float, cwd) -> None:
    _run_ok(
        "extract-text/scripts/extract_text.py", "--doc", doc,
        "--pages", ",".join(map(str, pages)), "--body-size", str(body_size),
        cwd=cwd,
    )


def _all_elements(doc: str, pages: list[int]) -> list[dict]:
    elements = []
    for n in pages:
        shard = json.loads(paths.shard_path(doc, n, "text").read_text())
        elements.extend(shard["elements"])
    return elements


def _headings_by_text(elements: list[dict]) -> dict[str, int]:
    return {e["text"]: e["level"] for e in elements if e["type"] == "heading"}


# --- inline PDF construction (same "safer choice" pattern as test_toc.py) --

def _build_pdf(tmp_path: Path, name: str, pages: list[list[tuple[str, float, str]]]) -> Path:
    """`pages`: one entry per page, each a list of (fontname, fontsize, text)
    tuples drawn top-to-bottom at a fixed left margin. `fontname` is a
    PyMuPDF base-14 alias -- "hebo" (Helvetica-Bold) for heading-style bold
    text, "helv" (Helvetica) for regular body text."""
    out_path = tmp_path / name
    document = fitz.open()
    for lines in pages:
        page = document.new_page()
        # Start well below the top-12%/above the bottom-12% edge bands
        # pdf-triage's furniture detection watches (see FURNITURE_EDGE_BAND
        # in triage.py) -- a single-page (or few-page) synthetic test PDF
        # would otherwise have its only heading trivially "repeat" on
        # 100% of pages and get misdetected as furniture, dropped before
        # heading classification ever sees it.
        y = 150.0
        for fontname, fontsize, text in lines:
            page.insert_text((72, y), text, fontsize=fontsize, fontname=fontname)
            y += fontsize + 14
    document.save(out_path)
    document.close()
    return out_path


BODY = "helv"
BOLD = "hebo"
BODY_TEXT = "This is an ordinary body paragraph with enough characters to anchor the document's median body text size reliably."


class TestTocDrivenHeadingLevels:
    """furniture_sample.pdf: every body heading is classified at its
    matching TOC entry's level; nothing else becomes a heading."""

    def test_every_body_heading_matches_its_toc_entrys_level(self, furniture_doc, tmp_project):
        triage = _run_triage(furniture_doc, tmp_project)
        pages = list(range(1, triage["page_count"] + 1))
        _run_extract_text(furniture_doc, pages, triage["body_size"], tmp_project)

        found = _headings_by_text(_all_elements(furniture_doc, pages))
        expected = _expected_toc_driven_heading_levels()

        # Every TOC-listed heading was found, at exactly the level its TOC
        # entry says -- and nothing else was classified as a heading (the
        # fixture's headings list is exhaustive: every heading printed in
        # the body has a matching TOC entry, one draw_heading() call each).
        assert found == expected

    def test_toc_json_has_entries_sanity(self, furniture_doc, tmp_project):
        """Sanity check on the fixture/setup: this test only proves what it
        claims to if furniture_sample.pdf's toc.json really is non-empty
        (the TOC-driven path, not the fallback, is what's under test)."""
        _run_triage(furniture_doc, tmp_project)
        toc_data = json.loads(paths.toc_json(furniture_doc).read_text())
        assert toc_data["entries"]


class TestTocTitleNotPromotedToHeading:
    """The TOC page's own "Table of Contents" title (18pt bold, per A0) has
    no TOC entry of its own -- it must not leak out as a heading anywhere.
    In practice it never gets the chance: the page it's printed on is
    marked role=toc and its extraction is short-circuited entirely (Task
    A3), so this also re-confirms that short-circuit holds under A4's
    changes."""

    def test_toc_page_is_fully_skipped_not_partially_extracted(self, furniture_doc, tmp_project):
        triage = _run_triage(furniture_doc, tmp_project)
        toc_pages = _golden()["toc"]["pages"]
        _run_extract_text(furniture_doc, toc_pages, triage["body_size"], tmp_project)
        for page_number in toc_pages:
            shard = json.loads(paths.shard_path(furniture_doc, page_number, "text").read_text())
            assert shard["elements"] == []
            assert shard["skipped"] == "toc"

    def test_table_of_contents_title_never_appears_as_a_heading_anywhere(self, furniture_doc, tmp_project):
        triage = _run_triage(furniture_doc, tmp_project)
        pages = list(range(1, triage["page_count"] + 1))
        _run_extract_text(furniture_doc, pages, triage["body_size"], tmp_project)
        found = _headings_by_text(_all_elements(furniture_doc, pages))
        assert "Table of Contents" not in found


class TestBulletGlyphLinesNotHeadings:
    """furniture_sample.pdf's nested bullet list (page 6, ASCII "-" marker,
    per A0's fixture) -- none of its items have a TOC entry, so none of them
    can become a heading under the TOC-driven rule, no matter earlier tasks'
    ratio-based classifier might have done with a large/bold glyph line."""

    def test_bullet_items_are_not_classified_as_headings(self, furniture_doc, tmp_project):
        golden = _golden()
        bullet_page = golden["bullet_list"]["page"]
        triage = _run_triage(furniture_doc, tmp_project)
        _run_extract_text(furniture_doc, [bullet_page], triage["body_size"], tmp_project)

        shard = json.loads(paths.shard_path(furniture_doc, bullet_page, "text").read_text())
        heading_texts = " ".join(e["text"] for e in shard["elements"] if e["type"] == "heading")
        for item in golden["bullet_list"]["items"]:
            assert item["text"] not in heading_texts


class TestFallbackRankingNoToc:
    """No TOC/outline at all -- distinct bold sizes rank into levels
    largest-first."""

    def test_two_distinct_bold_sizes_rank_largest_first(self, tmp_path, tmp_project):
        pdf_path = _build_pdf(tmp_path, "fallback_two_levels.pdf", [
            [(BOLD, 20, "1 Big Heading"), (BODY, 11, BODY_TEXT)],
            [(BOLD, 16, "2 Smaller Heading"), (BODY, 11, BODY_TEXT)],
        ])
        doc_name = "fallback_two_levels"
        shutil.copyfile(pdf_path, tmp_project / "input" / f"{doc_name}.pdf")

        triage = _run_triage(doc_name, tmp_project)
        toc_data = json.loads(paths.toc_json(doc_name).read_text())
        assert toc_data["entries"] == []  # sanity: this really is the no-TOC fallback case

        pages = [1, 2]
        _run_extract_text(doc_name, pages, triage["body_size"], tmp_project)
        found = _headings_by_text(_all_elements(doc_name, pages))

        assert found["1 Big Heading"] == 1
        assert found["2 Smaller Heading"] == 2


class TestFallbackSixLevelCollapse:
    """More than 6 distinct candidate bold sizes: the 6th and every smaller
    one all collapse to level 6 instead of growing unbounded. Exercised
    directly against `document_heading_size_ranks` (unit-level -- building
    a 7-page PDF and running the full pipeline just to inspect a ranking
    dict adds nothing a direct call doesn't already prove)."""

    def test_seventh_and_smaller_distinct_sizes_collapse_to_level_six(self, tmp_path):
        sizes = [30, 28, 26, 24, 22, 20, 18, 16]  # 8 distinct sizes
        pdf_path = _build_pdf(tmp_path, "eight_levels.pdf", [
            [(BOLD, size, f"Heading At Size {size}") for size in sizes] + [(BODY, 11, BODY_TEXT)],
        ])
        with fitz.open(pdf_path) as fitz_doc:
            ranks = extract_text.document_heading_size_ranks(fitz_doc, body_size=11.0)

        assert [ranks[float(s)] for s in sizes] == [1, 2, 3, 4, 5, 6, 6, 6]


class TestFallbackNonGlyphMinimum:
    """A candidate block needs >= 3 alphanumeric characters to be considered
    for heading classification at all in the fallback path -- a lone bullet
    glyph, or any large/bold block with only 1-2 real characters, is never a
    heading regardless of its size or boldness."""

    @pytest.mark.parametrize("text", ["", "-", "AB", "1", "12"])
    def test_fewer_than_three_alnum_chars_is_never_a_candidate(self, text):
        assert extract_text.is_fallback_heading_candidate(text, True, 20.0, 11.0) is False

    def test_three_or_more_alnum_chars_is_a_candidate_when_bold_and_larger(self):
        assert extract_text.is_fallback_heading_candidate("ABC", True, 20.0, 11.0) is True

    def test_two_char_bold_large_block_is_not_a_heading_end_to_end(self, tmp_path, tmp_project):
        """Integration-level version of the same rule: a real heading and a
        same-size/same-boldness two-character blob on the same page -- only
        the real heading is classified as a heading."""
        pdf_path = _build_pdf(tmp_path, "short_glyph_block.pdf", [
            [(BOLD, 20, "1 Real Heading Text"), (BOLD, 20, "AB"), (BODY, 11, BODY_TEXT)],
        ])
        doc_name = "short_glyph_block"
        shutil.copyfile(pdf_path, tmp_project / "input" / f"{doc_name}.pdf")

        triage = _run_triage(doc_name, tmp_project)
        _run_extract_text(doc_name, [1], triage["body_size"], tmp_project)
        elements = _all_elements(doc_name, [1])
        found = _headings_by_text(elements)

        assert found.get("1 Real Heading Text") == 1
        assert "AB" not in found
        # "AB" must still survive as a paragraph, not be dropped entirely.
        paragraph_texts = [e["text"] for e in elements if e["type"] == "paragraph"]
        assert "AB" in paragraph_texts


class TestSamplePdfRegressionUnderFallbackRanking:
    """sample.pdf (no TOC, no outline, pre-existing 5-page fixture) --
    regression check that the new rank-based fallback reproduces the same
    heading levels the old fixed-ratio classifier did."""

    def test_existing_headings_classify_the_same_under_ranking(self, pdf_doc, tmp_project):
        triage = _run_triage(pdf_doc, tmp_project)
        toc_data = json.loads(paths.toc_json(pdf_doc).read_text())
        assert toc_data["entries"] == []  # sanity: sample.pdf really has no TOC/outline

        pages = list(range(1, triage["page_count"] + 1))
        _run_extract_text(pdf_doc, pages, triage["body_size"], tmp_project)
        found = _headings_by_text(_all_elements(pdf_doc, pages))

        assert found == {
            "Elastic Loop Extraction Sample": 1,
            "Introduction": 2,
            "Quarterly Results": 2,
            "Figure: Status Indicator": 2,
            "Figure: Process Diagram": 3,
        }


class TestAssembledOutputAcceptsLevelsAboveThree:
    """assemble.py/output.html.j2/reqif_builder.py must round-trip heading
    levels up to 6, not clamp to 3 (the old de facto ceiling, since the
    previous classifier itself never produced anything above level 3)."""

    def test_markdown_level_six_heading_gets_six_hashes(self):
        md = assemble.elements_to_markdown([{"type": "heading", "level": 6, "text": "Deep Section"}])
        assert md.startswith("###### Deep Section")

    def test_html_level_five_heading_renders_h5_not_clamped(self):
        doc_data = {
            "doc": "d",
            "pages": {1: {"page_number": 1, "elements": [{"type": "heading", "level": 5, "text": "Deep Section"}]}},
        }
        html = assemble.to_html(doc_data)
        assert "<h5>Deep Section</h5>" in html
        assert "<h3>Deep Section</h3>" not in html

    def test_reqif_hierarchy_nests_correctly_through_level_six(self):
        elements = [
            {"type": "heading", "level": 1, "text": "Chapter"},
            {"type": "heading", "level": 4, "text": "Level Four"},
            {"type": "heading", "level": 5, "text": "Level Five"},
            {"type": "heading", "level": 6, "text": "Level Six"},
        ]
        doc_data = {"doc": "d", "pages": {1: {"page_number": 1, "elements": elements}}}
        xml_text = reqif_builder.build_reqif_xml("d", doc_data)
        root = ET.fromstring(xml_text)

        NS = {"r": reqif_builder.REQIF_NS}
        specification = root.find(".//r:SPECIFICATIONS/r:SPECIFICATION", NS)
        top_level = specification.find("r:CHILDREN", NS).findall("r:SPEC-HIERARCHY", NS)
        assert len(top_level) == 1  # only "Chapter" at the top

        level_four_node = top_level[0].find("r:CHILDREN", NS).findall("r:SPEC-HIERARCHY", NS)
        assert len(level_four_node) == 1  # "Level Four" nests inside "Chapter"

        level_five_node = level_four_node[0].find("r:CHILDREN", NS).findall("r:SPEC-HIERARCHY", NS)
        assert len(level_five_node) == 1  # "Level Five" nests inside "Level Four"

        level_six_node = level_five_node[0].find("r:CHILDREN", NS).findall("r:SPEC-HIERARCHY", NS)
        assert len(level_six_node) == 1  # "Level Six" nests inside "Level Five"
