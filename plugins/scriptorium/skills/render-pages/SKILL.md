---
name: render-pages
description: Render pages to PNG images. Required before OCR, vision-based extraction, or grading, since those all need to look at pixels, not just the text layer. PDF pages rasterize directly; pptx slides are converted to PDF via LibreOffice first, then rasterized the same way; a standalone image document is normalized straight to PNG.
---

# Render Pages

Rasterizes pages to `work/<doc>/pages/page{N}.png`. Shared by three
different consumers, which is why it is its own skill instead of being
duplicated inside `ocr-page` or `grade-output`:

- `ocr-extractor` — feeds pages to Tesseract and to Claude vision.
- `image-extractor` — needs a page render to crop vector-graphic regions.
- `grader` — compares the rendered page against the assembled output.

For **pptx**, there's no native "page" bitmap the way a PDF page has one:
this skill first shells out to `soffice --headless --convert-to pdf` to get
a slide-for-slide PDF (cached at `work/<doc>/<doc>.pdf`, skipped on a retry
if already newer than the source `.pptx`), then rasterizes that PDF with
the same PyMuPDF code path as a native PDF — 1 slide = 1 PDF page = 1 PNG.
Requires the `soffice` binary (bootstrapped by `setup-environment` when a
pptx is queued).

For a standalone **image** document (png/jpg/jpeg/webp/tiff), there's no
rasterization to do at all — the input *is* the page. This skill just
normalizes it to `work/<doc>/pages/page1.png` (RGB PNG, native resolution,
no dpi/zoom step) so every downstream consumer (OCR, vision, grading) sees
the same PNG shape it sees for every other format.

## How

```bash
uv run --project "${CLAUDE_PLUGIN_ROOT}" python \
  "${CLAUDE_PLUGIN_ROOT}/skills/render-pages/scripts/render.py" --doc <doc-name> [--pages 1,3,5] [--dpi 150]
```

Follow-up R26: to read small labels in one figure, render just its bbox
at a high resolution:

```bash
uv run --project "${CLAUDE_PLUGIN_ROOT}" python   "${CLAUDE_PLUGIN_ROOT}/skills/render-pages/scripts/render_region.py" --doc <doc-name> --page <n> --bbox x0,y0,x1,y1 [--dpi 400]
```

It writes `work/<doc>/zoom/page{N}_{x0}_{y0}.png` (the bbox plus 6 pt on
each side; PDF pages only) and prints the path.

Omit `--pages` to render every page. Rendering is idempotent and skips a
page whose PNG already exists unless `--force` is passed — re-rendering
the whole document on every retry is wasted work the loop doesn't need.

## Output

`work/<doc>/pages/page{N}.png`, one per requested page, 1-indexed to match
PDF page numbers everywhere else in this plugin.
