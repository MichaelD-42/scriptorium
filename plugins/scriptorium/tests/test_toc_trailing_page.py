"""Follow-up R15: two more printed-TOC entry shapes.

(a) A numbered entry line with no leader that ends in whitespace and an
    integer: the integer is the page, when it is at most the document page
    count and at least the previous entry's page. The number may also sit
    alone with its title at the same y ("8" / "TITLE 58").
(b) A dot leader is a run of 2 or more dots ("Title .. 74").
"""

import toc

YS = [48.9, 48.9, 70.5]


class TestTrailingPage:
    def test_number_and_title_at_the_same_y(self):
        lines = ["8", "A CHAPTER TITLE 58", "8.1 Next entry .......... 58"]
        entries, unparsed = toc.parse_toc_page_lines(
            lines, YS, page_count=115, min_page=53
        )
        assert entries[0] == {
            "number": "8",
            "title": "A CHAPTER TITLE",
            "page": 58,
            "level": 1,
        }
        assert [e["number"] for e in entries] == ["8", "8.1"]
        assert unparsed == []

    def test_number_and_title_on_one_line(self):
        lines = ["8 A CHAPTER TITLE 58", "8.1 Next entry .......... 58"]
        entries, unparsed = toc.parse_toc_page_lines(
            lines, [48.9, 70.5], page_count=115, min_page=53
        )
        assert entries[0] == {
            "number": "8",
            "title": "A CHAPTER TITLE",
            "page": 58,
            "level": 1,
        }
        assert unparsed == []

    def test_page_above_the_page_count_is_not_a_page(self):
        lines = ["8 A CHAPTER TITLE 580", "8.1 Next entry .......... 58"]
        entries, unparsed = toc.parse_toc_page_lines(
            lines, [48.9, 70.5], page_count=115, min_page=53
        )
        assert [e["number"] for e in entries] == ["8.1"]
        assert unparsed == ["8 A CHAPTER TITLE 580"]

    def test_page_below_the_previous_entry_is_not_a_page(self):
        lines = [
            "7.1 Earlier entry .......... 57",
            "8 MODEL 3",
            "8.1 Next entry .......... 58",
        ]
        entries, unparsed = toc.parse_toc_page_lines(
            lines, [30.0, 48.9, 70.5], page_count=115
        )
        assert [e["number"] for e in entries] == ["7.1", "8.1"]
        assert unparsed == ["8 MODEL 3"]

    def test_previous_page_carries_across_toc_pages(self, tmp_path):
        """parse_printed_toc_with_unparsed passes the last entry's page on."""
        entries, unparsed = toc.parse_toc_page_lines(
            ["9 LATE CHAPTER 60"], [40.0], page_count=115, min_page=61
        )
        assert entries == [] and unparsed == ["9 LATE CHAPTER 60"]


class TestTwoDotLeader:
    def test_two_dot_leader_is_a_leader(self):
        entries, unparsed = toc.parse_toc_page_lines(["9.4.3 A title .. 74"], [89.0])
        assert entries == [
            {"number": "9.4.3", "title": "A title", "page": 74, "level": 3}
        ]
        assert unparsed == []

    def test_two_dot_leader_counts_for_toc_page_detection(self):
        assert toc.DOT_LEADER_RE.search("A title .. 74")
