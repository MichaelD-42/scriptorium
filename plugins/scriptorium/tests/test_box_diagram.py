"""Follow-up R2: a diagram of separate labelled boxes is a figure.

Each box of such a diagram is one rectangle with text inside, so on its own
it looks like a text box (fix wave I1). `lib/figures.py` first groups the
single-box candidates that sit near each other (at most
`BOX_GROUP_MAX_GAP` apart on one axis and overlapping on the other). A
group, or a single box, with a "Figure n" caption line directly below or
above it (within `BOX_CAPTION_MAX_GAP`) is a figure region. Boxes with no
caption stay text boxes, so the I1 shapes (a boxed paragraph, a shaded ID
row) stay body text.

The shapes are the re-review's probe 2, page 6, rebuilt synthetically.
"""

import json
from pathlib import Path

import figures as figures_lib
import fitz  # PyMuPDF
import paths
from conftest import run_script

PAGE_WIDTH, PAGE_HEIGHT = 612.0, 792.0
ROW_LABELS = ["Sensor", "Controller", "Actuator"]
STACK_LABELS = ["Application", "Middleware", "Hardware"]
ROW_CAPTION = "Figure 2: Components"
STACK_CAPTION = "Figure 3: Layers"
FLOW_CAPTION = "Figure 4: Connected flow"


def _row(page, y: float = 200, caption: str | None = ROW_CAPTION) -> None:
    """Three labelled boxes side by side, 20 pt gaps, no connectors."""
    for i, label in enumerate(ROW_LABELS):
        x = 72 + i * 140
        page.draw_rect(fitz.Rect(x, y, x + 120, y + 40), width=1)
        page.insert_text((x + 10, y + 24), label, fontsize=9)
    if caption:
        page.insert_text((72, y + 66), caption, fontsize=10)


def _stack(page, y: float = 400, caption: str | None = STACK_CAPTION) -> None:
    """Three labelled boxes stacked, 6 pt gaps."""
    for i, label in enumerate(STACK_LABELS):
        by = y + i * 36
        page.draw_rect(fitz.Rect(72, by, 372, by + 30), width=1)
        page.insert_text((82, by + 19), label, fontsize=9)
    if caption:
        page.insert_text((72, y + 128), caption, fontsize=10)


def _flow(page, y: float = 600) -> None:
    """The control: three boxes joined by lines."""
    for i, label in enumerate(["In", "Proc", "Out"]):
        x = 72 + i * 150
        page.draw_rect(fitz.Rect(x, y, x + 100, y + 40), width=1)
        page.insert_text((x + 10, y + 24), label, fontsize=9)
        if i:
            page.draw_line((x - 50, y + 20), (x, y + 20), width=1)
    page.insert_text((72, y + 70), FLOW_CAPTION, fontsize=10)


def _make_pdf(path: Path, *draw_fns) -> None:
    doc = fitz.open()
    page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    page.insert_text((72, 100), "Ordinary body text above the diagrams.", fontsize=11)
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


def _reasons(excluded) -> list[str]:
    return [r["reason"] for r in excluded]


class TestBoxGroupDetection:
    def test_row_of_boxes_with_a_caption_is_one_region(self, tmp_path):
        path = tmp_path / "row.pdf"
        _make_pdf(path, _row)
        regions, excluded = _detect(path)
        assert len(regions) == 1
        assert "text_box" not in _reasons(excluded)
        x0, y0, x1, y1 = regions[0]["bbox"]
        assert x0 <= 72 and x1 >= 72 + 2 * 140 + 120 and y0 <= 200 and y1 >= 240

    def test_stack_of_boxes_with_a_caption_is_one_region(self, tmp_path):
        path = tmp_path / "stack.pdf"
        _make_pdf(path, _stack)
        regions, excluded = _detect(path)
        assert len(regions) == 1
        assert "text_box" not in _reasons(excluded)
        _x0, y0, _x1, y1 = regions[0]["bbox"]
        assert y0 <= 400 and y1 >= 400 + 2 * 36 + 30

    def test_single_box_with_a_caption_is_a_region(self, tmp_path):
        path = tmp_path / "single.pdf"

        def draw(page):
            page.draw_rect(fitz.Rect(72, 300, 372, 340), width=1)
            page.insert_text((82, 324), "Controller", fontsize=9)
            page.insert_text((72, 360), "Figure 6: One block", fontsize=10)

        _make_pdf(path, draw)
        regions, excluded = _detect(path)
        assert len(regions) == 1
        assert "text_box" not in _reasons(excluded)

    def test_row_without_a_caption_stays_text_boxes(self, tmp_path):
        path = tmp_path / "row_plain.pdf"
        _make_pdf(path, lambda page: _row(page, caption=None))
        regions, excluded = _detect(path)
        assert regions == []
        assert _reasons(excluded) == ["text_box"] * 3

    def test_caption_too_far_away_keeps_text_boxes(self, tmp_path):
        """A caption more than BOX_CAPTION_MAX_GAP below the boxes does not
        count."""
        path = tmp_path / "row_far.pdf"

        def draw(page):
            _row(page, caption=None)
            page.insert_text((72, 240 + 50 + 8), ROW_CAPTION, fontsize=10)

        _make_pdf(path, draw)
        regions, excluded = _detect(path)
        assert regions == []
        assert _reasons(excluded) == ["text_box"] * 3

    def test_table_caption_does_not_make_a_figure(self, tmp_path):
        path = tmp_path / "row_table_caption.pdf"
        _make_pdf(path, lambda page: _row(page, caption="Table 2: Limits"))
        regions, excluded = _detect(path)
        assert regions == []
        assert _reasons(excluded) == ["text_box"] * 3

    def test_boxes_far_apart_are_not_grouped(self, tmp_path):
        """Only the box next to the caption becomes a figure; a boxed
        paragraph further up the page stays a text box."""
        path = tmp_path / "apart.pdf"

        def draw(page):
            page.draw_rect(fitz.Rect(70, 150, 540, 190), width=1)
            page.insert_text((80, 174), "A boxed requirement paragraph.", fontsize=11)
            page.draw_rect(fitz.Rect(72, 300, 372, 340), width=1)
            page.insert_text((82, 324), "Controller", fontsize=9)
            page.insert_text((72, 360), "Figure 6: One block", fontsize=10)

        _make_pdf(path, draw)
        regions, excluded = _detect(path)
        assert len(regions) == 1
        assert regions[0]["bbox"][1] > 250
        assert _reasons(excluded) == ["text_box"]


class TestProbePageEndToEnd:
    """Probe 2, page 6: the row, the stack and the connected flow on one
    page give three captioned vector images; the box labels are figure
    text, not body paragraphs."""

    def test_three_captioned_images(self, tmp_project):
        _make_pdf(tmp_project / "input" / "box_diagrams.pdf", _row, _stack, _flow)
        result = run_script(
            "pdf-triage/scripts/triage.py", "--doc", "box_diagrams", cwd=tmp_project
        )
        assert result.returncode == 0, result.stderr
        for script in (
            "extract-text/scripts/extract_text.py",
            "extract-images/scripts/extract_images.py",
        ):
            result = run_script(
                script, "--doc", "box_diagrams", "--pages", "1", cwd=tmp_project
            )
            assert result.returncode == 0, result.stderr

        image_shard = json.loads(
            paths.shard_path("box_diagrams", 1, "image").read_text()
        )
        images = [e for e in image_shard["elements"] if e["type"] == "image"]
        assert [e.get("caption") for e in images] == [
            ROW_CAPTION,
            STACK_CAPTION,
            FLOW_CAPTION,
        ]
        assert "text_box" not in _reasons(image_shard["excluded_regions"])
        assert images[0]["figure_text"].split("\n") == ROW_LABELS
        assert images[1]["figure_text"].split("\n") == STACK_LABELS

        text_shard = json.loads(paths.shard_path("box_diagrams", 1, "text").read_text())
        body = " ".join(e.get("text", "") for e in text_shard["elements"])
        for label in ROW_LABELS + STACK_LABELS:
            assert label not in body
        for caption in (ROW_CAPTION, STACK_CAPTION, FLOW_CAPTION):
            assert caption not in body
