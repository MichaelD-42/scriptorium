"""Follow-up R18: repair text that a PDF's own text layer gets wrong.

Every text reader in the PDF path (extract_text's blocks, figures' lines and
table cells, toc's lines) builds a line's text with `line_text`, so the same
repair reaches body text, table cells, captions, figure_text and the TOC
match. Two repairs:

1. Symbol-font text. A span whose font is the Symbol font (its PDF font
   name, or for an anonymised subset such as "CIDFont+F4" the name of the
   embedded font program) carries Symbol-encoded codes as if they were
   Latin-1 ("£" for "≤", "W" for "Ω"), or the same codes in the private-use
   area (U+F028 for "("). `decode_symbol` maps them with the Adobe Symbol
   encoding. The list-marker glyphs in `SYMBOL_KEPT_CODES` are left as they
   are: extract_text's list detection owns them.
2. Ligature glyphs. Word's Calibri subsets map the "ti", "tt" and "ft"
   ligatures to U+019F, U+01A9 and U+014C. Those are real letters
   elsewhere, so `fix_ligatures` decodes them only inside a word: U+019F
   and U+01A9 next to a lowercase letter, U+014C after one. The Unicode
   presentation ligatures (U+FB00..U+FB06) are always decoded.

The furniture key (`furniture.furniture_key`) stays on the raw text, so the
triage line patterns keep matching.
"""

import fitz  # PyMuPDF

# Adobe Symbol encoding: the codes whose glyph is not the Latin-1 character
# of the same code. Every other code reads as its Latin-1 character.
_SYMBOL_TO_UNICODE = {
    0x22: "∀",
    0x24: "∃",
    0x27: "∋",
    0x2A: "∗",
    0x40: "≅",
    0x41: "Α",
    0x42: "Β",
    0x43: "Χ",
    0x44: "Δ",
    0x45: "Ε",
    0x46: "Φ",
    0x47: "Γ",
    0x48: "Η",
    0x49: "Ι",
    0x4A: "ϑ",
    0x4B: "Κ",
    0x4C: "Λ",
    0x4D: "Μ",
    0x4E: "Ν",
    0x4F: "Ο",
    0x50: "Π",
    0x51: "Θ",
    0x52: "Ρ",
    0x53: "Σ",
    0x54: "Τ",
    0x55: "Υ",
    0x56: "ς",
    0x57: "Ω",
    0x58: "Ξ",
    0x59: "Ψ",
    0x5A: "Ζ",
    0x5C: "∴",
    0x5E: "⊥",
    0x61: "α",
    0x62: "β",
    0x63: "χ",
    0x64: "δ",
    0x65: "ε",
    0x66: "φ",
    0x67: "γ",
    0x68: "η",
    0x69: "ι",
    0x6A: "ϕ",
    0x6B: "κ",
    0x6C: "λ",
    0x6D: "μ",
    0x6E: "ν",
    0x6F: "ο",
    0x70: "π",
    0x71: "θ",
    0x72: "ρ",
    0x73: "σ",
    0x74: "τ",
    0x75: "υ",
    0x76: "ϖ",
    0x77: "ω",
    0x78: "ξ",
    0x79: "ψ",
    0x7A: "ζ",
    0x7E: "∼",
    0xA1: "ϒ",
    0xA2: "′",
    0xA3: "≤",
    0xA4: "⁄",
    0xA5: "∞",
    0xA6: "ƒ",
    0xA8: "♦",
    0xA9: "♥",
    0xAA: "♠",
    0xAB: "↔",
    0xAC: "←",
    0xAD: "↑",
    0xAE: "→",
    0xAF: "↓",
    0xB0: "°",
    0xB1: "±",
    0xB2: "″",
    0xB3: "≥",
    0xB4: "×",
    0xB5: "∝",
    0xB6: "∂",
    0xB8: "÷",
    0xB9: "≠",
    0xBA: "≡",
    0xBB: "≈",
    0xBC: "…",
    0xC0: "ℵ",
    0xC1: "ℑ",
    0xC2: "ℜ",
    0xC3: "℘",
    0xC4: "⊗",
    0xC5: "⊕",
    0xC6: "∅",
    0xC7: "∩",
    0xC8: "∪",
    0xC9: "⊃",
    0xCA: "⊇",
    0xCB: "⊄",
    0xCC: "⊂",
    0xCD: "⊆",
    0xCE: "∈",
    0xCF: "∉",
    0xD0: "∠",
    0xD1: "∇",
    0xD5: "∏",
    0xD6: "√",
    0xD7: "⋅",
    0xD9: "∧",
    0xDA: "∨",
    0xDB: "⇔",
    0xDC: "⇐",
    0xDD: "⇑",
    0xDE: "⇒",
    0xDF: "⇓",
    0xE0: "◊",
    0xE1: "〈",
    0xE5: "∑",
    0xF1: "〉",
    0xF2: "∫",
}

# Codes left exactly as printed: the list-marker glyphs extract_text's
# LIST_BULLET_GLYPHS and its private-use bullet shapes rely on (minus,
# bullet, club, logical not).
SYMBOL_KEPT_CODES = frozenset({0x2D, 0xB7, 0xA7, 0xD8})

_PRIVATE_USE_BASE = 0xF000

LIGATURE_GLYPHS = {"Ɵ": "ti", "Ʃ": "tt", "Ō": "ft"}
PRESENTATION_LIGATURES = {
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "ﬅ": "st",
    "ﬆ": "st",
}

_symbol_font_cache: dict[tuple[str, int], bool] = {}


def _decode_symbol_char(ch: str) -> str:
    code = ord(ch)
    if _PRIVATE_USE_BASE + 0x20 <= code <= _PRIVATE_USE_BASE + 0xFF:
        code -= _PRIVATE_USE_BASE
        if code in SYMBOL_KEPT_CODES:
            return ch
        return _SYMBOL_TO_UNICODE.get(code, chr(code))
    if code in SYMBOL_KEPT_CODES:
        return ch
    return _SYMBOL_TO_UNICODE.get(code, ch)


def decode_symbol(text: str) -> str:
    """`text` from a Symbol-font span, decoded with the Adobe Symbol
    encoding (see module docstring)."""
    return "".join(_decode_symbol_char(ch) for ch in text)


def _is_lower(ch: str) -> bool:
    return ch.isalpha() and ch.islower()


def fix_ligatures(text: str) -> str:
    """`text` with the ligature glyphs decoded (see module docstring)."""
    if not any(ch in LIGATURE_GLYPHS or ch in PRESENTATION_LIGATURES for ch in text):
        return text
    out = []
    for i, ch in enumerate(text):
        if ch in PRESENTATION_LIGATURES:
            out.append(PRESENTATION_LIGATURES[ch])
            continue
        if ch in LIGATURE_GLYPHS:
            before = text[i - 1] if i > 0 else ""
            after = text[i + 1] if i + 1 < len(text) else ""
            in_word = (
                _is_lower(before)
                if ch == "Ō"
                else (_is_lower(before) or _is_lower(after))
            )
            if in_word:
                out.append(LIGATURE_GLYPHS[ch])
                continue
        out.append(ch)
    return "".join(out)


def _is_symbol_font(doc, xref: int, basefont: str) -> bool:
    key = (doc.name or str(id(doc)), xref)
    if key in _symbol_font_cache:
        return _symbol_font_cache[key]
    base = basefont.split("+", 1)[-1]
    result = base.lower().startswith("symbol")
    if not result and xref > 0:
        try:
            _name, _ext, _type, buffer = doc.extract_font(xref)
            if buffer:
                result = fitz.Font(fontbuffer=buffer).name.lower().startswith("symbol")
        except (
            RuntimeError,
            ValueError,
        ):  # an unreadable font program is simply not Symbol
            result = False
    _symbol_font_cache[key] = result
    return result


def page_symbol_fonts(page) -> set[str]:
    """The span font names on `page` that are the Symbol font, both with
    and without a subset prefix (PyMuPDF reports either form)."""
    names = set()
    for font in page.get_fonts():
        xref, basefont = font[0], font[3]
        if _is_symbol_font(page.parent, xref, basefont):
            names.add(basefont)
            names.add(basefont.split("+", 1)[-1])
    return names


def span_text(span: dict, symbol_fonts: set[str]) -> str:
    text = span.get("text", "")
    if symbol_fonts and span.get("font") in symbol_fonts:
        return decode_symbol(text)
    return text


def line_text(line: dict, symbol_fonts: set[str]) -> str:
    """A PyMuPDF "dict" line's text: its spans joined, each decoded, then
    the ligatures fixed. Not stripped."""
    return fix_ligatures(
        "".join(span_text(span, symbol_fonts) for span in line.get("spans", []))
    )


def page_chars(page) -> list[tuple]:
    """Every character on `page` as `(cx, cy, line_key, char)`: its bbox
    center, the (block, line) it belongs to, and the character with the
    Symbol decoding applied. `cell_texts` reads cells from this list."""
    symbol_fonts = page_symbol_fonts(page)
    chars = []
    for b_index, block in enumerate(page.get_text("rawdict").get("blocks", [])):
        if block.get("type") != 0:
            continue
        for l_index, line in enumerate(block.get("lines", [])):
            for span in line.get("spans", []):
                is_symbol = span.get("font") in symbol_fonts
                for ch in span.get("chars", []):
                    x0, y0, x1, y1 = ch["bbox"]
                    c = decode_symbol(ch["c"]) if is_symbol else ch["c"]
                    chars.append(((x0 + x1) / 2, (y0 + y1) / 2, (b_index, l_index), c))
    return chars


def cell_texts(chars: list[tuple], cell_bboxes: list) -> list[str]:
    """Text per cell bbox (None gives ""), from `page_chars(page)`: a
    character belongs to the cell that holds its center, characters keep
    their line order, and a cell's lines are joined with newlines. The
    same decoding as `line_text`. Used for pdfplumber's table cells, so a
    cell's text matches the body text readers (and a subscript stays on its
    line: "UN", not "U", "N" on two lines)."""
    texts = []
    for bbox in cell_bboxes:
        if bbox is None:
            texts.append("")
            continue
        x0, y0, x1, y1 = bbox
        lines: dict[tuple, list[str]] = {}
        for cx, cy, key, c in chars:
            if x0 <= cx <= x1 and y0 <= cy <= y1:
                lines.setdefault(key, []).append(c)
        parts = [
            fix_ligatures("".join(cs)).strip() for _key, cs in sorted(lines.items())
        ]
        texts.append("\n".join(p for p in parts if p))
    return texts
