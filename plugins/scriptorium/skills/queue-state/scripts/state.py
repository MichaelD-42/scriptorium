#!/usr/bin/env python3
"""The extraction queue, runs/state.json, and the pass / retry /
needs-human decision after each grade. See SKILL.md.

Deterministic: the orchestrator runs these subcommands and acts on their
compact stdout instead of editing state.json or applying the escalation
rules by hand.
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import elements as elements_lib  # noqa: E402
import grades  # noqa: E402
import paths  # noqa: E402

STATE_PATH = Path("runs") / "state.json"
OPEN_STATUSES = ("pending", "retrying")
# One rung up the body-tier ladder per format; a tier with no entry is the top.
NEXT_TIER = {
    "pdf": {"text": "ocr", "ocr": "vision"},
    "pptx": {"text": "vision"},  # no ocr rung: pptx is digital-native, vision reads the rendered slide
    "image": {"ocr": "vision"},
}
# Deterministic extraction, no rendered page: a content defect cannot be retried.
DIGITAL_NATIVE = ("docx", "xlsx", "html")
NEEDS_HUMAN_GATES = ("furniture_absent", "toc_headings_match")


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"docs": {}}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8", newline="")
    os.replace(tmp, STATE_PATH)  # an interrupted write never leaves a half-written queue


def decide(entry: dict, report: dict, tiers: dict[int, str], max_attempts: int) -> dict:
    """The queue entry after a grade. `report` is grade-report.json,
    `tiers` each page's body tier as extracted (elements.json)."""
    entry = {**entry, "escalated_pages": {}}
    entry.pop("reason", None)
    if report.get("warnings"):
        entry["warnings"] = report["warnings"]
    if report["overall_passed"]:
        entry["status"] = "passed"
        return entry

    entry["attempt"] += 1
    fmt = entry["input_format"]
    escalations: dict[int, dict] = {}
    human: list[str] = []
    unretryable: list[str] = []

    def escalate(page: int, tier: str, recheck: bool, reason: str) -> None:
        old = escalations.get(page)
        if old:
            reason = f"{old['reason']}; {reason}"
            recheck = recheck or old["recheck_images"]
        escalations[page] = {"tier": tier, "recheck_images": recheck, "reason": reason}

    for check in report["gates"]["checks"]:
        if check["passed"]:
            continue
        if check["name"] in NEEDS_HUMAN_GATES:
            human.append(f"{check['name']}: {check['detail']}")
        elif check["name"] == "figures_complete":
            for page in check.get("pages", []):
                escalate(page, tiers.get(page, "text"), True, check["detail"])
        else:
            unretryable.append(f"{check['name']}: {check['detail']}")

    for shard in report["rubric_verdict"]["per_page"]:
        issues = set(shard.get("issues", []))
        if not issues:
            continue
        page, tier = shard["page_number"], tiers.get(shard["page_number"], "text")
        reason = shard.get("reason") or ", ".join(sorted(issues))
        if issues & grades.CONTENT_ISSUES:
            next_tier = NEXT_TIER.get(fmt, {}).get(tier)
            if fmt in DIGITAL_NATIVE:
                human.append(f"page {page}: {reason} (digital-native extraction is deterministic)")
            elif next_tier is None:
                human.append(f"page {page}: {reason} (already at tier {tier})")
            else:
                escalate(page, next_tier, bool(issues & grades.IMAGE_ISSUES), reason)
        else:
            escalate(page, tier, True, reason)

    if human:
        entry["status"], entry["reason"] = "needs-human", "; ".join(human)
    elif entry["attempt"] >= max_attempts:
        entry["status"], entry["reason"] = "needs-human", f"still failing after {entry['attempt']} attempts"
    elif not escalations:
        entry["status"] = "needs-human"
        entry["reason"] = "; ".join(unretryable) or "rubric failed without page-level issues to retry"
    else:
        entry["status"] = "retrying"
        entry["escalated_pages"] = {str(p): escalations[p] for p in sorted(escalations)}
    return entry


def page_tiers(doc: str) -> dict[int, str]:
    """Each page's body tier as extracted; triage's tier for a page with no
    merged body yet."""
    tiers = {}
    triage_path = paths.triage_json(doc)
    if triage_path.exists():
        tiers = {p["page_number"]: p["tier"] for p in json.loads(triage_path.read_text(encoding="utf-8"))["pages"]}
    for n, page in elements_lib.load_doc(paths.elements_json(doc))["pages"].items():
        tiers[n] = page["tier"]
    return tiers


def cmd_init(args) -> None:
    state = load_state()
    seen = set()
    for path in sorted(Path("input").iterdir()):
        ext = path.suffix.lstrip(".").lower()
        if ext not in paths.SUPPORTED_INPUT_EXTS:
            continue
        if path.stem in seen:
            print(f"warning: {path} shares its name with another input; only one is processed", file=sys.stderr)
            continue
        seen.add(path.stem)
        state["docs"].setdefault(path.stem, {
            "status": "pending", "attempt": 0,
            "input_format": "image" if ext in paths.IMAGE_EXTS else ext,
            "format": args.format, "escalated_pages": {}, "lang_flag": None, "tessdata_prefix": None,
        })
    save_state(state)
    print(json.dumps(summary(state)))


def cmd_next(args) -> None:
    docs = load_state()["docs"]
    names = [args.doc] if args.doc else list(docs)
    print(next((n for n in names if docs.get(n, {}).get("status") in OPEN_STATUSES), ""))


def cmd_reject(args) -> None:
    state = load_state()
    state["docs"][args.doc].update(status="needs-human", reason=args.reason)
    save_state(state)


def cmd_set(args) -> None:
    state = load_state()
    state["docs"][args.doc].update(lang_flag=args.lang_flag, tessdata_prefix=args.tessdata_prefix)
    save_state(state)


def cmd_decide(args) -> None:
    report_path = paths.grade_report_json(args.doc)
    if not report_path.exists():
        print(f"error: {report_path} not found — run merge_grades.py first", file=sys.stderr)
        sys.exit(1)
    state = load_state()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    entry = decide(state["docs"][args.doc], report, page_tiers(args.doc), args.max_attempts)
    if entry["status"] == "needs-human":
        entry["grade_report"] = str(report_path)
    state["docs"][args.doc] = entry
    save_state(state)
    out = {k: entry[k] for k in ("status", "attempt", "reason", "escalated_pages") if k in entry}
    out["warnings"] = len(entry.get("warnings", []))
    print(json.dumps({"doc": args.doc, **out}, indent=2))


def summary(state: dict) -> dict:
    counts: dict[str, int] = {}
    for entry in state["docs"].values():
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    return {
        "counts": counts,
        "needs_human": {n: e.get("reason") for n, e in state["docs"].items() if e["status"] == "needs-human"},
        "warnings": {n: len(e["warnings"]) for n, e in state["docs"].items() if e.get("warnings")},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init", help="create the queue file, add every new input/ file as pending")
    p.add_argument("--format", default="md")
    p.set_defaults(func=cmd_init)
    p = sub.add_parser("next", help="print the next pending/retrying doc, empty if none")
    p.add_argument("--doc")
    p.set_defaults(func=cmd_next)
    p = sub.add_parser("reject", help="needs-human with a reason (e.g. triage's error line)")
    p.add_argument("--doc", required=True)
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_reject)
    p = sub.add_parser("set-lang", help="record ensure_language.py's result")
    p.add_argument("--doc", required=True)
    p.add_argument("--lang-flag", required=True)
    p.add_argument("--tessdata-prefix")
    p.set_defaults(func=cmd_set)
    p = sub.add_parser("decide", help="apply grade-report.json: passed / retrying / needs-human")
    p.add_argument("--doc", required=True)
    p.add_argument("--max-attempts", type=int, default=3)
    p.set_defaults(func=cmd_decide)
    p = sub.add_parser("summary", help="status counts, needs-human reasons, warning counts")
    p.set_defaults(func=lambda a: print(json.dumps(summary(load_state()), indent=2)))
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
