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
PDF, PowerPoint (`.pptx`), Word (`.docx`), Excel (`.xlsx`), and HTML
(`.html`) are implemented today.
