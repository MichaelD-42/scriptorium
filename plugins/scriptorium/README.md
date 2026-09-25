# scriptorium

Elastic-loop document extraction team. See the repo root `README.md` for
setup and how to run the example.

For the full architecture — the two-level agent tree, the queue loop,
context-rot prevention, and the escalation ladder — see
[`docs/architecture.md`](../../docs/architecture.md). For the skills,
scripts, and file/shard schemas that implement it, see
[`docs/tooling.md`](../../docs/tooling.md).

In short: an `orchestrator` (this plugin's `/scriptorium:extract` command)
triages a document page-by-page, then spawns `extractor` and `grader`
subagents in parallel over page batches — cheap deterministic extraction
first, with local OCR and Claude vision escalated to only where needed, and
an independent grader deciding pass/retry/escalate. Extraction is
format-agnostic at the agent level; only the *skills* are format-specific.
PDF, PowerPoint (`.pptx`), Word (`.docx`), Excel (`.xlsx`), HTML (`.html`),
and standalone images (`.png`/`.jpg`/`.jpeg`/`.webp`/`.tiff`) are
implemented today.

## 0.4.0

PDF extraction quality, for documents with running headers/footers, a
printed or outline table of contents, and figures on otherwise text-heavy
pages:

- **Page furniture** (running headers/footers, doc-number/revision/page
  blocks, a repeated frame border or logo) is detected once per document
  and removed from extracted text, tables, and images.
- **Headings** are classified from the document's table of contents
  (outline or printed) when one exists, instead of font-size heuristics
  alone; levels are no longer capped at 3.
- **List items** (bulleted and enumerated) are recognized as their own
  element type, with nesting level and cross-page-break paragraph joins.
- **Figures** are detected at the region level — a diagram or chart on a
  page that also has body text — instead of only whole-page vector
  renders; captions are read directly off the page, and a new
  `describe_image.py` records an agent's description, data table, and
  mermaid diagram separately from that caption.
- **New output format**: `md-tree` splits a document into nested folders
  and files with stable per-heading anchors, for a downstream per-section
  consumer.
- **New grading checks**: furniture actually absent from the output, every
  TOC heading present at the right page and level, and every figure
  captioned or described — the first two send a document straight to
  human review on failure, since the underlying data is deterministic and
  a retry can't change it.
