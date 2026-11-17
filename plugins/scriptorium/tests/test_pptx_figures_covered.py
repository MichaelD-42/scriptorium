"""The pptx figure census (lib/pptx_shapes.figure_shapes) and the
pptx_figures_covered gate that checks pptx-extract against it."""

import json

import paths
import pptx_shapes
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Inches

from conftest import load_script, run_script
from test_pptx_extract import (
    _add_chart,
    _add_worksheet,
    _blank_slide,
    _drawn_figure,
    _png,
    _slide_pdf,
    _workbook,
    extract_pptx,
)

gates = load_script("grade-output/scripts/gates.py", "gates_pptx_figures_module")
pptx_triage = load_script("pptx-triage/scripts/triage.py", "pptx_triage_census_module")


def _doc(page_elements, tier="text"):
    return {"pages": {1: {"page_number": 1, "tier": tier, "elements": page_elements}}}


def _kinds(slide):
    return [(s["kind"], s["shape_id"]) for s in pptx_shapes.figure_shapes(slide)]


class TestCensus:
    def test_counts_pictures_objects_charts_and_drawn_groups(self):
        slide = _blank_slide()
        pic = slide.shapes.add_picture(_png(10, 10), 0, 0, Inches(2), Inches(2))
        ole = _add_worksheet(slide, _workbook([["a"]]))
        chart = _add_chart(slide)
        group = _drawn_figure(slide)
        census = pptx_shapes.figure_shapes(slide)
        assert [(s["kind"], s["shape_id"]) for s in census if not s["groups"]] == [
            ("pic", pic.shape_id), ("ole", ole.shape_id), ("chart", chart.shape_id), ("group", group.shape_id),
        ]
        # the drawn group's icon is under 0.5% of the slide: part of the group, not a figure
        assert [s for s in census if s["groups"]] == []

    def test_leaves_out_hidden_cropped_away_and_degenerate_shapes(self):
        slide = _blank_slide()
        hidden = slide.shapes.add_picture(_png(10, 10), 0, 0, Inches(2), Inches(2))
        hidden._element.nvPicPr.cNvPr.set("hidden", "1")
        cropped = slide.shapes.add_picture(_png(10, 10), 0, 0, Inches(2), Inches(2))
        cropped.crop_top, cropped.crop_bottom = 0.5, 0.5
        _add_worksheet(slide, _workbook([["a"]]), width=2000, height=2000)
        assert _kinds(slide) == []

    def test_a_picture_in_a_plain_group_is_listed_with_its_group(self):
        slide = _blank_slide()
        group = slide.shapes.add_group_shape()
        pic = group.shapes.add_picture(_png(10, 10), 0, 0, Inches(2), Inches(2))
        assert pptx_shapes.figure_shapes(slide)[0]["groups"] == [group.shape_id]
        assert _kinds(slide) == [("pic", pic.shape_id)]


def test_triage_writes_the_census_and_counts_it():
    slide = _blank_slide()
    _add_worksheet(slide, _workbook([["a"]]))
    page = pptx_triage.classify_slide(slide, 1)
    assert page["image_count"] == 1
    assert [s["kind"] for s in page["figure_shapes"]] == ["ole"]


class TestGate:
    def test_the_gate_sees_a_figure_the_extractor_missed(self):
        doc = _doc([{"type": "image", "asset": "assets/page1_bitmap1.png", "caption": "c", "description": "d"}])
        assert gates.check_figures_complete(doc, "pptx")["passed"] is True
        census = {1: [{"shape_id": 2, "kind": "group"}, {"shape_id": 5, "kind": "pic"}]}
        result = gates.check_pptx_figures_covered(doc, census)
        assert result["passed"] is False
        assert result["uncovered"] == [{"page": 1, "shape_id": 2, "kind": "group"}, {"page": 1, "shape_id": 5, "kind": "pic"}]
        assert result["pages"] == [1]

    def test_a_group_element_covers_its_members(self):
        doc = _doc([{"type": "image", "asset": "a.png", "source_shape_id": 2}])
        census = {1: [{"shape_id": 2, "kind": "group", "groups": []}, {"shape_id": 5, "kind": "pic", "groups": [2]}]}
        assert gates.check_pptx_figures_covered(doc, census)["passed"] is True

    def test_a_vision_page_falls_back_to_a_count(self):
        census = {1: [{"shape_id": 5, "kind": "ole"}, {"shape_id": 6, "kind": "pic"}]}
        image = {"type": "image", "asset": "a.png", "source_shape_id": 6}
        assert gates.check_pptx_figures_covered(_doc([image, {"type": "table", "rows": [["x"]]}], "vision"), census)["passed"] is True
        assert gates.check_pptx_figures_covered(_doc([image], "vision"), census)["passed"] is False


def test_the_extract_script_handles_a_figure_with_or_without_libreoffice(tmp_project):
    """The slide PDF is made on first need; without LibreOffice the chart
    gets a warning instead of an element, and the slide's text is still
    written."""
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.shapes.add_textbox(0, 0, Inches(3), Inches(1)).text_frame.text = "Words"
    _add_chart(slide)
    prs.save(str(tmp_project / "input" / "deck.pptx"))
    result = run_script("pptx-extract/scripts/extract_pptx.py", "--doc", "deck", "--pages", "1", cwd=tmp_project)
    assert result.returncode == 0, result.stderr
    assert json.loads(paths.shard_path("deck", 1, "text").read_text())["elements"][0]["text"] == "Words"
    images = json.loads(paths.shard_path("deck", 1, "image").read_text())["elements"]
    assert images or "warning" in result.stderr


def test_the_extractor_covers_its_own_census(tmp_path):
    """Census and extractor are separate walks: on a slide with every
    figure kind, the gate passes on the extractor's output."""
    slide = _blank_slide()
    pic = slide.shapes.add_picture(_png(100, 100), 0, 0, Inches(2), Inches(2))
    pic.crop_left = 0.3
    _add_worksheet(slide, _workbook([["a", "b"]]))
    _add_worksheet(slide, _workbook([["a", "b"], ["c", "d"]], ole_size="A1:B2"))
    _add_chart(slide)
    _drawn_figure(slide)
    filled = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(5), Inches(5), Inches(2), Inches(2))
    filled._element.spPr.append(filled._element.spPr.makeelement(pptx_shapes.qn("a:blipFill"), {}))
    body, images = extract_pptx.extract_slide(slide, 1, tmp_path, _slide_pdf(tmp_path, slide))
    census = {1: pptx_shapes.figure_shapes(slide)}
    assert len(census[1]) == 6
    assert gates.check_pptx_figures_covered(_doc(body + images), census)["passed"] is True
