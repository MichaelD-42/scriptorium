# Evals

Two measurements the test suite can't make. Run them from the repo; none
of this runs in CI. Everything below runs from the repo root.

## Grader calibration — does the grader find real defects?

`grader/cases/` holds one synthetic document (`furniture_sample.pdf`,
extracted by the scripts alone) copied ten times: once clean, and once per
injected defect (`dropped_text`, `duplicated_text`, `wrong_reading_order`,
`hallucinated_text`, `wrong_heading_level`, `table_corruption`,
`missing_image`, `bad_caption`, `split_paragraph`). Each case has the
mutated `elements.json`; `cases.json` names the pages to grade (the broken
one plus an untouched control page) and the tag a grader should find.

Run real graders on them in a Claude Code session started from this
checkout, so the grader prompt and rubric are the repo's, not the installed
copy's:

```bash
claude --plugin-dir plugins/scriptorium
```

```
/eval-grader [--model sonnet|haiku|opus]
```

It stages the cases into `evals/run/` (gitignored; never the repo's
`input/` queue), spawns one grader per case and scores them with
`grader/score.py`: per tag found or missed, recall, and every false
positive (a tag on a control page or in the clean case). Results land in
`evals/run/score-<model>.json`. Cost: 21 page grades per run.

Compare models or rubric changes on these numbers, not on impressions.

After changing a mutation or the extraction scripts, regenerate the
committed cases on purpose and review the diff:

```bash
uv run --project plugins/scriptorium python evals/grader/prepare.py --build
```

## Extraction — how close is the LLM-free pipeline?

```bash
uv run --project plugins/scriptorium python evals/extraction/run.py
```

Runs triage, the text layer, Tesseract for scanned pages and bitmap labels,
with figures undescribed, on every entry of `extraction/corpus.json`, and
scores the Markdown against its reference: `text` (word-sequence
similarity), `headings` (share of reference headings found, in order) and
`tables` (cell F1). No agent, so two runs of the same code score the same.

The corpus starts with `sample.pdf` against `examples/golden.md`. Add a
real document with a hand-checked reference to make the numbers mean
something:

```json
{"input": "path/to/doc.pdf", "reference": "path/to/doc.md", "lang": "deu+eng"}
```

## Findings — corrections from real documents

`/scriptorium:extract --findings evals/findings` (run from this repo)
saves, for every passed PDF, each page that failed its grade at a script
tier and passed after the `vision` retry: `page.pdf`, `reference.md` (the
page the grader accepted), `script.md` (what the scripts made of it) and
`finding.json` (the grader's reasons). `extraction/run.py` scores every
folder in `evals/findings/` next to the corpus, so a script fix shows up as
a better score on the page that needed it.

The reference is a vision transcription and the page is a copy of a real
document: review both before committing a finding, and leave out what you
may not publish. A fixed finding usually becomes a quirk in
`plugins/scriptorium/tools/pdf-triage/scripts/pre_analysis.py` with its
measure and a synthetic test, so the pipeline handles it before extraction
next time.

## Tests

```bash
uv run --project plugins/scriptorium pytest evals/tests
```

Stages the committed cases and checks, without any LLM, that every
mutation shows in the assembled output, that `text_layer_coverage` catches
the dropped paragraph on a text page, and that each tag, written by an
oracle grader, takes its documented route through `merge_grades.py` and
`decide`.
