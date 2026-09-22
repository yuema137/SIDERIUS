"""Step 07a C1 — ``TrainingHistory`` validators and the typed trainer→tuner
results contract (design §3.5, §3.4a, §3.3).

Each test names the defect only it catches (CLAUDE.md test rule). What a
Pydantic declaration already enforces (a Literal rejecting a stranger, a
default of None) is NOT re-tested; these are the RUNTIME rules of the
``model_validator`` and of ``interpret_training_results``.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from execute_tools.training_history import (
    COMPARABILITY_ESTABLISHED_KINDS,
    COMPARABILITY_REASON_CUSTOM,
    COMPARABILITY_REASON_SUM,
    EPOCH_STATISTIC,
    LEGACY_TRAINING_RESULT_KEYS,
    TrainingHistory,
    TrainingResultsContractError,
    interpret_training_results,
    objective_config_fingerprint,
    stamp_comparability,
)
from ml_models.models_format_sandbox import LossConfig


def _history(**overrides) -> dict:
    base = {
        "objective_kind": "focal",
        "objective_config_fingerprint": "f" * 64,
        "objective_reduction": "mean",
        "comparability": "established",
        "comparability_reason": None,
        "epochs_planned": 3,
        "epochs_completed": 3,
        "train_objective": [3.0, 2.0, 1.0],
        "validation_objective": [3.1, 2.1, 1.1],
        "validation_requested_samples": 24,
        "validation_samples": 24,
        "validation_seconds": [0.1, 0.1, 0.1],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# TrainingHistory validators — the runtime consistency rules (test j)
# ---------------------------------------------------------------------------


class TestTrainingHistoryValidators:
    def test_a_consistent_history_validates_and_the_defaults_are_the_frozen_ones(self):
        h = TrainingHistory.model_validate(_history())
        assert h.cadence == "per_epoch"
        assert (
            h.epoch_statistic == EPOCH_STATISTIC == "sample_count_weighted_mean_of_batch_criterion"
        )
        assert h.observations == {}

    @pytest.mark.parametrize(
        "bad, match",
        [
            ({"epochs_completed": 2}, "epochs_completed"),  # ≠ len(train_objective)
            ({"epochs_planned": 2}, "exceeds epochs_planned"),  # completed > planned
            ({"validation_objective": [3.1, 2.1]}, "len\\(validation_objective\\)"),
            ({"validation_samples": 23}, "materialize exactly"),  # §3.4b: shrunk scope
            ({"validation_requested_samples": 0, "validation_samples": 0}, "> 0"),
            ({"validation_seconds": [0.1, 0.1]}, "len\\(validation_seconds\\)"),
            ({"validation_seconds": [0.1, -0.1, 0.1]}, ">= 0"),
            (
                {"observations": {"validation_accuracy": [0.5, 0.6]}},
                "observations\\['validation_accuracy'\\]",
            ),
            ({"comparability_reason": "reduction=sum"}, "must be None"),  # established + reason
            ({"comparability": "not_established", "comparability_reason": None}, "required"),
            ({"validation_seconds": None}, "present together or absent together"),
        ],
    )
    def test_each_consistency_rule_rejects_its_violation(self, bad, match):
        """Defect: a producer emitting a ragged / shrunk / mislabelled payload
        would otherwise reach the record as valid evidence."""
        with pytest.raises(ValueError, match=match):
            TrainingHistory.model_validate(_history(**bad))

    def test_validation_absent_is_a_valid_state_when_ALL_validation_fields_are_none(self):
        h = TrainingHistory.model_validate(
            _history(
                validation_objective=None,
                validation_requested_samples=None,
                validation_samples=None,
                validation_seconds=None,
            )
        )
        assert h.validation_objective is None

    def test_non_finite_objective_values_are_evidence_not_a_schema_error(self):
        """Defect: a schema rejecting NaN/inf would turn a diverged run (evidence)
        into a contract failure and lose the raw values."""
        h = TrainingHistory.model_validate(
            _history(
                train_objective=[3.0, float("nan"), float("inf")],
                validation_objective=[3.1, float("nan"), float("-inf")],
            )
        )
        assert math.isnan(h.train_objective[1]) and math.isinf(h.validation_objective[2])  # type: ignore[index]

    def test_an_undeclared_key_is_refused(self):
        with pytest.raises(ValueError):
            TrainingHistory.model_validate(_history(unexpected=1))


# ---------------------------------------------------------------------------
# interpret_training_results — the ONE validation site (test i)
# ---------------------------------------------------------------------------


def _raw(history: dict | None = None, **legacy) -> dict:
    raw = {"final_loss": 1.0, "loss_history": [3.0, 2.0, 1.0], "model_params": 10}
    raw.update(legacy)
    if history is not None:
        raw["training_history"] = history
    return raw


class TestInterpretTrainingResults:
    def test_best_checkpoint_receipt_cannot_be_dropped_or_name_wrong_epoch(self):
        raw = _raw(_history())
        with pytest.raises(TrainingResultsContractError, match="requested selection policy"):
            interpret_training_results(
                raw, expected_validation=True, expected_checkpoint_selection="best_validation_loss"
            )
        raw["selected_checkpoint"] = {
            "policy": "best_validation_loss",
            "epoch": 1,
            "validation_loss": 3.1,
        }
        with pytest.raises(TrainingResultsContractError, match="disagrees with validation history"):
            interpret_training_results(raw, expected_validation=True)

    def test_present_history_yields_legacy_payload_exactly_and_the_typed_history(self):
        res = interpret_training_results(_raw(_history()), expected_validation=True)
        assert res.history_state == "present"
        assert res.history is not None and res.history.validation_objective == [3.1, 2.1, 1.1]
        assert tuple(res.legacy_payload) == LEGACY_TRAINING_RESULT_KEYS
        assert res.legacy_payload == {
            "final_loss": 1.0,
            "loss_history": [3.0, 2.0, 1.0],
            "model_params": 10,
        }

    def test_absent_payload_and_validation_not_expected_is_the_honest_absent_state(self):
        """Legacy producer (no `training_history` key) + legacy caller → absent,
        never an error (design §3.4a, first case)."""
        res = interpret_training_results(_raw(), expected_validation=False)
        assert res.history is None and res.history_state == "absent"
        assert set(res.legacy_payload) == set(LEGACY_TRAINING_RESULT_KEYS)

    def test_the_legacy_payload_carries_only_the_keys_that_are_present(self):
        res = interpret_training_results({"final_loss": 2.0}, expected_validation=False)
        assert res.legacy_payload == {"final_loss": 2.0}

    def test_expected_validation_with_no_payload_is_a_contract_failure(self):
        """§3.4a BLOCKER 1: an eval SampleSet was supplied but no history arrived
        (transport dropped) → error, never a quiet `absent`."""
        with pytest.raises(TrainingResultsContractError, match="EXPECTED"):
            interpret_training_results(_raw(), expected_validation=True)

    def test_expected_validation_with_history_but_no_r3_is_a_contract_failure(self):
        """§3.4a BLOCKER 1, second half: the payload arrived but
        `validation_objective is None` while validation was expected."""
        h = _history(
            validation_objective=None,
            validation_requested_samples=None,
            validation_samples=None,
            validation_seconds=None,
        )
        with pytest.raises(TrainingResultsContractError, match="validation_objective is None"):
            interpret_training_results(_raw(h), expected_validation=True)
        # The SAME payload on a legacy attempt is a valid absent-validation history.
        res = interpret_training_results(_raw(h), expected_validation=False)
        assert res.history is not None and res.history.validation_objective is None

    def test_schema_invalid_payload_is_a_contract_failure_not_absent(self):
        """Q-07a-6: a producer violating its own schema fails closed."""
        with pytest.raises(TrainingResultsContractError, match="schema-invalid"):
            interpret_training_results(
                _raw(_history(validation_samples=1)), expected_validation=False
            )

    def test_r2_disagreeing_with_loss_history_is_a_contract_failure(self):
        with pytest.raises(
            TrainingResultsContractError, match="disagrees with the legacy loss_history"
        ):
            interpret_training_results(
                _raw(_history(), loss_history=[3.0, 2.0, 0.5]), expected_validation=True
            )

    def test_final_loss_disagreeing_with_the_last_r2_is_a_contract_failure(self):
        with pytest.raises(TrainingResultsContractError, match="final_loss must equal"):
            interpret_training_results(_raw(_history(), final_loss=0.9), expected_validation=True)

    def test_nan_r2_and_nan_final_loss_agree_under_the_nan_aware_comparison(self):
        """Defect: a naive `!=` on floats reports NaN ≠ NaN and would refuse a
        diverged run's honest payload."""
        h = _history(train_objective=[3.0, 2.0, float("nan")], validation_objective=[3.1, 2.1, 1.1])
        res = interpret_training_results(
            _raw(h, loss_history=[3.0, 2.0, float("nan")], final_loss=float("nan")),
            expected_validation=True,
        )
        assert res.history is not None and math.isnan(res.history.train_objective[-1])

    def test_a_non_mapping_payload_is_a_contract_failure(self):
        with pytest.raises(TrainingResultsContractError, match="must be a mapping"):
            interpret_training_results(["not", "a", "dict"], expected_validation=False)


# ---------------------------------------------------------------------------
# Comparability stamping (test m) and the objective fingerprint (test n)
# ---------------------------------------------------------------------------


class TestComparabilityStamp:
    @pytest.mark.parametrize("kind", sorted(COMPARABILITY_ESTABLISHED_KINDS))
    def test_each_audited_built_in_mean_reduced_kind_is_established(self, kind):
        assert stamp_comparability(LossConfig(loss_type=kind, reduction="mean")) == (
            "established",
            None,
        )

    @pytest.mark.parametrize("kind", sorted(COMPARABILITY_ESTABLISHED_KINDS))
    def test_sum_reduction_is_not_established_with_the_frozen_reason(self, kind):
        assert stamp_comparability(LossConfig(loss_type=kind, reduction="sum")) == (
            "not_established",
            COMPARABILITY_REASON_SUM,
        )

    def test_a_custom_objective_is_not_established_regardless_of_reduction(self):
        """The plugin contract declares no normalization — recorded, never assumed."""
        for reduction in ("mean", "sum"):
            assert stamp_comparability(
                LossConfig(loss_type="custom", loss_name="any_plugin", reduction=reduction)
            ) == ("not_established", COMPARABILITY_REASON_CUSTOM)

    def test_the_audited_set_is_exactly_the_four_built_ins(self):
        """A kind enters this set by SOURCE AUDIT (design §3.3 table), never by
        assumption; growing it silently would over-claim comparability."""
        assert COMPARABILITY_ESTABLISHED_KINDS == frozenset(
            {"focal", "focal_cw", "ce", "smooth_l1"}
        )


class TestObjectiveConfigFingerprint:
    def test_it_separates_configurations_within_the_same_family(self):
        """`objective_kind` alone would call focal(gamma=1) and focal(gamma=4) the same
        objective — the fingerprint must not."""
        a = objective_config_fingerprint(LossConfig(loss_type="focal", gamma=1.0))
        b = objective_config_fingerprint(LossConfig(loss_type="focal", gamma=4.0))
        assert a != b and len(a) == 64

    def test_it_is_stable_across_processes(self):
        """A per-process salt (or a dict-order dependence) would make the same
        resolved configuration fingerprint differently in the trainer
        subprocess and in the tuner — the whole point of a fingerprint."""
        cfg = LossConfig(loss_type="focal", gamma=3.0, alpha=0.25)
        here = objective_config_fingerprint(cfg)
        code = (
            "import json, sys;"
            "from execute_tools.training_history import objective_config_fingerprint as f;"
            "from ml_models.models_format_sandbox import LossConfig as L;"
            "print(f(L.model_validate(json.loads(sys.argv[1]))))"
        )
        repo_root = Path(__file__).resolve().parents[3]
        out = (
            subprocess.run(
                [sys.executable, "-c", code, json.dumps(cfg.model_dump())],
                capture_output=True,
                text=True,
                check=True,
                cwd=repo_root,
            )
            .stdout.strip()
            .splitlines()[-1]
        )
        assert out == here

    def test_it_is_a_configuration_surface_fingerprint_not_a_code_hash(self):
        """Two custom LossConfigs naming the SAME plugin fingerprint the same
        (the surface is identical) — the fingerprint claims nothing about the
        plugin's implementation."""
        a = objective_config_fingerprint(LossConfig(loss_type="custom", loss_name="p"))
        b = objective_config_fingerprint(LossConfig(loss_type="custom", loss_name="p"))
        assert a == b


class TestSeam5DocPresence:
    def test_the_genericity_contract_declares_seam_5(self):
        """Parent §8.2 item 6: Seam 5 is written BEFORE the code; the contract
        doc is the single place the seam is defined."""
        text = (
            Path(__file__)
            .resolve()
            .parents[3]
            .joinpath("docs/design/genericity_contract.md")
            .read_text()
        )
        assert "## Seam 5 — Training observation" in text
        assert "interpret_training_results" in text and "derive_training_diagnosis" in text
