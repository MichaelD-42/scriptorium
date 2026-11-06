#!/usr/bin/env python3
"""Turn a passed document's escalations into suggested corrections for the
scripts. See README.md.

    findings.py --doc <name> --dest <dir>

A PDF page that failed its grade at `text` or `ocr` and passed after the
`vision` retry is a script defect with a checked answer: the old shard is
what the scripts made of the page, the passing page is what the grader
accepted. Each such page lands in `<dest>/<doc>-p<N>/`:

    page.pdf        the single source page
    reference.md    the passing page (a suggestion: review before committing)
    script.md       what the scripts extracted
    finding.json    source, page, tiers, the grader's reasons, the eval inputs

`evals/extraction/run.py` scores every finding folder it finds, so the
scripts are measured on each page they once got wrong.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "assemble-output" / "scripts")
)
import assemble  # noqa: E402
import elements as elements_lib  # noqa: E402
import paths  # noqa: E402

SCRIPT_TIERS = (
    "text",
    "ocr",
)  # the tiers a script produced; the lower one is the finding's


def reasons_by_page(entry: dict) -> dict[int, list[str]]:
    """Every grader/gate reason that escalated a page, attempt by attempt."""
    out: dict[int, list[str]] = {}
    for attempt in entry.get("attempts", []):
        for page, esc in (attempt.get("escalated_pages") or {}).items():
            out.setdefault(int(page), []).append(esc["reason"])
    return out


def findings(doc: str, entry: dict, doc_data: dict) -> list[dict]:
    """[{page, from_tier, reasons, script_elements, reference_elements}] for
    each page that ended at vision after a script tier was graded."""
    reasons = reasons_by_page(entry)
    out = []
    for n, page in sorted(doc_data["pages"].items()):
        if page.get("tier") != "vision" or n not in reasons:
            continue
        for tier in SCRIPT_TIERS:
            shard = elements_lib.read_shard(paths.shard_path(doc, n, tier))
            if shard and shard.get("elements"):
                body = [el for el in shard["elements"] if el.get("type") != "image"]
                reference = [el for el in page["elements"] if el.get("type") != "image"]
                out.append(
                    {
                        "page": n,
                        "from_tier": tier,
                        "reasons": reasons[n],
                        "script_elements": body,
                        "reference_elements": reference,
                    }
                )
                break
    return out


def write_finding(dest: Path, doc: str, source: Path, lang: str, finding: dict) -> Path:
    import fitz  # PyMuPDF

    folder = dest / f"{doc}-p{finding['page']}"
    folder.mkdir(parents=True, exist_ok=True)
    with fitz.open(source) as pdf, fitz.open() as one:
        one.insert_pdf(pdf, from_page=finding["page"] - 1, to_page=finding["page"] - 1)
        one.save(folder / "page.pdf")
    (folder / "reference.md").write_text(
        assemble.elements_to_markdown(finding["reference_elements"]), encoding="utf-8", newline=""
    )
    (folder / "script.md").write_text(
        assemble.elements_to_markdown(finding["script_elements"]), encoding="utf-8", newline=""
    )
    meta = {
        "source": source.name,
        "page": finding["page"],
        "from_tier": finding["from_tier"],
        "reasons": finding["reasons"],
        "status": "suggested",
        "input": "page.pdf",
        "reference": "reference.md",
        "lang": lang,
    }
    (folder / "finding.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8", newline=""
    )
    return folder


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", required=True)
    parser.add_argument(
        "--dest",
        required=True,
        type=Path,
        help="folder for the findings, e.g. evals/findings",
    )
    args = parser.parse_args()

    entry = json.loads(Path("runs/state.json").read_text(encoding="utf-8"))["docs"][
        args.doc
    ]
    if entry["status"] != "passed":
        print(
            f"error: {args.doc} is {entry['status']}; only a passed document has checked answers",
            file=sys.stderr,
        )
        sys.exit(1)
    if entry["input_format"] != "pdf":
        print(
            json.dumps(
                {
                    "doc": args.doc,
                    "findings": [],
                    "note": "findings are collected for pdf input only",
                }
            )
        )
        return
    doc_data = elements_lib.load_doc(paths.elements_json(args.doc))
    lang = entry.get("lang_flag") or "eng"
    written = [
        str(write_finding(args.dest, args.doc, paths.input_file(args.doc), lang, f))
        for f in findings(args.doc, entry, doc_data)
    ]
    print(json.dumps({"doc": args.doc, "findings": written}))


if __name__ == "__main__":
    main()
