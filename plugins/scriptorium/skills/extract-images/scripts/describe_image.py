#!/usr/bin/env python3
"""Set the agent-authored interpretation fields on a previously-extracted
image element: `description` (always), and optionally `data_table` (for a
chart-like figure) and `mermaid` (for a diagram/flowchart the agent can
faithfully redraw) -- mutating that page's image shard, the same way the
old `caption_image.py` mutated it for `caption` alone.

Generalizes `caption_image.py` (Task A6). For a PDF image element (any
`kind`), `caption` is now script-authoritative -- extract_images.py itself
sets it, via `lib/figures.py`'s `find_caption_line()`, before the agent
ever looks at the crop -- so this script's job shrinks to the three fields
a script genuinely cannot judge on its own: what the image shows, whether
it encodes tabular data, and whether it's a diagram simple enough to redraw
as Mermaid.

    uv run ... describe_image.py --doc sample --page 2 \
        --asset assets/page2_vector1.png \
        --description "A bar chart showing quarterly revenue." \
        [--data-table '[["Q1", 10], ["Q2", 14]]'] \
        [--mermaid 'flowchart TD
  A --> B']

`--data-table` must be a JSON array; it's parsed and stored as a structure
on the element, not kept as a raw string. `--mermaid` is validated the same
way `mermaid_image.py` validates its own stdin-read source (must start with
a recognized diagram keyword) -- reuses `mermaid_image.validate_diagram_source`
rather than duplicating that check.

`--caption` is kept as a backward-compatible alias, NOT a no-op: pptx/docx/
xlsx/html image elements have no script-side caption detection (this
codebase's caption search only exists for PDF pages, which have a fitz text
layer to search near each image's bbox) -- caption stays agent-authored for
those formats, unchanged from before this task. Using `--caption` prints a
warning (for a PDF element, extract_images.py already set `caption`, and
any value passed here would just be overwritten by a future re-run of that
script) but still writes the field, so existing non-PDF captioning behavior
-- and `grade-output/text_mode_grade.py`'s `bad_caption` check, which
depends on a real caption for docx/xlsx/html images -- keeps working
unchanged. A judgment call: the brief suggested a true no-op, but that would
have silently regressed captioning for every non-PDF format with no
replacement in this task's scope.

`--figure-text` is a small addition beyond the brief's three named fields:
Task A5 pre-ruled that the agent fills a PDF vector-region element's
`figure_text` via vision when the script-side value (a real text-layer
read) comes back null/absent -- but no script anywhere could actually land
that vision transcription until now. Since this is the same "agent looked
at the crop, script lands the result" shape as `--description`, it's
mechanically the same kind of write, so it lives here rather than as a
fourth standalone script. Judgment call, not explicitly in the brief's CLI
signature -- documented in task-A6-report.md.

Unlike `--caption`/`--data-table`/`--mermaid`, "was `figure_text` already
set" is a deterministic, code-checkable precondition, not a judgment call
the script has to trust the agent on -- so `--figure-text` is refused
(exit 1, matching this script's other validation-failure paths, e.g.
invalid `--data-table` JSON or `--mermaid`) when the target element
already carries a non-empty `figure_text`, rather than silently
overwriting real, deterministically-extracted text with a vision guess.

`--no-visible-text` (Task A9 fix round 1) records `no_visible_text: true`
for an image with no printed caption and no visible text, after the agent
checked the render. It exists so that grade-output's figures_complete gate
can accept such an image without an agent-written caption (`caption` is
only the printed caption). Refused when the element already has a caption
or figure_text, or together with `--caption`/`--figure-text`.

Fix round 2: `--no-visible-text` is also refused unless the document's
input format (paths.detect_input_format) is pdf or image -- the formats
whose caption is verbatim-only. For pptx/docx/xlsx/html the agent writes
`--caption` instead.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import elements as elements_lib  # noqa: E402
import paths  # noqa: E402

# Sibling import -- same convention assemble.py's `import reqif_builder`
# uses -- so describe_image.py's `--mermaid` handling shares
# mermaid_image.py's exact keyword validation instead of duplicating it.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mermaid_image  # noqa: E402

# Same set as grade-output/scripts/gates.py's NO_VISIBLE_TEXT_FORMATS.
NO_VISIBLE_TEXT_FORMATS = {"pdf", "image"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", required=True)
    parser.add_argument("--page", required=True, type=int)
    parser.add_argument("--asset", required=True, help='e.g. "assets/page2_bitmap1.png"')
    parser.add_argument("--description", required=True)
    parser.add_argument("--data-table", dest="data_table", default=None, help='JSON array of rows, e.g. \'[["Q1", 10], ["Q2", 14]]\'')
    parser.add_argument("--mermaid", default=None, help="mermaid diagram source (same keyword validation as mermaid_image.py)")
    parser.add_argument("--caption", default=None, help="deprecated backward-compat alias -- see module docstring")
    parser.add_argument("--figure-text", dest="figure_text", default=None, help="vision transcription -- only when the script-side figure_text came back null/absent (see module docstring)")
    parser.add_argument(
        "--no-visible-text", dest="no_visible_text", action="store_true",
        help="record that the image has no printed caption and no visible text (checked on the render) -- refused when it has a caption or figure_text",
    )
    args = parser.parse_args()

    parsed_table = None
    if args.data_table is not None:
        try:
            parsed_table = json.loads(args.data_table)
        except json.JSONDecodeError as exc:
            print(f"error: --data-table is not valid JSON: {exc}", file=sys.stderr)
            sys.exit(1)

    if args.mermaid is not None:
        error = mermaid_image.validate_diagram_source(args.mermaid)
        if error:
            print(f"error: {error}", file=sys.stderr)
            sys.exit(1)

    if args.no_visible_text and (args.caption is not None or args.figure_text is not None):
        print("error: --no-visible-text cannot be combined with --caption or --figure-text", file=sys.stderr)
        sys.exit(1)

    if args.no_visible_text:
        input_format = paths.detect_input_format(args.doc)
        if input_format not in NO_VISIBLE_TEXT_FORMATS:
            print(
                f"error: --no-visible-text is only for pdf and image documents (this one is {input_format!r}); "
                "for pptx/docx/xlsx/html write the caption with --caption",
                file=sys.stderr,
            )
            sys.exit(1)

    if args.caption is not None:
        print(
            "warning: --caption is deprecated -- caption is script-authoritative for PDF "
            "image elements now (set automatically by extract-images); still applied here "
            "for formats without script-side caption detection (pptx/docx/xlsx/html)",
            file=sys.stderr,
        )

    shard_path = paths.shard_path(args.doc, args.page, "image")
    shard = elements_lib.read_shard(shard_path)
    if not shard:
        print(f"error: {shard_path} not found — run extract-images first", file=sys.stderr)
        sys.exit(1)

    found = False
    for el in shard["elements"]:
        if el["type"] == "image" and el["asset"] == args.asset:
            if args.figure_text is not None and el.get("figure_text"):
                # A5's contract: the agent may only fill figure_text via
                # vision when the script-side value came back null/absent
                # -- never overwrite real, deterministically-extracted text.
                # Unlike --caption/--data-table/--mermaid (judgment calls a
                # script can't verify), "was figure_text already set" is a
                # deterministic, code-checkable precondition, so it's
                # enforced here rather than left as documentation only.
                print(
                    f"error: {args.asset} already has a script-side figure_text -- "
                    "refusing to overwrite it with --figure-text. --figure-text is "
                    "only for an element whose figure_text came back null/absent "
                    "(no text layer at all); if it's already set, the vision step "
                    "isn't needed for this element.",
                    file=sys.stderr,
                )
                sys.exit(1)
            if args.no_visible_text and ((el.get("caption") or "").strip() or (el.get("figure_text") or "").strip()):
                # Task A9 fix round 1: the flag says "no printed caption and
                # no visible text". An element that has either is not that.
                print(
                    f"error: {args.asset} already has a caption or figure_text -- "
                    "refusing --no-visible-text",
                    file=sys.stderr,
                )
                sys.exit(1)
            el["description"] = args.description
            if args.no_visible_text:
                el["no_visible_text"] = True
            if parsed_table is not None:
                el["data_table"] = parsed_table
            if args.mermaid is not None:
                el["mermaid"] = args.mermaid
            if args.caption is not None:
                el["caption"] = args.caption
            if args.figure_text is not None:
                el["figure_text"] = args.figure_text
            found = True
    if not found:
        print(f"error: no image element with asset {args.asset} on page {args.page}", file=sys.stderr)
        sys.exit(1)

    shard_path.write_text(json.dumps(shard, indent=2))
    print(f"described {args.asset}: {args.description!r}")


if __name__ == "__main__":
    main()
