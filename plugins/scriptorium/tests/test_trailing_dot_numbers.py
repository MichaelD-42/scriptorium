"""Section numbers printed with a trailing dot ("4.1.1. Title"): the number
is parsed, keeps its dot, and its dot depth sets the level, also over a
PDF outline whose levels are wrong."""

import json

import fitz  # PyMuPDF
import paths
import toc
from conftest import load_script, run_script

gates = load_script("grade-output/scripts/gates.py", "gates_trailing_dot")

HEADINGS = ["4. Alpha", "4.1. Beta", "4.1.1. Gamma", "4.1.1.1. Delta"]


def _outlined_doc(path) -> None:
    pdf = fitz.open()
    page = pdf.new_page()
    y = 80
    for text in HEADINGS:
        page.insert_text((60, y), text, fontsize=13, fontname="hebo")
        page.insert_text((60, y + 20), "Body sentence for this section.", fontsize=10)
        page.insert_text((60, y + 34), "Another body sentence for this section.", fontsize=10)
        y += 70
    # The outline puts every heading but the first at level 2.
    pdf.set_toc([[1, HEADINGS[0], 1]] + [[2, text, 1] for text in HEADINGS[1:]])
    pdf.save(str(path))
    pdf.close()


def test_number_regexes_keep_the_trailing_dot():
    assert toc._split_leading_number("4.1.1. Gamma") == ("4.1.1.", "Gamma")
    assert toc._level_from_number("4.1.1.") == 3
    entries, unparsed = toc.parse_toc_page_lines(["4.1. Beta ........ 5", "4.1.1.", "Gamma ........ 6"])
    assert [(e["number"], e["level"]) for e in entries] == [("4.1.", 2), ("4.1.1.", 3)]
    assert unparsed == []


def test_outline_levels_follow_the_number_depth(tmp_project):
    doc = "trailing_dot"
    _outlined_doc(tmp_project / "input" / f"{doc}.pdf")
    for args in (
        ("pdf-triage/scripts/triage.py", "--doc", doc),
        ("extract-text/scripts/extract_text.py", "--doc", doc, "--pages", "1"),
    ):
        result = run_script(*args, cwd=tmp_project)
        assert result.returncode == 0, f"{args[0]}: {result.stderr}"
    entries = json.loads(paths.toc_json(doc).read_text(encoding="utf-8"))["entries"]
    assert [(e["number"], e["level"]) for e in entries] == [("4.", 1), ("4.1.", 2), ("4.1.1.", 3), ("4.1.1.1.", 4)]
    elements = json.loads(paths.shard_path(doc, 1, "text").read_text(encoding="utf-8"))["elements"]
    headings = [(e["text"], e["level"]) for e in elements if e["type"] == "heading"]
    assert headings == list(zip(HEADINGS, [1, 2, 3, 4]))


def test_gate_flags_a_level_that_is_not_the_number_depth():
    entries = [{"number": "4.1.", "title": "Beta", "page": 1, "level": 2}]
    doc_data = {"pages": {1: {"page_number": 1, "elements": [{"type": "heading", "level": 2, "text": "4.1. Beta"}]}}}
    assert gates.check_toc_headings_match(doc_data, entries)["passed"] is True
    # The same wrong level on both sides (an outline set it) is still caught.
    entries[0]["level"] = 3
    doc_data["pages"][1]["elements"][0]["level"] = 3
    result = gates.check_toc_headings_match(doc_data, entries)
    assert result["passed"] is False
    assert result["number_level_mismatch"] == [{"text": "4.1. Beta", "page": 1, "number_level": 2, "heading_level": 3}]
