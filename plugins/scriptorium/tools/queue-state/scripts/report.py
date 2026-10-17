#!/usr/bin/env python3
"""Write the end-of-run HTML report, output/report.html: a summary of the
whole queue and, per document, its attempts, durations, gates, warnings
and page grades. See README.md.

Reads runs/state.json, each document's grade-report.json and elements.json;
prints a one-line JSON summary (the orchestrator's context-rot rule).
"""

import importlib.metadata
import json
import platform
import re
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import elements as elements_lib  # noqa: E402
import grades  # noqa: E402
import paths  # noqa: E402
import tesseract as tesseract_lib  # noqa: E402

from jinja2 import Environment, FileSystemLoader

REPORT_PATH = Path("output") / "report.html"
TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
PLUGIN_ROOT = Path(__file__).resolve().parents[3]
TIERS = ("text", "ocr", "vision")
STATS = ("furniture", "images", "charts", "tables")


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


def page_stats(page: dict) -> dict:
    """Furniture graphics shown once (page 1's), figures, charts (a figure
    read into a data table) and tables on one merged page."""
    images = [el for el in page.get("elements", []) if el["type"] == "image"]
    return {
        "furniture": len(page.get("furniture_images", [])),
        "images": len(images),
        "charts": sum(1 for el in images if el.get("data_table")),
        "tables": sum(1 for el in page.get("elements", []) if el["type"] == "table"),
    }


def toc(name: str, merged: dict) -> list[dict]:
    """The printed or bookmark TOC (toc.json), else the extracted headings."""
    toc_path = paths.toc_json(name)
    entries = json.loads(toc_path.read_text(encoding="utf-8")).get("entries", []) if toc_path.exists() else []
    if entries:
        return [
            {"level": e["level"], "title": f"{e['number']} {e['title']}" if e.get("number") else e["title"], "page": e["page"]}
            for e in entries
        ]
    return [
        {"level": el["level"], "title": el["text"], "page": n}
        for n, page in sorted(merged["pages"].items())
        for el in page.get("elements", [])
        if el["type"] == "heading"
    ]


def version_number(output: str) -> str | None:
    """The first dotted version number in a tool's `--version` output."""
    match = re.search(r"\d+(?:\.\d+)+", output)
    return match.group(0) if match else None


def _command_version(command: str | None) -> str | None:
    if not command:
        return None
    try:
        result = subprocess.run([command, "--version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return version_number(result.stdout + result.stderr)


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def tool_versions() -> list[tuple[str, str]]:
    """The plugin and the tools this run's results depend on."""
    plugin = json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    versions = [
        ("scriptorium", plugin["version"]),
        ("Python", platform.python_version()),
        ("PyMuPDF", _package_version("PyMuPDF")),
        ("pdfplumber", _package_version("pdfplumber")),
        ("Tesseract", _command_version(tesseract_lib.find_tesseract())),
        ("LibreOffice", _command_version(shutil.which("soffice"))),
        ("ccusage", _command_version(shutil.which("ccusage"))),
    ]
    return [(name, version or "not installed") for name, version in versions]


def document_view(name: str, entry: dict) -> dict:
    report_path = paths.grade_report_json(name)
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    merged = elements_lib.load_doc(paths.elements_json(name))
    tiers = {n: page["tier"] for n, page in merged["pages"].items()}
    shards = {s["page_number"]: s for s in report.get("rubric_verdict", {}).get("per_page", [])}
    pages = [
        {
            "page_number": n, "score": None, **shards.get(n, {}), "tier": tiers.get(n, ""),
            "status": _page_status(shards.get(n, {}).get("issues", [])),
            "stats": page_stats(merged["pages"].get(n, {})),
        }
        for n in sorted(set(tiers) | set(shards))
    ]
    attempts = [{**a, "duration": duration(_seconds(a))} for a in entry.get("attempts", [])]
    seconds = sum(_seconds(a) for a in entry.get("attempts", []))
    costs = [a.get("cost_usd") for a in entry.get("attempts", []) if "finished_at" in a]
    # One unmeasured attempt (no ccusage, or resumed in another session) makes the total unknown.
    cost = round(sum(costs), 4) if costs and None not in costs else None
    tier_counts = Counter(tiers.values())
    return {
        "name": name,
        "entry": entry,
        "attempts": attempts,
        "seconds": seconds,
        "duration": duration(seconds),
        "cost": cost,
        "page_count": merged["page_count"] or len(pages),
        "score": report.get("rubric_verdict", {}).get("score"),
        "pages": pages,
        "checks": report.get("gates", {}).get("checks", []),
        "warnings": report.get("warnings", entry.get("warnings", [])),
        "tiers": [(t, tier_counts[t]) for t in TIERS if tier_counts[t]],
        "stats": {k: sum(p["stats"][k] for p in pages) for k in STATS},
        "toc": toc(name, merged),
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
        "stats": {k: sum(d["stats"][k] for d in docs) for k in STATS},
        "duration": duration(sum(d["seconds"] for d in docs)),
        "started": min(starts, default=None),
        "finished": max(ends, default=None),
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
    env.filters["when"] = lambda iso: datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M:%S UTC") if iso else ""
    html = env.get_template("report.html.j2").render(summary=summary, docs=docs, versions=tool_versions())
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(html, encoding="utf-8", newline="")
    print(json.dumps({"report": str(REPORT_PATH), "documents": summary["documents"],
                      "passed": summary["passed"], "needs_human": summary["needs_human"]}))


if __name__ == "__main__":
    main()
