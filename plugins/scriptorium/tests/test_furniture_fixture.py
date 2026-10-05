"""Smoke test for the furniture/TOC/heading/figure/list fixture (Task A0).

This only guards the fixture itself -- regenerating it into a tmp dir and
checking basic structural sanity (page count, that furniture_golden.json
parses and its sections match what generate_furniture_fixture.py built).
Later tasks (A1 onward) write the tests that check triage/extraction
behavior against this fixture; they read furniture_golden.json as ground
truth instead of hand-coding expectations inline.

The PDF itself is not compared byte-for-byte against the committed copy --
reportlab embeds a CreationDate/ID that changes on every run, so that
comparison would be flaky. The golden JSON has no such non-determinism, so
it *is* compared byte-for-byte to the committed copy, which additionally
guards against the generator and the committed fixture drifting apart.
"""

import importlib
import json
import sys
from pathlib import Path

import fitz  # PyMuPDF

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_ROOT = Path(__file__).resolve().parent.parent / "examples"
COMMITTED_PDF = EXAMPLES_ROOT / "furniture_sample.pdf"
COMMITTED_JSON = EXAMPLES_ROOT / "furniture_golden.json"

sys.path.insert(0, str(REPO_ROOT / "examples"))
import generate_furniture_fixture as gen  # noqa: E402


def test_generator_script_exists():
    assert (REPO_ROOT / "examples" / "generate_furniture_fixture.py").exists()


def test_committed_fixture_files_exist():
    assert COMMITTED_PDF.exists()
    assert COMMITTED_JSON.exists()


def test_regenerating_reproduces_committed_golden_json_and_page_count(tmp_path):
    tmp_pdf = tmp_path / "furniture_sample.pdf"
    tmp_json = tmp_path / "furniture_golden.json"

    importlib.reload(gen)
    regenerated = gen.generate(output_pdf=tmp_pdf, output_json=tmp_json)

    committed = json.loads(COMMITTED_JSON.read_text())
    assert regenerated == committed, "generator output has drifted from the committed furniture_golden.json -- regenerate and recommit it"

    with fitz.open(tmp_pdf) as doc:
        assert doc.page_count == regenerated["page_count"]
    with fitz.open(COMMITTED_PDF) as doc:
        assert doc.page_count == regenerated["page_count"]


def test_golden_json_page_count_matches_committed_pdf():
    golden = json.loads(COMMITTED_JSON.read_text())
    with fitz.open(COMMITTED_PDF) as doc:
        assert doc.page_count == golden["page_count"]
        assert doc.page_count >= 6  # brief: "6-8 pages is enough" -- this fixture needs 9, plus 2 appendix pages since Task A9


class TestGoldenFurniture:
    def test_furniture_section_present_on_every_page(self):
        golden = json.loads(COMMITTED_JSON.read_text())
        furniture = golden["furniture"]
        assert furniture["pages"] == list(range(1, golden["page_count"] + 1))
        assert furniture["frame_bbox"]
        assert len(furniture["frame_bbox"]) == 4
        assert furniture["logo_bbox"]
        assert len(furniture["lines"]) == 3
        for line in furniture["lines"]:
            assert "text" in line or "text_template" in line
            assert len(line["y_band"]) == 2
            assert 0.0 <= line["y_band"][0] < line["y_band"][1] <= 1.0


class TestGoldenToc:
    def test_toc_entries_non_empty_and_well_formed(self):
        golden = json.loads(COMMITTED_JSON.read_text())
        toc = golden["toc"]
        assert toc["pages"] == [2, 3]
        assert len(toc["entries"]) > 0
        for e in toc["entries"]:
            assert {"number", "title", "page", "level"} <= e.keys()
            assert e["level"] in (1, 2, 3, 4)

    def test_at_least_three_split_line_entries(self):
        golden = json.loads(COMMITTED_JSON.read_text())
        split_entries = [e for e in golden["toc"]["entries"] if e.get("split_line")]
        assert len(split_entries) >= 3


class TestGoldenHeadings:
    def test_headings_non_empty_and_four_distinct_sizes(self):
        golden = json.loads(COMMITTED_JSON.read_text())
        headings = golden["headings"]
        assert len(headings) > 0
        levels = {h["level"] for h in headings}
        assert levels == {1, 2, 3, 4}
        sizes = {h["font_size"] for h in headings}
        assert len(sizes) == 4

    def test_every_heading_matches_a_toc_entry(self):
        golden = json.loads(COMMITTED_JSON.read_text())
        toc_keys = {(e["number"], e["title"]) for e in golden["toc"]["entries"]}
        for h in golden["headings"]:
            assert (h["number"], h["title"]) in toc_keys

    def test_every_toc_entry_has_a_body_heading_on_its_page(self):
        """Task A9: the reverse direction. grade-output's toc_headings_match
        gate requires every TOC entry to appear as a body heading, so the
        fixture's TOC must not list entries that the body never prints --
        the appendix-style entries print on their own page (page 10)."""
        golden = json.loads(COMMITTED_JSON.read_text())
        heading_pages = {(h["number"], h["title"]): h["page"] for h in golden["headings"]}
        for e in golden["toc"]["entries"]:
            key = (e["number"], e["title"])
            assert key in heading_pages, f"TOC entry {key} has no body heading"
            assert heading_pages[key] == e["page"]


class TestGoldenFigures:
    def test_two_figures_with_captions_and_pages(self):
        golden = json.loads(COMMITTED_JSON.read_text())
        figures = golden["figures"]
        assert len(figures) == 2
        for fig in figures:
            assert fig["caption"].startswith("Figure ")
            assert fig["page"] >= 4


class TestGoldenListAndCutParagraph:
    def test_bullet_list_has_two_indent_levels(self):
        golden = json.loads(COMMITTED_JSON.read_text())
        items = golden["bullet_list"]["items"]
        assert len(items) > 0
        assert {item["level"] for item in items} == {1, 2}

    def test_cut_paragraph_spans_consecutive_pages(self):
        golden = json.loads(COMMITTED_JSON.read_text())
        cut = golden["cut_paragraph"]
        assert cut["continues_page"] == cut["start_page"] + 1
        assert not cut["start_text"].rstrip().endswith((".", "!", "?"))


class TestGoldenTable:
    def test_frame_only_table_page_differs_from_content_table_page(self):
        golden = json.loads(COMMITTED_JSON.read_text())
        table = golden["table"]
        assert table["frame_only_page"] != table["content_page"]
