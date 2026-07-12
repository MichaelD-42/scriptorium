---
name: pptx-triage
description: Analyze a PowerPoint file's slides to classify each slide's extraction tier (always "text", pptx is digital-native) and the document's overall loop size (tight vs loose). Use this first, before any extraction, to size the elastic loop for the document.
---

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
  "${CLAUDE_PLUGIN_ROOT}/skills/pptx-triage/scripts/triage.py" --doc <doc-name>
```

Reads `input/<doc-name>.pptx`, writes `work/<doc-name>/triage.json`, and
prints the same JSON to stdout.

## Output schema

```json
{
  "doc": "deck",
  "page_count": 8,
  "pages": [
    {"page_number": 1, "tier": "text", "image_count": 0, "reason": "native slide content (pptx is digital-native, no OCR needed)"},
    {"page_number": 6, "tier": "text", "image_count": 2, "reason": "native slide content (pptx is digital-native, no OCR needed)"}
  ],
  "loop_size": "tight"
}
```

- `tier`: always `text` for pptx — extraction is native (`python-pptx`),
  never OCR. `vision` only ever gets assigned by the orchestrator after a
  failed grade, exactly as for a PDF's escalation ladder.
- `loop_size`: `tight` if any slide has an embedded picture or chart (grade
  it closely, expect a possible escalation to `vision`); `loose` if every
  slide is text/tables only.
- No `body_size` field — pptx headings come from the slide's title
  placeholder, not a font-size ratio, so there's nothing to pass through to
  `pptx-extract`.

## Notes for the calling agent

- This is a pure classification pass — it does not extract any content.
- Treat `reason` as a legibility artifact, same as `pdf-triage`.
