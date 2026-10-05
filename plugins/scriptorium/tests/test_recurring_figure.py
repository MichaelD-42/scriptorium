"""Follow-up R1: a recurring figure is not page furniture.

The fixture is the re-review's probe 2 shape, rebuilt synthetically: a
6-page document whose page frame (one stroked rect and a footer) is on every
page, and whose small flow diagram (three boxes joined by lines, with the
caption "Figure 1: Recurring loop") sits at the same position on pages 2-5,
4 of the 6 pages. `repeated_drawings` needs a drawing on at least
`furniture.REPEATED_DRAWING_MIN_PAGE_FRACTION` (80%) of the body pages, so
the frame is still removed and the diagram is a figure on each page.

Page 6 holds a "Figure n" line with no figure, for the
`orphan_figure_caption` gate warning.
"""

import json
from pathlib import Path

import fitz  # PyMuPDF
import furniture as furniture_lib
import paths
from conftest import load_script, run_script

gates = load_script("grade-output/scripts/gates.py", "gates_module_recurring_figure")

DOC = "recurring_figure"
PAGE_WIDTH, PAGE_HEIGHT = 595.0, 842.0
PAGE_AREA = PAGE_WIDTH * PAGE_HEIGHT
PAGE_COUNT = 6
DIAGRAM_PAGES = (2, 3, 4, 5)
CAPTION = "Figure 1: Recurring loop"
ORPHAN_CAPTION = "Figure 5: Drawn nowhere"
FRAME_BBOX = [20.0, 20.0, 575.0, 822.0]


def _frame(page, n: int) -> None:
    page.draw_rect(fitz.Rect(*FRAME_BBOX), width=1)
    page.insert_text((40, 802), "Doc No. SYN-0002", fontsize=8)
    page.insert_text((40, 812), f"page {n} ({PAGE_COUNT})", fontsize=8)


def _flow(page, x: float, y: float, labels: list[str]) -> None:
    for i, label in enumerate(labels):
        bx = x + i * 150
        page.draw_rect(fitz.Rect(bx, y, bx + 100, y + 40), width=1)
        page.insert_text((bx + 10, y + 24), label, fontsize=9)
        if i:
            page.draw_line((bx - 50, y + 20), (bx, y + 20), width=1)


def _make_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    _frame(page, 1)
    page.insert_text((72, 242), "Synthetic Probe", fontsize=24)
    for n in DIAGRAM_PAGES:
        page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        _frame(page, n)
        page.insert_text(
            (72, 82), f"Body text on page {n} above the recurring diagram.", fontsize=10
        )
        _flow(page, 72, 202, ["Sense", "Decide", "Act"])
        page.insert_text((72, 272), CAPTION, fontsize=10)
        page.insert_text(
            (72, 302),
            f"Body text on page {n} below the recurring diagram.",
            fontsize=10,
        )
    page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    _frame(page, 6)
    page.insert_text((72, 82), "Body text on the last page.", fontsize=10)
    page.insert_text((72, 302), ORPHAN_CAPTION, fontsize=10)
    doc.save(str(path))
    doc.close()


def _run_ok(relpath: str, *args: str, cwd) -> str:
    result = run_script(relpath, *args, cwd=cwd)
    assert result.returncode == 0, (
        f"{relpath} {' '.join(args)} failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    return result.stdout


def _all_pages() -> str:
    return ",".join(str(p) for p in range(1, PAGE_COUNT + 1))


def _setup(tmp_project) -> dict:
    _make_pdf(tmp_project / "input" / f"{DOC}.pdf")
    _run_ok("pdf-triage/scripts/triage.py", "--doc", DOC, cwd=tmp_project)
    return json.loads(paths.triage_json(DOC).read_text())


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


def _area(bbox) -> float:
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])


class TestRecurringFigure:
    def test_threshold_is_a_named_constant(self):
        assert furniture_lib.REPEATED_DRAWING_MIN_PAGE_FRACTION == 0.8

    def test_diagram_is_not_listed_as_repeated(self, tmp_project):
        triage = _setup(tmp_project)
        counts = {r["page_count"] for r in triage["furniture"]["repeated_drawings"]}
        assert len(DIAGRAM_PAGES) not in counts

    def test_each_diagram_page_has_one_captioned_image(self, tmp_project):
        _setup(tmp_project)
        shards = _image_shards(tmp_project)
        for page_number in DIAGRAM_PAGES:
            images = [
                e for e in shards[page_number]["elements"] if e["type"] == "image"
            ]
            assert len(images) == 1, f"page {page_number}: {shards[page_number]}"
            assert images[0]["caption"] == CAPTION
            assert _area(images[0]["bbox"]) < 0.2 * PAGE_AREA

    def test_full_page_frame_part_is_still_removed(self, tmp_project):
        triage = _setup(tmp_project)
        frame_entries = [
            r
            for r in triage["furniture"]["repeated_drawings"]
            if furniture_lib.bbox_matches(r["bbox"], FRAME_BBOX)
        ]
        assert frame_entries and frame_entries[0]["page_count"] == PAGE_COUNT
        shards = _image_shards(tmp_project)
        for page_number, shard in shards.items():
            for element in shard["elements"]:
                assert _area(element["bbox"]) < 0.5 * PAGE_AREA, (
                    f"page {page_number}: {element}"
                )
            reasons = {r["reason"] for r in shard["excluded_regions"]}
            assert reasons & {"frame_drawing", "repeated_drawing"}, (
                f"page {page_number}: {reasons}"
            )


class TestRepeatedDrawingBoundary:
    """A drawing on exactly 80% of the body pages is still furniture."""

    def test_drawing_on_four_of_five_pages_is_listed(self, tmp_project):
        doc = fitz.open()
        for n in range(1, 6):
            page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            page.insert_text((72, 100), f"Body text on page {n}.", fontsize=10)
            if n != 3:
                page.draw_line((40, 780), (555, 780), width=0.8)
        doc.save(str(tmp_project / "input" / "four_of_five.pdf"))
        doc.close()
        _run_ok(
            "pdf-triage/scripts/triage.py", "--doc", "four_of_five", cwd=tmp_project
        )
        triage = json.loads(paths.triage_json("four_of_five").read_text())
        assert [r["page_count"] for r in triage["furniture"]["repeated_drawings"]] == [
            4
        ]


def _doc_data(pages: dict[int, list[dict]]) -> dict:
    return {
        "doc": "sample",
        "pages": {n: {"page_number": n, "elements": els} for n, els in pages.items()},
    }


class TestOrphanFigureCaption:
    def test_fires_for_a_caption_with_no_image(self):
        doc_data = _doc_data(
            {1: [{"type": "paragraph", "text": "Figure 7: Lost diagram"}]}
        )
        warnings = gates.check_orphan_figure_caption(doc_data)
        assert len(warnings) == 1
        assert warnings[0]["name"] == "orphan_figure_caption"
        assert warnings[0]["page"] == 1
        assert warnings[0]["caption"] == "Figure 7: Lost diagram"

    def test_fires_for_the_fig_dot_form(self):
        doc_data = _doc_data(
            {1: [{"type": "paragraph", "text": "Fig. 3 Lost diagram"}]}
        )
        assert [w["caption"] for w in gates.check_orphan_figure_caption(doc_data)] == [
            "Fig. 3 Lost diagram"
        ]

    def test_silent_for_a_caption_an_image_on_the_same_page_claims(self):
        doc_data = _doc_data(
            {
                1: [
                    {"type": "image", "caption": "Figure 7: Kept diagram"},
                    {"type": "paragraph", "text": "Figure 7: Kept diagram"},
                ],
            }
        )
        assert gates.check_orphan_figure_caption(doc_data) == []

    def test_silent_for_a_caption_an_image_on_the_next_page_claims(self):
        doc_data = _doc_data(
            {
                1: [{"type": "paragraph", "text": "Figure 7: Kept diagram"}],
                2: [{"type": "image", "caption": "Figure 7: Kept diagram"}],
            }
        )
        assert gates.check_orphan_figure_caption(doc_data) == []

    def test_fires_when_the_claiming_image_is_two_pages_away(self):
        doc_data = _doc_data(
            {
                1: [{"type": "paragraph", "text": "Figure 7: Kept diagram"}],
                2: [{"type": "paragraph", "text": "Filler."}],
                3: [{"type": "image", "caption": "Figure 7: Kept diagram"}],
            }
        )
        assert [w["page"] for w in gates.check_orphan_figure_caption(doc_data)] == [1]

    def test_silent_for_a_table_caption_and_body_text(self):
        doc_data = _doc_data(
            {
                1: [
                    {"type": "paragraph", "text": "Table 2: Limits"},
                    {
                        "type": "paragraph",
                        "text": "As Figure 3 shows, the loop is closed.",
                    },
                    {"type": "paragraph", "text": "See figure 3 below."},
                ],
            }
        )
        assert gates.check_orphan_figure_caption(doc_data) == []

    def test_end_to_end_only_the_orphan_line_warns(self, tmp_project):
        triage = _setup(tmp_project)
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
        _image_shards(tmp_project)
        _run_ok("assemble-output/scripts/merge.py", "--doc", DOC, cwd=tmp_project)
        _run_ok(
            "assemble-output/scripts/assemble.py",
            "--doc",
            DOC,
            "--format",
            "md",
            cwd=tmp_project,
        )
        report = json.loads(
            _run_ok(
                "grade-output/scripts/gates.py",
                "--doc",
                DOC,
                "--format",
                "md",
                cwd=tmp_project,
            )
        )
        orphans = [
            w for w in report["warnings"] if w["name"] == "orphan_figure_caption"
        ]
        assert [(w["page"], w["caption"]) for w in orphans] == [(6, ORPHAN_CAPTION)]
