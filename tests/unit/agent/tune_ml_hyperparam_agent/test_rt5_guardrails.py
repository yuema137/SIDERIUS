"""
RT5 — §5 step/batch guardrails (defense-in-depth).

Pins the pure guardrail matrix (steps ceiling, formal-only batch floor,
operator override, disabled-by-None), the best-effort step resolution,
and the planner-visible rejection record with its config provenance.
Schema defaults are None (zero behavior change — the §5 provisional
operational values land with the RT6 chain wiring).
"""

from __future__ import annotations

import pytest

from agent.schemas.hyperparam_tuning import ExperimentRecord, HyperparamTuningInput
from execute_tools.dataset_config import TIDMAD_PROFILE
from nodes.ml_hyperparameter_tune_agent import (
    _build_guardrail_rejection_record,
    _evaluate_step_guardrails,
    _resolve_guardrail_steps,
)

_BASE = dict(
    n_steps=100_000,
    batch_size=8,
    is_formal=True,
    max_steps_per_attempt=150_000,
    min_formal_batch_size=4,
    allow_extreme_steps=False,
)


class TestGuardrailMatrix:
    def test_within_limits_passes(self):
        assert _evaluate_step_guardrails(**_BASE) == []

    def test_step_ceiling_fires(self):
        violations = _evaluate_step_guardrails(**{**_BASE, "n_steps": 480_000})
        assert len(violations) == 1
        assert "max_steps_per_attempt" in violations[0]

    def test_formal_batch_floor_fires(self):
        violations = _evaluate_step_guardrails(**{**_BASE, "batch_size": 2})
        assert len(violations) == 1
        assert "min_formal_batch_size" in violations[0]
        assert "V18" in violations[0]  # the incident shape, named

    def test_trial_rounds_exempt_from_batch_floor(self):
        assert _evaluate_step_guardrails(**{**_BASE, "batch_size": 2, "is_formal": False}) == []

    def test_both_fire_together(self):
        violations = _evaluate_step_guardrails(**{**_BASE, "n_steps": 480_000, "batch_size": 2})
        assert len(violations) == 2

    def test_operator_override_bypasses_all(self):
        assert (
            _evaluate_step_guardrails(
                **{**_BASE, "n_steps": 480_000, "batch_size": 2, "allow_extreme_steps": True}
            )
            == []
        )

    def test_none_disables_each_check(self):
        assert (
            _evaluate_step_guardrails(
                **{**_BASE, "n_steps": 480_000, "max_steps_per_attempt": None}
            )
            == []
        )
        assert (
            _evaluate_step_guardrails(**{**_BASE, "batch_size": 1, "min_formal_batch_size": None})
            == []
        )

    def test_unresolvable_steps_skips_step_check(self):
        # Best-effort: the guardrail is defense-in-depth; the primary
        # runtime criterion still protects the attempt.
        assert _evaluate_step_guardrails(**{**_BASE, "n_steps": None}) == []


class TestStepResolution:
    def test_resolves_via_production_resolver(self):
        # 2 PSD × (10M // 10000) = 2000 samples // bs 8 = 250 steps.
        steps = _resolve_guardrail_steps(
            {"0": [0, 1]},
            {"segmentation_size": 10_000},
            {"batch_size": 8, "epochs": 1},
            None,
            dataset_profile=TIDMAD_PROFILE,
        )
        assert steps == 250

    def test_resolver_failure_returns_none(self):
        assert (
            _resolve_guardrail_steps(
                {"0": [0]}, {"segmentation_size": 0}, {}, None, dataset_profile=TIDMAD_PROFILE
            )
            is None
        )


class TestRejectionRecord:
    def test_record_shape_and_provenance(self):
        agent_input = HyperparamTuningInput.model_construct(
            max_steps_per_attempt=150_000,
            min_formal_batch_size=4,
            allow_extreme_steps=False,
        )
        record = _build_guardrail_rejection_record(
            exp_id="e1",
            model_type="wavenet",
            file_index=6,
            record_params={"k": "v"},
            expert_advice_str="",
            hypothesis="h",
            is_trial=False,
            round_index=1,
            attempt_in_round=1,
            violations=["resolved optimizer steps 480000 exceed max_steps_per_attempt 150000 (§5)"],
            n_steps=480_000,
            agent_input=agent_input,
        )
        ExperimentRecord.model_validate(record)  # planner-visible, schema-true
        assert record["status"] == "skipped_time_risk"  # §2.11 vocabulary reuse
        assert record["memory"]["verification_stage"] == "guardrail"
        # Config provenance shown (§11 RT5 checkpoint requirement).
        discovery = record["memory"]["discovery"]
        assert "max_steps_per_attempt=150000" in discovery
        assert "min_formal_batch_size=4" in discovery
        assert "allow_extreme_steps=False" in discovery
        assert "480000" in record["memory"]["conclusion"]


class TestSchemaDefaults:
    def test_guardrails_default_disabled(self):
        # Zero behavior change until the RT6 chain wiring sets the §5
        # provisional operational values.
        fields = HyperparamTuningInput.model_fields
        assert fields["max_steps_per_attempt"].default is None
        assert fields["min_formal_batch_size"].default is None
        assert fields["allow_extreme_steps"].default is False


class TestRT6CliMapping:
    """RT6: the tuner CLI carries the §5 operational defaults and maps
    0 → None (disabled); the chain layers stay default-synced (the
    shell-parity suite enforces the run_one_iteration ↔ shell side)."""

    def test_tuner_cli_operational_defaults_and_zero_disable(self):
        # The generic parser keeps the step ceiling, but the Formal-only batch
        # floor is opt-in so an executable Trial batch is not silently refused.
        from sdsc_submission_scripts.run_one_iteration import build_parser

        parser = build_parser()
        defaults = {a.dest: a.default for a in parser._actions if a.option_strings}
        assert defaults["max_steps_per_attempt"] == 150_000
        assert defaults["min_formal_batch_size"] == 0
        assert defaults["allow_extreme_steps"] is False
        # arXiv #261 (operator ruling 2026-08-25): the enablement flag is
        # TRI-STATE — None means "the (device, execution regime) runtime
        # profile decides at launch"; the pre-#261 hard False default moved
        # into the UNCALIBRATED profile resolution, pinned by
        # tests/unit/core/test_arxiv_261_watchdog_profile.py. This assert
        # still catches the regression that matters here: someone restoring
        # a hard boolean default, which would kill the profile path (False)
        # or force the watchdog on everywhere (True).
        assert defaults["runtime_watchdog"] is None
        assert defaults["runtime_watchdog_floor_seconds"] is None
        assert defaults["execution_regime"] == "single"
