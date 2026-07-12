#!/usr/bin/env python3
"""Write one page's grade shard. See rubric.md.

The grader agent's own visual judgment produces the score and issues; this
script just lands it in the shared shard schema, consistent with how
write_vision_page.py and caption_image.py work for extraction.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import paths  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", required=True)
    parser.add_argument("--page", required=True, type=int)
    parser.add_argument("--score", required=True, type=float, help="0.0-1.0, 1.0 = no issues")
    parser.add_argument("--issues", default="", help="comma-separated failure-taxonomy tags, empty if none")
    args = parser.parse_args()

    issues = [i.strip() for i in args.issues.split(",") if i.strip()]
    shard_path = paths.grade_shard_path(args.doc, args.page)
    shard_path.parent.mkdir(parents=True, exist_ok=True)
    shard_path.write_text(json.dumps({"page_number": args.page, "score": args.score, "issues": issues}, indent=2))
    print(f"page {args.page}: score={args.score} issues={issues}")


if __name__ == "__main__":
    main()
