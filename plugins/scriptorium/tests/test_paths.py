"""Unit tests for lib/paths.py -- path conventions and format detection."""

import json

import pytest

import paths


class TestDetectInputFormat:
    def test_passthrough_formats(self, tmp_path):
        for ext in ("pdf", "pptx", "xlsx", "docx", "html"):
            (tmp_path / "input").mkdir(exist_ok=True)
            path = tmp_path / "input" / f"doc.{ext}"
            path.write_bytes(b"x")
            assert paths.detect_input_format("doc", root=tmp_path) == ext
            path.unlink()

    @pytest.mark.parametrize("ext", ["png", "jpg", "jpeg", "webp", "tiff"])
    def test_image_extensions_normalize_to_image(self, tmp_path, ext):
        (tmp_path / "input").mkdir(exist_ok=True)
        (tmp_path / "input" / f"doc.{ext}").write_bytes(b"x")
        assert paths.detect_input_format("doc", root=tmp_path) == "image"

    def test_none_when_no_input_file(self, tmp_path):
        (tmp_path / "input").mkdir()
        assert paths.detect_input_format("missing", root=tmp_path) is None


class TestTruePageCount:
    def test_html_is_always_one(self, tmp_path):
        assert paths.true_page_count("doc", "html", root=tmp_path) == 1

    def test_image_is_always_one(self, tmp_path):
        assert paths.true_page_count("doc", "image", root=tmp_path) == 1

    def test_docx_reads_triage_json_page_count(self, tmp_path):
        work_dir = tmp_path / "work" / "doc"
        work_dir.mkdir(parents=True)
        (work_dir / "triage.json").write_text(json.dumps({"page_count": 3}))
        assert paths.true_page_count("doc", "docx", root=tmp_path) == 3

    def test_docx_raises_without_triage_json(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            paths.true_page_count("doc", "docx", root=tmp_path)

    def test_unsupported_format_raises(self, tmp_path):
        with pytest.raises(NotImplementedError):
            paths.true_page_count("doc", "made-up", root=tmp_path)


class TestOutputFile:
    @pytest.mark.parametrize(
        "fmt,ext",
        [("md", "md"), ("html", "html"), ("reqif", "reqif"), ("reqifz", "reqifz"), ("okf", "md")],
    )
    def test_extension_by_format(self, tmp_path, fmt, ext):
        result = paths.output_file("doc", fmt, root=tmp_path)
        assert result == tmp_path / "output" / "doc" / f"doc.{ext}"

    def test_output_zip_is_sibling_of_output_dir(self, tmp_path):
        assert paths.output_zip("doc", root=tmp_path) == tmp_path / "output" / "doc.zip"
