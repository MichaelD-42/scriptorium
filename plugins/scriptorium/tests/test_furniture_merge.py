"""Fix wave I5: the furniture filter at merge time.

extract-text removes furniture lines itself. The `ocr` and `vision` tiers do
not, so an escalated page would bring the title block back and fail
`furniture_absent` at once. `lib/elements.merge_shards` now removes the
furniture lines from an `ocr`/`vision` body, with the same band plus
pattern rule `gates.py` checks (lib/furniture.py):

- a letter-bearing pattern matches a line anywhere on the page;
- a digit-only pattern (e.g. a bare page number) matches only when the
  element's bbox lies in the furniture band of its page.

An element that is empty afterwards is dropped. The number of removed lines
is recorded on the merged page as `furniture_lines_removed`.
"""

import json
import shutil

import elements as elements_lib
import furniture as furniture_lib
import paths
from conftest import EXAMPLES_ROOT, load_script, run_script

gates = load_script("grade-output/scripts/gates.py", "gates_module_furniture_merge")

FURNITURE = {
    **furniture_lib.empty_furniture(),
    "line_patterns": [
        {"masked": "Doc No. SYN-FUR-#"},
        {"masked": "page # (#)"},
        {"masked": "#"},
    ],
}


def _para(text, **extra):
    return {"type": "paragraph", "text": text, **extra}


def _merge(tmp_path, tier, page_elements, page_heights=None):
    elements_lib.write_shard(tmp_path / f"page1.{tier}.json", 1, page_elements)
    return elements_lib.merge_shards(
        tmp_path, 1, furniture=FURNITURE, page_heights=page_heights
    )[1]


class TestOcrAndVisionBodies:
    def test_ocr_title_block_lines_are_dropped(self, tmp_path):
        page = _merge(
            tmp_path,
            "ocr",
            [
                _para("Real body text."),
                _para("Doc No. SYN-FUR-0001"),
                _para("page 4 (11)"),
            ],
        )
        assert [el["text"] for el in page["elements"]] == ["Real body text."]
        assert page["furniture_lines_removed"] == 2

    def test_vision_multi_line_element_keeps_its_other_lines(self, tmp_path):
        page = _merge(
            tmp_path,
            "vision",
            [_para("First line\nDoc No. SYN-FUR-0002\nLast line")],
        )
        assert page["elements"][0]["text"] == "First line\nLast line"
        assert page["furniture_lines_removed"] == 1

    def test_heading_and_list_item_are_filtered_too(self, tmp_path):
        page = _merge(
            tmp_path,
            "ocr",
            [
                {"type": "heading", "level": 1, "text": "page 2 (11)"},
                {
                    "type": "list_item",
                    "marker": "-",
                    "level": 1,
                    "text": "Doc No. SYN-FUR-0001",
                },
                _para("kept"),
            ],
        )
        assert [el["text"] for el in page["elements"]] == ["kept"]

    def test_digit_only_pattern_needs_a_bbox_in_the_band(self, tmp_path):
        page = _merge(
            tmp_path,
            "vision",
            [
                _para("3"),  # no bbox: band unknown, kept
                _para("4", bbox=[100, 400, 110, 410]),  # mid-page, kept
                _para("5", bbox=[300, 760, 310, 770]),  # bottom band, dropped
            ],
            page_heights={1: 792.0},
        )
        assert [el["text"] for el in page["elements"]] == ["3", "4"]
        assert page["furniture_lines_removed"] == 1

    def test_no_count_key_when_nothing_was_removed(self, tmp_path):
        page = _merge(tmp_path, "ocr", [_para("clean")])
        assert "furniture_lines_removed" not in page


class TestTextTierIsLeftAlone:
    def test_text_body_is_not_filtered(self, tmp_path):
        # extract-text already applies its own band rule; a body line that
        # happens to match a pattern there is its decision, not merge's.
        page = _merge(tmp_path, "text", [_para("Doc No. SYN-FUR-0001")])
        assert [el["text"] for el in page["elements"]] == ["Doc No. SYN-FUR-0001"]
        assert "furniture_lines_removed" not in page

    def test_no_furniture_argument_changes_nothing(self, tmp_path):
        elements_lib.write_shard(
            tmp_path / "page1.ocr.json", 1, [_para("Doc No. SYN-FUR-0001")]
        )
        page = elements_lib.merge_shards(tmp_path, 1)[1]
        assert page["elements"][0]["text"] == "Doc No. SYN-FUR-0001"


class TestMergeScriptEndToEnd:
    def test_ocr_shard_with_title_block_merges_without_it(self, tmp_project):
        doc = "furniture_sample"
        shutil.copyfile(
            EXAMPLES_ROOT / f"{doc}.pdf", tmp_project / "input" / f"{doc}.pdf"
        )
        result = run_script(
            "pdf-triage/scripts/triage.py", "--doc", doc, cwd=tmp_project
        )
        assert result.returncode == 0, result.stderr
        triage = json.loads(paths.triage_json(doc).read_text())
        furniture = triage["furniture"]
        assert furniture["line_patterns"], "sanity: the fixture has furniture"

        golden = json.loads((EXAMPLES_ROOT / "furniture_golden.json").read_text())
        doc_line = golden["furniture"]["lines"][0]["text"]
        page_line = golden["furniture"]["lines"][2]["text_template"].format(
            n=5, total=golden["page_count"]
        )
        elements_lib.write_shard(
            paths.shard_path(doc, 5, "ocr"),
            5,
            [_para("An OCR body paragraph."), _para(doc_line), _para(page_line)],
        )
        result = run_script(
            "assemble-output/scripts/merge.py", "--doc", doc, cwd=tmp_project
        )
        assert result.returncode == 0, result.stderr

        merged = json.loads(paths.elements_json(doc).read_text())
        page5 = next(p for p in merged["pages"] if p["page_number"] == 5)
        assert [el["text"] for el in page5["elements"]] == ["An OCR body paragraph."]
        assert page5["furniture_lines_removed"] == 2

        check = gates.check_furniture_absent(
            {"pages": {5: page5}}, furniture, tmp_project / "no-output"
        )
        assert check["passed"], check["detail"]
