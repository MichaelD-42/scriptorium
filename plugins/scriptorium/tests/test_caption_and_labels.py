"""Follow-up R22: a caption's second line, and labels just outside a figure.

- A caption that wraps keeps its continuation line: the line directly
  below the caption line (gap at most one caption line height), inside
  the caption's x-span, when the caption does not end with a full stop.
  It joins the caption text and is excluded from the body.
- A short label line printed just outside a vector figure's region, beside
  it (its y-range overlaps the region's), grows the region: the label goes
  to figure_text, and the crop shows it, instead of a stray body paragraph.
"""

import json

import fitz  # PyMuPDF
import paths
from conftest import run_script

W, H = 595.0, 842.0


def _diagram(page, x0: float, y0: float) -> None:
    page.draw_rect(fitz.Rect(x0, y0, x0 + 120, y0 + 50), width=1)
    page.draw_rect(fitz.Rect(x0 + 200, y0, x0 + 320, y0 + 50), width=1)
    page.draw_line((x0 + 120, y0 + 25), (x0 + 200, y0 + 25), width=1)


def _run(tmp_project, doc: str, draw) -> tuple[dict, dict]:
    pdf = fitz.open()
    page = pdf.new_page(width=W, height=H)
    page.insert_text((72, 120), "Ordinary body text above the figure.", fontsize=10)
    draw(page)
    pdf.save(str(tmp_project / "input" / f"{doc}.pdf"))
    pdf.close()
    for args in (
        ("pdf-triage/scripts/triage.py", "--doc", doc),
        ("extract-text/scripts/extract_text.py", "--doc", doc, "--pages", "1"),
        ("extract-images/scripts/extract_images.py", "--doc", doc, "--pages", "1"),
    ):
        result = run_script(*args, cwd=tmp_project)
        assert result.returncode == 0, f"{args[0]}: {result.stderr}"
    text = json.loads(paths.shard_path(doc, 1, "text").read_text(encoding="utf-8"))
    image = json.loads(paths.shard_path(doc, 1, "image").read_text(encoding="utf-8"))
    return text, image


def _body(text: dict) -> str:
    return " | ".join(e.get("text", "") for e in text["elements"])


class TestCaptionContinuation:
    def test_second_caption_line_joins_the_caption(self, tmp_project):
        def draw(page):
            _diagram(page, 120, 200)
            # Hanging indent: the number and the title are two spans (R17),
            # and the second line starts at the title's x.
            page.insert_text((100, 280), "Fig. 11", fontsize=10)
            page.insert_text(
                (150, 280),
                "Limit line showing synthetic emission levels for a complete",
                fontsize=10,
            )
            page.insert_text((150, 293), "vehicle, peak", fontsize=10)
            page.insert_text((72, 330), "Pass criteria:", fontsize=10)

        text, image = _run(tmp_project, "caption_two_lines", draw)
        images = [e for e in image["elements"] if e["type"] == "image"]
        assert len(images) == 1
        assert images[0]["caption"] == (
            "Fig. 11 Limit line showing synthetic emission levels for a complete vehicle, peak"
        )
        body = _body(text)
        assert "vehicle, peak" not in body
        assert "Pass criteria:" in body

    def test_centred_second_line_joins_the_caption(self, tmp_project):
        def draw(page):
            _diagram(page, 120, 200)
            page.insert_text(
                (130, 280),
                "Fig. 13   Limit line showing synthetic levels for a component test",
                fontsize=10,
            )
            page.insert_text((240, 293), "(peak and average limits)", fontsize=10)

        _text, image = _run(tmp_project, "caption_centred", draw)
        images = [e for e in image["elements"] if e["type"] == "image"]
        assert images[0]["caption"].endswith("component test (peak and average limits)")

    def test_flush_left_body_line_is_not_a_continuation(self, tmp_project):
        def draw(page):
            _diagram(page, 120, 200)
            page.insert_text(
                (100, 280),
                "Figure 1: Synthetic hemisphere with a flat ram",
                fontsize=10,
            )
            page.insert_text((100, 293), "Acceptance criteria", fontsize=10)

        text, image = _run(tmp_project, "caption_flush_left", draw)
        images = [e for e in image["elements"] if e["type"] == "image"]
        assert images[0]["caption"] == "Figure 1: Synthetic hemisphere with a flat ram"
        assert "Acceptance criteria" in _body(text)

    def test_caption_ending_with_a_full_stop_takes_no_next_line(self, tmp_project):
        def draw(page):
            _diagram(page, 120, 200)
            page.insert_text((100, 280), "Fig. 2 Synthetic set-up.", fontsize=10)
            page.insert_text((110, 293), "Short note", fontsize=10)

        text, image = _run(tmp_project, "caption_full_stop", draw)
        images = [e for e in image["elements"] if e["type"] == "image"]
        assert images[0]["caption"] == "Fig. 2 Synthetic set-up."
        assert "Short note" in _body(text)


class TestEdgeLabels:
    def test_label_beside_the_figure_joins_figure_text(self, tmp_project):
        def draw(page):
            _diagram(page, 120, 200)
            page.insert_text((454, 228), "CW", fontsize=12)
            page.insert_text((100, 300), "Fig. 14", fontsize=10)

        text, image = _run(tmp_project, "edge_label", draw)
        images = [e for e in image["elements"] if e["type"] == "image"]
        assert len(images) == 1
        assert "CW" in (images[0].get("figure_text") or "")
        assert "CW" not in _body(text)
        assert images[0]["bbox"][2] >= 470

    def test_label_reaching_into_the_figure_edge_joins_figure_text(self, tmp_project):
        def draw(page):
            _diagram(page, 120, 200)
            page.insert_text((300, 262), "tinterrupt", fontsize=12)

        text, image = _run(tmp_project, "label_into_edge", draw)
        images = [e for e in image["elements"] if e["type"] == "image"]
        assert "tinterrupt" in (images[0].get("figure_text") or "")
        assert "tinterrupt" not in _body(text)

    def test_short_line_below_the_figure_stays_body(self, tmp_project):
        def draw(page):
            _diagram(page, 120, 200)
            page.insert_text((120, 282), "Selected", fontsize=10)

        text, _image = _run(tmp_project, "line_below", draw)
        assert "Selected" in _body(text)
