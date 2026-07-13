---
name: image-triage
description: Classify a standalone image document (png/jpg/jpeg/webp/tiff) as a single page and record its extraction tier (always "ocr", escalating to "vision" as needed) and loop size. Use this first, before any extraction, to size the elastic loop for the document.
---

# Image Triage

The image sibling of `pdf-triage`, not of `html-triage`. An image has no
text layer at all — it *is* the pixel ground-truth — so it does **not**
follow the digital-native (`docx`/`xlsx`/`html`) pattern of tier `text` and
no escalation rung. Instead it starts on the same `ocr`→`vision` ladder a
scanned PDF page uses, just always starting at `ocr` rather than being
decided by a text-layer check. This plugin's convention: **one image file is
one page**, the same fixed rule `html-triage` uses for "one page", but with
a different starting tier.

Because there *is* a rendered page image for this format (the image itself,
normalized to PNG by `render-pages`), grading is **vision-mode** (a `grader`
subagent comparing the assembled output against pixels) — the same as
`pdf`/`pptx`, not the text-mode script used for `docx`/`xlsx`/`html`.

## When to use

Always run this first for a new image document.

## How

```bash
uv run --project "${CLAUDE_PLUGIN_ROOT}" python \
  "${CLAUDE_PLUGIN_ROOT}/skills/image-triage/scripts/triage.py" --doc <doc-name>
```

Reads `input/<doc-name>.{png,jpg,jpeg,webp,tiff}`, writes
`work/<doc-name>/triage.json`, and prints the same JSON to stdout.

## Output schema

```json
{
  "doc": "diagram",
  "page_count": 1,
  "pages": [
    {"page_number": 1, "tier": "ocr", "image_count": 1, "reason": "raster image, no text layer — OCR then escalate to vision"}
  ],
  "loop_size": "tight"
}
```

- `tier`: always `ocr` — triage never assigns `vision` directly, same rule
  as `pdf-triage`; escalation only happens when the `ocr` extractor itself
  reports low confidence or the retry ladder forces it.
- `image_count`: always `1` — the whole file is the one image asset that
  `extract-images` will save.
- `loop_size`: always `tight` — an `ocr`-tier page always carries escalation
  risk.
- No `body_size` — that field is a running-text font-size measurement
  `extract-text` uses for pdf/pptx; images never go through `extract-text`.

## Notes for the calling agent

- This is a pure classification pass — it does not extract any content.
- Unlike `html-triage`, this format does route through the `ocr`/`vision`
  escalation machinery in `commands/extract.md`'s Decide step — treat it
  like `pdf`/`pptx` there, not like `docx`/`xlsx`/`html`.
