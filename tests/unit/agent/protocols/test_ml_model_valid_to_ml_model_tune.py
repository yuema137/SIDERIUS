"""
Unit tests for agent/schemas/protocols/ml_model_valid_to_ml_model_tune.py

Tests cover:
  local_validated_model
    - Returns a valid HyperparamTuningInput
    - model_type passed through from ValidatorOutput
    - expert_advice passed through from ProposalOutput
    - storage passed through
    - max_rounds uses caller-supplied value
    - file_index uses caller-supplied value
    - llm_provider uses caller-supplied value
    - llm_model_id uses caller-supplied value
    - Defaults: max_rounds=50, file_index=6, llm_provider="gemini"

  database_validated_model
    - Raises NotImplementedError
"""
import pytest

from agent.schemas.validator import ValidatorOutput
from agent.schemas.proposal import ProposalOutput
from agent.schemas.hyperparam_tuning import HyperparamTuningInput, ExpertAdvice
from agent.schemas.storage import StorageConfig, LocalStorageConfig
from agent.schemas.protocols.ml_model_valid_to_ml_model_tune import (
    local_validated_model,
    database_validated_model,
)


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

    def test_model_type_passed_through(self, validator_output, proposal_output, storage):
        result = local_validated_model(validator_output, proposal_output, storage)
        assert result.model_type == "gated_tcn"

    def test_expert_advice_from_proposal(self, validator_output, proposal_output, storage):
        result = local_validated_model(validator_output, proposal_output, storage)
        assert isinstance(result.expert_advice, ExpertAdvice)
        assert "receptive field size" in result.expert_advice.focus_areas
        assert "VRAM < 8 GB" in result.expert_advice.constraints

    def test_storage_passed_through(self, validator_output, proposal_output, storage):
        result = local_validated_model(validator_output, proposal_output, storage)
        assert result.storage.local.workspace == "/tmp/tune_test"
        assert result.storage.local.run_name == "r2"

    def test_default_max_rounds(self, validator_output, proposal_output, storage):
        result = local_validated_model(validator_output, proposal_output, storage)
        assert result.max_rounds == 50

    def test_custom_max_rounds(self, validator_output, proposal_output, storage):
        result = local_validated_model(validator_output, proposal_output, storage, max_rounds=10)
        assert result.max_rounds == 10

    def test_default_file_index(self, validator_output, proposal_output, storage):
        result = local_validated_model(validator_output, proposal_output, storage)
        assert result.file_index == 6

    def test_custom_file_index(self, validator_output, proposal_output, storage):
        result = local_validated_model(validator_output, proposal_output, storage, file_index=3)
        assert result.file_index == 3

    def test_default_llm_provider(self, validator_output, proposal_output, storage):
        result = local_validated_model(validator_output, proposal_output, storage)
        assert result.llm_provider == "gemini"

    def test_custom_llm_provider(self, validator_output, proposal_output, storage):
        result = local_validated_model(validator_output, proposal_output, storage, llm_provider="openai")
        assert result.llm_provider == "openai"

    def test_custom_llm_model_id(self, validator_output, proposal_output, storage):
        result = local_validated_model(
            validator_output, proposal_output, storage, llm_model_id="gpt-4o"
        )
        assert result.llm_model_id == "gpt-4o"

    # --- Trial mode parameters ---

    def test_default_is_trial_false(self, validator_output, proposal_output, storage):
        result = local_validated_model(validator_output, proposal_output, storage)
        assert result.is_trial is False

    def test_trial_mode_passed_through(self, validator_output, proposal_output, storage):
        result = local_validated_model(
            validator_output, proposal_output, storage,
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

    def test_target_files_passed_through(self, validator_output, proposal_output, storage):
        result = local_validated_model(
            validator_output, proposal_output, storage,
            is_trial=True,
            trial_strategy="target",
            target_files=[0, 5, 10],
        )
        assert result.target_files == [0, 5, 10]

    def test_cleanup_denoised_passed_through(self, validator_output, proposal_output, storage):
        result = local_validated_model(
            validator_output, proposal_output, storage,
            cleanup_denoised=True,
        )
        assert result.cleanup_denoised is True


# ---------------------------------------------------------------------------
# Deviation-note propagation — spec and inheritance warnings prepended
# to expert_advice so the tuner's planner sees them.
# ---------------------------------------------------------------------------

class TestDeviationNotePropagation:

    def test_spec_deviation_prepended(self, validator_output, proposal_output, storage):
        """When the validator emits spec_deviation_notes, they must be prepended
        to expert_advice as a plain string (serialized from the structured
        ExpertAdvice)."""
        validator_output.spec_deviation_notes = (
            "NOTE: implementation approximates the mathematical spec — gating fused."
        )
        result = local_validated_model(validator_output, proposal_output, storage)
        assert isinstance(result.expert_advice, str)
        assert result.expert_advice.startswith("NOTE: implementation approximates")
        # original proposal advice must still be present
        assert "receptive field size" in result.expert_advice

    def test_inheritance_deviation_prepended(self, validator_output, proposal_output, storage):
        """inheritance_deviation_notes must reach the tuner's expert_advice."""
        validator_output.inheritance_deviation_notes = (
            "NOTE: claimed components not verified by regex: encoder_decoder."
        )
        result = local_validated_model(validator_output, proposal_output, storage)
        assert isinstance(result.expert_advice, str)
        assert "encoder_decoder" in result.expert_advice
        assert "receptive field size" in result.expert_advice

    def test_both_deviations_prepended_in_order(
        self, validator_output, proposal_output, storage
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
        self, validator_output, proposal_output, storage
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
# See docs/time_estimator_implement.md §2.7.2 / Phase I.
# ---------------------------------------------------------------------------

class TestTimeBudgetFanOut:

    def test_trial_time_budget_minutes_passed_through(
        self, validator_output, proposal_output, storage
    ):
        result = local_validated_model(
            validator_output, proposal_output, storage,
            trial_time_budget_minutes=45.0,
        )
        assert result.trial_time_budget_minutes == 45.0
        # Phase I: setting the trial budget alone must NOT touch the formal one.
        assert result.formal_time_budget_minutes is None

    def test_formal_time_budget_minutes_passed_through(
        self, validator_output, proposal_output, storage
    ):
        result = local_validated_model(
            validator_output, proposal_output, storage,
            formal_time_budget_minutes=240.0,
        )
        assert result.formal_time_budget_minutes == 240.0
        # Phase I: setting the formal budget alone must NOT touch the trial one.
        assert result.trial_time_budget_minutes is None

    def test_data_dir_passed_through(
        self, validator_output, proposal_output, storage
    ):
        result = local_validated_model(
            validator_output, proposal_output, storage,
            data_dir="/mnt/tidmad",
        )
        assert result.data_dir == "/mnt/tidmad"

    def test_both_budgets_independent(
        self, validator_output, proposal_output, storage
    ):
        """Phase I two-budget split: caller sets both — both survive the
        protocol mapping with their own values, no cross-contamination."""
        result = local_validated_model(
            validator_output, proposal_output, storage,
            trial_time_budget_minutes=30.0,
            formal_time_budget_minutes=240.0,
            data_dir="/data/tidmad",
        )
        assert result.trial_time_budget_minutes == 30.0
        assert result.formal_time_budget_minutes == 240.0
        assert result.data_dir == "/data/tidmad"

    def test_defaults_none_when_omitted(
        self, validator_output, proposal_output, storage
    ):
        """When the caller supplies none of the budget kwargs, both modes'
        gates stay disabled (one-time warning per mode). All three fields
        default to None."""
        result = local_validated_model(validator_output, proposal_output, storage)
        assert result.trial_time_budget_minutes is None
        assert result.formal_time_budget_minutes is None
        assert result.data_dir is None


# ---------------------------------------------------------------------------
# time_risk propagation — proposer's baseline gate annotates ProposalOutput
# with a time_risk string, which this protocol must surface to the tuner as a
# round-0 warning in expert_advice. Ordering: spec → inheritance → time_risk
# so the strongest architectural-fidelity signal comes first.
# See docs/time_estimator_implement.md §2.7.4.
# ---------------------------------------------------------------------------

class TestTimeRiskPropagation:

    def test_time_risk_prepended(self, validator_output, proposal_output, storage):
        """When ProposalOutput carries a time_risk string, it must be prepended
        to expert_advice with a recognisable NOTE prefix."""
        proposal_output.time_risk = (
            "baseline exceeds 30-min budget by 18m; consider reducing trial_portion."
        )
        result = local_validated_model(validator_output, proposal_output, storage)
        assert isinstance(result.expert_advice, str)
        assert "time-budget risk on baseline" in result.expert_advice
        assert "reducing trial_portion" in result.expert_advice
        # original proposal advice must still be present
        assert "receptive field size" in result.expert_advice

    def test_no_time_risk_leaves_advice_structured(
        self, validator_output, proposal_output, storage
    ):
        """time_risk=None + no deviation notes → expert_advice stays structured."""
        assert proposal_output.time_risk is None
        result = local_validated_model(validator_output, proposal_output, storage)
        assert isinstance(result.expert_advice, ExpertAdvice)

    def test_time_risk_ordering_after_deviation_notes(
        self, validator_output, proposal_output, storage
    ):
        """When all three signals fire, order must be:
        spec_deviation → inheritance_deviation → time_risk → serialized advice.
        Rationale: spec deviation is the strongest signal about architectural
        fidelity, inheritance is weaker, and time_risk is the latest-stage
        warning before tuning starts."""
        validator_output.spec_deviation_notes = "NOTE: spec deviation detail."
        validator_output.inheritance_deviation_notes = (
            "NOTE: inheritance deviation detail."
        )
        proposal_output.time_risk = "baseline exceeds budget by 10m."
        result = local_validated_model(validator_output, proposal_output, storage)
        ea = result.expert_advice
        assert isinstance(ea, str)
        spec_pos = ea.index("spec deviation detail")
        inherit_pos = ea.index("inheritance deviation detail")
        time_pos = ea.index("time-budget risk on baseline")
        advice_pos = ea.index("receptive field size")
        assert spec_pos < inherit_pos < time_pos < advice_pos

    def test_time_risk_only_without_deviations(
        self, validator_output, proposal_output, storage
    ):
        """time_risk alone (no deviation notes) still prepends correctly."""
        proposal_output.time_risk = "baseline exceeds budget by 5m."
        result = local_validated_model(validator_output, proposal_output, storage)
        ea = result.expert_advice
        assert isinstance(ea, str)
        time_pos = ea.index("time-budget risk on baseline")
        advice_pos = ea.index("receptive field size")
        assert time_pos < advice_pos


# ---------------------------------------------------------------------------
# database_validated_model
# ---------------------------------------------------------------------------

class TestDatabaseValidatedModel:

    def test_raises_not_implemented(self, validator_output, storage):
        with pytest.raises(NotImplementedError):
            database_validated_model(validator_output, storage)
