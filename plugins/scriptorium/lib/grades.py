"""The grader's failure taxonomy (grade-output/rubric.md), split by what a
retry does about each tag (queue-state/scripts/state.py)."""

# Wrong body text: the page's body tier goes up one rung.
CONTENT_ISSUES = frozenset({
    "dropped_text", "hallucinated_text", "wrong_reading_order",
    "duplicated_text", "wrong_heading_level", "table_corruption",
})
# Wrong figure: same tier, the extractor redoes only the image step.
IMAGE_ISSUES = frozenset({"missing_image", "bad_caption", "bad_mermaid"})
ISSUES = CONTENT_ISSUES | IMAGE_ISSUES
