---
name: ocr-page
description: OCR pages that triage classified as tier "ocr" (no usable text layer), using a pluggable local OCR backend. Use for scanned or image-only pages before falling back to Claude vision.
---

# OCR Page (Tier 2)

Local, deterministic-ish OCR. This is the middle rung of the elastic
escalation ladder: cheaper than vision, but it reports its own confidence so
the calling agent (the `extractor` role) knows when to escalate further.

**Pages must already be rendered** (`render-pages` first) — this skill reads
the PNGs, it does not touch the PDF directly.

## How

```bash
uv run --project "${CLAUDE_PLUGIN_ROOT}" python \
  "${CLAUDE_PLUGIN_ROOT}/skills/ocr-page/scripts/ocr.py" --doc <doc-name> --pages 5 [--backend tesseract] [--lang eng] [--tessdata-dir <path>]
```

`--lang` is a tesseract language code, or several joined with `+` (e.g.
`eng+deu`) — pass through whatever `setup-environment/ensure_language.py`
reported for this document. Defaults to `eng`. `--tessdata-dir` is that
same script's `tessdata_prefix` field — only set (non-`null`) when a
language pack had to be downloaded straight into a user-writable fallback
dir instead of the system tessdata dir (typically Windows without admin
rights); omit it otherwise.

## Backends

- `tesseract` (default, local, no API): runs `pytesseract.image_to_data`,
  groups words into paragraph blocks, and computes a 0-1 page confidence
  from Tesseract's own per-word confidence scores.

Only `tesseract` is implemented as an OCR backend. Tier 3 (Claude vision) is
**not** a script — it is the calling agent itself reading the rendered PNG
(with the Read tool, which supports images) and transcribing it, because
that step needs genuine visual judgment a deterministic script can't
provide. Escalate to vision when this skill reports `confidence` below your
threshold (default 0.5) or near-empty text on a page triage expected to
have content.

Once you've transcribed a page by vision, land it in the shard schema with:

```bash
echo '[{"type": "paragraph", "text": "..."}]' | uv run --project "${CLAUDE_PLUGIN_ROOT}" python \
  "${CLAUDE_PLUGIN_ROOT}/skills/ocr-page/scripts/write_vision_page.py" --doc <doc-name> --page 5
```

This writes a `page{N}.vision.json` shard (no `ocr_confidence` — that field
is specific to the tesseract backend's numeric score).

## Output

Writes one shard per given page to `work/<doc>/shards/page{N}.ocr.json`
(includes an `ocr_confidence` field 0-1) — never touches another page's or
another tier's shard, so parallel `extractor` subagents over different page
batches never race.
