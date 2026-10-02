"""Follow-up R12: a page-frame table with a slightly different bbox.

The page frame and its title block are ruled lines, and pdfplumber reads
them as one page-sized table. `frame_tables` removes it where it sits at the
repeated bbox. On a page where it comes out a few points different, it was
a "real" table that swallowed the page's headings and paragraphs into its
cells, title block included. With a `content_rect`, `figures.page_tables`
now detects tables on the page cropped to that rect (coordinates kept), and
drops a table there that covers more than 60% of the rect and matches it
within the frame tolerance: that is the frame again.
"""

import json

import fitz  # PyMuPDF
import paths
from conftest import run_script

W, H = 595.0, 842.0
PAGES = 4
ODD_PAGE = 3
INNER = (42.0, 28.0, 558.0, 720.0)
OUTER = (42.0, 28.0, 558.0, 802.0)
TITLE_LABEL = "Title block label"


def _page(doc, n: int) -> None:
    page = doc.new_page(width=W, height=H)
    page.draw_rect(fitz.Rect(*OUTER), width=0.8)
    page.draw_rect(fitz.Rect(*INNER), width=0.8)
    page.draw_line((42, 760), (558, 760), width=0.5)
    page.draw_line((300, 720), (300, 802), width=0.5)
    if n == ODD_PAGE:
        # A narrow extra cell left of the title block, so pdfplumber's frame
        # table is 6 pt wider on this page only.
        for p1, p2 in (((36, 720), (42, 720)), ((36, 802), (42, 802)), ((36, 720), (36, 802))):
            page.draw_line(p1, p2, width=0.5)
    page.insert_text((50, 742), TITLE_LABEL, fontsize=7)
    page.insert_text((310, 742), "Doc No. SYN-0012", fontsize=7)
    page.insert_text((50, 785), f"page {n} ({PAGES})", fontsize=7)
    page.insert_text(
        (60, 100), f"{n} Section heading {n}", fontsize=16, fontname="hebo"
    )
    page.insert_text(
        (60, 130), f"Body paragraph text on page {n} of the document.", fontsize=10
    )
    if n == 2:
        x0, y0 = 60.0, 300.0
        for r in range(4):
            page.draw_line((x0, y0 + r * 20), (x0 + 300, y0 + r * 20), width=0.5)
        for c in range(4):
            page.draw_line((x0 + c * 100, y0), (x0 + c * 100, y0 + 60), width=0.5)
        for r in range(3):
            for c in range(3):
                page.insert_text(
                    (x0 + c * 100 + 5, y0 + r * 20 + 14), f"r{r}c{c}", fontsize=9
                )


def _run(tmp_project) -> tuple[dict, dict]:
    doc = fitz.open()
    for n in range(1, PAGES + 1):
        _page(doc, n)
    doc.save(str(tmp_project / "input" / "frame_crop.pdf"))
    doc.close()
    pages = ",".join(str(n) for n in range(1, PAGES + 1))
    for args in (
        ("pdf-triage/scripts/triage.py", "--doc", "frame_crop"),
        (
            "extract-text/scripts/extract_text.py",
            "--doc",
            "frame_crop",
            "--pages",
            pages,
        ),
        (
            "extract-images/scripts/extract_images.py",
            "--doc",
            "frame_crop",
            "--pages",
            pages,
        ),
    ):
        result = run_script(*args, cwd=tmp_project)
        assert result.returncode == 0, f"{args[0]}: {result.stderr}"
    triage = json.loads(paths.triage_json("frame_crop").read_text())
    shards = {
        n: json.loads(paths.shard_path("frame_crop", n, "text").read_text())
        for n in range(1, PAGES + 1)
    }
    return triage, shards


class TestFrameTableCrop:
    def test_odd_page_keeps_its_heading_and_paragraph(self, tmp_project):
        triage, shards = _run(tmp_project)
        assert triage["furniture"]["content_rect"] is not None
        odd = shards[ODD_PAGE]["elements"]
        assert "table" not in [e["type"] for e in odd]
        texts = " ".join(e.get("text", "") for e in odd)
        assert f"Section heading {ODD_PAGE}" in texts
        assert f"Body paragraph text on page {ODD_PAGE}" in texts

    def test_no_title_block_text_in_any_table(self, tmp_project):
        _triage, shards = _run(tmp_project)
        for n, shard in shards.items():
            for e in shard["elements"]:
                if e["type"] == "table":
                    cells = " ".join(str(c) for row in e["rows"] for c in row)
                    assert TITLE_LABEL not in cells and "SYN-0012" not in cells, (
                        f"page {n}"
                    )

    def test_real_table_inside_the_frame_is_unaffected(self, tmp_project):
        _triage, shards = _run(tmp_project)
        tables = [e for e in shards[2]["elements"] if e["type"] == "table"]
        assert len(tables) == 1
        assert tables[0]["rows"][0] == ["r0c0", "r0c1", "r0c2"]
