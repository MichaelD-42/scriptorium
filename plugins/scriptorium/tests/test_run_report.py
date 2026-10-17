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


class TestContentStats:
    def _elements(self, doc, pages):
        path = paths.elements_json(doc)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"doc": doc, "page_count": len(pages), "pages": pages}))

    def test_totals_toc_and_per_page_counts(self, tmp_project):
        _queue(tmp_project, "a")
        img = {"type": "image", "asset": "assets/x.png"}
        self._elements("a", [
            {"page_number": 1, "tier": "text", "furniture_images": [{"asset": "assets/furniture1.png"}] * 2,
             "elements": [{"type": "heading", "level": 1, "text": "Intro"}, img,
                          {**img, "data_table": [["q", "v"]]}, {"type": "table", "rows": [["a"]]}]},
            {"page_number": 2, "tier": "text",
             "elements": [{"type": "heading", "level": 2, "text": "Details"}, img]},
        ])
        _grade_report("a", [{"page_number": 1, "score": 1.0, "issues": []}, {"page_number": 2, "score": 0.9, "issues": []}])

        view = report_py.document_view("a", _state(tmp_project)["a"])
        assert view["stats"] == {"furniture": 2, "images": 3, "charts": 1, "tables": 1}
        assert [(p["page_number"], p["stats"]) for p in view["pages"]] == [
            (1, {"furniture": 2, "images": 2, "charts": 1, "tables": 1}),
            (2, {"furniture": 0, "images": 1, "charts": 0, "tables": 0}),
        ]
        # No toc.json: the extracted headings are the TOC.
        assert view["toc"] == [{"level": 1, "title": "Intro", "page": 1}, {"level": 2, "title": "Details", "page": 2}]

        assert run_script("queue-state/scripts/report.py", cwd=tmp_project).returncode == 0
        html = (tmp_project / "output" / "report.html").read_text()
        assert ">Charts<" in html and ">Furniture<" in html and "Contents" in html and "Details" in html

    def test_printed_toc_wins_over_headings(self, tmp_project):
        _queue(tmp_project, "a")
        self._elements("a", [{"page_number": 1, "tier": "text", "elements": [{"type": "heading", "level": 1, "text": "X"}]}])
        paths.toc_json("a").write_text(json.dumps({"entries": [{"number": "1", "title": "Scope", "page": 3, "level": 1}]}))
        view = report_py.document_view("a", _state(tmp_project)["a"])
        assert view["toc"] == [{"level": 1, "title": "1 Scope", "page": 3}]


class TestToolVersions:
    def test_versions_list_the_plugin_and_its_tools(self, tmp_project, monkeypatch):
        plugin = json.loads((report_py.PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text())
        monkeypatch.setattr(report_py.tesseract_lib, "find_tesseract", lambda: None)
        monkeypatch.setattr(report_py.shutil, "which", lambda name: None)
        versions = dict(report_py.tool_versions())
        assert versions["scriptorium"] == plugin["version"]
        assert versions["Tesseract"] == "not installed" and versions["LibreOffice"] == "not installed"
        assert versions["PyMuPDF"][0].isdigit() and versions["pdfplumber"][0].isdigit()

    def test_command_version_keeps_the_version_number(self):
        assert report_py.version_number("tesseract 5.5.3\n leptonica-1.85.0") == "5.5.3"
        assert report_py.version_number("LibreOffice 25.2.1.2 520(Build:2)") == "25.2.1.2"

    def test_report_shows_the_versions(self, tmp_project):
        _queue(tmp_project, "a")
        assert run_script("queue-state/scripts/report.py", cwd=tmp_project).returncode == 0
        html = (tmp_project / "output" / "report.html").read_text()
        assert "scriptorium" in html and "Tesseract" in html and "PyMuPDF" in html
