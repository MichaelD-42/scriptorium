"""Re-review 2 M2: the split-caption join stays inside the caption's column.

Follow-up R17 joins a lone caption number ("Figure 3") with the text line to
its right at the same y. With no limit, a two-column page joined the number
with the right column's body line, and that sentence left the body. Now
`figures._join_split_captions` takes a partner only when it starts at most
CAPTION_JOIN_MAX_GAP (72 pt) to the right of the number, and is in the
caption's column: it overlaps the image's x-range, or another text line on
the page bridges the gap between the two (so no column gutter lies
between them).
"""

import json

import figures as figures_lib
import fitz  # PyMuPDF
import paths
from conftest import run_script

W, H = 595.0, 842.0


def _line(text: str, x0: float, x1: float, y: float = 200.0) -> dict:
    return {"text": text, "bbox": [x0, y, x1, y + 10.0]}


class TestJoinRule:
    def test_constant(self):
        assert figures_lib.CAPTION_JOIN_MAX_GAP == 72.0

    def test_partner_over_the_image_is_joined(self):
        lines = [_line("Fig. 2", 100, 130), _line("Synthetic title", 160, 260)]
        joined = figures_lib._join_split_captions(lines, image_bbox=[90, 100, 400, 190])
        assert [line["text"] for line in joined] == ["Fig. 2 Synthetic title"]

    def test_partner_beyond_the_gap_is_not_joined(self):
        lines = [_line("Fig. 2", 100, 130), _line("Synthetic title", 203, 300)]
        joined = figures_lib._join_split_captions(lines, image_bbox=[90, 100, 400, 190])
        assert [line["text"] for line in joined] == ["Fig. 2", "Synthetic title"]

    def test_partner_outside_the_image_needs_a_bridging_line(self):
        caption, partner = (
            _line("Figure 3", 200, 243),
            _line("Right column text", 300, 500),
        )
        image = [50, 100, 260, 190]
        assert (
            len(figures_lib._join_split_captions([caption, partner], image_bbox=image))
            == 2
        )
        bridge = _line("A full width body line above", 60, 540, y=80.0)
        joined = figures_lib._join_split_captions(
            [bridge, caption, partner], image_bbox=image
        )
        assert "Figure 3 Right column text" in [line["text"] for line in joined]


def _two_column(page) -> None:
    page.insert_text((60, 100), "Left column text above.", fontsize=10)
    page.insert_text((300, 100), "Right column text above.", fontsize=10)
    page.draw_rect(fitz.Rect(60, 140, 140, 190), width=1)
    page.draw_rect(fitz.Rect(170, 140, 250, 190), width=1)
    page.draw_line((140, 165), (170, 165), width=1)
    page.insert_text((200, 210), "Figure 3", fontsize=10)
    for i, y in enumerate((150, 170, 190, 210, 230)):
        page.insert_text((300, y), f"Right column sentence {i}.", fontsize=10)


class TestTwoColumnPage:
    def test_right_column_line_stays_in_the_body(self, tmp_project):
        doc = "two_column"
        pdf = fitz.open()
        _two_column(pdf.new_page(width=W, height=H))
        pdf.save(str(tmp_project / "input" / f"{doc}.pdf"))
        pdf.close()
        for args in (
            ("pdf-triage/scripts/triage.py", "--doc", doc),
            ("extract-text/scripts/extract_text.py", "--doc", doc, "--pages", "1"),
            ("extract-images/scripts/extract_images.py", "--doc", doc, "--pages", "1"),
        ):
            result = run_script(*args, cwd=tmp_project)
            assert result.returncode == 0, f"{args[0]}: {result.stderr}"
        text = json.loads(paths.shard_path(doc, 1, "text").read_text())
        image = json.loads(paths.shard_path(doc, 1, "image").read_text())
        images = [e for e in image["elements"] if e["type"] == "image"]
        assert len(images) == 1 and images[0]["caption"] == "Figure 3"
        body = " ".join(e.get("text", "") for e in text["elements"])
        assert "Right column sentence 3." in body
        assert "Figure 3" not in body
