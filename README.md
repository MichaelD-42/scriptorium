# scriptorium

A Claude Code plugin that runs a small team of agents to extract text,
tables, and images from documents — extraction and grading run as
**parallel subagents over page batches**, each with an isolated context
window, with an independent quality grader and an orchestrator loop — built
around **Elastic Loop Engineering**:

> Intent opens the loop. Context grounds it. Backpressure keeps it useful.
> Verification closes it.

Concretely: a document is triaged page-by-page, cheap deterministic
extraction runs first, expensive tiers (local OCR, then Claude vision) only
run on pages that actually need them, and an independent grader — never the
agent that did the extracting — decides whether to accept the result or
escalate specific pages one tier and retry. Claude Code subagents can't
spawn their own subagents, so the orchestrator is the only spawner: it fans
out `extractor`/`grader` subagents in parallel, one per page batch, and
never pulls their bulk output (page images, element lists) into its own
context — only compact summaries come back.

Scriptorium is **one plugin**: the `extractor`/`grader` agents and the
orchestrator loop are format-agnostic — only the *skills* they call
(`pdf-triage`, `extract-text`, `ocr-page`, ...) are format-specific. PDF,
PowerPoint (`.pptx`), Word (`.docx`), Excel (`.xlsx`), HTML (`.html`), and
standalone images (`.png`/`.jpg`/`.jpeg`/`.webp`/`.tiff`) are supported
today; new formats arrive as sibling skills the same agents call, not new
plugins.

See [`docs/architecture.md`](docs/architecture.md) for the elastic loop and
[`docs/tooling.md`](docs/tooling.md) for the skills/scripts reference.

## Install

In a Claude Code session:

```
/plugin marketplace add MichaelD-42/scriptorium
/plugin install scriptorium@scriptorium
```

Then run the pipeline over whatever's in your project's `input/` directory:

```
/scriptorium:extract [--doc <name>] [--format md|html|okf|reqif|reqifz] [--batch-size 8] [--max-attempts 3] [--zip]
```

No manual setup needed — the plugin bootstraps its own environment on first
run (`uv`, the Python env, and the `tesseract` binary + OCR language packs)
on Linux, macOS, and Windows. See [Setup details](#setup-details) below if
that bootstrap can't run non-interactively in your environment.

**Paths are relative to your project, not the plugin.** `lib/paths.py`
resolves `input/`, `work/<doc>/`, `output/<doc>/`, and `runs/state.json`
against the current working directory (`${CLAUDE_PROJECT_DIR}`) — i.e.
*your* project directory, not wherever the plugin was installed. Drop PDFs
in `<your-project>/input/` and find results in `<your-project>/output/<doc>/`.

Pull future updates with `/plugin marketplace update scriptorium`.

## Setup details

Requires [`uv`](https://docs.astral.sh/uv/) and, for local OCR, the
Tesseract binary — but you shouldn't need to install either by hand: the
pipeline bootstraps its own environment on first run (`skills/setup-environment`),
installing `uv` via its official installer if missing, then `tesseract` and
whatever OCR language pack a document actually needs via your system's
package manager. Manual install is a fallback for when that can't run
non-interactively (no cached `sudo`/admin rights, unrecognized package
manager):

```bash
# macOS
brew install tesseract
# Debian/Ubuntu
sudo apt install tesseract-ocr
# Arch
sudo pacman -S tesseract tesseract-data-eng
```

```powershell
# Windows
scoop install tesseract
# or: winget install --id UB-Mannheim.TesseractOCR -e   /   choco install tesseract
```

## From source (local dev)

Clone the repo, then either add it as a local marketplace or point Claude
Code straight at the plugin directory:

```bash
git clone https://github.com/MichaelD-42/scriptorium.git
cd scriptorium
```

```
/plugin marketplace add .
/plugin install scriptorium@scriptorium
```

or, without installing:

```bash
claude --plugin-dir plugins/scriptorium
```

Install the Python dependencies (PyMuPDF, pdfplumber, pytesseract, Pillow,
Jinja2, ReportLab, PyYAML):

```bash
cd plugins/scriptorium
uv sync
```

This also happens automatically via a `SessionStart` hook whenever you load
the plugin in a Claude Code session, and again as step 0 of
`/scriptorium:extract` itself.

### Try it

Generate the synthetic test PDF (exercises every extraction tier: native
text, a table, an embedded bitmap, a vector diagram, and one image-only
"scanned" page with no text layer):

```bash
uv run --project plugins/scriptorium python examples/generate_sample.py
```

This writes `input/sample.pdf`, plus `examples/golden.md` (the intended
correct output) and `examples/counterexample.md` (deliberately broken, for
testing that the grader actually rejects bad output).

Then, inside a session with the plugin loaded:

```
/scriptorium:extract [--doc <name>] [--format md|html|okf|reqif|reqifz] [--batch-size 8] [--max-attempts 3] [--zip]
```

This processes every PDF in `input/`, writing results to `output/<doc>/`
— a single `<doc>.md`/`<doc>.html`/`<doc>.reqif`, or (with `--format okf`)
a multi-file `index.md` + `NN-slug.md` bundle — plus `assets/` and
`grade-report.json`, tracking queue state in `runs/state.json`. Add `--zip`
to also package each passed document's `output/<doc>/` into a single
`output/<doc>.zip`. Run it again — an empty queue means every document is
already `passed` or `needs-human`.

## Repository layout

```
.claude-plugin/marketplace.json   marketplace listing this plugin
plugins/scriptorium/              the plugin: agents, skills, commands
examples/generate_sample.py       synthetic test PDF + golden/counterexample generator
input/                            drop PDFs here to queue them
work/<doc>/shards/                per-page extraction shards
work/<doc>/elements.json          merged shards (merge.py's output)
output/<doc>/                     final results (+ grade-shards/)
runs/state.json                   per-document queue state (see state.example.json)
```

## Status

PDF, pptx, docx, xlsx, HTML, and standalone images in, Markdown / HTML /
OKF bundle / OMG ReqIF (`.reqif`/`.reqifz`) out. Extraction and grading run
as parallel subagents over page batches with
isolated context windows. Diagrams the extractor can faithfully
reconstruct — PDF vector regions, pptx pictures/SmartArt, a whole image
document that is itself a diagram — additionally get a mermaid
representation alongside the captioned image. A local RAG pipeline over the
OKF output is deferred — the plugin's skill-based structure leaves room to
add it as a sibling skill later, without new agents or a new plugin.
