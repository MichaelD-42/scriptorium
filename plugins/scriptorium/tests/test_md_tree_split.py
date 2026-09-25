"""Task A8 -- `--format md-tree --split-depth N`: split output into a
folder-per-level-1/file-per-level-2 bundle (for `--split-depth 2`, the only
depth this repo's tests exercise -- see task-A8-brief.md's "ALL your tests
target N=2").

Layout (see assemble.py's `write_md_tree`/SKILL.md's "md-tree format"
section for the full contract):
  - `index.md` -- links to every split file, in document order.
  - `00-front-matter.md` -- content before the first level-1 heading, only
    written if non-empty.
  - `NN-<slug>/NN.00-<slug>.md` -- a level-1 chapter's own body content
    before its first level-2 child (or ALL its content, if it has no level-2
    children at all) -- only written if non-empty.
  - `NN-<slug>/NN.MM-<slug>.md` -- one file per level-2 heading, always
    written (even with an empty body) since the heading itself IS the
    section.
  - Levels 3+ stay inline within their enclosing file, each preceded by a
    stable `<a id="...">` anchor (Task A8's cross-repo anchor contract,
    `slugify_heading` -- byte-for-byte match with a downstream consumer's own,
    independently-implemented `slugify_heading()`).

Judgment calls made in `write_md_tree`, documented again here for anyone
reading tests first:
  - The heading that OPENS a file/folder becomes that file's frontmatter
    `title`/`section`, not a duplicated body heading (same convention
    `split_sections_by_h1`/OKF already use).
  - A chapter with zero level-2 children: its content (if any) still lands
    in `NN.00-<slug>.md` -- no third naming scheme invented for that case.
  - A chapter with neither body content of its own nor level-2 children:
    no folder/file written at all, but its number+title still appears as a
    plain (non-linked) label in `index.md` so it isn't silently missing.
"""

import json
from pathlib import Path

import pytest
import yaml

import paths
from conftest import EXAMPLES_ROOT, describe_all_images, load_script, run_script

assemble = load_script("assemble-output/scripts/assemble.py", "assemble_module_a8")


def _run_ok(relpath: str, *args: str, cwd) -> str:
    result = run_script(relpath, *args, cwd=cwd)
    assert result.returncode == 0, (
        f"{relpath} {' '.join(args)} failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    return result.stdout


def _frontmatter(text: str) -> dict:
    assert text.startswith("---\n")
    end = text.index("\n---\n", 4)
    return yaml.safe_load(text[4:end])


# --------------------------------------------------------------------------
# The anchor contract -- exact cross-repo match with a downstream consumer's own
# `slugify_heading()` (plugins/rfq-intake/skills/rfq-object-ids/scripts/
# tag_objects.py in that repo). Same input/output pairs as that repo's own
# `test_locator_anchor_from_leading_heading_number` test, so a reader can
# cross-check the two directly.
# --------------------------------------------------------------------------

class TestSlugifyHeading:
    def test_leading_dotted_number_becomes_dashed_anchor(self):
        assert assemble.slugify_heading("2.3.1 Some Title") == "2-3-1"

    def test_no_leading_number_falls_back_to_full_text_slug(self):
        assert assemble.slugify_heading("Appendix A") == "appendix-a"

    def test_single_component_number(self):
        assert assemble.slugify_heading("3 Process Diagrams") == "3"

    def test_no_word_boundary_check_after_digits_matches_other_repo_exactly(self):
        # Documented, intentional: "3D Printing" anchors as "3", not
        # "3d-printing" -- the other repo's LEADING_NUMBER regex has no
        # boundary check after the digit groups, and this reproduces that
        # exactly rather than a stricter version of it.
        assert assemble.slugify_heading("3D Printing") == "3"

    def test_empty_or_punctuation_only_text_falls_back_to_section(self):
        assert assemble.slugify_heading("...") == "section"
        assert assemble.slugify_heading("") == "section"

    def test_non_alnum_runs_collapse_to_single_dash(self):
        assert assemble.slugify_heading("Foo & Bar / Baz!") == "foo-bar-baz"


class TestSplitSectionNumber:
    def test_number_and_title_split_on_first_space(self):
        assert assemble.split_section_number("1.2 Document Overview") == ("1.2", "Document Overview")

    def test_no_leading_number_returns_none_and_stripped_text(self):
        assert assemble.split_section_number("  Appendix A: Glossary  ") == (None, "Appendix A: Glossary")

    def test_requires_whitespace_after_number_unlike_the_anchor_rule(self):
        # "3D Printing" has no space after "3" -- NOT treated as a numbered
        # heading here (distinct from slugify_heading's looser anchor rule).
        assert assemble.split_section_number("3D Printing") == (None, "3D Printing")


# --------------------------------------------------------------------------
# build_md_tree_sections -- pure function, hand-built page/element lists.
# --------------------------------------------------------------------------

def _heading(level, text):
    return {"type": "heading", "level": level, "text": text}


def _para(text):
    return {"type": "paragraph", "text": text}


class TestBuildMdTreeSections:
    def test_content_before_first_heading_is_front_matter(self):
        pages = [{"page_number": 1, "elements": [_para("preamble")]}]
        front_matter, folders = assemble.build_md_tree_sections(pages, split_depth=2)
        assert front_matter["elements"] == [_para("preamble")]
        assert front_matter["source_pages"] == [1]
        assert folders == []

    def test_folder_per_level1_file_per_level2(self):
        pages = [{
            "page_number": 1,
            "elements": [
                _heading(1, "1 Chapter One"),
                _para("chapter one intro"),
                _heading(2, "1.1 Section One"),
                _para("section one body"),
                _heading(2, "1.2 Section Two"),
                _para("section two body"),
                _heading(1, "2 Chapter Two"),
                _heading(2, "2.1 Section"),
                _para("chapter two section body"),
            ],
        }]
        front_matter, folders = assemble.build_md_tree_sections(pages, split_depth=2)
        assert front_matter["elements"] == []
        assert len(folders) == 2

        ch1 = folders[0]
        assert (ch1["number"], ch1["title"], ch1["level"]) == ("1", "Chapter One", 1)
        assert ch1["pre"]["elements"] == [_para("chapter one intro")]
        assert [f["number"] for f in ch1["files"]] == ["1.1", "1.2"]
        assert ch1["files"][0]["elements"] == [_para("section one body")]
        assert ch1["files"][1]["elements"] == [_para("section two body")]

        ch2 = folders[1]
        assert (ch2["number"], ch2["title"]) == ("2", "Chapter Two")
        assert ch2["pre"]["elements"] == []  # no content between "2" and "2.1"
        assert [f["number"] for f in ch2["files"]] == ["2.1"]

    def test_heading_deeper_than_split_depth_stays_inline(self):
        pages = [{
            "page_number": 1,
            "elements": [
                _heading(1, "1 Chapter"),
                _heading(2, "1.1 Section"),
                _para("body"),
                _heading(3, "1.1.1 Subsection"),
                _para("deep body"),
                _heading(4, "1.1.1.1 Even deeper"),
                _para("deeper body"),
            ],
        }]
        _front_matter, folders = assemble.build_md_tree_sections(pages, split_depth=2)
        file_elements = folders[0]["files"][0]["elements"]
        assert file_elements == [
            _para("body"),
            _heading(3, "1.1.1 Subsection"),
            _para("deep body"),
            _heading(4, "1.1.1.1 Even deeper"),
            _para("deeper body"),
        ]

    def test_chapter_with_no_level2_children_keeps_all_content_in_pre(self):
        pages = [{
            "page_number": 1,
            "elements": [
                _heading(1, "9 Lone Chapter"),
                _para("only content, no subsections"),
            ],
        }]
        _front_matter, folders = assemble.build_md_tree_sections(pages, split_depth=2)
        assert len(folders) == 1
        assert folders[0]["files"] == []
        assert folders[0]["pre"]["elements"] == [_para("only content, no subsections")]

    def test_chapter_with_no_content_and_no_children_is_still_tracked(self):
        pages = [{"page_number": 1, "elements": [_heading(1, "5 Empty Chapter")]}]
        _front_matter, folders = assemble.build_md_tree_sections(pages, split_depth=2)
        assert len(folders) == 1
        assert folders[0]["pre"]["elements"] == []
        assert folders[0]["files"] == []

    def test_source_pages_track_every_contributing_page_in_order(self):
        pages = [
            {"page_number": 1, "elements": [_heading(1, "1 Chapter"), _heading(2, "1.1 Section"), _para("p1")]},
            {"page_number": 2, "elements": [_para("p2 continues on the next page")]},
        ]
        _front_matter, folders = assemble.build_md_tree_sections(pages, split_depth=2)
        assert folders[0]["files"][0]["source_pages"] == [1, 2]


# --------------------------------------------------------------------------
# write_md_tree -- filesystem writes, hand-built doc_data, no full pipeline.
# --------------------------------------------------------------------------

class TestWriteMdTreeAssetPaths:
    """Asset path correctness: a root-level file (00-front-matter.md) uses a
    bare `assets/...` reference; a nested `NN-slug/` file uses `../assets/
    ...`. Both are resolved from the file's own directory and checked
    against the asset's real on-disk location, not just string-compared."""

    def _doc_data(self):
        return {
            "doc": "d",
            "pages": {
                1: {
                    "page_number": 1,
                    "elements": [
                        {"type": "image", "asset": "assets/root.png"},
                        {"type": "heading", "level": 1, "text": "1 Chapter"},
                        {"type": "heading", "level": 2, "text": "1.1 Section"},
                        {"type": "image", "asset": "assets/nested.png"},
                    ],
                },
            },
        }

    def _write_assets(self, tmp_project, doc):
        assets_dir = paths.assets_dir(doc)
        assets_dir.mkdir(parents=True, exist_ok=True)
        (assets_dir / "root.png").write_bytes(b"root")
        (assets_dir / "nested.png").write_bytes(b"nested")

    def test_root_level_file_asset_path_resolves(self, tmp_project):
        doc = "d"
        self._write_assets(tmp_project, doc)
        written = assemble.write_md_tree(self._doc_data(), doc, split_depth=2)
        fm_path = next(p for p in written if p.name == "00-front-matter.md")
        md = fm_path.read_text()
        assert "![](assets/root.png)" in md
        resolved = (fm_path.parent / "assets/root.png").resolve()
        assert resolved.exists()
        assert resolved == (paths.assets_dir(doc)).resolve() / "root.png"

    def test_nested_file_asset_path_resolves(self, tmp_project):
        doc = "d"
        self._write_assets(tmp_project, doc)
        written = assemble.write_md_tree(self._doc_data(), doc, split_depth=2)
        file_path = next(p for p in written if p.name == "01.01-section.md")
        md = file_path.read_text()
        assert "![](../assets/nested.png)" in md
        resolved = (file_path.parent / "../assets/nested.png").resolve()
        assert resolved.exists()
        assert resolved == (paths.assets_dir(doc)).resolve() / "nested.png"


class TestWriteMdTreeFrontmatterAndAnchors:
    def _doc_data(self):
        return {
            "doc": "d",
            "pages": {
                1: {
                    "page_number": 1,
                    "elements": [
                        {"type": "heading", "level": 1, "text": "1 Chapter"},
                        {"type": "paragraph", "text": "pre content"},
                        {"type": "heading", "level": 2, "text": "1.1 Section"},
                        {"type": "paragraph", "text": "section body"},
                        {"type": "heading", "level": 3, "text": "1.1.1 Deep"},
                        {"type": "paragraph", "text": "deep body"},
                    ],
                },
            },
        }

    def test_pre_file_frontmatter(self, tmp_project):
        written = assemble.write_md_tree(self._doc_data(), "d", split_depth=2)
        pre_path = next(p for p in written if p.name == "01.00-chapter.md")
        fm = _frontmatter(pre_path.read_text())
        assert fm == {"doc": "d", "section": "1", "title": "Chapter", "level": 1, "source_pages": [1]}

    def test_file_frontmatter(self, tmp_project):
        written = assemble.write_md_tree(self._doc_data(), "d", split_depth=2)
        file_path = next(p for p in written if p.name == "01.01-section.md")
        fm = _frontmatter(file_path.read_text())
        assert fm == {"doc": "d", "section": "1.1", "title": "Section", "level": 2, "source_pages": [1]}

    def test_index_has_no_frontmatter(self, tmp_project):
        written = assemble.write_md_tree(self._doc_data(), "d", split_depth=2)
        index_path = next(p for p in written if p.name == "index.md")
        assert not index_path.read_text().startswith("---\n")

    def test_deep_heading_gets_anchor_and_stays_inline_in_the_level2_file(self, tmp_project):
        written = assemble.write_md_tree(self._doc_data(), "d", split_depth=2)
        file_path = next(p for p in written if p.name == "01.01-section.md")
        md = file_path.read_text()
        assert '<a id="1-1-1"></a>' in md
        assert "### 1.1.1 Deep" in md
        anchor_pos = md.index('<a id="1-1-1"></a>')
        heading_pos = md.index("### 1.1.1 Deep")
        assert anchor_pos < heading_pos

    def test_file_defining_heading_itself_is_not_duplicated_in_body(self, tmp_project):
        written = assemble.write_md_tree(self._doc_data(), "d", split_depth=2)
        file_path = next(p for p in written if p.name == "01.01-section.md")
        md = file_path.read_text()
        assert "## 1.1 Section" not in md  # consumed into frontmatter, not a body heading


class TestWriteMdTreeIndex:
    def test_index_links_every_split_file_in_document_order(self, tmp_project):
        doc_data = {
            "doc": "d",
            "pages": {
                1: {
                    "page_number": 1,
                    "elements": [
                        {"type": "paragraph", "text": "front"},
                        {"type": "heading", "level": 1, "text": "1 Chapter One"},
                        {"type": "paragraph", "text": "pre"},
                        {"type": "heading", "level": 2, "text": "1.1 Section"},
                        {"type": "paragraph", "text": "body"},
                    ],
                },
            },
        }
        written = assemble.write_md_tree(doc_data, "d", split_depth=2)
        index_path = next(p for p in written if p.name == "index.md")
        index_md = index_path.read_text()
        assert "[Front Matter](00-front-matter.md)" in index_md
        assert "[1 Chapter One](01-chapter-one/01.00-chapter-one.md)" in index_md
        assert "[1.1 Section](01-chapter-one/01.01-section.md)" in index_md

    def test_empty_chapter_gets_a_plain_label_not_a_dead_link(self, tmp_project):
        doc_data = {
            "doc": "d",
            "pages": {1: {"page_number": 1, "elements": [{"type": "heading", "level": 1, "text": "5 Empty"}]}},
        }
        written = assemble.write_md_tree(doc_data, "d", split_depth=2)
        index_path = next(p for p in written if p.name == "index.md")
        index_md = index_path.read_text()
        assert "5 Empty" in index_md
        assert "[5 Empty]" not in index_md
        # No folder/file was written for it.
        assert not any(p.parent.name.startswith("05-") for p in written)


# --------------------------------------------------------------------------
# Full pipeline against furniture_sample.pdf.
# --------------------------------------------------------------------------

class TestFurnitureSampleMdTree:
    @pytest.fixture
    def furniture_doc(self, tmp_project):
        import shutil

        dest = tmp_project / "input" / "furniture_sample.pdf"
        shutil.copyfile(EXAMPLES_ROOT / "furniture_sample.pdf", dest)
        return "furniture_sample"

    def _golden(self) -> dict:
        return json.loads((EXAMPLES_ROOT / "furniture_golden.json").read_text())

    def _extract(self, furniture_doc, tmp_project):
        """triage -> extract-text/-images -> merge, no assemble.py call --
        shared by every test below (both the successful md-tree build and
        the --split-depth rejection test need elements.json to exist first,
        so the failure they check for is genuinely the split-depth check,
        not a missing-elements.json error)."""
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
        _run_ok("assemble-output/scripts/merge.py", "--doc", furniture_doc, cwd=tmp_project)

    def _build(self, furniture_doc, tmp_project):
        self._extract(furniture_doc, tmp_project)
        _run_ok(
            "assemble-output/scripts/assemble.py", "--doc", furniture_doc,
            "--format", "md-tree", "--split-depth", "2", cwd=tmp_project,
        )

    def test_layout_matches_toc_exactly(self, furniture_doc, tmp_project):
        self._build(furniture_doc, tmp_project)
        out_dir = paths.output_dir(furniture_doc)

        # Real body headings in furniture_sample.pdf: 1, 1.1, 1.2, 2, 2.1,
        # 2.1.1, 2.1.2, 2.2, 3, 3.1, then the appendix chapters 4-11 (see
        # furniture_golden.json's "headings").
        # Every level-1 chapter has pre-content on this fixture (checked
        # against generate_furniture_fixture.py's actual draw order).
        expected_files = {
            "00-front-matter.md",
            "index.md",
            "01-introduction/01.00-introduction.md",
            "01-introduction/01.01-purpose-and-scope.md",
            "01-introduction/01.02-document-overview.md",
            "02-system-requirements/02.00-system-requirements.md",
            "02-system-requirements/02.01-functional-requirements.md",
            "02-system-requirements/02.02-non-functional-requirements.md",
            "03-process-diagrams/03.00-process-diagrams.md",
            "03-process-diagrams/03.01-workflow-overview.md",
            # Task A9: the appendix pages (10-11) print the TOC's
            # appendix-style entries as headings, one short body line each.
            "04-appendix-a-glossary/04.00-appendix-a-glossary.md",
            "04-appendix-a-glossary/04.01-terms-and-definitions.md",
            "04-appendix-a-glossary/04.02-abbreviations.md",
            "05-appendix-b-references/05.00-appendix-b-references.md",
            "05-appendix-b-references/05.01-normative-references.md",
            "05-appendix-b-references/05.02-informative-references.md",
            "06-appendix-c-revision-history/06.00-appendix-c-revision-history.md",
            "06-appendix-c-revision-history/06.01-change-log.md",
            "06-appendix-c-revision-history/06.02-approval-record.md",
            "07-appendix-d-index/07.00-appendix-d-index.md",
            "08-appendix-e-contact-information/08.00-appendix-e-contact-information.md",
            "08-appendix-e-contact-information/08.01-program-office.md",
            "08-appendix-e-contact-information/08.02-technical-support.md",
            "09-appendix-f-safety-notes/09.00-appendix-f-safety-notes.md",
            "09-appendix-f-safety-notes/09.01-handling-precautions.md",
            "09-appendix-f-safety-notes/09.02-compliance-statement.md",
            "10-appendix-g-standards-referenced/10.00-appendix-g-standards-referenced.md",
            "10-appendix-g-standards-referenced/10.01-industry-standards.md",
            "10-appendix-g-standards-referenced/10.02-internal-standards.md",
            "11-closing-notes/11.00-closing-notes.md",
        }
        actual_files = {
            str(p.relative_to(out_dir)).replace("\\", "/")
            for p in out_dir.rglob("*.md")
        }
        assert actual_files == expected_files

    def test_index_links_every_level1_and_level2_section(self, furniture_doc, tmp_project):
        self._build(furniture_doc, tmp_project)
        index_md = (paths.output_dir(furniture_doc) / "index.md").read_text()
        for number, title in [
            ("1", "Introduction"), ("1.1", "Purpose and Scope"), ("1.2", "Document Overview"),
            ("2", "System Requirements"), ("2.1", "Functional Requirements"),
            ("2.2", "Non-Functional Requirements"),
            ("3", "Process Diagrams"), ("3.1", "Workflow Overview"),
        ]:
            assert f"{number} {title}" in index_md

    def test_front_matter_present_and_correct(self, furniture_doc, tmp_project):
        self._build(furniture_doc, tmp_project)
        fm_path = paths.output_dir(furniture_doc) / "00-front-matter.md"
        assert fm_path.exists()
        text = fm_path.read_text()
        fm = _frontmatter(text)
        assert fm["doc"] == furniture_doc
        assert fm["title"] == "Front Matter"
        # Page 1 (cover) plus page 4: furniture_sample.pdf's page 4 also
        # places a unique (non-furniture) bitmap icon near the top-right,
        # above "1 Introduction" in y-position -- merge_shards' bbox-y0 sort
        # (Task A5) puts it before the heading in the element stream, so it
        # counts as "content before the first level-1 heading" too. TOC
        # pages 2-3 are skipped by extract-text and contribute nothing.
        assert fm["source_pages"] == [1, 4]
        assert "This synthetic document combines" in text  # COVER_PARA, verbatim
        assert "![](assets/page4_bitmap1.png)" in text  # root-level file -> bare "assets/" prefix, no "../"

    def test_every_split_file_has_correct_frontmatter(self, furniture_doc, tmp_project):
        self._build(furniture_doc, tmp_project)
        out_dir = paths.output_dir(furniture_doc)
        expected_sections = {
            "01-introduction/01.00-introduction.md": ("1", "Introduction", 1),
            "01-introduction/01.01-purpose-and-scope.md": ("1.1", "Purpose and Scope", 2),
            "01-introduction/01.02-document-overview.md": ("1.2", "Document Overview", 2),
            "02-system-requirements/02.00-system-requirements.md": ("2", "System Requirements", 1),
            "02-system-requirements/02.01-functional-requirements.md": ("2.1", "Functional Requirements", 2),
            "02-system-requirements/02.02-non-functional-requirements.md": ("2.2", "Non-Functional Requirements", 2),
            "03-process-diagrams/03.00-process-diagrams.md": ("3", "Process Diagrams", 1),
            "03-process-diagrams/03.01-workflow-overview.md": ("3.1", "Workflow Overview", 2),
        }
        for relpath, (section, title, level) in expected_sections.items():
            fm = _frontmatter((out_dir / relpath).read_text())
            assert fm["doc"] == furniture_doc
            assert fm["section"] == section
            assert fm["title"] == title
            assert fm["level"] == level
            assert isinstance(fm["source_pages"], list) and fm["source_pages"]

    def test_deeper_headings_have_correctly_derived_anchors(self, furniture_doc, tmp_project):
        self._build(furniture_doc, tmp_project)
        md = (paths.output_dir(furniture_doc) / "02-system-requirements/02.01-functional-requirements.md").read_text()
        # "2.1.1 Data Processing Pipeline" and "2.1.2 Edge Case Handling"
        # both stay inline in the "2.1" file (split_depth=2). Both are level
        # 3 in the REAL extracted elements, not furniture_golden.json's
        # hand-authored "headings" list's level 4 for "2.1.2" -- Task A4's
        # already-documented divergence (toc.json's level is computed by
        # dot-depth, "2.1.2" has 2 dots -> level 3; golden.json's intent was
        # "printed at the smallest bold size" -- see task-A4-report.md).
        # Confirmed directly against the real elements.json in this test run.
        assert '<a id="2-1-1"></a>' in md
        assert "### 2.1.1 Data Processing Pipeline" in md
        assert '<a id="2-1-2"></a>' in md
        assert "### 2.1.2 Edge Case Handling" in md

    def test_figures_render_identically_inside_split_files(self, furniture_doc, tmp_project):
        # Spot check, not a re-test of A7's own coverage: the same
        # render_image_markdown call this format reuses, with the figure's
        # caption rendered verbatim and the asset path correctly ../-prefixed
        # since both figures land inside an NN-slug/ folder for this fixture.
        self._build(furniture_doc, tmp_project)
        golden = self._golden()
        diagram_caption = next(f["caption"] for f in golden["figures"] if f["kind"] == "diagram")
        chart_caption = next(f["caption"] for f in golden["figures"] if f["kind"] == "chart")

        diagram_md = (paths.output_dir(furniture_doc) / "02-system-requirements/02.02-non-functional-requirements.md").read_text()
        assert diagram_caption in diagram_md
        assert "![" in diagram_md and "](../assets/" in diagram_md

        chart_md = (paths.output_dir(furniture_doc) / "03-process-diagrams/03.00-process-diagrams.md").read_text()
        assert chart_caption in chart_md
        assert "![" in chart_md and "](../assets/" in chart_md

        # And the asset path genuinely resolves on disk from the file's own
        # directory, not just string-matches.
        asset_ref = diagram_md[diagram_md.index("](../assets/") + 2: diagram_md.index(")", diagram_md.index("](../assets/"))]
        resolved = (paths.output_dir(furniture_doc) / "02-system-requirements" / asset_ref).resolve()
        assert resolved.exists()

    def test_regular_md_html_okf_reqif_formats_unaffected(self, furniture_doc, tmp_project):
        """Full regression check that adding md-tree didn't disturb the
        other formats' behavior for the same document."""
        self._extract(furniture_doc, tmp_project)
        # Task A9: the extractor agent's describe step, then re-merge, so
        # gates.py's figures_complete check sees the descriptions.
        describe_all_images(furniture_doc, tmp_project)
        _run_ok("assemble-output/scripts/merge.py", "--doc", furniture_doc, cwd=tmp_project)

        for fmt in ("md", "html", "okf", "reqif"):
            out = _run_ok("assemble-output/scripts/assemble.py", "--doc", furniture_doc, "--format", fmt, cwd=tmp_project)
            for line in out.strip().splitlines():
                assert Path(line).exists()

        gates_out = _run_ok("grade-output/scripts/gates.py", "--doc", furniture_doc, "--format", "md", cwd=tmp_project)
        assert json.loads(gates_out)["passed"] is True

    # --------------------------------------------------------------------
    # Fix round 1 findings.
    # --------------------------------------------------------------------

    def test_output_bytes_contain_no_crlf(self, furniture_doc, tmp_project):
        # write_text() on Windows defaults to translating "\n" -> os.linesep
        # (CRLF) unless newline="" is passed. The other repo's object
        # tagger reads md-tree files as raw bytes and substring-matches an
        # LF-joined block_md against them, so any CRLF here silently breaks
        # every multi-line match on Windows. Checked against real pipeline
        # output (raw bytes, not `.read_text()`, which would normalize line
        # endings back and hide the bug), across every md-tree file plus
        # the single-file md format, since both share the same write_text()
        # call sites in assemble.py.
        self._build(furniture_doc, tmp_project)
        out_dir = paths.output_dir(furniture_doc)
        md_tree_files = list(out_dir.rglob("*.md"))
        assert md_tree_files  # sanity: the glob actually found files
        for md_path in md_tree_files:
            assert b"\r" not in md_path.read_bytes(), f"{md_path} contains a CR byte"

        _run_ok("assemble-output/scripts/assemble.py", "--doc", furniture_doc, "--format", "md", cwd=tmp_project)
        md_single = paths.output_file(furniture_doc, "md")
        assert b"\r" not in md_single.read_bytes()

    def test_split_depth_other_than_2_is_rejected(self, furniture_doc, tmp_project):
        # build_md_tree_sections only implements true nested-folder
        # splitting for split_depth == 2 -- any other value silently
        # produces wrong output (colliding folder numbers across unrelated
        # chapters) rather than crashing, so it must be rejected at the CLI
        # instead. Confirmed against the real CLI subprocess, not just a
        # direct function call, so this covers argparse wiring too.
        self._extract(furniture_doc, tmp_project)
        result = run_script(
            "assemble-output/scripts/assemble.py", "--doc", furniture_doc,
            "--format", "md-tree", "--split-depth", "3", cwd=tmp_project,
        )
        assert result.returncode != 0
        assert "split-depth" in result.stderr.lower()
        assert "2" in result.stderr
        assert not (paths.output_dir(furniture_doc) / "index.md").exists()
