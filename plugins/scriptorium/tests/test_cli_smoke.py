"""CLI integration smoke tests -- each script run as a real subprocess
(exactly how commands/extract.md invokes them), driving the full
triage -> extract -> merge -> assemble -> gate/grade chain per input format
against the committed fixtures in plugins/scriptorium/examples/.

Unit tests (test_*.py siblings) cover the pure logic in isolation; this file
is about the wiring between scripts actually working end to end.
"""

import json

import pytest

import paths
from conftest import describe_all_images, run_script


def _run_ok(relpath: str, *args: str, cwd) -> str:
    result = run_script(relpath, *args, cwd=cwd)
    assert result.returncode == 0, (
        f"{relpath} {' '.join(args)} failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    return result.stdout


class TestPdfPipeline:
    @pytest.mark.requires_tesseract  # page 5 has no text layer -- needs OCR to not be empty
    def test_triage_through_reqif_reqifz_and_zip(self, pdf_doc, tmp_project):
        _run_ok("pdf-triage/scripts/triage.py", "--doc", pdf_doc, cwd=tmp_project)
        triage = json.loads(paths.triage_json(pdf_doc).read_text())
        assert triage["page_count"] == 5
        text_pages = [p["page_number"] for p in triage["pages"] if p["tier"] == "text"]
        ocr_pages = [p["page_number"] for p in triage["pages"] if p["tier"] == "ocr"]
        assert ocr_pages == [5]  # the scanned page, per generate_sample.py

        _run_ok("render-pages/scripts/render.py", "--doc", pdf_doc, "--pages", "5", cwd=tmp_project)
        _run_ok("extract-text/scripts/extract_text.py", "--doc", pdf_doc, "--pages", ",".join(map(str, text_pages)), cwd=tmp_project)
        _run_ok("ocr-page/scripts/ocr.py", "--doc", pdf_doc, "--pages", "5", cwd=tmp_project)
        _run_ok("extract-images/scripts/extract_images.py", "--doc", pdf_doc, "--pages", "1,2,3,4,5", cwd=tmp_project)
        # Task A9: the extractor agent's describe step, before merge.
        describe_all_images(pdf_doc, tmp_project)
        _run_ok("assemble-output/scripts/merge.py", "--doc", pdf_doc, cwd=tmp_project)

        _run_ok("assemble-output/scripts/assemble.py", "--doc", pdf_doc, "--format", "reqif", cwd=tmp_project)
        assert (tmp_project / "output" / pdf_doc / f"{pdf_doc}.reqif").exists()
        gates_out = _run_ok("grade-output/scripts/gates.py", "--doc", pdf_doc, "--format", "reqif", cwd=tmp_project)
        assert json.loads(gates_out)["passed"] is True

        _run_ok("assemble-output/scripts/assemble.py", "--doc", pdf_doc, "--format", "reqifz", cwd=tmp_project)
        gates_out = _run_ok("grade-output/scripts/gates.py", "--doc", pdf_doc, "--format", "reqifz", cwd=tmp_project)
        assert json.loads(gates_out)["passed"] is True

        _run_ok("assemble-output/scripts/zip_output.py", "--doc", pdf_doc, cwd=tmp_project)
        assert (tmp_project / "output" / f"{pdf_doc}.zip").exists()


class TestPptxPipeline:
    def test_native_extract_and_assemble_needs_no_render(self, pptx_doc, tmp_project):
        """The pptx->PDF render step needs LibreOffice (see
        TestPptxRenderRequiresLibreoffice below); triage/extract/assemble
        don't touch render-pages at all."""
        _run_ok("pptx-triage/scripts/triage.py", "--doc", pptx_doc, cwd=tmp_project)
        triage = json.loads(paths.triage_json(pptx_doc).read_text())
        pages = ",".join(str(p) for p in range(1, triage["page_count"] + 1))

        _run_ok("pptx-extract/scripts/extract_pptx.py", "--doc", pptx_doc, "--pages", pages, cwd=tmp_project)
        # Task A9: the extractor agent's describe step, before merge.
        describe_all_images(pptx_doc, tmp_project)
        _run_ok("assemble-output/scripts/merge.py", "--doc", pptx_doc, cwd=tmp_project)
        _run_ok("assemble-output/scripts/assemble.py", "--doc", pptx_doc, "--format", "md", cwd=tmp_project)

        md = (tmp_project / "output" / pptx_doc / f"{pptx_doc}.md").read_text()
        assert "Sample Deck" in md

        gates_out = _run_ok("grade-output/scripts/gates.py", "--doc", pptx_doc, "--format", "md", cwd=tmp_project)
        assert json.loads(gates_out)["passed"] is True


@pytest.mark.requires_libreoffice
class TestPptxRenderRequiresLibreoffice:
    def test_render_converts_via_soffice(self, pptx_doc, tmp_project):
        _run_ok("render-pages/scripts/render.py", "--doc", pptx_doc, cwd=tmp_project)
        assert paths.page_png(pptx_doc, 1).exists()


class TestDocxPipeline:
    def test_triage_through_gates_and_text_mode_grade(self, docx_doc, tmp_project):
        _run_ok("docx-triage/scripts/triage.py", "--doc", docx_doc, cwd=tmp_project)
        triage = json.loads(paths.triage_json(docx_doc).read_text())
        assert triage["page_count"] == 2

        _run_ok("docx-extract/scripts/extract_docx.py", "--doc", docx_doc, "--pages", "1,2", cwd=tmp_project)
        # Task A9: the extractor agent's describe step, before merge.
        describe_all_images(docx_doc, tmp_project)
        _run_ok("assemble-output/scripts/merge.py", "--doc", docx_doc, cwd=tmp_project)
        _run_ok("assemble-output/scripts/assemble.py", "--doc", docx_doc, "--format", "md", cwd=tmp_project)

        gates_out = _run_ok("grade-output/scripts/gates.py", "--doc", docx_doc, "--format", "md", cwd=tmp_project)
        assert json.loads(gates_out)["passed"] is True

        _run_ok("grade-output/scripts/text_mode_grade.py", "--doc", docx_doc, cwd=tmp_project)
        assert (paths.grade_shard_path(docx_doc, 1)).exists()
        assert (paths.grade_shard_path(docx_doc, 2)).exists()


class TestXlsxPipeline:
    def test_triage_through_gates_and_text_mode_grade(self, xlsx_doc, tmp_project):
        _run_ok("xlsx-triage/scripts/triage.py", "--doc", xlsx_doc, cwd=tmp_project)
        _run_ok("xlsx-extract/scripts/extract_xlsx.py", "--doc", xlsx_doc, "--pages", "1", cwd=tmp_project)
        _run_ok("assemble-output/scripts/merge.py", "--doc", xlsx_doc, cwd=tmp_project)
        _run_ok("assemble-output/scripts/assemble.py", "--doc", xlsx_doc, "--format", "md", cwd=tmp_project)

        gates_out = _run_ok("grade-output/scripts/gates.py", "--doc", xlsx_doc, "--format", "md", cwd=tmp_project)
        assert json.loads(gates_out)["passed"] is True

        _run_ok("grade-output/scripts/text_mode_grade.py", "--doc", xlsx_doc, cwd=tmp_project)
        assert paths.grade_shard_path(xlsx_doc, 1).exists()


class TestHtmlPipeline:
    def test_triage_through_gates_and_text_mode_grade(self, html_doc, tmp_project):
        _run_ok("html-triage/scripts/triage.py", "--doc", html_doc, cwd=tmp_project)
        _run_ok("html-extract/scripts/extract_html.py", "--doc", html_doc, "--pages", "1", cwd=tmp_project)
        # Task A9: the extractor agent's describe step, before merge.
        describe_all_images(html_doc, tmp_project)
        _run_ok("assemble-output/scripts/merge.py", "--doc", html_doc, cwd=tmp_project)
        _run_ok("assemble-output/scripts/assemble.py", "--doc", html_doc, "--format", "md", cwd=tmp_project)

        gates_out = _run_ok("grade-output/scripts/gates.py", "--doc", html_doc, "--format", "md", cwd=tmp_project)
        assert json.loads(gates_out)["passed"] is True

        _run_ok("grade-output/scripts/text_mode_grade.py", "--doc", html_doc, cwd=tmp_project)
        assert paths.grade_shard_path(html_doc, 1).exists()


class TestImagePipeline:
    @pytest.mark.requires_tesseract
    def test_triage_through_gates(self, png_doc, tmp_project):
        _run_ok("image-triage/scripts/triage.py", "--doc", png_doc, cwd=tmp_project)
        triage = json.loads(paths.triage_json(png_doc).read_text())
        assert triage == {
            "doc": png_doc,
            "page_count": 1,
            "pages": [{"page_number": 1, "tier": "ocr", "image_count": 1, "reason": triage["pages"][0]["reason"]}],
            "loop_size": "tight",
        }

        _run_ok("render-pages/scripts/render.py", "--doc", png_doc, cwd=tmp_project)
        assert paths.page_png(png_doc, 1).exists()

        _run_ok("extract-images/scripts/extract_images.py", "--doc", png_doc, "--pages", "1", cwd=tmp_project)
        _run_ok("ocr-page/scripts/ocr.py", "--doc", png_doc, "--pages", "1", cwd=tmp_project)
        # Task A9: the extractor agent's describe step, before merge.
        describe_all_images(png_doc, tmp_project)
        _run_ok("assemble-output/scripts/merge.py", "--doc", png_doc, cwd=tmp_project)
        _run_ok("assemble-output/scripts/assemble.py", "--doc", png_doc, "--format", "md", cwd=tmp_project)

        gates_out = _run_ok("grade-output/scripts/gates.py", "--doc", png_doc, "--format", "md", cwd=tmp_project)
        assert json.loads(gates_out)["passed"] is True
