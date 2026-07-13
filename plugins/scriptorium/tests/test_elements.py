"""Unit tests for lib/elements.py -- shard read/write and merge."""

import json

import elements as elements_lib


def test_write_read_shard_roundtrip(tmp_path):
    shard_path = tmp_path / "page1.text.json"
    elements_lib.write_shard(shard_path, 1, [{"type": "paragraph", "text": "hi"}])

    shard = elements_lib.read_shard(shard_path)
    assert shard == {"page_number": 1, "elements": [{"type": "paragraph", "text": "hi"}]}


def test_write_shard_keeps_extra_fields(tmp_path):
    shard_path = tmp_path / "page1.ocr.json"
    elements_lib.write_shard(shard_path, 1, [], ocr_confidence=0.9)
    assert json.loads(shard_path.read_text())["ocr_confidence"] == 0.9


def test_read_shard_missing_file_returns_none(tmp_path):
    assert elements_lib.read_shard(tmp_path / "nope.json") is None


class TestMergeShards:
    def test_body_tier_priority_vision_beats_ocr_beats_text(self, tmp_path):
        shards_dir = tmp_path / "shards"
        elements_lib.write_shard(shards_dir / "page1.text.json", 1, [{"type": "paragraph", "text": "text-tier"}])
        elements_lib.write_shard(shards_dir / "page1.ocr.json", 1, [{"type": "paragraph", "text": "ocr-tier"}])
        elements_lib.write_shard(shards_dir / "page1.vision.json", 1, [{"type": "paragraph", "text": "vision-tier"}])

        pages = elements_lib.merge_shards(shards_dir, page_count=1)
        assert pages[1]["tier"] == "vision"
        assert pages[1]["elements"] == [{"type": "paragraph", "text": "vision-tier"}]

    def test_missing_body_shard_yields_empty_text_page(self, tmp_path):
        shards_dir = tmp_path / "shards"
        shards_dir.mkdir()
        pages = elements_lib.merge_shards(shards_dir, page_count=1)
        assert pages[1] == {"page_number": 1, "tier": "text", "elements": []}

    def test_image_shard_appended_independent_of_body_tier(self, tmp_path):
        shards_dir = tmp_path / "shards"
        elements_lib.write_shard(shards_dir / "page1.text.json", 1, [{"type": "paragraph", "text": "body"}])
        elements_lib.write_shard(shards_dir / "page1.image.json", 1, [{"type": "image", "asset": "assets/a.png"}])

        pages = elements_lib.merge_shards(shards_dir, page_count=1)
        assert pages[1]["elements"] == [
            {"type": "paragraph", "text": "body"},
            {"type": "image", "asset": "assets/a.png"},
        ]

    def test_body_shard_extra_fields_carried_through(self, tmp_path):
        shards_dir = tmp_path / "shards"
        elements_lib.write_shard(shards_dir / "page1.ocr.json", 1, [], ocr_confidence=0.42)
        pages = elements_lib.merge_shards(shards_dir, page_count=1)
        assert pages[1]["ocr_confidence"] == 0.42

    def test_covers_every_page_in_range(self, tmp_path):
        shards_dir = tmp_path / "shards"
        elements_lib.write_shard(shards_dir / "page2.text.json", 2, [{"type": "paragraph", "text": "p2"}])
        pages = elements_lib.merge_shards(shards_dir, page_count=3)
        assert set(pages) == {1, 2, 3}
        assert pages[1]["elements"] == []
        assert pages[3]["elements"] == []


class TestLoadSaveDoc:
    def test_save_then_load_roundtrip(self, tmp_path):
        elements_path = tmp_path / "elements.json"
        doc = {
            "doc": "sample",
            "source_file": "input/sample.pdf",
            "page_count": 2,
            "pages": {
                2: {"page_number": 2, "tier": "text", "elements": []},
                1: {"page_number": 1, "tier": "text", "elements": []},
            },
        }
        elements_lib.save_doc(elements_path, doc)

        # On disk, pages is a page_number-sorted list, not a dict.
        on_disk = json.loads(elements_path.read_text())
        assert [p["page_number"] for p in on_disk["pages"]] == [1, 2]

        loaded = elements_lib.load_doc(elements_path)
        assert loaded["pages"].keys() == {1, 2}
        assert loaded["doc"] == "sample"

    def test_load_missing_file_returns_empty_doc(self, tmp_path):
        loaded = elements_lib.load_doc(tmp_path / "missing.json")
        assert loaded == {"doc": None, "source_file": None, "page_count": 0, "pages": {}}
