"""Follow-up R17: a caption printed as two text lines at one y.

Some documents print "Fig. 11" and the caption title as two spans at the
same y (a tab between them), which PyMuPDF returns as two lines.
`CAPTION_PATTERN` now also accepts "Fig. n" / "Figure n" at the end of a
line, and `figures.find_caption_line` joins a lone caption-number line with the
text line at its y (within `toc.SAME_Y_TOLERANCE`) into one caption line,
before claiming and before the orphan check. An image's caption search
prefers the nearest figure caption over a "Table n" caption.
"""

import json

import figures as figures_lib
import fitz  # PyMuPDF
import paths
from conftest import run_script

W, H = 595.0, 842.0


def _diagram(page, y: float) -> None:
    page.draw_rect(fitz.Rect(100, y, 220, y + 50), width=1)
    page.draw_rect(fitz.Rect(320, y, 440, y + 50), width=1)
    page.draw_line((220, y + 25), (320, y + 25), width=1)


def _run(tmp_project, doc: str, draw) -> tuple[dict, dict, dict]:
    pdf = fitz.open()
    page = pdf.new_page(width=W, height=H)
    page.insert_text((72, 120), "Ordinary body text above the figure.", fontsize=11)
    draw(page)
    pdf.save(str(tmp_project / "input" / f"{doc}.pdf"))
    pdf.close()
    for args in (
        ("pdf-triage/scripts/triage.py", "--doc", doc),
        ("extract-text/scripts/extract_text.py", "--doc", doc, "--pages", "1"),
        ("extract-images/scripts/extract_images.py", "--doc", doc, "--pages", "1"),
        ("assemble-output/scripts/merge.py", "--doc", doc),
        ("assemble-output/scripts/assemble.py", "--doc", doc, "--format", "md"),
    ):
        result = run_script(*args, cwd=tmp_project)
        assert result.returncode == 0, f"{args[0]}: {result.stderr}"
    gates = run_script(
        "grade-output/scripts/gates.py", "--doc", doc, "--format", "md", cwd=tmp_project
    )
    text = json.loads(paths.shard_path(doc, 1, "text").read_text())
    image = json.loads(paths.shard_path(doc, 1, "image").read_text())
    return text, image, json.loads(gates.stdout)


class TestCaptionPattern:
    def test_caption_number_at_the_end_of_a_line(self):
        assert figures_lib.CAPTION_PATTERN.match("Fig. 11")
        assert figures_lib.CAPTION_PATTERN.match("Figure 3:")
        assert figures_lib.is_figure_caption("Fig. 11")
        assert not figures_lib.CAPTION_PATTERN.match("Figure 11a shows")


class TestTwoSpanCaption:
    def test_two_span_caption_is_claimed_by_the_image_above(self, tmp_project):
        def draw(page):
            _diagram(page, 200)
            page.insert_text((72, 285), "Fig. 11", fontsize=10)
            page.insert_text((160, 285), "Synthetic two span title", fontsize=10)

        text, image, report = _run(tmp_project, "two_span", draw)
        images = [e for e in image["elements"] if e["type"] == "image"]
        assert len(images) == 1
        assert images[0]["caption"] == "Fig. 11 Synthetic two span title"
        body = " ".join(e.get("text", "") for e in text["elements"])
        assert "Fig. 11" not in body and "Synthetic two span title" not in body
        assert not [
            w for w in report["warnings"] if w["name"] == "orphan_figure_caption"
        ]

    def test_figure_caption_below_wins_over_a_table_caption_above(self, tmp_project):
        def draw(page):
            page.insert_text((100, 190), "Table 3: Limits of the thing", fontsize=10)
            _diagram(page, 200)
            page.insert_text((250, 272), "Fig. 4", fontsize=10)

        text, image, report = _run(tmp_project, "table_above", draw)
        images = [e for e in image["elements"] if e["type"] == "image"]
        assert len(images) == 1 and images[0]["caption"] == "Fig. 4"
        assert "Table 3: Limits of the thing" in [
            e.get("text") for e in text["elements"]
        ]
        assert not [
            w for w in report["warnings"] if w["name"] == "orphan_figure_caption"
        ]
