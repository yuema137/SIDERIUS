"""Step-00 PB-7 (interpretation synthesis/dedup/flag-ON) + PB-8 (consolidator).

Design: ``docs/design/generic_framework_upgrade/step_00_golden_baseline_harness.md``
§13.1 / §15.1 (roadmap step 09 A-surface). The three EXISTING per-model
goldens (PB-0) are all flag-OFF; the flag-ON variants close that gap using
the SAME fixtures so the delta is exactly the flag.

Synthesis workspace hazard (§13.1/§15.1): the workspace string is
interpolated VERBATIM into the prompt (`result_interpretation_agent.py:
638-651`) — a MIGRATION PARITY behavior, not blessed. The fixture pins a
frozen literal (NEVER ``tmp_path``), and the pin is asserted load-bearing.
"""

from __future__ import annotations

from pathlib import Path

from agent.cache_consolidator import _LIST_MERGE_SYSTEM_PROMPT, consolidate
from agent.prompt_templates.interpretation.rendering import (
    DEDUP_SYSTEM_PROMPT,
    HEALTH_FEEDBACK_SYSTEM_INSTRUCTIONS,
    _build_per_model_prompt,
    _build_per_model_system_prompt,
    _build_synthesis_prompt,
    _build_synthesis_system_prompt,
)
from agent.prompt_templates.interpretation.task_blocks import load_interpretation_task_blocks
from agent.schemas.cache_entry import CacheEntry, ConsolidatedFinding
from agent.schemas.interpretation import InterpretationInput, VocabEntry
from execute_tools.metric_order import MetricOrder
from nodes.result_interpretation_agent import ResultInterpretationAgent
from tests.helpers.golden import assert_golden
from tests.helpers.llm_boundary_recorder import BoundaryRecorderBridge
from tests.helpers.metric_fixtures import shipped_spec
from tests.unit.agent.result_interpretation_agent.test_health_prompt_parity import (
    _summary_collapse,
)

#: Step 09a C3 — the migrated ordering consumers take the run's MetricOrder
#: as a REQUIRED keyword. TIDMAD is `higher`, so expectations are unchanged.
_STEP09A_ORDER = MetricOrder(shipped_spec())

GOLDENS = Path(__file__).parent / "goldens"

# Frozen literal — NEVER tmp_path (the string lands verbatim in the prompt).
_PB7_WORKSPACE = "/siderius/pb7/ws/iter_003"


class TestPB7PerModelFlagOn:
    def test_per_model_user_prompt_flag_on(self):
        rendered = _build_per_model_prompt(
            _summary_collapse(),
            "A test architecture.",
            expert_advice_str="Focus on stability.",
            human_advice=None,
            structured_health_feedback=True,
            order=_STEP09A_ORDER,
        )
        assert_golden(
            rendered,
            GOLDENS / "per_model_prompt_collapse_flag_on.txt",
            surface="PB-7 per_model user prompt (flag ON)",
        )

    def test_per_model_system_prompt_flag_on(self):
        inp = InterpretationInput(
            model_types=["wavenet"],
            task_description="Denoise SQUID data.",
            # Step 09b C2 — production shape: TIDMAD's science reaches the
            # system prompt through the task blocks, not the template.
            task_blocks=load_interpretation_task_blocks(),
            enable_structured_health_feedback=True,
        )
        rendered = _build_per_model_system_prompt(inp)
        assert_golden(
            rendered,
            GOLDENS / "per_model_system_prompt_flag_on.txt",
            surface="PB-7 per_model system prompt (flag ON)",
        )
        # Structural identity: flag-ON == flag-OFF golden + the constant.
        off = (GOLDENS / "per_model_system_prompt.txt").read_text(encoding="utf-8")
        assert rendered == off + HEALTH_FEEDBACK_SYSTEM_INSTRUCTIONS


class TestPB7Synthesis:
    def test_synthesis_user_prompt(self):
        rendered = _build_synthesis_prompt(
            per_model_summaries={
                "wavenet": {
                    "key_findings": ["f1"],
                    "bottlenecks": ["b1"],
                    "best_config_analysis": "bca",
                    "score_trend": "st",
                },
                "punet": {"one_line_takeaway": "tk", "best_score": -2.5, "n_rounds": 3},
            },
            per_model_best={"wavenet": -2.1, "punet": -2.5},
            per_model_worst={"wavenet": -3.0, "punet": -3.3},
            overall_best_score=-2.1,
            overall_worst_score=-3.3,
            overall_best_config={"lr": 1e-3},
            compressed_model_types={"punet"},
            workspace=_PB7_WORKSPACE,
        )
        # The workspace pin is load-bearing: verbatim interpolation
        # (MIGRATION PARITY — not blessed as a framework contract).
        assert _PB7_WORKSPACE in rendered
        assert_golden(
            rendered, GOLDENS / "pb7_synthesis_user.txt", surface="PB-7 synthesis user prompt"
        )

    def test_synthesis_system_prompt(self):
        inp = InterpretationInput(
            model_types=["wavenet", "punet"],
            task_description="Denoise SQUID data.",
            # Step 09b C2 — production shape (see the flag-ON case above).
            task_blocks=load_interpretation_task_blocks(),
        )
        assert_golden(
            _build_synthesis_system_prompt(inp),
            GOLDENS / "pb7_synthesis_system.txt",
            surface="PB-7 synthesis system prompt",
        )


class TestPB7Dedup:
    def test_dedup_prompt_via_agent(self):
        rec = BoundaryRecorderBridge()
        agent = ResultInterpretationAgent(bridge_factory=lambda **kw: rec)
        vocab = [
            VocabEntry(
                name="gated_recurrence",
                kind="feature",
                description="Hidden-state gating.",
                tier="canonical",
            ),
            VocabEntry(
                name="gated_rnn", kind="feature", description="Gating in RNNs.", tier="canonical"
            ),
            VocabEntry(
                name="dilated_convolution",
                kind="feature",
                description="Dilated conv stack.",
                tier="canonical",
            ),
        ]
        agent._dedup_promoted(["gated_recurrence"], vocab)
        assert len(rec.captures) == 1, "dedup call must fire exactly once"
        method, label, system, user = rec.captures[0]
        assert (method, label) == ("_chat_json", "interpretation.dedup")
        assert system == DEDUP_SYSTEM_PROMPT
        assert_golden(system, GOLDENS / "pb7_dedup_system.txt", surface="PB-7 dedup system prompt")
        assert_golden(user, GOLDENS / "pb7_dedup_user.txt", surface="PB-7 dedup user prompt")


class TestPB8CacheConsolidator:
    def test_list_merge_prompt(self):
        prior = CacheEntry(
            model_type="wavenet",
            key_findings=[
                ConsolidatedFinding(statement="S1", evidence_iters=[3], strength="strong"),
                ConsolidatedFinding(statement="S2", evidence_iters=[4], strength="weak"),
            ],
        )
        rec = BoundaryRecorderBridge()
        consolidate(
            rec,
            prior=prior,
            new_llm_response={"key_findings": ["N1", "N2"], "bottlenecks": []},
            new_stats={},
            current_iter=5,
            prior_iter=4,
        )
        assert len(rec.captures) == 1, "bottlenecks must take the no-new fast path"
        method, label, system, user = rec.captures[0]
        assert (method, label) == ("_chat_json", "cache_consolidator.list_merge")
        assert system == _LIST_MERGE_SYSTEM_PROMPT
        assert_golden(
            system, GOLDENS / "pb8_list_merge_system.txt", surface="PB-8 list_merge system prompt"
        )
        assert_golden(
            user, GOLDENS / "pb8_list_merge_user.txt", surface="PB-8 list_merge user prompt"
        )
