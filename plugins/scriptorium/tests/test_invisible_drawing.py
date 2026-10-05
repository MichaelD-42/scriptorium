"""Follow-up R19: an invisible drawing is not a figure.

Word sometimes paints a white, unstroked rectangle behind a run of body
text. It draws nothing on a white page, but `get_drawings()` lists it, and
a rect narrower than the text line beside it was kept as a figure region:
the lines inside became figure_text and left the body. A fill-only drawing
whose fill is white is now left out of figure detection and recorded in
`excluded_regions` with reason "invisible_drawing".
"""

import json

import figures as figures_lib
import fitz  # PyMuPDF
import paths
from conftest import run_script

W, H = 595.0, 842.0


def _pdf(path, fill=(1, 1, 1), stroke=None) -> None:
    pdf = fitz.open()
    page = pdf.new_page(width=W, height=H)
    page.draw_rect(
        fitz.Rect(108, 108, 283, 128),
        color=stroke,
        fill=fill,
        width=0 if stroke is None else 1,
    )
    page.insert_text((150, 104), "INF 12345678-6 v3", fontsize=10)
    page.insert_text(
        (46, 120),
        "The following synthetic limitations and interfaces shall be met by the part.",
        fontsize=10,
    )
    pdf.save(str(path))
    pdf.close()


def _run(tmp_project, doc: str) -> tuple[dict, dict]:
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


class TestInvisibleDrawing:
    def test_white_fill_only_rect_is_not_a_figure(self, tmp_project):
        doc = "white_rect"
        _pdf(tmp_project / "input" / f"{doc}.pdf")
        text, image = _run(tmp_project, doc)
        assert not [e for e in image["elements"] if e["type"] == "image"]
        body = " ".join(e.get("text", "") for e in text["elements"])
        assert "INF 12345678-6 v3" in body
        assert "The following synthetic limitations" in body
        reasons = [r["reason"] for r in image.get("excluded_regions", [])]
        assert "invisible_drawing" in reasons

    def test_is_invisible_drawing(self):
        assert figures_lib.is_invisible_drawing(
            {"fill": (1.0, 1.0, 1.0), "color": None, "type": "f"}
        )
        assert not figures_lib.is_invisible_drawing(
            {"fill": (1.0, 1.0, 1.0), "color": (0, 0, 0), "type": "fs"}
        )
        assert not figures_lib.is_invisible_drawing(
            {"fill": (0.8, 0.8, 0.8), "color": None, "type": "f"}
        )
        assert not figures_lib.is_invisible_drawing(
            {"fill": None, "color": (0, 0, 0), "type": "s"}
        )
