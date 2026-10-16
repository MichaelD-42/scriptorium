#!/usr/bin/env python3
"""Plan one attempt's work for a document: which pages the orchestrator
extracts by script alone, and how to batch the pages that need an agent so
that no extractor or grader runs out of turns. See SKILL.md.

    plan.py --doc <name> --stage scripts   deterministic extraction to run directly
    plan.py --doc <name> --stage extract   extractor batches (after the scripts ran)
    plan.py --doc <name> --stage grade     grader batches (after merge/assemble/gates)

The page set is the attempt's: every page on attempt 0, the escalated pages
on a retry (runs/state.json). A batch is whole pages, never part of one:
describe_image.py rewrites a page's image shard, so two agents on one page
would race.
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import elements as elements_lib  # noqa: E402
import paths  # noqa: E402

AGENTS_DIR = Path(__file__).resolve().parents[3] / "agents"
# Share of an agent's maxTurns a batch may plan for; the rest absorbs
# retried tool calls, zoomed re-renders and the final summary.
HEADROOM = 0.6
# Estimated agent turns per unit of work.
BODY_TURNS = {"ocr": 2, "vision": 3}  # ocr: shared OCR call + a possible vision fallback
IMAGE_TURNS = 2  # read the crop, describe_image.py
UNLABELLED_IMAGE_TURNS = 3  # + zoomed render to transcribe figure_text
GRADE_PAGE_TURNS = 2  # read the rendered page, write_grade_shard.py
GRADE_IMAGE_TURNS = 1  # check one figure against the page
RENDERED_FORMATS = ("pdf", "pptx", "image")


def turn_budget(role: str) -> int:
    text = (AGENTS_DIR / f"{role}.md").read_text(encoding="utf-8")
    return int(int(re.search(r"^maxTurns:\s*(\d+)", text, re.M).group(1)) * HEADROOM)


def pack(work: list[tuple[int, int]], budget: int, max_pages: int | None) -> tuple[list[list[int]], list[int]]:
    """Greedy contiguous batches of (page, turns) within `budget` turns and
    `max_pages` pages. A page over budget on its own gets its own batch and
    is reported."""
    batches, over, current, used = [], [], [], 0
    for page, turns in work:
        if current and (used + turns > budget or (max_pages and len(current) >= max_pages)):
            batches.append(current)
            current, used = [], 0
        current.append(page)
        used += turns
        if turns > budget:
            over.append(page)
    if current:
        batches.append(current)
    return batches, over


def _context(doc: str) -> tuple[dict, dict[int, str]]:
    """(queue entry, {page: tier} for this attempt's pages)."""
    entry = json.loads(Path("runs/state.json").read_text(encoding="utf-8"))["docs"][doc]
    if entry["attempt"] == 0:
        triage = json.loads(paths.triage_json(doc).read_text(encoding="utf-8"))
        return entry, {p["page_number"]: p["tier"] for p in triage["pages"]}
    return entry, {int(n): e["tier"] for n, e in entry["escalated_pages"].items()}


def _recheck(entry: dict) -> list[int]:
    return sorted(int(n) for n, e in entry["escalated_pages"].items() if e.get("recheck_images"))


def scripts_stage(doc: str) -> dict:
    entry, tiers = _context(doc)
    fmt, first = entry["input_format"], entry["attempt"] == 0
    image_pages = sorted(tiers) if first else _recheck(entry)
    if fmt == "pdf":
        text_pages = sorted(n for n, t in tiers.items() if t == "text") if first else []
        return {"extract_text": text_pages, "extract_images": image_pages}
    if fmt == "image":
        return {"extract_images": image_pages}
    return {"format_extract": image_pages}


def extract_stage(doc: str, max_pages: int | None) -> dict:
    entry, tiers = _context(doc)
    work = []
    for page, tier in sorted(tiers.items()):
        shard = elements_lib.read_shard(paths.shard_path(doc, page, "image")) or {"elements": []}
        turns = BODY_TURNS.get(tier, 0) + sum(
            IMAGE_TURNS if el.get("caption") or el.get("figure_text") else UNLABELLED_IMAGE_TURNS
            for el in shard["elements"]
            if el.get("type") == "image" and not el.get("description")
        )
        if turns:
            work.append((page, turns))
    batches, over = pack(work, turn_budget("extractor"), max_pages)
    recheck = set(_recheck(entry))
    escalated = entry["escalated_pages"]
    return {
        "agent_free_pages": len(tiers) - len(work),
        "batches": [
            {
                "pages": b,
                "tiers": {str(n): tiers[n] for n in b},
                "recheck_images": [n for n in b if n in recheck],
                **({"reasons": {str(n): escalated[str(n)]["reason"] for n in b if str(n) in escalated}} if escalated else {}),
            }
            for b in batches
        ],
        "over_budget_pages": over,
    }


def grade_stage(doc: str, max_pages: int | None) -> dict:
    entry, tiers = _context(doc)
    if entry["input_format"] not in RENDERED_FORMATS:
        return {"text_mode": True, "batches": []}
    pages = elements_lib.load_doc(paths.elements_json(doc))["pages"]
    work = [
        (n, GRADE_PAGE_TURNS + GRADE_IMAGE_TURNS * sum(
            1 for el in pages.get(n, {}).get("elements", []) if el.get("type") == "image"))
        for n in sorted(tiers)
    ]
    batches, over = pack(work, turn_budget("grader"), max_pages)
    return {"text_mode": False, "batches": [{"pages": b} for b in batches], "over_budget_pages": over}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", required=True)
    parser.add_argument("--stage", required=True, choices=("scripts", "extract", "grade"))
    parser.add_argument("--max-pages", type=int, help="cap on pages per batch (the old --batch-size)")
    args = parser.parse_args()
    if args.stage == "scripts":
        out = scripts_stage(args.doc)
    elif args.stage == "extract":
        out = extract_stage(args.doc, args.max_pages)
    else:
        out = grade_stage(args.doc, args.max_pages)
    print(json.dumps(out))


if __name__ == "__main__":
    main()
