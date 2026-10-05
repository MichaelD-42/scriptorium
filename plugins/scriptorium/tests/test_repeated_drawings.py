"""Fix wave B1: page-frame parts found by repetition.

`examples/line_frame_sample.pdf` (see `examples/generate_line_frame_fixture.py`)
draws its page frame from many separate parts on every page: a filled inner
rect, 4 border lines and a 31-line title block. Only the filled rect covers
more than 60% of the page, so `frame_drawings` alone cannot remove the
frame. Left in, the parts join every other drawing into one page-sized
cluster. `triage.json["furniture"]["repeated_drawings"]` lists every drawing
whose rect repeats on at least half the body pages (and on at least
FRAME_MIN_PAGE_COUNT pages), and `lib/figures.py` removes those drawings
before clustering.
"""

import json
import shutil
from pathlib import Path

import figures as figures_lib
import fitz  # PyMuPDF
import paths
from conftest import run_script

EXAMPLES_ROOT = Path(__file__).resolve().parent.parent / "examples"
DOC = "line_frame_sample"
PAGE_COUNT = 4
DIAGRAM_PAGE = 2
TABLE_PAGE = 3
TABLE_ROWS = [["Item", "Value"], ["Mode", "Normal"], ["Limit", "Ten"]]
PAGE_AREA = 612.0 * 792.0


def _run_ok(relpath: str, *args: str, cwd) -> str:
    result = run_script(relpath, *args, cwd=cwd)
    assert result.returncode == 0, (
        f"{relpath} {' '.join(args)} failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    return result.stdout


def _setup(tmp_project) -> dict:
    shutil.copyfile(EXAMPLES_ROOT / f"{DOC}.pdf", tmp_project / "input" / f"{DOC}.pdf")
    _run_ok("pdf-triage/scripts/triage.py", "--doc", DOC, cwd=tmp_project)
    return json.loads(paths.triage_json(DOC).read_text())


def _area(bbox) -> float:
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])


def _all_pages() -> str:
    return ",".join(str(p) for p in range(1, PAGE_COUNT + 1))


def _image_shards(tmp_project) -> dict[int, dict]:
    _run_ok(
        "extract-images/scripts/extract_images.py",
        "--doc",
        DOC,
        "--pages",
        _all_pages(),
        cwd=tmp_project,
    )
    return {
        p: json.loads(paths.shard_path(DOC, p, "image").read_text())
        for p in range(1, PAGE_COUNT + 1)
    }


def _text_shards(tmp_project, triage) -> dict[int, dict]:
    _run_ok(
        "extract-text/scripts/extract_text.py",
        "--doc",
        DOC,
        "--pages",
        _all_pages(),
        "--body-size",
        str(triage["body_size"]),
        cwd=tmp_project,
    )
    return {
        p: json.loads(paths.shard_path(DOC, p, "text").read_text())
        for p in range(1, PAGE_COUNT + 1)
    }


class TestTriageRepeatedDrawings:
    def test_every_frame_part_is_listed(self, tmp_project):
        triage = _setup(tmp_project)
        repeated = triage["furniture"]["repeated_drawings"]
        # 1 filled inner rect + 4 border lines + 31 title-block lines.
        assert len(repeated) == 36, repeated
        assert all(r["page_count"] == PAGE_COUNT for r in repeated)
        assert {r["type"] for r in repeated} == {"f", "s"}
        assert all(set(r) == {"bbox", "type", "page_count"} for r in repeated)

    def test_list_stays_short(self, tmp_project):
        """One entry per distinct repeated rect, not one per occurrence."""
        triage = _setup(tmp_project)
        doc = fitz.open(EXAMPLES_ROOT / f"{DOC}.pdf")
        try:
            first_page_drawings = len(doc[0].get_drawings())
        finally:
            doc.close()
        assert len(triage["furniture"]["repeated_drawings"]) <= first_page_drawings

    def test_diagram_and_table_parts_are_not_listed(self, tmp_project):
        """The diagram and the table appear on one page each: not repeated."""
        triage = _setup(tmp_project)
        for entry in triage["furniture"]["repeated_drawings"]:
            x0, y0, x1, y1 = entry["bbox"]
            inside_body = 60 < y0 and y1 < 640 and 60 < x0 and x1 < 560
            assert not inside_body, f"a body drawing was listed as repeated: {entry}"


class TestFiguresWithLineFrame:
    def test_no_page_sized_region_on_any_page(self, tmp_project):
        _setup(tmp_project)
        shards = _image_shards(tmp_project)
        for page_number, shard in shards.items():
            for el in shard["elements"]:
                if el["kind"] == "vector":
                    assert _area(el["bbox"]) / PAGE_AREA < 0.2, (
                        f"page {page_number}: page-sized region {el['bbox']}"
                    )

    def test_text_pages_have_no_vector_region(self, tmp_project):
        _setup(tmp_project)
        shards = _image_shards(tmp_project)
        for page_number in (1, 4):
            vectors = [
                e for e in shards[page_number]["elements"] if e["kind"] == "vector"
            ]
            assert vectors == [], f"page {page_number}: {vectors}"

    def test_diagram_is_one_region_of_about_its_own_size(self, tmp_project):
        _setup(tmp_project)
        shards = _image_shards(tmp_project)
        vectors = [e for e in shards[DIAGRAM_PAGE]["elements"] if e["kind"] == "vector"]
        assert len(vectors) == 1, vectors
        x0, y0, x1, y1 = vectors[0]["bbox"]
        # The diagram's boxes span x 100..510 and y (from the top) 290..412,
        # plus REGION_PADDING (10pt) on each side.
        assert 80 <= x0 <= 100 and 500 <= x1 <= 530, vectors[0]["bbox"]
        assert 260 <= y0 <= 300 and 405 <= y1 <= 440, vectors[0]["bbox"]
        assert vectors[0].get("caption") == "Figure 1: Line Frame Diagram"

    def test_one_repeated_drawing_summary_per_page(self, tmp_project):
        _setup(tmp_project)
        shards = _image_shards(tmp_project)
        for page_number, shard in shards.items():
            summaries = [
                r
                for r in shard["excluded_regions"]
                if r["reason"] == "repeated_drawing"
            ]
            assert len(summaries) == 1, (
                f"page {page_number}: {shard['excluded_regions']}"
            )
            assert summaries[0]["count"] >= 35, summaries[0]

    def test_table_overlap_only_for_the_real_table(self, tmp_project):
        _setup(tmp_project)
        shards = _image_shards(tmp_project)
        for page_number, shard in shards.items():
            overlaps = [
                r for r in shard["excluded_regions"] if r["reason"] == "table_overlap"
            ]
            if page_number != TABLE_PAGE:
                assert overlaps == [], f"page {page_number}: {overlaps}"
                continue
            assert len(overlaps) == 1, overlaps
            # The real table: x 150..370, y (from the top) 300..366, padded.
            x0, y0, x1, y1 = overlaps[0]["bbox"]
            assert 130 <= x0 <= 150 and 370 <= x1 <= 390, overlaps[0]
            assert 280 <= y0 <= 300 and 366 <= y1 <= 386, overlaps[0]


class TestTextWithLineFrame:
    def test_body_text_stays_body_text(self, tmp_project):
        triage = _setup(tmp_project)
        shards = _text_shards(tmp_project, triage)
        for page_number, shard in shards.items():
            texts = " ".join(e.get("text", "") for e in shard["elements"])
            assert "A second paragraph of ordinary body text" in texts, (
                f"page {page_number}: {shard}"
            )

    def test_real_table_inside_the_frame_still_extracts(self, tmp_project):
        triage = _setup(tmp_project)
        shards = _text_shards(tmp_project, triage)
        tables = [e for e in shards[TABLE_PAGE]["elements"] if e["type"] == "table"]
        assert len(tables) == 1, shards[TABLE_PAGE]["elements"]
        assert tables[0]["rows"] == TABLE_ROWS
        for page_number in (1, 2, 4):
            assert not [
                e for e in shards[page_number]["elements"] if e["type"] == "table"
            ]


class TestDetectWithRepeatedDrawings:
    """Direct unit test: a drawing that matches a repeated_drawings entry
    never reaches clustering, and the page gets one summary entry."""

    def test_repeated_parts_removed_and_summarised(self, tmp_path):
        path = tmp_path / "unit.pdf"
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        frame_lines = [
            ((28, 16), (584, 16)),
            ((28, 776), (584, 776)),
            ((28, 16), (28, 776)),
            ((584, 16), (584, 776)),
        ]
        for p1, p2 in frame_lines:
            page.draw_line(p1, p2, width=0.8)
        page.draw_rect(fitz.Rect(200, 300, 300, 350), width=1.5)
        page.draw_rect(fitz.Rect(330, 300, 430, 350), width=1.5)
        page.draw_line((300, 325), (330, 325), width=1.5)
        doc.save(str(path))
        doc.close()
        doc = fitz.open(str(path))
        try:
            page = doc[0]
            repeated = [
                {"bbox": list(d["rect"]), "type": d["type"], "page_count": 5}
                for d in page.get_drawings()
                if d["rect"].width > 500 or d["rect"].height > 500
            ]
            assert len(repeated) == 4
            regions, excluded = figures_lib.detect_figure_regions_with_exclusions(
                page,
                1,
                path,
                frame_tables=[],
                frame_drawings=[],
                repeated_drawings=repeated,
            )
            assert len(regions) == 1
            assert _area(regions[0]["bbox"]) < 0.1 * PAGE_AREA
            summaries = [r for r in excluded if r["reason"] == "repeated_drawing"]
            assert len(summaries) == 1 and summaries[0]["count"] == 4
        finally:
            doc.close()
