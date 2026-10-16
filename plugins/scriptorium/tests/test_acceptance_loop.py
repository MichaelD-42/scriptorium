"""Acceptance: the /scriptorium:extract queue loop, end to end.

`Orchestrator` follows commands/extract.md step by step and runs every
script the way the orchestrator does (subprocess, CLI arguments, compact
stdout only). The two subagents are the only fakes: `extractor` lands a
vision transcription for each ocr/vision page and describes its batch's
images; `grader` writes grade shards. A test swaps in a grader that finds
a defect to drive the retry and needs-human paths. When a script contract
in extract.md changes, these tests are meant to fail.
"""

import json
import shutil

from conftest import EXAMPLES_ROOT, describe_all_images, run_script

import paths

FORMAT_EXTRACT = {
    "pptx": "pptx-extract/scripts/extract_pptx.py",
    "docx": "docx-extract/scripts/extract_docx.py",
    "xlsx": "xlsx-extract/scripts/extract_xlsx.py",
    "html": "html-extract/scripts/extract_html.py",
}


def clean_grader(orch, doc, batch, attempt):
    for page in batch["pages"]:
        orch.sh(
            "grade-output/scripts/write_grade_shard.py",
            "--doc",
            doc,
            "--page",
            str(page),
            "--score",
            "1.0",
        )


class Orchestrator:
    def __init__(self, cwd, grader=clean_grader, max_attempts=3):
        self.cwd, self.grader, self.max_attempts = cwd, grader, max_attempts
        self.extractor_batches: list[dict] = []
        self.grader_batches: list[dict] = []
        self.body_size: dict[str, float] = {}

    def sh(self, script, *args):
        result = run_script(script, *args, cwd=self.cwd)
        assert result.returncode == 0, f"{script} {args}\n{result.stderr}"
        return result.stdout

    def state(self):
        return json.loads((self.cwd / "runs" / "state.json").read_text())["docs"]

    def run(self) -> dict:
        self.sh("queue-state/scripts/state.py", "init", "--format", "md")
        for _ in range(20):  # guard: a loop bug must fail the test, not hang it
            doc = self.sh("queue-state/scripts/state.py", "next").strip()
            if not doc:
                return json.loads(self.sh("queue-state/scripts/state.py", "summary"))
            self.attempt(doc)
        raise AssertionError("queue loop did not terminate")

    def attempt(self, doc):
        entry = self.state()[doc]
        fmt = entry["input_format"]
        if entry["attempt"] == 0:  # step 1
            result = run_script(
                f"{fmt}-triage/scripts/triage.py", "--doc", doc, cwd=self.cwd
            )
            if result.returncode == 1:
                self.sh(
                    "queue-state/scripts/state.py",
                    "reject",
                    "--doc",
                    doc,
                    "--reason",
                    result.stderr.splitlines()[0],
                )
                return
            assert result.returncode == 0, result.stderr
            self.body_size[doc] = json.loads(result.stdout).get("body_size", 0)

        scripts = json.loads(
            self.sh("queue-state/scripts/plan.py", "--doc", doc, "--stage", "scripts")
        )  # 2a
        if scripts.get("extract_text"):
            self.sh(
                "extract-text/scripts/extract_text.py",
                "--doc",
                doc,
                "--pages",
                ",".join(map(str, scripts["extract_text"])),
                "--body-size",
                str(self.body_size[doc]),
            )
        if scripts.get("extract_images"):
            self.sh(
                "extract-images/scripts/extract_images.py",
                "--doc",
                doc,
                "--pages",
                ",".join(map(str, scripts["extract_images"])),
            )
        if scripts.get("format_extract"):
            self.sh(
                FORMAT_EXTRACT[fmt],
                "--doc",
                doc,
                "--pages",
                ",".join(map(str, scripts["format_extract"])),
            )

        plan = json.loads(
            self.sh("queue-state/scripts/plan.py", "--doc", doc, "--stage", "extract")
        )  # 2b
        for batch in plan["batches"]:
            self.extract(doc, batch)

        self.sh("assemble-output/scripts/merge.py", "--doc", doc)  # 3
        self.sh("assemble-output/scripts/assemble.py", "--doc", doc, "--format", "md")
        self.sh("grade-output/scripts/gates.py", "--doc", doc, "--format", "md")

        grade_plan = json.loads(
            self.sh("queue-state/scripts/plan.py", "--doc", doc, "--stage", "grade")
        )  # 4
        if grade_plan["text_mode"]:
            self.sh("grade-output/scripts/text_mode_grade.py", "--doc", doc)
        for batch in grade_plan["batches"]:
            self.grader_batches.append(
                {"doc": doc, "attempt": entry["attempt"], **batch}
            )
            self.grader(self, doc, batch, entry["attempt"])
        self.sh(
            "grade-output/scripts/merge_grades.py",
            "--doc",
            doc,
            "--attempt",
            str(entry["attempt"]),
        )

        self.sh(
            "queue-state/scripts/state.py",
            "decide",
            "--doc",
            doc,
            "--max-attempts",
            str(self.max_attempts),
        )  # 5

    def extract(self, doc, batch):
        """The fake extractor: only its own pages, as agents/extractor.md says."""
        self.extractor_batches.append({"doc": doc, **batch})
        for page, tier in batch["tiers"].items():
            if tier in ("ocr", "vision"):
                result = run_script(
                    "ocr-page/scripts/write_vision_page.py",
                    "--doc",
                    doc,
                    "--page",
                    page,
                    cwd=self.cwd,
                    stdin=json.dumps(
                        [
                            {
                                "type": "paragraph",
                                "text": f"Transcribed page {page}.",
                                "bbox": [72, 72, 500, 90],
                            }
                        ]
                    ),
                )
                assert result.returncode == 0, result.stderr
        describe_all_images(doc, self.cwd, pages=set(batch["pages"]))


def _add(tmp_project, name, src):
    shutil.copyfile(EXAMPLES_ROOT / src, tmp_project / "input" / name)


def _pages(batches, doc, attempt=None):
    return [
        p
        for b in batches
        if b["doc"] == doc and (attempt is None or b.get("attempt") == attempt)
        for p in b["pages"]
    ]


class TestEveryFormatPasses:
    def test_mixed_queue_all_pass_with_agents_only_where_needed(self, tmp_project):
        for src in (
            "sample.pdf",
            "furniture_sample.pdf",
            "sample.pptx",
            "sample.docx",
            "sample.xlsx",
            "sample.html",
            "sample.png",
        ):
            _add(
                tmp_project,
                src.replace("sample.", "s_") + src[src.index("."):] if src.startswith("sample") else src,
                src,
            )

        orch = Orchestrator(tmp_project)
        summary = orch.run()

        assert summary["counts"] == {"passed": 7}, summary
        for doc in (
            "s_pdf",
            "furniture_sample",
            "s_pptx",
            "s_docx",
            "s_xlsx",
            "s_html",
            "s_png",
        ):
            assert paths.output_file(doc, "md").exists()
        # A page reaches at most one extractor and one grader per attempt.
        for batches in (orch.extractor_batches, orch.grader_batches):
            pages = [
                (b["doc"], b.get("attempt"), p) for b in batches for p in b["pages"]
            ]
            assert len(pages) == len(set(pages))
        # Text-mode formats never spawn a grader.
        assert not [
            b for b in orch.grader_batches if b["doc"] in ("s_docx", "s_xlsx", "s_html")
        ]
        # The scanned page 5 of sample.pdf goes to an extractor at tier ocr;
        # text-only pages of furniture_sample.pdf never reach an agent.
        assert "5" in [
            t
            for b in orch.extractor_batches
            if b["doc"] == "s_pdf"
            for t, tier in b["tiers"].items()
            if tier == "ocr"
        ]
        extracted = set(_pages(orch.extractor_batches, "furniture_sample"))
        assert extracted and extracted < set(range(1, 12))


class TestRetryCarriesTheGradersReason:
    def test_dropped_text_escalates_one_page_and_passes_on_attempt_1(self, tmp_project):
        _add(tmp_project, "s.pdf", "sample.pdf")

        def grader(orch, doc, batch, attempt):
            for page in batch["pages"]:
                bad = attempt == 0 and page == 2
                args = (
                    [
                        "--issues",
                        "dropped_text",
                        "--reason",
                        "table caption line missing",
                    ]
                    if bad
                    else []
                )
                orch.sh(
                    "grade-output/scripts/write_grade_shard.py",
                    "--doc",
                    doc,
                    "--page",
                    str(page),
                    "--score",
                    "0.0" if bad else "1.0",
                    *args,
                )

        orch = Orchestrator(tmp_project, grader=grader)
        summary = orch.run()

        assert summary["counts"] == {"passed": 1}
        assert orch.state()["s"]["attempt"] == 1
        retry = [b for b in orch.extractor_batches if b.get("reasons")]
        assert retry == [
            {
                "doc": "s",
                "pages": [2],
                "tiers": {"2": "ocr"},
                "recheck_images": [],
                "reasons": {"2": "table caption line missing"},
            }
        ]
        assert _pages(orch.grader_batches, "s", attempt=1) == [2]
        elements = json.loads(paths.elements_json("s").read_text())
        assert elements["pages"][1]["tier"] == "vision"


class TestNeedsHuman:
    def test_unreadable_input_is_rejected_and_the_queue_moves_on(self, tmp_project):
        (tmp_project / "input" / "a_broken.pdf").write_text("not a pdf")
        _add(tmp_project, "b_ok.html", "sample.html")

        summary = Orchestrator(tmp_project).run()

        assert summary["counts"] == {"needs-human": 1, "passed": 1}
        assert summary["needs_human"]["a_broken"].startswith("error: ")

    def test_a_failing_vision_page_has_no_tier_left(self, tmp_project):
        _add(tmp_project, "s.pdf", "sample.pdf")

        def grader(orch, doc, batch, attempt):
            for page in batch["pages"]:
                issues = ["--issues", "hallucinated_text"] if page == 5 else []
                orch.sh(
                    "grade-output/scripts/write_grade_shard.py",
                    "--doc",
                    doc,
                    "--page",
                    str(page),
                    "--score",
                    "0.0" if issues else "1.0",
                    *issues,
                )

        orch = Orchestrator(tmp_project, grader=grader)
        summary = orch.run()

        # Page 5 was transcribed at vision on attempt 0 (the fake extractor's
        # fallback); decide reads that actual tier, so there is no retry.
        assert summary["counts"] == {"needs-human": 1}
        assert "already at tier vision" in summary["needs_human"]["s"]
        assert orch.state()["s"]["attempt"] == 1

    def test_max_attempts_stops_a_retryable_failure(self, tmp_project):
        _add(tmp_project, "s.pdf", "sample.pdf")

        def grader(orch, doc, batch, attempt):
            for page in batch["pages"]:
                issues = ["--issues", "missing_image"] if page == 2 else []
                orch.sh(
                    "grade-output/scripts/write_grade_shard.py",
                    "--doc",
                    doc,
                    "--page",
                    str(page),
                    "--score",
                    "0.2" if issues else "1.0",
                    *issues,
                )

        summary = Orchestrator(tmp_project, grader=grader, max_attempts=2).run()

        assert summary["counts"] == {"needs-human": 1}
        assert summary["needs_human"]["s"] == "still failing after 2 attempts"
