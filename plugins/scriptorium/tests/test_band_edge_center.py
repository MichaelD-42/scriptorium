"""Re-review 2 M1: with a content rect, the band test uses the line's center.

A title-block line's glyph bbox can cross the frame rule: its top lies a
little inside the content rect. `furniture.furniture_edge` used to ask for
the whole span outside the rect, so such a line was kept as body text and
the gate passed. With a content rect, the span is now in the bottom band
when its vertical center is at or below the rect's bottom edge (and in the
top band when its center is at or above the top edge). Without a content
rect the 12% bands keep the whole-span test.
"""

import furniture as furniture_lib

H = 842.0
RECT = [42.0, 28.0, 558.0, 719.0]


class TestCenterAgainstRectEdges:
    def test_title_block_line_crossing_the_bottom_rule_is_furniture(self):
        y0 = RECT[3] - 0.6
        assert furniture_lib.furniture_edge(y0, y0 + 9.0, H, RECT) == "bottom"
        assert furniture_lib.in_furniture_band([60, y0, 200, y0 + 9.0], H, RECT)

    def test_line_crossing_the_top_rule_is_furniture(self):
        y1 = RECT[1] + 0.6
        assert furniture_lib.furniture_edge(y1 - 9.0, y1, H, RECT) == "top"

    def test_body_line_crossing_the_rule_from_inside_is_body(self):
        # Center inside the rect: the last body line whose descenders reach
        # past the rule.
        y1 = RECT[3] + 0.6
        assert furniture_lib.furniture_edge(y1 - 9.0, y1, H, RECT) is None

    def test_patterns_for_a_crossing_title_block_line(self):
        y0 = RECT[3] - 0.6
        patterns = furniture_lib.patterns_for_element(
            {"DocumentTitle"}, [60, y0, 200, y0 + 9.0], H, RECT
        )
        assert patterns == {"DocumentTitle"}

    def test_without_a_rect_the_whole_span_must_be_in_the_band(self):
        bottom = 0.88 * H
        assert furniture_lib.furniture_edge(bottom - 0.6, bottom + 8.4, H) is None
        assert furniture_lib.furniture_edge(bottom, bottom + 9.0, H) == "bottom"
