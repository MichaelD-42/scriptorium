"""Task A9: grade-output/scripts/gates.py's structure checks --
`furniture_absent`, `toc_headings_match` and `figures_complete`.

Unit tests build small hand-written elements.json / triage.json / toc.json
shapes, in the same style as test_gates.py. The end-to-end tests at the
bottom run the real pipeline on furniture_sample.pdf and on sample.pdf.
"""

import json
import shutil
from pathlib import Path

import fitz  # PyMuPDF
import pytest

import elements as elements_lib
import paths
from conftest import EXAMPLES_ROOT, describe_all_images, load_script, run_script

gates = load_script("grade-output/scripts/gates.py", "gates_module_a9")

FURNITURE = {
    "line_patterns": [
        {"masked": "Doc No. SYN-FUR-#", "edge": "bottom", "y_min": 730.0, "y_max": 740.0, "page_count": 3},
        {"masked": "page # (#)", "edge": "bottom", "y_min": 754.0, "y_max": 764.0, "page_count": 3},
    ],
    "frame_tables": [{"bbox": [24.0, 24.0, 588.0, 768.0], "page_count": 3}],
    "frame_drawings": [],
    "image_xrefs": [4],
}
NO_FURNITURE = {"line_patterns": [], "frame_tables": [], "frame_drawings": [], "image_xrefs": []}


def _doc_data(pages: dict) -> dict:
    return {"doc": "doc", "pages": pages}


def _page(number: int, elements: list[dict]) -> dict:
    return {"page_number": number, "tier": "text", "elements": elements}


def _clean_pages() -> dict:
    return {
        1: _page(1, [
            {"type": "heading", "level": 1, "text": "1 Introduction"},
            {"type": "paragraph", "text": "Body text on page 1."},
        ]),
        2: _page(2, [{"type": "table", "rows": [["Field", "Value"], ["Status", "Draft"]], "bbox": [156.0, 356.0, 456.0, 422.0]}]),
    }


def _write_md(output_dir, text: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "doc.md").write_text(text, encoding="utf-8", newline="")


# ---------------------------------------------------------------------------
# furniture_absent
# ---------------------------------------------------------------------------


class TestFurnitureAbsent:
    def test_passes_on_clean_elements_and_output(self, tmp_path):
        _write_md(tmp_path, "# 1 Introduction\n\nBody text on page 1.\n")
        result = gates.check_furniture_absent(_doc_data(_clean_pages()), FURNITURE, tmp_path)
        assert result["name"] == "furniture_absent"
        assert result["passed"] is True, result["detail"]

    def test_passes_trivially_with_no_furniture(self, tmp_path):
        pages = _clean_pages()
        pages[1]["elements"].append({"type": "paragraph", "text": "Doc No. SYN-FUR-0001"})
        _write_md(tmp_path, "Doc No. SYN-FUR-0001\n")
        result = gates.check_furniture_absent(_doc_data(pages), NO_FURNITURE, tmp_path)
        assert result["passed"] is True

    def test_fails_on_a_furniture_line_left_in_a_paragraph(self, tmp_path):
        pages = _clean_pages()
        pages[1]["elements"].append({"type": "paragraph", "text": "page 1 (3)"})
        result = gates.check_furniture_absent(_doc_data(pages), FURNITURE, tmp_path)
        assert result["passed"] is False
        assert result["pages"] == [1]
        assert {"page": 1, "where": "paragraph", "text": "page 1 (3)"} in result["offenders"]
        assert "page 1 (3)" in result["detail"]

    def test_fails_on_a_furniture_line_inside_a_multi_line_element(self, tmp_path):
        pages = _clean_pages()
        pages[1]["elements"].append({"type": "list_item", "level": 1, "marker": "-", "text": "Item text\nDoc No. SYN-FUR-0002"})
        result = gates.check_furniture_absent(_doc_data(pages), FURNITURE, tmp_path)
        assert result["passed"] is False
        assert result["offenders"][0]["where"] == "list_item"

    def test_fails_on_a_furniture_line_in_a_table_cell(self, tmp_path):
        pages = _clean_pages()
        pages[2]["elements"][0]["rows"].append(["Doc No. SYN-FUR-0001", ""])
        result = gates.check_furniture_absent(_doc_data(pages), FURNITURE, tmp_path)
        assert result["passed"] is False
        assert result["pages"] == [2]
        assert result["offenders"][0]["where"] == "table cell"

    def test_fails_on_a_furniture_line_in_figure_text_or_caption(self, tmp_path):
        pages = _clean_pages()
        pages[2]["elements"].append({
            "type": "image", "kind": "vector", "asset": "assets/a.png", "bbox": [0, 0, 10, 10],
            "figure_text": "Start\npage 2 (3)", "caption": "Doc No. SYN-FUR-0001", "description": "d",
        })
        result = gates.check_furniture_absent(_doc_data(pages), FURNITURE, tmp_path)
        assert result["passed"] is False
        assert {o["where"] for o in result["offenders"]} == {"image figure_text", "image caption"}

    def test_fails_when_a_frame_table_bbox_is_a_table_element(self, tmp_path):
        pages = _clean_pages()
        pages[2]["elements"].append({"type": "table", "rows": [["a"]], "bbox": [25.0, 23.0, 587.0, 769.5]})
        result = gates.check_furniture_absent(_doc_data(pages), FURNITURE, tmp_path)
        assert result["passed"] is False
        assert result["pages"] == [2]
        assert result["offenders"][0]["where"] == "frame table"

    def test_a_real_table_away_from_the_frame_bbox_passes(self, tmp_path):
        result = gates.check_furniture_absent(_doc_data(_clean_pages()), FURNITURE, tmp_path)
        assert result["passed"] is True

    def test_fails_on_a_furniture_line_in_the_assembled_markdown(self, tmp_path):
        _write_md(tmp_path, "# 1 Introduction\n\nBody text.\n\nDoc No. SYN-FUR-0001\n")
        result = gates.check_furniture_absent(_doc_data(_clean_pages()), FURNITURE, tmp_path)
        assert result["passed"] is False
        offender = result["offenders"][0]
        assert offender["where"] == "doc.md line 5"
        assert offender["text"] == "Doc No. SYN-FUR-0001"
        assert offender["page"] is None
        # The output file names no page, so it adds none to `pages`.
        assert result["pages"] == []

    def test_fails_on_a_furniture_line_in_a_markdown_table_cell_or_md_tree_file(self, tmp_path):
        section = tmp_path / "01-introduction"
        section.mkdir(parents=True)
        (section / "01.00-introduction.md").write_text("| page 4 (11) | x |\n", encoding="utf-8", newline="")
        result = gates.check_furniture_absent(_doc_data(_clean_pages()), FURNITURE, tmp_path)
        assert result["passed"] is False
        assert result["offenders"][0]["where"] == "01-introduction/01.00-introduction.md line 1"

    # Fix round 1 (review finding 2): a digit-only pattern (a footer that is
    # just the page number) matches an element only inside a furniture
    # band, and never in the assembled output.

    BARE_NUMBER_FURNITURE = {
        "line_patterns": [{"masked": "#", "edge": "bottom", "y_min": 760.0, "y_max": 770.0, "page_count": 3}],
        "frame_tables": [], "frame_drawings": [], "image_xrefs": [],
    }
    PAGE_HEIGHTS = {1: 792.0, 2: 792.0}

    def test_bare_number_table_cell_in_the_body_passes(self, tmp_path):
        pages = _clean_pages()
        pages[2]["elements"][0]["rows"].append(["Quantity", "3"])  # table bbox is mid-page
        pages[1]["elements"].append({"type": "paragraph", "text": "12", "bbox": [72.0, 300.0, 90.0, 312.0]})
        _write_md(tmp_path, "| Quantity | 3 |\n\n12\n")
        result = gates.check_furniture_absent(_doc_data(pages), self.BARE_NUMBER_FURNITURE, tmp_path, self.PAGE_HEIGHTS)
        assert result["passed"] is True, result["detail"]

    def test_bare_number_footer_left_inside_the_band_fails(self, tmp_path):
        pages = _clean_pages()
        pages[1]["elements"].append({"type": "paragraph", "text": "1", "bbox": [300.0, 760.0, 306.0, 770.0]})
        result = gates.check_furniture_absent(_doc_data(pages), self.BARE_NUMBER_FURNITURE, tmp_path, self.PAGE_HEIGHTS)
        assert result["passed"] is False
        assert result["offenders"] == [{"page": 1, "where": "paragraph", "text": "1"}]

    def test_bare_number_without_page_geometry_is_not_flagged(self, tmp_path):
        # No page height (a non-PDF input) means the band rule cannot be
        # applied, so a digit-only pattern never matches.
        pages = _clean_pages()
        pages[1]["elements"].append({"type": "paragraph", "text": "1", "bbox": [300.0, 760.0, 306.0, 770.0]})
        result = gates.check_furniture_absent(_doc_data(pages), self.BARE_NUMBER_FURNITURE, tmp_path)
        assert result["passed"] is True

    def test_a_pattern_with_letters_still_matches_anywhere(self, tmp_path):
        pages = _clean_pages()
        pages[1]["elements"].append({"type": "paragraph", "text": "page 1 (3)", "bbox": [72.0, 300.0, 200.0, 312.0]})
        result = gates.check_furniture_absent(_doc_data(pages), FURNITURE, tmp_path, self.PAGE_HEIGHTS)
        assert result["passed"] is False

    def test_digit_masking_does_not_match_other_text(self, tmp_path):
        pages = _clean_pages()
        pages[1]["elements"].append({"type": "paragraph", "text": "See page 4 (Appendix) for details."})
        result = gates.check_furniture_absent(_doc_data(pages), FURNITURE, tmp_path)
        assert result["passed"] is True


# ---------------------------------------------------------------------------
# toc_headings_match
# ---------------------------------------------------------------------------

TOC_ENTRIES = [
    {"number": "1", "title": "Introduction", "page": 4, "level": 1},
    {"number": "1.1", "title": "Purpose and Scope", "page": 4, "level": 2},
    {"number": "2", "title": "System Requirements", "page": 5, "level": 1},
]


def _toc_pages(overrides: dict | None = None, extra: list | None = None) -> dict:
    """Headings that match TOC_ENTRIES exactly; `overrides` maps a heading
    index to replacement fields, `extra` adds (page, element) pairs."""
    headings = [
        (4, {"type": "heading", "level": 1, "text": "1 Introduction"}),
        (4, {"type": "heading", "level": 2, "text": "1.1 Purpose and Scope"}),
        (5, {"type": "heading", "level": 1, "text": "2 System Requirements"}),
    ]
    for index, fields in (overrides or {}).items():
        page, el = headings[index]
        headings[index] = (fields.pop("page", page), {**el, **fields})
    pages = {n: _page(n, [{"type": "paragraph", "text": "x"}]) for n in range(1, 8)}
    for page, el in headings + (extra or []):
        pages[page]["elements"].append(el)
    return pages


class TestTocHeadingsMatch:
    def test_passes_when_every_entry_matches(self):
        result = gates.check_toc_headings_match(_doc_data(_toc_pages()), TOC_ENTRIES)
        assert result["name"] == "toc_headings_match"
        assert result["passed"] is True, result["detail"]

    def test_passes_trivially_with_no_toc_entries(self):
        pages = _toc_pages(extra=[(6, {"type": "heading", "level": 1, "text": "Anything"})])
        result = gates.check_toc_headings_match(_doc_data(pages), [])
        assert result["passed"] is True
        assert "no TOC entries" in result["detail"]

    def test_normalized_text_matches(self):
        pages = _toc_pages({0: {"text": "1  INTRODUCTION:"}})
        assert gates.check_toc_headings_match(_doc_data(pages), TOC_ENTRIES)["passed"] is True

    def test_passes_one_page_off_either_way(self):
        pages = _toc_pages({0: {"page": 5}, 2: {"page": 4}})
        assert gates.check_toc_headings_match(_doc_data(pages), TOC_ENTRIES)["passed"] is True

    def test_fails_on_a_missing_heading(self):
        pages = _toc_pages()
        pages[5]["elements"] = [el for el in pages[5]["elements"] if el["type"] != "heading"]
        result = gates.check_toc_headings_match(_doc_data(pages), TOC_ENTRIES)
        assert result["passed"] is False
        assert result["missing"] == [{"number": "2", "title": "System Requirements", "page": 5, "level": 1}]
        assert result["pages"] == [5]

    def test_fails_on_a_wrong_level(self):
        pages = _toc_pages({1: {"level": 3}})
        result = gates.check_toc_headings_match(_doc_data(pages), TOC_ENTRIES)
        assert result["passed"] is False
        assert result["level_mismatch"] == [{"text": "1.1 Purpose and Scope", "page": 4, "toc_level": 2, "heading_level": 3}]
        assert result["pages"] == [4]

    def test_fails_on_a_page_off_by_two(self):
        pages = _toc_pages({2: {"page": 7}})
        result = gates.check_toc_headings_match(_doc_data(pages), TOC_ENTRIES)
        assert result["passed"] is False
        assert result["page_mismatch"] == [{"text": "2 System Requirements", "toc_page": 5, "heading_page": 7}]
        assert result["pages"] == [5, 7]

    def test_fails_on_an_extra_heading_not_in_the_toc(self):
        pages = _toc_pages(extra=[(6, {"type": "heading", "level": 2, "text": "Stray Bold Line"})])
        result = gates.check_toc_headings_match(_doc_data(pages), TOC_ENTRIES)
        assert result["passed"] is False
        assert result["extra"] == [{"text": "Stray Bold Line", "page": 6, "level": 2}]
        assert result["pages"] == [6]

    def test_a_second_copy_of_a_toc_heading_is_extra(self):
        pages = _toc_pages(extra=[(6, {"type": "heading", "level": 1, "text": "1 Introduction"})])
        result = gates.check_toc_headings_match(_doc_data(pages), TOC_ENTRIES)
        assert result["passed"] is False
        assert result["extra"] == [{"text": "1 Introduction", "page": 6, "level": 1}]

    def test_entry_without_a_number_matches_its_title(self):
        entries = [{"number": None, "title": "Overview", "page": 2, "level": 1}]
        pages = {2: _page(2, [{"type": "heading", "level": 1, "text": "Overview"}])}
        assert gates.check_toc_headings_match(_doc_data(pages), entries)["passed"] is True


# ---------------------------------------------------------------------------
# figures_complete
# ---------------------------------------------------------------------------


def _image(**fields) -> dict:
    return {"type": "image", "kind": "vector", "asset": "assets/page3_vector1.png", "bbox": [0, 0, 10, 10], **fields}


class TestFiguresComplete:
    def test_passes_with_caption_and_description(self):
        pages = {3: _page(3, [_image(caption="Figure 1: Flow", description="A flow chart.")])}
        result = gates.check_figures_complete(_doc_data(pages))
        assert result["name"] == "figures_complete"
        assert result["passed"] is True, result["detail"]

    def test_passes_with_figure_text_and_description(self):
        pages = {3: _page(3, [_image(figure_text="Start\nEnd", description="A flow chart.")])}
        assert gates.check_figures_complete(_doc_data(pages))["passed"] is True

    def test_passes_trivially_with_no_images(self):
        pages = {1: _page(1, [{"type": "paragraph", "text": "x"}])}
        assert gates.check_figures_complete(_doc_data(pages))["passed"] is True

    def test_fails_with_no_caption_and_no_figure_text(self):
        pages = {3: _page(3, [_image(description="A flow chart.", caption="  ")])}
        result = gates.check_figures_complete(_doc_data(pages))
        assert result["passed"] is False
        assert result["incomplete"] == [{"page": 3, "asset": "assets/page3_vector1.png", "missing": ["caption or figure_text"]}]
        assert result["pages"] == [3]

    def test_fails_with_no_description(self):
        pages = {3: _page(3, [_image(caption="Figure 1: Flow")])}
        result = gates.check_figures_complete(_doc_data(pages))
        assert result["passed"] is False
        assert result["incomplete"] == [{"page": 3, "asset": "assets/page3_vector1.png", "missing": ["description"]}]

    # Fix round 1 (review finding 1): an explicit, recorded flag replaces an
    # agent-written caption for an image with no visible text.

    def test_passes_with_no_visible_text_flag_and_description(self):
        pages = {3: _page(3, [_image(no_visible_text=True, description="A plain square icon.")])}
        assert gates.check_figures_complete(_doc_data(pages), "pdf")["passed"] is True
        assert gates.check_figures_complete(_doc_data(pages), "image")["passed"] is True

    def test_fails_with_no_visible_text_flag_and_no_description(self):
        pages = {3: _page(3, [_image(no_visible_text=True)])}
        result = gates.check_figures_complete(_doc_data(pages), "pdf")
        assert result["passed"] is False
        assert result["incomplete"] == [{"page": 3, "asset": "assets/page3_vector1.png", "missing": ["description"]}]

    # Fix round 2: the flag counts only for pdf and image documents, where
    # caption is verbatim-only. Other formats' agents write --caption.

    def test_flag_does_not_count_for_a_docx_image(self):
        pages = {1: _page(1, [_image(no_visible_text=True, description="A plain square icon.")])}
        result = gates.check_figures_complete(_doc_data(pages), "docx")
        assert result["passed"] is False
        assert result["incomplete"][0]["missing"] == ["caption or figure_text"]

    def test_flag_does_not_count_when_the_format_is_unknown(self):
        pages = {1: _page(1, [_image(no_visible_text=True, description="A plain square icon.")])}
        assert gates.check_figures_complete(_doc_data(pages))["passed"] is False

    def test_fails_with_no_caption_no_figure_text_and_no_flag(self):
        pages = {3: _page(3, [_image(description="A plain square icon.", no_visible_text=False)])}
        result = gates.check_figures_complete(_doc_data(pages))
        assert result["passed"] is False
        assert result["incomplete"][0]["missing"] == ["caption or figure_text"]

    def test_reports_both_missing_fields_and_every_incomplete_image(self):
        pages = {
            2: _page(2, [_image(asset="assets/a.png")]),
            3: _page(3, [_image(caption="Figure 1", description="ok"), _image(asset="assets/b.png", figure_text="x")]),
        }
        result = gates.check_figures_complete(_doc_data(pages))
        assert result["incomplete"] == [
            {"page": 2, "asset": "assets/a.png", "missing": ["caption or figure_text", "description"]},
            {"page": 3, "asset": "assets/b.png", "missing": ["description"]},
        ]
        assert result["pages"] == [2, 3]


# ---------------------------------------------------------------------------
# describe_image.py --no-visible-text (fix round 1, finding 1)
# ---------------------------------------------------------------------------


class TestDescribeImageNoVisibleText:
    def _seed(self, ext: str = "pdf", **fields) -> None:
        # describe_image.py reads the source format from input/<doc>.<ext>
        # (paths.detect_input_format); the file content does not matter.
        (Path("input") / f"doc.{ext}").write_bytes(b"synthetic")
        shard_path = paths.shard_path("doc", 1, "image")
        elements_lib.write_shard(shard_path, 1, [{"type": "image", "kind": "bitmap", "asset": "assets/a.png", "bbox": [0, 0, 1, 1], **fields}])

    def _run(self, tmp_project, *extra):
        return run_script(
            "extract-images/scripts/describe_image.py",
            "--doc", "doc", "--page", "1", "--asset", "assets/a.png", "--description", "A plain square icon.", *extra,
            cwd=tmp_project,
        )

    def _element(self) -> dict:
        return json.loads(paths.shard_path("doc", 1, "image").read_text())["elements"][0]

    def test_sets_the_flag(self, tmp_project):
        self._seed()
        result = self._run(tmp_project, "--no-visible-text")
        assert result.returncode == 0, result.stderr
        el = self._element()
        assert el["no_visible_text"] is True
        assert el["description"] == "A plain square icon."
        assert "caption" not in el

    def test_refuses_when_a_caption_exists(self, tmp_project):
        self._seed(caption="Figure 1: Flow")
        result = self._run(tmp_project, "--no-visible-text")
        assert result.returncode == 1
        assert "no-visible-text" in result.stderr
        el = self._element()
        assert "no_visible_text" not in el and "description" not in el

    def test_refuses_when_figure_text_exists(self, tmp_project):
        self._seed(figure_text="Start")
        result = self._run(tmp_project, "--no-visible-text")
        assert result.returncode == 1
        assert "no_visible_text" not in self._element()

    def test_sets_the_flag_for_an_image_document(self, tmp_project):
        self._seed(ext="png")
        assert self._run(tmp_project, "--no-visible-text").returncode == 0
        assert self._element()["no_visible_text"] is True

    @pytest.mark.parametrize("ext", ["pptx", "docx", "xlsx", "html"])
    def test_refuses_for_a_format_whose_agent_writes_captions(self, tmp_project, ext):
        self._seed(ext=ext)
        result = self._run(tmp_project, "--no-visible-text")
        assert result.returncode == 1
        assert "--caption" in result.stderr
        el = self._element()
        assert "no_visible_text" not in el and "description" not in el

    def test_refuses_together_with_caption_or_figure_text_arguments(self, tmp_project):
        self._seed()
        assert self._run(tmp_project, "--no-visible-text", "--figure-text", "Start").returncode == 1
        assert self._run(tmp_project, "--no-visible-text", "--caption", "Logo").returncode == 1
        assert "no_visible_text" not in self._element()


# ---------------------------------------------------------------------------
# CLI: gates.py reads triage.json / toc.json itself
# ---------------------------------------------------------------------------


def _run_ok(relpath: str, *args: str, cwd) -> str:
    result = run_script(relpath, *args, cwd=cwd)
    assert result.returncode == 0, (
        f"{relpath} {' '.join(args)} failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    return result.stdout


class TestGatesCliReadsTriageAndToc:
    def _seed(self, tmp_project, heading_text: str, md_text: str) -> None:
        doc = fitz.open()
        for _ in range(2):
            doc.new_page()
        doc.save(str(tmp_project / "input" / "doc.pdf"))
        doc.close()
        work = paths.work_dir("doc")
        work.mkdir(parents=True)
        paths.triage_json("doc").write_text(json.dumps({"doc": "doc", "page_count": 2, "furniture": FURNITURE}))
        paths.toc_json("doc").write_text(json.dumps({"doc": "doc", "entries": [
            {"number": "1", "title": "Introduction", "page": 2, "level": 1},
        ]}))
        paths.elements_json("doc").write_text(json.dumps({"doc": "doc", "page_count": 2, "pages": [
            {"page_number": 1, "tier": "text", "elements": [{"type": "paragraph", "text": "Cover."}]},
            {"page_number": 2, "tier": "text", "elements": [{"type": "heading", "level": 1, "text": heading_text}]},
        ]}))
        _write_md(paths.output_dir("doc"), md_text)

    def test_all_three_checks_present_and_passing(self, tmp_project):
        self._seed(tmp_project, "1 Introduction", "Cover.\n\n# 1 Introduction\n")
        report = json.loads(_run_ok("grade-output/scripts/gates.py", "--doc", "doc", cwd=tmp_project))
        checks = {c["name"]: c for c in report["checks"]}
        for name in ("furniture_absent", "toc_headings_match", "figures_complete"):
            assert checks[name]["passed"] is True, checks[name]
        assert report["passed"] is True

    def test_a_failing_structure_check_fails_the_report(self, tmp_project):
        self._seed(tmp_project, "1 Intro", "Cover.\n\n# 1 Intro\n\npage 2 (2)\n")
        report = json.loads(_run_ok("grade-output/scripts/gates.py", "--doc", "doc", cwd=tmp_project))
        checks = {c["name"]: c for c in report["checks"]}
        assert checks["furniture_absent"]["passed"] is False
        assert checks["toc_headings_match"]["passed"] is False
        assert report["passed"] is False

    def test_missing_triage_and_toc_files_pass_trivially(self, tmp_project):
        self._seed(tmp_project, "1 Introduction", "Cover.\n\n# 1 Introduction\n")
        paths.triage_json("doc").unlink()
        paths.toc_json("doc").unlink()
        report = json.loads(_run_ok("grade-output/scripts/gates.py", "--doc", "doc", cwd=tmp_project))
        checks = {c["name"]: c for c in report["checks"]}
        assert checks["furniture_absent"]["passed"] is True
        assert checks["toc_headings_match"]["passed"] is True


# ---------------------------------------------------------------------------
# End to end on the real fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def furniture_doc(tmp_project):
    shutil.copyfile(EXAMPLES_ROOT / "furniture_sample.pdf", tmp_project / "input" / "furniture_sample.pdf")
    return "furniture_sample"


def _extract_pdf(doc: str, tmp_project) -> None:
    _run_ok("pdf-triage/scripts/triage.py", "--doc", doc, cwd=tmp_project)
    triage = json.loads(paths.triage_json(doc).read_text())
    text_pages = ",".join(str(p["page_number"]) for p in triage["pages"] if p["tier"] == "text")
    all_pages = ",".join(str(n) for n in range(1, triage["page_count"] + 1))
    _run_ok("extract-text/scripts/extract_text.py", "--doc", doc, "--pages", text_pages, "--body-size", str(triage["body_size"]), cwd=tmp_project)
    _run_ok("extract-images/scripts/extract_images.py", "--doc", doc, "--pages", all_pages, cwd=tmp_project)


class TestFurnitureSampleEndToEnd:
    def test_structure_checks_pass_on_the_real_pipeline_output(self, furniture_doc, tmp_project):
        _extract_pdf(furniture_doc, tmp_project)
        # The extractor agent's describe step (agents/extractor.md) runs
        # before merge in the real loop -- simulated here.
        describe_all_images(furniture_doc, tmp_project)
        _run_ok("assemble-output/scripts/merge.py", "--doc", furniture_doc, cwd=tmp_project)

        # Sanity: the fixture really exercises every check.
        triage = json.loads(paths.triage_json(furniture_doc).read_text())
        assert triage["furniture"]["line_patterns"]
        assert json.loads(paths.toc_json(furniture_doc).read_text())["entries"]

        # The page-4 icon has no printed caption and no text: it carries the
        # recorded no_visible_text flag, never an agent-written caption.
        icon = json.loads(paths.shard_path(furniture_doc, 4, "image").read_text())["elements"]
        icon = [el for el in icon if el.get("kind") == "bitmap"]
        assert len(icon) == 1
        assert icon[0]["no_visible_text"] is True
        assert "caption" not in icon[0]

        for fmt in ("md", "md-tree"):
            _run_ok("assemble-output/scripts/assemble.py", "--doc", furniture_doc, "--format", fmt, cwd=tmp_project)
        md = (paths.output_dir(furniture_doc) / f"{furniture_doc}.md").read_text(encoding="utf-8")
        assert "no_visible_text" not in md
        assert "Synthetic test caption" not in md
        report = json.loads(_run_ok("grade-output/scripts/gates.py", "--doc", furniture_doc, "--format", "md", cwd=tmp_project))
        checks = {c["name"]: c for c in report["checks"]}
        for name in ("furniture_absent", "toc_headings_match", "figures_complete"):
            assert checks[name]["passed"] is True, checks[name]
        assert report["passed"] is True

    def test_figures_complete_fails_before_the_describe_step(self, furniture_doc, tmp_project):
        _extract_pdf(furniture_doc, tmp_project)
        _run_ok("assemble-output/scripts/merge.py", "--doc", furniture_doc, cwd=tmp_project)
        _run_ok("assemble-output/scripts/assemble.py", "--doc", furniture_doc, "--format", "md", cwd=tmp_project)
        result = run_script("grade-output/scripts/gates.py", "--doc", furniture_doc, "--format", "md", cwd=tmp_project)
        checks = {c["name"]: c for c in json.loads(result.stdout)["checks"]}
        figures = checks["figures_complete"]
        assert figures["passed"] is False
        golden = json.loads((EXAMPLES_ROOT / "furniture_golden.json").read_text())
        assert {f["page"] for f in golden["figures"]} <= set(figures["pages"])
        assert all("description" in item["missing"] for item in figures["incomplete"])


class TestSamplePdfEndToEnd:
    """sample.pdf regression: the three new checks pass, or pass trivially
    (no furniture, no TOC), once the describe step has run. Page 5 (the
    scanned page) is left out -- it needs tesseract, and has no images."""

    def test_new_checks_pass_on_sample_pdf(self, pdf_doc, tmp_project):
        _run_ok("pdf-triage/scripts/triage.py", "--doc", pdf_doc, cwd=tmp_project)
        _run_ok("extract-text/scripts/extract_text.py", "--doc", pdf_doc, "--pages", "1,2,3,4", cwd=tmp_project)
        _run_ok("extract-images/scripts/extract_images.py", "--doc", pdf_doc, "--pages", "1,2,3,4,5", cwd=tmp_project)
        describe_all_images(pdf_doc, tmp_project)
        _run_ok("assemble-output/scripts/merge.py", "--doc", pdf_doc, cwd=tmp_project)
        _run_ok("assemble-output/scripts/assemble.py", "--doc", pdf_doc, "--format", "md", cwd=tmp_project)
        report = json.loads(run_script("grade-output/scripts/gates.py", "--doc", pdf_doc, "--format", "md", cwd=tmp_project).stdout)
        checks = {c["name"]: c for c in report["checks"]}
        assert checks["furniture_absent"]["passed"] is True
        assert checks["toc_headings_match"]["passed"] is True
        assert "no TOC entries" in checks["toc_headings_match"]["detail"]
        assert checks["figures_complete"]["passed"] is True, checks["figures_complete"]
