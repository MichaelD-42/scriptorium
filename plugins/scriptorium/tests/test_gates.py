"""Unit tests for grade-output/scripts/gates.py -- deterministic structural
checks."""

import zipfile

import pytest

from conftest import load_script

gates = load_script("grade-output/scripts/gates.py", "gates_module")


def _doc_data(pages: dict) -> dict:
    return {"doc": "sample", "pages": pages}


class TestCheckNoEmptyPages:
    def test_passes_when_every_page_has_elements(self):
        pages = {1: {"page_number": 1, "elements": [{"type": "paragraph", "text": "x"}]}}
        assert gates.check_no_empty_pages(_doc_data(pages))["passed"] is True

    def test_fails_and_names_empty_pages(self):
        pages = {1: {"page_number": 1, "elements": []}, 2: {"page_number": 2, "elements": [{"type": "paragraph", "text": "x"}]}}
        result = gates.check_no_empty_pages(_doc_data(pages))
        assert result["passed"] is False
        assert "[1]" in result["detail"]


class TestCheckImageRefsResolve:
    def test_passes_when_asset_exists_on_disk(self, tmp_path):
        (tmp_path / "assets").mkdir()
        (tmp_path / "assets" / "a.png").write_bytes(b"x")
        pages = {1: {"elements": [{"type": "image", "asset": "assets/a.png"}]}}
        assert gates.check_image_refs_resolve(_doc_data(pages), tmp_path)["passed"] is True

    def test_fails_when_asset_missing(self, tmp_path):
        pages = {1: {"elements": [{"type": "image", "asset": "assets/missing.png"}]}}
        result = gates.check_image_refs_resolve(_doc_data(pages), tmp_path)
        assert result["passed"] is False
        assert "assets/missing.png" in result["detail"]


class TestCheckOcrConfidenceFloor:
    def test_passes_above_floor(self):
        pages = {1: {"tier": "ocr", "ocr_confidence": 0.9}}
        assert gates.check_ocr_confidence_floor(_doc_data(pages))["passed"] is True

    def test_fails_below_floor(self):
        pages = {1: {"page_number": 1, "tier": "ocr", "ocr_confidence": 0.2}}
        assert gates.check_ocr_confidence_floor(_doc_data(pages))["passed"] is False

    def test_ignores_non_ocr_pages(self):
        pages = {1: {"tier": "text"}}  # no ocr_confidence key at all
        assert gates.check_ocr_confidence_floor(_doc_data(pages))["passed"] is True


class TestCheckOutputFileExists:
    def test_md_passes_when_file_big_enough(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        out = tmp_path / "output" / "sample" / "sample.md"
        out.parent.mkdir(parents=True)
        out.write_text("x" * 50)
        assert gates.check_output_file_exists("sample", "md")["passed"] is True

    def test_md_fails_when_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert gates.check_output_file_exists("sample", "md")["passed"] is False

    def test_okf_requires_index_and_sections(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        out_dir = tmp_path / "output" / "sample"
        out_dir.mkdir(parents=True)
        (out_dir / "index.md").write_text("x" * 30)
        assert gates.check_output_file_exists("sample", "okf")["passed"] is False  # no section files yet
        (out_dir / "00-intro.md").write_text("content")
        assert gates.check_output_file_exists("sample", "okf")["passed"] is True

    def test_md_tree_requires_an_index_whose_links_all_resolve(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        out_dir = tmp_path / "output" / "sample"
        out_dir.mkdir(parents=True)
        assert gates.check_output_file_exists("sample", "md-tree")["passed"] is False
        (out_dir / "index.md").write_text("# sample\n\n* [1 Intro](01-intro/01.00-intro.md)\n  * [1.1 Scope](01-intro/01.01-scope.md)\n")
        (out_dir / "01-intro").mkdir()
        (out_dir / "01-intro" / "01.00-intro.md").write_text("content")
        result = gates.check_output_file_exists("sample", "md-tree")
        assert result["passed"] is False
        assert "01-intro/01.01-scope.md" in result["detail"]
        (out_dir / "01-intro" / "01.01-scope.md").write_text("content")
        assert gates.check_output_file_exists("sample", "md-tree")["passed"] is True

    def test_md_tree_depth_1_flat_files_pass(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        out_dir = tmp_path / "output" / "sample"
        out_dir.mkdir(parents=True)
        (out_dir / "index.md").write_text("# sample\n\n* [1 Intro](01-intro.md)\n")
        (out_dir / "01-intro.md").write_text("content")
        assert gates.check_output_file_exists("sample", "md-tree")["passed"] is True

    def test_a_stale_okf_index_is_not_an_md_tree(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        out_dir = tmp_path / "output" / "sample"
        out_dir.mkdir(parents=True)
        (out_dir / "index.md").write_text("---\nokf_version: \"0.1\"\n---\n* [Intro](/01-intro.md) - x\n")
        (out_dir / "01-intro.md").write_text("content")
        assert gates.check_output_file_exists("sample", "md-tree")["passed"] is False

    def test_md_tree_accepts_front_matter_only_bundle(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        out_dir = tmp_path / "output" / "sample"
        out_dir.mkdir(parents=True)
        (out_dir / "index.md").write_text("# sample\n\n* [Front Matter](00-front-matter.md)\n")
        (out_dir / "00-front-matter.md").write_text("content")
        assert gates.check_output_file_exists("sample", "md-tree")["passed"] is True

    def test_md_tree_fails_on_tiny_index(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        out_dir = tmp_path / "output" / "sample"
        (out_dir / "01-intro").mkdir(parents=True)
        (out_dir / "index.md").write_text("[](a)")
        (out_dir / "01-intro" / "01.01-scope.md").write_text("content")
        assert gates.check_output_file_exists("sample", "md-tree")["passed"] is False

    def test_reqif_requires_well_formed_xml_with_req_if_root(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        out_dir = tmp_path / "output" / "sample"
        out_dir.mkdir(parents=True)
        (out_dir / "sample.reqif").write_text("<NOT-XML" + "x" * 30)
        assert gates.check_output_file_exists("sample", "reqif")["passed"] is False

        (out_dir / "sample.reqif").write_text("<REQ-IF>" + " " * 20 + "</REQ-IF>")
        assert gates.check_output_file_exists("sample", "reqif")["passed"] is True

        (out_dir / "sample.reqif").write_text("<WRONG-ROOT>" + " " * 20 + "</WRONG-ROOT>")
        assert gates.check_output_file_exists("sample", "reqif")["passed"] is False

    def test_reqifz_requires_valid_zip_containing_the_reqif(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        out_dir = tmp_path / "output" / "sample"
        out_dir.mkdir(parents=True)
        zip_path = out_dir / "sample.reqifz"

        zip_path.write_bytes(b"not a zip" + b"x" * 20)
        assert gates.check_output_file_exists("sample", "reqifz")["passed"] is False

        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("wrong-name.reqif", "<REQ-IF/>")
        assert gates.check_output_file_exists("sample", "reqifz")["passed"] is False

        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("sample.reqif", "<REQ-IF/>" + " " * 20)
        assert gates.check_output_file_exists("sample", "reqifz")["passed"] is True

    @pytest.mark.parametrize("fmt", ["reqif", "jsonl", "reqifz"])
    def test_missing_or_empty_output_fails(self, tmp_path, monkeypatch, fmt):
        monkeypatch.chdir(tmp_path)
        assert gates.check_output_file_exists("sample", fmt)["passed"] is False
        out = tmp_path / "output" / "sample" / f"sample.{fmt}"
        out.parent.mkdir(parents=True)
        out.write_text("")
        assert gates.check_output_file_exists("sample", fmt)["passed"] is False
