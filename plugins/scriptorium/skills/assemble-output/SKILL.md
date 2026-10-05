---
name: assemble-output
description: Assemble the merged elements.json (text + OCR + images, from all tiers) into the final Markdown, HTML, OKF, md-tree, or ReqIF document.
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
   **Furniture filter (fix wave I5)**: `extract-text` removes furniture
   lines while it extracts, but an `ocr` or `vision` body holds the whole
   page, title block included. So for a page whose body tier is `ocr` or
   `vision`, `merge_shards()` removes every `heading`/`paragraph`/
   `list_item` text line whose furniture key (`furniture_key`: no
   whitespace, digit runs as `#`) equals one of
   `triage.json["furniture"]["line_patterns"]`, with `lib/furniture.py`'s
   band plus pattern rule (the rule `grade-output`'s `furniture_absent`
   checks, follow-up R14): an element with a bbox matches any pattern only
   when the bbox lies in the furniture band (`band_limits`, with triage's
   `content_rect` when there is one), so a body line is never deleted; an
   element without a bbox matches a letter-bearing pattern anywhere. An
   element that is empty afterwards is dropped. The page records the count
   as `furniture_lines_removed` (absent when zero). `text` bodies are not
   touched.
   This rule is not the one `extract-text` uses, on purpose. `extract-text`
   removes a line only when its block lies in the band and the line matches
   any pattern; it has the exact text-layer geometry, so it can be strict.
   The merge filter uses the gate's rule, so that an escalated page passes
   `furniture_absent`, and because an `ocr` or `vision` element often has no
   bbox to test against the band. Two effects: a digit-only footer line in
   an `ocr`/`vision` body with no bbox is never removed (and the gate cannot
   flag it either); and a mid-page body line with no bbox that equals a
   letter-bearing furniture line is removed on an `ocr`/`vision` page but
   kept on a `text` page. The note in `lib/furniture.py` says the same.
   **Page-break joins (Task A4b)**: after combining, `lib/elements.py`'s
   `merge_shards()` walks every adjacent page pair once, ascending. If page
   `n`'s last non-image element is a `paragraph`/`list_item` whose text
   does NOT end in `. ! ? : ;`, and page `n+1`'s first non-image element is
   a plain `paragraph` (never a heading/table/new list item) starting
   within ~3pt of the same left x (for a `list_item`, its `text_x`: where
   its text starts after the marker, fix wave I3), the two are joined into ONE element:
   the second element's text is appended to the first with a single space
   (verbatim — no de-hyphenation, no other character changes), the first
   gains `"pages": [n, n+1]` (additive, absent everywhere else) and stays
   under page `n`, and the second is removed from page `n+1`. Pairwise
   only (no 3+ page chains). Follow-up R21: a table cut by a page break IS
   joined — page `n`'s last body element a `table`, page `n+1`'s first body
   element a `table` with the same column count and the same left and
   right edges (within 3 pt): page `n+1`'s rows are appended (leading rows
   equal to page `n`'s first rows are a repeated header and are dropped),
   page `n`'s table gains `"pages"`, and page `n+1`'s table is removed. A
   table join chains across a page that held only the continued table.
   `gates.py`'s `no_empty_pages` counts a page listed in another
   element's `"pages"` as filled.
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
  "${CLAUDE_PLUGIN_ROOT}/skills/assemble-output/scripts/assemble.py" --doc <doc-name> [--format md|html|okf|md-tree|reqif|reqifz] [--split-depth 2]
```

Default format is `md`. `html` renders through the Jinja2 template in
`templates/output.html.j2`. `okf` splits the document by top-level heading
into a multi-file [OKF](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
bundle instead of one file — see the "OKF format" section below. `md-tree`
splits the document into nested folders and files at a heading depth
(`--split-depth`, default `2` — **the only value currently supported;
anything else exits non-zero**) — see the "md-tree format" section below.
`reqif`/`reqifz` write an OMG
[ReqIF](https://www.omg.org/spec/ReqIF/About-ReqIF/) document instead — see
the "ReqIF format" section below.

## Element -> output mapping

| element type | Markdown | HTML | ReqIF |
|---|---|---|---|
| `heading` (level 1-6) | `#` through `######` | `<h1>` through `<h6>` | `SPEC-OBJECT` with a `ReqIF.ChapterName` string value; builds the `SPEC-HIERARCHY` tree |
| `paragraph` | plain text, blank-line separated | `<p>` | `SPEC-OBJECT` with a `ReqIF.Text` XHTML value (`<xhtml:p>`) |
| `list_item` | see "List items" below | one shared `<ul>` per run of consecutive `list_item`s, each `<li class="level-N">` | `SPEC-OBJECT` with a `ReqIF.Text` XHTML value (`<xhtml:p>`) holding the same rendered marker+text line as Markdown |
| `table` | pipe table | `<table>` | `SPEC-OBJECT` with a `ReqIF.Text` XHTML value (`<xhtml:table>`) |
| `image` | `![alt](assets/...)`, then `caption` verbatim, then `figure_text` as a blockquote, then any of `description`/`data_table`/`mermaid` wrapped in `<!-- scriptorium:interpretation -->` markers | `<img src="assets/..." alt="...">`, `<figcaption>`, a `<blockquote style="white-space: pre-line">` for `figure_text` (so its line breaks show), then the same three fields inside an HTML-comment marker pair | `SPEC-OBJECT` with a `ReqIF.Text` XHTML value (`<xhtml:object data="assets/...">caption</xhtml:object>`, plus an `<xhtml:pre>` of the mermaid source if the element has one) |

### List items (Task A4b)

A `list_item` element (`{"type": "list_item", "marker": <verbatim marker>,
"level": <1-based int>, "text": <text without the marker>, "bbox": [...]}`,
written by `extract-text` — see its own SKILL.md's "List items" section)
renders as, in Markdown (`elements_to_markdown` and md-tree's own
`elements_to_markdown_with_anchors` share the identical list-rendering
logic via `render_list_item_markdown`, so md-tree's per-file output
matches single-file `md` byte for byte for the same elements):

```
"  " * (level - 1) + <rendered marker> + " " + text
```

`<rendered marker>` is a plain ASCII `-` for a bullet-glyph marker (a
single character, e.g. `-`/`•`/a private-use Symbol-font glyph — always
normalized to `-` regardless of which glyph was actually printed) and the
marker rendered **verbatim** for an enumerator (more than one character,
e.g. `1)`, `a)`, `(1)`). Consecutive list items render with **no** blank
line between them; the surrounding elements still get their own blank
line before the first item and after the last one, same as any other
element. This exact rule is a later cross-repo byte-for-byte comparison
target — see `tests/test_lists_and_joins.py`'s
`TestMarkdownListRendering` — do not change it without updating both
sides.

HTML wraps each run of consecutive `list_item` elements in one shared
`<ul>`, with each item's level expressed as an `li` class
(`class="level-N"`, CSS-indented in `output.html.j2`) rather than truly
nested `<ul>`s — a deliberate "keep it small" choice, not semantic list
nesting. ReqIF has no list concept of its own, so a `list_item` renders as
an ordinary `ReqIF.Text` paragraph holding the exact same indent+marker+
text line Markdown uses (duplicated in miniature inside
`reqif_builder.py` rather than importing `assemble.py`, which would be a
circular import — `assemble.py` already imports `reqif_builder` at module
scope).

For `image`, alt text prefers `description`, falling back to `caption`,
else empty. `caption` and `figure_text` are script-authoritative/
verbatim, so they render plainly, outside any marker. `description`,
`data_table`, and `mermaid` are agent-judged, not extracted verbatim, so
Markdown and HTML both wrap them (only them, and only if at least one is
present) in `<!-- scriptorium:interpretation -->` / `<!-- /scriptorium:
interpretation -->` — a downstream mechanical validator greps for this pair
to exclude agent interpretation from a "verbatim" check. ReqIF's image
mapping is unchanged by this (still `caption` + `mermaid` only); the other
three figure fields aren't yet represented there.

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

## md-tree format

`--format md-tree --split-depth N` splits the document into nested folders
and files, unlike OKF's flat H1-only split — useful when a downstream
consumer needs one file per section, addressable by a stable per-heading
anchor. `N` is the heading
level at which a NEW FILE starts: levels shallower than `N` become folders,
level `N` itself starts a file, levels deeper than `N` stay as headings
inline within that file.

**Only `--split-depth 2` is currently supported** (folder per level-1
heading, file per level-2 heading) — `assemble.py` rejects any other value
with a non-zero exit rather than silently producing wrong output.
Internally, `build_md_tree_sections` collapses every level `< N` onto a
single flattened "current folder" rather than a truly nested folder stack,
which is only correct for `N == 2`; for `N > 2` this produces colliding
folder numbers across unrelated chapters (confirmed, not just theoretical —
see `build_md_tree_sections`'s docstring). Nested-folder generalization for
`N > 2` is unimplemented, not merely untested; the CLI check exists so that
gap can't be hit silently.

**Layout** (`--split-depth 2`):

- `output/<doc>/index.md` — links every split file, in document order, with
  the section number + title as link text. No frontmatter.
- `output/<doc>/00-front-matter.md` — content before the first level-1
  heading, in true document order (bbox-y0 sorted, so an image positioned
  above a page's heading counts as front matter even if it's on the same
  page as that heading). Omitted if empty.
- `output/<doc>/NN-<slug>/` — one folder per level-1 heading. `NN` is that
  heading's own leading number, zero-padded to 2 digits (a 1-based
  sequential index if the heading has no parseable leading number); `<slug>`
  is a URL-safe slug of its title (the OKF format's existing `slugify()`
  helper).
- `output/<doc>/NN-<slug>/NN.00-<slug>.md` — that level-1 heading's own body
  content that isn't yet under any level-2 child. Also used for a chapter
  with NO level-2 children at all (its whole body lands here, rather than
  inventing a third naming scheme). Omitted if empty; if a chapter has
  neither body content nor level-2 children, no folder/file is written for
  it at all, but its number+title still appears as a plain (non-linked)
  label in `index.md`.
- `output/<doc>/NN-<slug>/NN.MM-<slug>.md` — one file per level-2 heading,
  `MM` zero-padded the same way. Always written, even with an empty body —
  the heading itself defines the section.
- One shared `output/<doc>/assets/` at the bundle root (not duplicated per
  folder). `image` elements' asset paths are rewritten per file's location:
  `assets/...` from a root-level file (`00-front-matter.md`), `../assets/
  ...` from inside an `NN-slug/` folder — same `render_image_markdown`/
  `elements_to_markdown` functions as single-file md (see the mapping table
  above), called with an `asset_prefix` argument, not a second rendering
  path.
- The heading that OPENS a folder/file becomes that file's frontmatter
  `title`/`section`, not a duplicated body heading (same convention
  `split_sections_by_h1`/OKF already use for `H1`). Its anchor (see
  "Anchors" below) is the first body line of the file it opens.

**Frontmatter** — every split file except `index.md`: `doc` (the doc name),
`section` (the heading's own number, e.g. `"2.3"`, or `null` for
`00-front-matter.md`), `title`, `level` (`null` for front matter), and
`source_pages` (the list of page numbers whose content landed in this
file, including the second page of an element joined across a page break,
from its `pages` list). Written with the same `render_frontmatter` YAML
helper OKF uses.

**Anchors — exact cross-repo contract.** Every heading gets a stable
`<a id="...">` anchor from `slugify_heading(text)`:

- A heading that stays inline within a file (level `> N`, e.g. level 3+
  for `--split-depth 2`): the anchor line comes immediately before its
  heading line.
- A heading that opens a file (level `<= N`): the anchor line is the first
  body line of that file, followed by a blank line. A level-1 heading with
  no body of its own (no `NN.00` file) puts its anchor at the top of its
  first `NN.MM` file, before that file's own anchor.
- A level-1 heading with neither body content nor level-2 children has no
  file, so it has no anchor. Nothing can point into it, because it holds
  no content.

There is no shared code: a downstream consumer implements the same
`slugify_heading` rule independently; the rule below is a byte-for-byte
contract. The slug rule:

- If the heading text starts with a leading number (digit groups separated
  by dots, matched from the very start of the text with only leading
  whitespace skipped — e.g. `"2.3.1 Some Title"`), the anchor is that
  number with every `.` replaced by `-` (`"2-3-1"`). No word-boundary check
  follows the digits, so `"3D Printing"` anchors as `"3"`, not
  `"3d-printing"` — intentional, not a bug, because it must match the
  consumer's rule exactly.
- Otherwise, slugify the full heading text: lowercase, every run of
  anything outside ASCII a-z and 0-9 replaced with a single `-` (so
  `"Übersicht"` gives `"bersicht"` and `"Maße"` gives `"ma-e"`),
  leading/trailing `-` stripped, falling back to the literal `"section"`
  if that's empty.

**Any drift in this rule breaks the consumer's links into md-tree
files.** `slugify_heading` in `assemble.py` is unit-tested against fixed
input/output pairs
(`"2.3.1 Some Title"` → `"2-3-1"`, `"Appendix A"` → `"appendix-a"`) — see
`tests/test_md_tree_split.py::TestSlugifyHeading`.

Note this is a *different* rule from the `NN`/`MM` folder/file naming above:
folder/file naming uses `split_section_number`, which requires whitespace
after the number (so `"3D Printing"` is never misparsed as folder/file
number `"3"`) and slugifies the *title only* (not the number) for `<slug>`.
The two rules deliberately diverge — one is a byte-for-byte external
contract, the other is this repo's own filesystem-naming convention.

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
  (H1-only split) — the full H1-H6 tree survives.
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
