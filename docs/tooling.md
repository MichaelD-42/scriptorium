# Tooling — skills, scripts, and file schemas

This document is the reference for the machinery that implements the loop
described in [`architecture.md`](architecture.md): the two agents, the
skills they call, the shared `lib/`, and the on-disk file/shard formats.

## Agents

| Role | Skills it calls | Job |
|---|---|---|
| `extractor` | render-pages, extract-text, ocr-page, extract-images, pptx-extract, docx-extract, xlsx-extract, html-extract | given a page batch: run the right tier/skill per page and format (pdf: text; or OCR → escalate to vision on low confidence. pptx: native extract, escalate to vision on a forced retry. docx/xlsx/html: native extract, no ocr/vision rung at all), extract + caption images. Writes shards, returns a compact summary only. |
| `grader` | render-pages, grade-output | **independent**: given a page batch, applies the rubric (rendered PNG vs. assembled output) and writes per-page grade shards. Never grades output it produced. Only spawned for formats with a rendered page (`pdf`, `pptx`) — see `grade-output/text-rubric.md` for the no-render alternative. |

Both are leaves — spawned in parallel, several at once, one per page batch.
See `plugins/scriptorium/agents/extractor.md` and `agents/grader.md` for the
full agent prompts.

## Skills

Each skill is `SKILL.md` + `scripts/*.py`, run with
`uv run --project "${CLAUDE_PLUGIN_ROOT}"`:

| Skill | Scripts | Role |
|---|---|---|
| `setup-environment` | `check_env.sh` / `check_env.ps1`, `ensure_language.py` | bootstrap `uv`/Python/`tesseract`/`soffice` (LibreOffice, for pptx rendering); detect and install the OCR language pack a document actually needs |
| `pdf-triage` | `triage.py` | classify PDF pages into tiers + document loop size (`loose`/`tight`) |
| `pptx-triage` | `triage.py` | classify pptx slides (always tier `text`) + loop size (`tight` if any slide has a picture/chart) |
| `docx-triage` | `triage.py` | split a docx into logical pages (Heading-1 sections, via `lib/docx_pages.split_pages`) + loop size (`tight` if any page has a table/image); its `page_count` is the pipeline's own pagination, not an independent source-file property |
| `xlsx-triage` | `triage.py` | classify workbook sheets (always tier `text`, one sheet = one page) + loop size (`tight` if any sheet has an image/chart); its `page_count` (`workbook.sheetnames`) **is** an independent source-file property, like pptx |
| `html-triage` | `triage.py` | classify an HTML document as a single page (always tier `text`, `page_count` always `1` — HTML has no page concept at all) + loop size (`tight` if the page has a table or a saveable image) |
| `render-pages` | `render.py` | page → PNG. PDF pages rasterize directly; pptx is converted to PDF via LibreOffice first, then rasterized the same way. Not used for docx/xlsx/html (no rendered page — see `grade-output/text-rubric.md`) |
| `extract-text` | `extract_text.py` | PDF Tier 1: PyMuPDF text + pdfplumber tables → a shard per page |
| `ocr-page` | `ocr.py`, `write_vision_page.py` | PDF Tier 2: Tesseract (pluggable backend, `--lang`-aware); Tier 3 (vision) is agent-native, landed via `write_vision_page.py`. pptx also lands its vision escalation through `write_vision_page.py`; docx/xlsx/html have no vision rung |
| `extract-images` | `extract_images.py`, `caption_image.py` | PDF: bitmaps + vector-region detection → an independent shard per page; captions are agent-written via `caption_image.py` (also reused as-is by pptx/docx/xlsx/html image shards) |
| `pptx-extract` | `extract_pptx.py` | pptx Tier 1: title → heading, text frames → paragraphs, tables, pictures (own shard), speaker notes — body + image shards in one call |
| `docx-extract` | `extract_docx.py` | docx Tier 1: headings (clamped to level 1-3), paragraphs, tables, inline images — body + image shards in one call, using the same page split as `docx-triage` |
| `xlsx-extract` | `extract_xlsx.py` | xlsx Tier 1: sheet name → heading, used range → one table element (full rectangle, blank interior rows kept), embedded images (own shard) — charts not extracted (no rendering engine) |
| `html-extract` | `extract_html.py` | html Tier 1: `<h1>`-`<h6>` → headings (clamped to level 1-3), `<p>`/`<li>`/`<pre>`/`<blockquote>` → paragraphs, `<table>` → table, `<img>` (`data:` URI or local file only — remote sources skipped) → image — body + image shards in one call, single page always |
| `assemble-output` | `merge.py`, `assemble.py` | `merge.py` combines every page's shards into `elements.json` (page count from `paths.true_page_count`, format-aware); `assemble.py` renders Markdown, HTML, or an OKF bundle |
| `grade-output` | `gates.py`, `write_grade_shard.py`, `merge_grades.py`, `text_mode_grade.py` | `gates.py` (deterministic, whole-doc, any format) + `rubric.md` (vision judge, per page batch, applied by the `grader` agent via `write_grade_shard.py` — `pdf`/`pptx` only) **or** `text_mode_grade.py` (deterministic structural check re-reading the source file directly, no agent — `docx`/`xlsx`/`html`, see `text-rubric.md`) + `merge_grades.py` (deterministic, combines every batch's grade shards identically either way) |

`lib/` (not a skill) holds the shard read/write/merge helpers and path
conventions every skill script imports: `paths.py` (path conventions and
input-format dispatch, below), `elements.py` (shard read/write/merge
helpers), `tesseract.py` (OCR backend wrapper), `docx_pages.py` (docx block
iteration, Heading-1 pagination, and inline-image extraction, shared by
`docx-triage` and `docx-extract` so segmentation can't drift between them),
`html_pages.py` (HTML block iteration, table/heading parsing, and
`data:`-URI/local-file image resolution, shared by `html-triage`,
`html-extract`, and `text_mode_grade.py`'s html path).

### Key script arguments

- `pdf-triage/scripts/triage.py --doc <name>`
- `pptx-triage/scripts/triage.py --doc <name>`
- `docx-triage/scripts/triage.py --doc <name>`
- `xlsx-triage/scripts/triage.py --doc <name>`
- `html-triage/scripts/triage.py --doc <name>`
- `extract-text/scripts/extract_text.py --doc <name> --pages <csv> [--body-size <float>]`
  (`--body-size` is triage's document-wide measurement, passed through — not
  recomputed per batch)
- `ocr-page/scripts/ocr.py --doc <name> --pages <csv> [--backend tesseract] [--lang eng] [--tessdata-dir <path>]`
- `pptx-extract/scripts/extract_pptx.py --doc <name> --pages <csv>`
- `docx-extract/scripts/extract_docx.py --doc <name> --pages <csv>`
- `xlsx-extract/scripts/extract_xlsx.py --doc <name> --pages <csv>`
- `html-extract/scripts/extract_html.py --doc <name> --pages 1`
- `assemble-output/scripts/merge.py --doc <name>`
- `assemble-output/scripts/assemble.py --doc <name> [--format md|html|okf]`
- `grade-output/scripts/gates.py --doc <name> [--format md|html|okf]`
- `grade-output/scripts/write_grade_shard.py --doc <name> --page <n> --score <0-1> [--issues <csv>]`
- `grade-output/scripts/text_mode_grade.py --doc <name>` (docx/xlsx/html only — grades every page in one call, no batching)
- `grade-output/scripts/merge_grades.py --doc <name> [--attempt <n>]`
- `setup-environment/scripts/ensure_language.py <image> [--extra <csv>]`

## File & shard layout

Paths are resolved by `lib/paths.py` against the project root
(`${CLAUDE_PROJECT_DIR}`), not the plugin's install location:

```
input/<doc>.{pdf,pptx,xlsx,docx,html}               one supported input extension

work/<doc>/<doc>.pdf                                pptx only — LibreOffice conversion cache for render-pages
work/<doc>/pages/page{N}.png                        not present for docx/xlsx/html (no rendered page)
work/<doc>/shards/page{N}.{text|ocr|vision}.json    one body shard per page (highest tier wins)
work/<doc>/shards/page{N}.image.json                independent of body tier
work/<doc>/elements.json                            merge.py's output — the merged shards
work/<doc>/triage.json
work/<doc>/gates-report.json

output/<doc>/<doc>.{md,html}                        single-file formats
output/<doc>/{index.md,NN-slug.md}                  okf format (multi-file bundle)
output/<doc>/assets/*.{png,jpg,...}
output/<doc>/grade-shards/page{N}.json              one per grader batch page (or per page, for text_mode_grade.py)
output/<doc>/grade-report.json                      merge_grades.py's output

runs/state.json                                     per-document queue state
```

### Key schemas

- **`triage.json`** — `loop_size` (`loose`/`tight`), `pages[]` each with a
  `tier` (always `text` for pptx/docx/xlsx/html; `text`/`ocr` for pdf). PDF
  triage also has `body_size` (document-wide body-text font size estimate) —
  pptx/docx/xlsx/html have no font-size-based heading classification, so
  they omit it. For `docx`, `page_count` is this pipeline's own Heading-1
  segmentation (`lib/docx_pages.split_pages`), not an independent property
  of the source file the way a PDF's page count, a pptx's slide count, or
  an xlsx's sheet count is — see `lib/paths.true_page_count`. For `html`,
  `page_count` is always `1` — HTML has no page concept at all, not even
  docx's Heading-1 split.
- **`gates-report.json`** — `gates.py`'s deterministic hard-backpressure result:
  `passed` plus the structural checks (page count, empty pages, dangling asset
  refs, OCR confidence floor). Format-agnostic; runs the same way for every
  input format.
- **`grade-report.json`** — `merge_grades.py`'s output: `overall_passed`
  (`gates.passed AND rubric_passed`) and `rubric_verdict.per_page`, each entry
  a score (0-1) and any failure-taxonomy tags. Shards come from
  `write_grade_shard.py` (a `grader` subagent's visual judgment, `pdf`/`pptx`)
  or `text_mode_grade.py` (a deterministic structural check, `docx`/`xlsx`/
  `html`) — the shape is identical either way.
- **`runs/state.json`** — one entry per document keyed by stem: `status`
  (`pending`/`retrying`/`passed`/`needs-human`), `attempt`, `input_format`
  (the source file's extension — `pdf`, `pptx`, `docx`, `xlsx`, `html`), `format`
  (the output format), `escalated_pages` (page → reason, the retained
  feedback), `lang_flag`, `tessdata_prefix`. See `runs/state.example.json`
  for a worked example.

## Environment bootstrap

`pyproject.toml` + `uv`. `skills/setup-environment/scripts/check_env.sh`
(Linux/macOS) or `check_env.ps1` (Windows) bootstraps `uv` itself (official
installer) if missing, then `uv sync` (which fetches a matching Python and
installs `python-pptx`/`python-docx`/`openpyxl`/`beautifulsoup4` alongside
`pymupdf`/`pdfplumber`/etc.),
then the `tesseract` and `soffice` (LibreOffice, pptx rendering only)
binaries via whatever package manager it finds
(`apt-get`/`pacman`/`dnf`/`zypper`/`brew` on POSIX; `scoop`/`winget`/`choco`
on Windows) — both soft-fail (a document that doesn't need them never
blocks on their absence). Runs once at the start of `/scriptorium:extract`,
and again via the plugin's `SessionStart` hook. The `.venv` lives alongside
the plugin source.

OCR language packs are handled per-document, lazily: `ensure_language.py`
runs tesseract's own script detection (OSD) on a representative scanned page
and installs whatever's missing (on Windows, via a direct `.traineddata`
download when no package manager path works). This is coarse — it detects
*script* (Latin/Han/Cyrillic/...), not exact language, so a non-English
Latin-script document still needs its language listed in the plugin's
`ocr_languages` user config (`/plugin` → configure `scriptorium`) to be
ensured explicitly. The vision tier needs no extra setup — it's the calling
subagent's own Read tool.

## Output formats

- `--format md` (default, single file)
- `--format html` (single file)
- `--format okf` (multi-file [OKF v0.1](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
  bundle, split by top-level heading, with a TOC `index.md` and
  inter-section links — see `skills/assemble-output/SKILL.md` for the exact
  layout)

OKF is the on-ramp for the deferred local-RAG stretch goal: small,
self-describing, frontmatter-tagged chunks instead of one large document.
