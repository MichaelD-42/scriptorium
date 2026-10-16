"""queue-state/scripts/plan.py: which pages need an agent at all, and how
to batch them so no agent runs out of turns."""

import json

import elements as elements_lib
import paths
from conftest import load_script

plan = load_script("queue-state/scripts/plan.py", "queue_plan")


def _setup(tmp_project, doc="d", fmt="pdf", tiers=None, attempt=0, escalated=None):
    tiers = tiers or {1: "text"}
    (tmp_project / "input" / f"{doc}.{fmt if fmt != 'image' else 'png'}").write_bytes(
        b""
    )
    paths.triage_json(doc).parent.mkdir(parents=True, exist_ok=True)
    paths.triage_json(doc).write_text(
        json.dumps(
            {
                "page_count": len(tiers),
                "pages": [{"page_number": n, "tier": t} for n, t in tiers.items()],
            }
        )
    )
    (tmp_project / "runs" / "state.json").write_text(
        json.dumps(
            {
                "docs": {
                    doc: {
                        "status": "pending" if not attempt else "retrying",
                        "attempt": attempt,
                        "input_format": fmt,
                        "format": "md",
                        "escalated_pages": escalated or {},
                    }
                }
            }
        )
    )
    return doc


def _images(doc, page, *elements):
    elements_lib.write_shard(paths.shard_path(doc, page, "image"), page, list(elements))


DESCRIBED = {
    "type": "image",
    "asset": "a.png",
    "description": "a chart",
    "caption": "Figure 1",
}
BARE = {"type": "image", "asset": "b.png"}


class TestPack:
    def test_greedy_contiguous_batches_within_budget(self):
        batches, over = plan.pack(
            [(1, 4), (2, 4), (3, 4), (4, 4)], budget=10, max_pages=None
        )
        assert batches == [[1, 2], [3, 4]]
        assert over == []

    def test_a_page_over_budget_gets_its_own_batch_and_is_reported(self):
        batches, over = plan.pack([(1, 2), (2, 30), (3, 2)], budget=10, max_pages=None)
        assert batches == [[1], [2], [3]]
        assert over == [2]

    def test_max_pages_caps_a_batch(self):
        batches, _ = plan.pack([(n, 1) for n in range(1, 6)], budget=100, max_pages=2)
        assert batches == [[1, 2], [3, 4], [5]]


def test_budget_comes_from_the_agents_max_turns():
    assert plan.turn_budget("extractor") == int(30 * plan.HEADROOM)
    assert plan.turn_budget("grader") == int(20 * plan.HEADROOM)


class TestScriptsStage:
    def test_attempt_0_pdf(self, tmp_project):
        doc = _setup(tmp_project, tiers={1: "text", 2: "ocr", 3: "text"})
        assert plan.scripts_stage(doc) == {
            "extract_text": [1, 3],
            "extract_images": [1, 2, 3],
        }

    def test_attempt_0_docx_runs_the_format_extractor_on_every_page(self, tmp_project):
        doc = _setup(tmp_project, fmt="docx", tiers={1: "text", 2: "text"})
        assert plan.scripts_stage(doc) == {"format_extract": [1, 2]}

    def test_retry_redoes_only_the_image_step_of_recheck_pages(self, tmp_project):
        doc = _setup(
            tmp_project,
            tiers={1: "text", 2: "text"},
            attempt=1,
            escalated={
                "1": {"tier": "ocr", "recheck_images": False, "reason": "x"},
                "2": {"tier": "text", "recheck_images": True, "reason": "y"},
            },
        )
        assert plan.scripts_stage(doc) == {"extract_text": [], "extract_images": [2]}


class TestExtractStage:
    def test_only_pages_with_agent_work_are_batched(self, tmp_project):
        doc = _setup(tmp_project, tiers={1: "text", 2: "text", 3: "ocr"})
        _images(doc, 1, DESCRIBED)
        _images(doc, 2, BARE, BARE)
        _images(doc, 3)

        out = plan.extract_stage(doc, max_pages=None)

        assert out["agent_free_pages"] == 1
        assert [b["pages"] for b in out["batches"]] == [[2, 3]]
        assert out["batches"][0]["tiers"] == {"2": "text", "3": "ocr"}

    def test_retry_batch_carries_tiers_and_reasons(self, tmp_project):
        doc = _setup(
            tmp_project,
            tiers={1: "text", 2: "text"},
            attempt=1,
            escalated={
                "2": {
                    "tier": "vision",
                    "recheck_images": False,
                    "reason": "table rows dropped",
                }
            },
        )
        _images(doc, 2, DESCRIBED)

        batch = plan.extract_stage(doc, max_pages=None)["batches"][0]

        assert batch["pages"] == [2]
        assert batch["tiers"] == {"2": "vision"}
        assert batch["reasons"] == {"2": "table rows dropped"}
        assert batch["recheck_images"] == []


class TestGradeStage:
    def test_figures_make_a_page_heavier(self, tmp_project):
        doc = _setup(tmp_project, tiers={n: "text" for n in range(1, 5)})
        elements_lib.save_doc(
            paths.elements_json(doc),
            {
                "pages": {
                    n: {
                        "page_number": n,
                        "tier": "text",
                        "elements": [BARE] * (10 if n == 1 else 0),
                    }
                    for n in range(1, 5)
                }
            },
        )

        out = plan.grade_stage(doc, max_pages=None)

        assert out["batches"][0]["pages"] == [1]
        assert sum(len(b["pages"]) for b in out["batches"]) == 4

    def test_digital_native_formats_grade_by_script(self, tmp_project):
        doc = _setup(tmp_project, fmt="xlsx")
        assert plan.grade_stage(doc, max_pages=None) == {
            "text_mode": True,
            "batches": [],
        }
