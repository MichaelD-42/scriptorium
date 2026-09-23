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
  "body_size": 11.0,
  "furniture": {
    "line_patterns": [
      {"masked": "Doc No. SYN-FUR-#", "edge": "bottom", "y_min": 0.9159, "y_max": 0.9298, "page_count": 9}
    ],
    "frame_tables": [
      {"bbox": [24.0, 24.0, 588.0, 768.0], "page_count": 9}
    ],
    "image_xrefs": [4]
  },
  "furniture_text": "Doc No. SYN-FUR-0001\nRev. B\npage 1 (9)"
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

- `furniture`: page furniture detected once, document-wide (not yet
  removed — that is a separate, later step).
  - `line_patterns`: text lines whose digit-masked form (`re.sub(r"\d+",
    "#", line)`) repeats in the top or bottom 12% of the page on at least
    60% of pages — running headers/footers, doc-number/revision/page-number
    lines, etc. `y_min`/`y_max` are that line's observed y-position range,
    as a fraction of page height.
  - `frame_tables`: tables (per pdfplumber's `find_tables()`) covering more
    than 60% of the page area that repeat at the same bbox (within 2pt) on
    at least 50% of pages — a ruled page-frame border, if pdfplumber's
    table heuristics happen to pick it up. A plain unruled rectangle border
    is legitimately not detected as a table at all, so this is often `[]`.
  - `image_xrefs`: PyMuPDF image xrefs present on at least 50% of pages —
    typically a repeated logo.
- `furniture_text`: the verbatim (unmasked) text of the matched furniture
  lines on the document's first page, top-to-bottom, newline-joined. `null`
  if no line furniture was detected.

## Notes for the calling agent

- This is a pure classification pass — it does not extract any content.
- Treat `reason` as a legibility artifact: surface it in your own reasoning
  and in the final grade report, don't just discard it.
