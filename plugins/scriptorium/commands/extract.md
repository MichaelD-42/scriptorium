---
description: Run the elastic-loop PDF extraction pipeline over the input/ queue — bootstrap the environment, triage, extract and grade in parallel page batches, escalate on failure, repeat until the queue is empty.
---

# /scriptorium:extract

You are the **orchestrator** — the root of a two-level agent tree. You do
not extract, assemble, or grade anything yourself: you run the
deterministic scripts, size the loop, spawn `extractor` and `grader`
subagents **in parallel** over page batches, read their compact reports,
and decide pass / retry-with-escalation / give-up-to-human. This is the
"another document to process?" loop the whole system is built around.

**Subagents cannot spawn their own subagents** — you are the only spawner
in this pipeline. That's why extraction and grading are two agent *roles*
you dispatch many times (once per page batch), not many different agent
*types*: it's the only topology that parallelizes cleanly under that
constraint.

**Context-rot rule — this is not optional.** You run scripts and read only
their short stdout, `runs/state.json`, and `output/<doc>/grade-report.json`.
You **never** read `elements.json`, page PNGs, or a subagent's intermediate
reasoning into your own context — that content lives in the leaf subagents
and comes back to you only as their compact final summaries. If you catch
yourself about to `Read` a page image or `elements.json` directly: stop,
that's a subagent's job, not yours.

Arguments (`$ARGUMENTS`, all optional): `--doc <name>` to process a single
named document instead of the whole queue; `--format md|html|okf` (default
`md`); `--max-attempts <n>` (default `3`); `--batch-size <n>` (default `8`
pages per subagent).

## Step 0 — environment bootstrap (once, before the queue loop)

On Linux/macOS:

```bash
"${CLAUDE_PLUGIN_ROOT}/skills/setup-environment/scripts/check_env.sh" "${CLAUDE_PLUGIN_ROOT}"
```

On Windows:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}\skills\setup-environment\scripts\check_env.ps1" "${CLAUDE_PLUGIN_ROOT}"
```

Exit code 1 is fatal (uv couldn't be obtained) — stop and report it. Any
other outcome, proceed; a missing `tesseract` only matters for documents
that actually have scanned pages, and that's handled per-document below.

## Setup

- Ensure `runs/state.json` exists (`{"docs": {}}` if not).
- Scan `input/*` for every supported input extension (`pdf`, `pptx`, `xlsx`,
  `docx`). For every file whose stem isn't yet a key under `docs`, add it:
  `{"status": "pending", "attempt": 0, "input_format": "<ext>", "format": "<output format>", "escalated_pages": {}, "lang_flag": null, "tessdata_prefix": null}`.
  `input_format` is the source file's extension — not to be confused with
  `format`, which is the output format (`md`/`html`/`okf`).
- If `--doc` was given, you only ever pick that one document below.

## Queue loop

Repeat until no document matches:

**Pick** the first document (`input/` order) with `status` in `pending` or
`retrying`. None left → report a short summary (passed / needs-human counts,
with grade-report paths) and **stop**.

### 1. Triage / resume

- **Attempt 0**: run the triage script for this document's `input_format`
  (a script — pure classification, no judgment, don't spend an agent on
  it): `pdf-triage/scripts/triage.py --doc <name>` for `pdf`,
  `pptx-triage/scripts/triage.py --doc <name>` for `pptx`,
  `docx-triage/scripts/triage.py --doc <name>` for `docx`,
  `xlsx-triage/scripts/triage.py --doc <name>` for `xlsx`. Its `loop_size`
  tells you how closely to read the reports that follow: `loose` (all tier
  `text`, no tables/images) — dispatch and wait for everything before
  checking in; `tight` (some `ocr`, or visuals/tables present) — expect a
  retry, read each batch's summary closely. For `docx`/`xlsx` specifically,
  "expect a retry" only applies to `missing_image`/`bad_caption` — see the
  Decide step below for why a content defect on a docx/xlsx page doesn't
  get a normal retry.
- **Retry** (attempt > 0): don't re-triage — the PDF didn't change. Use
  `escalated_pages` from `runs/state.json`; you'll only re-dispatch those
  pages below, not the whole document.
- **If any page (from triage or escalation) is tier `ocr` or `vision`** and
  `lang_flag` is still `null` for this doc: run
  `setup-environment/scripts/ensure_language.py` on one such page's
  rendered PNG (render it first via `render-pages` if needed), store the
  resulting `lang_flag` **and** `tessdata_prefix` in `runs/state.json` for
  this doc, and pass both to every `extractor` batch below as `--lang` and
  (only when `tessdata_prefix` isn't `null`) `--tessdata-dir`. Resolve this
  once per document, not once per attempt.

### 2. Extract — parallel batches

Build the set of pages to (re-)extract: **all** pages on attempt 0; only
the keys of `escalated_pages` on a retry. Partition into groups of
`--batch-size`. **In a single message, spawn one `extractor` subagent per
group** (multiple Agent tool calls together — this is what makes it
parallel, not sequential calls across turns). Give each its doc name, its
`input_format`, its page list, the tier for each of its pages (from triage,
or the escalated tier), triage's `body_size` if the format has one (pass
through to every `extract-text` call as `--body-size`), and
`--lang`/`--tessdata-dir` if relevant. Wait for all of them.

This is race-free by construction: each `extractor` only ever writes shard
files for its own pages (`work/<doc>/shards/page{N}.*.json`), so batches
never touch the same file.

### 3. Merge and assemble (scripts, not agents)

```bash
uv run --project "${CLAUDE_PLUGIN_ROOT}" python "${CLAUDE_PLUGIN_ROOT}/skills/assemble-output/scripts/merge.py" --doc <name>
uv run --project "${CLAUDE_PLUGIN_ROOT}" python "${CLAUDE_PLUGIN_ROOT}/skills/assemble-output/scripts/assemble.py" --doc <name> --format <format>
uv run --project "${CLAUDE_PLUGIN_ROOT}" python "${CLAUDE_PLUGIN_ROOT}/skills/grade-output/scripts/gates.py" --doc <name> --format <format>
```

`merge.py` recombines **every** page's shards, old and new — untouched
pages' shards from a previous attempt are picked up automatically, so a
retry that only re-extracted 2 pages still produces a complete document.

### 4. Grade

Same page set as step 2 (all pages on attempt 0, only escalated pages on a
retry — an un-escalated page's assembled content didn't change, so its
existing grade shard from a prior attempt is still valid and doesn't need
regrading).

- **`pdf`/`pptx`** (rendered pages exist): partition into `--batch-size`
  groups, **spawn one `grader` subagent per group in parallel**, each with
  its page list and the assembled output's location. Wait for all of them.
- **`docx`/`xlsx`** (no rendered page — see `grade-output/text-rubric.md`):
  no subagent spawn for this step at all. Run the deterministic grader
  script once for the whole document instead:

  ```bash
  uv run --project "${CLAUDE_PLUGIN_ROOT}" python "${CLAUDE_PLUGIN_ROOT}/skills/grade-output/scripts/text_mode_grade.py" --doc <name>
  ```

Either way, once grade shards are on disk:

```bash
uv run --project "${CLAUDE_PLUGIN_ROOT}" python "${CLAUDE_PLUGIN_ROOT}/skills/grade-output/scripts/merge_grades.py" --doc <name> --attempt <attempt>
```

Read `output/<doc>/grade-report.json` — the only place you look at grading
detail, and even then just the compact per-page score/issues, not raw
subagent output.

### 5. Decide

- **`overall_passed: true`**: `status: "passed"`. Next document.
- **`overall_passed: false`**:
  - `attempt += 1`. `attempt >= max_attempts` → `status: "needs-human"`,
    record the grade-report path, next document.
  - Otherwise, for each page with issues in `rubric_verdict.per_page`,
    escalate into `escalated_pages` (keyed by page number) — this is
    **retained feedback**, not a blind re-run:
    - **`pdf`/`pptx`**: `dropped_text` / `hallucinated_text` /
      `wrong_reading_order` / `duplicated_text` / `wrong_heading_level` /
      `table_corruption` → bump the body tier one step:
      `text → ocr → ocr → vision` (a page already at `ocr` whose *content*
      is still wrong, not just low-confidence, goes straight to `vision`).
      **A page already at `vision` that's still failing**: don't retry it
      again — set `status: "needs-human"` for the whole document
      immediately rather than burning remaining attempts on something
      that's already had the best available tier.
    - **`docx`/`xlsx`** (no `ocr`/`vision` rung to escalate into —
      extraction is already digital-native and deterministic): the same
      content-defect issues above mean **`status: "needs-human"`
      immediately**, on the *first* failure, no retry — re-running
      `docx-extract`/`xlsx-extract` on an unchanged page produces
      byte-identical output, so a retry would only burn an attempt without
      ever being able to fix anything. This is the same logic as the
      "already at vision" rule above, just starting from attempt 0 instead
      of the top of the ladder.
    - `missing_image` / `bad_caption` (any format) → keep the page's body
      tier as-is, set `recheck_images: true` so the next `extractor` batch
      redoes just the image/caption step for that page — this **does**
      retry normally even for `docx`/`xlsx`, since re-captioning is a real,
      different action, unlike re-running deterministic text extraction.
    - Record `reason` (the grader's actual issue text) alongside each
      escalation — that's what makes this retained feedback instead of
      noise.
  - `status: "retrying"`. Loop to step 2 for this same document.

## Notes

- `runs/state.json` is the single source of truth. If you're ever unsure
  what to do next for a document, read it before guessing.
- Never re-run the same tier on a page that already failed at that tier
  without changing something — see the `vision`-already-failing rule above.
