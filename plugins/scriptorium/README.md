# scriptorium

Elastic-loop document extraction team. See the repo root `README.md` for
setup and how to run the example.

For the full architecture — the two-level agent tree, the queue loop,
context-rot prevention, and the escalation ladder — see
[`docs/architecture.md`](../../docs/architecture.md). For the tools,
scripts, and file/shard schemas that implement it, see
[`docs/tooling.md`](../../docs/tooling.md).

In short: an `orchestrator` (this plugin's `/scriptorium:extract` command)
triages a document page-by-page, then spawns `extractor` and `grader`
subagents in parallel over page batches — cheap deterministic extraction
first, with local OCR and Claude vision escalated to only where needed, and
an independent grader deciding pass/retry/escalate. Extraction is
format-agnostic at the agent level; only the *tools* are format-specific.
PDF, PowerPoint (`.pptx`), Word (`.docx`), Excel (`.xlsx`), HTML (`.html`),
and standalone images (`.png`/`.jpg`/`.jpeg`/`.webp`/`.tiff`) are
implemented today.

## 0.6.1

- **Fix**: a blank PDF page, or one with only the header and footer, sent
  the document to a human (`no_empty_pages`). Triage now keeps a fully
  blank page off OCR, and `extract-text` marks such pages
  `skipped: "blank"`.
- **Fix**: a content issue on a text-layer PDF page now goes to `vision`,
  not `ocr`. Tesseract writes only paragraphs, so the retry lost the
  page's tables and headings.
- **Fix**: `write_vision_page.py` refuses elements `assemble.py` cannot
  render (e.g. a heading without `level` crashed assembly), and the
  extractor prompt lists the heading, list and table shapes.
- **Fix**: `write_grade_shard.py` refuses a score outside 0-1; a
  percentage would have passed the document.
- **Fix**: a failed document-level gate goes to a human at once with its
  detail, instead of burning retries and ending as "still failing after N
  attempts". A low OCR-confidence page is retried at `vision`.
- `init` with a different `--format` updates open documents and warns
  about finished ones instead of silently ignoring the flag.

## 0.6.0

- **No skills**: the plugin registers no Claude Code skills, so nothing
  of it shows up in the skill list of every session. `skills/` is now
  `tools/`; each folder keeps its `scripts/` and has a `README.md` in
  place of `SKILL.md`. `/scriptorium:extract` is still the one entry
  point. The `extractor` and `grader` prompts list the exact commands
  they run and no longer preload about 40 KB and 14 KB of skill text at
  every spawn; they read a tool's README only when they need it.

## 0.5.2

- **Fix (data loss)**: an input named `...pdf` or `..pdf` made
  `state.py init` delete the project folder or all of `work/` and
  `output/`. Such names are now skipped with a warning.
- **Fix (macOS)**: an input with an upper-case extension (`Report.PDF`)
  is queued again; 0.5.1 skipped it.
- `init` hashes inputs in chunks instead of reading each file into memory.

## 0.5.1

- **Run report**: when the queue is empty, `output/report.html` sums up the
  run (documents, passed, needs a human, pages, attempts, extraction time)
  and shows each document's attempts with durations and escalation
  reasons, failed gates, warnings and per-page grades. Attempt timing is
  recorded in `runs/state.json`.
- **Security**: an HTML input's `<img>` is read only from inside the HTML
  file's own folder and only if it is an image; before, any local file
  could be copied into the output.
- **Reruns start clean**: a new or changed input file deletes the
  document's old `work/` and `output/`, so old OCR/vision text can no
  longer override the new extraction, and a replaced file is queued again.
- **Fixes**: repeated heading text at two levels no longer fails a correct
  docx/html document; parallel graders converting one pptx no longer share
  a LibreOffice profile or read a half-written PDF; with two inputs of one
  name the queue uses the file the scripts read.
- **Cleanup**: one grouping helper in PDF triage (identical output), four
  unused functions removed.

## 0.5.0

- **Work-sized batches**: the orchestrator runs the deterministic extract
  scripts itself and spawns an extractor only for pages that need judgment
  (OCR/vision bodies, undescribed images). Batches are sized by estimated
  turns against each agent's `maxTurns` instead of a fixed `--batch-size`
  (now an optional cap); grader batches are weighted by figure count.
- **Scripted queue** (`queue-state`): `state.py` owns `runs/state.json` and
  the pass / retry / needs-human rules; a failure with nothing page-level to
  retry goes to a human instead of burning attempts. Grade shards keep the
  grader's `--reason`, which the next extractor receives verbatim.
- **Stricter pass rule**: any page tagged with a content issue (dropped,
  hallucinated, duplicated or misordered text, wrong heading level, broken
  table) fails the document, whatever the average score.
- **Preflight in triage**: unreadable, password-protected, empty or damaged
  inputs (every format) and multi-page TIFFs are rejected with a one-line
  reason. A PDF page with a garbled text layer or a stamped scan starts at
  OCR.
- **Fixes**: a header line on a one-page PDF is no longer dropped as page
  furniture. PDF triage is up to 2.4x faster and prints a compact summary.
- **Docs and tests**: a Structurizr C4 model (`docs/c4/workspace.dsl`);
  acceptance tests that drive the whole queue loop; coverage now measures
  the scripts tests run as subprocesses (95%).

## 0.4.5

- **Faster PDF extraction**: table detection no longer reopens the PDF for
  every page, which made `extract-text` and `extract-images` quadratic in
  page count. On a 207-page PDF, `extract_text` drops from 14 s to 3.4 s
  and `extract_images` from 5.2 s to 1.6 s, with identical output.

## 0.4.4

Line breaks the R28 rule still missed or added, from the golden-document
run of 2026-10-06 (follow-up R29):

- **Bold label lines**: a whole bold line after a plain line (or the
  reverse) is its own paragraph ("… 0,6 V" / "Verification method").
- **List-item lines**: a line that starts a list item ("1. …", "- …",
  "– …") is a new paragraph after a line that ends a sentence (also before
  a closing bracket: "etc.)") or leaves room for the marker.
- **Inline bullets**: an item printed inline with its bullet and no hanging
  indent no longer absorbs the paragraph after the list.
- **Line-end hyphens**: "10-" + "second" joins as "10-second", not
  "10- second".
- **Paragraphs split into blocks**: a paragraph that PyMuPDF splits into one
  block per line is joined again when the line before is full and the gap
  is a line gap.
- **List indent**: a run of list items is indented relative to its first
  item, so a list that starts at level 3 is no longer a Markdown code block.

## 0.4.3

- **Explicit line breaks** (R28): a line the source broke on purpose (it
  ends a sentence, or is a short line, and the next word would have fit)
  ends its paragraph, instead of being joined like wrapped text.
- **Taller bullet glyphs** (R28): a bullet drawn in a larger font than its
  text is paired with the text by their common baseline.

## 0.4.2

Second round of fixes from the golden-document run (follow-ups R23–R27):

- **Label/value rows**: a block made of two-column header rows ("HWC
  requirement | REQ …", "ASIL Value: | To Be Selected") and a body is split
  into one paragraph per row, so a downstream tagger finds the label's
  value.
- **Stray marks**: a non-Latin combining mark after Latin text (a font's
  space-like glyph mapped to U+0BD7) is dropped or becomes a space.
- **Table captions**: a caption line that shares a text block with the
  table's header cells is kept.
- **List continuation**: a block that opens with the previous bullet's
  last line and then starts a new bullet is read as list content.
- **Figure text**: `render_region.py` renders one figure at a high dpi for
  reading small labels, and `describe_image.py` refuses a `--figure-text`
  that holds a legibility note instead of a transcription.

## 0.4.1

Fixes from the first golden-document run (follow-ups R18–R22):

- **Glyph decoding**: Symbol-font text ("£" for "≤", "W" for "Ω") and the
  Calibri "ti"/"tt"/"ft" ligature glyphs are decoded in body text, table
  cells, captions, figure text and the TOC match. Table cell text is read
  from PyMuPDF by visual line, so subscripts and footnote markers stay in
  place ("Us (V)", "LW 1)").
- **Invisible drawings**: a white, unstroked rectangle behind body text is
  no longer taken for a figure (`invisible_drawing` excluded region).
- **Open table rows**: a continued table keeps the first row on its new
  page when that row has no top rule.
- **Tables across page breaks** are joined into one table, a repeated
  header is dropped, and a join can span several pages.
- **Captions and labels**: a caption that wraps keeps its second line, and
  short labels just outside a figure go into its figure text and crop.

## 0.4.0

PDF extraction quality, for documents with running headers/footers, a
printed or outline table of contents, and figures on otherwise text-heavy
pages:

- **Page furniture** (running headers/footers, doc-number/revision/page
  blocks, a repeated frame border or logo) is detected once per document
  and removed from extracted text, tables, and images.
- **Headings** are classified from the document's table of contents
  (outline or printed) when one exists, instead of font-size heuristics
  alone; levels are no longer capped at 3.
- **List items** (bulleted and enumerated) are recognized as their own
  element type, with nesting level and cross-page-break paragraph joins.
- **Figures** are detected at the region level — a diagram or chart on a
  page that also has body text — instead of only whole-page vector
  renders; captions are read directly off the page, and a new
  `describe_image.py` records an agent's description, data table, and
  mermaid diagram separately from that caption.
- **New output format**: `md-tree` splits a document into nested folders
  and files with stable per-heading anchors, for a downstream per-section
  consumer.
- **New grading checks**: furniture actually absent from the output, every
  TOC heading present at the right page and level, and every figure
  captioned or described — the first two send a document straight to
  human review on failure, since the underlying data is deterministic and
  a retry can't change it.
