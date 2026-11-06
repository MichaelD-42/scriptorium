#!/usr/bin/env python3
"""The grader calibration set: one synthetic document, extracted by the
scripts alone (correct by construction: the test suite checks it against
furniture_golden.json), copied once per known defect.

The cases are committed in `evals/grader/cases/`: per case its mutated
`elements.json`, plus the base document's `triage.json`, `toc.json` and
image assets, shared by every case; the source is
`plugins/scriptorium/examples/furniture_sample.pdf`. `cases.json` records,
per case, the pages a grader should grade and the tag it should find. Every
page is marked tier `vision`, so the grader owns every rubric criterion (on
a `text` page, dropped text is the `text_layer_coverage` gate's job).

    uv run --project plugins/scriptorium python evals/grader/prepare.py --build
        regenerate the committed cases (after a mutation or extraction change)
    uv run --project plugins/scriptorium python evals/grader/prepare.py [--root evals/run]
        stage the committed cases as a project for graders: input PDFs,
        rendered pages, assembled Markdown, gates report
"""

import argparse
import copy
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PLUGIN = REPO / "plugins" / "scriptorium"
sys.path.insert(0, str(PLUGIN / "lib"))
import elements as elements_lib  # noqa: E402

SOURCE = PLUGIN / "examples" / "furniture_sample.pdf"
INVENTED = (
    "The controller also uploads every reading to a public cloud service each night."
)


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


def extract_base(root: Path, doc: str) -> None:
    (root / "input").mkdir(parents=True, exist_ok=True)
    shutil.copy(SOURCE, root / "input" / f"{doc}.pdf")
    sh(root, "pdf-triage/scripts/triage.py", "--doc", doc)
    triage = json.loads(
        (root / "work" / doc / "triage.json").read_text(encoding="utf-8")
    )
    pages = ",".join(str(p["page_number"]) for p in triage["pages"])
    sh(
        root,
        "extract-text/scripts/extract_text.py",
        "--doc",
        doc,
        "--pages",
        pages,
        "--body-size",
        str(triage["body_size"]),
    )
    sh(root, "extract-images/scripts/extract_images.py", "--doc", doc, "--pages", pages)
    sh(root, "assemble-output/scripts/merge.py", "--doc", doc)


# --- mutations: each edits `pages` in place, returns the page it broke ------


def _texts(page: dict, kind: str = "paragraph") -> list[dict]:
    return [el for el in page["elements"] if el["type"] == kind and not el.get("pages")]


def _first(pages: dict, fits) -> int:
    return next(n for n in sorted(pages) if fits(pages[n]))


def drop_paragraph(pages):
    n = _first(pages, lambda p: len(_texts(p)) >= 2)
    pages[n]["elements"].remove(max(_texts(pages[n]), key=lambda el: len(el["text"])))
    return n


def duplicate_paragraph(pages):
    n = _first(pages, lambda p: len(_texts(p)) >= 2)
    el = _texts(pages[n])[0]
    els = pages[n]["elements"]
    els.insert(els.index(el) + 1, dict(el))
    return n


def swap_paragraphs(pages):
    n = _first(pages, lambda p: len(_texts(p)) >= 3)
    els, texts = pages[n]["elements"], _texts(pages[n])
    i, j = els.index(texts[0]), els.index(texts[-1])
    els[i], els[j] = els[j], els[i]
    return n


def invent_sentence(pages):
    n = _first(pages, lambda p: len(_texts(p)) >= 1)
    el = _texts(pages[n])[0]
    el["text"] = f"{el['text']} {INVENTED}"
    return n


def shift_heading_level(pages):
    n = _first(
        pages, lambda p: any(el.get("level", 0) >= 2 for el in _texts(p, "heading"))
    )
    el = next(el for el in _texts(pages[n], "heading") if el["level"] >= 2)
    el["level"] = 4 if el["level"] == 2 else 1
    return n


def corrupt_table(pages):
    n = _first(
        pages, lambda p: any(len(el.get("rows", [])) >= 3 for el in _texts(p, "table"))
    )
    table = next(el for el in _texts(pages[n], "table") if len(el["rows"]) >= 3)
    del table["rows"][-1]
    table["rows"][1][-1] = "999"
    return n


def remove_image(pages):
    n = _first(pages, lambda p: any(el.get("caption") for el in _texts(p, "image")))
    pages[n]["elements"].remove(
        next(el for el in _texts(pages[n], "image") if el.get("caption"))
    )
    return n


def wrong_caption(pages):
    n = _first(pages, lambda p: any(el.get("caption") for el in _texts(p, "image")))
    el = next(el for el in _texts(pages[n], "image") if el.get("caption"))
    el["caption"] = "Figure 9: Installation Checklist"
    return n


def split_joined_paragraph(pages):
    """Undo a page-break join at the real break: the cut sentence becomes
    two paragraphs, the second starting where page n+1's text layer does."""
    import fitz  # PyMuPDF

    n = _first(pages, lambda p: any(el.get("pages") for el in p["elements"]))
    el = next(el for el in pages[n]["elements"] if el.get("pages"))
    with fitz.open(SOURCE) as pdf:
        next_page_lines = pdf[n].get_text().splitlines()  # pdf[n] is page n+1
    # The continuation starts at the first page n+1 line found in the joined text.
    cut = next(el["text"].find(line) for line in next_page_lines if len(line) > 10 and line in el["text"])
    el["text"], rest = el["text"][:cut].rstrip(), el["text"][cut:]
    del el["pages"]
    pages[n + 1]["elements"].insert(0, {"type": "paragraph", "text": rest})
    return n


MUTATIONS = {
    "dropped_text": drop_paragraph,
    "duplicated_text": duplicate_paragraph,
    "wrong_reading_order": swap_paragraphs,
    "hallucinated_text": invent_sentence,
    "wrong_heading_level": shift_heading_level,
    "table_corruption": corrupt_table,
    "missing_image": remove_image,
    "bad_caption": wrong_caption,
    "split_paragraph": split_joined_paragraph,
}


CASES = REPO / "evals" / "grader" / "cases"
BASE = "eval-furniture"


def build() -> None:
    """Extract the base document in a scratch project, write every case's
    mutated elements.json and the shared files into CASES."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        extract_base(root, BASE)
        shutil.rmtree(CASES, ignore_errors=True)
        CASES.mkdir(parents=True)
        for name in ("triage.json", "toc.json"):
            shutil.copy(root / "work" / BASE / name, CASES / name)
        shutil.copytree(root / "output" / BASE / "assets", CASES / "assets")
        base = elements_lib.load_doc(root / "work" / BASE / "elements.json")
        cases = []
        for name, mutate in [("clean", None), *MUTATIONS.items()]:
            doc = f"{BASE}-{name.replace('_', '-')}"
            data = copy.deepcopy(base)
            data["doc"] = doc
            for page in data["pages"].values():
                page["tier"] = "vision"
            page = mutate(data["pages"]) if mutate else None
            (CASES / doc).mkdir()
            elements_lib.save_doc(CASES / doc / "elements.json", data)
            if page is None:  # the clean case: three pages, no tag expected anywhere
                cases.append({"doc": doc, "pages": [4, 7, 8], "expected": {}})
                continue
            control = page + 2 if page + 2 <= len(data["pages"]) else page - 2  # untouched: false positives
            cases.append({"doc": doc, "pages": sorted({page, control}), "expected": {str(page): name}})
    (CASES / "cases.json").write_text(json.dumps(cases, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"cases": str(CASES), "count": len(cases)}))


def stage(root: Path) -> None:
    """Lay the committed cases out as a project graders can work in."""
    cases = json.loads((CASES / "cases.json").read_text(encoding="utf-8"))
    for case in cases:
        doc = case["doc"]
        for sub in ("work", "output"):
            shutil.rmtree(root / sub / doc, ignore_errors=True)
        (root / "input").mkdir(parents=True, exist_ok=True)
        shutil.copy(SOURCE, root / "input" / f"{doc}.pdf")
        (root / "work" / doc).mkdir(parents=True)
        for name in ("triage.json", "toc.json"):
            shutil.copy(CASES / name, root / "work" / doc / name)
        shutil.copy(CASES / doc / "elements.json", root / "work" / doc / "elements.json")
        shutil.copytree(CASES / "assets", root / "output" / doc / "assets")
        sh(root, "render-pages/scripts/render.py", "--doc", doc, "--pages", ",".join(map(str, case["pages"])))
        sh(root, "assemble-output/scripts/assemble.py", "--doc", doc, "--format", "md")
        sh(root, "grade-output/scripts/gates.py", "--doc", doc, "--no-describe")
    shutil.copy(CASES / "cases.json", root / "cases.json")
    print(json.dumps({"root": str(root), "cases": len(cases), "page_grades": sum(len(c["pages"]) for c in cases)}))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true", help="regenerate the committed cases")
    parser.add_argument("--root", type=Path, default=REPO / "evals" / "run", help="where to stage the cases")
    args = parser.parse_args()
    if args.build:
        build()
    else:
        stage(args.root.resolve())


if __name__ == "__main__":
    main()
