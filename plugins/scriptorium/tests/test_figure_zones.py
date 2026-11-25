"""Figure zones: a figure drawn from many small parts is one image.

A figure made of a few tiny drawings, two chart clusters and labels in a
smaller font than the body used to come out as separate crops plus loose
label paragraphs. `lib/figures.py`'s `_merge_figure_zones` joins the parts
and the label lines into one region, bounded by flow lines (body text, a
"[...]" requirement marker, a caption), so the figure renders as one crop.
An unnumbered one-line title right below the figure is its caption.

The page is synthetic: body text, a marker line, two small symbols with
labels and a legend, a two-part bar chart, a caption, more body text.
"""

import json
from pathlib import Path

import figures as figures_lib
import fitz  # PyMuPDF
import paths
from conftest import load_script, run_script

PAGE_WIDTH, PAGE_HEIGHT = 612.0, 792.0
MARKER = "[FA: DEMO-0001]"
CAPTION = "Principle sketch of the switch logic"
LABELS = [
    "Variant A",
    "Variant B",
    "Start",
    "Stable position",
    "Contact 1",
    "Contact 2",
]
gates = load_script("grade-output/scripts/gates.py", "gates_zone_module")

BODY = "This is an ordinary body sentence that runs across most of the line {}."


def _body(page, y0: float, count: int) -> None:
    for i in range(count):
        page.insert_text((72, y0 + i * 13), BODY.format(i), fontsize=10)


def _figure(page, drawings: bool = True) -> None:
    page.insert_text((440, 190), MARKER, fontsize=9)
    page.insert_text((150, 212), "Variant A", fontsize=7)
    page.insert_text((260, 212), "Variant B", fontsize=7)
    page.insert_text((140, 262), "Start", fontsize=5)
    page.insert_text((372, 242), "Stable position", fontsize=6)
    page.insert_text((80, 300), "Contact 1", fontsize=7)
    page.insert_text((80, 320), "Contact 2", fontsize=7)
    if drawings:
        # Two tiny symbols, a legend mark, and a bar chart in two clusters.
        page.draw_circle((170, 240), 12, width=1)
        page.draw_circle((280, 240), 12, width=1)
        page.draw_rect(fitz.Rect(360, 235, 366, 241), fill=(0, 0, 0))
        for left in (120, 250):
            for row in range(2):
                y = 292 + row * 20
                page.draw_rect(
                    fitz.Rect(left, y, left + 100, y + 10),
                    color=(0, 0, 0),
                    fill=(0.75, 0.75, 0.75),
                )
    page.insert_text((72, 352), CAPTION, fontsize=10)


def _make_pdf(path: Path, drawings: bool = True) -> None:
    doc = fitz.open()
    page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    _body(page, 100, 5)
    _figure(page, drawings)
    _body(page, 400, 8)
    doc.save(str(path))
    doc.close()


def _detect(path: Path):
    doc = fitz.open(str(path))
    try:
        page = doc[0]
        regions, excluded = figures_lib.detect_figure_regions_with_exclusions(
            page, 1, path, frame_tables=[], frame_drawings=[]
        )
        captions = [figures_lib.find_caption_line(page, r["bbox"]) for r in regions]
        lines = figures_lib._page_lines(page)
        return regions, excluded, captions, lines
    finally:
        doc.close()


def _line(lines, text):
    return next(l for l in lines if l["text"] == text)


def test_parts_and_labels_become_one_region(tmp_path):
    path = tmp_path / "zone.pdf"
    _make_pdf(path)
    regions, _excluded, captions, lines = _detect(path)
    assert len(regions) == 1
    zone = regions[0]
    assert zone.get("zone") is True
    for label in LABELS:
        assert figures_lib.line_in_region(_line(lines, label)["bbox"], zone["bbox"]), (
            label
        )
    # The marker above and the caption below stay outside the crop.
    assert zone["bbox"][1] >= _line(lines, MARKER)["bbox"][3]
    assert zone["bbox"][3] <= _line(lines, CAPTION)["bbox"][1]
    assert captions[0]["text"] == CAPTION


def test_labels_without_drawings_are_recorded(tmp_path):
    path = tmp_path / "labels.pdf"
    _make_pdf(path, drawings=False)
    regions, excluded, _captions, _lines = _detect(path)
    assert regions == []
    flagged = [r for r in excluded if r["reason"] == "figure_labels"]
    assert len(flagged) == 1
    doc_data = {
        "pages": {"1": {"page_number": 1, "elements": [], "excluded_regions": excluded}}
    }
    assert [w["name"] for w in gates.check_figure_without_image(doc_data)] == [
        "figure_without_image"
    ]


def test_body_paragraph_under_a_figure_is_not_a_caption(tmp_path):
    """A multi-line paragraph right below the figure keeps its lines."""
    path = tmp_path / "no_caption.pdf"
    doc = fitz.open()
    page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    _body(page, 100, 5)
    page.draw_rect(fitz.Rect(100, 200, 400, 320), width=1)
    page.draw_line((100, 260), (400, 260), width=1)
    page.insert_text(
        (72, 340), "A sentence that starts right below the figure", fontsize=10
    )
    page.insert_text(
        (72, 353), "and goes on in a second line of the paragraph.", fontsize=10
    )
    doc.save(str(path))
    doc.close()
    regions, _excluded, captions, _lines = _detect(path)
    assert len(regions) == 1
    assert captions == [None]


def test_end_to_end_one_image_and_clean_text(tmp_project):
    _make_pdf(tmp_project / "input" / "zones.pdf")
    result = run_script(
        "pdf-triage/scripts/triage.py", "--doc", "zones", cwd=tmp_project
    )
    assert result.returncode == 0, result.stderr
    for script in (
        "extract-text/scripts/extract_text.py",
        "extract-images/scripts/extract_images.py",
    ):
        result = run_script(script, "--doc", "zones", "--pages", "1", cwd=tmp_project)
        assert result.returncode == 0, result.stderr

    image_shard = json.loads(paths.shard_path("zones", 1, "image").read_text())
    images = [e for e in image_shard["elements"] if e["type"] == "image"]
    assert [(e["kind"], e["asset"], e.get("caption")) for e in images] == [
        ("vector", "assets/page1_vector1.png", CAPTION)
    ]
    assert set(LABELS) <= set(images[0]["figure_text"].split("\n"))

    text_shard = json.loads(paths.shard_path("zones", 1, "text").read_text())
    texts = [e.get("text", "") for e in text_shard["elements"]]
    assert MARKER in texts
    body = " ".join(texts)
    for label in LABELS:
        assert label not in body, label
    assert CAPTION not in body
    assert not [e for e in text_shard["elements"] if e["type"] == "table"]
