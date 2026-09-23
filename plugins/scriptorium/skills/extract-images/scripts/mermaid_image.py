#!/usr/bin/env python3
"""Set the mermaid representation on a previously-extracted image element.

A script can't judge what a diagram shows any more than it can write a
caption — the calling agent (the `extractor` role) looks at the saved PNG,
decides the diagram's structure is faithfully reconstructible, and lands its
mermaid source here, mutating that page's image shard. Mirrors
caption_image.py, but reads the (possibly multi-line) mermaid source from
stdin instead of an argv string, the same way write_vision_page.py reads
vision-tier elements from stdin.

    echo 'flowchart TD
      A --> B' | uv run ... mermaid_image.py --doc sample --page 2 \
        --asset assets/page2_vector1.png
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import elements as elements_lib  # noqa: E402
import paths  # noqa: E402

# Recognized mermaid diagram keywords (https://mermaid.js.org/intro/) — the
# first non-comment, non-config line must start with one of these, so an
# agent mistake (plain prose, a different diagram language) is caught here
# rather than landed silently.
DIAGRAM_KEYWORDS = (
    "flowchart", "graph", "sequenceDiagram", "classDiagram", "stateDiagram-v2",
    "stateDiagram", "erDiagram", "journey", "gantt", "pie", "mindmap",
    "timeline", "gitGraph", "quadrantChart", "requirementDiagram",
    "sankey-beta", "xychart-beta", "block-beta", "C4Context",
)


def first_diagram_line(mermaid: str) -> str | None:
    """Skip blank lines, `%%` comments, and a leading `---`...`---` YAML
    front-matter block, then return the first remaining non-blank line."""
    lines = mermaid.splitlines()
    i = 0
    if i < len(lines) and lines[i].strip() == "---":
        i += 1
        while i < len(lines) and lines[i].strip() != "---":
            i += 1
        i += 1  # skip the closing ---
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped and not stripped.startswith("%%"):
            return stripped
        i += 1
    return None


def validate_diagram_source(mermaid: str) -> str | None:
    """None if `mermaid`'s first real line (per first_diagram_line) starts
    with a recognized DIAGRAM_KEYWORDS entry, otherwise an error message
    describing why not. Factored out of main() (Task A6) so
    describe_image.py's own `--mermaid` handling applies the exact same
    validation instead of duplicating the keyword-regex check."""
    first_line = first_diagram_line(mermaid)
    if not first_line or not re.match(
        r"^(" + "|".join(re.escape(k) for k in DIAGRAM_KEYWORDS) + r")\b", first_line
    ):
        return (
            f"mermaid source doesn't start with a known diagram keyword "
            f"({', '.join(DIAGRAM_KEYWORDS)}); first line was {first_line!r}"
        )
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", required=True)
    parser.add_argument("--page", required=True, type=int)
    parser.add_argument("--asset", required=True, help='e.g. "assets/page2_vector1.png"')
    args = parser.parse_args()

    mermaid = sys.stdin.read().strip()
    if not mermaid:
        print("error: no mermaid source on stdin", file=sys.stderr)
        sys.exit(1)

    error = validate_diagram_source(mermaid)
    if error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)

    shard_path = paths.shard_path(args.doc, args.page, "image")
    shard = elements_lib.read_shard(shard_path)
    if not shard:
        print(f"error: {shard_path} not found — run extract-images first", file=sys.stderr)
        sys.exit(1)

    found = False
    for el in shard["elements"]:
        if el["type"] == "image" and el["asset"] == args.asset:
            el["mermaid"] = mermaid
            found = True
    if not found:
        print(f"error: no image element with asset {args.asset} on page {args.page}", file=sys.stderr)
        sys.exit(1)

    shard_path.write_text(json.dumps(shard, indent=2))
    print(f"landed mermaid on {args.asset} ({len(mermaid.splitlines())} line(s))")


if __name__ == "__main__":
    main()
