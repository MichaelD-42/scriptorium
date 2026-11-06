"""--no-describe: a text-layer PDF goes through extraction with no agent.
Images keep their asset, script caption and figure_text; nothing waits for
a description."""

import json
import shutil

from conftest import EXAMPLES_ROOT, run_script

import paths


def _ok(*args, cwd):
    result = run_script(*args, cwd=cwd)
    assert result.returncode == 0, result.stderr
    return result.stdout


def _gate(stdout, name):
    return next(c for c in json.loads(stdout)["checks"] if c["name"] == name)


def test_furniture_sample_passes_the_gates_with_no_agent(tmp_project):
    shutil.copy(EXAMPLES_ROOT / "furniture_sample.pdf", tmp_project / "input" / "f.pdf")
    _ok("pdf-triage/scripts/triage.py", "--doc", "f", cwd=tmp_project)
    triage = json.loads(paths.triage_json("f").read_text())
    pages = ",".join(str(p["page_number"]) for p in triage["pages"])
    assert {p["tier"] for p in triage["pages"]} == {"text"}
    _ok("extract-text/scripts/extract_text.py", "--doc", "f", "--pages", pages, "--body-size", str(triage["body_size"]), cwd=tmp_project)
    _ok("extract-images/scripts/extract_images.py", "--doc", "f", "--pages", pages, cwd=tmp_project)
    _ok("assemble-output/scripts/merge.py", "--doc", "f", cwd=tmp_project)
    _ok("assemble-output/scripts/assemble.py", "--doc", "f", "--format", "md", cwd=tmp_project)

    strict = run_script("grade-output/scripts/gates.py", "--doc", "f", cwd=tmp_project).stdout
    assert not _gate(strict, "figures_complete")["passed"]

    out = _ok("grade-output/scripts/gates.py", "--doc", "f", "--no-describe", cwd=tmp_project)
    assert _gate(out, "figures_complete")["detail"] == "skipped: --no-describe"
    assert json.loads(out)["passed"], out
