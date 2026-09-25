# Tooling — skills, scripts, and file schemas

This document is the reference for the machinery that implements the loop
described in [`architecture.md`](architecture.md): the two agents, the
skills they call, the shared `lib/`, and the on-disk file/shard formats.

## Agents

| Role | Skills it calls | Job |
|---|---|---|
| `extractor` | render-pages, extract-text, ocr-page, extract-images, pptx-extract, docx-extract, xlsx-extract, html-extract | given a page batch: run the right tier/skill per page and format (pdf: text; or OCR → escalate to vision on low confidence. pptx: native extract, escalate to vision on a forced retry. docx/xlsx/html: native extract, no ocr/vision rung at all. image: always OCR → escalate to vision, no text rung), extract + caption images. Writes shards, returns a compact summary only. |
| `grader` | render-pages, grade-output | **independent**: given a page batch, applies the rubric (rendered PNG vs. assembled output) and writes per-page grade shards. Never grades output it produced. Only spawned for formats with a rendered page (`pdf`, `pptx`, `image`) — see `grade-output/text-rubric.md` for the no-render alternative. |

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
| `image-triage` | `triage.py` | classify a standalone image document as a single page (always tier `ocr`, `page_count` always `1` — same fixed rule as html-triage, but on the pdf-style ocr/vision ladder, not the digital-native one) + loop size (always `tight`) |
| `render-pages` | `render.py` | page → PNG. PDF pages rasterize directly; pptx is converted to PDF via LibreOffice first, then rasterized the same way; a standalone image document is normalized straight to PNG (no dpi/zoom step). Not used for docx/xlsx/html (no rendered page — see `grade-output/text-rubric.md`) |
| `extract-text` | `extract_text.py` | PDF Tier 1: PyMuPDF text + pdfplumber tables → a shard per page. Removes page furniture (running headers/footers, frame borders) and skips printed-TOC pages before extraction; classifies headings from `toc.json` when present (fallback: font-size ranking) with no level cap; recognizes bullet/enumerator lines as `list_item`; excludes figure-region and caption lines (landed on the matching `image` element instead) |
| `ocr-page` | `ocr.py`, `write_vision_page.py` | PDF Tier 2: Tesseract (pluggable backend, `--lang`-aware); Tier 3 (vision) is agent-native, landed via `write_vision_page.py`. pptx also lands its vision escalation through `write_vision_page.py`; docx/xlsx/html have no vision rung. image documents always start here (there's no Tier 1 for image — no text layer to check) |
| `extract-images` | `extract_images.py`, `describe_image.py`, `mermaid_image.py` | PDF: bitmaps + region-level vector-graphic detection (`lib/figures.py`, shared with `extract-text`, frame-vs-figure disambiguated by furniture repetition, not size) → an independent shard per page, each dropped candidate recorded in `excluded_regions`; a standalone image document instead lands the whole file as page 1's one bitmap element. For a PDF/image element, `caption` is script-authoritative (a nearby "Figure n"/"Table n" text-layer line); the agent always writes `--description` via `describe_image.py` (renamed from the old `caption_image.py`), plus `--data-table`/`--mermaid`/`--figure-text` where they apply, and `--caption` only for pptx/docx/xlsx/html (no script-side detection there). `mermaid_image.py` lands a `mermaid` field standalone, same as `describe_image.py --mermaid` |
| `pptx-extract` | `extract_pptx.py` | pptx Tier 1: title → heading, text frames → paragraphs, tables, pictures (own shard), speaker notes — body + image shards in one call |
| `docx-extract` | `extract_docx.py` | docx Tier 1: headings (clamped to level 1-3), paragraphs, tables, inline images — body + image shards in one call, using the same page split as `docx-triage` |
| `xlsx-extract` | `extract_xlsx.py` | xlsx Tier 1: sheet name → heading, used range → one table element (full rectangle, blank interior rows kept), embedded images (own shard) — charts not extracted (no rendering engine) |
| `html-extract` | `extract_html.py` | html Tier 1: `<h1>`-`<h6>` → headings (clamped to level 1-3), `<p>`/`<li>`/`<pre>`/`<blockquote>` → paragraphs, `<table>` → table, `<img>` (`data:` URI or local file only — remote sources skipped) → image — body + image shards in one call, single page always |
| `assemble-output` | `merge.py`, `assemble.py`, `zip_output.py` | `merge.py` combines every page's shards into `elements.json` (page count from `paths.true_page_count`, format-aware; also joins a paragraph/list item cut by a page break); `assemble.py` renders Markdown, HTML, an OKF bundle, `md-tree` (nested folders/files split at a heading depth, with a stable per-heading anchor — a cross-repo contract with a downstream consumer), or a ReqIF document (XML built by the internal `reqif_builder.py` helper, stdlib `xml.etree.ElementTree`, no new dependency); `zip_output.py` (optional, `/scriptorium:extract --zip`) packages `output/<doc>/` into `output/<doc>.zip` |
| `grade-output` | `gates.py`, `write_grade_shard.py`, `merge_grades.py`, `text_mode_grade.py` | `gates.py` (deterministic, whole-doc, any format — page count, empty pages, dangling asset refs, OCR confidence floor, output file exists, plus PDF-only: furniture absent, TOC headings matched, figures complete, and a `large_region_excluded` warning) + `rubric.md` (vision judge, per page batch, applied by the `grader` agent via `write_grade_shard.py` — `pdf`/`pptx`/`image` only) **or** `text_mode_grade.py` (deterministic structural check re-reading the source file directly, no agent — `docx`/`xlsx`/`html`, see `text-rubric.md`) + `merge_grades.py` (deterministic, combines every batch's grade shards identically either way) |

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
- `image-triage/scripts/triage.py --doc <name>`
- `extract-text/scripts/extract_text.py --doc <name> --pages <csv> [--body-size <float>]`
  (`--body-size` is triage's document-wide measurement, passed through — not
  recomputed per batch)
- `ocr-page/scripts/ocr.py --doc <name> --pages <csv> [--backend tesseract] [--lang eng] [--tessdata-dir <path>]`
- `pptx-extract/scripts/extract_pptx.py --doc <name> --pages <csv>`
- `docx-extract/scripts/extract_docx.py --doc <name> --pages <csv>`
- `xlsx-extract/scripts/extract_xlsx.py --doc <name> --pages <csv>`
- `html-extract/scripts/extract_html.py --doc <name> --pages 1`
- `extract-images/scripts/describe_image.py --doc <name> --page <n> --asset <path> --description <text> [--data-table <json>] [--mermaid <text>] [--caption <text>] [--figure-text <text>] [--no-visible-text]`
  (`--no-visible-text` only for `pdf`/`image` documents; refused together with `--caption`/`--figure-text` or when the element already has one)
- `extract-images/scripts/mermaid_image.py --doc <name> --page <n> --asset <path>`
  (mermaid source on stdin)
- `assemble-output/scripts/merge.py --doc <name>`
- `assemble-output/scripts/assemble.py --doc <name> [--format md|html|okf|md-tree|reqif|reqifz] [--split-depth 2]`
  (`--split-depth` only applies to `md-tree`; only `2` is currently supported)
- `assemble-output/scripts/zip_output.py --doc <name>` (optional; packages `output/<doc>/` into `output/<doc>.zip`)
- `grade-output/scripts/gates.py --doc <name> [--format md|html|okf|reqif|reqifz]`
  (`md-tree` is not yet an accepted value here; the `output_file_exists`
  check has no dedicated case for it)
- `grade-output/scripts/write_grade_shard.py --doc <name> --page <n> --score <0-1> [--issues <csv>]`
- `grade-output/scripts/text_mode_grade.py --doc <name>` (docx/xlsx/html only — grades every page in one call, no batching)
- `grade-output/scripts/merge_grades.py --doc <name> [--attempt <n>]`
- `setup-environment/scripts/ensure_language.py <image> [--extra <csv>]`

## File & shard layout

Paths are resolved by `lib/paths.py` against the project root
(`${CLAUDE_PROJECT_DIR}`), not the plugin's install location:

```
input/<doc>.{pdf,pptx,xlsx,docx,html,png,jpg,jpeg,webp,tiff}  one supported input extension

work/<doc>/<doc>.pdf                                pptx only — LibreOffice conversion cache for render-pages
work/<doc>/pages/page{N}.png                        not present for docx/xlsx/html (no rendered page)
work/<doc>/shards/page{N}.{text|ocr|vision}.json    one body shard per page (highest tier wins)
work/<doc>/shards/page{N}.image.json                independent of body tier
                                                     (each image element may carry `caption`,
                                                     `figure_text`, `no_visible_text`, and
                                                     agent-authored `description`/`data_table`/
                                                     `mermaid`; also carries `excluded_regions`,
                                                     the page's dropped figure-region candidates)
work/<doc>/elements.json                            merge.py's output — the merged shards
work/<doc>/triage.json                              pdf only: also carries `furniture` and `furniture_text`
work/<doc>/toc.json                                 pdf only: detected TOC entries (outline or printed)
work/<doc>/gates-report.json

output/<doc>/<doc>.{md,html,reqif,reqifz}           single-file formats (reqifz is also a zip archive)
output/<doc>/{index.md,NN-slug.md}                  okf format (multi-file bundle)
output/<doc>/{index.md,00-front-matter.md,NN-slug/NN.MM-slug.md}
                                                     md-tree format (nested-folder bundle,
                                                     `--split-depth 2` only — see
                                                     `skills/assemble-output/SKILL.md`)
output/<doc>/assets/*.{png,jpg,...}
output/<doc>/grade-shards/page{N}.json              one per grader batch page (or per page, for text_mode_grade.py)
output/<doc>/grade-report.json                      merge_grades.py's output
output/<doc>.zip                                    zip_output.py's output (optional; sibling to output/<doc>/)

runs/state.json                                     per-document queue state
```

### Key schemas

- **`triage.json`** — `loop_size` (`loose`/`tight`), `pages[]` each with a
  `tier` (always `text` for pptx/docx/xlsx/html; `text`/`ocr` for pdf;
  always `ocr` for `image`). PDF
  triage also has `body_size` (document-wide body-text font size estimate) —
  pptx/docx/xlsx/html/image have no font-size-based heading classification, so
  they omit it. For `docx`, `page_count` is this pipeline's own Heading-1
  segmentation (`lib/docx_pages.split_pages`), not an independent property
  of the source file the way a PDF's page count, a pptx's slide count, or
  an xlsx's sheet count is — see `lib/paths.true_page_count`. For `html`
  and `image`, `page_count` is always `1` — neither has a page concept at
  all, not even docx's Heading-1 split. PDF triage also detects page
  furniture (`furniture`: `line_patterns`, `frame_tables`, `frame_drawings`,
  `image_xrefs`) and its verbatim text (`furniture_text`), and marks any
  detected printed-TOC page `"role": "toc"` in its `pages[]` entry — see
  `pdf-triage/SKILL.md`.
- **`toc.json`** (pdf only) — `entries[]`, each `{number, title, page,
  level}`, from `lib/toc.py`'s `detect_toc()`: the PDF's own outline if it
  has one, else a detected printed table of contents. `extract-text` reads
  this to drive heading-level classification; empty `entries: []` when
  neither source is found.
- **`gates-report.json`** — `gates.py`'s deterministic hard-backpressure result:
  `passed` plus the structural checks (page count, empty pages, dangling asset
  refs, OCR confidence floor, output file exists) that run for every input
  format, plus three PDF-only structure checks — `furniture_absent`,
  `toc_headings_match`, `figures_complete` — each carrying its own `pages`
  list and structured detail. Also a top-level `warnings` list (currently
  just `large_region_excluded`, a large dropped figure-region candidate) that
  never affects `passed` — see `grade-output/SKILL.md`.
- **`grade-report.json`** — `merge_grades.py`'s output: `overall_passed`
  (`gates.passed AND rubric_passed`) and `rubric_verdict.per_page`, each entry
  a score (0-1) and any failure-taxonomy tags. Shards come from
  `write_grade_shard.py` (a `grader` subagent's visual judgment, `pdf`/`pptx`)
  or `text_mode_grade.py` (a deterministic structural check, `docx`/`xlsx`/
  `html`) — the shape is identical either way. `pdf`/`pptx`/`image` are the
  rendered-page formats that go through `write_grade_shard.py`.
- **`runs/state.json`** — one entry per document keyed by stem: `status`
  (`pending`/`retrying`/`passed`/`needs-human`), `attempt`, `input_format`
  (the source file's extension — `pdf`, `pptx`, `docx`, `xlsx`, `html`, or
  `image`; the five image extensions all normalize to `image`, see
  `lib/paths.detect_input_format`), `format`
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
- `--format md-tree` (multi-file bundle split into nested folders/files at a
  heading depth, `--split-depth 2` only; every inline heading gets a stable
  cross-repo anchor — see `skills/assemble-output/SKILL.md`'s "md-tree
  format" section. This is an `assemble.py`-level format for a downstream
  consumer; it is not currently one of `/scriptorium:extract`'s own
  `--format` choices, and `gates.py` has no dedicated `output_file_exists`
  case for it)
- `--format reqif` / `--format reqifz` ([OMG ReqIF](https://www.omg.org/spec/ReqIF/About-ReqIF/)
  — the standard requirements-interchange XML format, one `SPEC-OBJECT` per
  element with a `SPEC-HIERARCHY` mirroring the heading tree; `reqifz`
  additionally bundles the `.reqif` with its referenced assets into a
  self-contained zip — see `skills/assemble-output/SKILL.md` for the exact
  element/attribute mapping)

An `image` element with a `mermaid` field renders as a ` ```mermaid ` code
block alongside the kept image (md/okf), a mermaid.js-rendered
`<pre class="mermaid">` alongside the `<img>` (html, mermaid.js pulled from
a CDN only when the document has at least one such element), or an
`<xhtml:pre>` of the raw mermaid source alongside the `<xhtml:object>` image
reference (reqif/reqifz).

OKF is the on-ramp for the deferred local-RAG stretch goal: small,
self-describing, frontmatter-tagged chunks instead of one large document.
