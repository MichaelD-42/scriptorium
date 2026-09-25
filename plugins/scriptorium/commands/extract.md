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
named document instead of the whole queue; `--format md|html|okf|md-tree|reqif|reqifz`
(default `md`); `--split-depth <n>` (`md-tree` only, default `2`; only `2` is
accepted); `--max-attempts <n>` (default `3`); `--batch-size <n>` (default `8`
pages per subagent); `--zip` to also package each document's `output/<doc>/`
into `output/<doc>.zip` once it passes (off by default).

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
  `docx`, `html`, `png`, `jpg`, `jpeg`, `webp`, `tiff`). For every file whose
  stem isn't yet a key under `docs`, add it:
  `{"status": "pending", "attempt": 0, "input_format": "<ext>", "format": "<output format>", "escalated_pages": {}, "lang_flag": null, "tessdata_prefix": null}`.
  `input_format` is the source file's extension — not to be confused with
  `format`, which is the output format (`md`/`html`/`okf`/`md-tree`/`reqif`/`reqifz`).
  The five image extensions all normalize to `input_format: "image"`
  (`lib/paths.py`'s `detect_input_format`) — record `"image"`, not the raw
  extension.
- If `--doc` was given, you only ever pick that one document below.

## Queue loop

Repeat until no document matches:

**Pick** the first document (`input/` order) with `status` in `pending` or
`retrying`. None left → report a short summary (passed / needs-human counts,
with grade-report paths, and any document that has `warnings` recorded in
its queue entry — see step 5) and **stop**.

### 1. Triage / resume

- **Attempt 0**: run the triage script for this document's `input_format`
  (a script — pure classification, no judgment, don't spend an agent on
  it): `pdf-triage/scripts/triage.py --doc <name>` for `pdf`,
  `pptx-triage/scripts/triage.py --doc <name>` for `pptx`,
  `docx-triage/scripts/triage.py --doc <name>` for `docx`,
  `xlsx-triage/scripts/triage.py --doc <name>` for `xlsx`,
  `html-triage/scripts/triage.py --doc <name>` for `html`,
  `image-triage/scripts/triage.py --doc <name>` for `image`. Its `loop_size`
  tells you how closely to read the reports that follow: `loose` (all tier
  `text`, no tables/images) — dispatch and wait for everything before
  checking in; `tight` (some `ocr`, or visuals/tables present) — expect a
  retry, read each batch's summary closely. `image` triage is always
  `tight` (it's always tier `ocr`, carrying the same escalation risk a
  scanned PDF page has). For `docx`/`xlsx`/`html`
  specifically, "expect a retry" only applies to `missing_image`/
  `bad_caption` — see the Decide step below for why a content defect on
  one of these pages doesn't get a normal retry.
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

For `--format md-tree`, run `assemble.py` twice: first `--format md`, then
`--format md-tree --split-depth <n>`. Then run `gates.py --format md-tree`.
The grader in step 4 reads the single-file `output/<doc>/<doc>.md`: md-tree
renders the heading that opens a file only as frontmatter, so a grader that
reads the split files would flag every level-1/level-2 heading as missing.
Both formats use the same element renderers.

```bash
uv run --project "${CLAUDE_PLUGIN_ROOT}" python "${CLAUDE_PLUGIN_ROOT}/skills/assemble-output/scripts/assemble.py" --doc <name> --format md
uv run --project "${CLAUDE_PLUGIN_ROOT}" python "${CLAUDE_PLUGIN_ROOT}/skills/assemble-output/scripts/assemble.py" --doc <name> --format md-tree --split-depth <n>
uv run --project "${CLAUDE_PLUGIN_ROOT}" python "${CLAUDE_PLUGIN_ROOT}/skills/grade-output/scripts/gates.py" --doc <name> --format md-tree
```

`merge.py` recombines **every** page's shards, old and new — untouched
pages' shards from a previous attempt are picked up automatically, so a
retry that only re-extracted 2 pages still produces a complete document.

### 4. Grade

Same page set as step 2 (all pages on attempt 0, only escalated pages on a
retry — an un-escalated page's assembled content didn't change, so its
existing grade shard from a prior attempt is still valid and doesn't need
regrading).

- **`pdf`/`pptx`/`image`** (rendered pages exist): partition into
  `--batch-size` groups, **spawn one `grader` subagent per group in
  parallel**, each with its page list and the assembled output's location
  (for `md-tree`, give it `output/<doc>/<doc>.md` — see step 3).
  Wait for all of them. (`image` is always a single page, so this is one
  `grader` subagent.)
- **`docx`/`xlsx`/`html`** (no rendered page — see
  `grade-output/text-rubric.md`): no subagent spawn for this step at all.
  Run the deterministic grader script once for the whole document instead:

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

- **`grade-report.json["warnings"]` is non-empty** (Task A5b fix round 1,
  controller finding 2 — e.g. a `large_region_excluded` entry): record the
  list verbatim in this document's `runs/state.json` queue entry as
  `warnings`, and include it in the loop summary you report to the human,
  **regardless of `overall_passed`** — a warning never blocks the pass/fail
  decision below (it's not a gate), but it must never be silently dropped
  either. This is the visibility half of the "no silent drops" contract
  `grade-output`'s `large_region_excluded` gate exists for — the warning
  is worthless if nothing downstream of `gates.py` ever surfaces it to a
  human.
- **`overall_passed: true`**: `status: "passed"`. If `--zip` was given, run
  `assemble-output/scripts/zip_output.py --doc <name>` now (a script, not an
  agent step — deterministic packaging of whatever `assemble.py` already
  wrote). Next document.
- **`overall_passed: false`**:
  - `attempt += 1`. `attempt >= max_attempts` → `status: "needs-human"`,
    record the grade-report path, next document.
  - **Gate failures** (`grade-report.json["gates"]["checks"]`, each with
    `passed: false`). The original five checks are document-level only:
    they name no pages, and this step does not map them to pages. The
    three Task A9 structure checks each carry a `pages` list:
    - `furniture_absent` or `toc_headings_match` failed →
      `status: "needs-human"` **immediately**, and record the check's
      `detail` and `pages` in the queue entry. These checks stay
      document-level: their input is deterministic script output
      (furniture removal in `extract-text`, TOC-driven heading levels), so
      a retry at the same tier gives the same result, and a tier bump
      makes it worse — `ocr`/`vision` do no furniture removal and no
      TOC-driven heading levels. This is the same logic as the
      `docx`/`xlsx`/`html` content-defect rule below.
    - `figures_complete` failed → for each page in its `pages`, keep the
      body tier and set `recheck_images: true` (the same flag as
      `missing_image`/`bad_caption` below), with the check's `detail` as
      `reason`. This retries normally for every format.
  - Unless the document is now `needs-human`, also, for each page with
    issues in `rubric_verdict.per_page`, escalate into `escalated_pages` (keyed by page number) — this is
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
    - **`image`**: same content-defect issues as above, but the ladder has
      only two rungs (no `text` — every image page starts at `ocr`):
      `ocr → vision`. A page already at `vision` that's still failing
      follows the identical `needs-human` rule above.
    - **`docx`/`xlsx`/`html`** (no `ocr`/`vision` rung to escalate into —
      extraction is already digital-native and deterministic): the same
      content-defect issues above mean **`status: "needs-human"`
      immediately**, on the *first* failure, no retry — re-running
      `docx-extract`/`xlsx-extract`/`html-extract` on an unchanged page
      produces byte-identical output, so a retry would only burn an
      attempt without ever being able to fix anything. This is the same
      logic as the "already at vision" rule above, just starting from
      attempt 0 instead of the top of the ladder.
    - `missing_image` / `bad_caption` (any format; for `pdf`/`image` this
      also covers a wrong or incomplete `figure_text`) / `bad_mermaid`
      (`pdf`/`pptx`/`image` only — `text_mode_grade.py` can't judge diagram
      fidelity, so `docx`/`xlsx`/`html` never emit it) → keep the page's body tier
      as-is, set `recheck_images: true` so the next `extractor` batch
      redoes just the image/caption/mermaid step for that page — this
      **does** retry normally even for `docx`/`xlsx`/`html`, since
      re-captioning is a real, different action, unlike re-running
      deterministic text extraction.
    - Record `reason` (the grader's actual issue text) alongside each
      escalation — that's what makes this retained feedback instead of
      noise.
  - `status: "retrying"`. Loop to step 2 for this same document.

## Notes

- `runs/state.json` is the single source of truth. If you're ever unsure
  what to do next for a document, read it before guessing.
- Never re-run the same tier on a page that already failed at that tier
  without changing something — see the `vision`-already-failing rule above.
