"""Task A6 -- figure record fields (caption, description, data_table,
mermaid).

`caption` becomes script-authoritative (`lib/figures.py`'s
`find_caption_line`, wired into `extract_images.py`): a nearby text-layer
line matching CAPTION_PATTERN ("Figure 1: ...", "Table 2 ..."), verbatim,
or absent when nothing nearby matches. The same line is excluded from
`extract_text.py`'s paragraph/heading extraction on that page (see also the
updated assertions in test_region_figures.py, which previously expected the
caption line to survive as a paragraph -- Task A5's behavior, intentionally
changed here).

`describe_image.py` (renamed/generalized from `caption_image.py`) is the
agent-facing script for the three fields a script cannot judge on its own:
`description` (always), `data_table` (optional, parsed JSON), `mermaid`
(optional, validated the same way mermaid_image.py validates its own
stdin-read source).

Fixtures used:
- `furniture_sample.pdf` (Task A0): page 7's diagram and page 8's chart,
  each with a real "Figure n: ..." caption a known, fixed distance below
  its region -- furniture_golden.json's "figures" entries are the ground
  truth. Page 4's unique (non-furniture) bitmap icon has no nearby caption
  text at all -- the negative case.
"""

import json

import fitz  # PyMuPDF
import pytest

import elements as elements_lib
import figures as figures_lib
import paths
from conftest import EXAMPLES_ROOT, load_script, run_script

describe_image = load_script("extract-images/scripts/describe_image.py", "describe_image_module")


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
    import shutil

    dest = tmp_project / "input" / "furniture_sample.pdf"
    shutil.copyfile(EXAMPLES_ROOT / "furniture_sample.pdf", dest)
    return "furniture_sample"


class TestScriptAuthoritativeCaption:
    """extract_images.py sets `caption` itself, verbatim, matching
    furniture_golden.json's recorded captions -- no agent involved."""

    def test_diagram_region_caption_matches_golden(self, furniture_doc, tmp_project):
        diagram_page = _figure_page("diagram")
        golden = _golden()
        expected = next(f["caption"] for f in golden["figures"] if f["kind"] == "diagram")

        _run_triage(furniture_doc, tmp_project)
        _run_ok("extract-images/scripts/extract_images.py", "--doc", furniture_doc, "--pages", str(diagram_page), cwd=tmp_project)

        shard = json.loads(paths.shard_path(furniture_doc, diagram_page, "image").read_text())
        vectors = [e for e in shard["elements"] if e["kind"] == "vector"]
        assert len(vectors) == 1
        assert vectors[0]["caption"] == expected

    def test_chart_region_caption_matches_golden(self, furniture_doc, tmp_project):
        chart_page = _figure_page("chart")
        golden = _golden()
        expected = next(f["caption"] for f in golden["figures"] if f["kind"] == "chart")

        _run_triage(furniture_doc, tmp_project)
        _run_ok("extract-images/scripts/extract_images.py", "--doc", furniture_doc, "--pages", str(chart_page), cwd=tmp_project)

        shard = json.loads(paths.shard_path(furniture_doc, chart_page, "image").read_text())
        vectors = [e for e in shard["elements"] if e["kind"] == "vector"]
        assert len(vectors) == 1
        assert vectors[0]["caption"] == expected

    def test_caption_line_excluded_from_paragraph_extraction(self, furniture_doc, tmp_project):
        """Same page, extract_text.py's own output -- the caption line must
        not also survive as a paragraph/heading element."""
        diagram_page = _figure_page("diagram")
        triage = _run_triage(furniture_doc, tmp_project)
        _run_ok(
            "extract-text/scripts/extract_text.py", "--doc", furniture_doc,
            "--pages", str(diagram_page), "--body-size", str(triage["body_size"]),
            cwd=tmp_project,
        )
        shard = json.loads(paths.shard_path(furniture_doc, diagram_page, "text").read_text())
        texts = [e.get("text") for e in shard["elements"]]
        assert "Figure 1: Process Diagram" not in texts
        # Surrounding real content on the same page still survives.
        assert any("vector-drawn flow diagram" in (t or "") for t in texts)

    def test_bitmap_with_no_nearby_caption_text_gets_no_caption(self, furniture_doc, tmp_project):
        """Page 4's unique (non-furniture) icon has no "Figure"/"Table"
        text anywhere near it -- caption must stay absent, not a false
        match against unrelated nearby body text."""
        _run_triage(furniture_doc, tmp_project)
        _run_ok("extract-images/scripts/extract_images.py", "--doc", furniture_doc, "--pages", "4", cwd=tmp_project)

        shard = json.loads(paths.shard_path(furniture_doc, 4, "image").read_text())
        bitmaps = [e for e in shard["elements"] if e["kind"] == "bitmap"]
        assert len(bitmaps) == 1
        assert "caption" not in bitmaps[0] or bitmaps[0]["caption"] is None

    def test_find_caption_line_returns_none_when_nothing_matches(self):
        """Direct unit test against lib/figures.py: an arbitrary bbox on a
        page with no "Figure"/"Table"-pattern text nearby returns None."""
        pdf_path = EXAMPLES_ROOT / "furniture_sample.pdf"
        doc = fitz.open(pdf_path)
        try:
            page = doc[3]  # page 4 -- no figure/table caption anywhere on it
            # A bbox roughly where the unique icon sits (top-right corner).
            bbox = [546.0, 34.0, 572.0, 60.0]
            assert figures_lib.find_caption_line(page, bbox) is None
        finally:
            doc.close()


class TestDescribeImageCli:
    """describe_image.py -- renamed/generalized from caption_image.py
    (Task A6): writes description (always), data_table (optional, parsed
    JSON), mermaid (optional), located by --doc/--page/--asset, same lookup
    convention as before."""

    def test_writes_description_only_by_default(self, tmp_project, monkeypatch):
        shard_path = paths.shard_path("doc", 1, "image")
        elements_lib.write_shard(shard_path, 1, [{"type": "image", "asset": "assets/a.png", "bbox": [0, 0, 1, 1]}])

        monkeypatch.setattr(
            "sys.argv",
            ["describe_image.py", "--doc", "doc", "--page", "1", "--asset", "assets/a.png", "--description", "a bar chart"],
        )
        describe_image.main()

        shard = json.loads(shard_path.read_text())
        el = shard["elements"][0]
        assert el["description"] == "a bar chart"
        assert "data_table" not in el
        assert "mermaid" not in el

    def test_writes_data_table_as_parsed_structure(self, tmp_project, monkeypatch):
        shard_path = paths.shard_path("doc", 1, "image")
        elements_lib.write_shard(shard_path, 1, [{"type": "image", "asset": "assets/a.png", "bbox": [0, 0, 1, 1]}])

        monkeypatch.setattr(
            "sys.argv",
            [
                "describe_image.py", "--doc", "doc", "--page", "1", "--asset", "assets/a.png",
                "--description", "a bar chart",
                "--data-table", json.dumps([["Q1", 10], ["Q2", 14]]),
            ],
        )
        describe_image.main()

        shard = json.loads(shard_path.read_text())
        el = shard["elements"][0]
        assert el["data_table"] == [["Q1", 10], ["Q2", 14]]
        assert isinstance(el["data_table"], list)

    def test_invalid_data_table_json_exits_with_error(self, tmp_project, monkeypatch):
        shard_path = paths.shard_path("doc", 1, "image")
        elements_lib.write_shard(shard_path, 1, [{"type": "image", "asset": "assets/a.png", "bbox": [0, 0, 1, 1]}])

        monkeypatch.setattr(
            "sys.argv",
            [
                "describe_image.py", "--doc", "doc", "--page", "1", "--asset", "assets/a.png",
                "--description", "x", "--data-table", "not json",
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            describe_image.main()
        assert exc_info.value.code == 1

    def test_writes_mermaid_verbatim(self, tmp_project, monkeypatch):
        shard_path = paths.shard_path("doc", 1, "image")
        elements_lib.write_shard(shard_path, 1, [{"type": "image", "asset": "assets/a.png", "bbox": [0, 0, 1, 1]}])

        mermaid_src = "flowchart TD\n  A --> B"
        monkeypatch.setattr(
            "sys.argv",
            [
                "describe_image.py", "--doc", "doc", "--page", "1", "--asset", "assets/a.png",
                "--description", "a flow diagram", "--mermaid", mermaid_src,
            ],
        )
        describe_image.main()

        shard = json.loads(shard_path.read_text())
        assert shard["elements"][0]["mermaid"] == mermaid_src

    def test_invalid_mermaid_exits_with_error(self, tmp_project, monkeypatch):
        shard_path = paths.shard_path("doc", 1, "image")
        elements_lib.write_shard(shard_path, 1, [{"type": "image", "asset": "assets/a.png", "bbox": [0, 0, 1, 1]}])

        monkeypatch.setattr(
            "sys.argv",
            [
                "describe_image.py", "--doc", "doc", "--page", "1", "--asset", "assets/a.png",
                "--description", "x", "--mermaid", "just some prose",
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            describe_image.main()
        assert exc_info.value.code == 1

    def test_caption_alias_still_sets_caption(self, tmp_project, monkeypatch, capsys):
        """Backward compat: pptx/docx/xlsx/html images have no script-side
        caption detection, so --caption stays a real (if deprecated,
        warned-about) alias rather than a no-op."""
        shard_path = paths.shard_path("doc", 1, "image")
        elements_lib.write_shard(shard_path, 1, [{"type": "image", "asset": "assets/a.png", "bbox": [0, 0, 1, 1]}])

        monkeypatch.setattr(
            "sys.argv",
            [
                "describe_image.py", "--doc", "doc", "--page", "1", "--asset", "assets/a.png",
                "--description", "a blue icon", "--caption", "a blue circle icon",
            ],
        )
        describe_image.main()

        shard = json.loads(shard_path.read_text())
        assert shard["elements"][0]["caption"] == "a blue circle icon"
        assert "deprecated" in capsys.readouterr().err

    def test_figure_text_alias_lands_vision_transcription(self, tmp_project, monkeypatch):
        """Judgment call (documented in task-A6-report.md): a small
        addition beyond the brief's three named fields, so the agent has an
        actual write path for A5's pre-ruled "fill figure_text via vision
        when it comes back null" contract."""
        shard_path = paths.shard_path("doc", 1, "image")
        elements_lib.write_shard(shard_path, 1, [{"type": "image", "asset": "assets/a.png", "bbox": [0, 0, 1, 1]}])

        monkeypatch.setattr(
            "sys.argv",
            [
                "describe_image.py", "--doc", "doc", "--page", "1", "--asset", "assets/a.png",
                "--description", "a flow diagram", "--figure-text", "Start\nProcess\nEnd",
            ],
        )
        describe_image.main()

        shard = json.loads(shard_path.read_text())
        assert shard["elements"][0]["figure_text"] == "Start\nProcess\nEnd"

    def test_figure_text_alias_refuses_to_overwrite_script_side_value(self, tmp_project, monkeypatch, capsys):
        """Fix round 1: A5's contract is that the agent only fills
        figure_text via vision when the script-side value came back
        null/absent -- never overwrite real, deterministically-extracted
        text. Unlike --caption/--data-table/--mermaid, this precondition is
        code-checkable, so it's a hard refusal (exit 1), not documentation
        only."""
        shard_path = paths.shard_path("doc", 1, "image")
        elements_lib.write_shard(shard_path, 1, [
            {"type": "image", "asset": "assets/a.png", "bbox": [0, 0, 1, 1], "figure_text": "Start\nEnd"},
        ])

        monkeypatch.setattr(
            "sys.argv",
            [
                "describe_image.py", "--doc", "doc", "--page", "1", "--asset", "assets/a.png",
                "--description", "a flow diagram", "--figure-text", "a vision guess",
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            describe_image.main()
        assert exc_info.value.code == 1
        assert "figure_text" in capsys.readouterr().err

        # The guard fires before the shard is ever rewritten -- the
        # original script-side figure_text (and every other field) is
        # untouched, not just figure_text specifically.
        shard = json.loads(shard_path.read_text())
        assert shard["elements"][0]["figure_text"] == "Start\nEnd"
        assert "description" not in shard["elements"][0]

    def test_locates_correct_element_among_several_on_same_page(self, tmp_project, monkeypatch):
        shard_path = paths.shard_path("doc", 1, "image")
        elements_lib.write_shard(shard_path, 1, [
            {"type": "image", "asset": "assets/page1_bitmap1.png", "bbox": [0, 0, 1, 1]},
            {"type": "image", "asset": "assets/page1_vector1.png", "bbox": [0, 0, 1, 1]},
            {"type": "image", "asset": "assets/page1_bitmap2.png", "bbox": [0, 0, 1, 1]},
        ])

        monkeypatch.setattr(
            "sys.argv",
            [
                "describe_image.py", "--doc", "doc", "--page", "1",
                "--asset", "assets/page1_vector1.png", "--description", "the right one",
            ],
        )
        describe_image.main()

        shard = json.loads(shard_path.read_text())
        by_asset = {el["asset"]: el for el in shard["elements"]}
        assert by_asset["assets/page1_vector1.png"]["description"] == "the right one"
        assert "description" not in by_asset["assets/page1_bitmap1.png"]
        assert "description" not in by_asset["assets/page1_bitmap2.png"]

    def test_missing_shard_exits_with_error(self, tmp_project, monkeypatch):
        monkeypatch.setattr(
            "sys.argv",
            ["describe_image.py", "--doc", "doc", "--page", "1", "--asset", "assets/a.png", "--description", "x"],
        )
        with pytest.raises(SystemExit) as exc_info:
            describe_image.main()
        assert exc_info.value.code == 1

    def test_unknown_asset_exits_with_error(self, tmp_project, monkeypatch):
        shard_path = paths.shard_path("doc", 1, "image")
        elements_lib.write_shard(shard_path, 1, [{"type": "image", "asset": "assets/other.png", "bbox": [0, 0, 1, 1]}])

        monkeypatch.setattr(
            "sys.argv",
            ["describe_image.py", "--doc", "doc", "--page", "1", "--asset", "assets/a.png", "--description", "x"],
        )
        with pytest.raises(SystemExit) as exc_info:
            describe_image.main()
        assert exc_info.value.code == 1
