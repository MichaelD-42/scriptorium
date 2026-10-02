"""Task A7 -- Markdown/HTML rendering of `image` elements, including the
interpretation markers around agent-judged fields.

Rendering order for one `image` element (see
`assemble.py`'s `render_image_markdown`):

1. `![alt](asset)` -- alt prefers `description`, falls back to `caption`,
   else empty.
2. `caption`, if present -- plain text, verbatim, script-authoritative.
   NOT wrapped in interpretation markers.
3. `figure_text`, if present -- a Markdown blockquote (this codebase's
   convention for verbatim quoted content, no other precedent existed so
   blockquote was chosen for Markdown readability over a fenced block).
   NOT wrapped in interpretation markers either -- same trust tier as
   caption.
4. `description`/`data_table`/`mermaid`, if any are present, wrapped in
   `<!-- scriptorium:interpretation -->` / `<!-- /scriptorium:interpretation
   -->` -- these are agent-judged/authored fields, not extracted verbatim.
   No markers at all when none of the three are present.

The HTML template (`output.html.j2`) mirrors the same ordering: image,
figcaption, a `<blockquote>` for figure_text, then the same HTML-comment
marker pair (chosen over a `data-scriptorium-interpretation` div -- an HTML
comment is literal text either way, and reusing the exact same marker
string as Markdown keeps one greppable convention instead of two).
"""

import json

import pytest

import elements as elements_lib
import paths
from conftest import EXAMPLES_ROOT, describe_all_images, load_script, run_script

assemble = load_script("assemble-output/scripts/assemble.py", "assemble_module_a7")
describe_image = load_script("extract-images/scripts/describe_image.py", "describe_image_module_a7")

START = assemble.INTERPRETATION_START
END = assemble.INTERPRETATION_END


def _run_ok(relpath: str, *args: str, cwd) -> str:
    result = run_script(relpath, *args, cwd=cwd)
    assert result.returncode == 0, (
        f"{relpath} {' '.join(args)} failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    return result.stdout


def _between_markers(md: str) -> str:
    return md[md.index(START) + len(START): md.index(END)]


class TestMarkdownAllFieldsSet:
    EL = {
        "type": "image",
        "asset": "assets/a.png",
        "caption": "Figure 1: Process Diagram",
        "figure_text": "Step 1\nStep 2",
        "description": "A three-step process flow.",
        "data_table": [["Step", "Duration"], ["1", "2h"], ["2", "1h"]],
        "mermaid": "flowchart TD\n  A --> B",
    }

    def test_order_image_caption_figure_text_then_markers(self):
        md = assemble.elements_to_markdown([self.EL])
        image_pos = md.index("![A three-step process flow.](assets/a.png)")
        caption_pos = md.index("Figure 1: Process Diagram")
        quote_pos = md.index("> Step 1\n> Step 2")
        start_pos = md.index(START)
        desc_pos = md.index("A three-step process flow.", caption_pos + 1)
        table_pos = md.index("| Step | Duration |")
        mermaid_pos = md.index("```mermaid")
        end_pos = md.index(END)
        assert (
            image_pos < caption_pos < quote_pos < start_pos
            < desc_pos < table_pos < mermaid_pos < end_pos
        )

    def test_caption_and_figure_text_are_outside_the_markers(self):
        md = assemble.elements_to_markdown([self.EL])
        span = _between_markers(md)
        assert "Figure 1: Process Diagram" not in span
        assert "Step 1" not in span
        assert "Step 2" not in span

    def test_alt_text_prefers_description(self):
        md = assemble.elements_to_markdown([self.EL])
        assert "![A three-step process flow.](assets/a.png)" in md

    def test_data_table_renders_as_real_markdown_table_via_shared_helper(self):
        md = assemble.elements_to_markdown([self.EL])
        expected = assemble.render_markdown_table(self.EL["data_table"])
        assert expected in md
        assert "| Step | Duration |" in md
        assert "| --- | --- |" in md

    def test_mermaid_renders_as_fenced_block_with_verbatim_source(self):
        md = assemble.elements_to_markdown([self.EL])
        assert "```mermaid\nflowchart TD\n  A --> B\n```" in md


class TestMarkdownOnlyAssetAndCaption:
    def test_no_marker_pair_emitted(self):
        el = {"type": "image", "asset": "assets/b.png", "caption": "Figure 2: Icon"}
        md = assemble.elements_to_markdown([el])
        assert "![Figure 2: Icon](assets/b.png)" in md  # no description -> alt falls back to caption
        assert "Figure 2: Icon" in md
        assert START not in md
        assert END not in md

    def test_alt_falls_back_to_caption_when_no_description(self):
        el = {"type": "image", "asset": "assets/b.png", "caption": "a caption used as alt"}
        md = assemble.elements_to_markdown([el])
        assert "![a caption used as alt](assets/b.png)" in md


class TestMarkdownFigureTextOnly:
    def test_verbatim_block_present_no_markers(self):
        el = {"type": "image", "asset": "assets/c.png", "figure_text": "Label A\nLabel B"}
        md = assemble.elements_to_markdown([el])
        assert "> Label A\n> Label B" in md
        assert START not in md
        assert END not in md


class TestMarkdownNoInterpretationFieldsAtAllYieldsNoMarkers:
    def test_bare_image_emits_no_empty_marker_pair(self):
        el = {"type": "image", "asset": "assets/d.png"}
        md = assemble.elements_to_markdown([el])
        assert "![](assets/d.png)" in md
        assert START not in md
        assert END not in md


# Fix wave M4: the browser folds the newlines of figure_text into one line
# unless the blockquote keeps them.
BLOCKQUOTE_OPEN = '<blockquote style="white-space: pre-line">'


class TestHtmlFigureTextKeepsLineBreaks:
    def test_blockquote_preserves_newlines(self):
        el = {"type": "image", "asset": "assets/c.png", "figure_text": "Label A\nLabel B"}
        html = assemble.to_html({"doc": "d", "pages": {1: {"page_number": 1, "elements": [el]}}})
        assert BLOCKQUOTE_OPEN + "Label A\nLabel B</blockquote>" in html


class TestHtmlImageRendering:
    def _doc_data(self, el: dict) -> dict:
        return {"doc": "d", "pages": {1: {"page_number": 1, "elements": [el]}}}

    def test_all_fields_render_in_order_with_markers_around_interpretation_only(self):
        el = dict(TestMarkdownAllFieldsSet.EL)
        html = assemble.to_html(self._doc_data(el))

        img_pos = html.index('<img src="assets/a.png"')
        figcaption_pos = html.index("<figcaption>Figure 1: Process Diagram</figcaption>")
        blockquote_pos = html.index(BLOCKQUOTE_OPEN + "Step 1\nStep 2</blockquote>")
        start_pos = html.index(START)
        desc_pos = html.index("<p>A three-step process flow.</p>")
        mermaid_pos = html.index('<pre class="mermaid">')
        end_pos = html.index(END)
        assert (
            img_pos < figcaption_pos < blockquote_pos < start_pos
            < desc_pos < mermaid_pos < end_pos
        )

        span = html[html.index(START) + len(START): html.index(END)]
        assert "Figure 1: Process Diagram" not in span
        assert "Step 1" not in span

    def test_alt_prefers_description(self):
        el = dict(TestMarkdownAllFieldsSet.EL)
        html = assemble.to_html(self._doc_data(el))
        assert 'alt="A three-step process flow."' in html

    def test_no_interpretation_fields_emits_no_markers(self):
        el = {"type": "image", "asset": "b.png", "caption": "Figure 2: Icon"}
        html = assemble.to_html(self._doc_data(el))
        assert START not in html
        assert END not in html
        assert "<figcaption>Figure 2: Icon</figcaption>" in html


class TestFurnitureSampleEndToEnd:
    """The real pipeline: triage -> extract-text/-images -> merge ->
    describe_image (agent-facing description/data_table/mermaid write) ->
    assemble --format md, spot-checked against furniture_sample.pdf's real
    diagram figure."""

    @pytest.fixture
    def furniture_doc(self, tmp_project):
        import shutil

        dest = tmp_project / "input" / "furniture_sample.pdf"
        shutil.copyfile(EXAMPLES_ROOT / "furniture_sample.pdf", dest)
        return "furniture_sample"

    def _golden(self) -> dict:
        return json.loads((EXAMPLES_ROOT / "furniture_golden.json").read_text())

    def test_diagram_figure_renders_with_markers_in_real_assembled_output(self, furniture_doc, tmp_project):
        diagram_page = next(f["page"] for f in self._golden()["figures"] if f["kind"] == "diagram")
        expected_caption = next(f["caption"] for f in self._golden()["figures"] if f["kind"] == "diagram")

        _run_ok("pdf-triage/scripts/triage.py", "--doc", furniture_doc, cwd=tmp_project)
        triage = json.loads(paths.triage_json(furniture_doc).read_text())
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

        shard = json.loads(paths.shard_path(furniture_doc, diagram_page, "image").read_text())
        vectors = [e for e in shard["elements"] if e.get("kind") == "vector"]
        assert len(vectors) == 1
        asset = vectors[0]["asset"]
        assert vectors[0]["caption"] == expected_caption

        # Agent-facing step: land description/data_table/mermaid via
        # describe_image.py, the same script/contract Task A6 built.
        result = run_script(
            "extract-images/scripts/describe_image.py",
            "--doc", furniture_doc, "--page", str(diagram_page), "--asset", asset,
            "--description", "A three-step process flow.",
            "--data-table", json.dumps([["Step", "Duration"], ["1", "2h"]]),
            "--mermaid", "flowchart TD\n  A --> B",
            cwd=tmp_project,
        )
        assert result.returncode == 0, result.stderr

        _run_ok("assemble-output/scripts/merge.py", "--doc", furniture_doc, cwd=tmp_project)
        _run_ok("assemble-output/scripts/assemble.py", "--doc", furniture_doc, "--format", "md", cwd=tmp_project)

        md = (tmp_project / "output" / furniture_doc / f"{furniture_doc}.md").read_text()

        assert f"![A three-step process flow.]({asset})" in md
        assert expected_caption in md
        assert START in md and END in md
        span = md[md.index(START) + len(START): md.index(END)]
        assert expected_caption not in span
        assert "A three-step process flow." in span
        assert "| Step | Duration |" in span
        assert "```mermaid\nflowchart TD\n  A --> B\n```" in span

        # Task A9: the other images need the describe step too, or
        # gates.py's figures_complete check fails. It runs after the
        # Markdown checks above so that the diagram is still the first
        # described image; the diagram keeps its own description.
        describe_all_images(furniture_doc, tmp_project)
        _run_ok("assemble-output/scripts/merge.py", "--doc", furniture_doc, cwd=tmp_project)
        _run_ok("assemble-output/scripts/assemble.py", "--doc", furniture_doc, "--format", "md", cwd=tmp_project)
        gates_out = _run_ok("grade-output/scripts/gates.py", "--doc", furniture_doc, "--format", "md", cwd=tmp_project)
        assert json.loads(gates_out)["passed"] is True
