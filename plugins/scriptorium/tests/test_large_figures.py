"""Task A5b -- no silent loss of large figures.

A5's review found two exclusion rules in `lib/figures.py` that could drop a
real figure region with no trace at all:

1. A size pre-filter removed any single drawing whose bbox covered more
   than 60% of the page, BEFORE clustering, regardless of whether it
   repeated across the document (i.e. was actually furniture) or was a
   genuine one-off large figure.
2. The furniture-band exclusion dropped a cluster for merely *overlapping*
   the top/bottom edge band at all, even if only a sliver of a tall real
   figure reached into it.

This task replaces (1) with repetition-based frame identification
(`triage.py`'s `_find_frame_drawings`, `triage.json["furniture"]
["frame_drawings"]`) and tightens (2) to a majority-area test, and records
every region a filter still excludes in the page's image shard as
`excluded_regions`, so nothing a filter drops vanishes without a trace.

`test_large_unique_figure_is_detected_not_silently_dropped` below is the
core regression test for the bug this task fixes: it was CONFIRMED FAILING
against the pre-A5b code (`git stash` back to before this task's changes,
same assertion, same fixture) before any implementation code was touched --
see task-A5b-report.md for the confirmation transcript.
"""

import json
import shutil
from pathlib import Path

import fitz  # PyMuPDF
import pytest

import figures as figures_lib
import paths
from conftest import load_script, run_script

gates = load_script("grade-output/scripts/gates.py", "gates_module_a5b")

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


def _make_region_pdf(path: Path, draw_fn):
    """Same small single-page (letter-size) PDF helper test_region_figures.py
    uses -- built directly with fitz's draw_rect/draw_line, saved then
    reopened so pdfplumber (used by lib/figures.py's real_table_bboxes)
    reads the same bytes the returned `page` object sees. Returns
    `(doc, page)` -- caller closes `doc`."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    draw_fn(page)
    doc.save(str(path))
    doc.close()
    reopened = fitz.open(str(path))
    return reopened, reopened[0]


PAGE_WIDTH, PAGE_HEIGHT = 612.0, 792.0
PAGE_AREA = PAGE_WIDTH * PAGE_HEIGHT


class TestLargeUniqueFigureNotDropped:
    """A large (~70% of the page), one-page-only figure, positioned so it
    does not touch either edge band -- must be detected as a figure region,
    not removed by the old unconditional size pre-filter."""

    def test_large_unique_figure_is_detected_not_silently_dropped(self, tmp_path):
        path = tmp_path / "large_figure.pdf"

        # width=606, height=560 -> area fraction ~0.700 of a 612x792 page.
        # Vertically centered: y0=116, y1=676 -- both comfortably inside the
        # top/bottom 12% (95.04pt) edge bands with ~21pt of clearance, so
        # this figure does NOT touch either band.
        width, height = 606.0, 560.0
        x0 = (PAGE_WIDTH - width) / 2
        y0 = (PAGE_HEIGHT - height) / 2
        rect = fitz.Rect(x0, y0, x0 + width, y0 + height)
        area_fraction = (width * height) / PAGE_AREA
        assert area_fraction > 0.65, "sanity: this must be a large figure, not a small one"

        top_band = 0.12 * PAGE_HEIGHT
        bottom_band = PAGE_HEIGHT - 0.12 * PAGE_HEIGHT
        assert rect.y0 > top_band, "sanity: figure must not touch the top edge band"
        assert rect.y1 < bottom_band, "sanity: figure must not touch the bottom edge band"

        def draw(page):
            page.draw_rect(rect, width=2)

        doc, page = _make_region_pdf(path, draw)
        try:
            # Deliberately calling with only `frame_tables` (no
            # `frame_drawings`), the pre-A5b signature -- this exact call
            # was confirmed to fail against the pre-A5b code (the old
            # unconditional >60%-page-area pre-filter dropped this drawing
            # before clustering ever saw it, regardless of repetition), see
            # task-A5b-report.md.
            regions = figures_lib.detect_figure_regions(page, 1, path, frame_tables=[])
            assert len(regions) == 1, (
                "a large (~70% of page), one-off, non-repeating figure that doesn't "
                f"touch either edge band must survive detection -- got {regions}"
            )
            bbox = regions[0]["bbox"]
            region_area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
            assert region_area / PAGE_AREA > 0.6
        finally:
            doc.close()


class TestTallFigureMostlyOutsideBandIsKept:
    """A tall figure that reaches into the bottom edge band, but whose own
    area is mostly outside it, must be detected -- the old "any overlap"
    band rule would have dropped it; the new majority-area rule must not."""

    def test_tall_figure_grazing_bottom_band_is_detected(self, tmp_path):
        path = tmp_path / "tall_figure.pdf"

        bottom_band_y0 = PAGE_HEIGHT - 0.12 * PAGE_HEIGHT  # 696.96
        # Spans from well above the band down to 20pt into it: total height
        # 300pt, only the last 20pt (~6.7%) inside the band -- comfortably
        # under the 50% majority-area threshold.
        y1 = bottom_band_y0 + 20.0
        y0 = y1 - 300.0
        rect = fitz.Rect(150, y0, 450, y1)
        assert rect.y1 > bottom_band_y0, "sanity: figure must reach into the bottom band"
        band_overlap = (rect.y1 - bottom_band_y0) / (rect.y1 - rect.y0)
        assert band_overlap < 0.5, "sanity: majority of the figure's area must be outside the band"

        def draw(page):
            page.draw_rect(rect, width=2)

        doc, page = _make_region_pdf(path, draw)
        try:
            regions = figures_lib.detect_figure_regions(page, 1, path, frame_tables=[], frame_drawings=[])
            assert len(regions) == 1, f"a figure mostly outside the band must survive -- got {regions}"
        finally:
            doc.close()

    def test_figure_mostly_inside_band_is_still_excluded(self, tmp_path):
        """Sanity check on the gate itself: a figure whose area is MOSTLY
        inside the band is still dropped -- the new rule loosens the old
        one, it doesn't remove the exclusion entirely."""
        path = tmp_path / "mostly_band_figure.pdf"

        bottom_band_y0 = PAGE_HEIGHT - 0.12 * PAGE_HEIGHT
        y0 = bottom_band_y0 - 5.0
        y1 = PAGE_HEIGHT - 5.0
        rect = fitz.Rect(150, y0, 450, y1)

        def draw(page):
            page.draw_rect(rect, width=2)

        doc, page = _make_region_pdf(path, draw)
        try:
            regions = figures_lib.detect_figure_regions(page, 1, path, frame_tables=[], frame_drawings=[])
            assert regions == []
        finally:
            doc.close()


class TestRepeatedFrameStillRemoved:
    """furniture_sample.pdf's real page-frame border (a single, plain,
    unruled c.rect() drawn on every page) must still be identified and
    removed -- now via repetition (frame_drawings), not size alone."""

    def test_frame_drawings_nonempty_for_furniture_sample(self, furniture_doc, tmp_project):
        triage = _run_triage(furniture_doc, tmp_project)
        frame_drawings = triage["furniture"]["frame_drawings"]
        assert frame_drawings, "expected the repeated page-frame border to be detected by repetition"
        golden_frame_bbox = _golden()["furniture"]["frame_bbox"]
        found_bbox = frame_drawings[0]["bbox"]
        for observed, expected in zip(found_bbox, golden_frame_bbox):
            assert abs(observed - expected) <= 3.0
        assert frame_drawings[0]["page_count"] >= 0.9 * triage["page_count"]

    def test_figure_pages_still_give_exactly_one_region_each(self, furniture_doc, tmp_project):
        triage = _run_triage(furniture_doc, tmp_project)
        frame_drawings = triage["furniture"]["frame_drawings"]
        pdf_path = EXAMPLES_ROOT / "furniture_sample.pdf"
        doc = fitz.open(pdf_path)
        try:
            for kind in ("diagram", "chart"):
                page_number = next(f["page"] for f in _golden()["figures"] if f["kind"] == kind)
                page = doc[page_number - 1]
                regions = figures_lib.detect_figure_regions(
                    page, page_number, pdf_path, frame_tables=[], frame_drawings=frame_drawings,
                )
                assert len(regions) == 1, f"page {page_number} ({kind}): expected exactly one region, got {regions}"
        finally:
            doc.close()

    def test_frame_never_becomes_a_region_on_any_page(self, furniture_doc, tmp_project):
        triage = _run_triage(furniture_doc, tmp_project)
        frame_drawings = triage["furniture"]["frame_drawings"]
        pdf_path = EXAMPLES_ROOT / "furniture_sample.pdf"
        doc = fitz.open(pdf_path)
        try:
            page_area = doc[0].rect.width * doc[0].rect.height
            for page_number in range(1, doc.page_count + 1):
                page = doc[page_number - 1]
                for region in figures_lib.detect_figure_regions(
                    page, page_number, pdf_path, frame_tables=[], frame_drawings=frame_drawings,
                ):
                    bbox = region["bbox"]
                    area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
                    assert area / page_area < 0.5, f"page {page_number}: frame leaked as a region ({bbox})"
        finally:
            doc.close()


class TestFrameOnlyPageGivesNoRegion:
    def test_page_frame_border_alone_produces_no_region(self, tmp_path):
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


class TestExcludedRegionsRecorded:
    """Every region a filter removes must appear in excluded_regions with
    the right reason -- the core "no silent drops" contract."""

    def test_frame_drawing_recorded_with_reason(self, tmp_path):
        path = tmp_path / "frame_excl.pdf"
        frame_bbox = [24.0, 24.0, 588.0, 768.0]

        def draw(page):
            page.draw_rect(fitz.Rect(*frame_bbox), width=1)

        doc, page = _make_region_pdf(path, draw)
        try:
            regions, excluded = figures_lib.detect_figure_regions_with_exclusions(
                page, 1, path, frame_tables=[], frame_drawings=[{"bbox": frame_bbox, "page_count": 2}],
            )
            assert regions == []
            assert len(excluded) == 1
            assert excluded[0]["reason"] == "frame_drawing"
        finally:
            doc.close()

    def test_tiny_stray_line_recorded_with_reason(self, tmp_path):
        path = tmp_path / "tiny_excl.pdf"

        def draw(page):
            page.draw_rect(fitz.Rect(100, 398, 160, 402), width=1)

        doc, page = _make_region_pdf(path, draw)
        try:
            regions, excluded = figures_lib.detect_figure_regions_with_exclusions(
                page, 1, path, frame_tables=[], frame_drawings=[],
            )
            assert regions == []
            assert len(excluded) == 1
            assert excluded[0]["reason"] == "tiny"
        finally:
            doc.close()

    def test_furniture_band_exclusion_recorded_with_reason(self, tmp_path):
        path = tmp_path / "band_excl.pdf"

        def draw(page):
            page.draw_rect(fitz.Rect(150, 15, 450, 70), width=1)  # fully in the top band

        doc, page = _make_region_pdf(path, draw)
        try:
            regions, excluded = figures_lib.detect_figure_regions_with_exclusions(
                page, 1, path, frame_tables=[], frame_drawings=[],
            )
            assert regions == []
            assert len(excluded) == 1
            assert excluded[0]["reason"] == "furniture_band"
        finally:
            doc.close()

    def test_table_overlap_exclusion_recorded_with_reason(self, tmp_path):
        path = tmp_path / "table_excl.pdf"

        def draw(page):
            x0, y0, x1, y1 = 150, 300, 450, 380
            for yy in (y0, (y0 + y1) / 2, y1):
                page.draw_line((x0, yy), (x1, yy), width=1)
            for xx in (x0, (x0 + x1) / 2, x1):
                page.draw_line((xx, y0), (xx, y1), width=1)

        doc, page = _make_region_pdf(path, draw)
        try:
            regions, excluded = figures_lib.detect_figure_regions_with_exclusions(
                page, 1, path, frame_tables=[], frame_drawings=[],
            )
            assert regions == []
            assert len(excluded) == 1
            assert excluded[0]["reason"] == "table_overlap"
        finally:
            doc.close()

    def test_excluded_regions_land_in_the_image_shard(self, tmp_path, tmp_project):
        """End-to-end: extract_images.py writes excluded_regions into the
        page's image shard, one entry per dropped candidate.

        Three pages, not one: triage.py's repetition-based frame detection
        counts a drawing as a repeated "frame" once it appears on at least
        half the document's pages (same threshold/shape as A1's
        frame_tables) -- on a single-page document, any large drawing
        trivially "repeats" on 100% of that one page. Two extra blank pages
        keep the large rect's 1-of-3 occurrence safely under that 50%
        threshold, so triage correctly does NOT mistake this one-off large
        figure for a repeated page frame."""
        path = tmp_project / "input" / "large_excl.pdf"

        width, height = 606.0, 560.0
        x0 = (PAGE_WIDTH - width) / 2
        y0 = (PAGE_HEIGHT - height) / 2
        rect = fitz.Rect(x0, y0, x0 + width, y0 + height)
        # Well clear of `rect`'s own bbox (y1=14 < rect.y0=116, so their
        # bboxes don't overlap and cluster_drawings() keeps them as two
        # separate candidates) and tiny (20x4 = 80pt^2, ~0.02% of the page).
        tiny = fitz.Rect(10, 10, 30, 14)

        doc = fitz.open()
        page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        page.draw_rect(rect, width=2)
        page.draw_rect(tiny, width=1)
        doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        doc.save(str(path))
        doc.close()

        _run_ok("pdf-triage/scripts/triage.py", "--doc", "large_excl", cwd=tmp_project)
        _run_ok("extract-images/scripts/extract_images.py", "--doc", "large_excl", "--pages", "1", cwd=tmp_project)

        shard = json.loads(paths.shard_path("large_excl", 1, "image").read_text())
        assert "excluded_regions" in shard
        reasons = {r["reason"] for r in shard["excluded_regions"]}
        assert "tiny" in reasons
        # The large rect and the tiny rect are far enough apart (see
        # coordinates above) that cluster_drawings() keeps them separate --
        # the large one is a real, non-repeating figure and must be KEPT,
        # not excluded.
        vectors = [e for e in shard["elements"] if e["kind"] == "vector"]
        assert len(vectors) == 1


class TestLargeRegionExcludedGate:
    """gates.py's `large_region_excluded` -- a warning entry (never a hard
    `checks` failure, see check_large_region_excluded's docstring), fired
    for a LARGE excluded region dropped by `table_overlap` or
    `furniture_band`, and never for `frame_drawing` (or `tiny`)."""

    PAGE_AREAS = {1: PAGE_AREA}

    def _doc_data(self, excluded_regions: list[dict]) -> dict:
        return {
            "doc": "sample",
            "pages": {1: {"page_number": 1, "elements": [], "excluded_regions": excluded_regions}},
        }

    def _large_bbox(self) -> list[float]:
        # ~70% of the page -- comfortably over the gate's 20% threshold.
        width, height = 606.0, 560.0
        x0 = (PAGE_WIDTH - width) / 2
        y0 = (PAGE_HEIGHT - height) / 2
        return [x0, y0, x0 + width, y0 + height]

    def test_fires_for_large_table_overlap_exclusion(self):
        doc_data = self._doc_data([{"bbox": self._large_bbox(), "reason": "table_overlap"}])
        warnings = gates.check_large_region_excluded(doc_data, self.PAGE_AREAS)
        assert len(warnings) == 1
        assert warnings[0]["name"] == "large_region_excluded"
        assert warnings[0]["page"] == 1
        assert warnings[0]["reason"] == "table_overlap"

    def test_fires_for_large_furniture_band_exclusion(self):
        doc_data = self._doc_data([{"bbox": self._large_bbox(), "reason": "furniture_band"}])
        warnings = gates.check_large_region_excluded(doc_data, self.PAGE_AREAS)
        assert len(warnings) == 1
        assert warnings[0]["reason"] == "furniture_band"

    def test_does_not_fire_for_the_frame(self):
        doc_data = self._doc_data([{"bbox": self._large_bbox(), "reason": "frame_drawing"}])
        warnings = gates.check_large_region_excluded(doc_data, self.PAGE_AREAS)
        assert warnings == []

    def test_does_not_fire_for_tiny(self):
        tiny_bbox = [10.0, 10.0, 30.0, 14.0]
        doc_data = self._doc_data([{"bbox": tiny_bbox, "reason": "tiny"}])
        warnings = gates.check_large_region_excluded(doc_data, self.PAGE_AREAS)
        assert warnings == []

    def test_does_not_fire_for_a_small_table_overlap_exclusion(self):
        """A large REASON isn't enough on its own -- the region itself must
        be large (>20% of the page)."""
        small_bbox = [150.0, 300.0, 250.0, 340.0]  # 100x40 = 4000pt^2, ~0.8%
        doc_data = self._doc_data([{"bbox": small_bbox, "reason": "table_overlap"}])
        warnings = gates.check_large_region_excluded(doc_data, self.PAGE_AREAS)
        assert warnings == []

    def test_never_a_hard_failure(self, tmp_path):
        """large_region_excluded is a warning, never part of `checks` --
        `passed` must not be affected by it, even end-to-end through gates.py's
        CLI (see main())."""
        doc_data = self._doc_data([{"bbox": self._large_bbox(), "reason": "table_overlap"}])
        warnings = gates.check_large_region_excluded(doc_data, self.PAGE_AREAS)
        assert warnings  # sanity: this scenario does fire the warning
        # None of gates.py's hard `checks` are computed from excluded_regions
        # at all -- check_no_empty_pages/check_image_refs_resolve/etc. only
        # ever look at "elements"/"tier"/"asset", never "excluded_regions".


class TestGatesEndToEndWritesWarnings:
    """gates.py's CLI writes a top-level "warnings" list to gates-report.json,
    populated for a real document whose image shard recorded a large
    excluded region, and the run still passes (warnings never fail a gate)."""

    def test_large_excluded_region_appears_as_a_warning_not_a_failure(self, tmp_project):
        path = tmp_project / "input" / "large_table_overlap.pdf"

        # A page-covering rect (a "figure") whose cluster overlaps a real
        # ruled table drawn on top of most of it -- the table-overlap
        # exclusion rule drops the (large) figure region, which must show up
        # as a warning, not silently, and must not fail the run.
        width, height = 606.0, 560.0
        x0 = (PAGE_WIDTH - width) / 2
        y0 = (PAGE_HEIGHT - height) / 2
        fig_rect = fitz.Rect(x0, y0, x0 + width, y0 + height)

        doc = fitz.open()
        page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        page.draw_rect(fig_rect, width=2)
        # A ruled table (grid lines) covering most of the same area -- real
        # tables are pdfplumber-detected via line intersections.
        tx0, ty0, tx1, ty1 = x0 + 20, y0 + 20, x0 + width - 20, y0 + height - 20
        for frac in (0.0, 0.33, 0.66, 1.0):
            yy = ty0 + frac * (ty1 - ty0)
            page.draw_line((tx0, yy), (tx1, yy), width=1)
        for frac in (0.0, 0.5, 1.0):
            xx = tx0 + frac * (tx1 - tx0)
            page.draw_line((xx, ty0), (xx, ty1), width=1)
        # Pages 2-3 need SOME content -- gates.py's no_empty_pages check
        # would otherwise (correctly) fail an empty page, which isn't what
        # this test is exercising.
        for _ in range(2):
            blank = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            blank.insert_text((72, 100), "Filler page text.")
        doc.save(str(path))
        doc.close()

        triage = _run_triage("large_table_overlap", tmp_project)
        _run_ok(
            "extract-text/scripts/extract_text.py", "--doc", "large_table_overlap",
            "--pages", "1,2,3", "--body-size", str(triage["body_size"]), cwd=tmp_project,
        )
        _run_ok(
            "extract-images/scripts/extract_images.py", "--doc", "large_table_overlap",
            "--pages", "1,2,3", cwd=tmp_project,
        )
        _run_ok("assemble-output/scripts/merge.py", "--doc", "large_table_overlap", cwd=tmp_project)

        shard = json.loads(paths.shard_path("large_table_overlap", 1, "image").read_text())
        reasons = {r["reason"] for r in shard["excluded_regions"]}
        assert "table_overlap" in reasons, f"sanity: expected a table_overlap exclusion, got {shard['excluded_regions']}"

        _run_ok("assemble-output/scripts/assemble.py", "--doc", "large_table_overlap", "--format", "md", cwd=tmp_project)
        gates_out = _run_ok("grade-output/scripts/gates.py", "--doc", "large_table_overlap", "--format", "md", cwd=tmp_project)
        report = json.loads(gates_out)

        assert report["passed"] is True, "a large excluded region must be a warning, not a gate failure"
        large_warnings = [w for w in report["warnings"] if w["name"] == "large_region_excluded"]
        assert large_warnings, f"expected a large_region_excluded warning, got {report['warnings']}"
        assert large_warnings[0]["reason"] == "table_overlap"


class TestSamplePdfRegressionUnchanged:
    """sample.pdf's page-4 vector diagram -- unaffected by this task's
    changes (no page-covering drawing on that fixture at all)."""

    def test_page4_vector_diagram_still_one_region(self, pdf_doc, tmp_project):
        _run_ok("pdf-triage/scripts/triage.py", "--doc", pdf_doc, cwd=tmp_project)
        _run_ok("extract-images/scripts/extract_images.py", "--doc", pdf_doc, "--pages", "4", cwd=tmp_project)
        shard = json.loads(paths.shard_path(pdf_doc, 4, "image").read_text())
        vectors = [e for e in shard["elements"] if e["kind"] == "vector"]
        assert len(vectors) == 1
        assert shard.get("excluded_regions") == []
