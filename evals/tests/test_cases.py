"""Acceptance over the grader calibration set (evals/grader/prepare.py):
every injected defect is visible in the assembled output, the gates catch
the one they own, and each tag, written by an oracle grader that knows the
answer, takes the route the rubric promises through merge_grades.py and
decide. No LLM; /eval-grader runs real graders on the same cases."""

import importlib.util
import json
from pathlib import Path

import pytest

import elements as elements_lib
import grades
import prepare

REPO = Path(__file__).resolve().parents[2]
PLUGIN = REPO / "plugins" / "scriptorium"
_spec = importlib.util.spec_from_file_location("queue_state", PLUGIN / "tools" / "queue-state" / "scripts" / "state.py")
state = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(state)


@pytest.fixture(scope="module")
def eval_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("evalrun")
    prepare.stage(root)
    return root


def _cases(root):
    return {c["doc"]: c for c in json.loads((root / "cases.json").read_text())}


def _md(root, doc):
    return (root / "output" / doc / f"{doc}.md").read_text()


def test_every_mutation_changes_the_output_and_names_a_known_tag(eval_root):
    cases = _cases(eval_root)
    assert len(cases) == 1 + len(prepare.MUTATIONS)
    clean = _md(eval_root, "eval-furniture-clean")
    for doc, case in cases.items():
        if case["expected"]:
            assert _md(eval_root, doc) != clean, doc
            assert set(case["expected"].values()) <= grades.ISSUES


def test_text_layer_coverage_catches_the_dropped_paragraph_on_a_text_page(eval_root):
    for doc, should_fail in (
        ("eval-furniture-dropped-text", True),
        ("eval-furniture-clean", False),
    ):
        path = eval_root / "work" / doc / "elements.json"
        data = elements_lib.load_doc(path)
        for page in data["pages"].values():
            page["tier"] = "text"
        elements_lib.save_doc(path, data)
        prepare.sh(eval_root, "grade-output/scripts/gates.py", "--doc", doc, "--no-describe")
        report = json.loads((eval_root / "work" / doc / "gates-report.json").read_text(encoding="utf-8"))
        check = next(c for c in report["checks"] if c["name"] == "text_layer_coverage")
        assert check["passed"] is not should_fail, check["detail"]
        if should_fail:
            assert check["pages"] == [
                int(next(iter(_cases(eval_root)[doc]["expected"])))
            ]


def _route(tag):
    if tag is None or tag not in grades.BLOCKING_ISSUES:
        return "passed"  # bad_caption/bad_mermaid count through the average only
    # The fixture prints a TOC: toc_headings_match catches a changed level
    # before any grader, and that gate goes to a human.
    if tag in grades.JOIN_ISSUES or tag == "wrong_heading_level":
        return "needs-human"
    if tag in grades.CONTENT_ISSUES:
        return "vision"
    return "recheck_images"


def test_each_tag_routes_as_the_rubric_says(eval_root):
    for doc, case in _cases(eval_root).items():
        page_count = json.loads((eval_root / "work" / doc / "triage.json").read_text())[
            "page_count"
        ]
        for n in range(1, page_count + 1):
            tag = case["expected"].get(str(n))
            prepare.sh(
                eval_root,
                "grade-output/scripts/write_grade_shard.py",
                "--doc",
                doc,
                "--page",
                str(n),
                *(["--issues", tag] if tag else []),
            )
        prepare.sh(eval_root, "grade-output/scripts/merge_grades.py", "--doc", doc)
        report = json.loads(
            (eval_root / "output" / doc / "grade-report.json").read_text()
        )
        entry = {
            "status": "pending",
            "attempt": 0,
            "input_format": "pdf",
            "format": "md",
            "escalated_pages": {},
        }
        out = state.decide(
            entry, report, {n: "text" for n in range(1, page_count + 1)}, max_attempts=3
        )

        ((page, tag),) = case["expected"].items() or [(None, None)]
        route = _route(tag)
        if route in ("passed", "needs-human"):
            assert out["status"] == route, (doc, out)
        else:
            assert out["status"] == "retrying", (doc, out)
            escalated = out["escalated_pages"][page]
            assert escalated["tier"] == ("vision" if route == "vision" else "text"), doc
            assert escalated["recheck_images"] is (route == "recheck_images"), doc
