---
name: docx-triage
description: Split a Word document into logical "pages" (Heading-1 sections) and classify the extraction tier (always "text", docx is digital-native) and loop size. Use this first, before any extraction, to size the elastic loop for the document.
---

# DOCX Triage

The docx sibling of `pdf-triage`/`pptx-triage`. Word has no page concept a
parser can see — pagination is computed at render time by Word itself and
isn't recoverable from the file. This plugin's convention instead: a
**page is a Heading-1 section** (content before the first Heading-1, if
any, is page 1's front matter; a document with no Heading-1 at all is a
single page). That split happens once here via `lib/docx_pages.split_pages()`
and is recorded in `triage.json` — **it is the single source of truth for
what a docx "page" is**; `docx-extract` calls the same function so the
segmentation can never drift between triage and extraction.

Because there's no rendered page image for this format, grading is
**text-mode** (a deterministic structural script, not a `grader` subagent
comparing against pixels) — see `grade-output/text-rubric.md`. There is
also no `ocr`/`vision` rung: extraction is already digital-native and
deterministic, so a failed grade on a docx page has nowhere higher to
escalate to (see `commands/extract.md`'s Decide step).

## When to use

Always run this first for a new docx document. Unlike pdf/pptx, there is
no per-page re-triage on retry — see the note above about there being no
higher tier to re-triage into.

## How

```bash
uv run --project "${CLAUDE_PLUGIN_ROOT}" python \
  "${CLAUDE_PLUGIN_ROOT}/skills/docx-triage/scripts/triage.py" --doc <doc-name>
```

Reads `input/<doc-name>.docx`, writes `work/<doc-name>/triage.json`, and
prints the same JSON to stdout.

## Output schema

```json
{
  "doc": "spec",
  "page_count": 3,
  "pages": [
    {"page_number": 1, "tier": "text", "has_table": false, "image_count": 0, "reason": "native docx content (digital-native, no OCR needed)"},
    {"page_number": 2, "tier": "text", "has_table": true, "image_count": 1, "reason": "native docx content (digital-native, no OCR needed)"}
  ],
  "loop_size": "tight"
}
```

- `tier`: always `text` — there is no `ocr` or `vision` rung for docx.
- `loop_size`: `tight` if any page has a table or an inline image (more
  structural surface for something to go wrong); `loose` otherwise.
- `page_count` here is **not** an independent oracle the way a PDF's page
  count or a pptx's slide count is — it's this pipeline's own Heading-1
  segmentation. `lib/paths.true_page_count()` reads it from here for docx
  specifically because there is nothing else to read it from.

## Notes for the calling agent

- This is a pure classification pass — it does not extract any content.
- `docx-extract` must use the exact same page boundaries; it gets them by
  calling `lib/docx_pages.split_pages()` itself (deterministic and cheap
  enough to recompute per call, not by re-reading this file).
