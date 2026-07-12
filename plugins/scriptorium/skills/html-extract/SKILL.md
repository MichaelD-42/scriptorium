---
name: html-extract
description: Extract native headings, paragraphs, tables, and images from an HTML document's single page (per html-triage). Writes both the body shard and the image shard in one call, same as docx-extract/xlsx-extract.
---

# Extract HTML (Tier 1)

The html sibling of `docx-extract`/`xlsx-extract`: HTML is digital-native,
so there's no separate OCR/vector-region step — everything comes from
walking the parsed DOM (`lib/html_pages.py`, via BeautifulSoup) in one
pass. There is no `ocr`/`vision` rung for this format at all (see
`commands/extract.md`'s Decide step for what happens when an HTML page
still fails grading).

The whole document is one page (per `html-triage`) — `--pages` is still
required for interface consistency with every other extract skill, but is
always `1`.

## How

```bash
uv run --project "${CLAUDE_PLUGIN_ROOT}" python \
  "${CLAUDE_PLUGIN_ROOT}/skills/html-extract/scripts/extract_html.py" --doc <doc-name> --pages 1
```

## What it does

- **Heading** tags (`<h1>`-`<h6>`) become `heading` elements, level clamped
  to 1-3 to match the rest of the pipeline's convention (`<h4>`-`<h6>` all
  land at level 3).
- **Paragraph-like** tags (`<p>`, `<li>`, `<pre>`, `<blockquote>`) become
  `paragraph` elements.
- **Tables** (`<table>`) become `table` elements (row-major list of lists,
  cell text via `get_text(strip=True)`).
- **Images** (`<img>`) whose `src` is a `data:` URI or a local file
  reference are saved to `output/<doc>/assets/page1_bitmap{idx}.<ext>` and
  become `image` elements with an empty caption — same contract as
  `extract-images`/`docx-extract`, so the same `caption_image.py` fills
  them in afterward. Remote (`http(s)://`) sources are skipped — not
  fetched, not counted (see `lib/html_pages.saveable_images`).
- Reading order follows the document's own tag order.

## Output

Writes `work/<doc>/shards/page1.text.json` (body) and
`work/<doc>/shards/page1.image.json` (images) — the same shard schema
every other format uses, so `merge.py`/`assemble.py`/`gates.py` need no
html-specific handling. See `lib/elements.py`.
