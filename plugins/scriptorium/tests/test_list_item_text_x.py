"""Fix wave I3: a list item cut by a page break is joined.

extract_text.py writes `text_x` on every `list_item`: the x where the item's
text starts, after the marker. `lib/elements.py`'s page-break join compares
the next page's first paragraph with `text_x` (falling back to `bbox[0]`
when `text_x` is absent), so a continuation printed at the item's text
indent joins the item instead of becoming a separate paragraph.
"""

import json

import elements as elements_lib
import fitz  # PyMuPDF
import paths
from conftest import run_script

MARKER_X = 90.0
FONT_SIZE = 11
ITEM_START = "A list item that is cut by the page"
ITEM_CONTINUATION = "break and continues on the next page."


def _text_x() -> float:
    return MARKER_X + fitz.get_text_length("- ", fontname="helv", fontsize=FONT_SIZE)


def _write_shard(shards_dir, page_number, elements):
    elements_lib.write_shard(
        shards_dir / f"page{page_number}.text.json", page_number, elements
    )


class TestJoinUsesTextX:
    def test_continuation_at_text_x_joins_the_item(self, tmp_path):
        shards = tmp_path / "shards"
        _write_shard(
            shards,
            1,
            [
                {
                    "type": "list_item",
                    "marker": "-",
                    "level": 1,
                    "text": "runs on such as",
                    "bbox": [90.0, 700.0, 400.0, 715.0],
                    "text_x": 100.5,
                },
            ],
        )
        _write_shard(
            shards,
            2,
            [
                {
                    "type": "paragraph",
                    "text": "this continuation.",
                    "bbox": [100.5, 90.0, 300.0, 110.0],
                },
            ],
        )
        pages = elements_lib.merge_shards(shards, page_count=2)
        joined = pages[1]["elements"][0]
        assert joined["text"] == "runs on such as this continuation."
        assert joined["pages"] == [1, 2]
        assert pages[2]["elements"] == []

    def test_paragraph_at_the_marker_x_does_not_join_when_text_x_is_known(
        self, tmp_path
    ):
        """A new paragraph at the marker's x is not the item's continuation."""
        shards = tmp_path / "shards"
        _write_shard(
            shards,
            1,
            [
                {
                    "type": "list_item",
                    "marker": "-",
                    "level": 1,
                    "text": "runs on such as",
                    "bbox": [72.0, 700.0, 400.0, 715.0],
                    "text_x": 84.0,
                },
            ],
        )
        _write_shard(
            shards,
            2,
            [
                {
                    "type": "paragraph",
                    "text": "A new paragraph.",
                    "bbox": [72.0, 90.0, 300.0, 110.0],
                },
            ],
        )
        pages = elements_lib.merge_shards(shards, page_count=2)
        assert "pages" not in pages[1]["elements"][0]
        assert pages[2]["elements"][0]["text"] == "A new paragraph."


class TestListItemCutByAPageBreak:
    def _build(self, path):
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        page.insert_text(
            (72, 100), "Ordinary body text before the list.", fontsize=FONT_SIZE
        )
        page.insert_text((MARKER_X, 640), "- A first list item.", fontsize=FONT_SIZE)
        page.insert_text((MARKER_X, 680), f"- {ITEM_START}", fontsize=FONT_SIZE)
        page = doc.new_page(width=612, height=792)
        page.insert_text((_text_x(), 80), ITEM_CONTINUATION, fontsize=FONT_SIZE)
        page.insert_text(
            (72, 140), "A later paragraph at the left margin.", fontsize=FONT_SIZE
        )
        doc.save(str(path))
        doc.close()

    def _extract(self, tmp_project) -> dict:
        self._build(tmp_project / "input" / "cut_item.pdf")
        for script, extra in (
            ("pdf-triage/scripts/triage.py", []),
            ("extract-text/scripts/extract_text.py", ["--pages", "1,2"]),
        ):
            result = run_script(script, "--doc", "cut_item", *extra, cwd=tmp_project)
            assert result.returncode == 0, result.stderr

    def test_list_items_carry_text_x(self, tmp_project):
        self._extract(tmp_project)
        shard = json.loads(paths.shard_path("cut_item", 1, "text").read_text())
        items = [e for e in shard["elements"] if e["type"] == "list_item"]
        assert len(items) == 2, shard["elements"]
        for item in items:
            assert abs(item["text_x"] - _text_x()) <= 1.0, item
            assert item["bbox"][0] < item["text_x"]

    def test_cut_list_item_is_joined_at_merge(self, tmp_project):
        self._extract(tmp_project)
        result = run_script(
            "assemble-output/scripts/merge.py", "--doc", "cut_item", cwd=tmp_project
        )
        assert result.returncode == 0, result.stderr
        merged = json.loads(paths.elements_json("cut_item").read_text())
        pages = {p["page_number"]: p for p in merged["pages"]}
        joined = [e for e in pages[1]["elements"] if e.get("pages") == [1, 2]]
        assert len(joined) == 1, pages[1]["elements"]
        assert joined[0]["type"] == "list_item"
        assert joined[0]["text"] == f"{ITEM_START} {ITEM_CONTINUATION}"
        assert ITEM_CONTINUATION not in [e.get("text") for e in pages[2]["elements"]]
