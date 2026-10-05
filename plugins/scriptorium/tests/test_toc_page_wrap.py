"""Follow-up R9: a TOC entry whose page number wraps onto its own line.

A long chapter title pushes its leader and page number onto the next line,
and that line holds only the page number:

    y=406   "5"  "VERY LONG UPPERCASE CHAPTER TITLE"     (no leader, no page)
    y=424   "53"                                           (nothing else at y)
    y=445   "5.1"  "Design rules .......... 53"

`lib/toc.py` reads this as one entry, page 53. A lone section number is
told apart from a page line by the same-y check: a section number always has
its title at its y. Every numbered line that ends up in no entry goes to
`unparsed`.
"""

from pathlib import Path

import fitz  # PyMuPDF
import toc

FILLER = [
    f"{n}.{m} Filler entry {n}.{m} .......... {n + 2}"
    for n in range(1, 4)
    for m in range(1, 7)
]


def _build_toc_pdf(path: Path) -> None:
    """One printed TOC page (18 filler leader lines, so it qualifies), then
    the wrapped-page L1 entry, its first sub-entry, and a lone-number entry
    whose title sits at the same y and carries the leader."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    y = 80.0
    for text in FILLER:
        page.insert_text((64, y), text, fontsize=10)
        y += 16
    page.insert_text((47, y + 10), "5", fontsize=16)
    page.insert_text(
        (76, y + 10), "A VERY LONG UPPERCASE CHAPTER TITLE THAT WRAPS", fontsize=16
    )
    page.insert_text((46, y + 28), "53", fontsize=16)
    page.insert_text((64, y + 50), "5.1 Design rules .......... 53", fontsize=10)
    page.insert_text((47, y + 80), "6", fontsize=16)
    page.insert_text((76, y + 80), "SHORT CHAPTER .......... 60", fontsize=16)
    doc.save(str(path))
    doc.close()


class TestPageOnlyLine:
    def test_wrapped_page_l1_entry_on_a_real_page(self, tmp_path):
        pdf = tmp_path / "toc_wrap.pdf"
        _build_toc_pdf(pdf)
        with fitz.open(pdf) as document:
            entries, toc_pages, unparsed = toc.detect_toc_with_unparsed(document)
        assert toc_pages == [1]
        by_number = {e["number"]: e for e in entries}
        assert by_number["5"] == {
            "number": "5",
            "title": "A VERY LONG UPPERCASE CHAPTER TITLE THAT WRAPS",
            "page": 53,
            "level": 1,
        }
        assert by_number["5.1"]["page"] == 53
        assert by_number["6"] == {
            "number": "6",
            "title": "SHORT CHAPTER",
            "page": 60,
            "level": 1,
        }
        assert len(entries) == len(FILLER) + 3
        assert unparsed == []

    def test_number_and_title_on_one_line_then_page_line(self):
        lines = ["5 A LONG TITLE", "53", "5.1 Next .......... 53"]
        entries, unparsed = toc.parse_toc_page_lines(lines, [406.0, 424.0, 445.0])
        assert entries[0] == {
            "number": "5",
            "title": "A LONG TITLE",
            "page": 53,
            "level": 1,
        }
        assert unparsed == []

    def test_lone_section_number_with_its_title_at_the_same_y(self):
        """The I2 shape: "7" and its leader title share a y. Not a page line."""
        lines = ["7", "Scope .......... 12", "7.1 Detail .......... 13"]
        entries, unparsed = toc.parse_toc_page_lines(lines, [100.0, 100.5, 120.0])
        assert [(e["number"], e["title"], e["page"]) for e in entries] == [
            ("7", "Scope", 12),
            ("7.1", "Detail", 13),
        ]
        assert unparsed == []

    def test_a_page_line_with_other_text_at_its_y_is_not_a_page(self):
        lines = ["5", "A LONG TITLE", "53", "Note"]
        entries, unparsed = toc.parse_toc_page_lines(
            lines, [406.0, 406.0, 424.0, 424.5]
        )
        assert entries == []
        # "53" has a word at its y, so it reads as a numbered line too.
        assert unparsed == ["5", "53"]


class TestUnparsedNumberedLines:
    def test_numbered_line_in_no_entry_is_unparsed(self):
        lines = ["4 Orphan title with nothing after it", "4.1 Next .......... 9"]
        entries, unparsed = toc.parse_toc_page_lines(lines, [100.0, 120.0])
        assert [e["number"] for e in entries] == ["4.1"]
        assert unparsed == ["4 Orphan title with nothing after it"]

    def test_footer_lines_are_not_numbered_lines(self):
        lines = ["12345678", "07", "2 ( 1 2 0 )", "1 Intro .......... 3"]
        entries, unparsed = toc.parse_toc_page_lines(
            lines, [780.0, 780.0, 784.0, 100.0]
        )
        assert [e["number"] for e in entries] == ["1"]
        assert unparsed == []
