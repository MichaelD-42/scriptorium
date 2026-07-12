#!/usr/bin/env python3
"""Combine every page's shards (work/<doc>/shards/*.json) into the merged
work/<doc>/elements.json that assemble.py and gates.py read. See SKILL.md.

Deterministic, no judgment involved — this is a script, not an agent step.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import elements as elements_lib  # noqa: E402
import paths  # noqa: E402


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

    pages = elements_lib.merge_shards(paths.shards_dir(args.doc), page_count)
    doc_data = {"doc": args.doc, "source_file": str(input_path), "page_count": page_count, "pages": pages}

    elements_path = paths.elements_json(args.doc)
    elements_lib.save_doc(elements_path, doc_data)
    print(str(elements_path))


if __name__ == "__main__":
    main()
