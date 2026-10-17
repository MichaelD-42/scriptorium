"""Follow-up R30: a paragraph set in two columns that start side by side
(KSEM AutoUpdate guide, page 1; line geometry from that PDF). The left
column is read first, its lines wrap at the column's own right edge, and
a sentence cut at the column break is one paragraph."""

import json

import fitz

import paths
from conftest import run_script

LEFT = [
    "Das automatische Update wird ab der Software Version",
    "2.1.0 für den KOSTAL Smart Energy Meter unterstützt.",
    "Wenn eine Software Version kleiner 2.1.0 installiert ist,",
    "muss die Software Version 2.1.0 oder höher zuerst",
]
RIGHT = [
    "manuell über den KOSTAL Smart Energy Meter Webserver",
    "installiert werden, bevor die AutoUpdate Funktion aktiviert",
    "werden kann. Wenn die neueste Version bereits installiert",
    "ist, springen Sie zu Schritt 4.",
]


def _build(tmp_project, left: list[str], right_column_first: bool) -> str:
    d = fitz.open()
    page = d.new_page()
    columns = [(321.2, RIGHT), (63.2, left)] if right_column_first else [(63.2, left), (321.2, RIGHT)]
    for x, lines in columns:
        for n, text in enumerate(lines):
            page.insert_text((x, 225 + 12 * n), text, fontsize=9)
    page.insert_text((63.2, 320), "Schritt 1 - Download der aktuellen Software.", fontsize=9)
    d.save(tmp_project / "input" / "columns.pdf")
    return "columns"


def _paragraphs(doc, cwd):
    result = run_script(
        "extract-text/scripts/extract_text.py",
        "--doc",
        doc,
        "--pages",
        "1",
        "--body-size",
        "9",
        cwd=cwd,
    )
    assert result.returncode == 0, result.stderr
    shard = json.loads(paths.shard_path(doc, 1, "text").read_text())
    return [el["text"] for el in shard["elements"]]


def test_two_columns_are_one_paragraph_left_column_first(tmp_project):
    # The guide's content stream draws the right column first.
    doc = _build(tmp_project, LEFT, right_column_first=True)
    assert _paragraphs(doc, tmp_project) == [
        " ".join(LEFT + RIGHT),
        "Schritt 1 - Download der aktuellen Software.",
    ]


def test_a_column_that_ends_a_sentence_is_its_own_paragraph(tmp_project):
    left = LEFT[:3] + ["muss die Software Version 2.1.0 oder höher zuerst sein."]
    doc = _build(tmp_project, left, right_column_first=False)
    assert _paragraphs(doc, tmp_project)[:2] == [" ".join(left), " ".join(RIGHT)]
