"""pdf-triage preflight: inputs that would otherwise crash triage, drop text
silently, or start a page at the wrong tier."""

import json

import fitz
import pytest

import paths
from conftest import load_script, run_script

triage = load_script("pdf-triage/scripts/triage.py", "pdf_triage_preflight")


def _save(doc: fitz.Document, tmp_project, name: str) -> str:
    doc.save(tmp_project / "input" / f"{name}.pdf")
    return name


def _triage(doc, cwd):
    result = run_script("pdf-triage/scripts/triage.py", "--doc", doc, cwd=cwd)
    assert result.returncode == 0, result.stderr
    return result, json.loads(paths.triage_json(doc).read_text())


class TestUnreadableInput:
    @pytest.mark.parametrize("kind", ["encrypted", "truncated", "not_a_pdf"])
    def test_exits_1_with_one_line_error_not_a_traceback(self, tmp_project, kind):
        path = tmp_project / "input" / f"{kind}.pdf"
        if kind == "encrypted":
            d = fitz.open()
            d.new_page().insert_text((72, 72), "secret")
            d.save(path, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o")
        elif kind == "truncated":
            d = fitz.open()
            for _ in range(20):
                d.new_page().insert_text((72, 72), "x" * 200)
            path.write_bytes(d.tobytes()[:2000])
        else:
            path.write_text("hello")

        result = run_script(
            "pdf-triage/scripts/triage.py", "--doc", kind, cwd=tmp_project
        )

        assert result.returncode == 1
        assert "Traceback" not in result.stderr
        assert result.stderr.startswith("error: ")
        assert not paths.triage_json(kind).exists()


class TestShortDocumentKeepsEdgeLines:
    def test_one_page_header_is_not_furniture(self, tmp_project):
        """One occurrence on a one-page document is 100% of pages; that is not
        repetition. assemble.py does not render furniture_text, so a header
        wrongly marked as furniture is lost from the output."""
        d = fitz.open()
        d.new_page().insert_text((72, 60), "ACME Corp annex to contract 4711")
        doc = _save(d, tmp_project, "one_page")

        _, data = _triage(doc, tmp_project)

        assert data["furniture"]["line_patterns"] == []
        assert data["furniture_text"] is None


class TestPageTierPreflight:
    def test_garbled_text_layer_goes_to_ocr(self, tmp_project):
        """An embedded font without a ToUnicode map: the text layer reads out
        glyph ids, not letters."""
        d = fitz.open()
        page = d.new_page()
        page.insert_font(fontname="F0", fontbuffer=fitz.Font("cjk").buffer)
        page.insert_text((72, 72), "Quarterly report body text " * 6, fontname="F0")
        for xref in range(1, d.xref_length()):
            if d.xref_get_key(xref, "ToUnicode")[0] != "null":
                d.xref_set_key(xref, "ToUnicode", "null")
        doc = _save(d, tmp_project, "garbled")

        _, data = _triage(doc, tmp_project)

        page = data["pages"][0]
        assert page["tier"] == "ocr"
        assert "garbled" in page["reason"]

    def test_scan_with_a_short_digital_header_goes_to_ocr(self, tmp_project):
        d = fitz.open()
        page = d.new_page()
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 100, 100), 0)
        pix.clear_with(200)
        page.insert_image(fitz.Rect(30, 80, 565, 820), pixmap=pix)
        page.insert_text((72, 60), "Annex B -- scanned copy, page 1")
        doc = _save(d, tmp_project, "stamped_scan")

        _, data = _triage(doc, tmp_project)

        page = data["pages"][0]
        assert page["tier"] == "ocr"
        assert "image" in page["reason"]

    def test_photo_with_a_full_text_page_stays_text(self, tmp_project):
        d = fitz.open()
        page = d.new_page()
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 100, 100), 0)
        pix.clear_with(200)
        page.insert_image(fitz.Rect(30, 80, 565, 500), pixmap=pix)
        page.insert_textbox(
            fitz.Rect(72, 520, 520, 800), "Body text of the report. " * 40, fontsize=9
        )
        doc = _save(d, tmp_project, "photo_page")

        _, data = _triage(doc, tmp_project)

        assert data["pages"][0]["tier"] == "text"


class TestCompactStdout:
    def test_stdout_is_a_summary_not_the_whole_triage_json(self, tmp_project):
        d = fitz.open()
        for n in range(40):
            d.new_page().insert_text(
                (72, 300), f"Body text on page {n + 1}, long enough to count."
            )
        d.new_page()  # blank page -> ocr
        doc = _save(d, tmp_project, "forty")

        result, data = _triage(doc, tmp_project)

        summary = json.loads(result.stdout)
        assert summary["page_count"] == 41
        assert summary["loop_size"] == data["loop_size"]
        assert summary["body_size"] == data["body_size"]
        assert summary["non_text_pages"] == {"41": "ocr"}
        assert summary["triage_json"] == str(paths.triage_json(doc))
        assert "furniture" not in summary and "pages" not in summary


class TestFindTablesOnlyOnCandidatePages:
    def test_pages_without_a_large_drawing_extent_are_skipped(self):
        d = fitz.open()
        d.new_page().insert_text((72, 72), "no drawings at all")
        framed = d.new_page()
        framed.draw_rect(fitz.Rect(20, 20, 575, 822))

        assert triage._frame_table_candidate_pages(d) == {2}
