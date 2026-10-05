"""Fix wave I2: TOC parsing must not drop entries silently.

Three gaps closed here, each on a small inline-built PDF (so the A0-A9
fixture assertions do not change):

1. A last TOC page with fewer than MIN_QUALIFYING_LINES leader lines is
   accepted when it directly follows a detected TOC page and its leader
   lines (plus number-only lines) are a large enough share of the page.
2. A title that wraps onto a second line is joined into one entry.
3. A leader line that gives no entry goes to `toc.json["unparsed"]`, and
   `toc_headings_match` fails while `unparsed` is not empty.
"""

import json
from pathlib import Path

import fitz  # PyMuPDF
import paths
import toc
from conftest import load_script, run_script

gates = load_script("grade-output/scripts/gates.py", "gates_module_toc_robust")


def _build_pdf(path: Path, pages_lines: list[list[str]]) -> Path:
    document = fitz.open()
    for lines in pages_lines:
        page = document.new_page()
        y = 60
        for line in lines:
            page.insert_text((72, y), line, fontsize=10)
            y += 13
    document.save(path)
    document.close()
    return path


def _entry_line(i: int) -> str:
    return f"{i} Section title {i:03d} .......... {10 + i}"


FULL_PAGE = [_entry_line(i) for i in range(1, 21)]  # 20 leader lines
PARTIAL_PAGE = [_entry_line(i) for i in range(21, 26)]  # 5 leader lines
BODY_PAGE = ["1 Section title 001", "Body text of the first section."]


class TestContinuationPage:
    def test_short_last_toc_page_is_accepted(self, tmp_path):
        pdf = _build_pdf(
            tmp_path / "partial.pdf",
            [["Cover page"], FULL_PAGE, PARTIAL_PAGE, BODY_PAGE],
        )
        with fitz.open(pdf) as document:
            entries, toc_pages = toc.detect_toc(document)
        assert toc_pages == [2, 3]
        assert [e["number"] for e in entries] == [str(i) for i in range(1, 26)]

    def test_short_page_that_is_mostly_prose_is_not_accepted(self, tmp_path):
        prose = [f"An ordinary sentence of body text, line {i}." for i in range(20)]
        mixed = PARTIAL_PAGE[:3] + prose  # 3 leader lines out of 23 lines
        pdf = _build_pdf(tmp_path / "mixed.pdf", [FULL_PAGE, mixed])
        with fitz.open(pdf) as document:
            _entries, toc_pages = toc.detect_toc(document)
        assert toc_pages == [1]

    def test_short_page_with_too_few_leader_lines_is_not_accepted(self, tmp_path):
        pdf = _build_pdf(tmp_path / "two_lines.pdf", [FULL_PAGE, PARTIAL_PAGE[:2]])
        with fitz.open(pdf) as document:
            _entries, toc_pages = toc.detect_toc(document)
        assert toc_pages == [1]

    def test_short_page_alone_never_starts_a_toc(self, tmp_path):
        pdf = _build_pdf(
            tmp_path / "alone.pdf", [["Cover page"], PARTIAL_PAGE, BODY_PAGE]
        )
        with fitz.open(pdf) as document:
            entries, toc_pages = toc.detect_toc(document)
        assert toc_pages == []
        assert entries == []


class TestWrappedTitles:
    def test_number_line_then_two_title_lines(self):
        lines = ["2.2", "A wrapped title that", "continues here .......... 7"]
        entries, unparsed = toc.parse_toc_page_lines(lines)
        assert entries == [
            {
                "number": "2.2",
                "title": "A wrapped title that continues here",
                "page": 7,
                "level": 2,
            }
        ]
        assert unparsed == []

    def test_numbered_title_line_then_leader_line(self):
        lines = ["2.3 Another long title", "that wraps .......... 8"]
        entries, unparsed = toc.parse_toc_page_lines(lines)
        assert entries == [
            {
                "number": "2.3",
                "title": "Another long title that wraps",
                "page": 8,
                "level": 2,
            }
        ]
        assert unparsed == []

    def test_one_line_and_split_entries_are_unchanged(self):
        lines = ["1 Introduction .......... 4", "2", "Scope .......... 5"]
        entries, unparsed = toc.parse_toc_page_lines(lines)
        assert entries == [
            {"number": "1", "title": "Introduction", "page": 4, "level": 1},
            {"number": "2", "title": "Scope", "page": 5, "level": 1},
        ]
        assert unparsed == []

    def test_a_wrap_never_swallows_the_next_entry(self):
        lines = ["3.1 Title with no leader", "3.2 Next entry .......... 9"]
        entries, unparsed = toc.parse_toc_page_lines(lines)
        assert entries == [
            {"number": "3.2", "title": "Next entry", "page": 9, "level": 2}
        ]
        # Follow-up R9: a numbered line that gives no entry is unparsed.
        assert unparsed == ["3.1 Title with no leader"]

    def test_wrapped_title_on_a_real_toc_page(self, tmp_path):
        page = FULL_PAGE[:18] + [
            "19.1",
            "A wrapped title that",
            "continues here .......... 40",
        ]
        pdf = _build_pdf(tmp_path / "wrapped.pdf", [page])
        with fitz.open(pdf) as document:
            entries, _toc_pages = toc.detect_toc(document)
        assert entries[-1] == {
            "number": "19.1",
            "title": "A wrapped title that continues here",
            "page": 40,
            "level": 2,
        }


class TestUnparsed:
    def test_leader_line_without_a_number_is_unparsed(self):
        lines = ["Foreword .......... 3", "1 Introduction .......... 4"]
        entries, unparsed = toc.parse_toc_page_lines(lines)
        assert [e["number"] for e in entries] == ["1"]
        assert unparsed == ["Foreword .......... 3"]

    def test_detect_toc_with_unparsed(self, tmp_path):
        page = ["Foreword .......... 3"] + FULL_PAGE
        pdf = _build_pdf(tmp_path / "unparsed.pdf", [page])
        with fitz.open(pdf) as document:
            entries, toc_pages, unparsed = toc.detect_toc_with_unparsed(document)
        assert toc_pages == [1]
        assert len(entries) == 20
        assert unparsed == ["Foreword .......... 3"]

    def test_triage_writes_unparsed_to_toc_json(self, tmp_project):
        page = ["Foreword .......... 3"] + FULL_PAGE
        _build_pdf(tmp_project / "input" / "unparsed_doc.pdf", [page, BODY_PAGE])
        result = run_script(
            "pdf-triage/scripts/triage.py", "--doc", "unparsed_doc", cwd=tmp_project
        )
        assert result.returncode == 0, result.stderr
        toc_data = json.loads(paths.toc_json("unparsed_doc").read_text())
        assert toc_data["unparsed"] == ["Foreword .......... 3"]
        assert len(toc_data["entries"]) == 20

    def test_triage_writes_empty_unparsed_when_all_lines_parse(self, tmp_project):
        _build_pdf(tmp_project / "input" / "clean_doc.pdf", [FULL_PAGE, BODY_PAGE])
        result = run_script(
            "pdf-triage/scripts/triage.py", "--doc", "clean_doc", cwd=tmp_project
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(paths.toc_json("clean_doc").read_text())["unparsed"] == []


GATE_ENTRIES = ({"number": "1", "title": "Intro", "page": 1, "level": 1},)


class TestGateFailsOnUnparsed:
    def _doc_data(self) -> dict:
        return {
            "doc": "d",
            "pages": {
                1: {
                    "page_number": 1,
                    "elements": [{"type": "heading", "level": 1, "text": "1 Intro"}],
                }
            },
        }

    def test_passes_without_unparsed(self):
        result = gates.check_toc_headings_match(
            self._doc_data(), list(GATE_ENTRIES), unparsed=[]
        )
        assert result["passed"] is True

    def test_fails_and_lists_the_unparsed_lines(self):
        result = gates.check_toc_headings_match(
            self._doc_data(), list(GATE_ENTRIES), unparsed=["Foreword .......... 3"]
        )
        assert result["passed"] is False
        assert result["unparsed"] == ["Foreword .......... 3"]
        assert "Foreword .......... 3" in result["detail"]

    def test_fails_on_unparsed_even_with_no_entries(self):
        result = gates.check_toc_headings_match(
            self._doc_data(), [], unparsed=["Foreword .......... 3"]
        )
        assert result["passed"] is False
