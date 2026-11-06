"""pdf-triage's pre-analysis: detection scopes and quirks, each with the
measure the pipeline applies, found before any extraction."""

import json
import shutil

import fitz  # PyMuPDF

import paths
from conftest import EXAMPLES_ROOT, run_script

GERMAN = (
    "Das Gerät wird über die Weboberfläche aktualisiert und der Zähler ist danach nicht "
    "erreichbar. Sie finden die Datei auf der Seite des Herstellers, mit der neuen Version "
    "für das Gerät. Die Installation wird bei jedem Neustart geprüft und ein Hinweis auf "
    "der Seite angezeigt, wenn das Update nicht abgeschlossen ist."
)
PROSE = (
    "Download the latest software from the website and save it on the computer, then open the "
    "web interface of the meter in a browser and log in with the password from the type label."
)


def _ok(*args, cwd):
    result = run_script(*args, cwd=cwd)
    assert result.returncode == 0, result.stderr
    return result.stdout


def _layout_table_pdf(tmp_project, name="steps"):
    """Steps laid out in a ruled 3x3 grid: one prose cell per step, the
    other cells empty spacers."""
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)
    xs, ys = (60, 330, 340, 535), (100, 260, 270, 430)
    for x in xs:
        page.draw_line((x, ys[0]), (x, ys[-1]))
    for y in ys:
        page.draw_line((xs[0], y), (xs[-1], y))
    page.insert_textbox(fitz.Rect(64, 104, 326, 256), PROSE, fontsize=10)
    page.insert_textbox(
        fitz.Rect(64, 274, 326, 426),
        PROSE.replace("Download", "Then download"),
        fontsize=10,
    )
    pdf.save(tmp_project / "input" / f"{name}.pdf")
    return name


def _triage(tmp_project, doc):
    stdout = json.loads(
        _ok("pdf-triage/scripts/triage.py", "--doc", doc, cwd=tmp_project)
    )
    return stdout, json.loads(paths.triage_json(doc).read_text())["pre_analysis"]


def test_german_text_layer_names_its_ocr_language(tmp_project):
    pdf = fitz.open()
    pdf.new_page().insert_textbox(fitz.Rect(60, 60, 540, 700), GERMAN, fontsize=11)
    pdf.save(tmp_project / "input" / "de.pdf")
    stdout, analysis = _triage(tmp_project, "de")
    assert stdout["text_languages"] == ["deu"]
    assert {
        "name": "text_language",
        "languages": ["deu"],
        "measure": analysis["quirks"][0]["measure"],
    } in analysis["quirks"]


def test_a_layout_table_is_flagged_and_read_as_body_text(tmp_project):
    doc = _layout_table_pdf(tmp_project)
    stdout, analysis = _triage(tmp_project, doc)
    assert "layout_table" in stdout["quirks"]
    assert next(q for q in analysis["quirks"] if q["name"] == "layout_table")[
        "pages"
    ] == [1]
    assert analysis["scopes"]["data_table_pages"] == []

    _ok(
        "extract-text/scripts/extract_text.py",
        "--doc",
        doc,
        "--pages",
        "1",
        "--body-size",
        "10",
        cwd=tmp_project,
    )
    elements = json.loads(paths.shard_path(doc, 1, "text").read_text())["elements"]
    assert [e["type"] for e in elements] == ["paragraph", "paragraph"]
    assert elements[0]["text"].startswith("Download the latest software")


def test_fixtures_with_real_tables_and_furniture_have_no_quirks(tmp_project):
    shutil.copy(EXAMPLES_ROOT / "furniture_sample.pdf", tmp_project / "input" / "f.pdf")
    stdout, analysis = _triage(tmp_project, "f")
    assert stdout["quirks"] == []
    assert analysis["scopes"]["data_table_pages"] == [8, 9]
    assert analysis["scopes"]["toc_entries"] == 30
    assert analysis["scopes"]["furniture"] is True
    # The logo on every page is furniture; page 4 has a bitmap of its own.
    assert analysis["scopes"]["bitmap_pages"] == [4]
