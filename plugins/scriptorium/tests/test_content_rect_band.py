"""Follow-up R10: the furniture bands follow a repeated inner frame rect.

Some documents draw an inner content frame on every page and put the title
block below it. The title block then starts above the fixed 12% bottom band
(y 0.88 of the page height), so its upper lines were never furniture. When a
frame rect repeats on at least 80% of the body pages, triage records it as
`furniture["content_rect"]`, and the bands are the page area outside it:
top band y < rect.y0, bottom band y > rect.y1. `lib/furniture.py`'s
`band_limits` is the one helper.

Follow-up R13: the bands are exactly the area outside the rect (no 12%
minimum), and the content rect must be the INNER rect: the qualifying rect
with body text inside it and text (the title block) outside it on most body
pages. An outer page border holds the title block too, so it never
qualifies, and a document with only an outer border keeps the 12% band.
"""

import json
from pathlib import Path

import elements as elements_lib
import fitz  # PyMuPDF
import furniture as furniture_lib
import paths
from conftest import load_script, run_script

gates = load_script("grade-output/scripts/gates.py", "gates_module_content_rect")

W, H = 595.0, 842.0
PAGES = 5
FRAME = [42.0, 28.0, 558.0, 720.0]  # ends at y 0.855 of the page
TITLE_LABEL = "Document Title"
TITLE_VALUE = "Synthetic Project Specification"
BODY_NEAR_FRAME = "Body line just inside the frame bottom."
BODY_LINE = [60.0, 110.0, 300.0, 122.0]
TITLE_LINE = [60.0, 724.0, 200.0, 731.0]


def _make_pdf(path: Path, with_frame: bool) -> None:
    doc = fitz.open()
    for n in range(1, PAGES + 1):
        page = doc.new_page(width=W, height=H)
        if with_frame:
            page.draw_rect(fitz.Rect(*FRAME), width=0.8)
        page.insert_text((60, 120), f"Ordinary body text on page {n}.", fontsize=10)
        page.insert_text(
            (60, 714), BODY_NEAR_FRAME, fontsize=8
        )  # top ~0.84, bottom ~0.85
        page.insert_text((60, 731), TITLE_LABEL, fontsize=7)  # top ~0.861
        page.insert_text((60, 742), TITLE_VALUE, fontsize=7)  # top ~0.874
        page.insert_text((60, 790), f"page {n} ({PAGES})", fontsize=7)
    doc.save(str(path))
    doc.close()


def _run_ok(relpath: str, *args: str, cwd) -> str:
    result = run_script(relpath, *args, cwd=cwd)
    assert result.returncode == 0, f"{relpath} failed\n{result.stdout}\n{result.stderr}"
    return result.stdout


def _pipeline(tmp_project, doc: str, with_frame: bool) -> tuple[dict, list[str]]:
    _make_pdf(tmp_project / "input" / f"{doc}.pdf", with_frame)
    _run_ok("pdf-triage/scripts/triage.py", "--doc", doc, cwd=tmp_project)
    triage = json.loads(paths.triage_json(doc).read_text())
    pages = ",".join(str(n) for n in range(1, PAGES + 1))
    _run_ok(
        "extract-text/scripts/extract_text.py",
        "--doc",
        doc,
        "--pages",
        pages,
        "--body-size",
        str(triage["body_size"]),
        cwd=tmp_project,
    )
    texts = []
    for n in range(1, PAGES + 1):
        shard = json.loads(paths.shard_path(doc, n, "text").read_text())
        texts.extend(e.get("text", "") for e in shard["elements"])
    return triage, texts


class TestBandLimits:
    def test_no_rect_keeps_the_twelve_percent_band(self):
        top, bottom = furniture_lib.band_limits(H, None)
        assert round(top, 2) == round(0.12 * H, 2) and round(bottom, 2) == round(
            0.88 * H, 2
        )

    def test_bands_are_exactly_outside_the_rect(self):
        assert furniture_lib.band_limits(H, FRAME) == (FRAME[1], FRAME[3])

    def test_find_content_rect_needs_eighty_percent_of_body_pages(self):
        frames = [{"bbox": FRAME, "page_count": 4}]
        lines = {n: [BODY_LINE, TITLE_LINE] for n in range(1, 7)}
        assert furniture_lib.find_content_rect(frames, [], 5, W, H, lines) == FRAME
        assert furniture_lib.find_content_rect(frames, [], 6, W, H, lines) is None

    def test_outer_border_with_the_title_block_inside_is_not_the_content_rect(self):
        outer = [20.0, 20.0, 575.0, 822.0]
        frames = [{"bbox": outer, "page_count": 5}]
        lines = {n: [BODY_LINE, TITLE_LINE] for n in range(1, 6)}
        assert furniture_lib.find_content_rect(frames, [], 5, W, H, lines) is None

    def test_inner_rect_wins_over_the_outer_border(self):
        outer = [20.0, 20.0, 575.0, 822.0]
        frames = [{"bbox": outer, "page_count": 5}, {"bbox": FRAME, "page_count": 5}]
        lines = {n: [BODY_LINE, TITLE_LINE] for n in range(1, 6)}
        assert furniture_lib.find_content_rect(frames, [], 5, W, H, lines) == FRAME

    def test_digit_only_pattern_does_not_hit_a_cell_near_the_top_inside_the_rect(self):
        cell = [60.0, 60.0, 80.0, 70.0]  # inside the rect, but in the old 12% band
        assert not furniture_lib.in_furniture_band(cell, H, FRAME)
        assert furniture_lib.patterns_for_element({"#", "DocNo#"}, cell, H, FRAME) == {"DocNo#"}


class TestWithInnerFrame:
    def test_title_block_lines_are_furniture_and_removed(self, tmp_project):
        triage, texts = _pipeline(tmp_project, "inner_frame", with_frame=True)
        furniture = triage["furniture"]
        assert furniture_lib.bbox_matches(furniture["content_rect"], FRAME)
        keys = {p["masked"] for p in furniture["line_patterns"]}
        assert furniture_lib.furniture_key(TITLE_LABEL) in keys
        assert furniture_lib.furniture_key(TITLE_VALUE) in keys
        assert furniture_lib.furniture_key(BODY_NEAR_FRAME) not in keys
        joined = "\n".join(texts)
        assert TITLE_LABEL not in joined and TITLE_VALUE not in joined
        assert texts.count(BODY_NEAR_FRAME) == PAGES

    def test_merge_filter_and_gate_use_the_same_bands(self):
        furniture = {
            **furniture_lib.empty_furniture(),
            "content_rect": FRAME,
            "line_patterns": [{"masked": "#"}],
        }
        in_band = {
            "type": "paragraph",
            "text": "42",
            "bbox": [60.0, 724.0, 80.0, 731.0],
        }
        inside = {"type": "paragraph", "text": "42", "bbox": [60.0, 700.0, 80.0, 708.0]}
        kept, removed = elements_lib.remove_furniture_lines(
            [in_band, inside], {"#"}, H, furniture_lib.content_rect(furniture)
        )
        assert removed == 1 and kept == [inside]
        doc_data = {
            "doc": "x",
            "pages": {1: {"page_number": 1, "elements": [in_band, inside]}},
        }
        result = gates.check_furniture_absent(
            doc_data, furniture, Path("nonexistent"), {1: H}
        )
        assert [o["page"] for o in result["offenders"]] == [1]


class TestWithoutFrame:
    def test_twelve_percent_behaviour_is_unchanged(self, tmp_project):
        triage, texts = _pipeline(tmp_project, "no_frame", with_frame=False)
        assert triage["furniture"].get("content_rect") is None
        keys = {p["masked"] for p in triage["furniture"]["line_patterns"]}
        assert furniture_lib.furniture_key(TITLE_LABEL) not in keys
        assert "page#(#)" in keys
        assert texts.count(TITLE_LABEL) == PAGES


class TestFigureBandUsesTheContentRect:
    """Follow-up R13: lib/figures.py's cluster band test uses the same
    band_limits, so a figure near the top of the content rect is kept."""

    def test_figure_near_the_top_inside_the_rect_is_kept(self, tmp_path):
        import figures as figures_lib

        path = tmp_path / "top_figure.pdf"
        doc = fitz.open()
        page = doc.new_page(width=W, height=H)
        page.draw_rect(fitz.Rect(200, 40, 300, 90), width=1)
        page.draw_rect(fitz.Rect(330, 40, 430, 90), width=1)
        page.draw_line((300, 65), (330, 65), width=1)
        doc.save(str(path))
        doc.close()
        with fitz.open(str(path)) as document:
            plain, plain_excluded = figures_lib.detect_figure_regions_with_exclusions(document[0], 1, path)
            framed, _ = figures_lib.detect_figure_regions_with_exclusions(document[0], 1, path, content_rect=FRAME)
        assert plain == [] and [r["reason"] for r in plain_excluded] == ["furniture_band"]
        assert len(framed) == 1
