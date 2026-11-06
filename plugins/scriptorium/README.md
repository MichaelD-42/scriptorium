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

## 0.7.1

Fixes from a repository audit.

- **HTML text**: inline markup no longer glues words together
  (`Hello <b>world</b>` came out as `Helloworld`), a `<br>` separates the
  words around it, and text held directly in a `<div>`, `<span>` or the
  `<body>` is extracted instead of dropped.
- **Text-mode grader** (docx, html): `dropped_text` now also fires when a
  word of the source is missing from the output, with the words read
  straight from the file rather than through the extractor's own block
  walk, so it catches what that walk skips. The shard's `reason` names the
  missing words. A docx whose text boxes were silently lost now goes to a
  human instead of passing.
- **docx images in tables** are extracted and counted (they were dropped
  and the grader did not see them either).
- **pptx groups**: pictures and text inside a group shape, and a filled
  picture placeholder, are extracted. A grouped picture used to be tagged
  `missing_image` on every attempt and end as needs-human.
- **Upper-case extensions** for docx, pptx, xlsx and html (`Report.DOCX`)
  are triaged and extracted; triage rejected them as unreadable.
- **`describe_image.py --data-table`** refuses anything but a JSON array
  of rows; a malformed table crashed `assemble.py` for the whole document.
- **Image-only retries** keep the page's body: an escalation for a figure
  problem (`missing_image`, `bad_caption`, `bad_mermaid`,
  `figures_complete`) records `body: false`, and the extractor redoes only
  the images instead of transcribing an `ocr`/`vision` page again.
- **HTML output** loads a pinned Mermaid (10.9.1) instead of the latest
  10.x.
- **Internal**: the body-size measure lives once, in `lib/fonts.py`
  (pdf-triage and extract-text each had a copy).

## 0.7.0

- **Graders tag, scripts score**: `write_grade_shard.py` no longer takes
  `--score`; a page's score is 1.0 minus 0.3 per distinct tag
  (`lib/grades.py`), the rule `text_mode_grade.py` already used. A grader
  can no longer soften a defect with a high number.
- **Blocking tags**: `missing_image` and the new `split_paragraph` now fail
  the document whatever the average, like the content tags.
  `grade-report.json`'s `content_issue_pages` is now `blocking_issue_pages`.
- **Paragraphs across pages**: an `ocr`/`vision` page has no bbox, so its
  paragraphs never joined across a page break. They now join when the next
  page continues in lowercase. The rubric grades a paragraph left split
  (`split_paragraph`, goes to a human: the join is a script rule) and no
  longer grades visual layout; a layout table is fine as long as its text
  is complete and in order.
- **`text_layer_coverage` gate** (pdf): every word of a `text`-tier page's
  text layer must be in the output. Dropped text on such a page is now
  found by a script, not by the grader; the page goes to `vision` with the
  missing words as reason.
- **Bitmap `figure_text` from Tesseract**: `extract_images.py --ocr-lang`
  keeps the lines Tesseract reads with confidence 80+ on every word
  (`figure_text_source: "ocr"`); the extractor may correct them.
- **`--no-describe`**: images get no description, mermaid or data table,
  so a text-layer document needs no extractor agent at all.
- **Pre-analysis** (pdf): before extraction, triage records the detection
  scopes (scans, bitmaps, data tables, furniture, TOC, text languages) and
  quirks, each with its measure: `layout_table` (now read as headings and
  paragraphs, not a table), `heading_in_block` (an accent heading sharing a
  block with its body is split off), `side_margin_text`,
  `garbled_text_layer`, `text_language` (passed to OCR, so a German scan or
  screenshot is no longer read as English). The KSEM guide's pages now come
  out of the scripts with tables 1.0 and headings 0.83 in the extraction
  eval, up from 0.0 and 0.17.
- **Findings** (`--findings <dir>`): a passed PDF's pages that failed at a
  script tier and passed at vision are saved as suggested corrections
  (`findings.py`), and the extraction eval scores every one of them.
- **Evals** (`evals/`, not run in CI): a committed grader calibration set
  (one synthetic document, nine injected defects, `/eval-grader`) and an
  LLM-free extraction eval against reference Markdown.
- **Output formats**: `md-tree` takes any `--split-depth` 1-6 (one file
  per chapter, section, subsection, ...; folders nest), with depth 2 byte
  for byte as before. New `jsonl`: one JSON object per element with its
  heading path and source pages, furniture left out. New plugin option
  **Default output format** for runs without `--format`. The `md-tree`
  gate now checks that every file `index.md` links exists.
- **C4 model**: the evals as a container with a developer actor and a
  `GraderEval` dynamic view; grader, gates, queue, image and merge
  descriptions match 0.7.0.

### Fixes

- **Retries**: a page a grader never reached no longer passes.
  `merge_grades.py` exits 1 naming pages with no grade shard, and `decide`
  deletes an escalated page's old shard, so a retry's new body cannot ride
  on the previous grade. When a gate and the grader both escalate one page,
  it keeps the higher tier instead of re-running the tier that failed.
- **Input**: `Scan.PDF`, `Photo.JPG` and other upper-case extensions are
  queued on Linux (they were skipped with a warning).
- **OCR**: one element per paragraph, not per printed line; figures keep
  their place among a scan's paragraphs. A language the package manager
  cannot install (no passwordless sudo) comes from the pinned, verified
  tessdata download instead of being dropped.
- **Output**: md-tree no longer overwrites a section that repeats another's
  number and title (it gets `-2`); okf and md-tree remove the previous
  attempt's files before writing; ReqIF stays valid XML when the text holds
  control characters; pptx line breaks no longer glue words together.
- **Orchestrator**: `gates.py` prints a summary (failed checks and their
  pages), not its full report; a failed `uv sync` in `check_env` is fatal
  (exit 1). Page PNGs are written atomically, so a parallel agent never
  reads a half-written one.
- **Removed**: the `page_count_match` gate (it compared a number with
  itself) and `ocr.py --backend` (Tesseract is the only backend).

## 0.6.2


- **Cost per document**: each attempt records what the session spent,
  measured with `ccusage` (optional, on `PATH`); the run report shows each
  document's total. See `tools/queue-state/README.md`.
- **Fix**: a retry opened no attempt record, because the orchestrator loops
  back to extraction without `next`, so the report showed only attempt 0's
  time. `decide` now opens the next attempt when it returns `retrying`.
- **Fix**: the `ocr_languages` option (`/plugin` → configure `scriptorium`)
  was never passed to `ensure_language.py`, so a German scan was OCR'd as
  English. The orchestrator now passes it as `--extra`; entries that are
  not tesseract codes are dropped with a warning.
- **Fix**: a language pack that only exists in scriptorium's own tessdata
  dir (`~/.cache/scriptorium/tessdata`) counted as installed, but on a
  machine with a package manager tesseract was never pointed there, so it
  OCR'd in English. `ensure_language.py` now returns `tessdata_prefix`
  whenever a wanted pack lives only there.
- **Fix**: `state.py init` crashed when `input/` did not exist. It now
  creates the folder, and exits 1 with an `error:` line if it cannot.
- **README**: rewritten for humans and agents: install and system tools
  first, full flag reference, where results and the run report land.

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
- **Fix (lost figures)**: on a two-page document every image counted as a
  repeated "furniture" image (one page is 50%), and a screenshot reused on
  every page of a bilingual guide did too. A furniture image now sits in
  the header/footer band or covers most of the page, on at least 2 pages.
- **Fix**: a screenshot printed as a mosaic of bitmap crops on a tinted
  panel (with number badges on top) is one figure, the rendered panel,
  instead of one figure per crop; a "table" read from a screenshot's text
  layer is dropped.
- **Headings without a TOC**: a title at 1.5x body size or more is a
  heading in any weight, and a short one-line subheading in an accent
  colour and a heavy weight (e.g. Helvetica Neue Medium) is one too.
- **Fix**: a layout table's screenshot cell no longer repeats the
  screenshot's text.
- **Grading**: a caption is only the line printed outside a figure; text
  inside a figure is never a caption, so a gap in `figure_text` is no
  longer tagged `bad_caption`.
- **Run report**: totals for furniture graphics, images, charts and
  tables; per document a contents list (the TOC, else the headings) and
  the same counts per page.
  The report lists the scriptorium, Python, PyMuPDF, pdfplumber, Tesseract
  and LibreOffice versions.
- **Furniture graphics once**: page 1's logo and colour boxes in the
  header/footer band appear once, at the top of the output, instead of not
  at all.
- **Side-margin furniture**: text rotated up the left or right page margin
  (document number, "Aktuelle Informationen ...") is dropped as furniture,
  even when it differs per page.
- **Fix**: a paragraph set in two side-by-side columns is read left column
  first, wraps at each column's own edge, and is one paragraph when the
  left column ends mid-sentence.

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
