"""Task A2 -- furniture removal in extract-text and extract-images.

Exercises the frame-table exclusion, furniture-line-text drop, repeated-image
skip, page_has_table() frame-exclusion, additive bbox schema field, and
merge.py's furniture_text passthrough added in this task, against two
fixtures:

- `furniture_sample.pdf` (Task A0, extended in this task with a second,
  unique, non-repeated bitmap -- see generate_furniture_fixture.py's
  `make_unique_icon_bytes()`/page-4 drawImage call): real line/image
  furniture, but its page frame is a plain, unruled c.rect() border that
  pdfplumber does not detect as a table (confirmed by A0/A1) -- so it never
  exercises the frame_tables removal path.
- `frame_table_sample.pdf` (added in this task, see
  generate_frame_table_fixture.py): a small, purpose-built fixture whose
  page frame has one internal ruling line, which pdfplumber's line-based
  table heuristic *does* pick up as a >60%-page-area table -- used
  instead of modifying furniture_sample.pdf's already-reviewed geometry
  and its byte-exact furniture_golden.json assertions.
"""

import json
import re
import shutil
from pathlib import Path

import pytest

import paths
from conftest import load_script, run_script

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_ROOT = Path(__file__).resolve().parent.parent / "examples"


def _run_ok(relpath: str, *args: str, cwd) -> str:
    result = run_script(relpath, *args, cwd=cwd)
    assert result.returncode == 0, (
        f"{relpath} {' '.join(args)} failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    return result.stdout


def _run_triage(doc: str, cwd) -> dict:
    _run_ok("pdf-triage/scripts/triage.py", "--doc", doc, cwd=cwd)
    return json.loads(paths.triage_json(doc).read_text())


def _golden() -> dict:
    return json.loads((EXAMPLES_ROOT / "furniture_golden.json").read_text())


@pytest.fixture
def furniture_doc(tmp_project):
    dest = tmp_project / "input" / "furniture_sample.pdf"
    shutil.copyfile(EXAMPLES_ROOT / "furniture_sample.pdf", dest)
    return "furniture_sample"


@pytest.fixture
def frame_table_doc(tmp_project):
    dest = tmp_project / "input" / "frame_table_sample.pdf"
    shutil.copyfile(EXAMPLES_ROOT / "frame_table_sample.pdf", dest)
    return "frame_table_sample"


class TestFrameTableFixtureGenerator:
    def test_generator_and_committed_fixture_exist(self):
        assert (REPO_ROOT / "examples" / "generate_frame_table_fixture.py").exists()
        assert (EXAMPLES_ROOT / "frame_table_sample.pdf").exists()

    def test_regenerating_reproduces_the_same_page_count(self, tmp_path):
        import importlib
        import sys

        sys.path.insert(0, str(REPO_ROOT / "examples"))
        import generate_frame_table_fixture as gen  # noqa: E402

        importlib.reload(gen)
        tmp_pdf = tmp_path / "frame_table_sample.pdf"
        gen.generate(output_pdf=tmp_pdf)

        import fitz  # PyMuPDF

        with fitz.open(tmp_pdf) as doc:
            regenerated_pages = doc.page_count
        with fitz.open(EXAMPLES_ROOT / "frame_table_sample.pdf") as doc:
            committed_pages = doc.page_count
        assert regenerated_pages == committed_pages == gen.PAGE_COUNT


class TestExtractTextFurnitureLineDrop:
    def test_no_paragraph_or_heading_matches_a_furniture_line_pattern(self, furniture_doc, tmp_project):
        triage = _run_triage(furniture_doc, tmp_project)
        masked_patterns = {p["masked"] for p in triage["furniture"]["line_patterns"]}
        assert masked_patterns, "sanity: the fixture is expected to have line furniture (see task-A1-report.md)"

        pages = list(range(1, triage["page_count"] + 1))
        _run_ok(
            "extract-text/scripts/extract_text.py", "--doc", furniture_doc,
            "--pages", ",".join(map(str, pages)), "--body-size", str(triage["body_size"]),
            cwd=tmp_project,
        )

        for n in pages:
            shard = json.loads(paths.shard_path(furniture_doc, n, "text").read_text())
            for e in shard["elements"]:
                if e["type"] not in ("paragraph", "heading"):
                    continue
                masked = re.sub(r"\d+", "#", e["text"])
                assert masked not in masked_patterns, f"page {n}: furniture line leaked as {e['type']!r}: {e['text']!r}"

    def test_real_body_table_on_content_page_is_still_extracted(self, furniture_doc, tmp_project):
        golden = _golden()
        content_page = golden["table"]["content_page"]
        triage = _run_triage(furniture_doc, tmp_project)
        _run_ok(
            "extract-text/scripts/extract_text.py", "--doc", furniture_doc,
            "--pages", str(content_page), "--body-size", str(triage["body_size"]),
            cwd=tmp_project,
        )
        shard = json.loads(paths.shard_path(furniture_doc, content_page, "text").read_text())
        tables = [e for e in shard["elements"] if e["type"] == "table"]
        assert tables, f"expected the real ruled table on page {content_page} to survive extraction"


class TestExtractTextFrameTableExclusion:
    def test_frame_table_bbox_never_appears_as_a_table_element(self, frame_table_doc, tmp_project):
        triage = _run_triage(frame_table_doc, tmp_project)
        frame_tables = triage["furniture"]["frame_tables"]
        assert frame_tables, "fixture is designed so pdfplumber detects the ruled frame as a table"

        pages = list(range(1, triage["page_count"] + 1))
        _run_ok(
            "extract-text/scripts/extract_text.py", "--doc", frame_table_doc,
            "--pages", ",".join(map(str, pages)), "--body-size", str(triage["body_size"]),
            cwd=tmp_project,
        )

        for n in pages:
            shard = json.loads(paths.shard_path(frame_table_doc, n, "text").read_text())
            for e in shard["elements"]:
                if e["type"] != "table":
                    continue
                for ft in frame_tables:
                    close = all(abs(a - b) <= 3.0 for a, b in zip(e["bbox"], ft["bbox"]))
                    assert not close, f"page {n}: frame table leaked as a table element: {e['bbox']}"

    def test_real_table_on_the_table_page_still_extracted(self, frame_table_doc, tmp_project):
        triage = _run_triage(frame_table_doc, tmp_project)
        _run_ok(
            "extract-text/scripts/extract_text.py", "--doc", frame_table_doc,
            "--pages", "2", "--body-size", str(triage["body_size"]),
            cwd=tmp_project,
        )
        shard = json.loads(paths.shard_path(frame_table_doc, 2, "text").read_text())
        tables = [e for e in shard["elements"] if e["type"] == "table"]
        assert len(tables) == 1, f"expected exactly the real table on page 2 (frame excluded), got {tables}"


class TestExtractImagesFurnitureSkip:
    def test_repeated_logo_xref_never_emitted_but_unique_bitmap_is(self, furniture_doc, tmp_project):
        triage = _run_triage(furniture_doc, tmp_project)
        furniture_xrefs = set(triage["furniture"]["image_xrefs"])
        assert furniture_xrefs, "sanity: the fixture's logo is expected to be detected as repeated furniture"

        pages = list(range(1, triage["page_count"] + 1))
        _run_ok(
            "extract-images/scripts/extract_images.py", "--doc", furniture_doc,
            "--pages", ",".join(map(str, pages)), cwd=tmp_project,
        )

        all_bitmaps = []
        for n in pages:
            shard = json.loads(paths.shard_path(furniture_doc, n, "image").read_text())
            all_bitmaps += [e for e in shard["elements"] if e["kind"] == "bitmap"]

        # None of the repeated-logo placements (one per page) were emitted -- only the
        # single unique, non-repeated bitmap on page 4 (see
        # generate_furniture_fixture.py) should survive.
        assert len(all_bitmaps) == 1, f"expected exactly the one unique bitmap, got {all_bitmaps}"


class TestPageHasTableExcludesFrame:
    def test_false_on_frame_only_page_true_on_real_table_page(self, frame_table_doc, tmp_project):
        triage = _run_triage(frame_table_doc, tmp_project)
        frame_tables = triage["furniture"]["frame_tables"]
        assert frame_tables

        mod = load_script("extract-images/scripts/extract_images.py", "extract_images_a2_page_has_table")
        pdf_path = paths.input_pdf(frame_table_doc)

        assert mod.page_has_table(pdf_path, 1, frame_tables) is False
        assert mod.page_has_table(pdf_path, 2, frame_tables) is True


class TestBboxOnEveryElement:
    def test_every_element_in_merged_elements_json_has_bbox(self, furniture_doc, tmp_project):
        triage = _run_triage(furniture_doc, tmp_project)
        pages = list(range(1, triage["page_count"] + 1))
        _run_ok(
            "extract-text/scripts/extract_text.py", "--doc", furniture_doc,
            "--pages", ",".join(map(str, pages)), "--body-size", str(triage["body_size"]),
            cwd=tmp_project,
        )
        _run_ok(
            "extract-images/scripts/extract_images.py", "--doc", furniture_doc,
            "--pages", ",".join(map(str, pages)), cwd=tmp_project,
        )
        _run_ok("assemble-output/scripts/merge.py", "--doc", furniture_doc, cwd=tmp_project)

        elements_data = json.loads(paths.elements_json(furniture_doc).read_text())
        checked_any = False
        for page in elements_data["pages"]:
            for e in page["elements"]:
                checked_any = True
                assert "bbox" in e, f"element missing bbox: {e}"
                assert len(e["bbox"]) == 4
        assert checked_any, "expected at least one element across the fixture's pages"


class TestMergeFurnitureText:
    def test_merged_elements_json_has_nonnull_top_level_furniture_text(self, furniture_doc, tmp_project):
        triage = _run_triage(furniture_doc, tmp_project)
        pages = list(range(1, triage["page_count"] + 1))
        _run_ok(
            "extract-text/scripts/extract_text.py", "--doc", furniture_doc,
            "--pages", ",".join(map(str, pages)), "--body-size", str(triage["body_size"]),
            cwd=tmp_project,
        )
        _run_ok(
            "extract-images/scripts/extract_images.py", "--doc", furniture_doc,
            "--pages", ",".join(map(str, pages)), cwd=tmp_project,
        )
        _run_ok("assemble-output/scripts/merge.py", "--doc", furniture_doc, cwd=tmp_project)

        elements_data = json.loads(paths.elements_json(furniture_doc).read_text())
        assert elements_data.get("furniture_text")
        assert elements_data["furniture_text"] == triage["furniture_text"]


class TestMixedFurnitureAndRealLineBlock:
    """Fix round 1 (controller review): a single PyMuPDF text block can mix
    a furniture-matching line with unrelated real content on an adjacent
    line -- plausible whenever PyMuPDF merges a footer note next to a page
    number into one block, the same way it merges furniture_sample.pdf's
    three footer lines into one block. The whole block must NOT be dropped
    in that case -- only the matching line is excluded; the real line's
    text and a bbox recomputed from just the surviving line(s) must
    survive. Exercised directly against `furniture_filtered_lines()`/
    `build_block_element()` (rather than via a generated PDF) because
    getting PyMuPDF to reliably merge two *specific* drawString calls into
    one block is exactly the kind of layout detail this task doesn't
    control -- a hand-built block dict pins down the mixed-line scenario
    precisely and deterministically."""

    def test_real_line_survives_furniture_line_is_dropped(self):
        mod = load_script("extract-text/scripts/extract_text.py", "extract_text_a2_mixed_block")

        page_height = 792.0
        # Bottom 12% band starts at 792 * 0.88 = 697.44pt from the top --
        # both lines sit well inside it, as a real merged footer block would.
        block = {
            "bbox": [40.0, 760.0, 300.0, 784.0],
            "lines": [
                {
                    "text": "Doc No. SYN-FUR-0001",
                    "masked": "Doc No. SYN-FUR-#",
                    "bbox": [40.0, 760.0, 160.0, 772.0],
                    "max_size": 8.0,
                    "bold": False,
                },
                {
                    "text": "Reviewed by Jane Doe",
                    "masked": "Reviewed by Jane Doe",
                    "bbox": [40.0, 772.0, 300.0, 784.0],
                    "max_size": 8.0,
                    "bold": False,
                },
            ],
        }
        furniture_masked = {"Doc No. SYN-FUR-#"}

        kept_lines = mod.furniture_filtered_lines(block, furniture_masked, page_height)
        assert [line["text"] for line in kept_lines] == ["Reviewed by Jane Doe"]

        element = mod.build_block_element(block, kept_lines, body_size=8.0, toc_lookup={}, heading_size_ranks={})
        assert element is not None
        assert element["type"] == "paragraph"
        assert element["text"] == "Reviewed by Jane Doe"
        assert "Doc No." not in element["text"]
        # bbox recomputed from the surviving line only, not the original
        # (furniture-including) block bbox.
        assert element["bbox"] == [40.0, 772.0, 300.0, 784.0]

    def test_all_lines_matching_drops_the_whole_block(self):
        mod = load_script("extract-text/scripts/extract_text.py", "extract_text_a2_all_furniture_block")

        page_height = 792.0
        block = {
            "bbox": [40.0, 760.0, 160.0, 772.0],
            "lines": [
                {
                    "text": "Doc No. SYN-FUR-0001",
                    "masked": "Doc No. SYN-FUR-#",
                    "bbox": [40.0, 760.0, 160.0, 772.0],
                    "max_size": 8.0,
                },
            ],
        }
        furniture_masked = {"Doc No. SYN-FUR-#"}

        kept_lines = mod.furniture_filtered_lines(block, furniture_masked, page_height)
        assert kept_lines == []
        assert mod.build_block_element(block, kept_lines, body_size=8.0, toc_lookup={}, heading_size_ranks={}) is None

    def test_block_outside_the_edge_band_is_never_filtered(self):
        """Sanity check on the gate itself: a block with the same
        furniture-matching text but positioned mid-page (not in the top/
        bottom 12% band) is left untouched -- matching text alone is never
        sufficient."""
        mod = load_script("extract-text/scripts/extract_text.py", "extract_text_a2_mid_page_block")

        page_height = 792.0
        block = {
            "bbox": [40.0, 380.0, 300.0, 404.0],
            "lines": [
                {
                    "text": "Doc No. SYN-FUR-0001",
                    "masked": "Doc No. SYN-FUR-#",
                    "bbox": [40.0, 380.0, 160.0, 392.0],
                    "max_size": 8.0,
                },
            ],
        }
        furniture_masked = {"Doc No. SYN-FUR-#"}

        kept_lines = mod.furniture_filtered_lines(block, furniture_masked, page_height)
        assert kept_lines == block["lines"]
