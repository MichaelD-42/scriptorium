# Glossary

The words this repo uses in a specific sense, in alphabetical order. Each
entry says what the term means here and where it lives; the linked docs
have the details. [`architecture.md`](architecture.md) explains the loop
these terms belong to; [`tooling.md`](tooling.md) has every script and
schema.

**Asset.** A figure saved as a PNG under `output/<doc>/assets/` and
referenced by an `image` element's `asset` path. The `image_refs_resolve`
gate checks that every reference points at a file.

**Attempt.** One pass of a document through extract, merge, assemble,
grade and decide. Counted from 0 in the queue entry's `attempt`; each
attempt's timing, cost, status and escalations are recorded in its
`attempts` list. `--max-attempts` (default 3) caps them.

**Band (furniture band).** The top and bottom 12% of a page
(`FURNITURE_EDGE_BAND` in `lib/furniture.py`), where running headers and
footers sit. When triage finds a page frame, the bands become the page area
outside the content rect instead.

**Batch.** A group of whole pages that one extractor or grader subagent
handles. `plan.py` packs pages into batches by their estimated agent turns
so a batch fits the agent's `maxTurns`. A page is never split across
batches.

**Blocking tag.** A grader tag that fails the document whatever the
average score: every content tag, `split_paragraph`, and `missing_image`
(`BLOCKING_ISSUES` in `lib/grades.py`).

**Body.** A page's text content (headings, paragraphs, list items,
tables), as opposed to its images. A page has one body shard, written at
one tier; images live in a separate image shard.

**Body size.** The document-wide font size of ordinary body text,
estimated by PDF triage (`body_size` in `triage.json`). `extract-text` uses
it to tell headings from body text when there is no table of contents.

**Content rect.** The area inside a page frame that repeats across the
document (`furniture["content_rect"]`). Text outside it counts as
furniture.

**Context-rot rule.** The orchestrator reads only short script stdout,
`runs/state.json` and `grade-report.json`, never page images or
`elements.json`. Bulk content stays inside the subagent that produced it.
See [`architecture.md`](architecture.md#context-rot-prevention).

**Decide.** `state.py decide`: the script that turns a grade report into
the document's next status (`passed`, `retrying` or `needs-human`) and,
for a retry, its escalated pages.

**Digital-native formats.** `docx`, `xlsx` and `html`. Their extraction is
deterministic and there is no rendered page to read, so a content defect
cannot be fixed by a higher tier: it goes straight to `needs-human`. They
are graded by text mode.

**Element.** One unit of extracted content: `heading`, `paragraph`,
`list_item`, `table` or `image`, with its fields (text, level, rows,
bbox, caption...). Every output format is rendered from the same elements.

**`elements.json`.** `work/<doc>/elements.json`, every page's elements
after `merge.py` combined the shards. `assemble.py` and `gates.py` read
it.

**Escalation.** Sending a page back for a retry with a new tier, a
`recheck_images` flag and the reason it failed. Stored per page in the
queue entry's `escalated_pages`; the next extractor batch gets the reason
verbatim.

**Excluded region.** A drawing or bitmap that figure detection found and
then decided is not a figure (a page frame, a repeated drawing, a sliver,
a table's grid...). Recorded with its reason in the page's
`excluded_regions`. A large one with an unusual reason raises the
`large_region_excluded` warning.

**Extractor.** The subagent role that extracts the pages a script cannot:
OCR and vision bodies, and figure descriptions. The orchestrator spawns one
per batch, in parallel (`agents/extractor.md`).

**Failure taxonomy.** The fixed set of tags a grader may put on a page
(`grade-output/rubric.md`, `ISSUES` in `lib/grades.py`), grouped by what a
retry does about them: content tags raise the tier, image tags redo the
image step, `split_paragraph` goes to a human.

**`figure_text`.** The text printed inside a figure (axis labels, box
labels), as opposed to its caption below or above it. Taken from the text
layer or Tesseract by a script, or transcribed by the extractor.

**Findings.** Suggested corrections for the scripts, saved by
`findings.py` under `--findings <dir>`: a PDF page that failed at a script
tier and passed at vision, with the source page, what the scripts made of
it and the accepted result. The extraction eval scores every finding
folder.

**Frame table, frame drawing.** A table or vector drawing that repeats on
most pages at the same place: the page's border or title block, not
content. Detected by triage, recorded under `furniture`, and left out of
extraction.

**Furniture.** Everything that repeats on the pages but isn't the
document's content: running headers and footers, page numbers, page
frames, repeated logos. PDF triage detects it (`triage.json["furniture"]`),
the extract scripts and `merge.py` remove it, and the `furniture_absent`
gate checks it is gone. `lib/furniture.py` holds the shared rules.

**Gate.** A deterministic structural check in `gates.py` that needs no
judgment, such as no empty pages or every text-layer word present. A failed
gate fails the document. Some gates send pages back for a retry; the
others go to a human. Gates write `work/<doc>/gates-report.json`.

**Grade report.** `output/<doc>/grade-report.json`, written by
`merge_grades.py`: the gates, every page's grade, the average score and
`overall_passed`. `decide` reads it.

**Grade shard.** One page's grade, `output/<doc>/grade-shards/page{N}.json`:
its tags, the score computed from them, and the grader's reason.

**Grader.** The subagent role that compares the assembled output with the
rendered page and tags what is wrong (`agents/grader.md`). It never grades
its own extraction and never picks a score.

**Input format, output format.** The input format is the source file's
kind (`pdf`, `pptx`, `docx`, `xlsx`, `html`, `image`), detected from its
extension. The output format is what `--format` asks for (`md`, `html`,
`okf`, `md-tree`, `jsonl`, `reqif`, `reqifz`).

**Join (page-break join).** Merging a paragraph or table cut by a page
break back into one element, done by `merge.py` (`lib/elements.py`). A
missed join is tagged `split_paragraph`.

**`lang_flag`, `tessdata_prefix`.** The Tesseract language string (for
example `deu+eng`) and the optional language-data folder that
`ensure_language.py` resolved for a document. Stored in the queue entry
and passed to OCR.

**Loop size.** Triage's guess at how much attention a document needs:
`loose` (all pages at tier text, no visuals) or `tight` (expect a retry).

**md-tree.** The output format that splits the document into one file
per heading at `--split-depth`, in nested folders, with an `index.md` and
stable heading anchors.

**`needs-human`.** The final status of a document the loop cannot fix:
attempts used up, no tier left, a gate no retry can fix, or a digital-native
content defect. Its `reason` says which.

**`no_visible_text`.** A flag the extractor sets on a PDF or image figure
that has no caption and no text inside it, after checking the render. It
satisfies the `figures_complete` gate in place of a caption or
`figure_text`.

**OKF.** The output format that writes an `index.md` and one file per
level-1 section with YAML frontmatter, following the
[OKF spec](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md).

**Orchestrator.** `/scriptorium:extract` (`commands/extract.md`): the
root agent that runs the scripts, spawns extractor and grader batches, and
follows `decide`. It is the only agent that spawns subagents.

**Page.** A PDF page, a pptx slide or an xlsx sheet. For docx, a page is
the plugin's own split at each Heading 1 (`lib/docx_pages.py`). An HTML
file or an image file is one page.

**Pre-analysis.** PDF triage's survey before extraction
(`pre_analysis.py`): which detectors will find something (scans, bitmaps,
tables, furniture, a TOC, text languages) and which quirks the document
has.

**Quirk.** A known trait of a PDF that the scripts handle with a specific
measure, such as `layout_table` or `garbled_text_layer`. Pre-analysis
lists the ones a document has; every quirk's measure already runs. See
[`pdf-triage/README.md`](../plugins/scriptorium/tools/pdf-triage/README.md#pre-analysis-pre_analysispy).

**`recheck_images`.** An escalation flag that tells the next extractor to
redo a page's image step (describe, caption, figure text) while the body
keeps its tier.

**ReqIF, ReqIFZ.** The Requirements Interchange Format, an XML format read
by requirements tools such as DOORS and Polarion. `reqifz` is the same file
in a zip archive.

**Rubric.** The grader's instructions for judging a page
(`grade-output/rubric.md`), and `text-rubric.md` for text mode.

**Score.** A page's score is `1 - 0.3 × distinct tags`, never below 0,
computed by `lib/grades.py` from the tags. The document's score is the page
average; it passes the rubric at 0.85 or above with no blocking tag.

**Shard.** A file that holds one page's output from one step, written by
exactly one script or subagent: body shards
(`work/<doc>/shards/page{N}.{text|ocr|vision}.json`), image shards
(`page{N}.image.json`) and grade shards. Parallel batches never write the
same file, and `merge.py` / `merge_grades.py` combine the shards
afterwards. See [`architecture.md`](architecture.md#why-shards-not-one-shared-file).

**Split depth.** `--split-depth 1-6` for md-tree: the heading level that
starts a new file.

**Text-layer coverage.** The gate that checks every word in a text-tier
PDF page's text layer appears in the output (neighbouring pages count, for
joins). It catches dropped text without a grader and sends failing pages to
vision.

**Text mode.** Grading without an agent for digital-native formats:
`text_mode_grade.py` re-reads the source file and compares it with
`elements.json`, writing the same grade shards a grader would.

**Tier.** How a page's body is extracted: `text` (the PDF's text layer,
PyMuPDF), `ocr` (Tesseract on the rendered page) or `vision` (Claude
reading the rendered page). Triage picks the cheapest tier that should
work; an escalation moves a page up. When a page has several body shards,
the highest tier wins.

**Triage.** The first script per document (`<format>-triage/triage.py`):
it rejects unreadable input, counts pages, picks each page's starting tier
and the loop size, and for a PDF runs the pre-analysis and finds the
furniture and table of contents.

**Warning.** A finding that never blocks a pass but is always reported,
such as `orphan_figure_caption`, `table_as_figure` or
`large_region_excluded`. Gates produce them; the grade report and the queue
entry carry them.
