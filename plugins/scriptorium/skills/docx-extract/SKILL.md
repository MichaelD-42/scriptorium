---
name: docx-extract
description: Extract native text, headings, tables, and images from a docx's logical pages (Heading-1 sections, per docx-triage's split). Writes both the body shard and the image shard in one call, same as pptx-extract.
---

# Extract DOCX (Tier 1)

The docx sibling of `extract-text` + `extract-images` combined, mirroring
`pptx-extract`'s shape: `python-docx` gives structured access to text,
tables, and inline images in one pass, so there's no separate OCR/vector-
region step — docx is digital-native, and there is no `ocr`/`vision` rung
for this format at all (see `commands/extract.md`'s Decide step for what
happens when a docx page still fails grading).

Uses `lib/docx_pages.split_pages()` — **the same function `docx-triage`
calls** — to get each page's block items, so a `--pages` request always
lines up with the page numbers triage assigned. Recomputing the split per
call is deterministic and cheap; it is not read back from `triage.json`.

## How

```bash
uv run --project "${CLAUDE_PLUGIN_ROOT}" python \
  "${CLAUDE_PLUGIN_ROOT}/skills/docx-extract/scripts/extract_docx.py" --doc <doc-name> --pages 1,2,3
```

`--pages` is required and explicit, same reason as `extract-text`/
`pptx-extract`: never process a page you weren't assigned, so parallel
batches can't race on the same shard file.

## What it does, per page

- **Heading** paragraphs (Word styles `Heading 1`-`Heading 9`, or `Title`)
  become `heading` elements, level clamped to 1-3 to match the rest of the
  pipeline's convention (deeper Word heading levels all land at level 3).
- Every other non-empty paragraph becomes a `paragraph` element.
- **Tables** become `table` elements (row-major list of lists, cell text
  as-is, via `cell.text` which already joins a cell's own paragraphs).
- **Inline images** (`lib.docx_pages.paragraph_images`) are saved to
  `output/<doc>/assets/page{N}_bitmap{idx}.<ext>` and become `image`
  elements with an empty caption — same contract as `extract-images`/
  `pptx-extract`, so the same `describe_image.py` (its `--caption` alias —
  docx has no script-side caption detection) fills them in afterward
  (the extractor reads the saved asset directly; no page render needed to
  caption an individual image).
- Reading order follows the document's own block order (paragraphs and
  tables interleaved as they appear in the XML body).

## Output

Writes one shard per given page to `work/<doc>/shards/page{N}.text.json`
(body) and `work/<doc>/shards/page{N}.image.json` (images) — the same
shard schema every other format uses, so `merge.py`/`assemble.py`/
`gates.py` need no docx-specific handling. See `lib/elements.py`.
