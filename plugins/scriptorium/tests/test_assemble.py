"""Unit tests for assemble-output/scripts/assemble.py -- pure rendering
functions, exercised directly on hand-built doc_data (no filesystem)."""

from conftest import load_script

assemble = load_script("assemble-output/scripts/assemble.py", "assemble_module")


class TestRenderMarkdownTable:
    def test_escapes_pipes_and_newlines(self):
        md = assemble.render_markdown_table([["a|b", "c\nd"], ["1", "2"]])
        header_line = md.splitlines()[0]
        assert header_line == "| a\\|b | c d |"  # pipe escaped, newline collapsed to a space

    def test_ragged_rows_padded_to_widest(self):
        md = assemble.render_markdown_table([["a", "b", "c"], ["1"]])
        lines = md.splitlines()
        assert lines[0].count("|") == lines[2].count("|")

    def test_empty_rows_returns_empty_string(self):
        assert assemble.render_markdown_table([]) == ""


class TestElementsToMarkdown:
    def test_heading_levels_map_to_hashes(self):
        md = assemble.elements_to_markdown([{"type": "heading", "level": 2, "text": "Title"}])
        assert md.startswith("## Title")

    def test_image_with_mermaid_fence_precedes_image_ref(self):
        el = {"type": "image", "asset": "assets/a.png", "caption": "a diagram", "mermaid": "flowchart TD\n  A --> B"}
        md = assemble.elements_to_markdown([el])
        mermaid_pos = md.index("```mermaid")
        image_pos = md.index("![a diagram](assets/a.png)")
        assert mermaid_pos < image_pos

    def test_image_without_mermaid_has_no_fence(self):
        el = {"type": "image", "asset": "assets/a.png", "caption": ""}
        md = assemble.elements_to_markdown([el])
        assert "```mermaid" not in md
        assert "![](assets/a.png)" in md


class TestToHtml:
    def test_has_mermaid_true_when_any_image_has_mermaid(self):
        doc_data = {
            "doc": "d",
            "pages": {1: {"page_number": 1, "elements": [{"type": "image", "asset": "a.png", "mermaid": "graph TD"}]}},
        }
        html = assemble.to_html(doc_data)
        assert "mermaid@10" in html
        assert 'class="mermaid"' in html

    def test_has_mermaid_false_when_no_image_has_mermaid(self):
        doc_data = {
            "doc": "d",
            "pages": {1: {"page_number": 1, "elements": [{"type": "paragraph", "text": "hi"}]}},
        }
        html = assemble.to_html(doc_data)
        assert "mermaid@10" not in html


class TestSplitSectionsByH1:
    def test_splits_on_each_h1_heading(self):
        pages = [
            {
                "page_number": 1,
                "elements": [
                    {"type": "heading", "level": 1, "text": "Intro"},
                    {"type": "paragraph", "text": "p1"},
                    {"type": "heading", "level": 1, "text": "Details"},
                    {"type": "paragraph", "text": "p2"},
                ],
            }
        ]
        sections = assemble.split_sections_by_h1(pages)
        assert [s["title"] for s in sections] == ["Intro", "Details"]
        assert sections[1]["elements"] == [{"type": "paragraph", "text": "p2"}]

    def test_content_before_first_h1_becomes_front_matter(self):
        pages = [{"page_number": 1, "elements": [{"type": "paragraph", "text": "preamble"}]}]
        sections = assemble.split_sections_by_h1(pages)
        assert sections[0]["title"] == "Front Matter"

    def test_no_elements_at_all_yields_no_sections(self):
        assert assemble.split_sections_by_h1([{"page_number": 1, "elements": []}]) == []


class TestFirstSentence:
    def test_returns_up_to_first_sentence_terminator(self):
        elements = [{"type": "paragraph", "text": "First sentence. Second sentence."}]
        assert assemble.first_sentence(elements) == "First sentence."

    def test_truncates_long_sentence_at_word_boundary(self):
        long_text = "word " * 50
        elements = [{"type": "paragraph", "text": long_text.strip()}]
        result = assemble.first_sentence(elements, max_len=20)
        assert len(result) <= 21  # ellipsis char
        assert result.endswith("…")

    def test_no_paragraph_elements_returns_empty_string(self):
        assert assemble.first_sentence([{"type": "heading", "level": 1, "text": "H"}]) == ""
