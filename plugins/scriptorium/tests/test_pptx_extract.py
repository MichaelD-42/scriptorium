"""pptx-extract's slide reading."""

import io
import zipfile

import fitz  # PyMuPDF
import openpyxl
import pptx_shapes
from PIL import Image
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.enum.shapes import MSO_SHAPE, PP_PLACEHOLDER
from pptx.oxml.ns import qn
from pptx.util import Inches

from conftest import load_script

extract_pptx = load_script(
    "pptx-extract/scripts/extract_pptx.py", "extract_pptx_module"
)
pptx_triage = load_script("pptx-triage/scripts/triage.py", "pptx_triage_module")
assemble = load_script("assemble-output/scripts/assemble.py", "assemble_pptx_module")


def _blank_slide():
    prs = Presentation()
    return prs.slides.add_slide(prs.slide_layouts[6])


def _texts(elements):
    return [el.get("text") for el in elements]


def _png(w, h):
    b = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(b, "PNG")
    b.seek(0)
    return b


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


class TestPosition:
    def test_a_group_member_is_placed_through_the_group_transform(self, tmp_path):
        slide = _blank_slide()
        group = slide.shapes.add_group_shape()
        group.shapes.add_textbox(0, Inches(1), Inches(3), Inches(1)).text_frame.text = "Inside group"
        slide.shapes.add_textbox(0, Inches(3), Inches(3), Inches(1)).text_frame.text = "Top level"
        group._element.grpSpPr.xfrm.off.y = Inches(5)  # child space still starts at 1 in
        body, _ = extract_pptx.extract_slide(slide, 1, tmp_path)
        assert _texts(body) == ["Top level", "Inside group"]
        assert body[1]["top"] == 360.0  # 5 in

    def test_a_hidden_shape_is_skipped(self, tmp_path):
        slide = _blank_slide()
        hidden = slide.shapes.add_textbox(0, 0, Inches(3), Inches(1))
        hidden.text_frame.text = "Hidden"
        hidden._element.nvSpPr.cNvPr.set("hidden", "1")
        hidden_pic = slide.shapes.add_picture(_png(10, 10), 0, 0, Inches(1), Inches(1))
        hidden_pic._element.nvPicPr.cNvPr.set("hidden", "1")
        body, images = extract_pptx.extract_slide(slide, 1, tmp_path)
        assert body == [] and images == []

    def test_images_interleave_with_text_and_notes_stay_last(self, tmp_path):
        slide = _blank_slide()
        slide.shapes.add_textbox(0, Inches(1), Inches(3), Inches(1)).text_frame.text = "Above"
        slide.shapes.add_picture(_png(10, 10), 0, Inches(2), Inches(1), Inches(1))
        slide.shapes.add_textbox(0, Inches(4), Inches(3), Inches(1)).text_frame.text = "Below"
        slide.notes_slide.notes_text_frame.text = "Say this"
        body, images = extract_pptx.extract_slide(slide, 1, tmp_path)
        assert images[0]["bbox"] == [0.0, 144.0, 72.0, 216.0]
        merged = sorted(body + images, key=lambda e: e["bbox"][1] if "bbox" in e else e.get("top", 0))
        assert [e.get("text", e["type"]) for e in merged] == ["Above", "image", "Below", "Speaker notes: Say this"]


def _slide_pdf(tmp_path, slide):
    """A stand-in for LibreOffice's slide PDF: one page of the slide's size
    in points, filled red, so a crop of it is a real PNG of a known size."""
    w, h = pptx_shapes.slide_size(slide)
    pdf = fitz.open()
    page = pdf.new_page(width=w / 12700, height=h / 12700)
    page.draw_rect(page.rect, color=(1, 0, 0), fill=(1, 0, 0))
    path = tmp_path / "deck.pdf"
    pdf.save(str(path))
    pdf.close()
    return lambda: path


def _asset_size(tmp_path, el):
    with Image.open(tmp_path / el["asset"].removeprefix("assets/")) as img:
        return img.size


class TestPictureCrop:
    def test_a_cropped_picture_is_exported_cropped(self, tmp_path):
        slide = _blank_slide()
        pic = slide.shapes.add_picture(_png(1000, 1000), Inches(1), Inches(1), Inches(2), Inches(2))
        pic.crop_left, pic.crop_top, pic.crop_right, pic.crop_bottom = 0.25, 0.70, 0.64, 0.03
        _, images = extract_pptx.extract_slide(slide, 1, tmp_path)
        w, h = _asset_size(tmp_path, images[0])
        assert abs(w - 110) <= 1 and abs(h - 270) <= 1

    def test_a_negative_crop_is_clamped(self, tmp_path):
        slide = _blank_slide()
        pic = slide.shapes.add_picture(_png(100, 100), Inches(1), Inches(1), Inches(2), Inches(2))
        pic.crop_top = -0.01
        _, images = extract_pptx.extract_slide(slide, 1, tmp_path)
        assert _asset_size(tmp_path, images[0]) == (100, 100)

    def test_a_picture_cropped_away_entirely_is_skipped(self, tmp_path):
        slide = _blank_slide()
        pic = slide.shapes.add_picture(_png(100, 100), Inches(1), Inches(1), Inches(2), Inches(2))
        pic.crop_left, pic.crop_right = 0.6, 0.4
        assert extract_pptx.extract_slide(slide, 1, tmp_path)[1] == []

    def test_a_picture_pil_cannot_decode_is_cropped_from_the_slide_pdf(self, tmp_path, monkeypatch):
        monkeypatch.setattr(extract_pptx, "VECTOR_IMAGE_EXTS", {"png"})  # stands in for an EMF blob
        slide = _blank_slide()
        pic = slide.shapes.add_picture(_png(40, 40), Inches(1), Inches(1), Inches(2), Inches(1))
        _, images = extract_pptx.extract_slide(slide, 1, tmp_path, _slide_pdf(tmp_path, slide))
        assert images[0]["asset"] == f"assets/page1_shape{pic.shape_id}.png"
        assert images[0]["source_shape_id"] == pic.shape_id
        w, h = _asset_size(tmp_path, images[0])
        assert abs(w - 2 * extract_pptx.CROP_DPI) <= 1 and abs(h - extract_pptx.CROP_DPI) <= 1

    def test_without_a_slide_pdf_such_a_picture_has_no_element(self, tmp_path, monkeypatch):
        monkeypatch.setattr(extract_pptx, "VECTOR_IMAGE_EXTS", {"png"})
        slide = _blank_slide()
        slide.shapes.add_picture(_png(40, 40), Inches(1), Inches(1), Inches(2), Inches(1))
        assert extract_pptx.extract_slide(slide, 1, tmp_path)[1] == []


def _workbook(rows, ole_size=None, hidden_row=None):
    """An xlsx blob; `ole_size` adds the <oleSize ref> PowerPoint writes
    (openpyxl does not), `hidden_row` hides that 1-based row."""
    wb = openpyxl.Workbook()
    for row in rows:
        wb.active.append(row)
    if hidden_row:
        wb.active.row_dimensions[hidden_row].hidden = True
    raw = io.BytesIO()
    wb.save(raw)
    if ole_size is None:
        raw.seek(0)
        return raw
    out = io.BytesIO()
    with zipfile.ZipFile(raw) as src, zipfile.ZipFile(out, "w") as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "xl/workbook.xml":
                data = data.replace(b"</workbook>", f'<oleSize ref="{ole_size}"/></workbook>'.encode())
            dst.writestr(item, data)
    out.seek(0)
    return out


def _add_worksheet(slide, blob, width=Inches(4), height=Inches(2)):
    return slide.shapes.add_ole_object(blob, "Excel.Sheet.12", Inches(1), Inches(1), width, height,
                                       icon_file=_png(400, 200))


def _add_chart(slide):
    data = CategoryChartData()
    data.categories = ["a", "b"]
    data.add_series("s", (1, 2))
    return slide.shapes.add_chart(XL_CHART_TYPE.PIE, Inches(1), Inches(1), Inches(3), Inches(2), data)


class TestEmbeddedObjects:
    def test_an_embedded_worksheet_becomes_an_element(self, tmp_path):
        slide = _blank_slide()
        frame = _add_worksheet(slide, _workbook([["Head A", "Head B"], ["r1a", "r1b"], ["r2a", "r2b"]]))
        body, images = extract_pptx.extract_slide(slide, 1, tmp_path, _slide_pdf(tmp_path, slide))
        assert body == []  # no oleSize: the slide crop, not a table
        assert [(el["kind"], el["source_shape_id"]) for el in images] == [("vector", frame.shape_id)]
        assert images[0]["bbox"] == [72.0, 72.0, 360.0, 216.0]
        assert _asset_size(tmp_path, images[0]) == (800, 400)  # 4 x 2 in at 200 dpi

    def test_a_worksheet_with_ole_size_becomes_a_table_of_what_the_slide_shows(self, tmp_path):
        slide = _blank_slide()
        rows = [["Head A", "Head B", "secret"], ["r1a", "r1b", "x"], ["r2a", "r2b", "x"], ["r3a", "r3b", "x"]]
        frame = _add_worksheet(slide, _workbook(rows, ole_size="A1:B3", hidden_row=2))
        body, images = extract_pptx.extract_slide(slide, 1, tmp_path)
        assert images == []
        assert body[0]["rows"] == [["Head A", "Head B"], ["r2a", "r2b"]]
        assert body[0]["source_shape_id"] == frame.shape_id

    def test_a_chart_is_cropped_from_the_slide_pdf(self, tmp_path):
        slide = _blank_slide()
        frame = _add_chart(slide)
        _, images = extract_pptx.extract_slide(slide, 1, tmp_path, _slide_pdf(tmp_path, slide))
        assert [el["source_shape_id"] for el in images] == [frame.shape_id]

    def test_a_hidden_or_degenerate_embedded_object_has_no_element(self, tmp_path):
        slide = _blank_slide()
        hidden = _add_worksheet(slide, _workbook([["a"]]))
        hidden._element.nvGraphicFramePr.cNvPr.set("hidden", "1")
        _add_worksheet(slide, _workbook([["a"]]), width=2000, height=2000)
        body, images = extract_pptx.extract_slide(slide, 1, tmp_path, _slide_pdf(tmp_path, slide))
        assert body == [] and images == []


def _drawn_figure(slide):
    """A top-level group of autoshapes with a tiny icon and a label."""
    group = slide.shapes.add_group_shape()
    group.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(1), Inches(1), Inches(2), Inches(2))
    group.shapes.add_shape(MSO_SHAPE.OVAL, Inches(1.3), Inches(1.3), Inches(1.4), Inches(1.4))
    group.shapes.add_picture(_png(40, 25), Inches(1.1), Inches(1.1), Inches(0.3), Inches(0.2))
    group.shapes.add_textbox(Inches(1), Inches(3.1), Inches(2), Inches(0.4)).text_frame.text = "Label"
    return group


class TestVectorFigures:
    def test_a_group_of_autoshapes_is_one_figure(self, tmp_path):
        slide = _blank_slide()
        group = _drawn_figure(slide)
        body, images = extract_pptx.extract_slide(slide, 1, tmp_path, _slide_pdf(tmp_path, slide))
        assert len(images) == 1
        assert images[0]["source_shape_id"] == group.shape_id
        assert _asset_size(tmp_path, images[0]) != (40, 25)
        assert _texts(body) == ["Label"]  # the group's words stay text

    def test_a_picture_with_a_drawn_overlay_is_one_figure(self, tmp_path):
        slide = _blank_slide()
        group = slide.shapes.add_group_shape()
        pic = group.shapes.add_picture(_png(100, 100), Inches(1), Inches(1), Inches(2), Inches(2))
        pic.crop_left = 0.5
        group.shapes.add_shape(MSO_SHAPE.CURVED_RIGHT_ARROW, Inches(1.5), Inches(1.5), Inches(1), Inches(1))
        _, images = extract_pptx.extract_slide(slide, 1, tmp_path, _slide_pdf(tmp_path, slide))
        assert [el["source_shape_id"] for el in images] == [group.shape_id]

    def test_a_group_of_text_boxes_is_not_a_figure(self, tmp_path):
        slide = _blank_slide()
        group = slide.shapes.add_group_shape()
        group.shapes.add_picture(_png(10, 10), 0, 0, Inches(1), Inches(1))
        group.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, Inches(2), Inches(3), Inches(1)).text_frame.text = "Box"
        _, images = extract_pptx.extract_slide(slide, 1, tmp_path)
        assert [el["kind"] for el in images] == ["bitmap"]

    def test_a_picture_filled_shape_is_cropped_from_the_slide_pdf(self, tmp_path):
        slide = _blank_slide()
        shape = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(1), Inches(1), Inches(2), Inches(2))
        shape._element.spPr.append(shape._element.spPr.makeelement(qn("a:blipFill"), {}))
        shape.text_frame.text = "Filled"
        body, images = extract_pptx.extract_slide(slide, 1, tmp_path, _slide_pdf(tmp_path, slide))
        assert [el["source_shape_id"] for el in images] == [shape.shape_id]
        assert _texts(body) == ["Filled"]


class TestFurniturePlaceholders:
    @staticmethod
    def _slide_with_footer_placeholders():
        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = "Title"
        for ph in slide.slide_layout.placeholders:
            if ph.placeholder_format.type in pptx_shapes.FURNITURE_PLACEHOLDERS:
                slide.shapes.clone_placeholder(ph)
        texts = {
            PP_PLACEHOLDER.FOOTER: "Footer line",
            PP_PLACEHOLDER.SLIDE_NUMBER: "7",
            PP_PLACEHOLDER.DATE: "2001-01-01",
        }
        for sh in slide.placeholders:
            if sh.placeholder_format.type in texts:
                sh.text_frame.text = texts[sh.placeholder_format.type]
        return prs, slide

    def test_footer_placeholders_are_furniture(self, tmp_path):
        _, slide = self._slide_with_footer_placeholders()
        body, _ = extract_pptx.extract_slide(slide, 1, tmp_path)
        assert [(el["type"], el["text"]) for el in body] == [("heading", "Title")]

    def test_a_text_box_with_the_footer_text_is_kept(self, tmp_path):
        _, slide = self._slide_with_footer_placeholders()
        slide.shapes.add_textbox(0, Inches(7), Inches(4), Inches(0.4)).text_frame.text = "Footer line"
        body, _ = extract_pptx.extract_slide(slide, 1, tmp_path)
        assert "Footer line" in _texts(body)

    def test_triage_records_footer_text_as_furniture(self):
        prs, _ = self._slide_with_footer_placeholders()
        furniture = pptx_triage.footer_furniture(prs)
        assert [p["masked"] for p in furniture["line_patterns"]] == ["Footerline"]

    def test_a_footer_that_is_also_body_text_is_not_furniture(self):
        prs, slide = self._slide_with_footer_placeholders()
        slide.shapes.title.text = "Footer line"  # a footer repeating the deck title
        assert pptx_triage.footer_furniture(prs)["line_patterns"] == []
