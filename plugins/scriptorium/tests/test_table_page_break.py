"""Follow-up R21: a table cut by a page break is joined into one table.

`elements.apply_page_break_joins` now also joins tables: when page n's last
body element is a table and page n+1's first body element is a table with
the same column count and the same left and right edges (within
JOIN_X_TOLERANCE), page n+1's rows are appended to page n's table, which
gains `"pages": [n, n+1]`, and page n+1's table is removed. A first row on
page n+1 equal to page n's first row is a repeated header and is dropped.
`gates.py`'s `no_empty_pages` counts a page as filled when an element of
another page lists it in `pages`.
"""

import elements as elements_lib
from conftest import load_script

gates = load_script("grade-output/scripts/gates.py", "gates_r21")


def _table(rows, x0=64.0, x1=452.0, y0=50.0, y1=400.0) -> dict:
    return {"type": "table", "rows": rows, "bbox": [x0, y0, x1, y1]}


def _pages(first: list[dict], second: list[dict]) -> dict[int, dict]:
    return {
        1: {"page_number": 1, "tier": "text", "elements": first},
        2: {"page_number": 2, "tier": "text", "elements": second},
    }


class TestTableJoin:
    def test_continued_table_is_joined(self):
        pages = _pages(
            [
                {"type": "paragraph", "text": "Intro.", "bbox": [46, 20, 300, 30]},
                _table([["Code", "Definition"], ["A", "Alpha"]]),
            ],
            [
                _table([["B", "Beta"], ["C", "Gamma"]], y0=32),
                {"type": "paragraph", "text": "After.", "bbox": [46, 500, 300, 510]},
            ],
        )
        elements_lib.apply_page_break_joins(pages)
        tables_1 = [e for e in pages[1]["elements"] if e["type"] == "table"]
        assert tables_1[0]["rows"] == [
            ["Code", "Definition"],
            ["A", "Alpha"],
            ["B", "Beta"],
            ["C", "Gamma"],
        ]
        assert tables_1[0]["pages"] == [1, 2]
        assert [e["type"] for e in pages[2]["elements"]] == ["paragraph"]

    def test_repeated_header_is_dropped(self):
        pages = _pages(
            [_table([["Code", "Definition"], ["A", "Alpha"]])],
            [_table([["Code", "Definition"], ["B", "Beta"]], y0=32)],
        )
        elements_lib.apply_page_break_joins(pages)
        assert pages[1]["elements"][0]["rows"] == [
            ["Code", "Definition"],
            ["A", "Alpha"],
            ["B", "Beta"],
        ]

    def test_repeated_two_row_header_is_dropped(self):
        header = [["Band", "Frequency", "Limit"], ["", "", "Peak"]]
        pages = _pages(
            [_table([*header, ["1", "0.15-0.3", "70"]])],
            [_table([*header, ["2", "0.3-0.5", "66"]], y0=32)],
        )
        elements_lib.apply_page_break_joins(pages)
        assert pages[1]["elements"][0]["rows"] == [*header, ["1", "0.15-0.3", "70"], ["2", "0.3-0.5", "66"]]

    def test_other_column_count_is_not_joined(self):
        pages = _pages(
            [_table([["A", "Alpha"]])], [_table([["B", "Beta", "x"]], y0=32)]
        )
        elements_lib.apply_page_break_joins(pages)
        assert len(pages[2]["elements"]) == 1
        assert "pages" not in pages[1]["elements"][0]

    def test_other_edges_are_not_joined(self):
        pages = _pages(
            [_table([["A", "Alpha"]])], [_table([["B", "Beta"]], x0=100, y0=32)]
        )
        elements_lib.apply_page_break_joins(pages)
        assert len(pages[2]["elements"]) == 1

    def test_caption_between_is_not_joined(self):
        pages = _pages(
            [_table([["A", "Alpha"]])],
            [
                {
                    "type": "paragraph",
                    "text": "Table 5 Other limits",
                    "bbox": [64, 32, 300, 42],
                },
                _table([["B", "Beta"]], y0=50),
            ],
        )
        elements_lib.apply_page_break_joins(pages)
        assert len(pages[2]["elements"]) == 2

    def test_an_image_before_the_table_does_not_block_the_join(self):
        pages = _pages(
            [_table([["A", "Alpha"]])],
            [
                {"type": "image", "asset": "a.png", "bbox": [64, 32, 200, 40]},
                _table([["B", "Beta"]], y0=50),
            ],
        )
        elements_lib.apply_page_break_joins(pages)
        assert pages[1]["elements"][0]["rows"] == [["A", "Alpha"], ["B", "Beta"]]


class TestNoEmptyPages:
    def test_page_whose_table_moved_is_not_empty(self):
        pages = _pages([_table([["A", "Alpha"]])], [_table([["B", "Beta"]], y0=32)])
        elements_lib.apply_page_break_joins(pages)
        assert pages[2]["elements"] == []
        result = gates.check_no_empty_pages({"pages": pages})
        assert result["passed"], result

    def test_really_empty_page_still_fails(self):
        pages = _pages(
            [{"type": "paragraph", "text": "Only.", "bbox": [46, 20, 300, 30]}], []
        )
        assert not gates.check_no_empty_pages({"pages": pages})["passed"]
