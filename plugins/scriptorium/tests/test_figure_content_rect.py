"""A figure drawn just below the content frame's top edge does not take
in the title block above the frame, and the furniture gate sees a title
block line inside an image's figure_text."""

import fitz  # PyMuPDF
from conftest import load_script

W, H = 595.0, 842.0
FRAME = (42.5, 154.7, 558.1, 813.7)

figures = load_script("../lib/figures.py", "figures_content_rect")
gates = load_script("grade-output/scripts/gates.py", "gates_content_rect")


def _page(path) -> None:
    """A title block above the frame (title cell and a revision number at
    one y, 4 pt above the frame), and a two-box diagram whose top edge is
    6 pt below the frame top."""
    pdf = fitz.open()
    page = pdf.new_page(width=W, height=H)
    page.insert_text((50, 150), "Synthetic document title", fontsize=10)
    page.insert_text((340, 150), "1.0.0.0", fontsize=10)
    page.draw_rect(fitz.Rect(*FRAME), width=0.5)
    shape = page.new_shape()
    for box in (fitz.Rect(100, 161, 200, 200), fitz.Rect(300, 161, 400, 200)):
        shape.draw_rect(box)
        shape.finish(color=(0, 0, 0), fill=(0.85, 0.9, 1.0), width=0.8)
    shape.draw_line((200, 180), (300, 180))
    shape.finish(color=(0, 0, 0), width=0.8)
    shape.commit()
    page.insert_text((120, 184), "Input", fontsize=9)
    page.insert_text((320, 184), "Output", fontsize=9)
    page.insert_text((46, 260), "Body text after the figure.", fontsize=10)
    pdf.save(str(path))
    pdf.close()


def test_figure_region_stops_at_the_content_frame(tmp_path):
    pdf_path = tmp_path / "figure.pdf"
    _page(pdf_path)
    with fitz.open(pdf_path) as doc:
        regions, excluded = figures.detect_figure_regions_with_exclusions(
            doc[0], 1, pdf_path, frame_drawings=[{"bbox": list(FRAME)}], content_rect=list(FRAME)
        )
        assert len(regions) == 1, (regions, excluded)
        assert regions[0]["bbox"][1] >= FRAME[1] - 0.5, regions
        text = figures.figure_text_for_region(doc[0], regions[0]["bbox"])
    assert text == "Input\nOutput", text


def test_furniture_line_in_figure_text_fails_the_gate(tmp_path):
    furniture = {
        "line_patterns": [{"masked": "#.#.#.#"}, {"masked": "Syntheticdocumenttitle"}],
        "content_rect": list(FRAME),
    }
    image = {"type": "image", "bbox": [90, 141, 410, 210], "figure_text": "Synthetic document title\nInput\nOutput"}
    doc_data = {"pages": {1: {"page_number": 1, "elements": [image]}}}
    check = gates.check_furniture_absent(doc_data, furniture, tmp_path / "out", {1: H}, {1: W})
    assert not check["passed"]
    assert [o["where"] for o in check["offenders"]] == ["image figure_text"], check["offenders"]
    # An image wholly in the body may show the same words (a screenshot).
    image["bbox"] = [90, 300, 410, 400]
    assert gates.check_furniture_absent(doc_data, furniture, tmp_path / "out", {1: H}, {1: W})["passed"]
