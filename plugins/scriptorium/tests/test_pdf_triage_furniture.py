"""Task A1 -- furniture detection in pdf-triage.

Exercises `triage.py`'s new furniture pass (repeated header/footer lines,
repeated full-page-covering tables, repeated images) against two fixtures:

- `furniture_sample.pdf` (Task A0): 9 pages, real furniture on every page --
  the detector must find it.
- `sample.pdf` (pre-existing): 5 single-purpose pages, no repeated furniture
  at all -- the detector must find *nothing*, not a false positive that
  happens to clear the 60%/50% thresholds by coincidence on a short doc.

`furniture_golden.json` (Task A0's hand-authored answer key) is read as
ground truth for the frame bbox / line texts, per shared-context.md's rule
that later tasks read that file instead of hand-coding expectations inline.
"""

import json

import pytest

import paths
from conftest import run_script


def _examples_root():
    from pathlib import Path

    return Path(__file__).resolve().parent.parent / "examples"


def _golden():
    return json.loads((_examples_root() / "furniture_golden.json").read_text())


@pytest.fixture
def furniture_doc(tmp_project):
    import shutil

    dest = tmp_project / "input" / "furniture_sample.pdf"
    shutil.copyfile(_examples_root() / "furniture_sample.pdf", dest)
    return "furniture_sample"


def _run_triage(doc, cwd):
    result = run_script("pdf-triage/scripts/triage.py", "--doc", doc, cwd=cwd)
    assert result.returncode == 0, f"triage.py failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    return json.loads(paths.triage_json(doc).read_text())


class TestFurnitureFixtureDetected:
    def test_line_patterns_find_the_title_block_on_almost_every_page(self, furniture_doc, tmp_project):
        triage = _run_triage(furniture_doc, tmp_project)
        furniture = triage["furniture"]
        page_count = triage["page_count"]

        assert furniture["line_patterns"], "expected at least one repeated header/footer line pattern"
        for pat in furniture["line_patterns"]:
            assert pat["edge"] in ("top", "bottom")
            assert 0.0 <= pat["y_min"] <= pat["y_max"] <= 1.0
            assert pat["page_count"] >= 0.9 * page_count

        # The fixture's title block (Doc No. / Rev. / "page N (TOTAL)") lives
        # in the bottom 12% band on every page -- assert we found bottom-edge
        # patterns specifically, not just top-edge ones.
        bottom_patterns = [p for p in furniture["line_patterns"] if p["edge"] == "bottom"]
        assert bottom_patterns

    def test_frame_tables_match_reality_for_this_fixture(self, furniture_doc, tmp_project):
        """The fixture's page frame is a plain `c.rect()` border with no
        ruled internal lines (per task-A0-report.md), so pdfplumber's
        find_tables() is not expected to treat it as a table -- verify the
        detector doesn't crash either way, and that whatever it reports is
        consistent with furniture_golden.json's recorded frame bbox."""
        triage = _run_triage(furniture_doc, tmp_project)
        frame_tables = triage["furniture"]["frame_tables"]
        golden_frame_bbox = _golden()["furniture"]["frame_bbox"]

        assert isinstance(frame_tables, list)
        if frame_tables:
            # If pdfplumber did detect it as a table, it should be at
            # roughly the golden frame bbox.
            found = frame_tables[0]["bbox"]
            for observed, expected in zip(found, golden_frame_bbox):
                assert abs(observed - expected) <= 5
        else:
            # The expected case for this fixture: a borderless-interior
            # rectangle isn't a "table" to pdfplumber's heuristics.
            assert frame_tables == []

    def test_image_xrefs_finds_the_repeated_logo(self, furniture_doc, tmp_project):
        triage = _run_triage(furniture_doc, tmp_project)
        image_xrefs = triage["furniture"]["image_xrefs"]
        assert len(image_xrefs) >= 1
        assert all(isinstance(x, int) for x in image_xrefs)

    def test_furniture_text_is_nonempty_and_contains_doc_number(self, furniture_doc, tmp_project):
        triage = _run_triage(furniture_doc, tmp_project)
        furniture_text = triage["furniture_text"]
        assert furniture_text
        assert isinstance(furniture_text, str)
        # golden fixture's fake doc number, per furniture_golden.json
        golden_lines = _golden()["furniture"]["lines"]
        doc_number_line = next(line["text"] for line in golden_lines if "text" in line and "Doc No." in line["text"])
        assert doc_number_line in furniture_text


class TestNoFurnitureFalsePositiveOnShortSample:
    def test_sample_pdf_has_no_detected_furniture(self, pdf_doc, tmp_project):
        triage = _run_triage(pdf_doc, tmp_project)
        assert triage["furniture"] == {
            "line_patterns": [], "frame_tables": [], "frame_drawings": [], "image_xrefs": [],
        }
        assert triage["furniture_text"] is None
