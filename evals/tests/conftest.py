"""Eval tests run from the repo, never in CI (CI collects
plugins/scriptorium/tests only):

    uv run --project plugins/scriptorium pytest evals/tests
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "plugins" / "scriptorium" / "lib"))
sys.path.insert(0, str(REPO / "evals" / "grader"))
