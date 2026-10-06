# scriptorium

Elastic-loop document extraction team. See the repo root `README.md` for
setup and how to run the example.

For the full architecture — the two-level agent tree, the queue loop,
context-rot prevention, and the escalation ladder — see
[`docs/architecture.md`](../../docs/architecture.md). For the skills,
scripts, and file/shard schemas that implement it, see
[`docs/tooling.md`](../../docs/tooling.md).

In short: an `orchestrator` (this plugin's `/scriptorium:extract` command)
triages a document page-by-page, then spawns `extractor` and `grader`
subagents in parallel over page batches — cheap deterministic extraction
first, with local OCR and Claude vision escalated to only where needed, and
an independent grader deciding pass/retry/escalate. Extraction is
format-agnostic at the agent level; only the *skills* are format-specific.
PDF, PowerPoint (`.pptx`), Word (`.docx`), Excel (`.xlsx`), HTML (`.html`),
and standalone images (`.png`/`.jpg`/`.jpeg`/`.webp`/`.tiff`) are
implemented today.

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
