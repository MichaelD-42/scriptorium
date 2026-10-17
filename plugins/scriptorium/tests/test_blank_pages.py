"""A blank page (nothing on it, or only the repeated header/footer) is not
a dropped page: it must not be sent to OCR or fail `no_empty_pages`."""

import json

import fitz
import pytest

import paths
from conftest import run_script


def _build(tmp_project, furniture: bool) -> str:
    d = fitz.open()
    for n in range(1, 6):
        page = d.new_page()
        if furniture:
            page.insert_text((72, 40), "ACME Corp Service Manual")
            page.insert_text((500, 810), f"page {n}")
        if n != 3:
            page.insert_text(
                (72, 300),
                f"Body text on page {n}, long enough to count as a text layer.",
            )
    d.save(tmp_project / "input" / "blanky.pdf")
    return "blanky"


def _run(doc, cwd, *args):
    result = run_script(*args, "--doc", doc, cwd=cwd)
    assert result.returncode == 0, result.stderr
    return result


@pytest.mark.parametrize("furniture", [False, True], ids=["empty", "furniture_only"])
def test_blank_page_is_text_tier_and_passes_no_empty_pages(tmp_project, furniture):
    doc = _build(tmp_project, furniture)
    _run(doc, tmp_project, "pdf-triage/scripts/triage.py")
    triage = json.loads(paths.triage_json(doc).read_text())
    assert triage["pages"][2]["tier"] == "text"

    pages = "1,2,3,4,5"
    _run(
        doc,
        tmp_project,
        "extract-text/scripts/extract_text.py",
        "--pages",
        pages,
        "--body-size",
        str(triage["body_size"]),
    )
    _run(doc, tmp_project, "extract-images/scripts/extract_images.py", "--pages", pages)
    _run(doc, tmp_project, "assemble-output/scripts/merge.py")
    _run(doc, tmp_project, "assemble-output/scripts/assemble.py", "--format", "md")
    run_script("grade-output/scripts/gates.py", "--doc", doc, cwd=tmp_project)

    checks = {
        c["name"]: c
        for c in json.loads(paths.gates_report_json(doc).read_text())["checks"]
    }
    assert checks["no_empty_pages"]["passed"], checks["no_empty_pages"]["detail"]


def test_page_with_lost_text_still_fails_no_empty_pages(tmp_project):
    """The exemption is for pages triage saw as blank, not any empty page."""
    doc = _build(tmp_project, furniture=False)
    _run(doc, tmp_project, "pdf-triage/scripts/triage.py")
    triage = json.loads(paths.triage_json(doc).read_text())
    _run(
        doc,
        tmp_project,
        "extract-text/scripts/extract_text.py",
        "--pages",
        "1,3,4,5",
        "--body-size",
        str(triage["body_size"]),
    )
    _run(doc, tmp_project, "assemble-output/scripts/merge.py")
    _run(doc, tmp_project, "assemble-output/scripts/assemble.py", "--format", "md")
    run_script("grade-output/scripts/gates.py", "--doc", doc, cwd=tmp_project)

    checks = {
        c["name"]: c
        for c in json.loads(paths.gates_report_json(doc).read_text())["checks"]
    }
    assert not checks["no_empty_pages"]["passed"]
    assert checks["no_empty_pages"]["detail"] == "empty pages: [2]"
