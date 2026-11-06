"""pptx-extract's text reading."""

from pptx import Presentation
from pptx.util import Inches

from conftest import load_script

extract_pptx = load_script(
    "pptx-extract/scripts/extract_pptx.py", "extract_pptx_module"
)


def test_a_line_break_keeps_the_words_apart():
    """A manual line break (Shift+Enter, <a:br/>) is not a run; joining the
    runs alone glued "line" and "second"."""
    slide = Presentation().slides.add_slide(Presentation().slide_layouts[6])
    shape = slide.shapes.add_textbox(0, 0, Inches(3), Inches(1))
    shape.text_frame.text = "first line\vsecond line"
    assert extract_pptx.shape_paragraphs(shape) == ["first line second line"]
