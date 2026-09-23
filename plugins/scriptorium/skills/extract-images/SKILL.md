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
  `detect_figure_regions`, shared with `extract-text` — see below) and
  crop-renders each surviving region, not the whole page, at 200dpi to
  `page{N}_vector{k}.png`. A candidate region is dropped if it overlaps the
  furniture edge band, overlaps a real (non-frame) table's bbox, or is too
  small to be more than a stray line. This is what catches a diagram or
  chart sitting on an otherwise text-heavy page — the old whole-page rule
  (gated on the page having little text overall) missed this case entirely.

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
- If `work/<doc>/triage.json` has a `furniture` section (`pdf-triage`'s
  furniture detection), a bitmap whose xref is in `image_xrefs` (e.g. a logo
  repeated on every page) is skipped entirely — no `image` element is
  written for it. `frame_tables` entries are also excluded from both
  `page_has_table()`'s query and `lib/figures.py`'s real-table lookup, so a
  page whose only pdfplumber-detected table is the page frame doesn't
  suppress vector-region detection on that page, and a real ruled table
  never itself becomes a vector-region `image` element. No
  `triage.json`/`furniture` section => no filtering, same output as before.
- If `work/<doc>/triage.json` marks a given page `"role": "toc"`
  (`pdf-triage`'s printed-TOC-page detection), that page's shard is written
  as `{"page_number": n, "elements": [], "skipped": "toc"}` immediately,
  with no bitmap/vector-region extraction attempted. Applies per-page even
  when `--pages` mixes a TOC page in with body pages.
- Captioning is intentionally **not** done here — a script can't judge what
  an image shows. The calling agent (the `extractor` role) looks at the
  saved PNG (with the Read tool) and fills the caption in with:

  ```bash
  uv run --project "${CLAUDE_PLUGIN_ROOT}" python \
    "${CLAUDE_PLUGIN_ROOT}/skills/extract-images/scripts/caption_image.py" \
    --doc <doc-name> --page 2 --asset assets/page2_bitmap1.png --caption "..."
  ```

- For a diagram/flowchart the agent can faithfully reconstruct, it can
  additionally set a `mermaid` field on the same `image` element — optional,
  in addition to the caption, never a replacement for the saved PNG:

  ```bash
  echo 'flowchart TD
    A --> B' | uv run --project "${CLAUDE_PLUGIN_ROOT}" python \
    "${CLAUDE_PLUGIN_ROOT}/skills/extract-images/scripts/mermaid_image.py" \
    --doc <doc-name> --page 2 --asset assets/page2_vector1.png
  ```

  Mermaid source is read from stdin (it's multi-line); the script rejects
  input that doesn't start with a recognized mermaid diagram keyword.
