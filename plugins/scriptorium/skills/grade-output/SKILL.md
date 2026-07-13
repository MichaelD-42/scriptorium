---
name: grade-output
description: Grade an assembled document against deterministic structural gates and a qualitative rubric. Use this to close the loop before deciding pass/retry/escalate for a document.
---

# Grade Output

This is where the loop closes. Elastic Loop Engineering's rule: a grader
must sit **outside** the run that produced the work, or you get automated
self-congratulation. That's why grading is its own agent role (`grader`),
never the `extractor` grading its own output.

Three steps:

1. **Gates** (`gates.py`) — deterministic, structural, hard backpressure.
   Runs **once per document** (not per page batch). If gates fail, the
   rubric doesn't matter — fix the structural problem and re-run gates.
2. **Rubric** — for formats with a rendered page (`pdf`, `pptx`, `image`), qualitative
   product backpressure applied by one or more `grader` subagents (`rubric.md`),
   each covering a page batch **in parallel**, looking at each rendered PNG
   and judging the assembled output against it — not a script. Each batch
   writes one shard per page it graded (`write_grade_shard.py`), never a
   whole-document report. For formats with **no** rendered page (`docx`,
   `xlsx`, `html`), there's no pixel ground truth to judge against, so this
   step is instead one deterministic script (`text_mode_grade.py`, see
   `text-rubric.md`) that writes the same per-page shards itself — no
   subagent spawned at all for this step.
3. **Merge** (`merge_grades.py`) — deterministic, combines the gates result
   and every batch's grade shards into the final report. No judgment left
   to make at this point, so this is a script the orchestrator runs itself,
   not another agent call.

## How

```bash
# once per document, before dispatching graders
uv run --project "${CLAUDE_PLUGIN_ROOT}" python \
  "${CLAUDE_PLUGIN_ROOT}/skills/grade-output/scripts/gates.py" --doc <doc-name> [--format md|html|okf|reqif|reqifz]

# inside each grader subagent, per page it graded — see rubric.md
uv run --project "${CLAUDE_PLUGIN_ROOT}" python \
  "${CLAUDE_PLUGIN_ROOT}/skills/grade-output/scripts/write_grade_shard.py" \
  --doc <doc-name> --page <n> --score 0.93 --issues dropped_text

# OR, for a no-rendered-page format (docx/xlsx/html) — note this does NOT
# apply to image, which is a rendered-page format like pdf/pptx: one script call
# replaces every grader subagent for this document — see text-rubric.md
uv run --project "${CLAUDE_PLUGIN_ROOT}" python \
  "${CLAUDE_PLUGIN_ROOT}/skills/grade-output/scripts/text_mode_grade.py" --doc <doc-name>

# once per document, after every grader batch has finished
uv run --project "${CLAUDE_PLUGIN_ROOT}" python \
  "${CLAUDE_PLUGIN_ROOT}/skills/grade-output/scripts/merge_grades.py" --doc <doc-name> --attempt <n>
```

`gates.py` writes `work/<doc>/gates-report.json`. `merge_grades.py` writes
the final `output/<doc>/grade-report.json` — read that one file for the
pass/fail decision.

## Gate checks

| check | fails when |
|---|---|
| `page_count_match` | pages in `elements.json` != the PDF's actual page count |
| `no_empty_pages` | a page has zero elements |
| `image_refs_resolve` | an `image` element's `asset` path doesn't exist on disk |
| `ocr_confidence_floor` | a tier-`ocr` page's `ocr_confidence` < 0.5 |
| `output_file_exists` | the assembled output is missing or near-empty (format-aware: single file for `md`/`html`, `index.md` + section files for `okf`) |

## Notes for the calling agent

- A rubric verdict of "pass" cannot rescue a failed gate — gates are the
  floor, not one more opinion.
- Don't grade your own extraction output in the same turn you produced it;
  that's exactly the self-congratulation failure mode this design avoids.
- Each `grader` batch only ever writes shards for **its own** pages — never
  read or touch another batch's shard, so parallel graders don't race.
