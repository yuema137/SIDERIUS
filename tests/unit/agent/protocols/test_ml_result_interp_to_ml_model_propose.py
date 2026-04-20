"""
Unit tests for agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py

Tests cover:
  local_full_context
    - Returns a valid ProposalInput
    - interpretation is a fully serialised InterpretationOutput dict
    - existing_model_types matches output.model_types
    - all InterpretationOutput fields are present in the interpretation dict
    - storage is passed through correctly
    - works with multiple model types

  database_full_context
    - Raises NotImplementedError (placeholder, not yet implemented)
"""
import pytest

from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.proposal import ProposalInput
from agent.schemas.storage import StorageConfig, LocalStorageConfig
from agent.schemas.protocols.ml_result_interp_to_ml_model_propose import (
    local_full_context,
    database_full_context,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def storage():
    return StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace="/tmp/proto_test", run_name="r1"),
    )


def make_interpretation_output(model_types):
    descriptions = {mt: f"{mt} description text" for mt in model_types}
    per_best  = {mt: 1.5 for mt in model_types}
    per_worst = {mt: 0.8 for mt in model_types}
    return InterpretationOutput(
        model_types=model_types,
        model_descriptions=descriptions,
        total_experiments=10,
        per_model_best=per_best,
        per_model_worst=per_worst,
        best_denoising_score=1.5,
        worst_denoising_score=0.8,
        best_config={"model_config": {"depth": 3}},
        key_findings=["focal loss outperforms ce"],
        bottlenecks=["architecture capacity ceiling"],
        take_home_message="A new architecture is needed to break the plateau.",
    )


# ---------------------------------------------------------------------------
# local_full_context
# ---------------------------------------------------------------------------

class TestLocalFullContext:

    def test_returns_proposal_input(self, storage):
        output = make_interpretation_output(["punet"])
        result = local_full_context(output, storage)
        assert isinstance(result, ProposalInput)

    def test_existing_model_types_from_output(self, storage):
        output = make_interpretation_output(["punet", "fcnet"])
        result = local_full_context(output, storage)
        assert set(result.existing_model_types) == {"punet", "fcnet"}

    def test_interpretation_is_dict(self, storage):
        output = make_interpretation_output(["punet"])
        result = local_full_context(output, storage)
        assert isinstance(result.interpretation, dict)

    def test_interpretation_contains_model_types(self, storage):
        output = make_interpretation_output(["punet", "fcnet"])
        result = local_full_context(output, storage)
        assert result.interpretation["model_types"] == ["punet", "fcnet"]

    def test_interpretation_contains_take_home_message(self, storage):
        output = make_interpretation_output(["punet"])
        result = local_full_context(output, storage)
        assert result.interpretation["take_home_message"] == (
            "A new architecture is needed to break the plateau."
        )

    def test_interpretation_contains_model_descriptions(self, storage):
        output = make_interpretation_output(["punet"])
        result = local_full_context(output, storage)
        assert "model_descriptions" in result.interpretation
        assert "punet" in result.interpretation["model_descriptions"]

    def test_interpretation_contains_scores(self, storage):
        output = make_interpretation_output(["punet"])
        result = local_full_context(output, storage)
        assert result.interpretation["best_denoising_score"] == 1.5
        assert result.interpretation["worst_denoising_score"] == 0.8

    def test_interpretation_contains_findings_and_bottlenecks(self, storage):
        output = make_interpretation_output(["punet"])
        result = local_full_context(output, storage)
        assert result.interpretation["key_findings"] == ["focal loss outperforms ce"]
        assert result.interpretation["bottlenecks"] == ["architecture capacity ceiling"]

    def test_storage_passed_through(self, storage):
        output = make_interpretation_output(["punet"])
        result = local_full_context(output, storage)
        assert result.storage.backend == "local"
        assert result.storage.local.workspace == "/tmp/proto_test"
        assert result.storage.local.run_name == "r1"

    def test_multiple_model_types(self, storage):
        output = make_interpretation_output(["punet", "fcnet", "wavenet"])
        result = local_full_context(output, storage)
        assert len(result.existing_model_types) == 3
        assert set(result.existing_model_types) == {"punet", "fcnet", "wavenet"}


# ---------------------------------------------------------------------------
# Time-budget + trial-mode context fields (Phase E0)
#
# The run-level data + time-budget fields originate at the workflow/CLI level
# and fan out into BOTH ProposalInput (here) and HyperparamTuningInput (via
# the validator→tuner protocol) so the proposer's baseline gate and the
# tuner's per-round gate construct the same SampleSet and see the same
# wall-time budget. See docs/resource_estimator_implement.md §2.7.2/§2.7.5.
#
# The training-side trial-mode set (is_trial / trial_strategy / trial_portion
# / target_files / train_portion / sampling_seed) mirrors the tuner exactly;
# legacy single-file mode (file_index, is_trial=False) is intentionally not
# surfaced — modern usage uses is_trial=True with trial_strategy='target'
# + target_files=[N] when a single file is wanted.
# ---------------------------------------------------------------------------

class TestTimeBudgetContextFields:

    # --- individual kwargs ---------------------------------------------------

    def test_is_trial_passed_through(self, storage):
        output = make_interpretation_output(["punet"])
        result = local_full_context(output, storage, is_trial=True)
        assert result.is_trial is True

    def test_trial_strategy_passed_through(self, storage):
        output = make_interpretation_output(["punet"])
        result = local_full_context(output, storage, trial_strategy="target")
        assert result.trial_strategy == "target"

    def test_trial_portion_passed_through(self, storage):
        output = make_interpretation_output(["punet"])
        result = local_full_context(output, storage, trial_portion=0.25)
        assert result.trial_portion == 0.25

    def test_target_files_passed_through(self, storage):
        output = make_interpretation_output(["punet"])
        result = local_full_context(output, storage, target_files=[3, 7, 11])
        assert result.target_files == [3, 7, 11]

    def test_train_portion_passed_through(self, storage):
        output = make_interpretation_output(["punet"])
        result = local_full_context(output, storage, train_portion=0.5)
        assert result.train_portion == 0.5

    def test_sampling_seed_passed_through(self, storage):
        output = make_interpretation_output(["punet"])
        result = local_full_context(output, storage, sampling_seed=1234)
        assert result.sampling_seed == 1234

    def test_trial_time_budget_minutes_passed_through(self, storage):
        output = make_interpretation_output(["punet"])
        result = local_full_context(output, storage, trial_time_budget_minutes=45.0)
        assert result.trial_time_budget_minutes == 45.0
        # Phase I: setting the trial budget alone must NOT touch the formal one.
        assert result.formal_time_budget_minutes is None

    def test_formal_time_budget_minutes_passed_through(self, storage):
        output = make_interpretation_output(["punet"])
        result = local_full_context(output, storage, formal_time_budget_minutes=240.0)
        assert result.formal_time_budget_minutes == 240.0
        # Phase I: setting the formal budget alone must NOT touch the trial one.
        assert result.trial_time_budget_minutes is None

    def test_both_budgets_independent(self, storage):
        """Phase I two-budget split: caller sets both — both survive the
        protocol mapping with their own values, no cross-contamination."""
        output = make_interpretation_output(["punet"])
        result = local_full_context(
            output, storage,
            trial_time_budget_minutes=30.0,
            formal_time_budget_minutes=240.0,
        )
        assert result.trial_time_budget_minutes == 30.0
        assert result.formal_time_budget_minutes == 240.0

    def test_data_dir_passed_through(self, storage):
        output = make_interpretation_output(["punet"])
        result = local_full_context(output, storage, data_dir="/data/tidmad")
        assert result.data_dir == "/data/tidmad"

    # --- combined fan-out scenarios -----------------------------------------

    def test_full_trial_target_fan_out(self, storage):
        """Realistic single-file-via-trial workflow plumbing: caller supplies
        the full trial-mode set + both budgets + data_dir together. Mirrors
        what the validator→tuner edge will receive for the tuner's per-round
        gate (Phase I two-budget split)."""
        output = make_interpretation_output(["punet"])
        result = local_full_context(
            output, storage,
            is_trial=True,
            trial_strategy="target",
            trial_portion=0.5,
            target_files=[6],
            train_portion=0.5,
            sampling_seed=42,
            trial_time_budget_minutes=30.0,
            formal_time_budget_minutes=240.0,
            data_dir="/mnt/tidmad",
        )
        assert result.is_trial is True
        assert result.trial_strategy == "target"
        assert result.trial_portion == 0.5
        assert result.target_files == [6]
        assert result.train_portion == 0.5
        assert result.sampling_seed == 42
        assert result.trial_time_budget_minutes == 30.0
        assert result.formal_time_budget_minutes == 240.0
        assert result.data_dir == "/mnt/tidmad"

    def test_defaults_when_caller_omits(self, storage):
        """When the caller passes none of the new kwargs, ProposalInput's
        schema defaults must take effect (mirroring HyperparamTuningInput:
        is_trial=False, trial_strategy='snapshot', trial_portion=0.1,
        target_files=[], train_portion=0.1, sampling_seed=None,
        trial_time_budget_minutes=None, formal_time_budget_minutes=None,
        data_dir=None)."""
        output = make_interpretation_output(["punet"])
        result = local_full_context(output, storage)
        assert result.is_trial is False
        assert result.trial_strategy == "snapshot"
        assert result.trial_portion == 0.1
        assert result.target_files == []
        assert result.train_portion == 0.1
        assert result.sampling_seed is None
        assert result.trial_time_budget_minutes is None
        assert result.formal_time_budget_minutes is None
        assert result.data_dir is None

    def test_partial_kwargs_only_overrides_supplied_fields(self, storage):
        """Caller supplies trial_time_budget_minutes only — every other
        run-level field (including formal_time_budget_minutes) keeps its
        schema default so partial workflow plumbing doesn't accidentally
        reset a field the caller didn't touch."""
        output = make_interpretation_output(["punet"])
        result = local_full_context(output, storage, trial_time_budget_minutes=60.0)
        assert result.trial_time_budget_minutes == 60.0
        assert result.formal_time_budget_minutes is None
        assert result.is_trial is False
        assert result.trial_strategy == "snapshot"
        assert result.trial_portion == 0.1
        assert result.target_files == []
        assert result.train_portion == 0.1
        assert result.sampling_seed is None
        assert result.data_dir is None


# ---------------------------------------------------------------------------
# Phase N (§14.N.2) — recent_tune_outputs aggregation pass-through
# Replaces K.7.4's singular prior_tune_output test class.
# ---------------------------------------------------------------------------

class TestLocalFullContextRecentGateExhaustionsAggregation:
    """The protocol must iterate ``recent_tune_outputs``, extract each
    non-None ``gate_exhaustion``, and surface the resulting list (oldest
    first) into ``ProposalInput.recent_gate_exhaustions``. Empty sequence
    or all-None entries → field stays at the schema default ([]).

    See docs/resource_estimator_implement.md §14.N.
    """

    @pytest.fixture
    def gate_exhaustion(self):
        from agent.schemas.hyperparam_tuning import GateExhaustionInfo
        return GateExhaustionInfo(
            total_attempts=9,
            vram_gated_attempts=9,
            time_gated_attempts=0,
            other_failure_attempts=0,
            active_mode="trial",
            vram_budget_gb=4.0,
            time_budget_minutes=20.0,
            baseline_vram_estimate_gb=6.4,
            baseline_vram_factor=1.6,
            baseline_time_estimate_minutes=8.0,
            baseline_time_factor=0.4,
            worst_vram_factor=2.0,
            worst_time_factor=0.6,
            summary_message="All 9 attempts were rejected by the VRAM gate.",
        )

    def _second_gate_exhaustion(self):
        from agent.schemas.hyperparam_tuning import GateExhaustionInfo
        return GateExhaustionInfo(
            total_attempts=3,
            vram_gated_attempts=0,
            time_gated_attempts=3,
            other_failure_attempts=0,
            active_mode="trial",
            vram_budget_gb=8.0,
            time_budget_minutes=20.0,
            baseline_vram_estimate_gb=1.2,
            baseline_vram_factor=0.15,
            baseline_time_estimate_minutes=45.0,
            baseline_time_factor=2.25,
            worst_vram_factor=0.2,
            worst_time_factor=3.1,
            summary_message="All 3 attempts exceeded the 20 min time budget.",
        )

    def _make_tune_output(self, gate_exhaustion=None):
        from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
        return HyperparamTuningOutput(
            run_name="prev_iter",
            model_type="punet",
            file_index=0,
            status="partial",
            completed_rounds=0,
            total_attempts=9,
            best_exp_id=None,
            best_denoising_score=None,
            best_config=None,
            best_file_vector=None,
            all_records=[],
            started_at="2026-04-18 10:00:00",
            finished_at="2026-04-18 11:00:00",
            gate_exhaustion=gate_exhaustion,
        )

    def test_default_empty_when_kwarg_omitted(self, storage):
        """No ``recent_tune_outputs`` kwarg → field stays at schema default
        ([]). Confirms backward compat: existing callers don't need to
        touch this."""
        output = make_interpretation_output(["punet"])
        result = local_full_context(output, storage)
        assert result.recent_gate_exhaustions == []

    def test_default_empty_when_all_outputs_have_no_gate_exhaustion(self, storage):
        """Successful prior iterations carry ``gate_exhaustion=None`` — the
        protocol must skip them and leave the list empty."""
        output = make_interpretation_output(["punet"])
        priors = [
            self._make_tune_output(gate_exhaustion=None),
            self._make_tune_output(gate_exhaustion=None),
        ]
        result = local_full_context(output, storage, recent_tune_outputs=priors)
        assert result.recent_gate_exhaustions == []

    def test_surfaces_single_gate_exhaustion_when_only_one_populated(
        self, storage, gate_exhaustion
    ):
        """Three recent outputs, only the middle one aborted → output list
        has length 1. Filtering must drop the None entries, not substitute
        placeholders."""
        from agent.schemas.hyperparam_tuning import GateExhaustionInfo
        output = make_interpretation_output(["punet"])
        priors = [
            self._make_tune_output(gate_exhaustion=None),
            self._make_tune_output(gate_exhaustion=gate_exhaustion),
            self._make_tune_output(gate_exhaustion=None),
        ]
        result = local_full_context(output, storage, recent_tune_outputs=priors)
        assert len(result.recent_gate_exhaustions) == 1
        assert isinstance(
            result.recent_gate_exhaustions[0], GateExhaustionInfo
        )
        assert (
            result.recent_gate_exhaustions[0].model_dump()
            == gate_exhaustion.model_dump()
        )

    def test_preserves_oldest_first_order_for_multi_entry_aggregation(
        self, storage, gate_exhaustion
    ):
        """Two populated outputs → list contains both in the same order the
        workflow passed them (oldest first). Order is load-bearing because
        the proposer renders each entry with a relative-iteration label."""
        output = make_interpretation_output(["punet"])
        second = self._second_gate_exhaustion()
        priors = [
            self._make_tune_output(gate_exhaustion=gate_exhaustion),
            self._make_tune_output(gate_exhaustion=second),
        ]
        result = local_full_context(output, storage, recent_tune_outputs=priors)
        assert len(result.recent_gate_exhaustions) == 2
        assert (
            result.recent_gate_exhaustions[0].model_dump()
            == gate_exhaustion.model_dump()
        )
        assert (
            result.recent_gate_exhaustions[1].model_dump()
            == second.model_dump()
        )

    def test_kwarg_independent_of_other_pass_through_fields(
        self, storage, gate_exhaustion
    ):
        """Surfacing recent gate exhaustions must not silently reset any of
        the other workflow-supplied kwargs — verifies the partial-plumbing
        guarantee documented at the top of the function."""
        output = make_interpretation_output(["punet"])
        priors = [self._make_tune_output(gate_exhaustion=gate_exhaustion)]
        result = local_full_context(
            output,
            storage,
            recent_tune_outputs=priors,
            trial_time_budget_minutes=60.0,
        )
        assert len(result.recent_gate_exhaustions) == 1
        assert result.trial_time_budget_minutes == 60.0
        # Untouched kwargs keep their schema defaults
        assert result.formal_time_budget_minutes is None
        assert result.is_trial is False


# ---------------------------------------------------------------------------
# database_full_context
# ---------------------------------------------------------------------------

class TestDatabaseFullContext:

    def test_raises_not_implemented(self, storage):
        output = make_interpretation_output(["punet"])
        with pytest.raises(NotImplementedError):
            database_full_context(output, storage)
