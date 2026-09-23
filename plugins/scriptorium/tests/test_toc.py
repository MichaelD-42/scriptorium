"""Task A3 -- TOC detection and parsing.

Exercises `lib/toc.py`'s two strategies (PDF outline via
`document.get_toc()`, and printed-TOC-page detection/parsing as a fallback),
`triage.py`'s new `work/<doc>/toc.json` output and per-page `role: "toc"`
marking, `extract_text.py`/`extract_images.py`'s short-circuit for a TOC
page, and `gates.py`'s `no_empty_pages` allowance for a page whose merged
shard carries `skipped: "toc"`.

`furniture_sample.pdf` (Task A0) has a real 2-page printed TOC (pages 2-3,
no PDF outline) -- `furniture_golden.json`'s `toc` section is read as ground
truth per shared-context.md's rule, rather than hand-copying expected values.
`sample.pdf` (pre-existing, no TOC, no outline) is the regression fixture:
it must behave identically to before this task.
"""

import json
import shutil
from pathlib import Path

import fitz  # PyMuPDF
import pytest

import paths
import toc  # lib/toc.py -- importable directly, LIB_ROOT is on sys.path via conftest
from conftest import run_script

EXAMPLES_ROOT = Path(__file__).resolve().parent.parent / "examples"


def _golden() -> dict:
    return json.loads((EXAMPLES_ROOT / "furniture_golden.json").read_text())


def _level_from_number(number: str) -> int:
    return number.count(".") + 1


def _expected_entries() -> list[dict]:
    """furniture_golden.json's toc entries, stripped down to the schema
    lib/toc.py actually produces (no `split_line` -- that's golden-JSON-only
    ground-truth metadata, not part of the entry shape this task defines),
    with `level` recomputed from the number's dot-depth rather than taken
    from golden's `level` field.

    These differ for exactly one entry: "2.1.2" is golden `level: 4`
    because TOC_ENTRIES (generate_furniture_fixture.py) deliberately uses it
    as a *heading*-classification edge case -- "a heading printed at the
    smallest of the four bold sizes used across this document" -- not
    because a dot-depth reading of "2.1.2" is 4. Per the brief, this task's
    printed-TOC parser derives level purely from the number's dot-depth
    ("that's a later task's concern for heading classification, not this
    one"), which gives "2.1.2" level 3 (two dots), matching "2.1.1"
    alongside it. See task-A3-report.md for this documented divergence."""
    return [
        {"number": e["number"], "title": e["title"], "page": e["page"], "level": _level_from_number(e["number"])}
        for e in _golden()["toc"]["entries"]
    ]


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


class TestPrintedTocDetectionAndParsing:
    """Exercises lib/toc.py directly against furniture_sample.pdf, without
    going through triage.py."""

    def test_finds_the_two_toc_pages(self):
        with fitz.open(EXAMPLES_ROOT / "furniture_sample.pdf") as document:
            entries, toc_pages = toc.detect_toc(document)
        assert toc_pages == _golden()["toc"]["pages"]

    def test_parses_all_entries_matching_the_golden_answer_key(self):
        with fitz.open(EXAMPLES_ROOT / "furniture_sample.pdf") as document:
            entries, _toc_pages = toc.detect_toc(document)
        assert entries == _expected_entries()

    def test_at_least_one_entry_came_from_the_split_number_and_title_case(self):
        """furniture_golden.json marks entries 2.1.1/2.1.2/3.1 as
        `split_line: true` -- printed as the number alone on one line, then
        "title .... page" on the next. Confirm the parser recovered at
        least one of them correctly (not just by accident of the full-line
        case elsewhere)."""
        golden = _golden()
        split_entries = {
            (e["number"], e["title"]) for e in golden["toc"]["entries"] if e.get("split_line")
        }
        assert split_entries  # sanity: the fixture is supposed to have some

        with fitz.open(EXAMPLES_ROOT / "furniture_sample.pdf") as document:
            entries, _toc_pages = toc.detect_toc(document)
        found = {(e["number"], e["title"]) for e in entries}
        assert split_entries <= found

    def test_no_toc_pages_and_no_entries_on_sample_pdf(self, pdf_doc, tmp_project):
        """sample.pdf has no printed TOC and no outline -- the detector must
        report nothing found, not a false positive."""
        with fitz.open(tmp_project / "input" / "sample.pdf") as document:
            entries, toc_pages = toc.detect_toc(document)
        assert entries == []
        assert toc_pages == []


class TestOutlineTocTakesPriority:
    """None of the existing fixtures have a real PDF outline (confirmed:
    furniture_sample.pdf's TOC is a printed page, not `document.get_toc()`
    entries) -- build a tiny outline-only PDF inline with PyMuPDF's own
    `set_toc()` API instead of touching either already-reviewed fixture."""

    def _make_outline_pdf(self, tmp_path: Path) -> Path:
        out_path = tmp_path / "outline_only.pdf"
        document = fitz.open()
        document.new_page()
        document.new_page()
        document.new_page()
        document.set_toc([
            [1, "1 Introduction", 1],
            [2, "1.1 Overview", 2],
            [1, "Appendix", 3],  # no leading number -- exercises the "leave number null" case
        ])
        document.save(out_path)
        document.close()
        return out_path

    def test_outline_entries_used_directly_no_printed_toc_page_scan(self, tmp_path):
        pdf_path = self._make_outline_pdf(tmp_path)
        with fitz.open(pdf_path) as document:
            entries, toc_pages = toc.detect_toc(document)

        assert entries == [
            {"number": "1", "title": "Introduction", "page": 1, "level": 1},
            {"number": "1.1", "title": "Overview", "page": 2, "level": 2},
            {"number": None, "title": "Appendix", "page": 3, "level": 1},
        ]
        # Outline entries don't correspond to a rendered "TOC page" -- no
        # page should be marked as one.
        assert toc_pages == []


def _build_inline_pdf(tmp_path: Path, name: str, pages_lines: list[list[str]]) -> Path:
    """A tiny inline-built PDF (via PyMuPDF's own text-insertion API, same
    "safer choice" pattern as TestOutlineTocTakesPriority's outline-only PDF)
    with one page per entry in `pages_lines`, each page's lines drawn
    top-to-bottom -- used to probe near-miss/deep-in-document cases without
    touching either already-reviewed fixture (furniture_sample.pdf /
    sample.pdf)."""
    out_path = tmp_path / name
    document = fitz.open()
    for lines in pages_lines:
        page = document.new_page()
        y = 72
        for line in lines:
            page.insert_text((72, y), line, fontsize=11)
            y += 14
    document.save(out_path)
    document.close()
    return out_path


class TestPrintedTocFalsePositiveGuards:
    """Task A3 fix round: a false positive here is silent, gate-passing data
    loss (a role="toc" page's extraction is skipped and no_empty_pages
    exempts it), so both the line-count threshold and the front-of-document
    scan bound need their own coverage -- not just the "some real TOC gets
    detected" positive cases above."""

    def test_dot_leader_pricing_table_below_threshold_is_not_detected_as_toc(self, tmp_path):
        """A pricing/spec table using dot-leader alignment for its price
        column -- exactly the shape a real RFQ document contains -- with 8
        dot-leader lines: comfortably more than the old (unsafe)
        MIN_QUALIFYING_LINES of 3, comfortably below the current 15. Must
        NOT be detected as a TOC page."""
        pricing_lines = [f"Part No. PN-{1000 + i} .......... {10 + i}" for i in range(8)]
        pdf_path = _build_inline_pdf(tmp_path, "pricing_table_near_miss.pdf", [pricing_lines])

        with fitz.open(pdf_path) as document:
            entries, toc_pages = toc.detect_toc(document)

        assert toc_pages == []
        assert entries == []

    def test_dot_leader_table_past_the_front_of_document_bound_is_not_detected(self, tmp_path):
        """A page with 20 dot-leader lines -- comfortably clearing
        MIN_QUALIFYING_LINES on pattern alone -- placed just past
        toc.TOC_SEARCH_MAX_PAGES. Must NOT be detected: a TOC is always near
        the front, so a coincidental pattern match deep in the document must
        never be accepted regardless of how many lines it has."""
        filler_pages = [[f"Body paragraph text on filler page {i}."] for i in range(1, toc.TOC_SEARCH_MAX_PAGES + 1)]
        dense_lines = [f"{i + 1} Item {i:03d} .......... {100 + i}" for i in range(20)]
        pdf_path = _build_inline_pdf(tmp_path, "dense_table_past_bound.pdf", filler_pages + [dense_lines])

        with fitz.open(pdf_path) as document:
            entries, toc_pages = toc.detect_toc(document)

        assert toc_pages == []
        assert entries == []

    def test_same_dense_table_near_the_front_is_still_detected(self, tmp_path):
        """Control for the previous test: the same pattern-qualifying page,
        placed within the bound instead of past it, IS detected -- proving
        the bound (not something else about the content) is what blocks the
        deep-in-document case."""
        dense_lines = [f"{i + 1} Item {i:03d} .......... {100 + i}" for i in range(20)]
        pdf_path = _build_inline_pdf(tmp_path, "dense_table_within_bound.pdf", [dense_lines])

        with fitz.open(pdf_path) as document:
            entries, toc_pages = toc.detect_toc(document)

        assert toc_pages == [1]
        assert len(entries) == 20


class TestTriageWritesTocJsonAndMarksRole:
    def test_toc_json_written_matching_parsed_entries(self, furniture_doc, tmp_project):
        triage = _run_triage(furniture_doc, tmp_project)
        toc_path = paths.toc_json(furniture_doc)
        assert toc_path.exists()
        toc_data = json.loads(toc_path.read_text())
        assert toc_data["entries"] == _expected_entries()

    def test_toc_pages_marked_role_toc_in_triage_json(self, furniture_doc, tmp_project):
        triage = _run_triage(furniture_doc, tmp_project)
        golden_toc_pages = set(_golden()["toc"]["pages"])
        for page in triage["pages"]:
            if page["page_number"] in golden_toc_pages:
                assert page.get("role") == "toc", f"page {page['page_number']} should be marked role=toc"
            else:
                assert "role" not in page, f"page {page['page_number']} should have no role key"


class TestSamplePdfRegressionNoToc:
    def test_no_toc_json_content_and_no_role_marked(self, pdf_doc, tmp_project):
        triage = _run_triage(pdf_doc, tmp_project)
        toc_path = paths.toc_json(pdf_doc)
        assert toc_path.exists()
        toc_data = json.loads(toc_path.read_text())
        assert toc_data["entries"] == []
        for page in triage["pages"]:
            assert "role" not in page


class TestExtractorsSkipTocPages:
    def test_extract_text_writes_empty_skipped_shard_for_a_toc_page(self, furniture_doc, tmp_project):
        triage = _run_triage(furniture_doc, tmp_project)
        toc_page = _golden()["toc"]["pages"][0]
        _run_ok(
            "extract-text/scripts/extract_text.py", "--doc", furniture_doc,
            "--pages", str(toc_page), "--body-size", str(triage["body_size"]),
            cwd=tmp_project,
        )
        shard = json.loads(paths.shard_path(furniture_doc, toc_page, "text").read_text())
        assert shard["elements"] == []
        assert shard["skipped"] == "toc"

    def test_extract_images_writes_empty_skipped_shard_for_a_toc_page(self, furniture_doc, tmp_project):
        triage = _run_triage(furniture_doc, tmp_project)
        toc_page = _golden()["toc"]["pages"][0]
        _run_ok(
            "extract-images/scripts/extract_images.py", "--doc", furniture_doc,
            "--pages", str(toc_page), cwd=tmp_project,
        )
        shard = json.loads(paths.shard_path(furniture_doc, toc_page, "image").read_text())
        assert shard["elements"] == []
        assert shard["skipped"] == "toc"

    def test_non_toc_page_still_extracted_normally(self, furniture_doc, tmp_project):
        """Sanity check: the short-circuit only fires for pages triage
        actually marked role=toc -- a body page passed via --pages is
        unaffected."""
        triage = _run_triage(furniture_doc, tmp_project)
        content_page = _golden()["table"]["content_page"]
        _run_ok(
            "extract-text/scripts/extract_text.py", "--doc", furniture_doc,
            "--pages", str(content_page), "--body-size", str(triage["body_size"]),
            cwd=tmp_project,
        )
        shard = json.loads(paths.shard_path(furniture_doc, content_page, "text").read_text())
        assert shard.get("skipped") is None
        assert shard["elements"]

    def test_toc_page_short_circuit_works_even_mixed_into_a_multi_page_batch(self, furniture_doc, tmp_project):
        """The script doesn't get to choose which pages it's asked about --
        a --pages batch that happens to include a TOC page must still
        short-circuit correctly just for that page."""
        triage = _run_triage(furniture_doc, tmp_project)
        toc_pages = _golden()["toc"]["pages"]
        content_page = _golden()["table"]["content_page"]
        pages = sorted(set(toc_pages) | {content_page})
        _run_ok(
            "extract-text/scripts/extract_text.py", "--doc", furniture_doc,
            "--pages", ",".join(map(str, pages)), "--body-size", str(triage["body_size"]),
            cwd=tmp_project,
        )
        for p in toc_pages:
            shard = json.loads(paths.shard_path(furniture_doc, p, "text").read_text())
            assert shard["elements"] == []
            assert shard["skipped"] == "toc"
        shard = json.loads(paths.shard_path(furniture_doc, content_page, "text").read_text())
        assert shard.get("skipped") is None


class TestGateAcceptsSkippedTocPages:
    def test_no_empty_pages_passes_for_a_toc_skipped_page(self):
        from conftest import load_script

        gates = load_script("grade-output/scripts/gates.py", "gates_module_toc_test")
        pages = {
            1: {"page_number": 1, "elements": [], "skipped": "toc"},
            2: {"page_number": 2, "elements": [{"type": "paragraph", "text": "x"}]},
        }
        result = gates.check_no_empty_pages({"doc": "furniture_sample", "pages": pages})
        assert result["passed"] is True

    def test_no_empty_pages_still_fails_for_a_genuinely_empty_non_toc_page(self):
        from conftest import load_script

        gates = load_script("grade-output/scripts/gates.py", "gates_module_toc_test2")
        pages = {
            1: {"page_number": 1, "elements": []},
            2: {"page_number": 2, "elements": [{"type": "paragraph", "text": "x"}]},
        }
        result = gates.check_no_empty_pages({"doc": "furniture_sample", "pages": pages})
        assert result["passed"] is False
        assert "[1]" in result["detail"]

    def test_merged_elements_json_skipped_toc_page_passes_the_gate_end_to_end(self, furniture_doc, tmp_project):
        """The real pipeline path: triage -> extract-text/-images -> merge
        -> gates, confirming `skipped` really does survive merge_shards()
        through to the merged page dict gates.py reads."""
        triage = _run_triage(furniture_doc, tmp_project)
        pages = list(range(1, triage["page_count"] + 1))
        _run_ok(
            "extract-text/scripts/extract_text.py", "--doc", furniture_doc,
            "--pages", ",".join(map(str, pages)), "--body-size", str(triage["body_size"]),
            cwd=tmp_project,
        )
        _run_ok(
            "extract-images/scripts/extract_images.py", "--doc", furniture_doc,
            "--pages", ",".join(map(str, pages)), cwd=tmp_project,
        )
        _run_ok("assemble-output/scripts/merge.py", "--doc", furniture_doc, cwd=tmp_project)

        import elements as elements_lib

        doc_data = elements_lib.load_doc(paths.elements_json(furniture_doc))
        for toc_page in _golden()["toc"]["pages"]:
            page = doc_data["pages"][toc_page]
            assert page["elements"] == []
            assert page["skipped"] == "toc"

        gates = load_script_gates()
        result = gates.check_no_empty_pages(doc_data)
        assert result["passed"] is True, result["detail"]


def load_script_gates():
    from conftest import load_script

    return load_script("grade-output/scripts/gates.py", "gates_module_toc_e2e")
