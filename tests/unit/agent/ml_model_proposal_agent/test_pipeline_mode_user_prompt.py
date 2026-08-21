"""Structural regression guards for pipeline-mode user prompt assembly (Commit P-d).

These tests catch *accidental* regressions in the per-stage user prompt
assembly: a deleted block, a wrong order, a forgotten constraint/hardware
render. They do NOT validate prompt design quality — that's Checkpoint P's
job (offline human review on rendered output).

Per ``feedback_dont_test_static_analysis``: no tests here for what Pydantic
schema or pyright already enforces. Only structural assembly behavior the
LLM would observably read differently.

Per ``feedback_unit_tests_are_flow_only``: every heavy subsystem is mocked.
We exercise the user-prompt assembly path only — no real LLM call, no
training, no GPU.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from agent.schemas.proposal import (
    AgentCard,
    ExpertContextItem,
    ModelSelectionStrategy,
    ProposalInput,
    ReasoningPipelineConfig,
    ReasoningStage,
    ResearchPolicy,
    VocabEntry,
)
from agent.schemas.proposer_evidence import build_proposer_evidence
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from core.hardware_context import HardwareContext
from nodes.ml_model_proposal_agent import MLModelProposalAgent

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_interpretation() -> dict:
    return {
        "model_types": ["punet"],
        "model_descriptions": {"punet": "A baseline U-Net for denoising."},
        "per_model_best": {"punet": 1.2},
        "per_model_worst": {"punet": 0.4},
        "best_denoising_score": 1.2,
        "worst_denoising_score": 0.4,
        "best_config": {"model_config": {}, "train_config": {}, "loss_config": {}},
        "key_findings": ["Files 0-3 weak."],
        "bottlenecks": ["Low-freq recovery."],
        "take_home_message": "Try richer low-freq modelling.",
        "total_experiments": 1,
    }


def _make_agent_card(agent_name: str = "ml_literature_review") -> AgentCard:
    return AgentCard(
        agent_name=agent_name,
        role="Surveys ML literature for techniques.",
        expertise_domain="ML denoising architectures.",
        coverage="arXiv + S2 corpus.",
        limitations="Cannot run experiments.",
        trust_level="soft_prior",
        trust_guidance="Treat as promising priors; experiment runs confirm applicability.",
    )


def _make_finding(source_ref: str) -> ExpertContextItem:
    return ExpertContextItem(
        source="ml_literature_review",
        kind="literature",
        content="A literature finding worth considering.",
        source_ref=source_ref,
        confidence=0.85,
    )


def _make_hardware_context() -> HardwareContext:
    return HardwareContext(
        device_name="NVIDIA RTX 3090",
        total_memory_bytes=24 * 1024**3,
        compute_capability=(8, 6),
        multiprocessor_count=82,
        cuda_runtime_version="12.1",
        torch_version="2.1.0",
        hostname="test-host",
        device_available=True,
        discovered_at=datetime.now(UTC),
    )


def _make_input(
    *,
    constraints: list[str] | None = None,
    hardware: bool = True,
    agent_cards: list[AgentCard] | None = None,
    expert_context: list[ExpertContextItem] | None = None,
    vocab_seed: list[VocabEntry] | None = None,
) -> ProposalInput:
    pipeline = ReasoningPipelineConfig(
        stages=[
            ReasoningStage(name="comparison", system_prompt_key="COMPARATIVE_ANALYSIS"),
            ReasoningStage(name="causal_reasoning", system_prompt_key="CAUSAL_REASONING"),
        ],
        model_selection=ModelSelectionStrategy(),
        exploration_mode="explore",
        policy=ResearchPolicy(minimum_boldness=0.05),
    )
    return ProposalInput(
        interpretation_evidence=build_proposer_evidence(_make_interpretation()),
        existing_model_types=["punet"],
        constraints=constraints or [],
        agent_cards=agent_cards or [],
        expert_context=expert_context or [],
        vocab_seed=vocab_seed or [],
        reasoning_pipeline=pipeline,
        hardware_context=_make_hardware_context() if hardware else None,
        vram_budget_gb=None,
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace="/tmp/p_d_test", run_name="r1"),
        ),
    )


@pytest.fixture
def captured_prompts():
    """Capture every (system_prompt, user_prompt) pair the bridge receives.

    Yields ``(captured, bridge_factory)``. Pass ``bridge_factory`` into the
    agent constructor so it never instantiates a real ``LLMBridge`` (which
    would build an ``OpenAI`` client and require ``OPENAI_API_KEY``).

    The injected mock bridge's ``generate`` / ``generate_text`` return
    minimal valid response shapes per stage so the pipeline runs end-to-end
    without an LLM. Each call is recorded.
    """
    captured: list[tuple[str, str, str]] = []  # (label, system_prompt, user_prompt)

    def _fake_generate(system_prompt, user_prompt, **kwargs):
        label = kwargs.get("label", "")
        captured.append((label, system_prompt, user_prompt))
        # Return shape suitable for whatever stage is calling.
        if "comparison" in label:
            return {
                "comparisons": [
                    {
                        "model_type": "punet",
                        "source": "seed",
                        "best_score": 1.2,
                        "key_mechanism": "U-Net baseline.",
                        "strengths": ["scores 1.2 on file 0"],
                        "weaknesses": ["scores 0.4 on file 19"],
                        "lesson_for_next_proposal": "Inherit encoder.",
                    }
                ],
                "proposed_vocab_links": [],
                "proposed_vocab_candidates": [],
                "sota_model_type": "punet",
                "sota_score": 1.2,
                "sota_mechanism": "Plain U-Net structure.",
            }
        if "causal_reasoning" in label:
            return {
                "proposed_change": "Add spectral conv to encoder.",
                "causal_hypothesis": "Low-freq deficit traced to wavenet (punet) — "
                "Stage 1 ModelComparison for punet shows weakness on files 0-3.",
                "falsifiable_prediction": {
                    "metric": "mean(file_vector[0:5])",
                    "current_value": 0.5,
                    "predicted_value": 1.0,
                    "threshold_for_refutation": 0.6,
                    "rationale": "Spectral conv addresses low-freq.",
                },
                "predicted_failure_modes": ["spectral conv may add VRAM cost"],
                "inherited_components": [],
            }
        # proposing stage
        return {
            "model_name": "spectral_punet",
            "model_description": "punet + spectral conv.",
            "mathematical_definition": "Spectral conv layers added to encoder.",
            "motivation": "Addresses low-freq bottleneck per causal hypothesis.",
            "expert_advice": {
                "focus_areas": ["low-freq"],
                "constraints": ["VRAM < 10 GB", "params < 50M"],
                "known_failures": [],
                "suggested_directions": ["start small"],
                "rationale": "Conservative baseline.",
            },
            "baseline_config": {
                "model_config": {},
                "train_config": {"lr": 1e-4, "epochs": 1},
                "loss_config": {"loss_type": "focal", "alpha": 0.5, "gamma": 2.0},
            },
            "parameter_count_estimate": 1_000_000,
        }

    def _fake_generate_text(system_prompt, user_prompt, **kwargs):
        label = kwargs.get("label", "")
        captured.append((label, system_prompt, user_prompt))
        return ""

    bridge = MagicMock()
    bridge.generate.side_effect = _fake_generate
    bridge.generate_text.side_effect = _fake_generate_text

    yield captured, lambda **kw: bridge


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPipelineModeUserPromptOrder:
    def test_hardware_constraints_cards_context_precede_accumulated(self, captured_prompts):
        """All four top blocks render BEFORE the accumulated JSON dump.

        The P-d position-bias fix: external findings (cards + context) and
        hard constraints (hardware + ## Constraints) sit at the TOP of the
        user prompt, before KB of experiment history. Pre-P-d these blocks
        appended at the BOTTOM and the LLM systematically anchored on
        experiment data."""
        captured, bridge_factory = captured_prompts
        inp = _make_input(
            constraints=["VRAM < 10 GB"],
            hardware=True,
            agent_cards=[_make_agent_card()],
            expert_context=[_make_finding("arxiv:2312.00752")],
        )
        agent = MLModelProposalAgent(
            provider="openai", model_id="gpt-4o-mini", bridge_factory=bridge_factory
        )
        agent.run(inp)

        # We captured 3 stages (comparison + causal_reasoning + proposing).
        assert len(captured) >= 2
        for label, _system_prompt, user_prompt in captured:
            # The accumulated JSON dump is anchored on this exact header
            i_accum = user_prompt.find("## Accumulated context")
            assert i_accum >= 0, f"no accumulated JSON in {label!r} user prompt"

            i_hardware = user_prompt.find("[HARDWARE CONTEXT]")
            i_constraints = user_prompt.find("## Constraints")
            i_cards = user_prompt.find("## External Contributors")
            i_context = user_prompt.find("## Expert Context")

            assert i_hardware >= 0, f"[HARDWARE CONTEXT] missing in {label!r}"
            assert i_constraints >= 0, f"## Constraints missing in {label!r}"
            assert i_cards >= 0, f"## External Contributors missing in {label!r}"
            assert i_context >= 0, f"## Expert Context missing in {label!r}"

            # Each top block precedes the accumulated dump.
            assert i_hardware < i_accum, f"hardware after accumulated in {label!r}"
            assert i_constraints < i_accum, f"constraints after accumulated in {label!r}"
            assert i_cards < i_accum, f"cards after accumulated in {label!r}"
            assert i_context < i_accum, f"context after accumulated in {label!r}"

    def test_block_order_hardware_constraints_cards_context(self, captured_prompts):
        """Among the four top blocks, the exact order is locked:
        hardware → constraints → cards → context."""
        captured, bridge_factory = captured_prompts
        inp = _make_input(
            constraints=["VRAM < 10 GB"],
            hardware=True,
            agent_cards=[_make_agent_card()],
            expert_context=[_make_finding("arxiv:2312.00752")],
        )
        agent = MLModelProposalAgent(
            provider="openai", model_id="gpt-4o-mini", bridge_factory=bridge_factory
        )
        agent.run(inp)

        for label, _system_prompt, user_prompt in captured:
            i_hardware = user_prompt.find("[HARDWARE CONTEXT]")
            i_constraints = user_prompt.find("## Constraints")
            i_cards = user_prompt.find("## External Contributors")
            i_context = user_prompt.find("## Expert Context")
            assert i_hardware < i_constraints, f"order violation in {label!r}"
            assert i_constraints < i_cards, f"order violation in {label!r}"
            assert i_cards < i_context, f"order violation in {label!r}"


class TestPipelineModeOptionalBlocksOmitted:
    def test_no_hardware_no_hardware_block(self, captured_prompts):
        """When inp.hardware_context is None the [HARDWARE CONTEXT] block is
        omitted entirely (no empty header, no blank line). Same idiom as
        pre-P-d behavior for the agent_cards block."""
        captured, bridge_factory = captured_prompts
        inp = _make_input(hardware=False)
        agent = MLModelProposalAgent(
            provider="openai", model_id="gpt-4o-mini", bridge_factory=bridge_factory
        )
        agent.run(inp)

        assert captured
        for label, _system_prompt, user_prompt in captured:
            assert "[HARDWARE CONTEXT]" not in user_prompt, (
                f"hardware block leaked into {label!r} when hardware_context=None"
            )

    def test_no_constraints_no_existing_models_no_constraints_block(self, captured_prompts):
        """When both constraints and existing_model_types are empty the
        ## Constraints block is omitted entirely."""
        captured, bridge_factory = captured_prompts
        inp = ProposalInput(
            interpretation_evidence=build_proposer_evidence(_make_interpretation()),
            existing_model_types=[],  # explicitly empty
            constraints=[],
            reasoning_pipeline=ReasoningPipelineConfig(
                stages=[
                    ReasoningStage(name="comparison", system_prompt_key="COMPARATIVE_ANALYSIS"),
                    ReasoningStage(name="causal_reasoning", system_prompt_key="CAUSAL_REASONING"),
                ],
                exploration_mode="explore",
            ),
            storage=StorageConfig(
                backend="local",
                local=LocalStorageConfig(workspace="/tmp/p_d_test_b", run_name="r1"),
            ),
        )
        agent = MLModelProposalAgent(
            provider="openai", model_id="gpt-4o-mini", bridge_factory=bridge_factory
        )
        agent.run(inp)

        assert captured
        for label, _system_prompt, user_prompt in captured:
            assert "## Constraints" not in user_prompt, (
                f"constraints block leaked into {label!r} when both inputs empty"
            )


class TestSynthesizedHumanAgentCard:
    def test_human_advice_wrap_injects_strong_prior_agent_card(self):
        """The protocol's human_advice wrap path adds a synthesized human
        AgentCard with trust_level='strong_prior' so the wrapped item
        carries proper calibration under the P-c synthesis rules."""
        from agent.schemas.interpretation import InterpretationOutput
        from agent.schemas.protocols.ml_result_interp_to_ml_model_propose import (
            local_full_context,
        )

        interp = InterpretationOutput(
            model_types=["punet"],
            model_descriptions={"punet": "U-Net baseline."},
            total_experiments=1,
            per_model_best={"punet": 1.0},
            per_model_worst={"punet": 0.5},
            best_denoising_score=1.0,
            worst_denoising_score=0.5,
            best_config={},
            key_findings=["finding"],
            bottlenecks=["bn"],
            take_home_message="msg",
        )
        result = local_full_context(
            interp,
            StorageConfig(
                backend="local",
                local=LocalStorageConfig(workspace="/tmp/p_d_protocol", run_name="r1"),
            ),
            human_advice="Focus on low-freq recovery.",
        )

        # Exactly one agent_card injected (the synthesized human one).
        assert len(result.agent_cards) == 1
        card = result.agent_cards[0]
        assert card.agent_name == "human"
        assert card.trust_level == "strong_prior"

        # The corresponding expert_context entry is wrapped under
        # source='human' and a source_ref with the 'human:' prefix per the
        # P-b regex format.
        human_items = [c for c in result.expert_context if c.source == "human"]
        assert len(human_items) == 1
        assert human_items[0].source_ref.startswith("human:")
