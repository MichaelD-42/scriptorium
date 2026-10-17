---
name: queue-state
description: Orchestrator-only bookkeeping for /scriptorium:extract — the runs/state.json queue, the pass / retry / needs-human decision after a grade, and the per-attempt plan of which pages need an agent and how to batch them. Not for extractor or grader subagents.
---

# Queue state and batch planning

Two scripts, both deterministic, both with compact stdout (the orchestrator
reads them under the context-rot rule). `commands/extract.md` says when to
run each.

## `state.py` — the queue

| Subcommand | Does |
|---|---|
| `init --format <fmt>` | creates `runs/state.json`, adds each new supported `input/` file as `pending` (image extensions become `input_format: "image"`). A file whose content changed (`input_sha256`) is queued again from nothing: `work/<doc>/`, `output/<doc>/` and `output/<doc>.zip` are deleted, so old ocr/vision shards cannot outrank the new extraction. Two inputs with one name: the one `paths.input_file` picks (the scripts' rule) is queued, the other skipped with a warning |
| `next [--doc <name>]` | prints the next `pending`/`retrying` document in `input/` order, or nothing |
| `reject --doc <name> --reason <text>` | `needs-human` with the reason (triage's `error:` line) |
| `set-lang --doc <name> --lang-flag <f> [--tessdata-prefix <p>]` | records `ensure_language.py`'s result |
| `decide --doc <name> --max-attempts <n>` | applies `output/<doc>/grade-report.json` (rules below) |
| `summary` | status counts, needs-human reasons, warning counts |

Writes are atomic (temp file, then rename). `next` opens an attempt
record (`started_at`) when it picks a document; `decide` and `reject` close
it (`finished_at`, `status`, `score`, and on a retry the `escalated_pages`
with their reasons). A queue entry:

```json
{"status": "retrying", "attempt": 1, "input_format": "pdf", "format": "md",
 "escalated_pages": {"3": {"tier": "ocr", "recheck_images": false, "reason": "second paragraph missing"}},
 "lang_flag": null, "tessdata_prefix": null, "warnings": [], "reason": null, "grade_report": null,
 "input_sha256": "9f2c..."}
```

### Decision rules (`decide`)

A page's current tier is the tier it was actually extracted at
(`elements.json`), so an extractor that fell back from OCR to vision on its
own is counted at `vision`.

1. The report's `warnings` are recorded in the entry, whatever the outcome.
2. `overall_passed` → `passed`.
3. Otherwise `attempt += 1`, then each failure is sorted:
   - Gate `furniture_absent` or `toc_headings_match` failed → needs a human.
     Their input is deterministic script output: the same tier gives the
     same result, and a higher tier has no TOC-driven heading levels.
   - Gate `figures_complete` failed → each page in its `pages`: same tier,
     `recheck_images`, the gate's `detail` as reason.
   - Any other failed gate is document-level and names no page.
   - A page tagged with a content issue (`dropped_text`, `hallucinated_text`,
     `wrong_reading_order`, `duplicated_text`, `wrong_heading_level`,
     `table_corruption`) moves one rung up its format's ladder:
     `pdf` text → ocr → vision, `pptx` text → vision (no OCR rung),
     `image` ocr → vision. Already at the top → needs a human.
     `docx`/`xlsx`/`html` → needs a human at once: extraction is
     deterministic and there is no rendered page, so a retry gives
     byte-identical output.
   - A page tagged only `missing_image`/`bad_caption`/`bad_mermaid` → same
     tier, `recheck_images`. This retries for every format.
   - The reason is the grader's `reason` text from the grade shard, or the
     tags when the grader wrote none.
4. Status: anything that needs a human → `needs-human` with all reasons.
   Else `attempt >= max_attempts` → `needs-human`. Else no page to retry
   (a document-level gate, or a low score without tags) → `needs-human`,
   since a retry would re-run nothing. Else `retrying` with
   `escalated_pages`.

## `report.py` — the end-of-run report

```bash
report.py   # {"report": "output/report.html", "documents": n, "passed": n, "needs_human": n}
```

Run once when the queue is empty. Writes one self-contained HTML file (no
scripts, light and dark mode) from `runs/state.json` and each document's
`grade-report.json` and `elements.json`: summary tiles (documents, passed,
needs a human, pages, attempts, extraction time), a row per document with
its page-grade strip, and per document its reason, attempts (start, time,
outcome, score, escalations with reasons), failed gates, warnings, and a
page table (tier, score, issues, the grader's reason). Time is the sum of
attempt durations, from `next` to `decide`/`reject`; it is not split by
phase. All document text is HTML-escaped.

## `plan.py` — what needs an agent, and batch sizes

```bash
plan.py --doc <name> --stage scripts                  # {"extract_text": [...], "extract_images": [...]} or {"format_extract": [...]}
plan.py --doc <name> --stage extract [--max-pages n]  # {"agent_free_pages": n, "batches": [...], "over_budget_pages": [...]}
plan.py --doc <name> --stage grade   [--max-pages n]  # {"text_mode": false, "batches": [{"pages": [...]}], "over_budget_pages": [...]}
```

The page set is the attempt's: every page on attempt 0, the escalated pages
on a retry.

- **scripts**: deterministic extraction the orchestrator runs itself.
  Attempt 0: `extract_text` for text-tier PDF pages, `extract_images` for
  every PDF/image page, `format_extract` for every pptx/docx/xlsx/html page.
  A retry re-runs only the image step of `recheck_images` pages (a content
  escalation never goes back to `text`).
- **extract**: run after the scripts. A page needs an extractor only for an
  `ocr`/`vision` body or an image element without a `description`; the
  rest are `agent_free_pages`. Each extract batch carries `pages`, `tiers`,
  `recheck_images` and, on a retry, `reasons`.
- **grade**: every page of the set for `pdf`/`pptx`/`image`; `text_mode:
  true` with no batches for `docx`/`xlsx`/`html`.

Batches are contiguous whole pages: `describe_image.py` rewrites a page's
image shard, so two agents on one page would race. Pages are packed
greedily into a turn budget of 60% of the agent's `maxTurns` (read from
`agents/extractor.md` and `agents/grader.md`). The remaining 40% absorbs
retried calls and the summary. Estimated turns:

| Work | Turns |
|---|---|
| `ocr` body (shared OCR call plus a possible vision fallback) | 2 |
| `vision` body | 3 |
| image without description, with caption or `figure_text` | 2 |
| image without description, caption or `figure_text` (zoom and transcribe) | 3 |
| grading a page | 2, plus 1 per figure |

A page whose work alone exceeds the budget gets its own batch and is listed
in `over_budget_pages`.
