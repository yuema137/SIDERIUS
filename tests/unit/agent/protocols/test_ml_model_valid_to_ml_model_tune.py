"""
Unit tests for agent/schemas/protocols/ml_model_valid_to_ml_model_tune.py

Parametrized to collapse one-kwarg-per-test pass-through fixtures into single
parametrized functions with explicit case IDs. Every fan-out invariant
(default value, caller override, cross-budget independence, legacy alias
canonicalisation) is preserved as a named case.

Tests cover:
  local_validated_model
    - Returns a valid HyperparamTuningInput.
    - Pass-through of: model_type, expert_advice, storage.
    - Per-kwarg default + override semantics (max_rounds, file_index, LLM
      knobs, is_trial, cleanup_denoised).
    - Trial mode multi-field fan-out (snapshot + target sub-paths).
    - Deviation-note prepending from validator into expert_advice.
    - Two-budget time / VRAM fan-out (independence across modes + categories).
    - Per-round attempt-budget fan-out (Phase L).
    - formal_round_strategy default + legacy alias canonicalisation.
    - degenerate_penalty_score default + float override.
  database_validated_model
    - Raises NotImplementedError.
"""

import pytest

from agent.schemas.hyperparam_tuning import ExpertAdvice, HyperparamTuningInput
from agent.schemas.proposal import ProposalOutput
from agent.schemas.protocols.ml_model_valid_to_ml_model_tune import (
    database_validated_model,
    local_validated_model,
)
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from agent.schemas.validator import ValidatorOutput
from execute_tools.dataset_config import DataScope

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def storage():
    return StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace="/tmp/tune_test", run_name="r2"),
    )


@pytest.fixture
def validator_output():
    return ValidatorOutput(
        passed=True,
        model_type="gated_tcn",
        plugin_registered=True,
        tests_passed=True,
        description_valid=True,
        config_fields_valid=True,
        instantiation_passed=True,
        gradient_check_passed=True,
        llm_review_passed=True,
    )


@pytest.fixture
def proposal_output():
    return ProposalOutput(
        model_name="gated_tcn",
        model_description="A gated temporal convolution network for signal denoising.",
        mathematical_definition="Dilated causal convolutions with gated activations.",
        motivation="Address limited receptive field in current best model.",
        expert_advice=ExpertAdvice(
            focus_areas=["receptive field size", "dilation schedule"],
            constraints=["VRAM < 8 GB"],
            known_failures=["batch_size > 8 causes OOM"],
            suggested_directions=["try dilation factors [1, 2, 4, 8]"],
            rationale="Current best model struggles with long-range dependencies.",
        ),
        baseline_config={
            "model_config": {"n_layers": 4, "hidden_dim": 64},
            "train_config": {"epochs": 10, "batch_size": 4},
            "loss_config": {"loss_type": "focal"},
        },
    )


# ---------------------------------------------------------------------------
# local_validated_model
# ---------------------------------------------------------------------------


class TestLocalValidatedModel:
    def test_returns_hyperparam_tuning_input(self, validator_output, proposal_output, storage):
        result = local_validated_model(validator_output, proposal_output, storage)
        assert isinstance(result, HyperparamTuningInput)

    def test_baseline_attributes_from_inputs(
        self,
        validator_output,
        proposal_output,
        storage,
    ):
        """Sanity baseline: model_type/expert_advice/storage flow from
        ValidatorOutput + ProposalOutput + the kwarg straight into the
        downstream input."""
        result = local_validated_model(validator_output, proposal_output, storage)
        assert result.model_type == "gated_tcn"
        assert isinstance(result.expert_advice, ExpertAdvice)
        assert "receptive field size" in result.expert_advice.focus_areas
        assert "VRAM < 8 GB" in result.expert_advice.constraints
        assert result.storage.local.workspace == "/tmp/tune_test"
        assert result.storage.local.run_name == "r2"

    @pytest.mark.parametrize(
        "attr, expected_default",
        [
            pytest.param("max_rounds", 50, id="max_rounds"),
            pytest.param("file_index", 6, id="file_index"),
            pytest.param("llm_provider", "gemini", id="llm_provider"),
            pytest.param("is_trial", False, id="is_trial"),
        ],
    )
    def test_default_when_kwarg_omitted(
        self,
        validator_output,
        proposal_output,
        storage,
        attr,
        expected_default,
    ):
        """Defensive shield: caller omits the kwarg → protocol surfaces the
        documented default. Pins regressions where a schema default could
        silently drift."""
        result = local_validated_model(validator_output, proposal_output, storage)
        assert getattr(result, attr) == expected_default

    @pytest.mark.parametrize(
        "kwarg, value, attr",
        [
            pytest.param("max_rounds", 10, "max_rounds", id="max_rounds_override"),
            pytest.param("file_index", 3, "file_index", id="file_index_override"),
            pytest.param("llm_provider", "openai", "llm_provider", id="llm_provider_override"),
            pytest.param("llm_model_id", "gpt-4o", "llm_model_id", id="llm_model_id_override"),
            pytest.param(
                "cleanup_denoised", True, "cleanup_denoised", id="cleanup_denoised_override"
            ),
        ],
    )
    def test_custom_kwarg_passes_through(
        self,
        validator_output,
        proposal_output,
        storage,
        kwarg,
        value,
        attr,
    ):
        """Caller supplies the kwarg → it lands verbatim on the downstream input."""
        result = local_validated_model(
            validator_output,
            proposal_output,
            storage,
            **{kwarg: value},
        )
        assert getattr(result, attr) == value

    def test_trial_mode_snapshot_kwargs_fan_out(
        self,
        validator_output,
        proposal_output,
        storage,
    ):
        """All trial-mode knobs land on the downstream input together —
        kept as a single multi-field assertion because the 8 fields are
        semantically one trial-config payload, not 8 unrelated kwargs."""
        result = local_validated_model(
            validator_output,
            proposal_output,
            storage,
            is_trial=True,
            trial_strategy="snapshot",
            trial_portion=0.2,
            train_portion=0.15,
            eval_strategy="anchors",
            eval_portion=0.5,
            train_validation_align=False,
            sampling_seed=42,
            train_base_seed=99,
        )
        assert result.is_trial is True
        assert result.trial_strategy == "snapshot"
        assert result.trial_portion == 0.2
        assert result.train_portion == 0.15
        assert result.eval_strategy == "anchors"
        assert result.eval_portion == 0.5
        assert result.train_validation_align is False
        assert result.sampling_seed == 42
        assert result.train_base_seed == 99

    def test_target_files_in_trial_target_mode(
        self,
        validator_output,
        proposal_output,
        storage,
    ):
        """target_files travels with the trial_strategy='target' sub-path
        (distinct payload from snapshot trial config)."""
        result = local_validated_model(
            validator_output,
            proposal_output,
            storage,
            is_trial=True,
            trial_strategy="target",
            target_files=[0, 5, 10],
        )
        assert result.target_files == [0, 5, 10]


# ---------------------------------------------------------------------------
# Deviation-note propagation — spec and inheritance warnings prepended
# to expert_advice so the tuner's planner sees them.
# ---------------------------------------------------------------------------


class TestDeviationNotePropagation:
    @pytest.mark.parametrize(
        "attr_to_set, note, expected_substr",
        [
            pytest.param(
                "spec_deviation_notes",
                "NOTE: implementation approximates the mathematical spec — gating fused.",
                "NOTE: implementation approximates",
                id="spec_deviation",
            ),
            pytest.param(
                "inheritance_deviation_notes",
                "NOTE: claimed components not verified by regex: encoder_decoder.",
                "encoder_decoder",
                id="inheritance_deviation",
            ),
        ],
    )
    def test_single_deviation_prepended_to_serialized_advice(
        self,
        validator_output,
        proposal_output,
        storage,
        attr_to_set,
        note,
        expected_substr,
    ):
        """When the validator emits one kind of deviation note, it must be
        prepended to expert_advice as a plain string, with the proposal's
        original advice still present below."""
        setattr(validator_output, attr_to_set, note)
        result = local_validated_model(validator_output, proposal_output, storage)
        assert isinstance(result.expert_advice, str)
        assert expected_substr in result.expert_advice
        assert "receptive field size" in result.expert_advice

    def test_both_deviations_prepended_in_order(
        self,
        validator_output,
        proposal_output,
        storage,
    ):
        """When both deviation notes are present, spec first then inheritance,
        then the serialized proposal advice."""
        validator_output.spec_deviation_notes = "NOTE: spec deviation detail."
        validator_output.inheritance_deviation_notes = "NOTE: inheritance deviation detail."
        result = local_validated_model(validator_output, proposal_output, storage)
        ea = result.expert_advice
        assert isinstance(ea, str)
        spec_pos = ea.index("spec deviation detail")
        inherit_pos = ea.index("inheritance deviation detail")
        advice_pos = ea.index("receptive field size")
        assert spec_pos < inherit_pos < advice_pos

    def test_no_deviation_passes_advice_through_structured(
        self,
        validator_output,
        proposal_output,
        storage,
    ):
        """No deviation notes → expert_advice stays as the structured ExpertAdvice."""
        result = local_validated_model(validator_output, proposal_output, storage)
        assert isinstance(result.expert_advice, ExpertAdvice)


# ---------------------------------------------------------------------------
# Time-budget context fan-out (Phase E0 + Phase I two-budget split)
#
# trial_time_budget_minutes / formal_time_budget_minutes / data_dir fan out
# from the workflow/CLI into BOTH ProposalInput (via interp→propose) and
# HyperparamTuningInput (here) so the tuner's per-round evaluate_time_skill
# gate sees the same numbers as the proposer's baseline gate. The per-round
# pick (trial vs formal) happens inside the tuner based on plan.is_trial.
# See docs/resource_estimator_implement.md §2.7.2 / Phase I.
# ---------------------------------------------------------------------------


class TestTimeBudgetFanOut:
    @pytest.mark.parametrize(
        "kwargs, set_field, set_value, other_fields_must_stay_none",
        [
            pytest.param(
                {"trial_time_budget_minutes": 45.0},
                "trial_time_budget_minutes",
                45.0,
                ["formal_time_budget_minutes", "data_dir"],
                id="trial_only_set",
            ),
            pytest.param(
                {"formal_time_budget_minutes": 240.0},
                "formal_time_budget_minutes",
                240.0,
                ["trial_time_budget_minutes", "data_dir"],
                id="formal_only_set",
            ),
            pytest.param(
                {"data_dir": "/mnt/tidmad"},
                "data_dir",
                "/mnt/tidmad",
                ["trial_time_budget_minutes", "formal_time_budget_minutes"],
                id="data_dir_only_set",
            ),
        ],
    )
    def test_individual_budget_passes_through_without_polluting_siblings(
        self,
        validator_output,
        proposal_output,
        storage,
        kwargs,
        set_field,
        set_value,
        other_fields_must_stay_none,
    ):
        """Phase I invariant: setting one of {trial, formal, data_dir} alone
        leaves the others at their default None — no cross-contamination."""
        result = local_validated_model(
            validator_output,
            proposal_output,
            storage,
            **kwargs,
        )
        assert getattr(result, set_field) == set_value
        for f in other_fields_must_stay_none:
            assert getattr(result, f) is None

    def test_all_three_budgets_independent(
        self,
        validator_output,
        proposal_output,
        storage,
    ):
        """Two-budget split: caller sets every kwarg — all three survive."""
        result = local_validated_model(
            validator_output,
            proposal_output,
            storage,
            trial_time_budget_minutes=30.0,
            formal_time_budget_minutes=240.0,
            data_dir="/data/tidmad",
        )
        assert result.trial_time_budget_minutes == 30.0
        assert result.formal_time_budget_minutes == 240.0
        assert result.data_dir == "/data/tidmad"

    def test_defaults_none_when_omitted(
        self,
        validator_output,
        proposal_output,
        storage,
    ):
        """When the caller supplies none of the budget kwargs, both modes'
        gates stay disabled (one-time warning per mode). All three fields
        default to None."""
        result = local_validated_model(validator_output, proposal_output, storage)
        assert result.trial_time_budget_minutes is None
        assert result.formal_time_budget_minutes is None
        assert result.data_dir is None


# ---------------------------------------------------------------------------
# VRAM-budget context fan-out (Phase K two-budget split)
#
# trial_vram_budget_gb / formal_vram_budget_gb fan out from the workflow/CLI
# into HyperparamTuningInput (no proposer-side gate in Phase K — unlike the
# time budgets, the interp→propose protocol is NOT touched). The per-round
# pick (trial vs formal) happens inside the tuner based on plan.is_trial.
# See docs/resource_estimator_implement.md §10.9 / §10.17.
# ---------------------------------------------------------------------------


class TestVramBudgetFanOut:
    @pytest.mark.parametrize(
        "kwargs, set_field, set_value, sibling_to_check",
        [
            pytest.param(
                {"trial_vram_budget_gb": 6.0},
                "trial_vram_budget_gb",
                6.0,
                "formal_vram_budget_gb",
                id="trial_only_set",
            ),
            pytest.param(
                {"formal_vram_budget_gb": 24.0},
                "formal_vram_budget_gb",
                24.0,
                "trial_vram_budget_gb",
                id="formal_only_set",
            ),
        ],
    )
    def test_individual_vram_budget_passes_through_without_polluting_sibling(
        self,
        validator_output,
        proposal_output,
        storage,
        kwargs,
        set_field,
        set_value,
        sibling_to_check,
    ):
        """Phase K invariant: setting one of {trial, formal} VRAM budget
        alone leaves the other at None."""
        result = local_validated_model(
            validator_output,
            proposal_output,
            storage,
            **kwargs,
        )
        assert getattr(result, set_field) == set_value
        assert getattr(result, sibling_to_check) is None

    def test_both_vram_budgets_set_does_not_touch_time_budgets(
        self,
        validator_output,
        proposal_output,
        storage,
    ):
        """Cross-category independence: VRAM kwargs do not bleed into the
        time-budget fields. Both vram fields survive; both time fields
        stay at default None."""
        result = local_validated_model(
            validator_output,
            proposal_output,
            storage,
            trial_vram_budget_gb=6.0,
            formal_vram_budget_gb=24.0,
        )
        assert result.trial_vram_budget_gb == 6.0
        assert result.formal_vram_budget_gb == 24.0
        assert result.trial_time_budget_minutes is None
        assert result.formal_time_budget_minutes is None

    def test_vram_defaults_none_when_omitted(
        self,
        validator_output,
        proposal_output,
        storage,
    ):
        """When the caller supplies neither VRAM kwarg, both fields default
        to None so the tuner's per-round gate falls back to free×0.8."""
        result = local_validated_model(validator_output, proposal_output, storage)
        assert result.trial_vram_budget_gb is None
        assert result.formal_vram_budget_gb is None


# ---------------------------------------------------------------------------
# Per-round attempt-budget fan-out (Phase L, §11.5)
#
# attempts_per_round / attempts_per_formal_round / max_fail_rounds are
# tuner-only knobs. The protocol must surface caller overrides to
# HyperparamTuningInput and otherwise leave the schema defaults (3/5/3).
# ---------------------------------------------------------------------------


class TestAttemptBudgetFanOut:
    @pytest.mark.parametrize(
        "kwargs, set_field, set_value, sibling_defaults",
        [
            pytest.param(
                {"attempts_per_round": 7},
                "attempts_per_round",
                7,
                {"attempts_per_formal_round": 5, "max_fail_rounds": 3},
                id="attempts_per_round",
            ),
            pytest.param(
                {"attempts_per_formal_round": 8},
                "attempts_per_formal_round",
                8,
                {"attempts_per_round": 3, "max_fail_rounds": 3},
                id="attempts_per_formal_round",
            ),
            pytest.param(
                {"max_fail_rounds": 5},
                "max_fail_rounds",
                5,
                {"attempts_per_round": 3, "attempts_per_formal_round": 5},
                id="max_fail_rounds",
            ),
        ],
    )
    def test_individual_attempt_kwarg_passes_through(
        self,
        validator_output,
        proposal_output,
        storage,
        kwargs,
        set_field,
        set_value,
        sibling_defaults,
    ):
        """Each Phase L knob travels independently — siblings stay at the
        documented schema defaults (3 / 5 / 3)."""
        result = local_validated_model(
            validator_output,
            proposal_output,
            storage,
            **kwargs,
        )
        assert getattr(result, set_field) == set_value
        for sib, sib_default in sibling_defaults.items():
            assert getattr(result, sib) == sib_default

    def test_all_three_independent(
        self,
        validator_output,
        proposal_output,
        storage,
    ):
        """All three knobs survive together with independent values."""
        result = local_validated_model(
            validator_output,
            proposal_output,
            storage,
            attempts_per_round=2,
            attempts_per_formal_round=4,
            max_fail_rounds=1,
        )
        assert result.attempts_per_round == 2
        assert result.attempts_per_formal_round == 4
        assert result.max_fail_rounds == 1

    def test_defaults_match_schema_when_omitted(
        self,
        validator_output,
        proposal_output,
        storage,
    ):
        """Caller passes nothing -> protocol surfaces the documented
        Phase L defaults (3/5/3, see §11.5)."""
        result = local_validated_model(validator_output, proposal_output, storage)
        assert result.attempts_per_round == 3
        assert result.attempts_per_formal_round == 5
        assert result.max_fail_rounds == 3


# ---------------------------------------------------------------------------
# HealthGate config fan-out
# ---------------------------------------------------------------------------


class TestHealthChecksConfigFanOut:
    def test_default_is_none(self, validator_output, proposal_output, storage):
        result = local_validated_model(validator_output, proposal_output, storage)
        assert result.health_checks_config is None

    def test_explicit_path_reaches_tuner_input(self, validator_output, proposal_output, storage):
        path = "configs/health_checks_baseline_observe_mode.yaml"
        result = local_validated_model(
            validator_output,
            proposal_output,
            storage,
            health_checks_config=path,
        )
        assert result.health_checks_config == path


# ---------------------------------------------------------------------------
# formal_round_strategy fan-out
#
# Orchestration policy for the forced formal round. Phase 1 of
# refactor_formal_round_strategy.md flipped the schema default to the
# canonical name ``full_clone`` and added legacy aliasing. The protocol
# must (a) leave the schema default in effect when the caller omits the
# field, (b) surface canonical caller overrides verbatim, and (c) let
# legacy literals reach the schema layer where the validator
# canonicalises them.
# ---------------------------------------------------------------------------


class TestFormalRoundStrategyFanOut:
    @pytest.mark.parametrize(
        "kwargs, expected_canonical",
        [
            pytest.param({}, "full_clone", id="default_when_omitted"),
            pytest.param(
                {"formal_round_strategy": "independent"},
                "independent",
                id="canonical_independent_passthrough",
            ),
            pytest.param(
                {"formal_round_strategy": "inherit_best_trial"},
                "full_clone",
                id="legacy_inherit_best_trial_canonicalised",
            ),
            pytest.param(
                {"formal_round_strategy": "llm_propose"},
                "independent",
                id="legacy_llm_propose_canonicalised",
            ),
        ],
    )
    def test_value_resolves_to_canonical(
        self,
        validator_output,
        proposal_output,
        storage,
        kwargs,
        expected_canonical,
    ):
        """Default and every legacy alias collapse to the canonical
        Phase 1 vocabulary on the way through the schema validator."""
        result = local_validated_model(
            validator_output,
            proposal_output,
            storage,
            **kwargs,
        )
        assert result.formal_round_strategy == expected_canonical


# ---------------------------------------------------------------------------
# degenerate_penalty_score fan-out
#
# Operator policy for the agent's reaction when score_vector flags a
# degenerate formal-round output. None (default) → null score; float →
# use as penalty. The protocol must surface caller overrides to
# HyperparamTuningInput and otherwise leave the schema default (None).
# ---------------------------------------------------------------------------


class TestDegeneratePenaltyScoreFanOut:
    @pytest.mark.parametrize(
        "kwargs, expected",
        [
            pytest.param({}, None, id="default_none_when_omitted"),
            pytest.param({"degenerate_penalty_score": -2.5}, -2.5, id="float_passthrough"),
        ],
    )
    def test_penalty_resolves(
        self,
        validator_output,
        proposal_output,
        storage,
        kwargs,
        expected,
    ):
        result = local_validated_model(
            validator_output,
            proposal_output,
            storage,
            **kwargs,
        )
        assert result.degenerate_penalty_score == expected


# ---------------------------------------------------------------------------
# database_validated_model
# ---------------------------------------------------------------------------


class TestDataScopeThreading:
    """DS6b — data_scope / health_gate_enabled / health_gate_files reach
    HyperparamTuningInput; None scope normalizes to the explicit full
    scope in the protocol, not in the schema."""

    def test_defaults_full_scope_gates_enabled(self, validator_output, proposal_output, storage):
        result = local_validated_model(validator_output, proposal_output, storage)
        assert result.data_scope == DataScope.default()
        assert result.health_gate_enabled is True
        assert result.health_gate_files is None

    def test_partial_scope_and_files_thread_through(
        self, validator_output, proposal_output, storage
    ):
        result = local_validated_model(
            validator_output,
            proposal_output,
            storage,
            data_scope=DataScope(file_indices=[4, 5, 6, 7, 8, 9]),
            health_gate_files=[4, 7, 9],
        )
        assert result.data_scope.file_indices == [4, 5, 6, 7, 8, 9]
        assert result.health_gate_enabled is True
        assert result.health_gate_files == [4, 7, 9]

    def test_disabled_gates_thread_through(self, validator_output, proposal_output, storage):
        result = local_validated_model(
            validator_output,
            proposal_output,
            storage,
            health_gate_enabled=False,
        )
        assert result.health_gate_enabled is False
        assert result.health_gate_files is None


class TestDatabaseValidatedModel:
    def test_raises_not_implemented(self, validator_output, storage):
        with pytest.raises(NotImplementedError):
            database_validated_model(validator_output, storage)
