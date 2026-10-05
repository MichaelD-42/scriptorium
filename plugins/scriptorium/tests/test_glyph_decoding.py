"""Follow-up R18: text the PDF's own text layer gets wrong.

Two shapes, both seen on a real Word-made document:

- A Symbol-font span (the PDF's font, or its embedded font program, is
  named "Symbol") carries Symbol-encoded codes as if they were Latin-1:
  "£" for "≤", "W" for "Ω", or the same codes in the private-use area
  (U+F028 for "("). `lib/glyphs.py` decodes them with the Adobe Symbol
  encoding. The list-marker glyphs (U+F02D, U+F0B7, U+F0A7, U+F0D8, "·")
  are left alone: list detection owns them.
- A Calibri-style "ti"/"tt"/"ft" ligature glyph is mapped to U+019F,
  U+01A9 and U+014C. They are decoded only inside a word.

Tables read their cell text from PyMuPDF (per character, by cell), so the
same decoding reaches table cells.
"""

import json

import fitz  # PyMuPDF
import glyphs
import paths
from conftest import run_script

W, H = 595.0, 842.0


class TestFixLigatures:
    def test_ligature_glyphs_inside_words(self):
        assert glyphs.fix_ligatures("IniƟal producƟon") == "Initial production"
        assert glyphs.fix_ligatures("aŌer seƩing") == "after setting"
        assert glyphs.fix_ligatures("t, Ɵme") == "t, time"
        assert glyphs.fix_ligatures("leŌ") == "left"

    def test_presentation_ligatures(self):
        assert glyphs.fix_ligatures("ﬁle ﬂat") == "file flat"

    def test_letters_outside_a_word_are_kept(self):
        assert glyphs.fix_ligatures("Ōsaka") == "Ōsaka"
        assert glyphs.fix_ligatures("Ɵ") == "Ɵ"


class TestDecodeSymbol:
    def test_symbol_codes(self):
        assert glyphs.decode_symbol("£ 1") == "≤ 1"
        assert glyphs.decode_symbol("(W)") == "(Ω)"
        assert glyphs.decode_symbol("³ ± m") == "≥ ± μ"

    def test_private_use_codes(self):
        assert glyphs.decode_symbol("") == "(≤)"
        assert glyphs.decode_symbol("") == "°"

    def test_list_markers_are_kept(self):
        for marker in ("", "", "", "", "·", "-"):
            assert glyphs.decode_symbol(marker) == marker

    def test_digits_and_spaces_are_kept(self):
        assert glyphs.decode_symbol("12 (3)") == "12 (3)"


def _run_of(page, x: float, y: float, runs: list[tuple[str, str]]) -> float:
    """Insert `runs` ((text, fontname)) end to end on one baseline, with no
    gap between them, so PyMuPDF reads one line with no extra space."""
    for text, fontname in runs:
        page.insert_text((x, y), text, fontname=fontname, fontsize=10)
        x += fitz.get_text_length(text, fontname=fontname, fontsize=10)
    return x


def _symbol_pdf(path) -> None:
    pdf = fitz.open()
    page = pdf.new_page(width=W, height=H)
    page.insert_font(fontname="F0", fontbuffer=fitz.Font("cjk").buffer)
    _run_of(page, 72, 100, [("Rise time ", "helv"), ("£", "symb"), (" 1 ms", "helv")])
    page.insert_text((72, 130), "Applied aŌer the test.", fontname="F0", fontsize=10)
    # A ruled 2x2 table: "Ri (W)" | "a£er" and "20" | "50".
    xs, ys = (72, 200, 330), (300, 320, 340)
    for x in xs:
        page.draw_line((x, ys[0]), (x, ys[-1]), width=0.8)
    for y in ys:
        page.draw_line((xs[0], y), (xs[-1], y), width=0.8)
    _run_of(page, 76, 314, [("Ri (", "helv"), ("W", "symb"), (")", "helv")])
    page.insert_text((204, 314), "aŌer", fontname="F0", fontsize=10)
    page.insert_text((76, 334), "20", fontname="helv", fontsize=10)
    page.insert_text((204, 334), "50", fontname="helv", fontsize=10)
    pdf.save(str(path))
    pdf.close()


class TestExtractTextDecodes:
    def test_body_and_table_text_is_decoded(self, tmp_project):
        doc = "glyphs"
        _symbol_pdf(tmp_project / "input" / f"{doc}.pdf")
        for args in (
            ("pdf-triage/scripts/triage.py", "--doc", doc),
            ("extract-text/scripts/extract_text.py", "--doc", doc, "--pages", "1"),
        ):
            result = run_script(*args, cwd=tmp_project)
            assert result.returncode == 0, f"{args[0]}: {result.stderr}"
        elements = json.loads(
            paths.shard_path(doc, 1, "text").read_text(encoding="utf-8")
        )["elements"]
        body = [e["text"] for e in elements if e["type"] == "paragraph"]
        assert any("Rise time" in t and "≤" in t and "£" not in t for t in body), body
        assert any("Applied after the test." == t for t in body), body
        tables = [e for e in elements if e["type"] == "table"]
        assert len(tables) == 1
        assert tables[0]["rows"] == [["Ri (Ω)", "after"], ["20", "50"]]


class TestCellReadingOrder:
    def test_glyph_in_its_own_line_is_read_in_place(self):
        """PyMuPDF puts the Symbol "W" (drawn after the brackets) in a line
        of its own; the cell still reads "Ri (Ω)"."""
        pdf = fitz.open()
        page = pdf.new_page(width=W, height=H)

        def length(text, font, size=10):
            return fitz.get_text_length(text, fontname=font, fontsize=size)

        x0 = 76
        xp = x0 + length("Ri ", "helv")
        xw = xp + length("(", "symb", 11)
        xc = xw + length("W", "symb", 9.6)
        page.insert_text((x0, 314), "Ri ", fontname="helv", fontsize=10)
        page.insert_text((xp, 314), "(", fontname="symb", fontsize=11)
        page.insert_text((xc, 314), ")", fontname="symb", fontsize=11)
        page.insert_text((xw, 312.5), "W", fontname="symb", fontsize=9.6)
        doc = fitz.open("pdf", pdf.tobytes())
        assert glyphs.cell_texts(glyphs.page_chars(doc[0]), [[70, 300, 200, 320]]) == ["Ri (Ω)"]
