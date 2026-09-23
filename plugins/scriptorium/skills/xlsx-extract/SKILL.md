---
name: xlsx-extract
description: Extract each sheet's name, used-range table, and embedded images from a workbook. One sheet = one page, matching xlsx-triage. Writes both the body shard and the image shard in one call, same as pptx-extract/docx-extract.
---

# Extract XLSX (Tier 1)

The xlsx sibling of `pptx-extract`/`docx-extract`: `openpyxl` gives
structured access to cell values and embedded images in one pass, so
there's no separate OCR/vision step — xlsx is digital-native like the
other Office formats.

## How

```bash
uv run --project "${CLAUDE_PLUGIN_ROOT}" python \
  "${CLAUDE_PLUGIN_ROOT}/skills/xlsx-extract/scripts/extract_xlsx.py" --doc <doc-name> --pages 1,2
```

`--pages` is required and explicit, same reason as every other extract
skill: never process a sheet you weren't assigned, so parallel batches
can't race on the same shard file. Page numbers are 1-indexed positions in
`workbook.sheetnames` order, matching `xlsx-triage`.

## What it does, per sheet

- The **sheet name** becomes a `heading` (level 1) — there's no sub-heading
  structure within a sheet the way a docx has Heading 2/3, so a sheet is
  always exactly one heading plus (at most) one table.
- The sheet's **used range** (`ws.dimensions`) becomes one `table` element
  (row-major, cell values coerced to strings, blank cells as `""`). Opened
  with `data_only=True` so formula cells return their last-calculated
  value, not the formula text — this only works if the file was last saved
  by an application that caches computed values (Excel does; a workbook
  whose formulas were never opened in a real spreadsheet app before saving
  may still show blank for those cells).
- Sheets with no data at all produce no table element (an empty sheet
  isn't a defect — `xlsx-triage`'s `has_table: false` already flags it).
- **Embedded images** (`ws._images`) are saved to
  `output/<doc>/assets/page{N}_bitmap{idx}.<ext>` and become `image`
  elements with an empty caption — same contract as every other format's
  image shard, filled in afterward by the same `describe_image.py` (its
  `--caption` alias — xlsx has no script-side caption detection).
- **Charts** (`ws._charts`) are not extracted as images in this version —
  openpyxl can detect a chart's presence but has no rendering engine to
  turn it into a picture, so there's nothing to save. `xlsx-triage` flags a
  sheet with a chart as `loop_size: "tight"`; a grade failure tagging
  `missing_image` on a chart-only sheet is this known gap, not a
  captioning bug (same accepted limitation as pptx charts).

## Output

Writes one shard per given sheet to `work/<doc>/shards/page{N}.text.json`
(body) and `work/<doc>/shards/page{N}.image.json` (images) — the same
shard schema every other format uses. See `lib/elements.py`.
