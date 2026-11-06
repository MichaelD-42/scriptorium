"""Bitmap figure_text from Tesseract at the scripts stage, so a labelled
screenshot needs no agent to transcribe it."""

import json

import fitz  # PyMuPDF
import pytest
from PIL import Image, ImageDraw, ImageFont

import paths
import tesseract as tesseract_lib
from conftest import run_script


def _ok(*args, cwd):
    result = run_script(*args, cwd=cwd)
    assert result.returncode == 0, result.stderr
    return result


def _label_png(path, text):
    img = Image.new("RGB", (900, 160), "white")
    ImageDraw.Draw(img).text((30, 40), text, fill="black", font=ImageFont.load_default(size=64))
    img.save(path)
    return path


@pytest.mark.requires_tesseract
def test_a_labelled_bitmap_is_read_and_a_blank_one_is_not(tmp_path):
    assert "Firmware Update" in tesseract_lib.ocr_figure_text(_label_png(tmp_path / "a.png", "Firmware Update"), "eng")
    Image.new("RGB", (300, 200), "white").save(tmp_path / "b.png")
    assert tesseract_lib.ocr_figure_text(tmp_path / "b.png", "eng") == ""


def _pdf_with_bitmap(tmp_project, png):
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)
    page.insert_text((72, 100), "Body text above the screenshot.", fontsize=11)
    page.insert_image(fitz.Rect(72, 300, 522, 380), filename=str(png))
    pdf.save(tmp_project / "input" / "shot.pdf")


@pytest.mark.requires_tesseract
def test_extract_images_sets_ocr_figure_text_only_with_a_language(tmp_project):
    _pdf_with_bitmap(tmp_project, _label_png(tmp_project / "label.png", "Firmware Update"))
    _ok("extract-images/scripts/extract_images.py", "--doc", "shot", "--pages", "1", cwd=tmp_project)
    (el,) = json.loads(paths.shard_path("shot", 1, "image").read_text())["elements"]
    assert "figure_text" not in el

    _ok("extract-images/scripts/extract_images.py", "--doc", "shot", "--pages", "1", "--ocr-lang", "eng", cwd=tmp_project)
    (el,) = json.loads(paths.shard_path("shot", 1, "image").read_text())["elements"]
    assert "Firmware Update" in el["figure_text"]
    assert el["figure_text_source"] == "ocr"


@pytest.mark.requires_tesseract
def test_the_extractor_may_correct_ocr_figure_text(tmp_project):
    _pdf_with_bitmap(tmp_project, _label_png(tmp_project / "label.png", "Firmware Update"))
    _ok("extract-images/scripts/extract_images.py", "--doc", "shot", "--pages", "1", "--ocr-lang", "eng", cwd=tmp_project)
    asset = json.loads(paths.shard_path("shot", 1, "image").read_text())["elements"][0]["asset"]
    _ok(
        "extract-images/scripts/describe_image.py", "--doc", "shot", "--page", "1", "--asset", asset,
        "--description", "A banner reading Firmware Update.", "--figure-text", "Firmware-Update",
        cwd=tmp_project,
    )
    (el,) = json.loads(paths.shard_path("shot", 1, "image").read_text())["elements"]
    assert el["figure_text"] == "Firmware-Update"
    assert "figure_text_source" not in el
