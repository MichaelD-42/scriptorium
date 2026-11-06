"""The grader's failure taxonomy (grade-output/rubric.md), split by what a
retry does about each tag (queue-state/scripts/state.py), and the one rule
that turns a page's tags into its score."""

import json

import paths

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


def write_shard(doc: str, page_number: int, issues: list[str], reason: str | None = None) -> dict:
    """Write one page's grade shard, scored by `score_from_issues`, and
    return it. Graders (write_grade_shard.py) and text_mode_grade.py both
    land here, so merge_grades.py reads one shape."""
    shard = {"page_number": page_number, "score": score_from_issues(issues), "issues": issues}
    if reason:
        shard["reason"] = reason
    shard_path = paths.grade_shard_path(doc, page_number)
    shard_path.parent.mkdir(parents=True, exist_ok=True)
    shard_path.write_text(json.dumps(shard, indent=2), encoding="utf-8", newline="")
    return shard
