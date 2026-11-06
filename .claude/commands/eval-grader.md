---
description: Calibrate the scriptorium grader — build the synthetic defect set, run one grader per case, score its tags against the injected defects.
---

# /eval-grader

Measures the `grader` role, not a document: how often it finds a known
defect, and how often it tags one that isn't there. Development only; the
cases live in `evals/run/` (gitignored), never in `input/`.

Run this from a session started with `claude --plugin-dir plugins/scriptorium`,
so `scriptorium:grader` is this checkout's prompt and rubric, not the
installed copy.

Arguments (`$ARGUMENTS`, optional): `--model sonnet|haiku|opus` (default:
the grader's own `model:`), used for every grader and as the result label.

1. Stage the committed cases (`evals/grader/cases/`; scripts only, no agent):

   ```bash
   UV_CACHE_DIR="${TMPDIR:-/tmp}/uvcache" uv run --project plugins/scriptorium python evals/grader/prepare.py
   ```

   Its stdout names the root (`evals/run/` as an absolute path) and the case
   count. Read `evals/run/cases.json`: each case has a `doc` and the `pages`
   to grade. Do not read `expected` into a grader's prompt, and do not read
   any page image, `elements.json` or output file yourself.

2. In a single message, spawn one `scriptorium:grader` per case (with
   `model` set when `--model` was given). Tell each: the document name, its
   pages, that the assembled output is `output/<doc>/<doc>.md`, and that the
   project root is the eval root from step 1 — every Bash command it runs
   must start with `cd <root> && `. Nothing else: no hint of what was
   changed. Wait for all of them.

3. Score:

   ```bash
   python3 evals/grader/score.py --label <model or "default">
   ```

   Report its stdout to the user as is: which tags were found or missed,
   recall, and each false positive.
