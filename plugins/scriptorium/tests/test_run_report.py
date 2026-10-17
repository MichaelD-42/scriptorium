"""The end-of-run HTML report (queue-state/scripts/report.py) and the attempt
timing it reads from runs/state.json."""

import json

import paths
from conftest import load_script, run_script

state_py = load_script("queue-state/scripts/state.py", "queue_state_report")
report_py = load_script("queue-state/scripts/report.py", "queue_report")


def _state(cwd):
    return json.loads((cwd / "runs" / "state.json").read_text())["docs"]


def _queue(cwd, *names):
    for name in names:
        (cwd / "input" / f"{name}.html").write_text("<p>x</p>")
    assert run_script("queue-state/scripts/state.py", "init", cwd=cwd).returncode == 0


def _grade_report(doc, per_page, passed=True, checks=(), warnings=()):
    path = paths.grade_report_json(doc)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "overall_passed": passed,
                "gates": {
                    "passed": all(c["passed"] for c in checks),
                    "checks": list(checks),
                },
                "rubric_verdict": {
                    "score": round(
                        sum(p["score"] for p in per_page) / len(per_page), 3
                    ),
                    "per_page": per_page,
                },
                "warnings": list(warnings),
            }
        )
    )


class TestAttemptTiming:
    def test_next_opens_an_attempt_once_and_decide_closes_it(self, tmp_project):
        _queue(tmp_project, "a")
        run_script("queue-state/scripts/state.py", "next", cwd=tmp_project)
        run_script(
            "queue-state/scripts/state.py", "next", cwd=tmp_project
        )  # asking again starts nothing new
        attempts = _state(tmp_project)["a"]["attempts"]
        assert (
            len(attempts) == 1
            and attempts[0]["attempt"] == 0
            and "finished_at" not in attempts[0]
        )

        _grade_report("a", [{"page_number": 1, "score": 1.0, "issues": []}])
        run_script(
            "queue-state/scripts/state.py", "decide", "--doc", "a", cwd=tmp_project
        )

        done = _state(tmp_project)["a"]["attempts"][0]
        assert done["status"] == "passed" and done["score"] == 1.0
        assert done["finished_at"] >= done["started_at"]

    def test_a_retry_logs_its_escalations_and_reject_closes_the_attempt(
        self, tmp_project
    ):
        _queue(tmp_project, "a", "b")
        run_script("queue-state/scripts/state.py", "next", cwd=tmp_project)
        _grade_report(
            "a",
            [
                {
                    "page_number": 1,
                    "score": 0.5,
                    "issues": ["missing_image"],
                    "reason": "logo missing",
                }
            ],
            passed=False,
        )
        run_script(
            "queue-state/scripts/state.py", "decide", "--doc", "a", cwd=tmp_project
        )

        first = _state(tmp_project)["a"]["attempts"][0]
        assert first["status"] == "retrying"
        assert first["escalated_pages"] == {
            "1": {"tier": "text", "recheck_images": True, "reason": "logo missing"}
        }

        run_script(
            "queue-state/scripts/state.py", "next", "--doc", "b", cwd=tmp_project
        )
        run_script(
            "queue-state/scripts/state.py",
            "reject",
            "--doc",
            "b",
            "--reason",
            "error: x",
            cwd=tmp_project,
        )
        assert _state(tmp_project)["b"]["attempts"][0]["status"] == "needs-human"


class TestReport:
    def test_duration_format(self):
        assert [report_py.duration(s) for s in (0, 9, 65, 3725)] == [
            "0s",
            "9s",
            "1m 05s",
            "1h 02m",
        ]

    def test_report_summarizes_every_document_and_escapes_untrusted_text(
        self, tmp_project
    ):
        _queue(tmp_project, "good", "stuck")
        state_path = tmp_project / "runs" / "state.json"
        state = json.loads(state_path.read_text())
        state["docs"]["good"].update(
            status="passed",
            attempts=[
                {
                    "attempt": 0,
                    "started_at": "2026-10-17T10:00:00+00:00",
                    "finished_at": "2026-10-17T10:01:05+00:00",
                    "status": "passed",
                    "score": 1.0,
                }
            ],
        )
        state["docs"]["stuck"].update(
            status="needs-human",
            attempt=1,
            reason="page 2: <script>alert(1)</script>",
            attempts=[
                {
                    "attempt": 0,
                    "started_at": "2026-10-17T10:02:00+00:00",
                    "finished_at": "2026-10-17T10:02:30+00:00",
                    "status": "needs-human",
                }
            ],
        )
        state_path.write_text(json.dumps(state))
        _grade_report("good", [{"page_number": 1, "score": 1.0, "issues": []}])
        _grade_report(
            "stuck",
            [
                {"page_number": 1, "score": 1.0, "issues": []},
                {
                    "page_number": 2,
                    "score": 0.3,
                    "issues": ["dropped_text"],
                    "reason": "<b>table</b> gone",
                },
            ],
            passed=False,
            warnings=[
                {"name": "orphan_figure_caption", "page": 2, "caption": "Figure 9"}
            ],
        )

        result = run_script("queue-state/scripts/report.py", cwd=tmp_project)

        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == {
            "report": "output/report.html",
            "documents": 2,
            "passed": 1,
            "needs_human": 1,
        }
        html = (tmp_project / "output" / "report.html").read_text()
        assert (
            "<script>alert" not in html
            and "&lt;script&gt;alert(1)&lt;/script&gt;" in html
        )
        assert "&lt;b&gt;table&lt;/b&gt; gone" in html
        assert "1m 05s" in html and "1m 35s" in html  # per document, and the run total
        assert "orphan_figure_caption" in html and "dropped_text" in html

    def test_report_with_an_empty_queue(self, tmp_project):
        result = run_script("queue-state/scripts/report.py", cwd=tmp_project)
        assert result.returncode == 0, result.stderr
        assert "No documents" in (tmp_project / "output" / "report.html").read_text()
