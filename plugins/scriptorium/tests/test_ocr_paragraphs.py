"""ocr.py's grouping of Tesseract's words into elements."""

from PIL import Image

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
    }


def test_the_lines_of_one_paragraph_make_one_element(tmp_path, monkeypatch):
    image = tmp_path / "page1.png"
    Image.new("RGB", (10, 10), "white").save(image)
    words = [(1, 1, 1, "A"), (1, 1, 1, "well-"), (1, 1, 2, "known"), (1, 1, 3, "fact."), (1, 2, 1, "Second.")]
    monkeypatch.setattr(ocr.pytesseract, "image_to_data", lambda *a, **k: _fake_data(words))
    elements, confidence = ocr.ocr_tesseract(image, "eng")
    assert [el["text"] for el in elements] == ["A well-known fact.", "Second."]  # elements.join_text's line-end hyphen rule
    assert confidence == 0.95
