#!/usr/bin/env python3
"""Write the end-of-run HTML report, output/report.html: a summary of the
whole queue and, per document, its attempts, durations, gates, warnings
and page grades. See SKILL.md.

Reads runs/state.json, each document's grade-report.json and elements.json;
prints a one-line JSON summary (the orchestrator's context-rot rule).
"""

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import elements as elements_lib  # noqa: E402
import grades  # noqa: E402
import paths  # noqa: E402

from jinja2 import Environment, FileSystemLoader

REPORT_PATH = Path("output") / "report.html"
TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
TIERS = ("text", "ocr", "vision")


def duration(seconds: float) -> str:
    s = int(round(seconds))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    return f"{s // 3600}h {s % 3600 // 60:02d}m"


def _seconds(attempt: dict) -> float:
    if "finished_at" not in attempt:
        return 0.0
    return (datetime.fromisoformat(attempt["finished_at"]) - datetime.fromisoformat(attempt["started_at"])).total_seconds()


def _page_status(issues: list[str]) -> str:
    if grades.CONTENT_ISSUES & set(issues):
        return "critical"
    return "warning" if issues else "good"


def document_view(name: str, entry: dict) -> dict:
    report_path = paths.grade_report_json(name)
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    merged = elements_lib.load_doc(paths.elements_json(name))
    tiers = {n: page["tier"] for n, page in merged["pages"].items()}
    pages = [
        {**shard, "tier": tiers.get(shard["page_number"], ""), "status": _page_status(shard.get("issues", []))}
        for shard in report.get("rubric_verdict", {}).get("per_page", [])
    ]
    attempts = [{**a, "duration": duration(_seconds(a))} for a in entry.get("attempts", [])]
    seconds = sum(_seconds(a) for a in entry.get("attempts", []))
    tier_counts = Counter(tiers.values())
    return {
        "name": name,
        "entry": entry,
        "attempts": attempts,
        "seconds": seconds,
        "duration": duration(seconds),
        "page_count": merged["page_count"] or len(pages),
        "score": report.get("rubric_verdict", {}).get("score"),
        "pages": pages,
        "checks": report.get("gates", {}).get("checks", []),
        "warnings": report.get("warnings", entry.get("warnings", [])),
        "tiers": [(t, tier_counts[t]) for t in TIERS if tier_counts[t]],
    }


def main() -> None:
    state_path = Path("runs") / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"docs": {}}
    docs = [document_view(name, entry) for name, entry in state["docs"].items()]
    statuses = Counter(d["entry"]["status"] for d in docs)
    starts = [a["started_at"] for d in docs for a in d["attempts"]]
    ends = [a["finished_at"] for d in docs for a in d["attempts"] if "finished_at" in a]
    summary = {
        "documents": len(docs),
        "passed": statuses["passed"],
        "needs_human": statuses["needs-human"],
        "open": statuses["pending"] + statuses["retrying"],
        "pages": sum(d["page_count"] for d in docs),
        "attempts": sum(len(d["attempts"]) for d in docs),
        "duration": duration(sum(d["seconds"] for d in docs)),
        "started": min(starts, default=None),
        "finished": max(ends, default=None),
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
    env.filters["when"] = lambda iso: datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M:%S UTC") if iso else ""
    html = env.get_template("report.html.j2").render(summary=summary, docs=docs)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(html, encoding="utf-8", newline="")
    print(json.dumps({"report": str(REPORT_PATH), "documents": summary["documents"],
                      "passed": summary["passed"], "needs_human": summary["needs_human"]}))


if __name__ == "__main__":
    main()
