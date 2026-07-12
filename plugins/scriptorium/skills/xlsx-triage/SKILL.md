---
name: xlsx-triage
description: Classify each sheet of a workbook into an extraction tier (always "text", xlsx is digital-native) and the document's overall loop size. Use this first, before any extraction, to size the elastic loop for the document.
---

# XLSX Triage

The xlsx sibling of `pptx-triage`/`docx-triage`. Unlike docx, a workbook's
**sheets are a real source-file property** — `workbook.sheetnames` is a
genuine independent oracle, the same way a pptx's slide count is (see
`lib/paths.true_page_count`). This plugin's convention: **one sheet = one
page**, in workbook order.

Like the other digital-native formats, there is no `ocr` rung, and grading
is **text-mode** (a deterministic script, not a `grader` subagent looking
at pixels) — see `grade-output/text-rubric.md`. There is also no `vision`
rung: there's no rendered page image to escalate to (see
`commands/extract.md`'s Decide step for what a failed grade does instead).

## How

```bash
uv run --project "${CLAUDE_PLUGIN_ROOT}" python \
  "${CLAUDE_PLUGIN_ROOT}/skills/xlsx-triage/scripts/triage.py" --doc <doc-name>
```

Reads `input/<doc-name>.xlsx`, writes `work/<doc-name>/triage.json`, and
prints the same JSON to stdout.

## Output schema

```json
{
  "doc": "budget",
  "page_count": 2,
  "pages": [
    {"page_number": 1, "tier": "text", "has_table": true, "image_count": 0, "has_chart": false, "reason": "native worksheet content (digital-native, no OCR needed)"},
    {"page_number": 2, "tier": "text", "has_table": true, "image_count": 1, "has_chart": true, "reason": "native worksheet content (digital-native, no OCR needed)"}
  ],
  "loop_size": "tight"
}
```

- `tier`: always `text` — there is no `ocr`/`vision` rung for xlsx.
- `has_table`: whether the sheet has any non-empty cell at all (an empty
  sheet has no table to extract).
- `has_chart`: openpyxl can detect a chart's presence but not render it to
  an image (no rendering engine) — same scoped-out limitation as pptx
  charts. A sheet with a chart is flagged `loop_size: "tight"` so the
  text-mode grader looks closely, but the chart itself won't become an
  `image` element. See `xlsx-extract/SKILL.md`.
- `loop_size`: `tight` if any sheet has an embedded image or a chart;
  `loose` otherwise.

## Notes for the calling agent

- This is a pure classification pass — it does not extract any content.
- `page_count` here **is** an independent oracle (unlike docx) — it comes
  straight from `workbook.sheetnames`, not from any pipeline decision.
