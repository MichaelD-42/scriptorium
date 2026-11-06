#!/usr/bin/env python3
"""Score graders against the calibration set prepare.py built: per tag,
did the grader find the injected defect on its page (recall), and how many
tags did it put where nothing was injected (false positives, from the
control pages and the clean case). Deterministic; reads the grade shards.

    python3 evals/grader/score.py [--root evals/run] [--label sonnet]

Prints a summary and writes `<root>/score-<label>.json`.
"""

import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def score(cases: list[dict], shards: dict[str, dict[int, list[str]]]) -> dict:
    """`shards`: {doc: {page: issues}} as the graders wrote them."""
    per_tag, false_positives, ungraded = {}, [], []
    for case in cases:
        graded = shards.get(case["doc"], {})
        for page in case["pages"]:
            if page not in graded:
                ungraded.append(f"{case['doc']} p{page}")
                continue
            expected = case["expected"].get(str(page))
            if expected:
                per_tag.setdefault(expected, {"found": 0, "cases": 0})
                per_tag[expected]["cases"] += 1
                per_tag[expected]["found"] += expected in graded[page]
            for tag in graded[page]:
                if tag != expected:
                    false_positives.append(
                        {"doc": case["doc"], "page": page, "tag": tag}
                    )
    cases_with_tag = sum(t["cases"] for t in per_tag.values())
    return {
        "recall": round(sum(t["found"] for t in per_tag.values()) / cases_with_tag, 3)
        if cases_with_tag
        else None,
        "per_tag": per_tag,
        "false_positives": false_positives,
        "ungraded": ungraded,
    }


def load_shards(root: Path, cases: list[dict]) -> dict[str, dict[int, list[str]]]:
    out = {}
    for case in cases:
        shard_dir = root / "output" / case["doc"] / "grade-shards"
        out[case["doc"]] = {
            int(p.stem.removeprefix("page")): json.loads(
                p.read_text(encoding="utf-8")
            ).get("issues", [])
            for p in shard_dir.glob("page*.json")
        }
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=REPO / "evals" / "run")
    parser.add_argument(
        "--label", default="grader", help="names the result file, e.g. the model"
    )
    args = parser.parse_args()
    cases = json.loads((args.root / "cases.json").read_text(encoding="utf-8"))
    result = score(cases, load_shards(args.root, cases))
    (args.root / f"score-{args.label}.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    for tag, t in sorted(result["per_tag"].items()):
        print(f"{tag:22} {'found' if t['found'] == t['cases'] else 'MISSED'}")
    print(
        f"recall {result['recall']}  false positives {len(result['false_positives'])}  ungraded {len(result['ungraded'])}"
    )
    for fp in result["false_positives"]:
        print(f"  false positive: {fp['doc']} page {fp['page']} {fp['tag']}")


if __name__ == "__main__":
    main()
