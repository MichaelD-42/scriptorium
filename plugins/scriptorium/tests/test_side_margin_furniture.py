"""A line rotated into the left or right page margin (a document number,
"Aktuelle Informationen finden Sie unter ...") is page furniture, even
when it differs per page (KSEM AutoUpdate guide: "- DE -" on page 1,
"- EN -" on page 2), so repetition cannot find it."""

import json

import fitz

import paths
from conftest import run_script


def test_rotated_side_margin_line_is_dropped_rotated_body_line_is_kept(tmp_project):
    d = fitz.open()
    page = d.new_page()  # 595 x 842
    page.insert_text((72, 100), "Body text that stays, long enough to be a text layer line.", fontsize=9)
    page.insert_text((572, 814), "03 / 2023 - DE - DOC03153690 - Technische Aenderungen vorbehalten.", fontsize=7, rotate=90)
    page.insert_text((300, 600), "Rotated label in the body", fontsize=9, rotate=90)
    d.save(tmp_project / "input" / "margin.pdf")

    for script, args in (
        ("pdf-triage/scripts/triage.py", ()),
        ("extract-text/scripts/extract_text.py", ("--pages", "1", "--body-size", "9")),
    ):
        result = run_script(script, "--doc", "margin", *args, cwd=tmp_project)
        assert result.returncode == 0, result.stderr

    text = " ".join(e.get("text", "") for e in json.loads(paths.shard_path("margin", 1, "text").read_text())["elements"])
    assert "Body text that stays" in text
    assert "Rotated label in the body" in text
    assert "DOC03153690" not in text
