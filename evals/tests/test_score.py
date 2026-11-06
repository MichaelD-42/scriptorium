"""evals/grader/score.py: recall per injected tag, and every other tag a
false positive."""

import score as score_mod

CASES = [
    {"doc": "clean", "pages": [4, 7], "expected": {}},
    {"doc": "drop", "pages": [1, 3], "expected": {"1": "dropped_text"}},
    {"doc": "cap", "pages": [7, 9], "expected": {"7": "bad_caption"}},
]


def test_found_missed_false_positive_and_ungraded():
    shards = {
        "clean": {4: [], 7: ["missing_image"]},
        "drop": {1: ["dropped_text", "wrong_reading_order"], 3: []},
        "cap": {7: []},
    }
    result = score_mod.score(CASES, shards)
    assert result["per_tag"] == {
        "dropped_text": {"found": 1, "cases": 1},
        "bad_caption": {"found": 0, "cases": 1},
    }
    assert result["recall"] == 0.5
    assert result["false_positives"] == [
        {"doc": "clean", "page": 7, "tag": "missing_image"},
        {"doc": "drop", "page": 1, "tag": "wrong_reading_order"},
    ]
    assert result["ungraded"] == ["cap p9"]
