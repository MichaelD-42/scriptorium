"""Follow-up R14: a short furniture pattern that is also body text.

A title-block value (here the synthetic program name "SYNX") can also be a
row of an abbreviations table or a word in body text. The rules:
(a) an element WITH a bbox matches any pattern (letters or digits) only
    when it lies in the furniture band;
(b) an element WITHOUT a bbox (OCR, vision) matches letter patterns
    anywhere, as before;
(c) the assembled-output scan flags a pattern only when it occurs as a whole
    line at least max(3, 10% of the body pages) times in one output.
The merge filter uses the same rule, so a body line is never deleted.
"""

from pathlib import Path

import elements as elements_lib
import furniture as furniture_lib
from conftest import load_script

gates = load_script("grade-output/scripts/gates.py", "gates_module_r14")

H = 842.0
FURNITURE = {
    **furniture_lib.empty_furniture(),
    "line_patterns": [{"masked": "SYNX"}, {"masked": "DocNo.SYN-#"}, {"masked": "#"}],
}
PATTERNS = {"SYNX", "DocNo.SYN-#", "#"}
ABBREV_ROW = {
    "type": "table",
    "rows": [["SYNX", "Synthetic program"]],
    "bbox": [60.0, 300.0, 400.0, 320.0],
}
BODY_LINE = {"type": "paragraph", "text": "SYNX", "bbox": [60.0, 400.0, 90.0, 410.0]}
FOOTER = {
    "type": "paragraph",
    "text": "Doc No. SYN-0012",
    "bbox": [60.0, 800.0, 200.0, 808.0],
}
VISION_FOOTER = {"type": "paragraph", "text": "Doc No. SYN-0012"}


def _doc(pages: dict[int, list[dict]]) -> dict:
    return {
        "doc": "d",
        "pages": {n: {"page_number": n, "elements": els} for n, els in pages.items()},
    }


class TestElementsWithABbox:
    def test_abbreviation_row_and_body_line_pass_the_gate(self, tmp_path):
        result = gates.check_furniture_absent(
            _doc({1: [ABBREV_ROW, BODY_LINE]}), FURNITURE, tmp_path, {1: H}
        )
        assert result["passed"], result

    def test_a_footer_in_the_band_still_fails(self, tmp_path):
        result = gates.check_furniture_absent(
            _doc({1: [FOOTER]}), FURNITURE, tmp_path, {1: H}
        )
        assert not result["passed"]

    def test_merge_filter_keeps_the_body_line(self):
        kept, removed = elements_lib.remove_furniture_lines(
            [BODY_LINE, FOOTER], PATTERNS, H
        )
        assert kept == [BODY_LINE] and removed == 1


class TestElementsWithoutABbox:
    def test_vision_footer_is_removed_at_merge(self):
        kept, removed = elements_lib.remove_furniture_lines(
            [VISION_FOOTER], PATTERNS, H
        )
        assert kept == [] and removed == 1

    def test_vision_footer_left_in_is_flagged(self, tmp_path):
        result = gates.check_furniture_absent(
            _doc({1: [VISION_FOOTER]}), FURNITURE, tmp_path, {1: H}
        )
        assert not result["passed"]


class TestOutputScanNeedsRepetition:
    def _out(self, tmp_path: Path, lines: list[str]) -> Path:
        out = tmp_path / "d"
        out.mkdir()
        (out / "d.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return out

    def test_a_single_line_is_not_flagged(self, tmp_path):
        out = self._out(tmp_path, ["# 1 Scope", "SYNX", "Body text."])
        pages = {n: [] for n in range(1, 11)}
        result = gates.check_furniture_absent(_doc(pages), FURNITURE, out, {})
        assert result["passed"], result

    def test_a_repeated_whole_line_is_flagged(self, tmp_path):
        out = self._out(
            tmp_path,
            ["Doc No. SYN-0012", "Body.", "Doc No. SYN-0013", "Doc No. SYN-0014"],
        )
        pages = {n: [] for n in range(1, 11)}
        result = gates.check_furniture_absent(_doc(pages), FURNITURE, out, {})
        assert not result["passed"]
        assert len([o for o in result["offenders"] if o["page"] is None]) == 3

    def test_threshold_is_ten_percent_of_body_pages(self, tmp_path):
        out = self._out(tmp_path, [f"Doc No. SYN-{n}" for n in range(4)])
        pages = {n: [] for n in range(1, 51)}  # threshold max(3, 5) = 5
        result = gates.check_furniture_absent(_doc(pages), FURNITURE, out, {})
        assert result["passed"], result
