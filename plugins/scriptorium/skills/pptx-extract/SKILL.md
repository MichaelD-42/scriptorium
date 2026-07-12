---
name: pptx-extract
description: Extract native text, headings, tables, and images from PowerPoint slides that triage classified as tier "text" (pptx is digital-native, so that's every slide unless a prior failed grade forced "vision"). Writes both the body shard and the image shard in one call.
---

# Extract PPTX (Tier 1)

The pptx sibling of `extract-text` + `extract-images` combined into one
skill, since `python-pptx` gives structured access to both a slide's text
and its embedded pictures in the same pass — there's no separate
vector-region detection step like the PDF pipeline has, because a pptx
diagram is either a native shape tree (already structured, no extraction
needed) or a picture (handled here).

## How

```bash
uv run --project "${CLAUDE_PLUGIN_ROOT}" python \
  "${CLAUDE_PLUGIN_ROOT}/skills/pptx-extract/scripts/extract_pptx.py" --doc <doc-name> --pages 1,2,3
```

`--pages` is required and explicit on purpose, same reason as `extract-text`:
this skill must never process a slide it wasn't assigned, so a batch can't
overwrite what another batch (or a higher tier, after escalation) already
produced for a slide. It only ever writes **its own** shard files.

## What it does, per slide

- The **title placeholder** becomes a `heading` (level 1). There's no
  font-size ratio classification like `extract-text` uses (pptx headings
  are structural — a title placeholder — not inferred from size).
- Every other text-bearing shape's paragraphs become `paragraph` elements,
  one per non-empty paragraph.
- **Tables** (`shape.has_table`) become `table` elements (row-major list of
  lists, cell text as-is).
- **Pictures** (`shape.shape_type == PICTURE`) are saved to
  `output/<doc>/assets/page{N}_bitmap{idx}.<ext>` and become `image`
  elements with an empty caption — same contract as `extract-images`, so
  the same `caption_image.py` script fills them in afterward.
- **Speaker notes**, if present, become a trailing `paragraph` prefixed
  `"Speaker notes: "` so they're preserved without being confused for
  on-slide content.
- Reading order follows each shape's vertical position (`top`) on the
  slide, then notes last.
- **Charts** (`shape.has_chart`) are not extracted as images in this
  version — pptx-triage flags a slide with a chart as `loop_size: "tight"`
  so the grader looks closely, but rendering a chart to a picture asset
  isn't implemented yet. If a grade fails on a chart-bearing slide with
  `missing_image`, that's the known gap — the fix is a chart-to-image
  export path, not a captioning fix.

## Output

Writes one shard per given slide to `work/<doc>/shards/page{N}.text.json`
(body) and `work/<doc>/shards/page{N}.image.json` (images) — the same
shard schema `pdf-triage`'s pipeline uses, so `merge.py`/`assemble.py`/
`gates.py` need no pptx-specific handling. See `lib/elements.py`.
