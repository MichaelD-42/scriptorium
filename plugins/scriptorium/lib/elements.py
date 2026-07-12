"""Read/write helpers for the per-document extraction data.

Extraction is sharded, one file per page per extractor, so that parallel
subagents never read-modify-write the same file (that was the v1 design and
it races under concurrency — see git history). Each extractor writes its own
shard once and never touches another page's or another tier's shard:

    work/<doc>/shards/page{N}.{text|ocr|vision}.json   body shard (one tier wins)
    work/<doc>/shards/page{N}.image.json                image shard (independent)

merge_shards() combines them into the same page shape v1 used, so
assemble.py and gates.py don't need to know sharding exists:

{
  "doc": "sample",
  "source_file": "input/sample.pdf",
  "page_count": 5,
  "pages": [ {"page_number": 1, "tier": "text", "elements": [...]}, ... ]
}
"""

import json
from pathlib import Path

BODY_KINDS_BY_PRIORITY = ("vision", "ocr", "text")  # highest tier first — wins at merge time


def write_shard(shard_path: Path, page_number: int, elements: list, **extra) -> None:
    shard_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"page_number": page_number, "elements": elements, **extra}
    shard_path.write_text(json.dumps(payload, indent=2))


def read_shard(shard_path: Path) -> dict | None:
    if not shard_path.exists():
        return None
    return json.loads(shard_path.read_text())


def merge_shards(shards_dir: Path, page_count: int) -> dict[int, dict]:
    """Combine every page's shards into {page_number: page_dict}. A page
    with no body shard yet (extraction incomplete or still in flight) gets
    tier "text" with no elements — assemble/gates will flag it as empty
    rather than silently dropping it."""
    pages: dict[int, dict] = {}
    for n in range(1, page_count + 1):
        body_tier, body_shard = None, None
        for tier in BODY_KINDS_BY_PRIORITY:
            shard = read_shard(shards_dir / f"page{n}.{tier}.json")
            if shard:
                body_tier, body_shard = tier, shard
                break

        image_shard = read_shard(shards_dir / f"page{n}.image.json")
        image_elements = image_shard["elements"] if image_shard else []

        if body_shard:
            extra = {k: v for k, v in body_shard.items() if k not in {"page_number", "elements"}}
            pages[n] = {
                "page_number": n,
                "tier": body_tier,
                "elements": body_shard["elements"] + image_elements,
                **extra,
            }
        else:
            pages[n] = {"page_number": n, "tier": "text", "elements": image_elements}
    return pages


def load_doc(elements_path: Path) -> dict:
    """Read the merged elements.json (merge_shards()' output, written by
    merge.py). Returns pages as a dict keyed by page_number for convenience."""
    if elements_path.exists():
        data = json.loads(elements_path.read_text())
        data["pages"] = {p["page_number"]: p for p in data.get("pages", [])}
        return data
    return {"doc": None, "source_file": None, "page_count": 0, "pages": {}}


def save_doc(elements_path: Path, doc: dict) -> None:
    elements_path.parent.mkdir(parents=True, exist_ok=True)
    pages_sorted = sorted(doc["pages"].values(), key=lambda p: p["page_number"])
    payload = {**doc, "pages": pages_sorted}
    elements_path.write_text(json.dumps(payload, indent=2))
