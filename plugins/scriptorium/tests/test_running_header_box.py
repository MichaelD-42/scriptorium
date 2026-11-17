"""A running header drawn as a ruled box of many thin filled rects, with a
logo strip above it, that reaches deeper than the 12% furniture band. Its
four text lines must still be furniture, its cells must not become tables,
and a paragraph cut by the page break must still join."""

import json

import elements as elements_lib
import fitz  # PyMuPDF
import furniture as furniture_lib
import paths
from conftest import load_script, run_script

W, H = 595.0, 842.0
PAGES = 5
HEADER_BOTTOM = 167.5
triage = load_script("pdf-triage/scripts/triage.py", "triage_header_box")


def _fill(page, x0, y0, x1, y1) -> None:
    page.draw_rect(fitz.Rect(x0, y0, x1, y1), color=None, fill=(0, 0, 0), width=0)


def _header(page, number: int) -> None:
    """Only the logo strip and the box's top rule start in the 12% band
    (101 pt) and they end at 96; the rules and cell borders below them
    start 15.5 pt and more lower, so the box is found by growing."""
    page.draw_rect(fitz.Rect(55, 28, 543, 82), color=None, fill=(0.85, 0.85, 0.85), width=0)  # logo strip
    rows = (95.5, 111.5, 131.3, 147.3, HEADER_BOTTOM - 0.5)
    for y in rows:
        _fill(page, 53, y, 545, y + 0.5)
    for top, bottom in zip(rows[1:], rows[2:]):
        for x in (53.0, 544.5) + ((346.0, 468.0) if top >= 131 else ()):
            _fill(page, x, top, x + 0.5, bottom + 0.5)
    page.insert_text((60, 102), "Project label    Owner label", fontsize=6, fontname="hebo")
    page.insert_text((60, 125), "Synthetic project value", fontsize=10)
    page.insert_text((60, 138), "Status label    Version label", fontsize=6, fontname="hebo")
    page.insert_text((60, 161), f"Released value    {number} ({PAGES})", fontsize=10)
    page.insert_text((60, 795), "Synthetic footer title v1.0", fontsize=10)


def _table(page, top: float, rows: int) -> None:
    xs = (93, 250, 400, 530)
    bottom = top + rows * 14
    for x in xs:
        page.draw_line((x, top), (x, bottom), width=0.5)
    for r in range(rows + 1):
        page.draw_line((xs[0], top + r * 14), (xs[-1], top + r * 14), width=0.5)
    for r in range(rows):
        for c, x in enumerate(xs[:-1]):
            page.insert_text((x + 3, top + r * 14 + 10), f"r{r}c{c}", fontsize=8)


def _doc(path) -> None:
    pdf = fitz.open()
    for n in range(1, PAGES + 1):
        page = pdf.new_page(width=W, height=H)
        _header(page, n)
    first, second = pdf[0], pdf[1]
    first.insert_text((93, 220), "Opening paragraph of the body text.", fontsize=10)
    y = 700
    for line in ("A paragraph near the bottom of the first page that runs on", "and on over several lines and is cut by the page", "break in the middle of its last sentence and"):
        first.insert_text((93, y), line, fontsize=10)
        y += 13
    second.insert_text((93, 220), "continues here on the second page to its end.", fontsize=10)
    _table(pdf[2], 775 - 10 * 14, 10)  # ends at y = 775, below the 88% line
    for n in (3, 4, 5):
        pdf[n - 1].insert_text((93, 220), f"Body text of page {n}.", fontsize=10)
    pdf.save(str(path))
    pdf.close()


def _run(tmp_project, doc: str) -> None:
    for args in (
        ("pdf-triage/scripts/triage.py", "--doc", doc),
        ("extract-text/scripts/extract_text.py", "--doc", doc, "--pages", ",".join(str(n) for n in range(1, PAGES + 1))),
        ("assemble-output/scripts/merge.py", "--doc", doc),
    ):
        result = run_script(*args, cwd=tmp_project)
        assert result.returncode == 0, f"{args[0]}: {result.stderr}"


def test_header_box_lines_are_furniture_and_joins_work(tmp_project):
    doc = "header_box"
    _doc(tmp_project / "input" / f"{doc}.pdf")
    _run(tmp_project, doc)
    furniture = json.loads(paths.triage_json(doc).read_text(encoding="utf-8"))["furniture"]
    assert abs(furniture["header_limit"] - HEADER_BOTTOM) <= 2
    assert furniture["content_rect"] is None
    top = [p for p in furniture["line_patterns"] if p["edge"] == "top"]
    assert len(top) == 4, top
    assert any(p["edge"] == "bottom" and "footer" in p["masked"] for p in furniture["line_patterns"])

    pages = json.loads(paths.elements_json(doc).read_text(encoding="utf-8"))["pages"]
    for page in pages:
        for el in page["elements"]:
            assert el["bbox"][3] > HEADER_BOTTOM + 1, (page["page_number"], el)
    joined = [el for el in pages[0]["elements"] if el.get("pages") == [1, 2]]
    assert len(joined) == 1 and joined[0]["text"].endswith("to its end.")
    assert not any(el.get("text", "").startswith("continues") for el in pages[1]["elements"])
    tables = [el for el in pages[2]["elements"] if el["type"] == "table"]
    assert len(tables) == 1 and len(tables[0]["rows"]) == 10


def test_thin_rule_under_one_line_header_keeps_the_12_percent_band():
    drawings = [{"bbox": [53, 90, 545, 90.5], "type": "f", "page_count": 5}]
    assert triage._header_footer_limits(drawings, W, H) == (None, None)
    furniture = {"header_limit": None, "footer_limit": None, "content_rect": None}
    assert furniture_lib.page_band_rect(furniture, W, H) is None


def test_header_limit_band_applies_only_on_the_body_page_size():
    furniture = {"content_rect": None, "content_rect_page_size": [W, H], "header_limit": 167.5, "footer_limit": None}
    assert furniture_lib.page_band_rect(furniture, W, H) == (167.5, 0.88 * H)
    rect = furniture_lib.page_band_rect(furniture, W, H)
    # The bottom side has no drawn limit: a body paragraph reaching into
    # the 12% band, but not wholly inside it, stays body.
    assert not furniture_lib.in_furniture_band([93, 720, 533, 777], H, rect)
    assert furniture_lib.in_furniture_band([60, 152, 525, 163], H, rect)
    assert furniture_lib.page_table_rect(furniture, W, H) == [0.0, 167.5, W, H]
    assert furniture_lib.page_band_rect(furniture, H, W) is None  # a landscape page
    assert furniture_lib.page_table_rect(furniture, H, W) is None


def _pages(region_bottom: float) -> dict:
    return {
        1: {"page_number": 1, "elements": [
            {"type": "paragraph", "text": "A sentence cut by the page break and", "bbox": [93, 700, 531, 771]},
        ]},
        2: {"page_number": 2, "excluded_regions": [{"bbox": [53, 28, 545, region_bottom], "reason": "repeated_drawing"}],
            "elements": [
                {"type": "table", "rows": [[""], [""]], "bbox": [55, 28, 543, 82]},
                {"type": "paragraph", "text": "Leaked header value", "bbox": [60, 116, 434, 128]},
                {"type": "paragraph", "text": "continues on the next page.", "bbox": [93, 210, 500, 222]},
            ]},
    }


def test_join_skips_leaked_elements_in_a_header_box():
    pages = _pages(167.5)
    elements_lib.apply_page_break_joins(pages, {}, {1: H, 2: H}, {1: W, 2: W})
    assert pages[1]["elements"][0]["pages"] == [1, 2]
    assert [el["text"] for el in pages[2]["elements"] if el["type"] == "paragraph"] == ["Leaked header value"]


def test_join_does_not_skip_on_a_page_tall_repeated_region_or_without_geometry():
    for pages, heights in ((_pages(800.0), {1: H, 2: H}), (_pages(167.5), None)):
        elements_lib.apply_page_break_joins(pages, {}, heights)
        assert "pages" not in pages[1]["elements"][0]


def test_join_skips_elements_above_the_header_limit():
    pages = _pages(167.5)
    del pages[2]["excluded_regions"]
    furniture = {"content_rect": None, "content_rect_page_size": [W, H], "header_limit": 167.5, "footer_limit": None}
    elements_lib.apply_page_break_joins(pages, furniture, {1: H, 2: H}, {1: W, 2: W})
    assert pages[1]["elements"][0]["pages"] == [1, 2]
