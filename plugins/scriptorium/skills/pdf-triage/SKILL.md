---
name: pdf-triage
description: Analyze a PDF's pages to classify each page's extraction tier (text / ocr / vision) and the document's overall loop size (tight vs loose). Use this first, before any extraction, to size the elastic loop for the document.
---

# PDF Triage

Classifies every page of a PDF so the orchestrator knows how much effort to
spend before it spends it — this is the Elastic Loop "context grounds the
loop" step: cheap, deterministic, and it runs once per document (per attempt).

## When to use

Always run this first for a new document, and again after an escalation to
re-check only the pages that were bumped a tier (pass `--pages`).

## How

```bash
uv run --project "${CLAUDE_PLUGIN_ROOT}" python \
  "${CLAUDE_PLUGIN_ROOT}/skills/pdf-triage/scripts/triage.py" --doc <doc-name>
```

Reads `input/<doc-name>.pdf`, writes `work/<doc-name>/triage.json`, and prints
the same JSON to stdout.

## Output schema

```json
{
  "doc": "sample",
  "page_count": 5,
  "pages": [
    {"page_number": 1, "tier": "text", "text_ratio": 0.92, "image_count": 1, "reason": "native text layer present"},
    {"page_number": 5, "tier": "ocr",  "text_ratio": 0.0,  "image_count": 1, "reason": "no extractable text, likely scanned"}
  ],
  "loop_size": "tight",
  "body_size": 11.0
}
```

- `tier`: `text` (Tier 1, native extraction), `ocr` (Tier 2, needs OCR/vision).
  Triage never assigns `vision` directly — that only happens when Tier 2
  (`ocr-extractor`) itself reports low confidence and escalates.
- `loop_size`: `loose` if every page is `text` (low risk, let extractors run
  to completion unsupervised); `tight` if any page needs escalation (grade
  the result closely, expect retries).
- `body_size`: the document's dominant running-text font size, measured once
  across every page (character-weighted, so a page with just a heading and
  a short caption doesn't skew it). Pass straight through to every
  `extract-text` call for this document as `--body-size` — a single page's
  own text is often too sparse to reliably tell a heading from body text on
  its own.

## Notes for the calling agent

- This is a pure classification pass — it does not extract any content.
- Treat `reason` as a legibility artifact: surface it in your own reasoning
  and in the final grade report, don't just discard it.
