"""Follow-up R29: line breaks the R28 rule still missed or added, found in
the golden run 2026-10-06 (tr-elcp-24453445-04-4). Line geometry below is
taken from that document's real PyMuPDF output.

A. A whole bold line after a plain line (or the reverse) is its own
   paragraph: "... 0,4-0,6 V" then bold "Verification method".
B. A line that starts a list item is a new paragraph when the line before
   ends a sentence (also before a closing bracket: "etc.)", "testing.)")
   or leaves room for the marker's first word.
C. A bullet item printed inline with no hanging indent does not absorb the
   paragraph after it: a hard break ends the item.
D. A line that ends in a hyphen joins the next line with no space:
   "10-" + "second" is "10-second", not "10- second".
E. One paragraph that PyMuPDF splits into blocks, one line each, is joined
   again when the first block's line is full and the gap is a line gap.
F. A run of list items renders its indent relative to the run, so a list
   whose first item is level 3 does not become a Markdown code block.
"""

from conftest import load_script

extract_text = load_script("extract-text/scripts/extract_text.py", "extract_text_r29")
assemble = load_script("assemble-output/scripts/assemble.py", "assemble_r29")


def _line(x0, y0, x1, text, bold=False, y1=None):
    return {
        "text": text,
        "bbox": [x0, y0, x1, y1 if y1 is not None else y0 + 11],
        "max_size": 10.0,
        "bold": bold,
        "masked": text,
    }


def _texts(groups):
    return [extract_text.join_line_texts(g) for g in groups]


class TestBoldLabelLine:
    def test_bold_label_between_plain_lines_is_its_own_paragraph(self):
        # p64: the label's first word is too wide for the gap, so the
        # word-fit rule alone keeps the wrap.
        lines = [
            _line(
                46.2,
                457.2,
                505.5,
                "The purpose of the test is to catch circuits that aren't fully reset unless the voltage is less than 0,4–0,6 V.",
            ),
            _line(46.2, 468.6, 144.3, "Verification method", bold=True),
            _line(
                46.2,
                479.7,
                388.3,
                "Test according to ISO 16750-2 Slow decrease and increase of supply voltage.",
            ),
        ]
        assert _texts(extract_text.split_hard_breaks(lines, right_edge=554.4)) == [
            "The purpose of the test is to catch circuits that aren't fully reset unless the voltage is less than 0,4–0,6 V.",
            "Verification method",
            "Test according to ISO 16750-2 Slow decrease and increase of supply voltage.",
        ]


class TestListMarkerLine:
    def test_enumerator_after_closing_bracket_sentence_end(self):
        # p68: "...for testing.)" then "1. Apply Usmin ..."
        lines = [
            _line(
                46.2,
                153.8,
                554.4,
                "The simulation device shall be constructed to meet the specified component loads. (Insert reference to component",
            ),
            _line(
                46.2,
                164.9,
                387.2,
                "supplied or sufficient information for constructing equivalent loads for testing.)",
            ),
            _line(46.2, 175.9, 195.5, "1. Apply Usmin to the component."),
            _line(
                46.2,
                186.9,
                538.2,
                "2. Subject the applicable ground line of one representative I/O simulation device to a +1,5 V offset relative to the",
            ),
            _line(46.2, 198.0, 132.1, "component ground."),
        ]
        assert _texts(extract_text.split_hard_breaks(lines, right_edge=554.4)) == [
            "The simulation device shall be constructed to meet the specified component loads. (Insert reference to component supplied or sufficient information for constructing equivalent loads for testing.)",
            "1. Apply Usmin to the component.",
            "2. Subject the applicable ground line of one representative I/O simulation device to a +1,5 V offset relative to the component ground.",
        ]

    def test_dash_item_after_nearly_full_line_that_ends_a_sentence(self):
        # p70: no room for "- Description", but the line ends a sentence.
        lines = [
            _line(
                46.2,
                302.9,
                547.2,
                "- Estimated available resources when the functional increments described in REQ 24453445-63 are implemented.",
            ),
            _line(
                46.2,
                313.9,
                502.6,
                "- Description of assumptions, methods and tools used to create the estimates.",
            ),
        ]
        assert len(extract_text.split_hard_breaks(lines, right_edge=554.4)) == 2

    def test_dash_item_after_short_line_without_punctuation(self):
        # p34: "– All chip resistors ... values" then "– All LEDs ..."
        lines = [
            _line(
                46.2,
                678.5,
                342.5,
                "– All chip resistors shall be functional with correct resistance values",
            ),
            _line(
                46.2,
                689.5,
                513.2,
                "– All LEDs, including any with silicone-optical protections, shall function normally. (A bare-eye inspection is",
            ),
            _line(46.2, 700.5, 91.6, "sufficient.)"),
        ]
        assert _texts(extract_text.split_hard_breaks(lines, right_edge=550.5)) == [
            "– All chip resistors shall be functional with correct resistance values",
            "– All LEDs, including any with silicone-optical protections, shall function normally. (A bare-eye inspection is sufficient.)",
        ]

    def test_dash_that_wraps_mid_sentence_stays(self):
        # A full line with no sentence end, then a line that starts with a
        # dash, is a wrap ("... the range" / "– PT) ...").
        lines = [
            _line(
                46.2,
                100,
                548.0,
                "The test covers every temperature step defined for the component over the full range",
            ),
            _line(46.2, 111, 300.0, "– PT) and the cold start sequence."),
        ]
        assert len(extract_text.split_hard_breaks(lines, right_edge=550.0)) == 1


class TestInlineBulletContinuation:
    def _block(self):
        # p60: inline "• " items, no hanging indent; real wraps sit at the
        # marker's x too.
        return [
            _line(
                46.2,
                31.9,
                298.8,
                "Examples of electrical and electronic assembly materials:",
            ),
            _line(
                46.2,
                42.9,
                542.8,
                "• Solder used to connect electrical and/or electronic parts to a circuit board (substrate) or a lead frame (when",
            ),
            _line(46.2, 54.0, 90.5, "substrate)"),
            _line(
                46.2,
                98.1,
                347.1,
                "• Protective coatings on the circuit board (Conformal coat materials)",
            ),
            _line(
                46.2,
                109.2,
                274.8,
                "• Shrink hoses for components on the circuit board.",
            ),
            _line(
                46.2,
                131.3,
                342.1,
                "Exemptions are defined in ELV Annex II paragraph 8 (x) and 10 (x).",
            ),
        ]

    def test_paragraph_after_the_last_item_is_not_absorbed(self):
        elements = extract_text.parse_block_list_items(
            self._block(), [46.2], right_edge=545.1
        )
        assert [(e["type"], e["text"]) for e in elements] == [
            ("paragraph", "Examples of electrical and electronic assembly materials:"),
            (
                "list_item",
                "Solder used to connect electrical and/or electronic parts to a circuit board (substrate) or a lead frame (when substrate)",
            ),
            (
                "list_item",
                "Protective coatings on the circuit board (Conformal coat materials)",
            ),
            ("list_item", "Shrink hoses for components on the circuit board."),
            (
                "paragraph",
                "Exemptions are defined in ELV Annex II paragraph 8 (x) and 10 (x).",
            ),
        ]


class TestHyphenJoin:
    def test_line_ending_in_hyphen_joins_without_space(self):
        lines = [
            _line(
                46.2,
                204.0,
                522.7,
                "If the internal voltage supply does not reach its steady-state value within the 5-second drop time, or if the 10-",
            ),
            _line(
                46.2, 215.0, 549.5, "second function test time at Usmin is too short."
            ),
        ]
        assert extract_text.join_line_texts(lines) == (
            "If the internal voltage supply does not reach its steady-state value within the 5-second drop time, "
            "or if the 10-second function test time at Usmin is too short."
        )

    def test_spaced_dash_and_minus_keep_the_space(self):
        lines = [
            _line(46, 100, 540, "Supply range Us -"),
            _line(46, 111, 200, "14 V to +24 V"),
        ]
        assert extract_text.join_line_texts(lines) == "Supply range Us - 14 V to +24 V"

    def test_paragraph_element_uses_the_hyphen_join(self):
        lines = [
            _line(46.2, 100, 540.0, "The h-"),
            _line(46.2, 111, 300.0, "point is the reference."),
        ]
        elements = extract_text.merge_list_and_paragraph_blocks(
            [({"bbox": [46.2, 100, 540.0, 122], "lines": lines}, lines)],
            10.0,
            {},
            {},
            [46.2],
            right_edge=554.0,
        )
        assert [e["text"] for e in elements] == ["The h-point is the reference."]


class TestSplitParagraphBlocks:
    def _blocks(self):
        # p71: one line per PyMuPDF block. Line gap 15 pt inside a
        # paragraph, 25 pt between paragraphs.
        rows = [
            (
                432.3,
                517.6,
                "This test is intended to evaluate permanent interference, as well as switch-off and switch-on transients sent",
            ),
            (
                447.3,
                486.1,
                "from the DUT (Fig. 1). It is also intended to evaluate “braked/disconnected” electric motors (state 3).",
            ),
            (
                472.7,
                500.4,
                "Permanent interference shall be measured when switch S1 is closed and switch S2 is closed to state 2.",
            ),
            (
                498.0,
                510.6,
                "Transients are measured when opening or closing switch S1, and when switching S2 between its different",
            ),
            (513.0, 75.6, "states."),
        ]
        out = []
        for y0, x1, text in rows:
            line = _line(46.2, y0, x1, text)
            out.append(({"bbox": list(line["bbox"]), "lines": [line]}, [line]))
        return out

    def test_wrapped_line_in_the_next_block_joins(self):
        elements = extract_text.merge_list_and_paragraph_blocks(
            self._blocks(), 10.0, {}, {}, [46.2], right_edge=530.5
        )
        assert [e["text"] for e in elements] == [
            (
                "This test is intended to evaluate permanent interference, as well as switch-off and switch-on transients sent "
                "from the DUT (Fig. 1). It is also intended to evaluate “braked/disconnected” electric motors (state 3)."
            ),
            "Permanent interference shall be measured when switch S1 is closed and switch S2 is closed to state 2.",
            "Transients are measured when opening or closing switch S1, and when switching S2 between its different states.",
        ]

    def test_wrap_before_a_long_word_joins(self):
        # p76: the line fills 83 % of the width; "component/system," did
        # not fit on it.
        first = _line(46.2, 81.6, 468.5, "Scope: This pulse originates from the switching off of an inductive load in parallel with the tested")
        second = _line(46.2, 96.6, 318.4, "component/system, e.g. electric valves without clamp diodes.")
        first["bbox"][3], second["bbox"][3] = 92.8, 107.8
        blocks = [
            ({"bbox": list(first["bbox"]), "lines": [first]}, [first]),
            ({"bbox": list(second["bbox"]), "lines": [second]}, [second]),
        ]
        elements = extract_text.merge_list_and_paragraph_blocks(blocks, 10.0, {}, {}, [46.2], right_edge=553.5)
        assert len(elements) == 1

    def test_full_line_followed_by_paragraph_gap_stays_split(self):
        first = _line(
            46.2,
            100,
            529.0,
            "A full line that ends a paragraph exactly at the right margin of the text",
        )
        second = _line(46.2, 125, 300.0, "A new paragraph after a paragraph gap.")
        blocks = [
            ({"bbox": list(first["bbox"]), "lines": [first]}, [first]),
            ({"bbox": list(second["bbox"]), "lines": [second]}, [second]),
        ]
        elements = extract_text.merge_list_and_paragraph_blocks(
            blocks, 10.0, {}, {}, [46.2], right_edge=530.5
        )
        assert len(elements) == 2


class TestSplitParagraphBlocksSparsePage:
    def test_short_lines_on_a_table_page_stay_apart(self):
        # p91: the page is a table; the right edge comes from these three
        # footnote lines alone, so each one looks "full" against it.
        rows = [(539.7, 113.4, "1)Broadcast"), (554.7, 113.9, "2)Free band"), (569.7, 157.6, "3)Mobile services band")]
        blocks = []
        for y0, x1, text in rows:
            line = _line(64.2, y0, x1, text)
            blocks.append(({"bbox": list(line["bbox"]), "lines": [line]}, [line]))
        elements = extract_text.merge_list_and_paragraph_blocks(blocks, 10.0, {}, {}, [46.2], right_edge=157.6)
        assert [e["text"] for e in elements] == ["1)Broadcast", "2)Free band", "3)Mobile services band"]


class TestListIndentRelativeToRun:
    def test_run_starting_at_level_three_is_not_indented(self):
        elements = [
            {"type": "paragraph", "text": "VT"},
            {"type": "list_item", "marker": "-", "level": 3, "text": "Color"},
            {
                "type": "list_item",
                "marker": "-",
                "level": 4,
                "text": "Visible components color",
            },
            {"type": "list_item", "marker": "-", "level": 3, "text": "Grain and gloss"},
        ]
        md = assemble.elements_to_markdown(elements)
        assert "- Color\n  - Visible components color\n- Grain and gloss" in md
        assert "    -" not in md

    def test_level_jump_is_clamped_to_one_step(self):
        elements = [
            {"type": "list_item", "marker": "-", "level": 1, "text": "Top"},
            {"type": "list_item", "marker": "-", "level": 4, "text": "Deep"},
        ]
        md = assemble.elements_to_markdown(elements)
        assert "- Top\n  - Deep" in md
