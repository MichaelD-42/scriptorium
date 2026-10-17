"""Page furniture graphics (a logo in the header band, a colour box in the
footer band) appear once, at the top of the output, taken from page 1 --
not once per page and not dropped (KSEM AutoUpdate guide: KOSTAL logo top
right, green box bottom left). A header rule is a line, not a graphic."""

import json
import re

import fitz

import paths
from conftest import run_script


def _build(tmp_project) -> str:
    d = fitz.open()
    for n in (1, 2):
        page = d.new_page()  # 595 x 842
        page.draw_rect(
            fitz.Rect(414, 46, 550, 74), color=None, fill=(0.0, 0.3, 0.6)
        )  # logo
        page.draw_rect(
            fitz.Rect(-9, 799, 43, 850), color=None, fill=(0.69, 0.80, 0.22)
        )  # green box, bleeds off
        page.draw_line(
            fitz.Point(62, 90), fitz.Point(544, 90), color=(0, 0, 0)
        )  # header rule
        page.insert_text(
            (72, 300),
            f"Body text on page {n}, long enough to be a text layer line.",
            fontsize=9,
        )
    d.save(tmp_project / "input" / "branded.pdf")
    return "branded"


def test_band_graphics_appear_once_at_the_top(tmp_project):
    doc = _build(tmp_project)
    triage = run_script("pdf-triage/scripts/triage.py", "--doc", doc, cwd=tmp_project)
    assert triage.returncode == 0, triage.stderr
    for script, args in (
        (
            "extract-text/scripts/extract_text.py",
            ("--pages", "1,2", "--body-size", "9"),
        ),
        ("extract-images/scripts/extract_images.py", ("--pages", "1,2")),
        ("assemble-output/scripts/merge.py", ()),
        ("assemble-output/scripts/assemble.py", ("--format", "md")),
    ):
        result = run_script(script, "--doc", doc, *args, cwd=tmp_project)
        assert result.returncode == 0, result.stderr

    shard1 = json.loads(paths.shard_path(doc, 1, "image").read_text())
    shard2 = json.loads(paths.shard_path(doc, 2, "image").read_text())
    assert [[round(v) for v in f["bbox"]] for f in shard1["furniture_images"]] == [
        [414, 46, 550, 74],
        [0, 799, 43, 842],
    ]
    assert "furniture_images" not in shard2
    assert shard1["elements"] == [] and shard2["elements"] == []

    md = paths.output_file(doc, "md").read_text()
    images = re.findall(r"!\[\]\((assets/furniture\d\.png)\)", md)
    assert images == ["assets/furniture1.png", "assets/furniture2.png"]
    assert md.index(images[-1]) < md.index("Body text on page 1")
    assert all((paths.output_dir(doc) / i).exists() for i in images)
