#!/usr/bin/env python3
"""Write one page's grade shard. See rubric.md.

The grader agent's visual judgment produces the issues; the score is
`grades.score_from_issues`, the same rule text_mode_grade.py uses, so a
grader never picks a number.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import grades  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", required=True)
    parser.add_argument("--page", required=True, type=int)
    parser.add_argument("--issues", default="", help="comma-separated failure-taxonomy tags, empty if none")
    parser.add_argument("--reason", help="what is wrong, specific enough to act on; the next extractor gets it verbatim")
    args = parser.parse_args()

    issues = [i.strip() for i in args.issues.split(",") if i.strip()]
    unknown = sorted(set(issues) - grades.ISSUES)
    if unknown:
        print(f"error: unknown issue tag(s) {unknown}; see rubric.md's failure taxonomy", file=sys.stderr)
        sys.exit(1)
    shard = grades.write_shard(args.doc, args.page, issues, args.reason)
    print(f"page {args.page}: score={shard['score']} issues={issues}")


if __name__ == "__main__":
    main()
