"""Follow-up R31: a screenshot printed as a mosaic of bitmap crops on one
grey panel, with vector number badges on top (KSEM AutoUpdate guide), is
one figure: the rendered panel. A single icon in a coloured callout box
stays a plain bitmap, and the callout's text stays body text."""

import json

import fitz

import paths
from conftest import run_script


def _pixmap(shade: int):
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 30), 0)
    pix.set_rect(pix.irect, (shade, 120, 200))
    return pix


def _build(tmp_project) -> str:
    d = fitz.open()
    page = d.new_page()
    page.insert_text(
        (72, 100), "Schritt 2 - Login in den Webserver des Geraets.", fontsize=9
    )
    # The mosaic: grey panel, three crops, a dark badge with its number.
    page.draw_rect(fitz.Rect(322, 405, 534, 508), color=None, fill=(0.90, 0.91, 0.93))
    page.insert_image(fitz.Rect(329, 411, 401, 429), pixmap=_pixmap(10))
    page.insert_image(fitz.Rect(329, 438, 401, 457), pixmap=_pixmap(40))
    page.insert_image(fitz.Rect(444, 415, 508, 493), pixmap=_pixmap(70))
    page.draw_rect(fitz.Rect(406, 428, 418, 441), color=None, fill=(0.11, 0.09, 0.10))
    page.insert_text((409, 438), "1", fontsize=7, color=(1, 1, 1))
    page.insert_text((330, 470), "192.168.172.20", fontsize=6)
    # A callout: one icon and its text on a tinted box.
    page.draw_rect(fitz.Rect(60, 600, 540, 650), color=None, fill=(1.0, 0.95, 0.80))
    page.insert_image(fitz.Rect(66, 610, 96, 640), pixmap=_pixmap(200))
    page.insert_text(
        (110, 628),
        "Achtung: Das Geraet waehrend des Updates nicht ausschalten.",
        fontsize=9,
    )
    d.save(tmp_project / "input" / "mosaic.pdf")
    return "mosaic"


def test_mosaic_panel_is_one_figure_and_callout_icon_stays_a_bitmap(tmp_project):
    doc = _build(tmp_project)
    for script, args in (
        ("pdf-triage/scripts/triage.py", ()),
        ("extract-text/scripts/extract_text.py", ("--pages", "1", "--body-size", "9")),
        ("extract-images/scripts/extract_images.py", ("--pages", "1")),
    ):
        result = run_script(script, "--doc", doc, *args, cwd=tmp_project)
        assert result.returncode == 0, result.stderr

    images = json.loads(paths.shard_path(doc, 1, "image").read_text())["elements"]
    boxes = sorted((round(e["bbox"][1]), e["kind"]) for e in images)
    assert len(images) == 2, boxes
    panel = next(e for e in images if e["kind"] != "bitmap")
    assert [round(v) for v in panel["bbox"]] == [322, 405, 534, 508]
    assert "192.168.172.20" in panel["figure_text"]
    assert (tmp_project / "output" / doc / panel["asset"]).exists()

    body = [
        e["text"]
        for e in json.loads(paths.shard_path(doc, 1, "text").read_text())["elements"]
        if "text" in e
    ]
    assert not any("192.168" in t for t in body)
    assert any("Achtung" in t for t in body)


def test_table_cell_holding_a_panel_does_not_repeat_its_text(tmp_project):
    """A layout table (step text | screenshot) whose screenshot cell holds a
    mosaic panel: the panel's screen text is the figure's, not the cell's."""
    d = fitz.open()
    page = d.new_page()
    for x in (62, 293, 551):
        page.draw_line(fitz.Point(x, 381), fitz.Point(x, 530))
    for y in (381, 530):
        page.draw_line(fitz.Point(62, y), fitz.Point(551, y))
    page.insert_text((66, 395), "Schritt 2 - Login", fontsize=9)
    page.insert_text((66, 407), "IP-Adresse im Browser eingeben.", fontsize=9)
    page.draw_rect(fitz.Rect(322, 405, 534, 508), color=None, fill=(0.90, 0.91, 0.93))
    page.insert_image(fitz.Rect(329, 411, 401, 429), pixmap=_pixmap(10))
    page.insert_image(fitz.Rect(444, 415, 508, 493), pixmap=_pixmap(70))
    page.insert_text((330, 470), "192.168.172.20", fontsize=6)
    d.save(tmp_project / "input" / "layout.pdf")
    for script, args in (
        ("pdf-triage/scripts/triage.py", ()),
        ("extract-text/scripts/extract_text.py", ("--pages", "1", "--body-size", "9")),
    ):
        result = run_script(script, "--doc", "layout", *args, cwd=tmp_project)
        assert result.returncode == 0, result.stderr

    elements = json.loads(paths.shard_path("layout", 1, "text").read_text())["elements"]
    text = json.dumps(elements, ensure_ascii=False)
    assert "Schritt 2 - Login" in text
    assert "192.168" not in text
