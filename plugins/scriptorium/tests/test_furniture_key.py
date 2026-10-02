"""Follow-up R6: one furniture key for every shape of a footer line.

PyMuPDF can return the same footer page-number line in different shapes on
different pages: letter-spaced ("1 0 ( 1 2 0 )"), compact ("13(120)"), or
letter-spaced with a single digit ("9 ( 1 2 0 )"). `furniture.furniture_key`
removes all whitespace and then collapses each digit run to "#", so all
three shapes give the one key "#(#)". Triage stores the key in `masked`, and
extract_text, the merge filter and the gates compare with the same function.

The fixture is a synthetic 6-page PDF. No single shape is on 60% of the
pages, so a digit-masked-only key would find no footer pattern at all.
"""

import json
from pathlib import Path

import fitz  # PyMuPDF
import furniture as furniture_lib
import paths
from conftest import load_script, run_script

gates = load_script("grade-output/scripts/gates.py", "gates_module_furniture_key")

DOC = "spaced_footer"
PAGE_WIDTH, PAGE_HEIGHT = 595.0, 842.0
PAGE_COUNT = 6
DOC_NUMBER = "Doc No. SYN-0006"
FOOTERS = {
    1: "9 ( 1 2 0 )",
    2: "1 0 ( 1 2 0 )",
    3: "1 1 ( 1 2 0 )",
    4: "1 2 ( 1 2 0 )",
    5: "13(120)",
    6: "14(120)",
}


def _make_pdf(path: Path) -> None:
    doc = fitz.open()
    for n in range(1, PAGE_COUNT + 1):
        page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        page.insert_text(
            (72, 120), f"Body text on page {n} of the synthetic document.", fontsize=11
        )
        page.insert_text(
            (72, 140),
            "A second body line keeps the page from being sparse.",
            fontsize=11,
        )
        page.insert_text((40, 790), DOC_NUMBER, fontsize=8)
        page.insert_text((480, 810), FOOTERS[n], fontsize=8)
    doc.save(str(path))
    doc.close()


def _run_ok(relpath: str, *args: str, cwd) -> str:
    result = run_script(relpath, *args, cwd=cwd)
    assert result.returncode == 0, (
        f"{relpath} {' '.join(args)} failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    return result.stdout


def _pages() -> str:
    return ",".join(str(p) for p in range(1, PAGE_COUNT + 1))


class TestFurnitureKey:
    def test_all_three_footer_shapes_give_one_key(self):
        keys = {
            furniture_lib.furniture_key(s)
            for s in ("1 0 ( 1 2 0 )", "100(120)", "9 ( 1 2 0 )")
        }
        assert keys == {"#(#)"}

    def test_letter_patterns_lose_their_spaces(self):
        assert furniture_lib.furniture_key("Legal Owner") == "LegalOwner"
        assert furniture_lib.furniture_key("Doc No. SYN-0006") == "DocNo.SYN-#"

    def test_strip_and_hits_use_the_key(self):
        text = "Body line.\n1 0 ( 1 2 0 )"
        assert furniture_lib.strip_furniture_lines(text, {"#(#)"}) == ("Body line.", 1)
        assert furniture_lib.furniture_line_hits(text, {"#(#)"}) == ["1 0 ( 1 2 0 )"]


class TestSpacedFooterEndToEnd:
    def _triage(self, tmp_project) -> dict:
        _make_pdf(tmp_project / "input" / f"{DOC}.pdf")
        _run_ok("pdf-triage/scripts/triage.py", "--doc", DOC, cwd=tmp_project)
        return json.loads(paths.triage_json(DOC).read_text())

    def test_one_pattern_covers_every_page(self, tmp_project):
        triage = self._triage(tmp_project)
        patterns = {
            p["masked"]: p["page_count"] for p in triage["furniture"]["line_patterns"]
        }
        assert patterns == {"#(#)": PAGE_COUNT, "DocNo.SYN-#": PAGE_COUNT}

    def test_no_footer_survives_in_the_body(self, tmp_project):
        triage = self._triage(tmp_project)
        _run_ok(
            "extract-text/scripts/extract_text.py",
            "--doc",
            DOC,
            "--pages",
            _pages(),
            "--body-size",
            str(triage["body_size"]),
            cwd=tmp_project,
        )
        for n in range(1, PAGE_COUNT + 1):
            shard = json.loads(paths.shard_path(DOC, n, "text").read_text())
            texts = [e.get("text", "") for e in shard["elements"]]
            assert any("Body text on page" in t for t in texts), f"page {n}: {texts}"
            for t in texts:
                assert "115" not in "".join(t.split()), (
                    f"page {n}: footer left in {t!r}"
                )
                assert "SYN-0006" not in t, f"page {n}: doc number left in {t!r}"

        _run_ok(
            "extract-images/scripts/extract_images.py",
            "--doc",
            DOC,
            "--pages",
            _pages(),
            cwd=tmp_project,
        )
        _run_ok("assemble-output/scripts/merge.py", "--doc", DOC, cwd=tmp_project)
        _run_ok(
            "assemble-output/scripts/assemble.py",
            "--doc",
            DOC,
            "--format",
            "md",
            cwd=tmp_project,
        )
        report = json.loads(
            _run_ok(
                "grade-output/scripts/gates.py",
                "--doc",
                DOC,
                "--format",
                "md",
                cwd=tmp_project,
            )
        )
        furniture_check = next(
            c for c in report["checks"] if c["name"] == "furniture_absent"
        )
        assert furniture_check["passed"], furniture_check

    def test_gate_flags_a_spaced_footer_left_in_the_body(self):
        furniture = {
            "line_patterns": [{"masked": "#(#)"}, {"masked": "DocNo.SYN-#"}],
            "frame_tables": [],
        }
        doc_data = {
            "doc": DOC,
            "pages": {
                1: {
                    "page_number": 1,
                    "elements": [
                        {"type": "paragraph", "text": "Doc No. SYN-0006"},
                        {
                            "type": "paragraph",
                            "text": "1 0 ( 1 2 0 )",
                            "bbox": [480.0, 802.0, 530.0, 812.0],
                        },
                    ],
                }
            },
        }
        result = gates.check_furniture_absent(
            doc_data, furniture, Path("nonexistent"), {1: PAGE_HEIGHT}
        )
        assert not result["passed"]
        assert len(result["offenders"]) == 2
