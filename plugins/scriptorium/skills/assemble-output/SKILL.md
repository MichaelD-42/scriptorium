---
name: assemble-output
description: Assemble the merged elements.json (text + OCR + images, from all tiers) into the final Markdown or HTML document.
---

# Assemble Output

The one place all three extraction tiers converge. Two scripts:

1. **`merge.py`** combines every page's shards (written independently by
   parallel `extractor` subagents into `work/<doc>/shards/`) into one
   `work/<doc>/elements.json` — the merged, whole-document shape everything
   downstream reads. Deterministic: highest tier present wins the page body
   (`vision` > `ocr` > `text`), image elements are appended after it.
2. **`assemble.py`** reads that merged file and writes the final deliverable.

## How

```bash
uv run --project "${CLAUDE_PLUGIN_ROOT}" python \
  "${CLAUDE_PLUGIN_ROOT}/skills/assemble-output/scripts/merge.py" --doc <doc-name>
uv run --project "${CLAUDE_PLUGIN_ROOT}" python \
  "${CLAUDE_PLUGIN_ROOT}/skills/assemble-output/scripts/assemble.py" --doc <doc-name> [--format md|html|okf]
```

Default format is `md`. `html` renders through the Jinja2 template in
`templates/output.html.j2`. `okf` splits the document by top-level heading
into a multi-file [OKF](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
bundle instead of one file — see the "OKF format" section below.

## Element -> output mapping

| element type | Markdown | HTML |
|---|---|---|
| `heading` (level 1-3) | `#`/`##`/`###` | `<h1>`/`<h2>`/`<h3>` |
| `paragraph` | plain text, blank-line separated | `<p>` |
| `table` | pipe table | `<table>` |
| `image` | `![caption](assets/...)` | `<img src="assets/..." alt="caption">` |

Elements are emitted in page order, then in the order they appear in
`elements.json` for that page — extraction scripts are responsible for
getting reading order right before this step runs.

## Output

`output/<doc>/<doc>.md` or `output/<doc>/<doc>.html`. Assets referenced by
`image` elements are expected to already exist under `output/<doc>/assets/`
(written there directly by `extract-images`) — this skill only writes
references to them, it does not copy files.

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
