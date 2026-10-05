#!/usr/bin/env python3
"""Combine gates-report.json + every per-page grade shard (written
independently by parallel `grader` subagents) into the final
output/<doc>/grade-report.json. See SKILL.md / rubric.md.

Deterministic — the judgment already happened when the grader wrote each
shard's score and issues; this step is just arithmetic, no agent needed.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import paths  # noqa: E402

THRESHOLD = 0.85


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", required=True)
    parser.add_argument("--attempt", type=int, default=1)
    args = parser.parse_args()

    gates_path = paths.gates_report_json(args.doc)
    if not gates_path.exists():
        print(f"error: {gates_path} not found — run gates.py first", file=sys.stderr)
        sys.exit(1)
    gates = json.loads(gates_path.read_text(encoding="utf-8"))

    shards_dir = paths.grade_shards_dir(args.doc)
    shard_paths = sorted(shards_dir.glob("page*.json"), key=lambda p: int(p.stem.removeprefix("page")))
    if not shard_paths:
        print(f"error: no grade shards found in {shards_dir} — run the grader first", file=sys.stderr)
        sys.exit(1)
    per_page = [json.loads(p.read_text(encoding="utf-8")) for p in shard_paths]

    score = round(sum(p["score"] for p in per_page) / len(per_page), 3)
    failure_taxonomy = sorted({issue for p in per_page for issue in p.get("issues", [])})
    rubric_passed = score >= THRESHOLD

    result = {
        "doc": args.doc,
        "attempt": args.attempt,
        "gates": gates,
        "rubric_verdict": {
            "score": score,
            "passed": rubric_passed,
            "threshold": THRESHOLD,
            "per_page": per_page,
            "failure_taxonomy": failure_taxonomy,
        },
        "overall_passed": gates["passed"] and rubric_passed,
        # Task A5b fix round 1 (controller finding 2): gates.py's warnings
        # (e.g. large_region_excluded) already reach this report nested
        # under "gates" above, but nothing downstream (commands/extract.md's
        # Decide step) reads that deep -- it only looks at overall_passed
        # and per_page. Lifting the same list to the top level, alongside
        # overall_passed, is what actually makes it visible to the
        # orchestrator (and the human it reports to) without requiring a
        # schema change to what already exists nested. Always present, `[]`
        # when gates.py fired none.
        "warnings": gates.get("warnings", []),
    }

    out_path = paths.grade_report_json(args.doc)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8", newline="")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
