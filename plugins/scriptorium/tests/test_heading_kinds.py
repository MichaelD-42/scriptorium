"""Headings in a document with no TOC that the bold-and-larger rule missed
(KSEM AutoUpdate guide): a title in a light weight at almost three times
the body size, and a subheading at body size set apart only by an accent
colour and a heavier weight (Helvetica Neue "Md")."""

import json

import fitz

import paths
from conftest import load_script, run_script

extract_text = load_script("extract-text/scripts/extract_text.py", "extract_text_heading_kinds")

BLUE = (0.11, 0.33, 0.54)


def _headings(tmp_project):
    d = fitz.open()
    page = d.new_page()
    page.insert_text((63, 140), "Software aktualisieren", fontsize=25, fontname="helv", color=BLUE)
    page.insert_text((63, 200), "Aktualisierung auf neueste Version", fontsize=9, fontname="hebo", color=BLUE)
    page.insert_text((63, 230), "Das automatische Update wird ab der Software Version 2.1.0 unterstuetzt.", fontsize=9)
    page.insert_text((63, 260), "www.kostal-solar-electric.com/download", fontsize=9, fontname="helv", color=BLUE)
    page.insert_text((63, 290), "Achtung: Geraet nicht ausschalten.", fontsize=9, fontname="hebo", color=(0.8, 0.1, 0.1))
    page.insert_text((63, 320), "Weitere Hinweise folgen in diesem Abschnitt der Anleitung.", fontsize=9)
    d.save(tmp_project / "input" / "kinds.pdf")
    for script, args in (
        ("pdf-triage/scripts/triage.py", ()),
        ("extract-text/scripts/extract_text.py", ("--pages", "1", "--body-size", "9")),
    ):
        result = run_script(script, "--doc", "kinds", *args, cwd=tmp_project)
        assert result.returncode == 0, result.stderr
    elements = json.loads(paths.shard_path("kinds", 1, "text").read_text())["elements"]
    return [(e["type"], e.get("level"), e["text"]) for e in elements]


def test_large_light_title_and_accent_subheading_are_headings(tmp_project):
    assert _headings(tmp_project) == [
        ("heading", 1, "Software aktualisieren"),
        ("heading", 2, "Aktualisierung auf neueste Version"),
        ("paragraph", None, "Das automatische Update wird ab der Software Version 2.1.0 unterstuetzt."),
        ("paragraph", None, "www.kostal-solar-electric.com/download"),
        ("paragraph", None, "Achtung: Geraet nicht ausschalten."),
        ("paragraph", None, "Weitere Hinweise folgen in diesem Abschnitt der Anleitung."),
    ]


def test_medium_weight_font_name_is_heavy():
    assert extract_text.is_heavy_span({"font": "HelveticaNeueLTW1G-Md", "flags": 4})
    assert extract_text.is_heavy_span({"font": "Arial-BoldMT", "flags": 0})
    assert not extract_text.is_heavy_span({"font": "HelveticaNeueLTW1G-Lt", "flags": 4})
    assert not extract_text.is_heavy_span({"font": "Times-Roman", "flags": 0})
