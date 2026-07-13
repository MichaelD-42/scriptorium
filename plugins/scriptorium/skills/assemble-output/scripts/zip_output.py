#!/usr/bin/env python3
"""Package output/<doc>/ (the assembled document(s), assets, and grade
report) into a single output/<doc>.zip for easy download/sharing. See
SKILL.md.

Deterministic, no judgment involved — this is a script, not an agent step.
"""

import argparse
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import paths  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", required=True)
    args = parser.parse_args()

    output_dir = paths.output_dir(args.doc)
    if not output_dir.is_dir():
        print(f"error: {output_dir} not found — run assemble.py first", file=sys.stderr)
        sys.exit(1)

    files = [p for p in output_dir.rglob("*") if p.is_file()]
    if not files:
        print(f"error: {output_dir} has no files to package", file=sys.stderr)
        sys.exit(1)

    zip_path = paths.output_zip(args.doc)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in files:
            zf.write(file_path, arcname=Path(args.doc) / file_path.relative_to(output_dir))

    print(str(zip_path))


if __name__ == "__main__":
    main()
