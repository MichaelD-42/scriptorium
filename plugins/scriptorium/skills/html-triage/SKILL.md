---
name: html-triage
description: Classify an HTML document as a single logical "page" and record its extraction tier (always "text", HTML is digital-native) and loop size. Use this first, before any extraction, to size the elastic loop for the document.
---

# HTML Triage

The html sibling of `docx-triage`/`xlsx-triage`. Unlike docx (which at
least has Heading-1 sections to split on), HTML has **no page concept at
all** a parser can see — this plugin's convention: **the whole file is one
page**. There is no per-file segmentation decision to make or record; a
document's `page_count` is always `1`.

Because there's no rendered page image for this format, grading is
**text-mode** (a deterministic structural script, not a `grader` subagent
comparing against pixels) — see `grade-output/text-rubric.md`. There is
also no `ocr`/`vision` rung: extraction is already digital-native and
deterministic, so a failed grade on an HTML page has nowhere higher to
escalate to (see `commands/extract.md`'s Decide step).

## When to use

Always run this first for a new HTML document.

## How

```bash
uv run --project "${CLAUDE_PLUGIN_ROOT}" python \
  "${CLAUDE_PLUGIN_ROOT}/skills/html-triage/scripts/triage.py" --doc <doc-name>
```

Reads `input/<doc-name>.html`, writes `work/<doc-name>/triage.json`, and
prints the same JSON to stdout.

## Output schema

```json
{
  "doc": "webpage",
  "page_count": 1,
  "pages": [
    {"page_number": 1, "tier": "text", "has_table": true, "image_count": 1, "reason": "native HTML content (digital-native, no OCR needed)"}
  ],
  "loop_size": "tight"
}
```

- `tier`: always `text` — there is no `ocr` or `vision` rung for html.
- `image_count`: only counts **saveable** images (`data:` URIs and local
  file references) — see `lib/html_pages.saveable_images`. Remote
  (`http(s)://`) `<img>` sources are not fetched and are not counted, a
  documented gap like xlsx's missing charts.
- `loop_size`: `tight` if the page has a table or a saveable image (more
  structural surface for something to go wrong); `loose` otherwise.

## Notes for the calling agent

- This is a pure classification pass — it does not extract any content.
- `html-extract` walks the same document independently via
  `lib/html_pages.py`; since there's only ever one page, there's no split
  boundary that could drift between triage and extraction the way there is
  for docx.
