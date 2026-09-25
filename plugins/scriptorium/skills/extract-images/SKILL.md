---
name: extract-images
description: Extract embedded bitmap images and detect vector-graphic regions (diagrams, charts drawn with PDF drawing operators) on given pages, saving them as PNG assets. For a standalone image document, lands the whole file as its one page's bitmap asset instead.
---

# Extract Images

Handles both image kinds a PDF can contain:

- **Bitmaps**: images embedded via `/Image` XObjects (photos, scanned
  figures, logos) — extracted directly from the PDF at native resolution.
- **Vector graphics**: diagrams/charts drawn with PDF path operators
  (lines, curves, fills) rather than embedded as an image. These have no
  extractable "image" to pull out, so this skill clusters a page's vector
  drawings into candidate regions (`lib/figures.py`'s
  `detect_figure_regions_with_exclusions`, shared with `extract-text` — see
  below) and crop-renders each surviving region, not the whole page, at
  200dpi to `page{N}_vector{k}.png`. A candidate region is dropped if:
  - it's a single drawing matching `triage.json["furniture"]
    ["frame_drawings"]` (Task A5b — a page-frame border identified by
    *repetition* across the document, not by size, so a large one-off real
    figure is never mistaken for furniture and dropped before clustering
    even sees it);
  - *more than half* its own area lies inside the furniture edge band
    (Task A5b tightened this from "any overlap at all", so a tall real
    figure that only grazes the band survives);
  - it overlaps a real (non-frame) table's bbox; or
  - it's too small to be more than a stray line.

  This is what catches a diagram or chart sitting on an otherwise
  text-heavy page — the old whole-page rule (gated on the page having
  little text overall) missed this case entirely.

For a standalone **image** document (`input_format` `image`), there's
nothing to detect — the whole input file *is* the diagram/photo. This skill
normalizes it to PNG and lands it as page 1's single bitmap element
(`assets/page1_bitmap1.png`), skipping the bitmap-XObject/vector-region
logic above entirely. Captioning and mermaid work exactly the same
afterward, via the calling agent.

## How

```bash
uv run --project "${CLAUDE_PLUGIN_ROOT}" python \
  "${CLAUDE_PLUGIN_ROOT}/skills/extract-images/scripts/extract_images.py" --doc <doc-name> --pages 2,4
```

For an image document, `--pages` is always `1` — there's only ever page 1.

## Output

- Saves assets to `output/<doc>/assets/page{N}_{bitmap|vector}{idx}.png`
  (`vector{idx}` is 1-indexed per page, in top-to-bottom region order).
- Writes one shard per given page to `work/<doc>/shards/page{N}.image.json`
  (`image` elements, `kind: "bitmap"|"vector"`, `asset: "assets/..."`,
  `bbox: [x0, y0, x1, y1]`) — even when a page has no images, so a retry
  can tell "checked, found nothing" apart from "never checked". This shard
  is independent of whatever text/OCR/vision shard the page has; `merge.py`
  combines them, interleaving image elements with text elements by `bbox`
  y-position (Task A5) rather than always trailing them after.
- A vector-region `image` element also carries `figure_text` — the
  region's own text-layer lines (if any), newline-joined — whenever the
  region has a text layer at all; absent/`null` when it doesn't (e.g. a
  pure-raster chart with no underlying text), which is the signal a later
  vision-fallback step uses to fill it in instead. These lines are excluded
  from `extract-text`'s paragraph/heading output for the same page, so they
  never appear twice.
- Every `image` element (bitmap or vector-region) also gets a
  script-authoritative `caption`: `lib/figures.py`'s `find_caption_line`
  searches the text layer within 60pt directly above or below the
  element's own bbox for a line matching `Figure n[.:]`/`Fig. n`/`Table n`
  (case-insensitive) and, if found, sets `caption` to that line's text
  verbatim; absent/`null` if nothing nearby matches. That same line is
  excluded from `extract-text`'s paragraph/heading output on the same page
  — same "shared detection, no ordering dependency" pattern as
  `figure_text` above, so the two scripts can never disagree about which
  line is the caption. This only applies to PDF image elements — pptx/docx/
  xlsx/html images have no text-layer/bbox convention to search and keep
  `caption` agent-authored via `describe_image.py`'s `--caption` (below).
- If `work/<doc>/triage.json` has a `furniture` section (`pdf-triage`'s
  furniture detection), a bitmap whose xref is in `image_xrefs` (e.g. a logo
  repeated on every page) is skipped entirely — no `image` element is
  written for it. `frame_tables` entries are also excluded from both
  `page_has_table()`'s query and `lib/figures.py`'s real-table lookup, so a
  page whose only pdfplumber-detected table is the page frame doesn't
  suppress vector-region detection on that page, and a real ruled table
  never itself becomes a vector-region `image` element. No
  `triage.json`/`furniture` section => no filtering, same output as before.
- **`excluded_regions` (Task A5b, "no silent drops")**: the page's image
  shard also carries `excluded_regions: [{"bbox": [...], "reason":
  "frame_drawing"|"tiny"|"furniture_band"|"table_overlap"}]` — every
  candidate a filter dropped on this page, always present (an empty list
  when nothing was dropped), so a large region that a filter removes is
  never simply invisible. `merge.py` passes it through to the merged page
  dict the same way `skipped` already does. `grade-output`'s
  `large_region_excluded` gate flags (as a warning, not a hard failure) any
  entry here whose reason isn't `frame_drawing`/`tiny` and whose area is
  more than 20% of the page — see `grade-output`'s SKILL.md.
- If `work/<doc>/triage.json` marks a given page `"role": "toc"`
  (`pdf-triage`'s printed-TOC-page detection), that page's shard is written
  as `{"page_number": n, "elements": [], "skipped": "toc"}` immediately,
  with no bitmap/vector-region extraction attempted. Applies per-page even
  when `--pages` mixes a TOC page in with body pages.
- Interpretation is intentionally **not** done here — a script can't judge
  what an image shows, whether it encodes tabular data, or whether it's a
  diagram simple enough to redraw. The calling agent (the `extractor` role)
  looks at the saved PNG (with the Read tool) and fills these in with
  `describe_image.py` (generalized from the old `caption_image.py` — Task
  A6, since `caption` is script-authoritative for a PDF element now, per
  above):

  ```bash
  uv run --project "${CLAUDE_PLUGIN_ROOT}" python \
    "${CLAUDE_PLUGIN_ROOT}/skills/extract-images/scripts/describe_image.py" \
    --doc <doc-name> --page 2 --asset assets/page2_bitmap1.png \
    --description "A bar chart showing quarterly revenue." \
    [--data-table '[["Q1", 10], ["Q2", 14]]'] \
    [--mermaid 'flowchart TD
  A --> B']
  ```

  - `--description` is always given, for any figure.
  - `--data-table` (optional) is a JSON array of rows — only for a
    chart-like figure; it's parsed and stored as a structure, not kept as a
    raw string.
  - `--mermaid` (optional) is only for a diagram/flowchart the agent can
    faithfully reconstruct — validated the same way `mermaid_image.py`
    validates its own stdin-read source (must start with a recognized
    diagram keyword).
  - `--caption` still exists as a backward-compatible alias — deprecated
    and warned-about for a PDF element (whose `caption` `extract-images`
    already set), but still the real way to set `caption` for a pptx/docx/
    xlsx/html image element, which has no script-side caption detection.
  - `--figure-text` (optional, PDF vector-region elements only) lands a
    vision transcription — only used when the region's script-side
    `figure_text` (above) came back null/absent, i.e. the region had no
    text layer at all. Enforced, not just documented: `describe_image.py`
    refuses (exits 1) to overwrite an element that already has a non-empty
    `figure_text`, since that precondition is deterministic and
    code-checkable, unlike the other agent-judgment fields.
  - `--no-visible-text` (Task A9 fix round 1) sets `"no_visible_text":
    true`: the agent checked the render and the image has no printed
    caption and no visible text. It is refused (exit 1) when the element
    has a caption or figure_text, together with `--caption`/
    `--figure-text`, or for a document that is not pdf or image (fix
    round 2): for pptx/docx/xlsx/html the agent writes `--caption`. It is not rendered in the output; the description
    already renders inside the interpretation markers.

  `mermaid_image.py` (below) still exists standalone too, for a
  stdin-based, `describe_image.py`-independent call.

- For a diagram/flowchart the agent can faithfully reconstruct, it can
  alternatively set `mermaid` on its own via `mermaid_image.py` — same
  effect as `describe_image.py`'s `--mermaid`, useful when the agent wants
  to land the diagram separately from the description/data_table call:

  ```bash
  echo 'flowchart TD
    A --> B' | uv run --project "${CLAUDE_PLUGIN_ROOT}" python \
    "${CLAUDE_PLUGIN_ROOT}/skills/extract-images/scripts/mermaid_image.py" \
    --doc <doc-name> --page 2 --asset assets/page2_vector1.png
  ```

  Mermaid source is read from stdin (it's multi-line); the script rejects
  input that doesn't start with a recognized mermaid diagram keyword.
