# PPTX Triage

The pptx sibling of `pdf-triage`. Slides are digital-native — there is no
scanned-page case — so every slide is tier `text` and there is no `ocr`
rung. What still varies is how much visual content a slide carries: a
slide that's mostly a diagram, chart, or full-bleed photo is more likely to
get escalated to `vision` later if `pptx-extract`'s text-frame extraction
turns out to have missed something the grader can see. Triage flags that
risk up front via `loop_size`, exactly like `pdf-triage` does for scanned
pages.

## When to use

Always run this first for a new pptx document, and again after an
escalation to re-check only the slides that were bumped a tier (pass
`--pages`).

## How

```bash
uv run --project "${CLAUDE_PLUGIN_ROOT}" python \
  "${CLAUDE_PLUGIN_ROOT}/tools/pptx-triage/scripts/triage.py" --doc <doc-name>
```

Reads `input/<doc-name>.pptx`, writes `work/<doc-name>/triage.json`, and
prints the same JSON to stdout.

## Output schema

```json
{
  "doc": "deck",
  "page_count": 8,
  "pages": [
    {
      "page_number": 1,
      "tier": "text",
      "image_count": 0,
      "figure_shapes": [],
      "reason": "native slide content (pptx is digital-native, no OCR needed)"
    },
    {
      "page_number": 6,
      "tier": "text",
      "image_count": 1,
      "figure_shapes": [
        {
          "shape_id": 23,
          "kind": "group",
          "bbox_emu": [9696714, 677264, 11200000, 2100000],
          "groups": []
        }
      ],
      "reason": "native slide content (pptx is digital-native, no OCR needed)"
    }
  ],
  "loop_size": "tight",
  "furniture": {
    "line_patterns": [{ "masked": "Footerline", "page_count": 8 }],
    "...": "..."
  }
}
```

- `figure_shapes`: the slide's figure census (`lib/pptx_shapes.py`'s
  `figure_shapes`), read from the shape tree on its own walk, apart from
  `pptx-extract`: pictures at any depth showing on at least 0.5% of the
  slide after their crop (`pic`), embedded objects, charts and SmartArt
  (`ole`, `chart`, `diagram`), top-level groups that draw a figure
  (`group`), and picture-filled shapes (`fill`). Hidden shapes and frames
  under 0.1% of the slide are left out. `bbox_emu` is in slide space;
  `groups` lists the ids of the groups that contain the shape.
  `gates.py`'s `pptx_figures_covered` checks that each has an element.
- `image_count`: the number of `figure_shapes`.

- `tier`: always `text` for pptx — extraction is native (`python-pptx`),
  never OCR. `vision` only ever gets assigned by the orchestrator after a
  failed grade, exactly as for a PDF's escalation ladder.
- `loop_size`: `tight` if any slide has a figure (grade
  it closely, expect a possible escalation to `vision`); `loose` if every
  slide is text/tables only.
- `furniture`: the same shape `pdf-triage` writes, with one
  `line_patterns` entry (`masked`, `page_count`) per footer, slide-number
  or date placeholder line that has letters. `pptx-extract` skips these
  placeholders; the patterns let `merge.py` strip them from a vision
  transcription and `furniture_absent` catch them in the output.
- No `body_size` field — pptx headings come from the slide's title
  placeholder, not a font-size ratio, so there's nothing to pass through to
  `pptx-extract`.

## Notes for the calling agent

- This is a pure classification pass — it does not extract any content.
- Treat `reason` as a legibility artifact, same as `pdf-triage`.
