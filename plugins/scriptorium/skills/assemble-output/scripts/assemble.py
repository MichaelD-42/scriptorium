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


def elements_to_markdown(elements: list[dict]) -> str:
    lines = []
    for el in elements:
        if el["type"] == "heading":
            lines.append(f"{'#' * el['level']} {el['text']}")
        elif el["type"] == "paragraph":
            lines.append(el["text"])
        elif el["type"] == "table":
            lines.append(render_markdown_table(el["rows"]))
        elif el["type"] == "image":
            if el.get("mermaid"):
                lines.append(f"```mermaid\n{el['mermaid']}\n```")
                lines.append("")
            caption = el.get("caption") or ""
            lines.append(f"![{caption}]({el['asset']})")
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
        sec["path"].write_text(f"{frontmatter}\n{sec['body']}{nav_block}")
        written.append(sec["path"])

    toc_lines = [f"# {doc}", ""]
    for sec in prepared:
        suffix = f" - {sec['description']}" if sec["description"] else ""
        toc_lines.append(f"* [{sec['title']}](/{sec['path'].name}){suffix}")

    index_path = paths.okf_index(doc)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text('---\nokf_version: "0.1"\n---\n\n' + "\n".join(toc_lines) + "\n")
    written.append(index_path)
    return written


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", required=True)
    parser.add_argument("--format", choices=["md", "html", "okf", "reqif", "reqifz"], default="md")
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

    if args.format in ("reqif", "reqifz"):
        reqif_xml = reqif_builder.build_reqif_xml(args.doc, doc_data)
        reqif_path = paths.output_file(args.doc, "reqif")
        reqif_path.parent.mkdir(parents=True, exist_ok=True)
        reqif_path.write_text(reqif_xml)
        print(str(reqif_path))
        if args.format == "reqifz":
            print(str(reqif_builder.write_reqifz(args.doc, doc_data, reqif_xml)))
        return

    content = to_markdown(doc_data) if args.format == "md" else to_html(doc_data)
    out_path = paths.output_file(args.doc, args.format)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content)
    print(str(out_path))


if __name__ == "__main__":
    main()
