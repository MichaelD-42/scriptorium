#!/usr/bin/env python3
"""Set the caption on a previously-extracted image element.

extract_images.py always writes image elements with an empty caption since
a script can't judge what a picture shows — the calling agent (the
`extractor` role) looks at the saved PNG and fills the caption in with this
script, mutating that page's image shard.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import elements as elements_lib  # noqa: E402
import paths  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", required=True)
    parser.add_argument("--page", required=True, type=int)
    parser.add_argument("--asset", required=True, help='e.g. "assets/page2_bitmap1.png"')
    parser.add_argument("--caption", required=True)
    args = parser.parse_args()

    shard_path = paths.shard_path(args.doc, args.page, "image")
    shard = elements_lib.read_shard(shard_path)
    if not shard:
        print(f"error: {shard_path} not found — run extract-images first", file=sys.stderr)
        sys.exit(1)

    found = False
    for el in shard["elements"]:
        if el["type"] == "image" and el["asset"] == args.asset:
            el["caption"] = args.caption
            found = True
    if not found:
        print(f"error: no image element with asset {args.asset} on page {args.page}", file=sys.stderr)
        sys.exit(1)

    shard_path.write_text(json.dumps(shard, indent=2))
    print(f"captioned {args.asset}: {args.caption!r}")


if __name__ == "__main__":
    main()
