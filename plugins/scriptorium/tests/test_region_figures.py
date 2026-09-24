"""Task A5 -- region-level figure detection and cropping.

`lib/figures.py`'s `detect_figure_regions()` replaces extract_images.py's
old whole-page vector-detection rule (>=8 drawings AND <=200 page chars,
gone entirely) with per-cluster region detection, shared with
extract_text.py so both scripts agree on where a page's figure regions are
without either waiting on the other's shard (they can run as parallel
subagent batches -- see commands/extract.md).

Fixtures used:
- `furniture_sample.pdf` (Task A0): page 7's vector flow diagram and page
  8's vector bar chart are both on otherwise text-heavy pages -- exactly
  the case the old whole-page rule missed. Page 8 also has a real ruled
  table, and every page has a page-frame border -- both must be excluded
  from figure-region detection, not just from `extract_text.py`'s own
  table/furniture handling.
- `sample.pdf` (pre-existing): page 4's vector flow diagram is the
  regression check for the old whole-page rule's one working case.
- Small hand-built single-page PDFs (via `fitz`'s own Shape/`draw_*` API,
  not reportlab -- no headings/paragraphs/TOC needed, only vector drawings
  at controlled coordinates) for the exclusion-rule unit tests, so each
  case is deterministic and isolated rather than depending on
  `furniture_sample.pdf`'s specific geometry.
"""

import json
import shutil
from pathlib import Path

import fitz  # PyMuPDF
import pytest
from PIL import Image

import figures as figures_lib
import paths
from conftest import run_script

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


def _figure_page(kind: str) -> int:
    return next(f["page"] for f in _golden()["figures"] if f["kind"] == kind)


@pytest.fixture
def furniture_doc(tmp_project):
    dest = tmp_project / "input" / "furniture_sample.pdf"
    shutil.copyfile(EXAMPLES_ROOT / "furniture_sample.pdf", dest)
    return "furniture_sample"


def _make_region_pdf(path: Path, draw_fn):
    """A small single-page (letter-size) PDF built directly with fitz's
    draw_rect/draw_line, saved then reopened so pdfplumber (used by
    lib/figures.py's real_table_bboxes) reads the same bytes the returned
    `page` object sees. Returns (doc, page) -- caller closes `doc`."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    draw_fn(page)
    doc.save(str(path))
    doc.close()
    reopened = fitz.open(str(path))
    return reopened, reopened[0]


class TestFurnitureSampleFigureRegions:
    """Region crops for the diagram (page 7) and chart (page 8), both on
    otherwise text-heavy pages -- the case the old whole-page rule missed
    entirely (it required <=200 total page characters)."""

    def test_diagram_region_is_a_small_crop_not_a_whole_page_render(self):
        diagram_page = _figure_page("diagram")
        pdf_path = EXAMPLES_ROOT / "furniture_sample.pdf"
        doc = fitz.open(pdf_path)
        page = doc[diagram_page - 1]
        page_area = page.rect.width * page.rect.height

        # Task A5b: the page-frame border is now identified by repetition
        # (frame_drawings), not by size alone -- pass the golden fixture's
        # known frame bbox so this direct (no-triage) call still excludes it
        # the same way the production pipeline (which reads it from
        # triage.json) does.
        frame_drawings = [{"bbox": _golden()["furniture"]["frame_bbox"]}]
        regions = figures_lib.detect_figure_regions(page, diagram_page, pdf_path, frame_tables=[], frame_drawings=frame_drawings)
        assert len(regions) == 1
        bbox = regions[0]["bbox"]
        area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
        assert area / page_area < 0.5, f"region should be a small fraction of the page, got {area / page_area:.3f}"
        doc.close()

    def test_chart_region_is_a_small_crop_and_excludes_the_real_table(self):
        """Page 8 has both the bar chart and a real ruled table -- exactly
        one region should survive (the chart); the table's own cluster must
        be dropped by the real-table exclusion rule."""
        chart_page = _figure_page("chart")
        pdf_path = EXAMPLES_ROOT / "furniture_sample.pdf"
        doc = fitz.open(pdf_path)
        page = doc[chart_page - 1]
        page_area = page.rect.width * page.rect.height

        frame_drawings = [{"bbox": _golden()["furniture"]["frame_bbox"]}]
        regions = figures_lib.detect_figure_regions(page, chart_page, pdf_path, frame_tables=[], frame_drawings=frame_drawings)
        assert len(regions) == 1
        bbox = regions[0]["bbox"]
        area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
        assert area / page_area < 0.5
        doc.close()

    def test_page_frame_border_never_becomes_a_region_on_any_page(self):
        """Every page of furniture_sample.pdf carries the same near-full-
        page frame border -- it must never itself surface as a figure
        region, on figure pages or otherwise-plain body pages alike."""
        pdf_path = EXAMPLES_ROOT / "furniture_sample.pdf"
        frame_drawings = [{"bbox": _golden()["furniture"]["frame_bbox"]}]
        doc = fitz.open(pdf_path)
        page_area = doc[0].rect.width * doc[0].rect.height
        for page_number in range(1, doc.page_count + 1):
            page = doc[page_number - 1]
            for region in figures_lib.detect_figure_regions(page, page_number, pdf_path, frame_tables=[], frame_drawings=frame_drawings):
                bbox = region["bbox"]
                area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
                assert area / page_area < 0.5, f"page {page_number}: a near-full-page region leaked through ({bbox})"
        doc.close()

    def test_extract_images_writes_a_crop_render_not_a_whole_page_png(self, furniture_doc, tmp_project):
        diagram_page = _figure_page("diagram")
        _run_triage(furniture_doc, tmp_project)
        _run_ok(
            "extract-images/scripts/extract_images.py", "--doc", furniture_doc,
            "--pages", str(diagram_page), cwd=tmp_project,
        )
        shard = json.loads(paths.shard_path(furniture_doc, diagram_page, "image").read_text())
        vectors = [e for e in shard["elements"] if e["kind"] == "vector"]
        assert len(vectors) == 1
        assert vectors[0]["asset"] == f"assets/page{diagram_page}_vector1.png"

        asset_path = tmp_project / "output" / furniture_doc / vectors[0]["asset"]
        assert asset_path.exists()
        full_page_width_at_200dpi = 612 / 72 * 200
        with Image.open(asset_path) as img:
            assert img.width < full_page_width_at_200dpi * 0.9, "crop should be narrower than a full-page render"


class TestSurroundingBodyTextStillExtracted:
    """The figure-region exclusion only applies to text actually inside the
    region's own bbox -- surrounding paragraphs/headings on the same page
    must still come out as normal elements."""

    def test_paragraph_and_heading_and_caption_around_the_diagram_survive(self, furniture_doc, tmp_project):
        diagram_page = _figure_page("diagram")
        triage = _run_triage(furniture_doc, tmp_project)
        _run_ok(
            "extract-text/scripts/extract_text.py", "--doc", furniture_doc,
            "--pages", str(diagram_page), "--body-size", str(triage["body_size"]),
            cwd=tmp_project,
        )
        shard = json.loads(paths.shard_path(furniture_doc, diagram_page, "text").read_text())
        para_and_heading_text = " ".join(
            e["text"] for e in shard["elements"] if e["type"] in ("paragraph", "heading")
        )
        assert "2.1.2 Edge Case Handling" in para_and_heading_text
        assert "vector-drawn flow diagram" in para_and_heading_text
        # Task A6: the caption line is now excluded from paragraph
        # extraction -- it's script-authoritative on the image element's
        # own `caption` field instead (see test_figure_captions.py).
        assert "Figure 1: Process Diagram" not in para_and_heading_text

    def test_paragraph_and_table_around_the_chart_survive(self, furniture_doc, tmp_project):
        chart_page = _figure_page("chart")
        golden = _golden()
        triage = _run_triage(furniture_doc, tmp_project)
        _run_ok(
            "extract-text/scripts/extract_text.py", "--doc", furniture_doc,
            "--pages", str(chart_page), "--body-size", str(triage["body_size"]),
            cwd=tmp_project,
        )
        shard = json.loads(paths.shard_path(furniture_doc, chart_page, "text").read_text())
        para_and_heading_text = " ".join(
            e["text"] for e in shard["elements"] if e["type"] in ("paragraph", "heading")
        )
        assert "vector-drawn bar chart" in para_and_heading_text
        # Task A6: excluded from paragraph extraction -- script-authoritative
        # on the image element's own `caption` field instead.
        assert "Figure 2: Revenue by Quarter" not in para_and_heading_text

        tables = [e for e in shard["elements"] if e["type"] == "table"]
        assert len(tables) == 1
        assert list(tables[0]["bbox"]) == golden["table"]["content_bbox"]


class TestFigureText:
    """Text-layer lines inside a figure region become figure_text on the
    image element, not separate paragraph elements."""

    def test_diagram_box_labels_become_figure_text_not_paragraphs(self, furniture_doc, tmp_project):
        diagram_page = _figure_page("diagram")
        triage = _run_triage(furniture_doc, tmp_project)
        _run_ok(
            "extract-text/scripts/extract_text.py", "--doc", furniture_doc,
            "--pages", str(diagram_page), "--body-size", str(triage["body_size"]),
            cwd=tmp_project,
        )
        _run_ok(
            "extract-images/scripts/extract_images.py", "--doc", furniture_doc,
            "--pages", str(diagram_page), cwd=tmp_project,
        )
        text_shard = json.loads(paths.shard_path(furniture_doc, diagram_page, "text").read_text())
        image_shard = json.loads(paths.shard_path(furniture_doc, diagram_page, "image").read_text())

        for label in ("Start", "Process", "Decision", "End"):
            leaked = [e for e in text_shard["elements"] if e.get("text") == label]
            assert not leaked, f"{label!r} leaked as its own text element: {leaked}"
        # Task A6: the caption ("Figure 1: Process Diagram") is outside the
        # region's bbox but is now excluded from paragraph extraction too --
        # it's script-authoritative on the image element's `caption` field
        # (see test_figure_captions.py), not a normal paragraph.
        assert not any(e.get("text") == "Figure 1: Process Diagram" for e in text_shard["elements"])

        vectors = [e for e in image_shard["elements"] if e["kind"] == "vector"]
        assert len(vectors) == 1
        assert vectors[0]["caption"] == "Figure 1: Process Diagram"
        figure_text = vectors[0].get("figure_text")
        assert figure_text is not None
        for label in ("Start", "Process", "Decision", "End"):
            assert label in figure_text

    def test_chart_axis_labels_become_figure_text_not_paragraphs(self, furniture_doc, tmp_project):
        chart_page = _figure_page("chart")
        triage = _run_triage(furniture_doc, tmp_project)
        _run_ok(
            "extract-text/scripts/extract_text.py", "--doc", furniture_doc,
            "--pages", str(chart_page), "--body-size", str(triage["body_size"]),
            cwd=tmp_project,
        )
        _run_ok(
            "extract-images/scripts/extract_images.py", "--doc", furniture_doc,
            "--pages", str(chart_page), cwd=tmp_project,
        )
        text_shard = json.loads(paths.shard_path(furniture_doc, chart_page, "text").read_text())
        image_shard = json.loads(paths.shard_path(furniture_doc, chart_page, "image").read_text())

        for label in ("Q1", "Q2", "Q3", "Q4"):
            leaked = [e for e in text_shard["elements"] if e.get("text") == label]
            assert not leaked, f"{label!r} leaked as its own text element: {leaked}"

        vectors = [e for e in image_shard["elements"] if e["kind"] == "vector"]
        assert len(vectors) == 1
        figure_text = vectors[0].get("figure_text")
        assert figure_text is not None
        for label in ("Q1", "Q2", "Q3", "Q4"):
            assert label in figure_text


class TestRegionExclusionRules:
    """Direct unit tests against detect_figure_regions() with small,
    purpose-built single-page PDFs -- one exclusion rule isolated per case,
    plus a legitimate mid-page region in each to prove the rule excludes
    only what it should."""

    def test_cluster_in_furniture_edge_band_is_excluded(self, tmp_path):
        path = tmp_path / "band.pdf"

        def draw(page):
            page.draw_rect(fitz.Rect(150, 15, 450, 70), width=1)  # fully in the top 12% edge band
            page.draw_rect(fitz.Rect(150, 300, 450, 450), width=1)  # legitimate mid-page figure

        doc, page = _make_region_pdf(path, draw)
        try:
            regions = figures_lib.detect_figure_regions(page, 1, path, frame_tables=[])
            assert len(regions) == 1
            assert regions[0]["bbox"][1] > 200
        finally:
            doc.close()

    def test_cluster_overlapping_a_real_table_bbox_is_excluded(self, tmp_path):
        path = tmp_path / "table.pdf"

        def draw(page):
            x0, y0, x1, y1 = 150, 300, 450, 380
            for yy in (y0, (y0 + y1) / 2, y1):
                page.draw_line((x0, yy), (x1, yy), width=1)
            for xx in (x0, (x0 + x1) / 2, x1):
                page.draw_line((xx, y0), (xx, y1), width=1)
            page.draw_rect(fitz.Rect(150, 450, 450, 600), width=1)  # legitimate figure, well clear of the table

        doc, page = _make_region_pdf(path, draw)
        try:
            regions = figures_lib.detect_figure_regions(page, 1, path, frame_tables=[])
            assert len(regions) == 1
            assert regions[0]["bbox"][1] > 400
        finally:
            doc.close()

    def test_tiny_stray_line_produces_no_region(self, tmp_path):
        path = tmp_path / "tiny.pdf"

        def draw(page):
            page.draw_rect(fitz.Rect(100, 398, 160, 402), width=1)  # a short rule, not a figure

        doc, page = _make_region_pdf(path, draw)
        try:
            regions = figures_lib.detect_figure_regions(page, 1, path, frame_tables=[])
            assert regions == []
        finally:
            doc.close()

    def test_page_frame_border_alone_produces_no_region(self, tmp_path):
        """The furniture_sample.pdf case in isolation: a single near-full-
        page rectangle border and nothing else must never itself become a
        figure region.

        Task A5b: the frame is now identified by repetition
        (frame_drawings), not size alone -- this single-page fixture can't
        demonstrate repetition itself, so frame_drawings is passed in
        directly, simulating what triage.py's document-wide
        _find_frame_drawings would have found for a border repeated at this
        exact bbox across the document."""
        path = tmp_path / "frame_only.pdf"
        frame_bbox = [24.0, 24.0, 588.0, 768.0]

        def draw(page):
            page.draw_rect(fitz.Rect(*frame_bbox), width=1)

        doc, page = _make_region_pdf(path, draw)
        try:
            regions = figures_lib.detect_figure_regions(
                page, 1, path, frame_tables=[], frame_drawings=[{"bbox": frame_bbox, "page_count": 2}],
            )
            assert regions == []
        finally:
            doc.close()


class TestReadingOrderMerge:
    """merge_shards() interleaves an image element with surrounding text by
    bbox y-position, rather than always appending images after every text
    element -- a direct test against the merge function itself."""

    def test_image_between_two_paragraphs_comes_out_interleaved(self, tmp_path):
        import elements as elements_lib

        shards_dir = tmp_path / "shards"
        elements_lib.write_shard(shards_dir / "page1.text.json", 1, [
            {"type": "paragraph", "text": "before", "bbox": [0, 10, 100, 30]},
            {"type": "paragraph", "text": "after", "bbox": [0, 200, 100, 220]},
        ])
        elements_lib.write_shard(shards_dir / "page1.image.json", 1, [
            {"type": "image", "kind": "vector", "asset": "assets/a.png", "bbox": [0, 100, 100, 180]},
        ])

        pages = elements_lib.merge_shards(shards_dir, page_count=1)
        ordering = [e.get("text") or e.get("asset") for e in pages[1]["elements"]]
        assert ordering == ["before", "assets/a.png", "after"]


class TestSamplePdfRegression:
    """sample.pdf's existing page-4 vector diagram, previously handled by
    the OLD whole-page rule -- still produces a reasonable figure element
    under the NEW region-based rule."""

    def test_page4_vector_diagram_still_produces_one_small_region(self, pdf_doc, tmp_project):
        _run_ok("pdf-triage/scripts/triage.py", "--doc", pdf_doc, cwd=tmp_project)
        _run_ok("extract-images/scripts/extract_images.py", "--doc", pdf_doc, "--pages", "4", cwd=tmp_project)

        shard = json.loads(paths.shard_path(pdf_doc, 4, "image").read_text())
        vectors = [e for e in shard["elements"] if e["kind"] == "vector"]
        assert len(vectors) == 1

        bbox = vectors[0]["bbox"]
        page_area = 612 * 792
        area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
        assert area / page_area < 0.5, "region-based crop should not be a whole-page render"

        asset_path = tmp_project / "output" / pdf_doc / vectors[0]["asset"]
        assert asset_path.exists()

    def test_page4_diagram_box_labels_become_figure_text(self, pdf_doc, tmp_project):
        _run_ok("pdf-triage/scripts/triage.py", "--doc", pdf_doc, cwd=tmp_project)
        _run_ok("extract-images/scripts/extract_images.py", "--doc", pdf_doc, "--pages", "4", cwd=tmp_project)

        shard = json.loads(paths.shard_path(pdf_doc, 4, "image").read_text())
        vectors = [e for e in shard["elements"] if e["kind"] == "vector"]
        figure_text = vectors[0].get("figure_text")
        assert figure_text is not None
        for label in ("Start", "Process", "Decision", "End"):
            assert label in figure_text
