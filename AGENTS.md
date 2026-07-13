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

## Tests

```bash
cd plugins/scriptorium
uv run pytest
```

Config lives in `plugins/scriptorium/pyproject.toml`
(`[tool.pytest.ini_options]`). Two markers gate environment-dependent tests:
`requires_tesseract` and `requires_libreoffice` (the latter skipped in
default CI — `.github/workflows/ci.yml` installs tesseract but not
LibreOffice). CI runs on Python 3.11 and 3.12.

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
- **A new input format is a sibling skill, not a new plugin.** The
  `extractor`/`grader` agents and the orchestrator loop are format-agnostic;
  only the `*-triage`/`*-extract` skills are format-specific. Adding support
  for a new format means adding skills the existing agents call, not a new
  agent or plugin.

## Where to go deeper

- [`docs/architecture.md`](docs/architecture.md) — the elastic loop, the
  agent tree, the escalation ladder, why shards exist.
- [`docs/tooling.md`](docs/tooling.md) — every skill, script, CLI argument,
  and on-disk file/shard schema.
- `plugins/scriptorium/commands/extract.md` — the orchestrator's exact,
  executable step-by-step spec.
- Per-skill `plugins/scriptorium/skills/*/SKILL.md` — one per extraction
  tier/format.

Don't duplicate content from these into this file — link to them instead.
