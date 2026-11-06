"""Regression tests for the 0.7.1 audit findings."""

import io
import json
import shutil

from bs4 import BeautifulSoup
from docx import Document
from PIL import Image
from pptx import Presentation
from pptx.util import Inches

import docx_pages
import html_pages
import paths
from conftest import EXAMPLES_ROOT, load_script, run_script

extract_html = load_script("html-extract/scripts/extract_html.py", "extract_html_0_7_1")
extract_docx = load_script("docx-extract/scripts/extract_docx.py", "extract_docx_0_7_1")
extract_pptx = load_script("pptx-extract/scripts/extract_pptx.py", "extract_pptx_0_7_1")
text_mode = load_script("grade-output/scripts/text_mode_grade.py", "text_mode_0_7_1")


def _png_bytes() -> io.BytesIO:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buf, "PNG")
    buf.seek(0)
    return buf


def _html(tmp_path, body: str):
    path = tmp_path / "doc.html"
    path.write_text(
        f"<html><head><title>Title</title></head><body>{body}</body></html>",
        encoding="utf-8",
    )
    return html_pages.parse(path)


class TestHtmlText:
    def test_inline_markup_keeps_the_spaces_around_it(self, tmp_path):
        soup = _html(
            tmp_path,
            "<p>Hello <b>world</b>, see <a href='x'>the docs</a><br>now.</p>"
            "<table><tr><td>first <i>cell</i></td></tr></table>",
        )

        body, _ = extract_html.extract_page(soup, tmp_path, tmp_path)

        assert body == [
            {"type": "paragraph", "text": "Hello world, see the docs now."},
            {"type": "table", "rows": [["first cell"]]},
        ]

    def test_text_outside_block_tags_is_extracted(self, tmp_path):
        soup = _html(
            tmp_path,
            "<div>Important notice here</div><section><span>Second note</span></section>",
        )

        body, _ = extract_html.extract_page(soup, tmp_path, tmp_path)

        assert [el["text"] for el in body] == ["Important notice here", "Second note"]

    def test_a_body_with_no_blocks_leaves_the_title_out(self, tmp_path):
        soup = _html(tmp_path, "Only body text")

        body, _ = extract_html.extract_page(soup, tmp_path, tmp_path)

        assert body == [{"type": "paragraph", "text": "Only body text"}]


class TestTextModeCoverage:
    """The grader reads the source text without the extractor's block walk,
    so content the walk skips is still found."""

    def test_html_text_the_walk_skips_is_dropped_text(self, tmp_path):
        soup = _html(tmp_path, "<div>Intro words <p>A paragraph</p></div>")
        blocks = list(html_pages.iter_block_items(soup))
        page = {"elements": [{"type": "paragraph", "text": "A paragraph"}]}

        assert "dropped_text" in text_mode.grade_html_page(blocks, page, soup, tmp_path)
        assert text_mode.missing_words(html_pages.visible_text(soup), page) == [
            "intro",
            "words",
        ]

    def test_html_glued_words_are_dropped_text(self, tmp_path):
        soup = _html(tmp_path, "<p>Hello <b>world</b></p>")
        blocks = list(html_pages.iter_block_items(soup))
        page = {"elements": [{"type": "paragraph", "text": "Helloworld"}]}

        assert "dropped_text" in text_mode.grade_html_page(blocks, page, soup, tmp_path)

    def test_docx_table_cell_text_is_checked(self):
        d = Document()
        d.add_paragraph("Body text")
        d.add_table(rows=1, cols=1).cell(0, 0).text = "Cell words"
        source = " ".join(docx_pages.block_source_text(b) for b in docx_pages.iter_block_items(d))
        page = {"elements": [{"type": "paragraph", "text": "Body text"}]}

        assert text_mode.missing_words(source, page) == ["cell", "words"]

    def test_the_reason_names_the_missing_words(self, docx_doc, tmp_project):
        run_script("docx-triage/scripts/triage.py", "--doc", docx_doc, cwd=tmp_project)
        run_script(
            "docx-extract/scripts/extract_docx.py",
            "--doc",
            docx_doc,
            "--pages",
            "1,2",
            cwd=tmp_project,
        )
        shard = paths.shard_path(docx_doc, 1, "text")
        data = json.loads(shard.read_text())
        data["elements"] = [el for el in data["elements"] if el["type"] == "heading"]
        shard.write_text(json.dumps(data))
        run_script(
            "assemble-output/scripts/merge.py", "--doc", docx_doc, cwd=tmp_project
        )

        result = run_script(
            "grade-output/scripts/text_mode_grade.py",
            "--doc",
            docx_doc,
            cwd=tmp_project,
        )

        assert result.returncode == 0, result.stderr
        grade = json.loads(paths.grade_shard_path(docx_doc, 1).read_text())
        assert "dropped_text" in grade["issues"]
        assert grade["reason"].startswith("source words not in the output: ")


class TestDocxTableImages:
    def test_an_image_in_a_table_cell_is_extracted_and_counted(self, tmp_path):
        d = Document()
        cell = d.add_table(rows=1, cols=1).cell(0, 0)
        cell.paragraphs[0].add_run().add_picture(_png_bytes())
        path = tmp_path / "t.docx"
        d.save(path)
        document = Document(path)

        blocks = docx_pages.split_pages(document)[0]
        body, images = extract_docx.extract_page(blocks, 1, document, tmp_path)

        assert body[0]["type"] == "table"
        assert len(images) == 1
        missing_image, _ = text_mode.docx_check_images(blocks, [], document)
        assert missing_image


class TestUppercaseExtensions:
    def test_docx_with_an_uppercase_extension_is_triaged_and_extracted(
        self, tmp_project
    ):
        shutil.copyfile(
            EXAMPLES_ROOT / "sample.docx", tmp_project / "input" / "Report.DOCX"
        )

        triage = run_script(
            "docx-triage/scripts/triage.py", "--doc", "Report", cwd=tmp_project
        )
        extract = run_script(
            "docx-extract/scripts/extract_docx.py",
            "--doc",
            "Report",
            "--pages",
            "1",
            cwd=tmp_project,
        )

        assert triage.returncode == 0, triage.stderr
        assert extract.returncode == 0, extract.stderr
        assert paths.shard_path("Report", 1, "text").exists()


class TestPptxGroups:
    def test_a_picture_and_text_inside_a_group_are_extracted(self, tmp_path):
        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        group = slide.shapes.add_group_shape()
        group.shapes.add_picture(_png_bytes(), 0, 0, Inches(1), Inches(1))
        group.shapes.add_textbox(
            0, Inches(2), Inches(3), Inches(1)
        ).text_frame.text = "Grouped label"

        body, images = extract_pptx.extract_slide(slide, 1, tmp_path)

        assert body == [{"type": "paragraph", "text": "Grouped label"}]
        assert len(images) == 1
        assert (tmp_path / images[0]["asset"].removeprefix("assets/")).exists()


def test_block_text_ignores_comments_and_scripts():
    soup = BeautifulSoup(
        "<p>kept <!-- dropped --><script>x()</script>text</p>", "html.parser"
    )
    assert html_pages.block_text(soup.p) == "kept text"
