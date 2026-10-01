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
  "${CLAUDE_PLUGIN_ROOT}/skills/grade-output/scripts/gates.py" --doc <doc-name> [--format md|html|okf|md-tree|reqif|reqifz]

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
| `no_empty_pages` | a page has zero elements (a page whose merged shard has `"skipped": "toc"` — a printed TOC page, see `pdf-triage`/`extract-text` — is exempt: zero elements there is expected, not a failure) |
| `image_refs_resolve` | an `image` element's `asset` path doesn't exist on disk |
| `ocr_confidence_floor` | a tier-`ocr` page's `ocr_confidence` < 0.5 |
| `output_file_exists` | the assembled output is missing or near-empty (format-aware: single file for `md`/`html`, `index.md` + section files for `okf`, `index.md` + `NN-slug/NN.MM-slug.md` files or `00-front-matter.md` for `md-tree`) |
| `furniture_absent` | a heading/paragraph/list_item, table cell, image `figure_text` or `caption`, or a line of any `.md`/`.html` file under `output/<doc>/`, has digit-masked text equal to a `triage.json` furniture `line_patterns` entry; or a `table` element's bbox matches a `frame_tables` entry (3pt). A digit-only pattern (no letters, e.g. `#` for a bare page-number footer) matches an element only when its bbox is in the top/bottom 12% furniture band of its PDF page, and is not checked in the output files. Passes trivially with no furniture. Furniture images are not checked: no element records its source xref |
| `toc_headings_match` | a `toc.json` entry has no `heading` with the same normalized text (`lib/toc.py`'s `normalize_toc_text`) within ±1 page, or the heading's level differs from the entry's `level`; or a heading matches no entry. Passes trivially when `toc.json` has no entries |
| `figures_complete` | an `image` element has no non-empty `caption`, no non-empty `figure_text` and no `no_visible_text: true` flag (`describe_image.py --no-visible-text`; counts for pdf and image documents only), or no non-empty `description` |

The three Task A9 checks also carry a `pages` list (the pages to act on)
and structured details: `offenders` (`furniture_absent`); `missing`,
`page_mismatch`, `level_mismatch`, `extra` (`toc_headings_match`);
`incomplete` (`figures_complete`). `commands/extract.md`'s Decide step
reads them: `figures_complete` sets `recheck_images` on its pages;
`furniture_absent`/`toc_headings_match` send the document to a human.

`figures_complete` depends on order: the extractor agent writes
`description` (and `figure_text` or the `no_visible_text` flag when the
scripts found no caption and no figure_text) with `describe_image.py` in `commands/extract.md` step 2, and
`gates.py` runs in step 3. Run straight after the extract scripts, with
no describe step, the check fails on purpose.

`gates-report.json` also carries a top-level `warnings` list (Task A5b),
separate from `checks` — see below.

## `large_region_excluded` (warning, not a gate)

For a PDF, `gates.py` also checks every page's `excluded_regions` (written
by `extract-images`, see its SKILL.md) and, for any entry whose `reason` is
`furniture_band` or `table_overlap` (never `frame_drawing`/
`repeated_drawing`/`tiny`/`text_box` — those are expected/benign; a
`text_box` keeps its text as body text) AND whose bbox
covers more than 20% of its page,
appends a `{"name": "large_region_excluded", "page": ..., "bbox": ...,
"reason": ..., "area_fraction": ..., "detail": ...}` entry to
`gates-report.json`'s top-level `warnings` list.

This is deliberately a **warning**, not one of the `checks` above, so it
never flips `passed` to `false` on its own: a large excluded region is very
often a *correct* exclusion (an oversized real table, say), and a hard
gate would force an escalation every time one legitimately occurs. The
point is visibility, not blocking, and visibility is wired through the rest
of the pipeline (Task A5b fix round 1):

- The `grader` subagent (`agents/grader.md`) reads `gates-report.json`'s
  `warnings` for its own batch's pages, looks at the flagged region on the
  rendered PNG, and — only when it's actually a real figure, a judgment
  call gates.py can't make on its own — tags that page `missing_image`
  when it writes its grade shard. A large excluded region that turns out
  to be a correctly-dropped table, say, gets no tag; the warning stays
  informational.
- `merge_grades.py` lifts the same `warnings` list to the top level of
  `output/<doc>/grade-report.json` (alongside `overall_passed`), not just
  nested under `gates`.
- `commands/extract.md`'s Decide step records a non-empty `warnings` list
  in the document's `runs/state.json` queue entry and reports it to the
  human in the loop summary, regardless of `overall_passed` — a warning is
  never silently dropped even when everything else passes.

## Notes for the calling agent

- A rubric verdict of "pass" cannot rescue a failed gate — gates are the
  floor, not one more opinion.
- Read `gates-report.json`'s `warnings` list (or `grade-report.json`'s
  top-level copy, once merge_grades.py has run) alongside `checks` — a
  passing `checks` result with a non-empty `warnings` list still deserves a
  look before calling the extraction done.
- Don't grade your own extraction output in the same turn you produced it;
  that's exactly the self-congratulation failure mode this design avoids.
- Each `grader` batch only ever writes shards for **its own** pages — never
  read or touch another batch's shard, so parallel graders don't race.
