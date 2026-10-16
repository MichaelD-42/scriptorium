"""queue-state: the queue file and the pass / retry / needs-human decision,
as a script instead of orchestrator prose."""

import json
import shutil

import paths
from conftest import EXAMPLES_ROOT, load_script, run_script

state = load_script("queue-state/scripts/state.py", "queue_state")


def _entry(input_format="pdf", attempt=0):
    return {
        "status": "pending",
        "attempt": attempt,
        "input_format": input_format,
        "format": "md",
        "escalated_pages": {},
        "lang_flag": None,
        "tessdata_prefix": None,
    }


def _report(per_page=(), checks=(), passed=False, warnings=()):
    return {
        "overall_passed": passed,
        "gates": {"passed": all(c["passed"] for c in checks), "checks": list(checks)},
        "rubric_verdict": {"per_page": list(per_page)},
        "warnings": list(warnings),
    }


def _page(n, issues, reason=None):
    shard = {"page_number": n, "score": 0.5 if issues else 1.0, "issues": issues}
    if reason:
        shard["reason"] = reason
    return shard


def _decide(report, tiers, input_format="pdf", attempt=0, max_attempts=3):
    return state.decide(_entry(input_format, attempt), report, tiers, max_attempts)


class TestDecide:
    def test_pass_records_warnings(self):
        warning = {"name": "orphan_figure_caption", "page": 2, "caption": "Figure 3"}
        out = _decide(_report(passed=True, warnings=[warning]), {1: "text"})
        assert out["status"] == "passed"
        assert out["warnings"] == [warning]
        assert out["escalated_pages"] == {}

    def test_pdf_content_issue_bumps_text_to_ocr_with_the_graders_reason(self):
        out = _decide(
            _report([_page(3, ["dropped_text"], "second paragraph missing")]),
            {3: "text"},
        )
        assert out["status"] == "retrying"
        assert out["attempt"] == 1
        assert out["escalated_pages"] == {
            "3": {
                "tier": "ocr",
                "recheck_images": False,
                "reason": "second paragraph missing",
            }
        }

    def test_pdf_ocr_page_goes_to_vision(self):
        out = _decide(_report([_page(1, ["hallucinated_text"])]), {1: "ocr"})
        assert out["escalated_pages"]["1"]["tier"] == "vision"
        assert out["escalated_pages"]["1"]["reason"] == "hallucinated_text"

    def test_page_already_at_vision_is_needs_human(self):
        out = _decide(
            _report([_page(1, ["dropped_text"]), _page(2, ["dropped_text"])]),
            {1: "vision", 2: "text"},
        )
        assert out["status"] == "needs-human"
        assert "page 1" in out["reason"]
        assert out["escalated_pages"] == {}

    def test_pptx_has_no_ocr_rung(self):
        out = _decide(
            _report([_page(2, ["wrong_reading_order"])]),
            {2: "text"},
            input_format="pptx",
        )
        assert out["escalated_pages"]["2"]["tier"] == "vision"

    def test_image_ocr_goes_to_vision(self):
        out = _decide(
            _report([_page(1, ["dropped_text"])]), {1: "ocr"}, input_format="image"
        )
        assert out["escalated_pages"]["1"]["tier"] == "vision"

    def test_digital_native_content_issue_is_needs_human_at_once(self):
        out = _decide(
            _report([_page(1, ["table_corruption"])]), {1: "text"}, input_format="docx"
        )
        assert out["status"] == "needs-human"
        assert out["attempt"] == 1

    def test_image_issue_keeps_the_tier_and_rechecks_images(self):
        out = _decide(
            _report([_page(1, ["missing_image"])]), {1: "text"}, input_format="html"
        )
        assert out["status"] == "retrying"
        assert out["escalated_pages"]["1"] == {
            "tier": "text",
            "recheck_images": True,
            "reason": "missing_image",
        }

    def test_content_and_image_issue_on_one_page(self):
        out = _decide(_report([_page(4, ["dropped_text", "bad_caption"])]), {4: "text"})
        assert out["escalated_pages"]["4"]["tier"] == "ocr"
        assert out["escalated_pages"]["4"]["recheck_images"] is True

    def test_figures_complete_gate_rechecks_its_pages(self):
        check = {
            "name": "figures_complete",
            "passed": False,
            "detail": "page 2: image without text",
            "pages": [2],
        }
        out = _decide(_report(checks=[check]), {2: "ocr"})
        assert out["escalated_pages"] == {
            "2": {
                "tier": "ocr",
                "recheck_images": True,
                "reason": "page 2: image without text",
            }
        }

    def test_furniture_gate_is_needs_human(self):
        check = {
            "name": "furniture_absent",
            "passed": False,
            "detail": "title block on page 3",
            "pages": [3],
        }
        out = _decide(
            _report([_page(1, ["missing_image"])], checks=[check]), {1: "text"}
        )
        assert out["status"] == "needs-human"
        assert "furniture_absent" in out["reason"]

    def test_last_attempt_is_needs_human(self):
        out = _decide(
            _report([_page(1, ["dropped_text"])]),
            {1: "text"},
            attempt=2,
            max_attempts=3,
        )
        assert out["status"] == "needs-human"
        assert out["attempt"] == 3

    def test_failure_with_nothing_to_retry_is_needs_human(self):
        """A document-level gate, or low scores with no tags, gives no page
        to re-extract; a retry would rerun nothing and burn an attempt."""
        check = {
            "name": "page_count_match",
            "passed": False,
            "detail": "expected 5 pages, elements.json has 4",
        }
        out = _decide(_report([_page(1, [])], checks=[check]), {1: "text"})
        assert out["status"] == "needs-human"
        assert "page_count_match" in out["reason"]


class TestCli:
    def _state(self):
        return json.loads((paths.Path("runs/state.json")).read_text())

    def test_init_next_reject(self, tmp_project):
        shutil.copyfile(EXAMPLES_ROOT / "sample.pdf", tmp_project / "input" / "b.pdf")
        shutil.copyfile(EXAMPLES_ROOT / "sample.png", tmp_project / "input" / "a.png")

        result = run_script(
            "queue-state/scripts/state.py", "init", "--format", "html", cwd=tmp_project
        )
        assert result.returncode == 0, result.stderr
        docs = self._state()["docs"]
        assert docs["a"]["input_format"] == "image" and docs["b"]["format"] == "html"

        assert (
            run_script(
                "queue-state/scripts/state.py", "next", cwd=tmp_project
            ).stdout.strip()
            == "a"
        )
        run_script(
            "queue-state/scripts/state.py",
            "reject",
            "--doc",
            "a",
            "--reason",
            "error: bad",
            cwd=tmp_project,
        )
        assert self._state()["docs"]["a"]["status"] == "needs-human"
        assert (
            run_script(
                "queue-state/scripts/state.py", "next", cwd=tmp_project
            ).stdout.strip()
            == "b"
        )

    def test_decide_reads_report_and_actual_tiers(self, tmp_project):
        shutil.copyfile(EXAMPLES_ROOT / "sample.pdf", tmp_project / "input" / "s.pdf")
        run_script(
            "queue-state/scripts/state.py", "init", "--format", "md", cwd=tmp_project
        )
        # The extractor escalated page 1 to vision on its own; the shard tier is the truth.
        paths.elements_json("s").parent.mkdir(parents=True)
        paths.elements_json("s").write_text(
            json.dumps(
                {"pages": [{"page_number": 1, "tier": "vision", "elements": []}]}
            )
        )
        paths.grade_report_json("s").parent.mkdir(parents=True)
        paths.grade_report_json("s").write_text(
            json.dumps(_report([_page(1, ["dropped_text"])]))
        )

        result = run_script(
            "queue-state/scripts/state.py",
            "decide",
            "--doc",
            "s",
            "--max-attempts",
            "3",
            cwd=tmp_project,
        )

        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["status"] == "needs-human"
        assert self._state()["docs"]["s"]["status"] == "needs-human"
