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

Parametrized to collapse one-attribute-per-test scaffolding noise into
multi-assertion baselines and pytest.param families. No sovereign math
lives in this file; all surfaces are LLM-mock-wiring and prompt-string
assembly contracts.
"""

import json
from unittest.mock import MagicMock, call, patch

import pytest

from agent.schemas.hyperparam_tuning import ExpertAdvice
from agent.schemas.proposal import ProposalInput, ProposalOutput, VocabEntry
from agent.schemas.proposer_evidence import build_proposer_evidence
from agent.schemas.score_table import (
    AggregateScalars,
    PerFileRow,
    ScoreComparisonTable,
)
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from agent.schemas.task_config import ForwardContract
from nodes.ml_model_proposal_agent import MLModelProposalAgent, _build_reasoning_prompt


# PR 01a: the commit-prompt render is FAIL-CLOSED on an empty contract
# (design rule 6.2-6). Production ALWAYS supplies one — the workflow via
# load_task_config(), and now the standalone CLI too — so legacy-path unit
# fixtures must declare it as well. Declared explicitly (not loaded from
# configs/) to keep these unit tests hermetic and cwd-independent.
def _legacy_test_contract() -> ForwardContract:
    return ForwardContract(
        input_shape="[B, T] int64",
        input_description="per-timestep ADC class indices",
        output_shape="[B, 256, T] float32",
        output_description="per-timestep logits over 256 denoising classes",
        num_classes=256,
        task_type="classification",
    )


def _make_score_table_dict(fv):
    """Serialized ScoreComparisonTable fixture matching what the interp dict
    carries in production (output.model_dump() through the protocol)."""
    rows = [
        PerFileRow(
            file_index=i,
            raw_baseline=0.1,
            ground_truth=100.0,
            model=v,
            gain_vs_raw=(v - 0.1) if v is not None else None,
            headroom_vs_gt=(100.0 - v) if v is not None else None,
        )
        for i, v in enumerate(fv)
    ]
    return ScoreComparisonTable(
        rows=rows,
        aggregate=AggregateScalars(
            raw_baseline_scalar=0.1,
            ground_truth_scalar=100.0,
            model_scalar=0.5,
            percent_of_ceiling_log=0.005,
            num_sampled_files=len([v for v in fv if v is not None]) or 1,
        ),
        s_max_global=1.0,
        reference_source="test",
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
            "lr": 1e-4,
            "epochs": 10,
            "batch_size": 1,
            "optimizer_type": "adamw",
            "weight_decay": 1e-5,
            "device": "cuda",
        },
        "loss_config": {"loss_type": "focal", "alpha": 0.5, "gamma": 2.0, "reduction": "mean"},
    },
}

FAKE_INTERPRETATION = {
    "model_types": ["punet", "fcnet"],
    "model_descriptions": {"punet": "PUNet description...", "fcnet": "FCNet description..."},
    "total_experiments": 20,
    "per_model_best": {"punet": 1.8, "fcnet": 0.9},
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


def make_input(
    workspace, run_name="r1", existing_model_types=None, constraints=None, human_advice=None
):
    return ProposalInput(
        interpretation_evidence=build_proposer_evidence(FAKE_INTERPRETATION),
        forward_contract=_legacy_test_contract(),
        existing_model_types=existing_model_types or [],
        constraints=constraints or [],
        human_advice=human_advice,
        storage={"backend": "local", "local": {"workspace": str(workspace), "run_name": run_name}},
    )


# ---------------------------------------------------------------------------
# LLM call structure
# ---------------------------------------------------------------------------


class TestLLMCallStructure:
    def test_text_gen_then_commit_gen_each_called_once(self, agent, tmp_path):
        """Single multi-assertion baseline: both LLM methods fire exactly once
        and in the documented order (text reasoning -> commit JSON). Replaces
        three flat tests (generate_text_called_once, generate_called_once,
        generate_text_called_before_generate)."""
        call_order = []
        agent.bridge.generate_text.side_effect = lambda *a, **kw: (
            call_order.append("text") or FAKE_REASONING
        )
        agent.bridge.generate.side_effect = lambda *a, **kw: (
            call_order.append("json") or FAKE_COMMIT_RESPONSE
        )
        agent.run(make_input(tmp_path))

        agent.bridge.generate_text.assert_called_once()
        agent.bridge.generate.assert_called_once()
        assert call_order == ["text", "json"]

    def test_reasoning_injected_into_commit_prompt(self, agent, tmp_path):
        agent.run(make_input(tmp_path))
        commit_call_args = agent.bridge.generate.call_args
        user_prompt = commit_call_args[0][1]
        assert FAKE_REASONING in user_prompt


# ---------------------------------------------------------------------------
# Output correctness
# ---------------------------------------------------------------------------


class TestOutputCorrectness:
    def test_llm_response_threads_through_all_output_fields(self, agent, tmp_path):
        """Single multi-assertion baseline: every field in FAKE_COMMIT_RESPONSE
        must thread through to the corresponding ProposalOutput attribute,
        expert_advice is coerced to its Pydantic instance, and baseline_config
        keeps its three required keys. Replaces eight flat single-assertion
        tests (output_is_valid_proposal_output, model_name_from_llm,
        model_description_from_llm, mathematical_definition_from_llm,
        motivation_from_llm, expert_advice_is_expert_advice_instance,
        expert_advice_fields_populated, baseline_config_has_required_keys)."""
        output = agent.run(make_input(tmp_path))

        # Schema validity.
        assert isinstance(output, ProposalOutput)

        # Each LLM-supplied scalar threads through.
        assert output.model_name == "attn_unet"
        assert "U-Net" in output.model_description
        assert "Embedding" in output.mathematical_definition
        assert "take-home message" in output.motivation

        # expert_advice dict is coerced to its Pydantic instance and populated.
        assert isinstance(output.expert_advice, ExpertAdvice)
        assert "VRAM < 10 GB" in output.expert_advice.constraints
        assert len(output.expert_advice.focus_areas) > 0
        assert len(output.expert_advice.suggested_directions) > 0

        # baseline_config carries the three required sub-blocks.
        assert "model_config" in output.baseline_config
        assert "train_config" in output.baseline_config
        assert "loss_config" in output.baseline_config


# ---------------------------------------------------------------------------
# File persistence
# ---------------------------------------------------------------------------


class TestFilePersistence:
    def test_output_persists_to_disk_with_correct_content(self, agent, tmp_path):
        """Single multi-assertion baseline: the output file lands at the
        documented path, parses as JSON, carries the LLM-supplied model_name,
        and surfaces expert_advice in serialised form. Replaces three flat
        tests (output_written_to_file, output_file_is_valid_json,
        output_file_contains_expert_advice)."""
        agent.run(make_input(tmp_path, run_name="r1"))
        out_path = tmp_path / "proposal_r1.json"

        assert out_path.exists()
        data = json.loads(out_path.read_text())
        assert data["model_name"] == "attn_unet"
        assert "expert_advice" in data
        assert "constraints" in data["expert_advice"]


# ---------------------------------------------------------------------------
# Human advice injection
# ---------------------------------------------------------------------------


def _structured_focus_areas_advice():
    return ExpertAdvice(
        focus_areas=["reduce depth first"],
        constraints=["VRAM < 8 GB"],
        known_failures=["large batch_size"],
        suggested_directions=["try dilated convolutions"],
        rationale="prior plateau at depth=4",
    )


def _structured_rationale_only_advice():
    return ExpertAdvice(
        focus_areas=[],
        constraints=[],
        known_failures=[],
        suggested_directions=[],
        rationale="plateau at depth=4 confirmed across 3 runs",
    )


class TestHumanAdviceInjection:
    @pytest.mark.parametrize(
        "advice, expected_substrings",
        [
            pytest.param(
                "Avoid transformers — too slow on CPU.",
                ["Avoid transformers", "Human Expert Advice"],
                id="plain_string_advice",
            ),
            pytest.param(
                "Use attention.",
                ["Human Expert Advice"],
                id="plain_string_header",
            ),
            pytest.param(
                _structured_focus_areas_advice(),
                ["reduce depth first"],
                id="structured_focus_areas",
            ),
            pytest.param(
                _structured_rationale_only_advice(),
                ["plateau at depth=4 confirmed across 3 runs"],
                id="structured_rationale",
            ),
        ],
    )
    def test_advice_strings_propagate_into_reasoning_prompt(
        self,
        agent,
        tmp_path,
        advice,
        expected_substrings,
    ):
        """Either plain-string or structured ExpertAdvice -> documented
        substrings must surface in the reasoning prompt. Replaces four flat
        tests (plain_string_advice_injected, structured_advice_focus_areas,
        structured_advice_rationale, plain_string_injects_header)."""
        agent.run(make_input(tmp_path, human_advice=advice))
        prompt = agent.bridge.generate_text.call_args[0][1]
        for substr in expected_substrings:
            assert substr in prompt

    def test_no_advice_omits_human_section(self, agent, tmp_path):
        agent.run(make_input(tmp_path, human_advice=None))
        prompt = agent.bridge.generate_text.call_args[0][1]
        assert "Human Expert Advice" not in prompt


# ---------------------------------------------------------------------------
# Duplicate model name guard
# ---------------------------------------------------------------------------


class TestDuplicateNameGuard:
    @pytest.mark.parametrize(
        "existing, expect_raise",
        [
            pytest.param(["attn_unet", "punet", "fcnet"], True, id="duplicate_name_raises"),
            pytest.param([], False, id="empty_list_accepts"),
            pytest.param(["punet", "fcnet", "wavenet"], False, id="different_names_accept"),
        ],
    )
    def test_name_collision_guard(self, agent, tmp_path, existing, expect_raise):
        """The guard rejects an LLM-proposed name that already appears in
        existing_model_types, and accepts when the list is empty or disjoint.
        Replaces three flat tests (duplicate_model_name_raises,
        empty_existing_model_types_does_not_raise,
        different_existing_types_do_not_raise)."""
        inp = make_input(tmp_path, existing_model_types=existing)
        if expect_raise:
            with pytest.raises(ValueError, match="already exists in existing_model_types"):
                agent.run(inp)
        else:
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
            interpretation_evidence=build_proposer_evidence(interp),
            forward_contract=_legacy_test_contract(),
            existing_model_types=["punet"],
            storage={"backend": "local", "local": {"workspace": "/tmp/test", "run_name": "r1"}},
        )

    def test_includes_rendered_markdown_per_model(self):
        """Phase 5 C: legacy path emits per-model ``rendered_markdown`` under a
        ``### Per-model score tables`` heading instead of a weak-files one-liner.
        """
        fv = [0.001, 0.01] + [5.0] * 18
        inp = self._make_enriched_input(
            per_model_score_tables={"punet": _make_score_table_dict(fv)},
        )
        prompt = _build_reasoning_prompt(inp)
        assert "### Per-model score tables" in prompt
        assert "#### punet" in prompt
        # `_make_score_table_dict` stamps `rendered_markdown="(test)"` — that
        # sentinel must make it through the legacy renderer verbatim.
        assert "(test)" in prompt

    @pytest.mark.parametrize(
        "interp_field, value, expected_substrings",
        [
            pytest.param(
                "per_model_params",
                {"punet": 55000},
                ["55,000", "Model Parameters"],
                id="model_params",
            ),
            pytest.param(
                "per_model_training_segments",
                {"punet": 200},
                ["200", "Training Data Volume"],
                id="training_segments",
            ),
            # ``per_file_comparison`` and ``efficiency_comparison`` were
            # REMOVED here by Step 10 / P3 C3, together with the two reads they
            # exercised. ``InterpretationOutput`` has never declared either
            # field (checked at head, and no commit ever added one), so the
            # legacy renderer's branches for them could not fire in production:
            # the only thing that ever populated them was this parametrization,
            # feeding them straight into a ``dict[str, Any]``.
            #
            # That is how the dead reads survived — they had a test. It passed
            # for the input it invented rather than for anything the producer
            # can emit, so it made two unreachable branches look maintained.
            # The typed evidence cannot carry an undeclared name, which is
            # precisely why the deletion is safe and why the branches are gone.
            # `test_step10_p3_c1_projection.py` keeps the fact executable by
            # asserting both names are still absent from the producer schema.
        ],
    )
    def test_prompt_includes_enriched_interpretation_fields(
        self,
        interp_field,
        value,
        expected_substrings,
    ):
        """Enriched interpretation fields each surface in the reasoning prompt
        under their documented heading. Replaces two flat tests
        (includes_model_params, includes_training_segments); the two
        comparison cases were removed with the dead reads (see above)."""
        inp = self._make_enriched_input(**{interp_field: value})
        prompt = _build_reasoning_prompt(inp)
        for substr in expected_substrings:
            assert substr in prompt

    def test_works_without_enriched_fields(self):
        """Old-style interpretation (no enriched fields) still produces valid prompt."""
        inp = self._make_enriched_input()
        prompt = _build_reasoning_prompt(inp)
        assert "punet" in prompt
        assert "test bottleneck" in prompt
        assert "File Vector" not in prompt

    # NOTE: tests test_expert_advice_propagation and
    # test_expert_advice_before_human_advice were removed in Commit P-d
    # alongside the hard-remove of ProposalInput.expert_advice. The legacy
    # rendering block in _build_reasoning_prompt is gone; there is no
    # behavior left to test. Human_advice behavior is covered by
    # test_advice_strings_propagate_into_reasoning_prompt and
    # test_no_advice_omits_human_section above.


# ---------------------------------------------------------------------------
# F.4 — _render_vocabulary (feedback loop)
# ---------------------------------------------------------------------------


class TestRenderVocabulary:
    """Verify that _render_vocabulary renders all four vocab kinds correctly.

    Bug 2 (fixed): discoveries were silently dropped — this class would have
    caught it immediately via the discovery_kind case in
    test_single_kind_entry_rendered.
    """

    def test_empty_returns_empty_string(self):
        assert MLModelProposalAgent._render_vocabulary([]) == ""

    @pytest.mark.parametrize(
        "kind, name, description, tier, expected_strings",
        [
            pytest.param(
                "feature",
                "dilated_causal_conv",
                "Causal dilated convolution.",
                "canonical",
                ["Features", "dilated_causal_conv"],
                id="feature_kind",
            ),
            pytest.param(
                "capability",
                "large_receptive_field",
                "Receptive field > 10k samples.",
                "canonical",
                ["Capabilities", "large_receptive_field"],
                id="capability_kind",
            ),
            pytest.param(
                "discovery",
                "prediction_attn_wavenet_refuted",
                "REFUTED: attn_wavenet achieved denoising_score=-1.509 (predicted 6.5).",
                "candidate",
                ["Discoveries", "REFUTED", "prediction_attn_wavenet_refuted"],
                id="discovery_kind",
            ),
            pytest.param(
                "candidate",
                "ssm_layer",
                "State-space model layer.",
                "candidate",
                ["Candidates", "ssm_layer"],
                id="candidate_kind",
            ),
        ],
    )
    def test_single_kind_entry_rendered(self, kind, name, description, tier, expected_strings):
        """Each vocab kind renders under its documented section header and
        surfaces the entry name (plus the discovery description sentinel).
        Replaces four flat tests (feature_entries_rendered,
        capability_entries_rendered, discovery_entries_rendered,
        candidate_entries_rendered)."""
        vocab = [VocabEntry(name=name, kind=kind, description=description, tier=tier)]
        rendered = MLModelProposalAgent._render_vocabulary(vocab)
        for s in expected_strings:
            assert s in rendered

    def test_all_four_kinds_rendered(self):
        vocab = [
            VocabEntry(name="f1", kind="feature", description="feat.", tier="canonical"),
            VocabEntry(name="c1", kind="capability", description="cap.", tier="canonical"),
            VocabEntry(
                name="d1",
                kind="discovery",
                description="CONFIRMED: something worked.",
                tier="candidate",
            ),
            VocabEntry(name="n1", kind="candidate", description="proposed.", tier="candidate"),
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
        vocab = [
            {
                "name": "d1",
                "kind": "discovery",
                "description": "REFUTED: something failed.",
                "tier": "candidate",
            }
        ]
        rendered = MLModelProposalAgent._render_vocabulary(vocab)
        assert "Discoveries" in rendered
        assert "REFUTED" in rendered


pytestmark = pytest.mark.usefixtures("synthetic_dataset_profile")
