# Text-Mode Grading (no rendered page)

For formats with no natural page image (`docx`, `xlsx`) there's no pixel
ground truth for a `grader` subagent to judge against, so grading is a
**deterministic script** (`scripts/text_mode_grade.py`) instead of a
subagent applying `rubric.md` — there is no qualitative judgment call to
make here that a script can't already make by comparing text. One page in
this context is a Heading-1 section (docx) or a worksheet (xlsx).

## What it checks, per page

The script re-reads the **source file directly** (not `elements.json`, not
anything `docx-extract`/`xlsx-extract` produced) to build independent
ground truth, then compares it against the assembled `elements.json` for
that page:

1. **`dropped_text`** — a source paragraph/cell of meaningful length
   (≥15 chars) whose normalized text doesn't appear anywhere in that
   page's assembled output.
2. **`table_corruption`** — docx: a source table's row/column count doesn't
   match the corresponding output table element (or the table is missing
   entirely). xlsx: the sheet's used-range dimensions
   (`max_row - min_row + 1` × `max_column - min_column + 1`) don't match
   the one table element a sheet should produce — this only holds because
   `xlsx-extract` keeps the full rectangular range including blank
   interior rows, rather than silently dropping them.
3. **`missing_image`** — the source has more inline images on this page
   than `elements.json` has `image` elements.
4. **`bad_caption`** — an image element's caption is empty or a generic
   placeholder (`"image"`, `"figure"`, `"picture"`, case-insensitive).
5. **`wrong_heading_level`** — **docx only**: a source heading paragraph's
   text is present in the output only as a `paragraph`, or as a `heading`
   with a different (clamped) level than the source style implies. Not
   checked for xlsx — a sheet is always exactly one heading (its name)
   with no sub-heading structure to get wrong.

## What it does not check

`hallucinated_text`, `duplicated_text`, and `wrong_reading_order` from the
full visual rubric are **not** evaluated in text mode. Both docx and xlsx
extraction read structured content directly off the same paragraphs/
tables/cells this script re-reads — there's no OCR/vision step in between
that could invent or reorder content, so these failure modes aren't
realistically reachable for these formats the way they are for pdf/pptx.
If that assumption ever proves wrong, that's a gap to close here, not a
reason to add a visual grader for a format with no page image to show it.

## Scoring

Same 0.85 pass threshold as the visual rubric, for one merged
`grade-report.json` shape the orchestrator can read the same way
regardless of format: `score = 1.0` with no issues, else
`max(0.0, 1.0 - 0.3 * distinct_issue_types_present)` — a single real defect
type is enough to fail a page, matching the visual rubric's "don't round in
the document's favor" rule.

## Output

Same shard contract as the visual path (`work/<doc>/shards` in, one
`output/<doc>/grade-shards/page{N}.json` out per page) — `merge_grades.py`
combines them identically either way; it has no idea whether the shards
came from a subagent or a script.

## No retry ladder

Because there is no `ocr`/`vision` rung for these formats, a content-defect
failure here has nowhere higher to escalate — see `commands/extract.md`'s
Decide step: a text-mode content-defect failure goes straight to
`needs-human` on the first miss, not a wasted retry of an already-
deterministic extraction. `missing_image`/`bad_caption` are the exception:
those still retry (redo just the image/caption step), same as pdf/pptx.
