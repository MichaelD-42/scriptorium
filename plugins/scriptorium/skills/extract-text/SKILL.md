---
name: extract-text
description: Extract native text, headings, and tables from PDF pages that triage classified as tier "text". Fast, deterministic, no OCR or vision involved.
---

# Extract Text (Tier 1)

The cheap, deterministic extraction tier. Only run this on pages triage
marked `text` — pages without a usable text layer belong to `ocr-page`
instead.

## How

```bash
uv run --project "${CLAUDE_PLUGIN_ROOT}" python \
  "${CLAUDE_PLUGIN_ROOT}/skills/extract-text/scripts/extract_text.py" --doc <doc-name> --pages 1,2,3 [--body-size 11.0]
```

`--body-size` should be `pdf-triage`'s `body_size` field — pass it through
for every call on this document. Without it, this script falls back to
estimating body size from just the pages it was given, which is unreliable
on a sparse page (e.g. a page with only a heading and one caption line has
no real "body text" sample of its own to measure).

`--pages` is required and explicit on purpose: this skill must never process
a page it wasn't assigned, so a Tier-1 pass can't silently overwrite what a
higher tier already produced for a page that failed grading and got escalated.
It only ever writes **its own** shard file, never reads or touches another
page's or another tier's shard — that's what makes it safe to run several
`extractor` subagents in parallel over different page batches of the same
document.

## What it does

- Text blocks, grouped by font size relative to the document's body size
  (`--body-size`, from `pdf-triage`), are classified as `heading` (level
  1-3, ratio ≥1.9/≥1.45/≥1.15) or `paragraph`.
- Tables are detected with `pdfplumber` and emitted as `table` elements
  (row-major list of lists).
- Reading order follows PyMuPDF's block order top-to-bottom, left-to-right.
- Every `heading`/`paragraph`/`table` element carries a `"bbox": [x0, y0,
  x1, y1]` field (fitz/pdfplumber-style, top-left origin, y down).
- If `work/<doc>/triage.json` has a `furniture` section (`pdf-triage`'s
  furniture detection), it's applied before anything else is written: a
  pdfplumber table whose bbox matches a `frame_tables` entry is dropped
  (page frames aren't real tables — never emitted as a `table` element).
  For text: a block that sits in the top/bottom 12% edge band has each of
  its **lines** checked individually against `line_patterns` — only the
  matching line(s) are excluded, not the whole block. A block outside the
  edge band, or with no matching lines, is untouched; a block where every
  line matches is dropped entirely; a block that mixes one furniture line
  with unrelated real content on an adjacent line (PyMuPDF sometimes
  groups a footer note and a page number into one block) keeps the real
  line, with its `bbox` recomputed from just the surviving line(s). No
  `triage.json`/`furniture` section => no removal, same output as before.
- If `work/<doc>/triage.json` marks a given page `"role": "toc"`
  (`pdf-triage`'s printed-TOC-page detection), that page's shard is written
  as `{"page_number": n, "elements": [], "skipped": "toc"}` immediately,
  with no text/table extraction attempted — a printed TOC page's own text
  is redundant with `toc.json` and isn't useful body content. This applies
  per-page even when `--pages` mixes a TOC page in with body pages.

## Output

Writes one shard per given page to `work/<doc>/shards/page{N}.text.json` —
see `lib/elements.py` for the shard schema and how `merge.py` (in
`assemble-output`) later combines every page's shards into `elements.json`.
