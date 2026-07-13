# Extraction Quality Rubric

For each page: open `work/<doc>/pages/page{N}.png` (render it first if it
doesn't exist yet) and compare it against the corresponding section of the
assembled output. Judge against these criteria — this is qualitative,
product-side backpressure, not a checklist a script could run.

For an `image` document there is only ever `page1.png` — the whole input
file — so "the corresponding section of the assembled output" is the whole
document; criterion 7 (images present and captioned, mermaid fidelity) is
squarely in scope since the page's one `image` element *is* the page.

For `--format reqif`/`reqifz`, "the assembled output" is
`output/<doc>/<doc>.reqif`: each extracted element is one `SPEC-OBJECT`,
its text living in either `ReqIF.ChapterName` (headings) or the `ReqIF.Text`
XHTML value (paragraphs/tables/images) — read those as you would the
Markdown/HTML body when applying the criteria below.

## Criteria

1. **Reading order** — does the text flow in the order a human would read
   the page (top-to-bottom, columns handled correctly)?
2. **No dropped text** — is there visible body text on the page that is
   absent from the output?
3. **No hallucinated text** — does the output contain text that is not
   actually on the page? (Most likely on OCR/vision-tier pages.)
4. **No duplicated text** — same sentence/paragraph appearing twice
   (a common symptom of a table not being excluded from paragraph text).
5. **Table integrity** — for pages with a visible table, do the row/column
   counts and cell values in the output match the image?
6. **Heading hierarchy** — do heading levels in the output roughly match
   the visual size/weight hierarchy on the page?
7. **Images present and captioned** — does every visible figure/diagram on
   the page have a corresponding `image` element with a non-empty,
   accurate caption? If that `image` element also has a `mermaid` block,
   does it faithfully represent the diagram's nodes, edges, and labels (not
   just "some diagram exists")?

## Scoring

Score each page 0-1 (1 = no issues). Document score = average of page
scores. **Pass threshold: 0.85.**

## Failure taxonomy

When a page has an issue, tag it with one of:

`dropped_text` · `hallucinated_text` · `wrong_reading_order` ·
`duplicated_text` · `table_corruption` · `missing_image` · `bad_caption` ·
`bad_mermaid` · `wrong_heading_level`

## Output schema — write one shard per page, not a merged report

You are one of possibly several `grader` subagents running in parallel,
each covering a different batch of pages. Don't try to write the whole
document's grade report yourself — write **one shard per page you graded**,
and a deterministic script (`merge_grades.py`) combines every batch's
shards afterward:

```bash
uv run --project "${CLAUDE_PLUGIN_ROOT}" python \
  "${CLAUDE_PLUGIN_ROOT}/skills/grade-output/scripts/write_grade_shard.py" \
  --doc <doc-name> --page <page-number> --score 0.93 --issues dropped_text,bad_caption
```

Omit `--issues` (or pass an empty string) when the page is clean. `--score`
is 0.0-1.0, 1.0 = no issues.

Score 1.0 = no issues. The document-level score, pass/fail against the 0.85
threshold, and the combined `overall_passed` (gates AND rubric) are computed
by `merge_grades.py` after every grader batch's shards are on disk — you
don't need to (and can't, from inside one batch) compute those yourself.
