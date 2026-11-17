# Extract PPTX (Tier 1)

The pptx sibling of `extract-text` + `extract-images` combined into one
tool, since `python-pptx` gives structured access to both a slide's text
and its embedded pictures in the same pass — there's no separate
vector-region detection step like the PDF pipeline has, because a pptx
diagram is either a native shape tree (already structured, no extraction
needed) or a picture (handled here).

## How

```bash
uv run --project "${CLAUDE_PLUGIN_ROOT}" python \
  "${CLAUDE_PLUGIN_ROOT}/tools/pptx-extract/scripts/extract_pptx.py" --doc <doc-name> --pages 1,2,3
```

`--pages` is required and explicit on purpose, same reason as `extract-text`:
this tool must never process a slide it wasn't assigned, so a batch can't
overwrite what another batch (or a higher tier, after escalation) already
produced for a slide. It only ever writes **its own** shard files.

## What it does, per slide

- The **title placeholder** becomes a `heading` (level 1). There's no
  font-size ratio classification like `extract-text` uses (pptx headings
  are structural — a title placeholder — not inferred from size).
- **Footer, slide-number and date placeholders** are page furniture and
  are skipped (a date field's cached text is the last-save date anyway).
- Every other text-bearing shape's paragraphs become `paragraph` elements,
  one per non-empty paragraph. Struck-through runs (`strike="sngStrike"` or
  `"dblStrike"`) are wrapped in Markdown `~~...~~`, in table cells too; the
  HTML output shows them as `<del>`.
- **Tables** (`shape.has_table`) become `table` elements (row-major list of
  lists, cell text as-is).
- **Pictures** (`shape.shape_type == PICTURE`) are saved to
  `output/<doc>/assets/page{N}_bitmap{idx}.<ext>` and become `image`
  elements with an empty caption — same contract as `extract-images`, so
  the same `describe_image.py` script fills them in afterward. A picture's
  crop (`a:srcRect`) is applied, so the asset is the part the slide shows
  (a negative value is an outset and is clamped, not padded); a picture
  cropped away entirely is skipped. An EMF/WMF picture, or one PIL cannot
  read, is cropped from the slide PDF instead (below).
- **Slide-PDF crops**: some figures are taken from the rendered slide, not
  from the file: `page{N}_shape{id}.png`, `kind: "vector"`, cut at the
  shape's bbox from `work/<doc>/<doc>.pdf` (`render.py`'s LibreOffice
  conversion, run on first need only, so a deck with no such figure needs
  no LibreOffice) with `render_region.py`'s `crop_png`. If the slide PDF
  can't be made, the figure gets no element and a warning on stderr.
- Every image element records `source_shape_id`, the id of the shape it
  came from.
- **Speaker notes**, if present, become a trailing `paragraph` prefixed
  `"Speaker notes: "` so they're preserved without being confused for
  on-slide content.
- Reading order follows each shape's vertical position on the slide,
  then notes last. A group member's position is mapped through its
  groups' transforms (`a:chOff`/`a:chExt`), so it is in slide space. Each
  body element carries that position as `top` and each image as `bbox`,
  in points (1 pt = 12700 EMU), and `merge.py` sorts the two shards into
  one stream on it.
- **Hidden shapes** (`cNvPr hidden="1"`), and every member of a hidden
  group, are skipped.
- **Embedded objects, charts and SmartArt** (a `graphicFrame` whose
  `a:graphicData` uri ends in `/ole`, `/chart` or `/diagram`) become a
  slide-PDF crop at the frame's bbox: exactly what the slide prints,
  with no EMF decoding. A frame thinner or shorter than 0.1% of the slide
  (an add-in helper stub) is skipped. An embedded Excel worksheet
  (`progId` `Excel.Sheet.*`) whose workbook names an `oleSize` range
  becomes a `table` element instead (with `source_shape_id`): the active
  sheet's cells in that range only, without hidden rows, hidden columns
  and empty rows. Cells outside `oleSize` are never read: they are not on
  the slide. Values are the cached results (`data_only`), unformatted.

## Output

Writes one shard per given slide to `work/<doc>/shards/page{N}.text.json`
(body) and `work/<doc>/shards/page{N}.image.json` (images) — the same
shard schema `pdf-triage`'s pipeline uses, so `merge.py`/`assemble.py`/
`gates.py` need no pptx-specific handling. See `lib/elements.py`.
