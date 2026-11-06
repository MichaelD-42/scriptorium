# AGENTS.md

Guide for a coding agent **editing this repository** — setup, tests, and the
invariants that are easy to break by accident. If you're looking for how to
*run* the extraction pipeline instead, that's a different job: see
`plugins/scriptorium/commands/extract.md` (loaded automatically by Claude
Code) or the human-facing [`README.md`](README.md). This file is not that —
and it's also not the same as `plugins/scriptorium/agents/` (`extractor.md`,
`grader.md`), which are the runtime subagent prompts the pipeline spawns.

## Setup

```bash
cd plugins/scriptorium
uv sync
```

Installs the Python dependencies (PyMuPDF, pdfplumber, pytesseract, Pillow,
Jinja2, ReportLab, PyYAML, python-pptx, python-docx, openpyxl,
beautifulsoup4) plus the `pytest`/`pytest-cov` dev group. Requires
[`uv`](https://docs.astral.sh/uv/) and Python 3.11+. Also runs automatically
via a `SessionStart` hook when the plugin loads in a Claude Code session.

## Running the plugin from this checkout

An installed plugin is a copy in `~/.claude/plugins/cache/`, so edits here
don't reach it. To try a change, start Claude Code with this checkout's
plugin for the session:

```bash
claude --plugin-dir plugins/scriptorium
```

To update the installed copies after a release, see the README's
[Install](README.md#install) section (every scope that has an install).

## Tests

```bash
cd plugins/scriptorium
uv run pytest
```

Config lives in `plugins/scriptorium/pyproject.toml`
(`[tool.pytest.ini_options]`). Two markers gate environment-dependent tests:
`requires_tesseract` and `requires_libreoffice` (the latter skipped in
the main CI job and run by its own `libreoffice` job in
`.github/workflows/ci.yml`). CI runs on Python 3.11 and 3.12, with a
coverage floor on 3.12. `tests/test_prompt_contract.py` checks every
script, subcommand and `--flag` that `commands/` and `agents/` name
against the scripts' argparse.

## Evals

Only the LLM-free extraction eval runs in CI (it fails below the floors
in `evals/extraction/corpus.json`). [`evals/README.md`](evals/README.md) covers the committed
grader calibration set (`/eval-grader`, real graders on injected
defects), the LLM-free extraction eval, and `evals/tests` (run with
`uv run --project plugins/scriptorium pytest evals/tests`). Run the eval
tests after changing the rubric's tags, `merge_grades.py`, `decide` or the
gates. Run `/eval-grader` before and after a change to `rubric.md` or
`agents/grader.md`, and compare the scores. A finding in `evals/findings/`
(a page the scripts got wrong) is fixed as a pre-analysis quirk plus its
measure; see `tools/pdf-triage/README.md`.

## Invariants — easy to break, hard to notice

These aren't style preferences; violating them breaks correctness in ways
that only show up under concurrency or on large documents.

- **Context-rot rule**: the orchestrator (`/scriptorium:extract`) never reads
  `elements.json`, page PNGs, or a subagent's intermediate output into its
  own context — only compact summaries (script stdout, `state.json`,
  `grade-report.json`) come back. If you're adding orchestrator logic that
  `Read`s bulk content directly, that belongs in a leaf subagent instead.
- **Only the orchestrator spawns subagents.** Claude Code subagents are a
  two-level tree — a subagent cannot spawn its own subagents. `extractor` and
  `grader` are roles the orchestrator dispatches many times in parallel (one
  per page batch), not agents that fan out further themselves.
- **Shards, not a shared file.** Every `extractor`/`grader` subagent writes
  only its own page's shard file (`work/<doc>/shards/page{N}.*.json`,
  `output/<doc>/grade-shards/page{N}.json`) and never reads or touches
  another page's shard. This is what makes parallel batches race-free.
  Two deterministic scripts (`merge.py`, `merge_grades.py`) combine shards
  afterward — don't reintroduce a read-modify-write pattern on one shared
  file.
- **A new input format is a pair of sibling tools, not a new plugin or
  agent.** The `extractor`/`grader` agents and the orchestrator loop are
  format-agnostic; the `tools/<format>-triage` and `tools/<format>-extract`
  scripts are format-specific. The format's name still appears in a few
  shared places (`lib/paths.py`, `queue-state/scripts/state.py`,
  `assemble-output/scripts/merge.py`, `grade-output`, `commands/extract.md`,
  `agents/extractor.md`); grep for an existing format such as `xlsx`.
- **Graders tag, scripts score.** A grade shard's score is
  `lib/grades.py`'s `score_from_issues`, never a number an agent picks; a
  new tag goes into `lib/grades.py`'s sets (what a retry does with it,
  whether it blocks a pass), `rubric.md`'s taxonomy and
  `evals/grader/prepare.py`'s mutations.
- **No Claude Code skills.** `tools/` folders have a `README.md`, never a
  `SKILL.md`: a skill would be listed in every session with the plugin
  enabled. The command and the agent prompts name each script by its
  `${CLAUDE_PLUGIN_ROOT}/tools/...` path (substituted in command and agent
  content; not set in Bash).

## Where to go deeper

- [`docs/architecture.md`](docs/architecture.md) — the elastic loop, the
  agent tree, the escalation ladder, why shards exist.
- [`docs/tooling.md`](docs/tooling.md) — every tool, script, CLI argument,
  and on-disk file/shard schema.
- `plugins/scriptorium/commands/extract.md` — the orchestrator's exact,
  executable step-by-step spec.
- Per-tool `plugins/scriptorium/tools/*/README.md` — one per extraction
  tier/format.

Don't duplicate content from these into this file — link to them instead.
