"""Fix wave I1: a boxed or shaded paragraph is a text box, not a figure.

A cluster whose drawings form one axis-aligned rectangle (one `re` item, or
at most 4 axis-aligned lines) and that holds at least one text-layer line
is excluded as `reason: "text_box"`. Its text stays body text. The two
shapes below are the final review's probe shapes: a paragraph inside one
stroked rect, and an ID row (a category label left, an ID right) on one
filled grey bar.
"""

import json
from pathlib import Path

import figures as figures_lib
import fitz  # PyMuPDF
import paths
from conftest import load_script, run_script

gates = load_script("grade-output/scripts/gates.py", "gates_module_text_box")

PAGE_WIDTH, PAGE_HEIGHT = 612.0, 792.0
BOXED_TEXT = "This requirement paragraph sits inside one stroked box"
ID_LABEL = "Requirement"
ID_VALUE = "SYN-REQ-0042"


def _boxed_paragraph(page) -> None:
    page.draw_rect(fitz.Rect(70, 200, 540, 260), width=1)
    page.insert_text((80, 225), BOXED_TEXT, fontsize=11)
    page.insert_text(
        (80, 245), "and continues on a second line of body text.", fontsize=11
    )


def _shaded_id_row(page) -> None:
    page.draw_rect(fitz.Rect(70, 400, 540, 420), color=None, fill=(0.85, 0.85, 0.85))
    page.insert_text((80, 414), ID_LABEL, fontsize=10)
    page.insert_text((420, 414), ID_VALUE, fontsize=10)


def _four_line_box(page) -> None:
    x0, y0, x1, y1 = 70, 500, 540, 560
    for p1, p2 in (
        ((x0, y0), (x1, y0)),
        ((x1, y0), (x1, y1)),
        ((x1, y1), (x0, y1)),
        ((x0, y1), (x0, y0)),
    ):
        page.draw_line(p1, p2, width=1)
    page.insert_text((80, 530), "A note drawn inside four separate lines.", fontsize=11)


def _make_pdf(path: Path, *draw_fns) -> None:
    doc = fitz.open()
    page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    page.insert_text((72, 100), "Ordinary body text above the boxes.", fontsize=11)
    for fn in draw_fns:
        fn(page)
    doc.save(str(path))
    doc.close()


def _detect(path: Path):
    doc = fitz.open(str(path))
    try:
        return figures_lib.detect_figure_regions_with_exclusions(
            doc[0], 1, path, frame_tables=[], frame_drawings=[]
        )
    finally:
        doc.close()


class TestTextBoxDetection:
    def test_boxed_paragraph_is_a_text_box(self, tmp_path):
        path = tmp_path / "boxed.pdf"
        _make_pdf(path, _boxed_paragraph)
        regions, excluded = _detect(path)
        assert regions == []
        assert [r["reason"] for r in excluded] == ["text_box"]

    def test_shaded_id_row_is_a_text_box(self, tmp_path):
        path = tmp_path / "shaded.pdf"
        _make_pdf(path, _shaded_id_row)
        regions, excluded = _detect(path)
        assert regions == []
        assert [r["reason"] for r in excluded] == ["text_box"]

    def test_box_of_four_lines_is_a_text_box(self, tmp_path):
        path = tmp_path / "four_lines.pdf"
        _make_pdf(path, _four_line_box)
        regions, excluded = _detect(path)
        assert regions == []
        assert [r["reason"] for r in excluded] == ["text_box"]

    def test_empty_box_is_still_a_figure(self, tmp_path):
        """No text inside: not a text box (the A5b large-figure rule)."""
        path = tmp_path / "empty_box.pdf"

        def draw(page):
            page.draw_rect(fitz.Rect(150, 300, 450, 500), width=1)

        _make_pdf(path, draw)
        regions, excluded = _detect(path)
        assert len(regions) == 1
        assert not any(r["reason"] == "text_box" for r in excluded)

    def test_two_boxes_with_a_connector_are_still_a_figure(self, tmp_path):
        """A small flow diagram: more than one rectangle, so not a text box."""
        path = tmp_path / "diagram.pdf"

        def draw(page):
            page.draw_rect(fitz.Rect(100, 300, 200, 340), width=1.5)
            page.draw_rect(fitz.Rect(300, 300, 400, 340), width=1.5)
            page.draw_line((200, 320), (300, 320), width=1.5)
            page.insert_text((120, 324), "Start", fontsize=9)
            page.insert_text((320, 324), "End", fontsize=9)

        _make_pdf(path, draw)
        regions, excluded = _detect(path)
        assert len(regions) == 1
        assert not any(r["reason"] == "text_box" for r in excluded)

    def test_box_with_a_curve_is_still_a_figure(self, tmp_path):
        path = tmp_path / "curve.pdf"

        def draw(page):
            page.draw_rect(fitz.Rect(100, 300, 400, 400), width=1)
            page.draw_circle((250, 350), 30, width=1)
            page.insert_text((120, 324), "Label", fontsize=9)

        _make_pdf(path, draw)
        regions, excluded = _detect(path)
        assert len(regions) == 1
        assert not any(r["reason"] == "text_box" for r in excluded)


class TestTextBoxTextStaysBodyText:
    def test_both_probe_shapes_stay_paragraphs(self, tmp_project):
        _make_pdf(
            tmp_project / "input" / "text_boxes.pdf", _boxed_paragraph, _shaded_id_row
        )
        result = run_script(
            "pdf-triage/scripts/triage.py", "--doc", "text_boxes", cwd=tmp_project
        )
        assert result.returncode == 0, result.stderr
        for script in (
            "extract-text/scripts/extract_text.py",
            "extract-images/scripts/extract_images.py",
        ):
            result = run_script(
                script, "--doc", "text_boxes", "--pages", "1", cwd=tmp_project
            )
            assert result.returncode == 0, result.stderr

        text_shard = json.loads(paths.shard_path("text_boxes", 1, "text").read_text())
        body = " ".join(
            e.get("text", "")
            for e in text_shard["elements"]
            if e["type"] == "paragraph"
        )
        assert BOXED_TEXT in body
        assert ID_LABEL in body and ID_VALUE in body

        image_shard = json.loads(paths.shard_path("text_boxes", 1, "image").read_text())
        assert image_shard["elements"] == []
        assert sorted(r["reason"] for r in image_shard["excluded_regions"]) == [
            "text_box",
            "text_box",
        ]


class TestTextBoxIsBenignForTheGate:
    def test_large_text_box_gives_no_warning(self):
        doc_data = {
            "doc": "sample",
            "pages": {
                1: {
                    "page_number": 1,
                    "elements": [],
                    "excluded_regions": [
                        {"bbox": [10.0, 10.0, 600.0, 700.0], "reason": "text_box"}
                    ],
                }
            },
        }
        assert (
            gates.check_large_region_excluded(doc_data, {1: PAGE_WIDTH * PAGE_HEIGHT})
            == []
        )
