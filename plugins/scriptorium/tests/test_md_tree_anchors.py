"""Fix wave I4 + M2: md-tree anchors for every heading, and joined pages.

I4: the level-1/level-2 heading that opens a split file is written as
frontmatter, not as a body heading. Its anchor is now the first body line
of the file it opens, so every heading has an anchor in some md-tree file.
A level-1 heading with no body of its own (no `NN.00` file) puts its anchor
at the top of its first `NN.MM` file.

M2: an element joined across a page break (`pages: [n, n+1]`) adds both
pages to its file's `source_pages`.
"""

import json
import re
import shutil
from pathlib import Path

import paths
from conftest import EXAMPLES_ROOT, describe_all_images, load_script, run_script

assemble = load_script("assemble-output/scripts/assemble.py", "assemble_module_anchors")


def _heading(level, text):
    return {"type": "heading", "level": level, "text": text}


def _para(text, **extra):
    return {"type": "paragraph", "text": text, **extra}


def _body(path: Path) -> str:
    """The file's text after its frontmatter block."""
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    return text.split("\n---\n", 1)[1]


def _write(elements_by_page: dict[int, list[dict]]) -> dict[str, Path]:
    doc_data = {
        "doc": "d",
        "pages": {
            n: {"page_number": n, "elements": els}
            for n, els in elements_by_page.items()
        },
    }
    written = assemble.write_md_tree(doc_data, "d", split_depth=2)
    return {p.name: p for p in written}


class TestOpenerAnchors:
    def test_level1_file_starts_with_its_anchor(self, tmp_project):
        files = _write({1: [_heading(1, "1 Chapter"), _para("chapter intro")]})
        body = _body(files["01.00-chapter.md"])
        assert body.startswith('\n<a id="1"></a>\n\nchapter intro\n'), repr(body)

    def test_level2_file_starts_with_its_anchor(self, tmp_project):
        files = _write(
            {
                1: [
                    _heading(1, "1 Chapter"),
                    _para("intro"),
                    _heading(2, "1.1 Section"),
                    _para("body"),
                ]
            }
        )
        body = _body(files["01.01-section.md"])
        assert body.startswith('\n<a id="1-1"></a>\n\nbody\n'), repr(body)
        assert "## 1.1 Section" not in body

    def test_empty_level2_file_still_has_its_anchor(self, tmp_project):
        files = _write(
            {1: [_heading(1, "1 Chapter"), _para("intro"), _heading(2, "1.1 Empty")]}
        )
        assert _body(files["01.01-empty.md"]) == '\n<a id="1-1"></a>\n'

    def test_level1_without_own_body_puts_its_anchor_in_the_first_child(
        self, tmp_project
    ):
        files = _write(
            {
                1: [
                    _heading(1, "2 Chapter"),
                    _heading(2, "2.1 First"),
                    _para("a"),
                    _heading(2, "2.2 Second"),
                    _para("b"),
                ],
            }
        )
        assert "02.00-chapter.md" not in files
        first = _body(files["02.01-first.md"])
        assert first.startswith('\n<a id="2"></a>\n\n<a id="2-1"></a>\n\na\n'), repr(
            first
        )
        assert '<a id="2"></a>' not in _body(files["02.02-second.md"])

    def test_unnumbered_opener_uses_the_text_slug(self, tmp_project):
        files = _write({1: [_heading(1, "Appendix Overview"), _para("text")]})
        name = next(n for n in files if n.endswith("-appendix-overview.md"))
        assert _body(files[name]).startswith('\n<a id="appendix-overview"></a>\n\n')

    def test_inline_headings_keep_their_anchor(self, tmp_project):
        files = _write(
            {
                1: [
                    _heading(1, "1 C"),
                    _heading(2, "1.1 S"),
                    _heading(3, "1.1.1 Deep"),
                    _para("x"),
                ]
            }
        )
        body = _body(files["01.01-s.md"])
        assert (
            body.index('<a id="1-1"></a>')
            < body.index('<a id="1-1-1"></a>')
            < body.index("### 1.1.1 Deep")
        )


class TestJoinedPagesInSourcePages:
    def test_joined_element_adds_its_second_page(self):
        pages = [
            {
                "page_number": 4,
                "elements": [
                    _heading(1, "1 C"),
                    _heading(2, "1.1 S"),
                    _para("cut", pages=[4, 5]),
                ],
            },
            {"page_number": 5, "elements": []},
        ]
        _front, folders = assemble.build_md_tree_sections(pages, split_depth=2)
        assert folders[0]["files"][0]["source_pages"] == [4, 5]

    def test_joined_element_in_front_matter(self):
        pages = [
            {"page_number": 1, "elements": [_para("cut", pages=[1, 2])]},
            {"page_number": 2, "elements": []},
        ]
        front, _folders = assemble.build_md_tree_sections(pages, split_depth=2)
        assert front["source_pages"] == [1, 2]


class TestEveryHeadingHasAnAnchorEndToEnd:
    def test_furniture_sample(self, tmp_project):
        doc = "furniture_sample"
        shutil.copyfile(
            EXAMPLES_ROOT / f"{doc}.pdf", tmp_project / "input" / f"{doc}.pdf"
        )
        result = run_script(
            "pdf-triage/scripts/triage.py", "--doc", doc, cwd=tmp_project
        )
        assert result.returncode == 0, result.stderr
        triage = json.loads(paths.triage_json(doc).read_text())
        pages = ",".join(str(p["page_number"]) for p in triage["pages"])
        for script, extra in (
            (
                "extract-text/scripts/extract_text.py",
                ["--body-size", str(triage["body_size"])],
            ),
            ("extract-images/scripts/extract_images.py", []),
        ):
            result = run_script(
                script, "--doc", doc, "--pages", pages, *extra, cwd=tmp_project
            )
            assert result.returncode == 0, result.stderr
        describe_all_images(doc, tmp_project)
        for script, extra in (
            ("assemble-output/scripts/merge.py", []),
            (
                "assemble-output/scripts/assemble.py",
                ["--format", "md-tree", "--split-depth", "2"],
            ),
        ):
            result = run_script(script, "--doc", doc, *extra, cwd=tmp_project)
            assert result.returncode == 0, result.stderr

        merged = json.loads(paths.elements_json(doc).read_text())
        headings = [
            el["text"]
            for page in merged["pages"]
            for el in page["elements"]
            if el["type"] == "heading"
        ]
        assert headings, "sanity: the fixture has headings"
        anchors = set()
        for md in paths.output_dir(doc).rglob("*.md"):
            anchors |= set(
                re.findall(r'<a id="([^"]+)"></a>', md.read_text(encoding="utf-8"))
            )
        missing = [h for h in headings if assemble.slugify_heading(h) not in anchors]
        assert missing == []
