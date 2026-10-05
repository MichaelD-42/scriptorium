"""Re-review 2 I2: the content rect is used only on a page it fits.

Triage measures `furniture["content_rect"]` on the document's body page size
and stores that size as `content_rect_page_size`. `furniture.page_content_rect`
returns the rect for one page only when the page has that size (within
FRAME_MATCH_TOLERANCE) and the rect fits inside the page; otherwise None.
Every stage asks it: `figures.page_tables`, the band callers, the grid-table
reference area and triage. Before, a landscape page in a framed portrait
document was cropped to the portrait rect, its wide table was lost and its
rulings became a captionless image.
"""

import json

import fitz  # PyMuPDF
import furniture as furniture_lib
import paths
from conftest import run_script

RECT = [42.0, 28.0, 558.0, 719.0]
PORTRAIT = (595.0, 842.0)
LANDSCAPE = (842.0, 595.0)
TABLE_XS = [450, 560, 680, 800]


def _framed(page, n: int) -> None:
    page.draw_rect(fitz.Rect(*RECT), width=0.8)
    page.insert_text((60, 60), f"Body heading on page {n}", fontsize=12)
    page.insert_text(
        (60, 90), f"Ordinary body text line {n} inside the frame.", fontsize=10
    )
    page.insert_text((60, 745), "Document Title Synthetic", fontsize=8)
    page.insert_text((60, 770), f"Page {n} of 7", fontsize=8)


def _landscape(page) -> None:
    page.insert_text((60, 60), "Landscape page with a wide table", fontsize=12)
    for r in range(5):
        page.draw_line(
            (TABLE_XS[0], 100 + r * 25), (TABLE_XS[-1], 100 + r * 25), width=0.5
        )
    for x in TABLE_XS:
        page.draw_line((x, 100), (x, 200), width=0.5)
    for r in range(4):
        for c in range(3):
            page.insert_text(
                (TABLE_XS[c] + 4, 100 + r * 25 + 16), f"c{r}{c}", fontsize=8
            )


class TestPageContentRect:
    FURNITURE = {"content_rect": RECT, "content_rect_page_size": list(PORTRAIT)}

    def test_same_size_page_gets_the_rect(self):
        assert furniture_lib.page_content_rect(self.FURNITURE, *PORTRAIT) == RECT

    def test_within_tolerance(self):
        assert furniture_lib.page_content_rect(self.FURNITURE, 596.5, 843.0) == RECT

    def test_other_size_page_gets_none(self):
        assert furniture_lib.page_content_rect(self.FURNITURE, *LANDSCAPE) is None

    def test_rect_that_does_not_fit_gets_none(self):
        legacy = {"content_rect": RECT}  # no stored page size
        assert furniture_lib.page_content_rect(legacy, *PORTRAIT) == RECT
        assert furniture_lib.page_content_rect(legacy, *LANDSCAPE) is None

    def test_no_rect(self):
        assert furniture_lib.page_content_rect({}, *PORTRAIT) is None

    def test_landscape_bands_fall_back_to_twelve_percent(self):
        rect = furniture_lib.page_content_rect(self.FURNITURE, *LANDSCAPE)
        height = LANDSCAPE[1]
        assert furniture_lib.band_limits(height, rect) == (0.12 * height, 0.88 * height)


class TestLandscapePageInFramedDocument:
    def test_wide_table_is_a_table(self, tmp_project):
        doc = "landscape"
        pdf = fitz.open()
        for n in range(1, 7):
            _framed(pdf.new_page(width=PORTRAIT[0], height=PORTRAIT[1]), n)
        _landscape(pdf.new_page(width=LANDSCAPE[0], height=LANDSCAPE[1]))
        pdf.save(str(tmp_project / "input" / f"{doc}.pdf"))
        pdf.close()
        for args in (
            ("pdf-triage/scripts/triage.py", "--doc", doc),
            ("extract-text/scripts/extract_text.py", "--doc", doc, "--pages", "7"),
            ("extract-images/scripts/extract_images.py", "--doc", doc, "--pages", "7"),
        ):
            result = run_script(*args, cwd=tmp_project)
            assert result.returncode == 0, f"{args[0]}: {result.stderr}"
        triage = json.loads(paths.triage_json(doc).read_text())
        assert triage["furniture"]["content_rect"] is not None
        assert triage["furniture"]["content_rect_page_size"] == list(PORTRAIT)
        text = json.loads(paths.shard_path(doc, 7, "text").read_text())
        image = json.loads(paths.shard_path(doc, 7, "image").read_text())
        tables = [e for e in text["elements"] if e["type"] == "table"]
        assert len(tables) == 1
        assert len(tables[0]["rows"]) == 4 and len(tables[0]["rows"][0]) == 3
        assert [e for e in image["elements"] if e["type"] == "image"] == []
