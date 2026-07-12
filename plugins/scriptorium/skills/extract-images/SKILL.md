---
name: extract-images
description: Extract embedded bitmap images and detect vector-graphic regions (diagrams, charts drawn with PDF drawing operators) on given pages, saving them as PNG assets.
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

## How

```bash
uv run --project "${CLAUDE_PLUGIN_ROOT}" python \
  "${CLAUDE_PLUGIN_ROOT}/skills/extract-images/scripts/extract_images.py" --doc <doc-name> --pages 2,4
```

## Output

- Saves assets to `output/<doc>/assets/page{N}_{bitmap|vector}{idx}.png`.
- Writes one shard per given page to `work/<doc>/shards/page{N}.image.json`
  (`image` elements, `kind: "bitmap"|"vector"`, `asset: "assets/..."`) — even
  when a page has no images, so a retry can tell "checked, found nothing"
  apart from "never checked". This shard is independent of whatever
  text/OCR/vision shard the page has; `merge.py` combines them.
- Captioning is intentionally **not** done here — a script can't judge what
  an image shows. The calling agent (the `extractor` role) looks at the
  saved PNG (with the Read tool) and fills the caption in with:

  ```bash
  uv run --project "${CLAUDE_PLUGIN_ROOT}" python \
    "${CLAUDE_PLUGIN_ROOT}/skills/extract-images/scripts/caption_image.py" \
    --doc <doc-name> --page 2 --asset assets/page2_bitmap1.png --caption "..."
  ```
