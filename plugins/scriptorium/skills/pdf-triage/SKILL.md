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
    "frame_drawings": [
      {"bbox": [24.0, 24.0, 588.0, 768.0], "page_count": 9}
    ],
    "image_xrefs": [4]
  },
  "furniture_text": "Doc No. SYN-FUR-0001\nRev. B\npage 1 (9)"
}
```

A page that was identified as a printed table-of-contents page (see
`toc.json` below) additionally carries `"role": "toc"` in its `pages[]`
entry. Every other page's entry has no `role` key at all — the default is
"body", never written out explicitly.

## `toc.json`

Also writes `work/<doc-name>/toc.json`:

```json
{
  "doc": "furniture_sample",
  "entries": [
    {"number": "1", "title": "Introduction", "page": 4, "level": 1},
    {"number": "2.1.1", "title": "Data Processing Pipeline", "page": 6, "level": 3}
  ]
}
```

`entries` comes from `lib/toc.py`'s `detect_toc()`, tried in this order:

1. **PDF outline** (`document.get_toc()`) — used directly if the document
   has one. A leading `"<number> "` in the outline title is split into
   `number`; otherwise `number` is `null`. `level` is the outline's own
   level. No page in `pages[]` is marked `role: "toc"` for this path —
   outline entries don't correspond to a rendered TOC page.
2. **Printed TOC page detection** (fallback) — pages near the front of the
   document with enough dot-leader lines ("Title .......... 4") are treated
   as a printed TOC and parsed, handling both "number and title on one
   line" and "number alone on one line, title+leader+page on the next".
   `level` is the entry number's dot-depth (`"1"` → 1, `"1.2"` → 2, ...) —
   a later heading-classification step may assign a different level from
   actual font size; this one only reads the printed number. Every page in
   the detected contiguous run is marked `role: "toc"` in `triage.json`.

Empty `entries: []` and no `role` keys anywhere when there's no outline and
no printed TOC found.

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
  - `frame_drawings` (Task A5b): single vector drawings (per PyMuPDF's
    `page.get_drawings()`) covering more than 60% of the page area that
    repeat at the same bbox (within 2pt) on at least 50% of pages — the
    repetition-based counterpart to `frame_tables`, for exactly the case
    `frame_tables` misses: a plain unruled `c.rect()` border, invisible to
    pdfplumber's table heuristics. `extract-images`/`extract-text` use this
    (not size alone) to tell a real page-frame border apart from a
    genuinely large one-off figure before clustering a page's vector
    drawings into figure regions — see `extract-images`'s SKILL.md.
  - `image_xrefs`: PyMuPDF image xrefs present on at least 50% of pages —
    typically a repeated logo.
- `furniture_text`: the verbatim (unmasked) text of the matched furniture
  lines on the document's first page, top-to-bottom, newline-joined. `null`
  if no line furniture was detected.

## Notes for the calling agent

- This is a pure classification pass — it does not extract any content.
- Treat `reason` as a legibility artifact: surface it in your own reasoning
  and in the final grade report, don't just discard it.
