"""
Tests for nodes/ml_model_proposal_agent.py

LLM calls are mocked — these tests validate:
  - Both LLM calls are made: generate_text (reasoning) then generate (commit)
  - Reasoning text is injected into the commit prompt
  - LLM response is merged correctly into ProposalOutput
  - expert_advice dict is coerced to ExpertAdvice instance
  - Output validates against ProposalOutput schema
  - Output file written to the correct path with correct content
  - Duplicate model_name raises ValueError
  - Empty existing_model_types does not block a valid name
"""
import json
import pytest
from unittest.mock import MagicMock, patch, call

from agent.schemas.proposal import ProposalInput, ProposalOutput, VocabEntry
from agent.schemas.hyperparam_tuning import ExpertAdvice
from agent.schemas.score_table import (
    AggregateScalars, PerFileRow, ScoreComparisonTable,
)
from agent.schemas.storage import StorageConfig, LocalStorageConfig
from nodes.ml_model_proposal_agent import MLModelProposalAgent, _build_reasoning_prompt


def _make_score_table_dict(fv):
    """Serialized ScoreComparisonTable fixture matching what the interp dict
    carries in production (output.model_dump() through the protocol)."""
    rows = [
        PerFileRow(
            file_index=i, raw_baseline=0.1, ground_truth=100.0,
            model=v,
            gain_vs_raw=(v - 0.1) if v is not None else None,
            headroom_vs_gt=(100.0 - v) if v is not None else None,
        )
        for i, v in enumerate(fv)
    ]
    return ScoreComparisonTable(
        rows=rows,
        aggregate=AggregateScalars(
            raw_baseline_scalar=0.1, ground_truth_scalar=100.0,
            model_scalar=0.5, percent_of_ceiling_log=0.005,
            num_sampled_files=len([v for v in fv if v is not None]) or 1,
        ),
        s_max_global=1.0, reference_source="test",
        rendered_markdown="(test)",
    ).model_dump()


# ---------------------------------------------------------------------------
# Fake LLM responses
# ---------------------------------------------------------------------------

FAKE_REASONING = (
    "The bottleneck is the limited receptive field of the current U-Net at the "
    "sequence level. A multi-scale attention mechanism would address this by allowing "
    "the model to attend to both local and global patterns simultaneously..."
)

FAKE_COMMIT_RESPONSE = {
    "model_name": "attn_unet",
    "model_description": "A U-Net variant augmented with multi-head self-attention at the bottleneck.",
    "mathematical_definition": (
        "1. Embedding: nn.Embedding(256, 32) → [B, T, 32], permuted to [B, 32, T]. "
        "2. Encoder: 3 down-blocks, each Conv1d(C, 2C, k=9, stride=2) + GroupNorm + GELU. "
        "3. Bottleneck: MultiheadAttention(embed_dim=256, num_heads=4) over T dimension. "
        "4. Decoder: 3 up-blocks with bilinear upsampling + skip connections from encoder. "
        "5. Head: Conv1d(32, 256, k=1) → [B, 256, T] float32."
    ),
    "motivation": (
        "The take-home message identified that the architecture capacity ceiling prevents "
        "further improvement. Self-attention at the bottleneck addresses the receptive "
        "field bottleneck without significantly increasing parameter count."
    ),
    "expert_advice": {
        "focus_areas": ["tune attention heads before depth", "try focal gamma 2-4"],
        "constraints": ["VRAM < 10 GB", "params < 50M"],
        "known_failures": ["large batch_size with long sequences"],
        "suggested_directions": ["start with depth=2, nhead=4, lr=1e-4"],
        "rationale": "Attention bottleneck is sensitive to learning rate; start conservative.",
    },
    "baseline_config": {
        "model_config": {"depth": 2, "multi": 32, "nhead": 4},
        "train_config": {
            "lr": 1e-4, "epochs": 10, "batch_size": 1,
            "optimizer_type": "adamw", "weight_decay": 1e-5, "device": "cuda",
        },
        "loss_config": {"loss_type": "focal", "alpha": 0.5, "gamma": 2.0, "reduction": "mean"},
    },
}

FAKE_INTERPRETATION = {
    "model_types": ["punet", "fcnet"],
    "model_descriptions": {"punet": "PUNet description...", "fcnet": "FCNet description..."},
    "total_experiments": 20,
    "per_model_best":  {"punet": 1.8, "fcnet": 0.9},
    "per_model_worst": {"punet": 1.2, "fcnet": 0.7},
    "best_denoising_score": 1.8,
    "worst_denoising_score": 0.7,
    "best_config": {"model_config": {"depth": 4}, "train_config": {"lr": 3e-4}},
    "key_findings": ["focal loss consistently outperforms ce"],
    "bottlenecks": ["architecture capacity ceiling at depth=3"],
    "take_home_message": "The current architecture has saturated; a new design is needed.",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def agent():
    with patch("nodes.ml_model_proposal_agent.LLMBridge") as MockBridge:
        MockBridge.return_value.generate_text.return_value = FAKE_REASONING
        MockBridge.return_value.generate.return_value = FAKE_COMMIT_RESPONSE
        a = MLModelProposalAgent(provider="gemini", model_id="test-model")
        a.bridge = MockBridge.return_value
        yield a


def make_input(workspace, run_name="r1", existing_model_types=None, constraints=None,
               human_advice=None):
    return ProposalInput(
        interpretation=FAKE_INTERPRETATION,
        existing_model_types=existing_model_types or [],
        constraints=constraints or [],
        human_advice=human_advice,
        storage={"backend": "local", "local": {"workspace": str(workspace), "run_name": run_name}},
    )


# ---------------------------------------------------------------------------
# LLM call structure
# ---------------------------------------------------------------------------

class TestLLMCallStructure:

    def test_generate_text_called_once(self, agent, tmp_path):
        agent.run(make_input(tmp_path))
        agent.bridge.generate_text.assert_called_once()

    def test_generate_called_once(self, agent, tmp_path):
        agent.run(make_input(tmp_path))
        agent.bridge.generate.assert_called_once()

    def test_reasoning_injected_into_commit_prompt(self, agent, tmp_path):
        agent.run(make_input(tmp_path))
        commit_call_args = agent.bridge.generate.call_args
        user_prompt = commit_call_args[0][1]
        assert FAKE_REASONING in user_prompt

    def test_generate_text_called_before_generate(self, agent, tmp_path):
        call_order = []
        agent.bridge.generate_text.side_effect = lambda *a, **kw: call_order.append("text") or FAKE_REASONING
        agent.bridge.generate.side_effect     = lambda *a, **kw: call_order.append("json") or FAKE_COMMIT_RESPONSE
        agent.run(make_input(tmp_path))
        assert call_order == ["text", "json"]


# ---------------------------------------------------------------------------
# Output correctness
# ---------------------------------------------------------------------------

class TestOutputCorrectness:

    def test_output_is_valid_proposal_output(self, agent, tmp_path):
        output = agent.run(make_input(tmp_path))
        assert isinstance(output, ProposalOutput)

    def test_model_name_from_llm(self, agent, tmp_path):
        output = agent.run(make_input(tmp_path))
        assert output.model_name == "attn_unet"

    def test_model_description_from_llm(self, agent, tmp_path):
        output = agent.run(make_input(tmp_path))
        assert "U-Net" in output.model_description

    def test_mathematical_definition_from_llm(self, agent, tmp_path):
        output = agent.run(make_input(tmp_path))
        assert "Embedding" in output.mathematical_definition

    def test_motivation_from_llm(self, agent, tmp_path):
        output = agent.run(make_input(tmp_path))
        assert "take-home message" in output.motivation

    def test_expert_advice_is_expert_advice_instance(self, agent, tmp_path):
        output = agent.run(make_input(tmp_path))
        assert isinstance(output.expert_advice, ExpertAdvice)

    def test_expert_advice_fields_populated(self, agent, tmp_path):
        output = agent.run(make_input(tmp_path))
        assert "VRAM < 10 GB" in output.expert_advice.constraints
        assert len(output.expert_advice.focus_areas) > 0
        assert len(output.expert_advice.suggested_directions) > 0

    def test_baseline_config_has_required_keys(self, agent, tmp_path):
        output = agent.run(make_input(tmp_path))
        assert "model_config" in output.baseline_config
        assert "train_config" in output.baseline_config
        assert "loss_config"  in output.baseline_config


# ---------------------------------------------------------------------------
# File persistence
# ---------------------------------------------------------------------------

class TestFilePersistence:

    def test_output_written_to_file(self, agent, tmp_path):
        agent.run(make_input(tmp_path, run_name="myrun"))
        out_path = tmp_path / "proposal_myrun.json"
        assert out_path.exists()

    def test_output_file_is_valid_json(self, agent, tmp_path):
        agent.run(make_input(tmp_path, run_name="r1"))
        data = json.loads((tmp_path / "proposal_r1.json").read_text())
        assert data["model_name"] == "attn_unet"

    def test_output_file_contains_expert_advice(self, agent, tmp_path):
        agent.run(make_input(tmp_path, run_name="r1"))
        data = json.loads((tmp_path / "proposal_r1.json").read_text())
        assert "expert_advice" in data
        assert "constraints" in data["expert_advice"]


# ---------------------------------------------------------------------------
# Human advice injection
# ---------------------------------------------------------------------------

class TestHumanAdviceInjection:

    def test_plain_string_advice_injected_into_reasoning_prompt(self, agent, tmp_path):
        inp = make_input(tmp_path, human_advice="Avoid transformers — too slow on CPU.")
        agent.run(inp)
        reasoning_user_prompt = agent.bridge.generate_text.call_args[0][1]
        assert "Avoid transformers" in reasoning_user_prompt

    def test_structured_advice_focus_areas_injected(self, agent, tmp_path):
        adv = ExpertAdvice(
            focus_areas=["reduce depth first"],
            constraints=["VRAM < 8 GB"],
            known_failures=["large batch_size"],
            suggested_directions=["try dilated convolutions"],
            rationale="prior plateau at depth=4",
        )
        inp = make_input(tmp_path, human_advice=adv)
        agent.run(inp)
        reasoning_user_prompt = agent.bridge.generate_text.call_args[0][1]
        assert "reduce depth first" in reasoning_user_prompt

    def test_structured_advice_rationale_injected(self, agent, tmp_path):
        adv = ExpertAdvice(
            focus_areas=[],
            constraints=[],
            known_failures=[],
            suggested_directions=[],
            rationale="plateau at depth=4 confirmed across 3 runs",
        )
        inp = make_input(tmp_path, human_advice=adv)
        agent.run(inp)
        reasoning_user_prompt = agent.bridge.generate_text.call_args[0][1]
        assert "plateau at depth=4 confirmed across 3 runs" in reasoning_user_prompt

    def test_no_advice_does_not_inject_human_section(self, agent, tmp_path):
        inp = make_input(tmp_path, human_advice=None)
        agent.run(inp)
        reasoning_user_prompt = agent.bridge.generate_text.call_args[0][1]
        assert "Human Expert Advice" not in reasoning_user_prompt

    def test_plain_string_advice_injects_human_section_header(self, agent, tmp_path):
        inp = make_input(tmp_path, human_advice="Use attention.")
        agent.run(inp)
        reasoning_user_prompt = agent.bridge.generate_text.call_args[0][1]
        assert "Human Expert Advice" in reasoning_user_prompt


# ---------------------------------------------------------------------------
# Duplicate model name guard
# ---------------------------------------------------------------------------

class TestDuplicateNameGuard:

    def test_duplicate_model_name_raises(self, agent, tmp_path):
        inp = make_input(tmp_path, existing_model_types=["attn_unet", "punet", "fcnet"])
        with pytest.raises(ValueError, match="already exists in existing_model_types"):
            agent.run(inp)

    def test_empty_existing_model_types_does_not_raise(self, agent, tmp_path):
        inp = make_input(tmp_path, existing_model_types=[])
        output = agent.run(inp)
        assert output.model_name == "attn_unet"

    def test_different_existing_types_do_not_raise(self, agent, tmp_path):
        inp = make_input(tmp_path, existing_model_types=["punet", "fcnet", "wavenet"])
        output = agent.run(inp)
        assert output.model_name == "attn_unet"


# ---------------------------------------------------------------------------
# Reasoning prompt enrichment tests
# ---------------------------------------------------------------------------

class TestBuildReasoningPromptEnriched:
    """Tests that _build_reasoning_prompt includes new interpretation fields."""

    def _make_enriched_input(self, **extra_interp):
        interp = {
            "model_types": ["punet"],
            "total_experiments": 10,
            "best_denoising_score": 1.8,
            "worst_denoising_score": 0.5,
            "per_model_best": {"punet": 1.8},
            "per_model_worst": {"punet": 0.5},
            "key_findings": ["test finding"],
            "bottlenecks": ["test bottleneck"],
            "take_home_message": "Need better architecture.",
            "model_descriptions": {"punet": "PUNet description"},
        }
        interp.update(extra_interp)
        return ProposalInput(
            interpretation=interp,
            existing_model_types=["punet"],
            storage={"backend": "local", "local": {"workspace": "/tmp/test", "run_name": "r1"}},
        )

    def test_includes_file_vectors(self):
        fv = [0.001, 0.01] + [5.0] * 18
        inp = self._make_enriched_input(
            per_model_score_tables={"punet": _make_score_table_dict(fv)},
        )
        prompt = _build_reasoning_prompt(inp)
        assert "File Vector" in prompt
        assert "weak files" in prompt.lower()

    def test_includes_weak_frequency_files(self):
        inp = self._make_enriched_input(
            weak_frequency_files={"punet": [0, 1, 2, 3]},
        )
        prompt = _build_reasoning_prompt(inp)
        assert "Weak Frequency" in prompt
        assert "[0, 1, 2, 3]" in prompt

    def test_includes_model_params(self):
        inp = self._make_enriched_input(
            per_model_params={"punet": 55000},
        )
        prompt = _build_reasoning_prompt(inp)
        assert "55,000" in prompt
        assert "Model Parameters" in prompt

    def test_includes_training_segments(self):
        inp = self._make_enriched_input(
            per_model_training_segments={"punet": 200},
        )
        prompt = _build_reasoning_prompt(inp)
        assert "200" in prompt
        assert "Training Data Volume" in prompt

    def test_includes_frequency_comparison(self):
        inp = self._make_enriched_input(
            frequency_comparison="All models struggle with files 0-3.",
        )
        prompt = _build_reasoning_prompt(inp)
        assert "Frequency Comparison" in prompt
        assert "files 0-3" in prompt

    def test_includes_efficiency_comparison(self):
        inp = self._make_enriched_input(
            efficiency_comparison="PUNet has best score-per-parameter.",
        )
        prompt = _build_reasoning_prompt(inp)
        assert "Efficiency Comparison" in prompt

    def test_works_without_enriched_fields(self):
        """Old-style interpretation (no enriched fields) still produces valid prompt."""
        inp = self._make_enriched_input()
        prompt = _build_reasoning_prompt(inp)
        assert "punet" in prompt
        assert "test bottleneck" in prompt
        assert "File Vector" not in prompt

    def test_includes_expert_advice_string(self):
        inp = self._make_enriched_input()
        inp.expert_advice = "Prioritize architectures with skip connections"
        prompt = _build_reasoning_prompt(inp)
        assert "Expert Guidance" in prompt
        assert "skip connections" in prompt

    def test_excludes_expert_when_empty(self):
        inp = self._make_enriched_input()
        inp.expert_advice = ""
        prompt = _build_reasoning_prompt(inp)
        assert "Expert Guidance" not in prompt

    def test_includes_structured_expert_advice(self):
        from agent.schemas.hyperparam_tuning import ExpertAdvice
        inp = self._make_enriched_input()
        inp.expert_advice = ExpertAdvice(
            focus_areas=["low-frequency denoising"],
            constraints=["VRAM < 8 GB"],
            known_failures=[],
            suggested_directions=["try dilated convolutions"],
            rationale="Files 0-3 consistently weak.",
        )
        prompt = _build_reasoning_prompt(inp)
        assert "Expert Guidance" in prompt
        assert "low-frequency denoising" in prompt
        assert "VRAM < 8 GB" in prompt
        assert "dilated convolutions" in prompt

    def test_expert_advice_before_human_advice(self):
        inp = self._make_enriched_input()
        inp.expert_advice = "Expert says X"
        inp.human_advice = "Human says Y"
        prompt = _build_reasoning_prompt(inp)
        expert_pos = prompt.index("Expert Guidance")
        human_pos = prompt.index("Human Expert Advice")
        assert expert_pos < human_pos


# ---------------------------------------------------------------------------
# F.4 — _render_vocabulary (feedback loop)
# ---------------------------------------------------------------------------

class TestRenderVocabulary:
    """Verify that _render_vocabulary renders all four vocab kinds correctly.

    Bug 2 (fixed): discoveries were silently dropped — this class would have
    caught it immediately via test_discovery_entries_rendered.
    """

    def test_empty_returns_empty_string(self):
        assert MLModelProposalAgent._render_vocabulary([]) == ""

    def test_feature_entries_rendered(self):
        vocab = [VocabEntry(name="dilated_causal_conv", kind="feature",
                            description="Causal dilated convolution.", tier="canonical")]
        rendered = MLModelProposalAgent._render_vocabulary(vocab)
        assert "Features" in rendered
        assert "dilated_causal_conv" in rendered

    def test_capability_entries_rendered(self):
        vocab = [VocabEntry(name="large_receptive_field", kind="capability",
                            description="Receptive field > 10k samples.", tier="canonical")]
        rendered = MLModelProposalAgent._render_vocabulary(vocab)
        assert "Capabilities" in rendered
        assert "large_receptive_field" in rendered

    def test_discovery_entries_rendered(self):
        vocab = [VocabEntry(
            name="prediction_attn_wavenet_refuted",
            kind="discovery",
            description="REFUTED: attn_wavenet achieved denoising_score=-1.509 (predicted 6.5).",
            tier="candidate",
        )]
        rendered = MLModelProposalAgent._render_vocabulary(vocab)
        assert "Discoveries" in rendered
        assert "REFUTED" in rendered
        assert "prediction_attn_wavenet_refuted" in rendered

    def test_candidate_entries_rendered(self):
        vocab = [VocabEntry(name="ssm_layer", kind="candidate",
                            description="State-space model layer.", tier="candidate")]
        rendered = MLModelProposalAgent._render_vocabulary(vocab)
        assert "Candidates" in rendered
        assert "ssm_layer" in rendered

    def test_all_four_kinds_rendered(self):
        vocab = [
            VocabEntry(name="f1", kind="feature",     description="feat.",    tier="canonical"),
            VocabEntry(name="c1", kind="capability",  description="cap.",     tier="canonical"),
            VocabEntry(name="d1", kind="discovery",   description="CONFIRMED: something worked.", tier="candidate"),
            VocabEntry(name="n1", kind="candidate",   description="proposed.", tier="candidate"),
        ]
        rendered = MLModelProposalAgent._render_vocabulary(vocab)
        assert "Features" in rendered
        assert "Capabilities" in rendered
        assert "Discoveries" in rendered
        assert "Candidates" in rendered

    def test_no_discoveries_no_discoveries_section(self):
        vocab = [VocabEntry(name="f1", kind="feature", description="feat.", tier="canonical")]
        rendered = MLModelProposalAgent._render_vocabulary(vocab)
        assert "Discoveries" not in rendered

    def test_dict_entries_also_work(self):
        """_render_vocabulary must handle plain dicts as well as VocabEntry objects."""
        vocab = [{"name": "d1", "kind": "discovery",
                  "description": "REFUTED: something failed.", "tier": "candidate"}]
        rendered = MLModelProposalAgent._render_vocabulary(vocab)
        assert "Discoveries" in rendered
        assert "REFUTED" in rendered
