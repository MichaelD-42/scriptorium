"""text_layer_coverage: dropped text on a text-tier PDF page is a gate,
checked against the page's own text layer, not by a grader's eye."""

import fitz  # PyMuPDF
import furniture as furniture_lib
from conftest import load_script

gates = load_script("grade-output/scripts/gates.py", "gates_module_text_coverage")

BODY = "Laden Sie die neueste Firmware herunter und speichern Sie die Datei lokal."
SECOND = "Melden Sie sich anschließend an der Weboberfläche des Zählers an."


def _pdf(tmp_path):
    pdf = fitz.open()
    for lines in ([BODY, SECOND], ["Installieren Sie danach das Update."]):
        page = pdf.new_page(width=595, height=842)
        for i, line in enumerate(lines):
            page.insert_text((72, 200 + 20 * i), line, fontsize=11)
        page.insert_text((72, 820), "Vertraulich Seite", fontsize=8)  # footer band
    path = tmp_path / "doc.pdf"
    pdf.save(path)
    return path


def _doc(page1, page2, tier="text"):
    para = lambda t: {"type": "paragraph", "text": t}  # noqa: E731
    return {
        "pages": {
            1: {"page_number": 1, "tier": tier, "elements": [para(t) for t in page1]},
            2: {"page_number": 2, "tier": "text", "elements": [para(t) for t in page2]},
        }
    }


def test_complete_output_passes_and_footer_band_is_ignored(tmp_path):
    words = gates.pdf_text_layer_words(_pdf(tmp_path), furniture_lib.empty_furniture())
    assert "vertraulich" not in words[1]
    check = gates.check_text_layer_coverage(
        _doc([BODY, SECOND], ["Installieren Sie danach das Update."]), words
    )
    assert check["passed"], check["detail"]


def test_a_dropped_paragraph_fails_that_page_with_the_missing_words(tmp_path):
    words = gates.pdf_text_layer_words(_pdf(tmp_path), furniture_lib.empty_furniture())
    check = gates.check_text_layer_coverage(
        _doc([BODY], ["Installieren Sie danach das Update."]), words
    )
    assert not check["passed"]
    assert check["pages"] == [1]
    assert "weboberfläche" in check["detail"]


def test_text_joined_onto_the_previous_page_counts(tmp_path):
    words = gates.pdf_text_layer_words(_pdf(tmp_path), furniture_lib.empty_furniture())
    joined = SECOND + " Installieren Sie danach das Update."
    check = gates.check_text_layer_coverage(_doc([BODY, joined], []), words)
    assert check["passed"], check["detail"]


def test_words_lost_on_a_page_count_even_when_they_occur_nearby():
    """Page 1 prints a table label twice; the output keeps one. The same
    words on page 2 do not cover the loss."""
    label = "Sensor Interface Module Wiring"
    source = {1: gates._words(f"{label} {label} {BODY}"), 2: gates._words(label)}
    check = gates.check_text_layer_coverage(_doc([f"{label} {BODY}"], [label]), source)
    assert check["pages"] == [1], check["detail"]


def test_repeated_header_of_a_joined_table_counts_for_its_page():
    """A table continued on page 2 repeats its header there; the join keeps
    the header once, on page 1's element, which lists both pages."""
    header = ["Parameter Name", "Default Value", "Measurement Unit"]
    rows = [header, ["Voltage", "Twelve", "Volts"], ["Current", "Three", "Amperes"]]
    table = {"type": "table", "rows": rows, "pages": [1, 2]}
    source = {
        1: gates._words(" ".join(" ".join(r) for r in rows[:2])),
        2: gates._words(" ".join(" ".join(r) for r in (header, rows[2]))),
    }
    doc_data = {
        "pages": {
            1: {"page_number": 1, "tier": "text", "elements": [table]},
            2: {"page_number": 2, "tier": "text", "elements": []},
        }
    }
    check = gates.check_text_layer_coverage(doc_data, source)
    assert check["passed"], check["detail"]


def test_ocr_and_vision_pages_are_not_checked(tmp_path):
    words = gates.pdf_text_layer_words(_pdf(tmp_path), furniture_lib.empty_furniture())
    check = gates.check_text_layer_coverage(
        _doc([], ["Installieren Sie danach das Update."], tier="vision"), words
    )
    assert check["passed"]
