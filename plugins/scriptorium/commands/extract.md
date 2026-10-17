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
accepted); `--max-attempts <n>` (default `3`); `--batch-size <n>` (optional cap
on pages per subagent, passed to `plan.py` as `--max-pages`; without it,
batches are sized by work, see step 2); `--zip` to also package each
document's `output/<doc>/` into `output/<doc>.zip` once it passes (off by
default).

Two scripts carry the bookkeeping, so you never edit `runs/state.json` or
size a batch by hand (`queue-state` tool):
`queue-state/scripts/state.py` owns the queue and the pass / retry /
needs-human decision; `queue-state/scripts/plan.py` decides which pages need
an agent and how to batch them. Run every script below as
`uv run --project "${CLAUDE_PLUGIN_ROOT}" python "${CLAUDE_PLUGIN_ROOT}/tools/<tool>/scripts/<script>" ...`.

## Step 0 — environment bootstrap (once, before the queue loop)

On Linux/macOS:

```bash
"${CLAUDE_PLUGIN_ROOT}/tools/setup-environment/scripts/check_env.sh" "${CLAUDE_PLUGIN_ROOT}"
```

On Windows:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}\tools\setup-environment\scripts\check_env.ps1" "${CLAUDE_PLUGIN_ROOT}"
```

Exit code 1 is fatal (uv couldn't be obtained) — stop and report it. Any
other outcome, proceed; a missing `tesseract` only matters for documents
that actually have scanned pages, and that's handled per-document below.

## Setup

`state.py init --format <output format>` creates `runs/state.json` if needed
and adds every new supported file in `input/` as `pending`. If `--doc` was
given, pass `--doc <name>` to every `state.py next` below.

## Queue loop

Repeat until no document matches:

**Pick**: `state.py next` prints the next `pending`/`retrying` document, or
nothing. Nothing → run `queue-state/scripts/report.py` (writes
`output/report.html`: summary tiles, every document's attempts with their
durations, gates, warnings and page grades) and `state.py summary`; report
the summary (passed / needs-human counts, each needs-human reason,
documents with warnings) with the report's path, and **stop**.

### 1. Triage / resume

- **Attempt 0**: run `<input_format>-triage/scripts/triage.py --doc <name>`
  (`pdf`, `pptx`, `docx`, `xlsx`, `html`, `image`; a script, no agent).
  **Exit 1** means the input is unreadable, password-protected, empty or
  damaged: `state.py reject --doc <name> --reason "<the error: line>"`, next
  document. A retry cannot fix the input file. Triage's `loop_size` tells
  you how closely to read the reports that follow: `loose` (all tier
  `text`, no visuals) — dispatch and wait; `tight` — expect a retry and read
  each batch's summary closely.
- **Retry** (attempt > 0): don't re-triage. `plan.py` reads the escalated
  pages from `runs/state.json`.
- **OCR language**: if this attempt has an `ocr` or `vision` page (PDF
  triage's `non_text_pages`, an `image` document, or a retry tier) and the
  queue entry's `lang_flag` is `null`: run
  `setup-environment/scripts/ensure_language.py` on one such page's rendered
  PNG (render it first via `render-pages`), then `state.py set-lang --doc
  <name> --lang-flag <lang_flag> [--tessdata-prefix <prefix>]`. Pass both
  to every extractor batch with an `ocr`/`vision` page as `--lang` and (only
  when set) `--tessdata-dir`. Once per document, not per attempt.

### 2. Extract — scripts first, agents only where needed

**2a. Scripts.** `plan.py --doc <name> --stage scripts` prints the pages to
extract deterministically yourself (each list may be empty; skip a command
with no pages):

- `extract_text` → `extract-text/scripts/extract_text.py --doc <name>
  --pages <list> --body-size <triage body_size>`
- `extract_images` → `extract-images/scripts/extract_images.py --doc <name>
  --pages <list>`
- `format_extract` → the format's extract script
  (`pptx-extract/scripts/extract_pptx.py`, `docx-extract/scripts/extract_docx.py`,
  `xlsx-extract/scripts/extract_xlsx.py`, `html-extract/scripts/extract_html.py`)
  `--doc <name> --pages <list>`

Their stdout is one short line per page; that is all you read.

**2b. Agents.** `plan.py --doc <name> --stage extract [--max-pages <n>]`
prints `batches`: only the pages that still need judgment (an `ocr`/`vision`
body, or an image without a description). Each batch is sized to fit in an
extractor's turn limit. **In a single message, spawn one `extractor` per
batch** (multiple Agent calls together, so they run in parallel). Give each:
the doc name, `input_format`, its `pages` and `tiers` (verbatim), the note
that text-tier bodies and image shards for its pages are already on disk,
`--lang`/`--tessdata-dir` if it has an `ocr`/`vision` page, and on a retry its
`recheck_images` pages and `reasons` (verbatim). No batches → skip the
spawn. A page in `over_budget_pages` has more figures than one extractor
can describe in its turn limit: tell that batch's extractor to describe as
many as it can and list the rest in its summary; `figures_complete` will
send the rest back as a retry. Wait for all of them.

Each `extractor` only writes its own pages' shard files, so batches never
touch the same file.

### 3. Merge and assemble (scripts, not agents)

```bash
uv run --project "${CLAUDE_PLUGIN_ROOT}" python "${CLAUDE_PLUGIN_ROOT}/tools/assemble-output/scripts/merge.py" --doc <name>
uv run --project "${CLAUDE_PLUGIN_ROOT}" python "${CLAUDE_PLUGIN_ROOT}/tools/assemble-output/scripts/assemble.py" --doc <name> --format <format>
uv run --project "${CLAUDE_PLUGIN_ROOT}" python "${CLAUDE_PLUGIN_ROOT}/tools/grade-output/scripts/gates.py" --doc <name> --format <format>
```

For `--format md-tree`, run `assemble.py` twice: first `--format md`, then
`--format md-tree --split-depth <n>`. Then run `gates.py --format md-tree`.
The grader in step 4 reads the single-file `output/<doc>/<doc>.md`: md-tree
renders the heading that opens a file only as frontmatter, so a grader that
reads the split files would flag every level-1/level-2 heading as missing.
Both formats use the same element renderers.

```bash
uv run --project "${CLAUDE_PLUGIN_ROOT}" python "${CLAUDE_PLUGIN_ROOT}/tools/assemble-output/scripts/assemble.py" --doc <name> --format md
uv run --project "${CLAUDE_PLUGIN_ROOT}" python "${CLAUDE_PLUGIN_ROOT}/tools/assemble-output/scripts/assemble.py" --doc <name> --format md-tree --split-depth <n>
uv run --project "${CLAUDE_PLUGIN_ROOT}" python "${CLAUDE_PLUGIN_ROOT}/tools/grade-output/scripts/gates.py" --doc <name> --format md-tree
```

`merge.py` recombines **every** page's shards, old and new — untouched
pages' shards from a previous attempt are picked up automatically, so a
retry that only re-extracted 2 pages still produces a complete document.

### 4. Grade

- **`pdf`/`pptx`/`image`**: `plan.py --doc <name> --stage grade
  [--max-pages <n>]` prints `batches`, weighted by each page's figure count.
  **Spawn one `grader` per batch in parallel**, each with its `pages` and
  the assembled output's location (for `md-tree`, `output/<doc>/<doc>.md`,
  see step 3). Wait for all of them. On a retry only the escalated pages are
  regraded; the others' grade shards are still valid.
- **`docx`/`xlsx`/`html`** (`plan.py` prints `text_mode: true`; no rendered
  page, see `grade-output/text-rubric.md`): no agents. Run
  `grade-output/scripts/text_mode_grade.py --doc <name>` once.

Then `grade-output/scripts/merge_grades.py --doc <name> --attempt <attempt>`.
Its stdout is a summary; you never need to read `grade-report.json`.

### 5. Decide

`state.py decide --doc <name> --max-attempts <n>` applies the grade report
and prints the document's new `status`:

- `passed` → if `--zip`, run `assemble-output/scripts/zip_output.py --doc
  <name>`. Next document.
- `retrying` → loop to step 2 for this document. `escalated_pages` holds
  each page's new tier, `recheck_images` flag and the grader's `reason`;
  `plan.py` reads them from the queue file.
- `needs-human` → its `reason` says why. Next document.

`warnings` (a count) is recorded in the queue entry whatever the status and
reported by `state.py summary`; a warning never blocks a pass, but it is
never dropped either. The rules `decide` applies (tier ladder per format,
which gate failures go straight to a human, why a docx/xlsx/html content
defect is not retried) are in `queue-state/README.md`.

## Notes

- `runs/state.json` is the single source of truth, and only `state.py`
  writes it. If you're unsure what to do next for a document, run
  `state.py summary` or `state.py next` before guessing.
- Never re-run the same tier on a page that already failed at that tier:
  `decide` never proposes it.
