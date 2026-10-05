#!/usr/bin/env python3
"""Combine every page's shards (work/<doc>/shards/*.json) into the merged
work/<doc>/elements.json that assemble.py and gates.py read. See SKILL.md.

Deterministic, no judgment involved — this is a script, not an agent step.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import elements as elements_lib  # noqa: E402
import furniture as furniture_lib  # noqa: E402
import paths  # noqa: E402


def load_furniture_text(doc: str) -> str | None:
    """triage.json["furniture_text"] (pdf-triage's verbatim furniture lines,
    Task A1), or None if triage hasn't run for this document or its
    triage.json predates furniture detection (docx/xlsx/html/image triage
    never write this field at all)."""
    triage_path = paths.triage_json(doc)
    if not triage_path.exists():
        return None
    triage = json.loads(triage_path.read_text(encoding="utf-8"))
    return triage.get("furniture_text")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", required=True)
    args = parser.parse_args()

    input_path = paths.input_file(args.doc)
    if input_path is None:
        print(f"error: no input file found for doc '{args.doc}' in input/", file=sys.stderr)
        sys.exit(1)
    input_format = paths.detect_input_format(args.doc)
    page_count = paths.true_page_count(args.doc, input_format)

    # Fix wave I5: ocr/vision bodies lose their furniture lines here, with
    # the same band plus pattern rule gates.py checks (lib/furniture.py).
    furniture = furniture_lib.load_furniture(args.doc)
    page_sizes = (
        furniture_lib.pdf_page_sizes(input_path)
        if input_format == "pdf" and furniture.get("line_patterns")
        else {}
    )
    pages = elements_lib.merge_shards(
        paths.shards_dir(args.doc), page_count, furniture=furniture,
        page_heights={n: s[1] for n, s in page_sizes.items()},
        page_widths={n: s[0] for n, s in page_sizes.items()},
    )
    removed = sum(p.get("furniture_lines_removed", 0) for p in pages.values())
    if removed:
        print(f"furniture lines removed from ocr/vision bodies: {removed}", file=sys.stderr)
    doc_data = {
        "doc": args.doc,
        "source_file": str(input_path),
        "page_count": page_count,
        "furniture_text": load_furniture_text(args.doc),
        "pages": pages,
    }

    elements_path = paths.elements_json(args.doc)
    elements_lib.save_doc(elements_path, doc_data)
    print(str(elements_path))


if __name__ == "__main__":
    main()
