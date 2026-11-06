"""The grader's failure taxonomy (grade-output/rubric.md), split by what a
retry does about each tag (queue-state/scripts/state.py), and the one rule
that turns a page's tags into its score."""

# Wrong body text: the page's body tier goes up one rung.
CONTENT_ISSUES = frozenset(
    {
        "dropped_text",
        "hallucinated_text",
        "wrong_reading_order",
        "duplicated_text",
        "wrong_heading_level",
        "table_corruption",
    }
)
# Wrong figure: same tier, the extractor redoes only the image step.
IMAGE_ISSUES = frozenset({"missing_image", "bad_caption", "bad_mermaid"})
# A paragraph cut at a page break and not joined: the join is a script
# (lib/elements.py), so no tier changes it -- a human fixes the rule.
JOIN_ISSUES = frozenset({"split_paragraph"})
ISSUES = CONTENT_ISSUES | IMAGE_ISSUES | JOIN_ISSUES
# Fail the document whatever the average: a missing figure is lost content.
BLOCKING_ISSUES = CONTENT_ISSUES | JOIN_ISSUES | {"missing_image"}

PENALTY_PER_ISSUE = 0.3


def score_from_issues(issues) -> float:
    """A page's score from its distinct tags. Graders only tag; the number
    is this rule, so two graders that agree on tags agree on the score."""
    return round(max(0.0, 1.0 - PENALTY_PER_ISSUE * len(set(issues))), 3)
