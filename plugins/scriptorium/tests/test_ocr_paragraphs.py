"""ocr.py's grouping of Tesseract's words into elements."""

import json

from PIL import Image

import elements as elements_lib
from conftest import load_script

ocr = load_script("ocr-page/scripts/ocr.py", "ocr_module")


def _fake_data(words):
    """image_to_data's DICT for (block, par, line, word) tuples."""
    return {
        "text": [w for *_, w in words],
        "conf": [95] * len(words),
        "block_num": [b for b, *_ in words],
        "par_num": [p for _, p, *_ in words],
        "line_num": [ln for _, _, ln, _ in words],
        "top": [100 * b + 10 * p + ln for b, p, ln, _ in words],
    }


def test_the_lines_of_one_paragraph_make_one_element(tmp_path, monkeypatch):
    image = tmp_path / "page1.png"
    Image.new("RGB", (10, 10), "white").save(image)
    words = [(1, 1, 1, "A"), (1, 1, 1, "well-"), (1, 1, 2, "known"), (1, 1, 3, "fact."), (1, 2, 1, "Second.")]
    monkeypatch.setattr(ocr.pytesseract, "image_to_data", lambda *a, **k: _fake_data(words))
    elements, confidence = ocr.ocr_tesseract(image, "eng")
    assert [el["text"] for el in elements] == ["A well-known fact.", "Second."]  # elements.join_text's line-end hyphen rule
    assert confidence == 0.95
    assert [el["top"] for el in elements] == [111, 121]  # the paragraph's first line, in pixels


def test_ocr_top_is_scaled_to_points(tmp_path, monkeypatch):
    image = tmp_path / "page1.png"
    Image.new("RGB", (10, 10), "white").save(image)
    monkeypatch.setattr(ocr.pytesseract, "image_to_data", lambda *a, **k: _fake_data([(1, 1, 1, "Word")]))
    elements, _ = ocr.ocr_tesseract(image, "eng", scale=0.5)
    assert elements[0]["top"] == 55.5


def test_a_figure_keeps_its_place_between_ocr_paragraphs(tmp_path):
    """OCR text has no bbox; without its `top` every figure sorted after
    all of the page's text."""
    shards = tmp_path / "shards"
    shards.mkdir()
    body = [{"type": "paragraph", "text": "Above.", "top": 50}, {"type": "paragraph", "text": "Below.", "top": 500}]
    figure = {"type": "image", "asset": "assets/page1_bitmap1.png", "bbox": [0, 200, 100, 300]}
    (shards / "page1.ocr.json").write_text(json.dumps({"page_number": 1, "elements": body}))
    (shards / "page1.image.json").write_text(json.dumps({"page_number": 1, "elements": [figure]}))
    page = elements_lib.merge_shards(shards, 1)[1]
    assert [el.get("text", "figure") for el in page["elements"]] == ["Above.", "figure", "Below."]
