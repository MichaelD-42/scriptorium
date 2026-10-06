"""Follow-up R28: explicit line breaks and taller bullet glyphs.

- A line that ends so early that the next line's first word would have fit
  on it was broken on purpose (Word's line break), not wrapped. A paragraph
  is split there.
- A bullet glyph drawn in a larger font than its text starts a few points
  higher; glyph and text are paired when their bottoms align, too.
"""

from conftest import load_script

extract_text = load_script("extract-text/scripts/extract_text.py", "extract_text_r28")


def _line(x0, y0, x1, text, y1=None):
    return {"text": text, "bbox": [x0, y0, x1, y1 if y1 is not None else y0 + 11], "max_size": 10.0, "bold": False, "masked": text}


class TestHardBreaks:
    def test_short_line_with_room_for_the_next_word_breaks(self):
        lines = [
            _line(46, 669, 200, "Systems with 12 V nominal voltage"),
            _line(46, 680, 410, "Test with supply voltage 18 V. Test duration: 1 h in a hot air oven."),
            _line(46, 691, 363, "Test with supply voltage 24 V. Test duration: 5 min."),
        ]
        groups = extract_text.split_hard_breaks(lines, right_edge=550.0)
        assert [" ".join(x["text"] for x in g) for g in groups] == [
            "Systems with 12 V nominal voltage",
            "Test with supply voltage 18 V. Test duration: 1 h in a hot air oven.",
            "Test with supply voltage 24 V. Test duration: 5 min.",
        ]

    def test_wrapped_lines_stay_one_paragraph(self):
        lines = [
            _line(46, 100, 548, "A long sentence that fills the line up to the right margin of the"),
            _line(46, 111, 546, "column and wraps onto the next line, which also reaches the right"),
            _line(46, 122, 200, "margin before it ends."),
        ]
        assert extract_text.split_hard_breaks(lines, right_edge=550.0) == [lines]

    def test_long_next_word_keeps_the_wrap(self):
        lines = [
            _line(46, 100, 470, "The supplier shall document every"),
            _line(46, 111, 300, "Supercalifragilisticexpialidociousness test."),
        ]
        assert extract_text.split_hard_breaks(lines, right_edge=550.0) == [lines]


    def test_narrow_column_lines_stay_one_paragraph(self):
        lines = [
            _line(46, 100, 250, "All rights reserved in the event of the"),
            _line(46, 111, 248, "grant of a patent, utility model or"),
            _line(46, 122, 200, "ornamental design registration."),
        ]
        assert extract_text.split_hard_breaks(lines, right_edge=550.0) == [lines]


class TestTallGlyph:
    def test_glyph_with_aligned_bottom_starts_an_item(self):
        lines = [
            _line(46, 152, 550, "The component shall support production requirements on capacity and"),
            _line(46, 163, 81, "quality:"),
            _line(46, 174, 52, "·", y1=189),
            _line(64, 177.4, 485, "Component and connector ease of installation.", y1=189),
            _line(46, 189, 52, "·", y1=204),
            _line(64, 192.4, 281, "One motion installation and connection (no twist).", y1=203.6),
        ]
        elements = extract_text.parse_block_list_items(lines, [46.0])
        assert [e["text"] for e in elements if e["type"] == "list_item"] == [
            "Component and connector ease of installation.",
            "One motion installation and connection (no twist).",
        ]
