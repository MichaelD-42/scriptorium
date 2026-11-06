"""findings.py: a page that failed at a script tier and passed at vision
becomes a suggested correction -- page PDF, reference, script output and
the grader's reasons."""

import json
import shutil

import fitz  # PyMuPDF

import elements as elements_lib
import paths
from conftest import EXAMPLES_ROOT, run_script


def _passed_doc(tmp_project, status="passed"):
    shutil.copy(EXAMPLES_ROOT / "sample.pdf", tmp_project / "input" / "s.pdf")
    elements_lib.write_shard(
        paths.shard_path("s", 2, "text"),
        2,
        [
            {"type": "table", "rows": [["Quarter", "Revenue"], ["Q1 120", ""]]},
        ],
    )
    elements_lib.write_shard(
        paths.shard_path("s", 2, "vision"),
        2,
        [
            {"type": "table", "rows": [["Quarter", "Revenue"], ["Q1", "120"]]},
        ],
    )
    elements_lib.write_shard(
        paths.shard_path("s", 1, "text"), 1, [{"type": "paragraph", "text": "Fine."}]
    )
    pages = elements_lib.merge_shards(paths.shards_dir("s"), 2)
    elements_lib.save_doc(
        paths.elements_json("s"), {"doc": "s", "page_count": 2, "pages": pages}
    )
    entry = {
        "status": status,
        "attempt": 1,
        "input_format": "pdf",
        "format": "md",
        "escalated_pages": {},
        "lang_flag": "eng",
        "attempts": [
            {
                "attempt": 0,
                "status": "retrying",
                "escalated_pages": {
                    "2": {
                        "tier": "vision",
                        "recheck_images": False,
                        "reason": "Q1 row cells fused",
                    }
                },
            },
            {"attempt": 1, "status": "passed"},
        ],
    }
    (tmp_project / "runs" / "state.json").write_text(json.dumps({"docs": {"s": entry}}))


def test_an_escalated_page_that_passed_becomes_a_finding(tmp_project):
    _passed_doc(tmp_project)
    result = run_script(
        "queue-state/scripts/findings.py",
        "--doc",
        "s",
        "--dest",
        "found",
        cwd=tmp_project,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["findings"] == ["found/s-p2"]

    folder = tmp_project / "found" / "s-p2"
    meta = json.loads((folder / "finding.json").read_text())
    assert meta == {
        "source": "s.pdf",
        "page": 2,
        "from_tier": "text",
        "reasons": ["Q1 row cells fused"],
        "status": "suggested",
        "input": "page.pdf",
        "reference": "reference.md",
        "lang": "eng",
    }
    assert "| Q1 | 120 |" in (folder / "reference.md").read_text()
    assert "| Q1 120 |" in (folder / "script.md").read_text()
    with fitz.open(folder / "page.pdf") as pdf:
        assert pdf.page_count == 1
    assert not (tmp_project / "found" / "s-p1").exists()


def test_a_document_that_did_not_pass_gives_no_findings(tmp_project):
    _passed_doc(tmp_project, status="needs-human")
    result = run_script(
        "queue-state/scripts/findings.py",
        "--doc",
        "s",
        "--dest",
        "found",
        cwd=tmp_project,
    )
    assert result.returncode == 1
    assert not (tmp_project / "found").exists()
