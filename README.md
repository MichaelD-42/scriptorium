# Scriptorium

[![CI](https://github.com/MichaelD-42/scriptorium/actions/workflows/ci.yml/badge.svg)](https://github.com/MichaelD-42/scriptorium/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11 | 3.12](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](plugins/scriptorium/pyproject.toml)

A Claude Code plugin that extracts documents into structured text — headings,
tables, figures with descriptions — and checks its own result before handing
it back. PDF, Word, PowerPoint, Excel, HTML and images go in; Markdown, HTML,
a split Markdown bundle or ReqIF comes out.

Cheap deterministic extraction runs first. OCR and Claude reading the rendered
page are used only on the pages that need them. A separate grader agent
compares every page against the original and sends failing pages back one
tier up, until the document passes or is handed to a human.

## Install

In a Claude Code session:

```
/plugin marketplace add MichaelD-42/scriptorium
/plugin install scriptorium@scriptorium
```

Update with `/plugin marketplace update scriptorium`.

The first run sets up the Python environment with [`uv`](https://docs.astral.sh/uv/)
(installed if missing). System tools are only needed for some inputs:

| Tool | Needed for | If missing |
|---|---|---|
| Tesseract | scanned pages and images (OCR) | install attempted via the package manager when `sudo` needs no password, or brew; otherwise text-layer documents still work |
| LibreOffice (`soffice`) | `.pptx` (renders slides for grading) | same install attempt; pptx documents fail to render |
| [ccusage](https://github.com/ryoppippi/ccusage) | cost per document in the run report | cost shows as "–" |

OCR detects the script, not the language: a German or French scan reads as
English unless you list its language codes (e.g. `deu,fra`) in the plugin's
**Extra OCR languages** option (`/plugin` → scriptorium → configure).

## Use

Work from the project directory where you want the results. Put your files
in `input/` there (the first run creates the folder if it is missing), then
run:

```
/scriptorium:extract
```

or ask Claude in plain words ("extract the text from the documents in
input/"). The command processes every new file in `input/` and stops when the
queue is empty.

```
/scriptorium:extract [--doc <name>] [--format md|html|okf|md-tree|reqif|reqifz]
                     [--split-depth 2] [--max-attempts 3] [--batch-size <n>] [--zip]
```

| Flag | Effect |
|---|---|
| `--doc <name>` | process only this file (name without extension) |
| `--format` | output format, default `md` (see below) |
| `--split-depth` | `md-tree` only; `2` is the only accepted value |
| `--max-attempts` | extraction attempts before a document goes to a human, default 3 |
| `--batch-size` | cap on pages per subagent; by default batches are sized by work |
| `--zip` | also write `output/<doc>.zip` for each passed document |

Supported inputs: `.pdf`, `.docx`, `.pptx`, `.xlsx`, `.html`, `.png`, `.jpg`,
`.jpeg`, `.webp`, `.tiff`. To try it, copy a file from
[`plugins/scriptorium/examples/`](plugins/scriptorium/examples/) into `input/`.

### Output formats

| Format | Result | Use for |
|---|---|---|
| `md` | `output/<doc>/<doc>.md` | default; reading, diffing, pasting into other tools |
| `html` | `output/<doc>/<doc>.html` | viewing in a browser; diagrams render inline |
| `okf` | `output/<doc>/index.md` + one file per section | large documents, search/RAG pipelines |
| `md-tree` | `output/<doc>/index.md` + one folder per chapter, one file per section, stable heading anchors | the same, split by chapter |
| `reqif`, `reqifz` | `output/<doc>/<doc>.reqif(z)` | requirements tools (DOORS, Polarion) |

## Results

| Path | Contents |
|---|---|
| `output/<doc>/` | the extracted document and `assets/` (figures, referenced from it) |
| `output/<doc>/grade-report.json` | gates and per-page grades with the grader's reasons |
| `output/report.html` | the run report: status, score, attempts, time and cost per document, page grades, failed gates, warnings |
| `runs/state.json` | the queue: each document's status, attempts and escalations |
| `work/<doc>/` | intermediate files (triage, page renders, shards, merged `elements.json`); needed to resume a document or re-render it in another format |

A document ends as `passed` or `needs-human`. Running the command again skips
finished documents and resumes open ones; a file whose content changed starts
over from scratch.

`needs-human` means the pipeline ran out of options: a page failed at the
highest tier, attempts ran out, or a document-level check failed (e.g. page
furniture leaked into the text, or the headings don't match the printed
table of contents). The reason is in the run report and in `state.json`; the
flagged pages and the grader's reasons are in `grade-report.json`. Typical
causes are poor scans, handwriting and pages that are mostly a complex
diagram.

Warnings never block a pass but are always reported, for example a large
region excluded from the text that might have been a figure.

## How it works

`/scriptorium:extract` is the orchestrator. It runs deterministic scripts for
triage, text and image extraction, assembly and checks, and spawns two
subagent roles in parallel over page batches: `extractor` (OCR, vision, figure
descriptions) and `grader` (independent check against the rendered page). A
failing page moves up one tier: a text-layer page to vision, a scanned page
from OCR to vision. The orchestrator
reads only compact summaries, never page content, so long documents don't
exhaust its context.

- [`docs/architecture.md`](docs/architecture.md) — the loop, agent tree,
  escalation ladder, why per-page shards
- [`docs/tooling.md`](docs/tooling.md) — every script, argument and file schema
- [`plugins/scriptorium/README.md`](plugins/scriptorium/README.md) — changelog

## For agents

- **Running the pipeline**: follow
  [`plugins/scriptorium/commands/extract.md`](plugins/scriptorium/commands/extract.md),
  the orchestrator's step-by-step spec. Read script stdout, `runs/state.json`
  and `grade-report.json` summaries only; never page images or
  `elements.json`.
- **Changing this repo**: read [`AGENTS.md`](AGENTS.md) first — setup, tests
  (`cd plugins/scriptorium && uv run pytest`) and the invariants that break
  silently.

## License

MIT — see [LICENSE](LICENSE).
