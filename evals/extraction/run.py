#!/usr/bin/env python3
"""Extraction eval: run the LLM-free pipeline (triage, text layer,
Tesseract for scanned pages, figures undescribed) on each corpus document
and score the Markdown against a hand-checked reference. No agent, so two
runs on the same code give the same numbers.

    uv run --project plugins/scriptorium python evals/extraction/run.py [--corpus evals/extraction/corpus.json]

corpus.json: [{"input": "<pdf>", "reference": "<md>", "lang": "eng"}, ...],
paths relative to the repo. Scores per document:
- text: similarity of the body word sequence (headings, paragraphs, list
  items, table cells; images and their alt text left out), 0-1
- headings: share of reference (level, text) headings found, in order
- tables: F1 of the table cells
"""

import argparse
import difflib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PLUGIN = REPO / "plugins" / "scriptorium"
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def sh(root: Path, script: str, *args: str) -> str:
    result = subprocess.run(
        [sys.executable, str(PLUGIN / "tools" / script), *args],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.exit(f"error: {script} {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout


def extract(pdf: Path, lang: str, root: Path) -> str:
    doc = pdf.stem
    (root / "input").mkdir(parents=True)
    shutil.copy(pdf, root / "input" / pdf.name)
    sh(root, "pdf-triage/scripts/triage.py", "--doc", doc)
    triage = json.loads(
        (root / "work" / doc / "triage.json").read_text(encoding="utf-8")
    )
    tiers = {p["page_number"]: p["tier"] for p in triage["pages"]}
    csv = lambda pages: ",".join(map(str, pages))  # noqa: E731
    text_pages = [n for n, t in tiers.items() if t == "text"]
    scanned = [n for n, t in tiers.items() if t != "text"]
    if text_pages:
        sh(
            root,
            "extract-text/scripts/extract_text.py",
            "--doc",
            doc,
            "--pages",
            csv(text_pages),
            "--body-size",
            str(triage["body_size"]),
        )
    sh(
        root,
        "extract-images/scripts/extract_images.py",
        "--doc",
        doc,
        "--pages",
        csv(tiers),
        "--ocr-lang",
        lang,
    )
    if scanned:
        sh(
            root,
            "render-pages/scripts/render.py",
            "--doc",
            doc,
            "--pages",
            csv(scanned),
        )
        sh(
            root,
            "ocr-page/scripts/ocr.py",
            "--doc",
            doc,
            "--pages",
            csv(scanned),
            "--lang",
            lang,
        )
    sh(root, "assemble-output/scripts/merge.py", "--doc", doc)
    sh(root, "assemble-output/scripts/assemble.py", "--doc", doc, "--format", "md")
    return (root / "output" / doc / f"{doc}.md").read_text(encoding="utf-8")


def parse(md: str) -> dict:
    """Body words, (level, text) headings and table cells of a Markdown
    document; image lines, figure-text quotes and table rules are dropped."""
    words, headings, cells = [], [], []
    for line in md.splitlines():
        line = line.strip()
        if not line or line.startswith(("![", ">", "<!--", "---")):
            continue
        if line.startswith("|"):
            row = [c.strip() for c in line.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in row):
                continue
            cells += [c.lower() for c in row if c]
            words += " ".join(row).lower().split()
            continue
        m = HEADING.match(line)
        if m:
            headings.append((len(m.group(1)), m.group(2).strip().lower()))
            line = m.group(2)
        words += re.sub(r"^([-*]|\d+[.)])\s+", "", line).lower().split()
    return {"words": words, "headings": headings, "cells": cells}


def score(output_md: str, reference_md: str) -> dict:
    out, ref = parse(output_md), parse(reference_md)
    matcher = difflib.SequenceMatcher(
        None, out["headings"], ref["headings"], autojunk=False
    )
    found = sum(block.size for block in matcher.get_matching_blocks())
    common = sum(
        min(out["cells"].count(c), ref["cells"].count(c)) for c in set(ref["cells"])
    )
    precision = common / len(out["cells"]) if out["cells"] else 1.0
    recall = common / len(ref["cells"]) if ref["cells"] else 1.0
    return {
        "text": round(
            difflib.SequenceMatcher(
                None, out["words"], ref["words"], autojunk=False
            ).ratio(),
            3,
        ),
        "headings": round(found / len(ref["headings"]), 3) if ref["headings"] else 1.0,
        "tables": round(2 * precision * recall / (precision + recall), 3)
        if precision + recall
        else 0.0,
    }


def entries(corpus: Path, findings: Path) -> list[dict]:
    """The corpus entries, plus every finding folder findings.py wrote
    (paths in a finding are relative to its folder)."""
    out = [
        {**e, "input": REPO / e["input"], "reference": REPO / e["reference"]}
        for e in json.loads(corpus.read_text(encoding="utf-8"))
    ]
    for meta_path in sorted(findings.glob("*/finding.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        folder = meta_path.parent
        out.append({**meta, "input": folder / meta["input"], "reference": folder / meta["reference"]})
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=REPO / "evals" / "extraction" / "corpus.json")
    parser.add_argument("--findings", type=Path, default=REPO / "evals" / "findings")
    args = parser.parse_args()
    for entry in entries(args.corpus, args.findings.resolve()):
        with tempfile.TemporaryDirectory() as tmp:
            output_md = extract(entry["input"], entry.get("lang", "eng"), Path(tmp))
        result = {"input": str(entry["input"].relative_to(REPO)), **score(output_md, entry["reference"].read_text(encoding="utf-8"))}
        print(json.dumps(result))


if __name__ == "__main__":
    main()
