"""PRODUCTION pipeline-mode delivery of the [HEALTHGATE EVIDENCE] block.

P3-V1 reopen fix (pr3_healthgate_feedback.md §3.7): production runs use
``_run_pipeline``'s template assembly (source comment :481), which the
CB4 legacy-mode splice never reached. These tests exercise the REAL
pipeline — ``MLModelProposalAgent.run()`` with configured stages and a
mock bridge — and assert on the ACTUAL stage prompts the bridge
received. Per the operator rule, ``_build_reasoning_prompt`` evidence is
NOT accepted for the production-pipeline claim; nothing here touches it.
"""

from unittest.mock import MagicMock

from agent.schemas.proposal import ProposalInput, ReasoningPipelineConfig, ReasoningStage
from agent.schemas.proposer_evidence import build_proposer_evidence
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.ml_model_proposal_agent import MLModelProposalAgent
from nodes.ml_model_proposal_agent.ml_model_proposal_agent import (
    _format_recent_gate_exhaustions_block,
)
from tests.unit.agent.ml_model_proposal_agent._health_feedback_fixtures import (
    SIG_A,
    SIG_B,
    gate_exhaustion,
    structured_interpretation_output,
)
from tests.unit.agent.ml_model_proposal_agent.test_prompt_context_surfacing import (
    _FAKE_COMPARISON,
    _FAKE_PROPOSING,
    _FAKE_REASONING,
)


def _pipeline_input(tmp_path, *, on: bool, interp: dict | None = None) -> ProposalInput:
    dump = (
        interp if interp is not None else structured_interpretation_output().model_dump(mode="json")
    )
    return ProposalInput(
        interpretation_evidence=build_proposer_evidence(dump),
        existing_model_types=["model_a", "model_b"],
        recent_gate_exhaustions=[gate_exhaustion()],
        enable_structured_health_feedback=on,
        reasoning_pipeline=ReasoningPipelineConfig(
            exploration_mode="exploit",
            stages=[
                ReasoningStage(name="comparison", system_prompt_key="COMPARATIVE_ANALYSIS"),
                ReasoningStage(name="causal_reasoning", system_prompt_key="CAUSAL_REASONING"),
            ],
        ),
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="pipe"),
        ),
    )


def _run_pipeline_capture(inp) -> list[str]:
    """Run the REAL pipeline with a mock bridge; return every system
    prompt the bridge received (comparison, causal, proposing)."""
    mock_bridge = MagicMock()
    mock_bridge.generate.side_effect = [_FAKE_COMPARISON, _FAKE_REASONING, _FAKE_PROPOSING]
    agent = MLModelProposalAgent(
        provider="gemini", model_id="test", bridge_factory=lambda **kw: mock_bridge
    )
    agent.run(inp)
    prompts = []
    for call in mock_bridge.generate.call_args_list:
        prompts.append(call.kwargs.get("system_prompt") or call.args[0])
    return prompts


def _proposing_prompt(prompts: list[str]) -> str:
    """The final (proposing) stage system prompt — the one that emits the
    proposal JSON. Identified by its schema-skeleton marker."""
    final = prompts[-1]
    assert "custom_loss_spec" in final  # proposing_stage.md marker
    return final


class TestPipelineFlagOn:
    def test_block_reaches_the_real_proposing_stage_prompt(self, tmp_path):
        prompts = _run_pipeline_capture(_pipeline_input(tmp_path, on=True))
        final = _proposing_prompt(prompts)
        assert "[HEALTHGATE EVIDENCE]" in final
        # Exact fingerprints with attribution, retained-window counts,
        # and representative metrics — in the PRODUCTION stage prompt.
        a_sec = final.split("### model_a")[1].split("### model_b")[0]
        b_sec = final.split("### model_b")[1]
        assert SIG_A in a_sec and SIG_B not in a_sec
        assert SIG_B in b_sec and SIG_A not in b_sec
        assert f"- {SIG_A}: 3 occurrence(s) across iteration(s) 3, 5" in final
        assert "Representative observation: output_std_mv=0.0431" in final

    def test_block_renders_in_exactly_one_stage(self, tmp_path):
        """Narrowest-stage guarantee: the evidence appears in the
        proposing stage only — no duplicated context in earlier stages."""
        prompts = _run_pipeline_capture(_pipeline_input(tmp_path, on=True))
        hits = [p for p in prompts if "[HEALTHGATE EVIDENCE]" in p]
        assert len(hits) == 1
        assert hits[0] == _proposing_prompt(prompts)

    def test_adjacent_but_separate_from_gate_exhaustions(self, tmp_path):
        prompts = _run_pipeline_capture(_pipeline_input(tmp_path, on=True))
        final = _proposing_prompt(prompts)
        exhaustion_block = _format_recent_gate_exhaustions_block([gate_exhaustion()])
        assert exhaustion_block in final  # §14.N byte-identical inside the prompt
        assert final.find("[RECENT GATE EXHAUSTIONS") < final.find("[HEALTHGATE EVIDENCE]")


class TestPipelineFlagOff:
    def test_off_prompt_has_no_evidence_and_placeholder_collapses(self, tmp_path):
        prompts = _run_pipeline_capture(_pipeline_input(tmp_path, on=False))
        final = _proposing_prompt(prompts)
        assert "[HEALTHGATE EVIDENCE]" not in final
        assert SIG_A not in final and SIG_B not in final
        assert "Representative observation" not in final
        assert "{healthgate_evidence_block}" not in final  # substituted, not leaked

    def test_off_prompt_identical_to_legacy_interp_prompt(self, tmp_path):
        """Pre-PR3 preservation on the production path: with the flag OFF,
        the proposing-stage prompt from a structured-evidence payload is
        byte-identical to the prompt from a legacy payload carrying the
        same conventional fields — the PR 3 fields change nothing."""
        structured = structured_interpretation_output().model_dump(mode="json")
        legacy = {
            k: v
            for k, v in structured.items()
            if k
            not in (
                "per_model_round_health_counts",
                "per_model_collapse_fingerprints",
                "collapse_fingerprint_history",
            )
        }
        p_structured = _proposing_prompt(
            _run_pipeline_capture(_pipeline_input(tmp_path / "a", on=False))
        )
        p_legacy = _proposing_prompt(
            _run_pipeline_capture(_pipeline_input(tmp_path / "b", on=False, interp=legacy))
        )
        assert p_structured == p_legacy

    def test_legacy_interp_with_flag_on_renders_nothing(self, tmp_path):
        legacy = {
            "model_types": ["wavenet"],
            "total_experiments": 3,
            "key_findings": [],
            "bottlenecks": [],
            "take_home_message": "x",
        }
        prompts = _run_pipeline_capture(_pipeline_input(tmp_path, on=True, interp=legacy))
        final = _proposing_prompt(prompts)
        assert "[HEALTHGATE EVIDENCE]" not in final  # no invented block
