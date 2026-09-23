---
name: assemble-output
description: Assemble the merged elements.json (text + OCR + images, from all tiers) into the final Markdown, HTML, OKF, or ReqIF document.
---

# Assemble Output

The one place all three extraction tiers converge. Three scripts:

1. **`merge.py`** combines every page's shards (written independently by
   parallel `extractor` subagents into `work/<doc>/shards/`) into one
   `work/<doc>/elements.json` — the merged, whole-document shape everything
   downstream reads. Deterministic: highest tier present wins the page body
   (`vision` > `ocr` > `text`), image elements are appended after it. Also
   copies `work/<doc>/triage.json`'s `furniture_text` (`pdf-triage`'s
   verbatim repeated header/footer text, if any) to the top level of
   `elements.json`, alongside `doc`/`source_file`/`page_count` — `None` if
   `triage.json` doesn't exist or has no `furniture_text`.
2. **`assemble.py`** reads that merged file and writes the final deliverable
   (`--format reqif`/`reqifz` delegates the XML build to `reqif_builder.py`,
   an internal helper module, not a script run on its own).
3. **`zip_output.py`** (optional) packages the whole `output/<doc>/` directory
   into a single `output/<doc>.zip` — see "Zip package" below.

## How

```bash
uv run --project "${CLAUDE_PLUGIN_ROOT}" python \
  "${CLAUDE_PLUGIN_ROOT}/skills/assemble-output/scripts/merge.py" --doc <doc-name>
uv run --project "${CLAUDE_PLUGIN_ROOT}" python \
  "${CLAUDE_PLUGIN_ROOT}/skills/assemble-output/scripts/assemble.py" --doc <doc-name> [--format md|html|okf|reqif|reqifz]
```

Default format is `md`. `html` renders through the Jinja2 template in
`templates/output.html.j2`. `okf` splits the document by top-level heading
into a multi-file [OKF](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
bundle instead of one file — see the "OKF format" section below. `reqif`/
`reqifz` write an OMG [ReqIF](https://www.omg.org/spec/ReqIF/About-ReqIF/)
document instead — see the "ReqIF format" section below.

## Element -> output mapping

| element type | Markdown | HTML | ReqIF |
|---|---|---|---|
| `heading` (level 1-3) | `#`/`##`/`###` | `<h1>`/`<h2>`/`<h3>` | `SPEC-OBJECT` with a `ReqIF.ChapterName` string value; builds the `SPEC-HIERARCHY` tree |
| `paragraph` | plain text, blank-line separated | `<p>` | `SPEC-OBJECT` with a `ReqIF.Text` XHTML value (`<xhtml:p>`) |
| `table` | pipe table | `<table>` | `SPEC-OBJECT` with a `ReqIF.Text` XHTML value (`<xhtml:table>`) |
| `image` | `![caption](assets/...)` | `<img src="assets/..." alt="caption">` | `SPEC-OBJECT` with a `ReqIF.Text` XHTML value (`<xhtml:object data="assets/...">caption</xhtml:object>`, plus an `<xhtml:pre>` of the mermaid source if the element has one) |

Elements are emitted in page order, then in the order they appear in
`elements.json` for that page — extraction scripts are responsible for
getting reading order right before this step runs.

## Output

`output/<doc>/<doc>.{md,html,reqif}` (`reqifz` additionally writes
`output/<doc>/<doc>.reqifz`). Assets referenced by `image` elements are
expected to already exist under `output/<doc>/assets/` (written there
directly by `extract-images`) — this skill only writes references to them
(or, for `reqifz`, copies them into the archive too), it does not otherwise
copy files.

## OKF format

`--format okf` splits the document at every top-level (`H1`) heading and
writes one [OKF v0.1](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
concept file per section instead of one file for the whole document —
useful as an on-ramp to a RAG pipeline later (small, self-describing chunks
instead of one large document):

- `output/<doc>/NN-<slug>.md` — one per `H1` (content before the first
  `H1`, if any, becomes `00-front-matter.md`). YAML frontmatter: `type`
  (`"Document Section"`), `title` (the heading text), `description` (first
  sentence of the section's body), `timestamp` (ISO 8601, generation time),
  `resource` (the source PDF path), `source_pages` (which PDF pages
  contributed). Body is the section's elements rendered the same way as
  single-file Markdown (see the mapping table above), plus bundle-relative
  prev/next links at the bottom.
- `output/<doc>/index.md` — the bundle-root TOC: frontmatter
  `okf_version: "0.1"`, then one `* [title](/NN-slug.md) - description`
  line per section (bundle-relative `/` links, per spec).

`H2`/`H3` headings do **not** start new files — they stay inside whichever
`H1` section they fall under (a flat split, not nested chapters/sections).
A document with no `H1` at all produces a single `00-front-matter.md` file.

## ReqIF format

`--format reqif`/`reqifz` write an [OMG ReqIF](https://www.omg.org/spec/ReqIF/About-ReqIF/)
document (schema `http://www.omg.org/spec/ReqIF/20110401/reqif.xsd`,
unchanged across ReqIF 1.0.1/1.1/1.2) — the standard requirements
interchange format read by DOORS, ReqEdit, Enterprise Architect, Polarion,
etc. Built by `reqif_builder.py` with stdlib `xml.etree.ElementTree`, no new
dependency.

- One `SPEC-OBJECT-TYPE` ("Scriptorium Extracted Element") with two
  attributes: `ReqIF.ChapterName` (`DATATYPE-DEFINITION-STRING`, headings
  only) and `ReqIF.Text` (`DATATYPE-DEFINITION-XHTML`, everything else) —
  see the mapping table above for which element uses which.
- **Hierarchy**: a `SPECIFICATION`'s `SPEC-HIERARCHY` tree mirrors the
  document's heading structure — a heading at level `L` nests under the
  nearest preceding heading at a level `< L` (or the document root if
  none); non-heading elements nest under whichever heading currently
  applies. This is richer than md/html (a flat element stream) or okf
  (H1-only split) — the full H1/H2/H3 tree survives.
- `--format reqif` writes only `output/<doc>/<doc>.reqif` (loose XML;
  `image` elements' `THE-VALUE` reference `assets/...` relative to
  `output/<doc>/`, same as md/html).
- `--format reqifz` writes the same `.reqif` file **and**
  `output/<doc>/<doc>.reqifz` — a zip with the `.reqif` at its root plus
  every asset it references (same relative `assets/...` paths), so the
  archive is self-contained and portable on its own. Image assets also
  remain on disk under `output/<doc>/assets/` either way (written there by
  `extract-images`), so the `image_refs_resolve` gate is unaffected by
  which of `reqif`/`reqifz` was chosen.

## Zip package

```bash
uv run --project "${CLAUDE_PLUGIN_ROOT}" python \
  "${CLAUDE_PLUGIN_ROOT}/skills/assemble-output/scripts/zip_output.py" --doc <doc-name>
```

Zips every file under `output/<doc>/` (the assembled document(s), `assets/`,
`grade-shards/`, `grade-report.json`) into `output/<doc>.zip` — a sibling of
`output/<doc>/`, not inside it, so the zip never tries to include itself.
Entries inside the archive are rooted at `<doc>/...`, so extracting the zip
recreates the `<doc>/` folder. Format-agnostic — works the same regardless
of `--format`. Run any time after `assemble.py`; not run automatically
unless `/scriptorium:extract` is given `--zip`.
