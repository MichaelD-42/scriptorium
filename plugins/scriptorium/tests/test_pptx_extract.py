"""pptx-extract's text reading."""

from pptx import Presentation
from pptx.util import Inches

from conftest import load_script

extract_pptx = load_script(
    "pptx-extract/scripts/extract_pptx.py", "extract_pptx_module"
)
assemble = load_script("assemble-output/scripts/assemble.py", "assemble_pptx_module")


def _blank_slide():
    prs = Presentation()
    return prs.slides.add_slide(prs.slide_layouts[6])


def _texts(elements):
    return [el.get("text") for el in elements]


def test_a_line_break_keeps_the_words_apart():
    """A manual line break (Shift+Enter, <a:br/>) is not a run; joining the
    runs alone glued "line" and "second"."""
    slide = Presentation().slides.add_slide(Presentation().slide_layouts[6])
    shape = slide.shapes.add_textbox(0, 0, Inches(3), Inches(1))
    shape.text_frame.text = "first line\vsecond line"
    assert extract_pptx.shape_paragraphs(shape) == ["first line second line"]


class TestStrikethrough:
    @staticmethod
    def _paragraph(slide, runs):
        para = slide.shapes.add_textbox(0, 0, Inches(4), Inches(1)).text_frame.paragraphs[0]
        for text, strike in runs:
            para.add_run().text = text
            if strike:
                para.runs[-1].font._rPr.set("strike", strike)
        return para

    def test_a_struck_run_is_marked(self, tmp_path):
        slide = _blank_slide()
        self._paragraph(slide, [("keep ", None), ("struck ", "sngStrike"), ("tail", None)])
        body, _ = extract_pptx.extract_slide(slide, 1, tmp_path)
        assert _texts(body) == ["keep ~~struck~~ tail"]

    def test_a_no_strike_run_is_not_marked(self, tmp_path):
        slide = _blank_slide()
        self._paragraph(slide, [("keep ", None), ("plain", "noStrike")])
        body, _ = extract_pptx.extract_slide(slide, 1, tmp_path)
        assert _texts(body) == ["keep plain"]

    def test_adjacent_struck_runs_give_one_span(self, tmp_path):
        slide = _blank_slide()
        self._paragraph(slide, [("a ", "sngStrike"), ("b", "dblStrike"), (" c", None)])
        body, _ = extract_pptx.extract_slide(slide, 1, tmp_path)
        assert _texts(body) == ["~~a b~~ c"]

    def test_a_struck_table_cell_is_marked(self, tmp_path):
        slide = _blank_slide()
        table = slide.shapes.add_table(1, 2, 0, 0, Inches(4), Inches(1)).table
        table.cell(0, 0).text = "live"
        para = table.cell(0, 1).text_frame.paragraphs[0]
        para.add_run().text = "gone"
        para.runs[0].font._rPr.set("strike", "sngStrike")
        body, _ = extract_pptx.extract_slide(slide, 1, tmp_path)
        assert body[0]["rows"] == [["live", "~~gone~~"]]

    def test_html_shows_struck_text_as_del(self):
        html = assemble.to_html({"doc": "d", "pages": {1: {"page_number": 1, "elements": [
            {"type": "paragraph", "text": "keep ~~<b>gone</b>~~"},
            {"type": "table", "rows": [["~~x~~"]]},
        ]}}})
        assert "<p>keep <del>&lt;b&gt;gone&lt;/b&gt;</del></p>" in html
        assert "<td><del>x</del></td>" in html
