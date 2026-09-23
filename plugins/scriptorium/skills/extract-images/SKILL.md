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
  extractable "image" to pull out, so a page with a lot of vector drawing
  and little text is treated as a diagram and captured by rendering that
  page to PNG (reusing `render-pages`' output if present).

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

- Saves assets to `output/<doc>/assets/page{N}_{bitmap|vector}{idx}.png`.
- Writes one shard per given page to `work/<doc>/shards/page{N}.image.json`
  (`image` elements, `kind: "bitmap"|"vector"`, `asset: "assets/..."`,
  `bbox: [x0, y0, x1, y1]`) — even when a page has no images, so a retry
  can tell "checked, found nothing" apart from "never checked". This shard
  is independent of whatever text/OCR/vision shard the page has; `merge.py`
  combines them.
- If `work/<doc>/triage.json` has a `furniture` section (`pdf-triage`'s
  furniture detection), a bitmap whose xref is in `image_xrefs` (e.g. a logo
  repeated on every page) is skipped entirely — no `image` element is
  written for it. `frame_tables` entries are also excluded from
  `page_has_table()`'s query, so a page whose only pdfplumber-detected
  table is the page frame doesn't suppress vector-region detection on that
  page. No `triage.json`/`furniture` section => no filtering, same output
  as before.
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
