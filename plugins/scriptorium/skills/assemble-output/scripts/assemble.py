#!/usr/bin/env python3
"""Assemble elements.json into the final Markdown, HTML, or OKF document.
See SKILL.md."""

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import elements as elements_lib  # noqa: E402
import paths  # noqa: E402

import reqif_builder  # noqa: E402

import yaml
from jinja2 import Environment, FileSystemLoader

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"


def render_markdown_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]

    def escape(cell: str) -> str:
        return str(cell).replace("|", "\\|").replace("\n", " ")

    header = "| " + " | ".join(escape(c) for c in rows[0]) + " |"
    sep = "| " + " | ".join("---" for _ in range(width)) + " |"
    body = ["| " + " | ".join(escape(c) for c in r) + " |" for r in rows[1:]]
    return "\n".join([header, sep, *body])


INTERPRETATION_START = "<!-- scriptorium:interpretation -->"
INTERPRETATION_END = "<!-- /scriptorium:interpretation -->"


def render_image_markdown(el: dict, asset_prefix: str = "") -> list[str]:
    """Render one `image` element as a list of Markdown lines/blocks, in
    order:

    1. The image itself, `![alt](asset)` -- alt prefers `description` (the
       richest available text), falling back to `caption`, then empty.
       `asset_prefix` is prepended to `el['asset']` verbatim -- empty for
       single-file md/okf output (asset paths are already root-relative,
       `assets/...`), `"../"` when this is called from a file one directory
       below the output root (Task A8's md-tree format).
    2. `caption`, if present -- plain text, script-authoritative, verbatim.
       NOT wrapped in interpretation markers: it's deterministic matched
       text, not agent interpretation.
    3. `figure_text`, if present -- rendered as a Markdown blockquote (this
       codebase has no other precedent for "verbatim quoted content" in
       Markdown output, so blockquote was chosen for readability over a
       fenced code block). Also NOT wrapped in markers -- same trust tier
       as `caption`, verbatim extracted text.
    4. `description`/`data_table`/`mermaid`, if any are present, wrapped in
       an `INTERPRETATION_START`/`INTERPRETATION_END` HTML-comment pair --
       these are the fields an agent judged/authored, not extracted
       verbatim, so a downstream mechanical validator can grep the markers
       to exclude this span from a "verbatim" check. No markers at all if
       none of the three are present (never an empty pair).
    """
    lines = []

    alt = el.get("description") or el.get("caption") or ""
    lines.append(f"![{alt}]({asset_prefix}{el['asset']})")

    caption = el.get("caption") or ""
    if caption:
        lines.append(caption)

    figure_text = el.get("figure_text") or ""
    if figure_text:
        lines.append("\n".join(f"> {line}" for line in figure_text.splitlines()))

    interpretation_parts = []
    description = el.get("description") or ""
    if description:
        interpretation_parts.append(description)
    data_table = el.get("data_table")
    if data_table:
        interpretation_parts.append(render_markdown_table(data_table))
    mermaid = el.get("mermaid") or ""
    if mermaid:
        interpretation_parts.append(f"```mermaid\n{mermaid}\n```")

    if interpretation_parts:
        lines.append(INTERPRETATION_START)
        lines.append("\n\n".join(interpretation_parts))
        lines.append(INTERPRETATION_END)

    return lines


def elements_to_markdown(elements: list[dict], asset_prefix: str = "") -> str:
    lines = []
    for el in elements:
        if el["type"] == "heading":
            lines.append(f"{'#' * el['level']} {el['text']}")
        elif el["type"] == "paragraph":
            lines.append(el["text"])
        elif el["type"] == "table":
            lines.append(render_markdown_table(el["rows"]))
        elif el["type"] == "image":
            lines.extend(render_image_markdown(el, asset_prefix=asset_prefix))
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def sorted_pages(doc_data: dict) -> list[dict]:
    return sorted(doc_data["pages"].values(), key=lambda p: p["page_number"])


def to_markdown(doc_data: dict) -> str:
    all_elements = [el for page in sorted_pages(doc_data) for el in page["elements"]]
    return elements_to_markdown(all_elements)


def to_html(doc_data: dict) -> str:
    pages = sorted_pages(doc_data)
    has_mermaid = any(
        el["type"] == "image" and el.get("mermaid")
        for page in pages
        for el in page["elements"]
    )
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
    template = env.get_template("output.html.j2")
    return template.render(doc=doc_data["doc"], pages=pages, has_mermaid=has_mermaid)


# --- OKF (https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) ---

def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "section"


def split_sections_by_h1(pages: list[dict]) -> list[dict]:
    """Flatten every page's elements into one stream, split into sections at
    each H1. Content before the first H1 (if any) becomes a "Front Matter"
    section. The H1 element itself becomes the section's title (frontmatter),
    not a body element — deeper headings (H2/H3) stay inside the section."""
    preamble = {"title": None, "elements": [], "source_pages": []}
    sections = [preamble]
    current = preamble
    for page in pages:
        for el in page["elements"]:
            if el["type"] == "heading" and el.get("level") == 1:
                current = {"title": el["text"], "elements": [], "source_pages": []}
                sections.append(current)
                continue
            current["elements"].append(el)
            if page["page_number"] not in current["source_pages"]:
                current["source_pages"].append(page["page_number"])

    if sections[0]["title"] is None:
        if sections[0]["elements"]:
            sections[0]["title"] = "Front Matter"
        else:
            sections.pop(0)
    return sections


def first_sentence(elements: list[dict], max_len: int = 160) -> str:
    for el in elements:
        if el["type"] != "paragraph" or not el["text"].strip():
            continue
        text = el["text"].strip()
        match = re.search(r"[.!?](\s|$)", text)
        if match:
            return text[: match.end()].strip()
        if len(text) <= max_len:
            return text
        return text[:max_len].rsplit(" ", 1)[0] + "…"  # word-boundary truncation, not mid-word
    return ""


def render_frontmatter(fields: dict) -> str:
    return "---\n" + yaml.safe_dump(fields, sort_keys=False, allow_unicode=True) + "---\n"


def write_okf(doc_data: dict, doc: str) -> list[Path]:
    sections = split_sections_by_h1(sorted_pages(doc_data))
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    resource = doc_data.get("source_file") or ""

    prepared = []
    for i, section in enumerate(sections):
        title = section["title"] or doc
        prepared.append({
            "path": paths.okf_section(doc, i, slugify(title)),
            "title": title,
            "description": first_sentence(section["elements"]),
            "source_pages": section["source_pages"],
            "body": elements_to_markdown(section["elements"]),
        })

    written = []
    for i, sec in enumerate(prepared):
        frontmatter = render_frontmatter({
            "type": "Document Section",
            "title": sec["title"],
            "description": sec["description"],
            "timestamp": timestamp,
            "resource": resource,
            "source_pages": sec["source_pages"],
        })
        nav = []
        if i > 0:
            nav.append(f"[← {prepared[i - 1]['title']}](/{prepared[i - 1]['path'].name})")
        if i < len(prepared) - 1:
            nav.append(f"[{prepared[i + 1]['title']} →](/{prepared[i + 1]['path'].name})")
        nav_block = f"\n---\n\n{' | '.join(nav)}\n" if nav else ""

        sec["path"].parent.mkdir(parents=True, exist_ok=True)
        sec["path"].write_text(f"{frontmatter}\n{sec['body']}{nav_block}", encoding="utf-8", newline="")
        written.append(sec["path"])

    toc_lines = [f"# {doc}", ""]
    for sec in prepared:
        suffix = f" - {sec['description']}" if sec["description"] else ""
        toc_lines.append(f"* [{sec['title']}](/{sec['path'].name}){suffix}")

    index_path = paths.okf_index(doc)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text('---\nokf_version: "0.1"\n---\n\n' + "\n".join(toc_lines) + "\n", encoding="utf-8", newline="")
    written.append(index_path)
    return written


# --- md-tree (Task A8) -------------------------------------------------

# The anchor contract: EXACT cross-repo match with a downstream consumer's own,
# independently-implemented `slugify_heading()`
# (plugins/rfq-intake/skills/rfq-object-ids/scripts/tag_objects.py in that
# repo -- no shared code between the two repos, reproduced here byte-for-byte
# per Task A8's brief). See SKILL.md's "md-tree format" section for the
# documented contract; the downstream step (a later, separate step) directly compares
# this repo's anchors against that repo's `object_anchor`/`locator.anchor`
# output, so any drift here breaks that cross-reference.
LEADING_NUMBER_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)")


def slugify_heading(text: str) -> str:
    """Stable per-heading anchor slug (Task A8's cross-repo contract -- see
    the module comment above `LEADING_NUMBER_RE`).

    Preferred source: the heading's own leading number (e.g. "2.3.1 Some
    Title" -> "2-3-1"), matched from the very start of the text (only
    leading whitespace is skipped -- note this means a heading like "3D
    Printing" anchors as "3", not "3d-printing": the other repo's regex has
    no word-boundary check after the digit groups, and this reproduces that
    exactly, not a stricter version of it -- verified against that repo's
    own `LEADING_NUMBER = re.compile(r"^\\s*(\\d+(?:\\.\\d+)*)")`). No
    leading number -> slugify the full text: lowercase, every run of
    non-alphanumeric characters replaced with a single "-", leading/
    trailing "-" stripped, "section" if empty."""
    match = LEADING_NUMBER_RE.match(text)
    if match:
        return match.group(1).replace(".", "-")
    slug = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return slug or "section"


# A leading section number followed by whitespace and the rest of the title,
# e.g. "1.2 Document Overview" -> ("1.2", "Document Overview"). Distinct from
# LEADING_NUMBER_RE above: this one REQUIRES whitespace after the number
# group (so "3D Printing" is never misparsed as number "3", title "D
# Printing"), because this is used for md-tree's own NN/MM folder/file
# naming, not the anchor contract -- the two are deliberately different
# rules for different purposes, not the same regex reused twice. Same shape
# as lib/toc.py's own NUMBER_PREFIX_RE, kept here as an independent copy
# rather than importing that module's private helper.
_SECTION_NUMBER_RE = re.compile(r"^(\d+(?:\.\d+)*)\s+(.+)$")


def split_section_number(text: str) -> tuple[str | None, str]:
    """`("1.2", "Document Overview")` for "1.2 Document Overview"; `(None,
    text)` (stripped) when there's no leading "<number> " prefix."""
    match = _SECTION_NUMBER_RE.match(text.strip())
    if match:
        return match.group(1), match.group(2).strip()
    return None, text.strip()


def _zero_pad_component(number: str | None, fallback_index: int) -> str:
    """The 2-digit `NN`/`MM` naming component for one heading's OWN digit
    group (the last dot-separated component of its full number, e.g. "3"
    from "2.3" -- level-1 numbers have no dots, so this is just the whole
    number for those). Falls back to a 1-based sequential index, zero-padded
    the same way, when the heading had no parseable leading number at all --
    an untested edge case in this repo (every heading in furniture_sample.pdf
    is numbered), kept simple so a numberless heading degrades gracefully
    instead of crashing."""
    if number is not None:
        own = number.split(".")[-1]
        try:
            return f"{int(own):02d}"
        except ValueError:
            pass
    return f"{fallback_index:02d}"


def build_md_tree_sections(pages: list[dict], split_depth: int) -> tuple[dict, list[dict]]:
    """Walk every page's elements in document order and bucket them for
    md-tree splitting:

    - `front_matter`: `{"elements": [...], "source_pages": [...]}` -- content
      before the first heading at level < split_depth.
    - `folders`: an ordered list of
      `{"number", "title", "level", "pre": {"elements", "source_pages"},
        "files": [{"number", "title", "level", "elements", "source_pages"}]}`.
      A heading at level < split_depth opens a new folder. A heading at
      level == split_depth opens a new file inside the current folder. A
      heading at level > split_depth (or any non-heading element) is simply
      appended to whichever bucket is currently innermost-open (the active
      file, else the active folder's "pre" bucket, else front matter) --
      that's what keeps deeper headings "inline" rather than splitting
      further, and what makes deeper folder nesting for split_depth > 2 a
      documented gap: every level < split_depth heading collapses onto ONE
      "current folder" here rather than a real nested stack, which is only
      correct for split_depth == 2 (the only depth this repo's tests
      exercise -- see the brief's own "ALL your tests target N=2").

    The heading element that OPENS a folder/file is never itself appended as
    body content -- it becomes that section's frontmatter `title`/`section`
    instead (same convention `split_sections_by_h1`/OKF already uses)."""
    front_matter = {"elements": [], "source_pages": []}
    folders: list[dict] = []
    active_folder = None
    active_file = None

    def track_page(bucket: dict, page_number: int) -> None:
        if page_number not in bucket["source_pages"]:
            bucket["source_pages"].append(page_number)

    for page in pages:
        page_number = page["page_number"]
        for el in page["elements"]:
            level = el.get("level") if el["type"] == "heading" else None

            if level is not None and level < split_depth:
                number, title = split_section_number(el["text"])
                active_folder = {
                    "number": number,
                    "title": title,
                    "level": level,
                    "pre": {"elements": [], "source_pages": [page_number]},
                    "files": [],
                }
                folders.append(active_folder)
                active_file = None
                continue

            if level is not None and level == split_depth:
                number, title = split_section_number(el["text"])
                new_file = {
                    "number": number,
                    "title": title,
                    "level": level,
                    "elements": [],
                    "source_pages": [page_number],
                }
                if active_folder is None:
                    # A level==split_depth heading with no enclosing
                    # shallower heading yet -- not exercised by
                    # furniture_sample.pdf (every level-2 heading there
                    # follows a level-1 heading first). Synthesize an
                    # unlabeled folder so the file still lands somewhere
                    # instead of crashing; documented, untested edge case.
                    active_folder = {
                        "number": None,
                        "title": None,
                        "level": split_depth - 1,
                        "pre": {"elements": [], "source_pages": []},
                        "files": [],
                    }
                    folders.append(active_folder)
                active_folder["files"].append(new_file)
                active_file = new_file
                continue

            if active_file is not None:
                target = active_file
            elif active_folder is not None:
                target = active_folder["pre"]
            else:
                target = front_matter
            target["elements"].append(el)
            track_page(target, page_number)

    return front_matter, folders


def elements_to_markdown_with_anchors(elements: list[dict], asset_prefix: str = "") -> str:
    """md-tree's own per-file element renderer. Calls the exact same
    `render_markdown_table`/`render_image_markdown` functions
    `elements_to_markdown` uses for table/image elements -- not a second
    rendering path for those -- but additionally emits a stable
    `<a id="...">` anchor immediately before every heading line (Task A8's
    anchor contract, `slugify_heading`). `elements_to_markdown` itself is
    left untouched so the single-file md/OKF formats' existing heading
    rendering (and their tests, e.g. `test_heading_levels_map_to_hashes`'s
    `md.startswith("## Title")`) are unaffected -- anchors are new behavior
    scoped to md-tree only."""
    lines = []
    for el in elements:
        if el["type"] == "heading":
            anchor = slugify_heading(el["text"])
            lines.append(f'<a id="{anchor}"></a>')
            lines.append("")
            lines.append(f"{'#' * el['level']} {el['text']}")
        elif el["type"] == "paragraph":
            lines.append(el["text"])
        elif el["type"] == "table":
            lines.append(render_markdown_table(el["rows"]))
        elif el["type"] == "image":
            lines.extend(render_image_markdown(el, asset_prefix=asset_prefix))
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def write_md_tree(doc_data: dict, doc: str, split_depth: int) -> list[Path]:
    """`--format md-tree --split-depth N`: folder-per-level-`<N` heading,
    file-per-level-`N` heading, deeper headings stay inline. See SKILL.md's
    "md-tree format" section for the full layout/frontmatter/anchor
    contract."""
    pages = sorted_pages(doc_data)
    front_matter, folders = build_md_tree_sections(pages, split_depth)

    out_dir = paths.output_dir(doc)
    out_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    index_lines = [f"# {doc}", ""]

    if front_matter["elements"]:
        fm_path = out_dir / "00-front-matter.md"
        frontmatter = render_frontmatter({
            "doc": doc,
            "section": None,
            "title": "Front Matter",
            "level": None,
            "source_pages": front_matter["source_pages"],
        })
        body = elements_to_markdown_with_anchors(front_matter["elements"])
        fm_path.write_text(f"{frontmatter}\n{body}", encoding="utf-8", newline="")
        written.append(fm_path)
        index_lines.append(f"* [Front Matter]({fm_path.name})")

    for folder_idx, folder in enumerate(folders, start=1):
        nn = _zero_pad_component(folder["number"], folder_idx)
        folder_slug = slugify(folder["title"] or "section")
        folder_dirname = f"{nn}-{folder_slug}"
        folder_dir = out_dir / folder_dirname
        folder_label = f"{folder['number']} {folder['title']}".strip() if folder["number"] else (folder["title"] or nn)

        pre = folder["pre"]
        has_pre = bool(pre["elements"])
        has_files = bool(folder["files"])
        if not has_pre and not has_files:
            # A heading with neither body content of its own nor any
            # level-2 children -- still surfaced in the index (so the
            # section isn't silently missing) but no folder/file is written
            # for it at all, consistent with "don't write an empty file".
            index_lines.append(f"* {folder_label}")
            continue

        folder_dir.mkdir(parents=True, exist_ok=True)

        if has_pre:
            # Also covers "a chapter with NO level-2 subsections": all of
            # its content (there being no children to separate it from)
            # lands here too, in the same NN.00-<slug>.md file, rather than
            # inventing a third naming scheme for that case.
            pre_path = folder_dir / f"{nn}.00-{folder_slug}.md"
            frontmatter = render_frontmatter({
                "doc": doc,
                "section": folder["number"],
                "title": folder["title"],
                "level": folder["level"],
                "source_pages": pre["source_pages"],
            })
            body = elements_to_markdown_with_anchors(pre["elements"], asset_prefix="../")
            pre_path.write_text(f"{frontmatter}\n{body}", encoding="utf-8", newline="")
            written.append(pre_path)
            index_lines.append(f"* [{folder_label}]({folder_dirname}/{pre_path.name})")
        else:
            index_lines.append(f"* {folder_label}")

        for file_idx, file in enumerate(folder["files"], start=1):
            mm = _zero_pad_component(file["number"], file_idx)
            file_slug = slugify(file["title"] or "section")
            file_path = folder_dir / f"{nn}.{mm}-{file_slug}.md"
            frontmatter = render_frontmatter({
                "doc": doc,
                "section": file["number"],
                "title": file["title"],
                "level": file["level"],
                "source_pages": file["source_pages"],
            })
            body = elements_to_markdown_with_anchors(file["elements"], asset_prefix="../")
            file_path.write_text(f"{frontmatter}\n{body}", encoding="utf-8", newline="")
            written.append(file_path)
            file_label = f"{file['number']} {file['title']}".strip() if file["number"] else (file["title"] or mm)
            index_lines.append(f"  * [{file_label}]({folder_dirname}/{file_path.name})")

    index_path = out_dir / "index.md"
    index_path.write_text("\n".join(index_lines) + "\n", encoding="utf-8", newline="")
    written.append(index_path)
    return written


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", required=True)
    parser.add_argument("--format", choices=["md", "html", "okf", "md-tree", "reqif", "reqifz"], default="md")
    parser.add_argument(
        "--split-depth", type=int, default=2,
        help="md-tree only: heading level at which a new FILE starts (levels shallower become folders, deeper stay inline).",
    )
    args = parser.parse_args()

    elements_path = paths.elements_json(args.doc)
    if not elements_path.exists():
        print(f"error: {elements_path} not found — run merge.py first", file=sys.stderr)
        sys.exit(1)

    doc_data = elements_lib.load_doc(elements_path)

    if args.format == "okf":
        for path in write_okf(doc_data, args.doc):
            print(path)
        return

    if args.format == "md-tree":
        if args.split_depth != 2:
            # build_md_tree_sections only implements true folder splitting
            # for split_depth == 2 (folder-per-level-1/file-per-level-2) --
            # any level < split_depth collapses onto ONE flattened "current
            # folder" instead of a real nested stack, which silently
            # produces wrong output (colliding folder numbers across
            # unrelated chapters) for split_depth != 2. Rejected at the CLI
            # rather than left to produce wrong-but-exit-0 output, until
            # nested-folder generalization is implemented -- see
            # build_md_tree_sections' docstring and SKILL.md.
            print(
                f"error: --split-depth {args.split_depth} is not supported yet -- "
                "only --split-depth 2 (folder-per-level-1/file-per-level-2) is implemented",
                file=sys.stderr,
            )
            sys.exit(1)
        for path in write_md_tree(doc_data, args.doc, args.split_depth):
            print(path)
        return

    if args.format in ("reqif", "reqifz"):
        reqif_xml = reqif_builder.build_reqif_xml(args.doc, doc_data)
        reqif_path = paths.output_file(args.doc, "reqif")
        reqif_path.parent.mkdir(parents=True, exist_ok=True)
        reqif_path.write_text(reqif_xml, encoding="utf-8", newline="")
        print(str(reqif_path))
        if args.format == "reqifz":
            print(str(reqif_builder.write_reqifz(args.doc, doc_data, reqif_xml)))
        return

    content = to_markdown(doc_data) if args.format == "md" else to_html(doc_data)
    out_path = paths.output_file(args.doc, args.format)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8", newline="")
    print(str(out_path))


if __name__ == "__main__":
    main()
