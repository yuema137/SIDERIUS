"""Schema validation for the pluggable health-check framework.

Covers the rev-6 HealthGate schemas: ``HealthCheckContext``,
``HealthCheckResult``, ``GateResult``, and ``GateAction``. The legacy
``HealthCheckOutput`` / ``HealthCheckPanelOutput`` classes were removed
in commit-6 (zero remaining consumers post-migration).

See ``docs/design/pluggable_health_checks.md`` §5 for the schema spec
and §15.2 for the per-commit test scope rule of thumb.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from execute_tools.health_checks.schemas import (
    GateAction,
    GateResult,
    HealthCheckContext,
    HealthCheckResult,
)

# ---------------------------------------------------------------------------
# GateAction
# ---------------------------------------------------------------------------


class TestGateAction:
    def test_expected_members(self):
        """The rev-6 action set is exactly four members — the runner's
        severity resolution ordering (SKIP_ITER > SKIP_TO_FORMAL >
        INVALIDATE_ROUND > CONTINUE) depends on this exact set."""
        assert {a.name for a in GateAction} == {
            "CONTINUE",
            "SKIP_ITER",
            "SKIP_TO_FORMAL",
            "INVALIDATE_ROUND",
        }

    def test_string_values(self):
        """String values match the YAML action keys operators type into
        configs/health_checks.yaml."""
        assert GateAction.CONTINUE.value == "continue"
        assert GateAction.SKIP_ITER.value == "skip_iter"
        assert GateAction.SKIP_TO_FORMAL.value == "skip_to_formal"
        assert GateAction.INVALIDATE_ROUND.value == "invalidate_round"

    def test_no_record_score(self):
        """rev-6 point 2 removed RECORD_SCORE — the tuner already knows
        which round is terminal and records the score on CONTINUE. This
        test pins that the enum stays lean; a future PR that adds
        RECORD_SCORE back must consciously decide to fail this."""
        with pytest.raises(AttributeError):
            _ = GateAction.RECORD_SCORE  # type: ignore[attr-defined]

    def test_string_enum_semantics(self):
        """GateAction is a StrEnum — instances compare equal to their str
        value. This is what lets the YAML loader produce
        `GateAction("continue")` directly."""
        assert GateAction.CONTINUE == "continue"
        assert GateAction("skip_iter") is GateAction.SKIP_ITER


# ---------------------------------------------------------------------------
# HealthCheckContext (rev-6)
# ---------------------------------------------------------------------------


class TestHealthCheckContext:
    def test_required_fields_construction(self):
        ctx = HealthCheckContext(model_name="my_model", run_name="run_001", round_index=1)
        assert ctx.model_name == "my_model"
        assert ctx.run_name == "run_001"
        assert ctx.round_index == 1

    def test_missing_all_required_fields_raises(self):
        with pytest.raises(ValidationError):
            HealthCheckContext()  # type: ignore[call-arg]

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"run_name": "r", "round_index": 1},  # missing model_name
            {"model_name": "m", "round_index": 1},  # missing run_name
            {"model_name": "m", "run_name": "r"},  # missing round_index
        ],
    )
    def test_missing_one_required_field_raises(self, kwargs):
        with pytest.raises(ValidationError):
            HealthCheckContext(**kwargs)  # type: ignore[arg-type]

    def test_iter_num_defaults_to_none(self):
        """D3: iter_num is optional because the tuner does not yet plumb
        the workflow-level iteration number through HyperparamTuningInput
        (plumbing deferred to commit-5)."""
        ctx = HealthCheckContext(model_name="m", run_name="r", round_index=1)
        assert ctx.iter_num is None

    def test_iter_num_can_be_set(self):
        ctx = HealthCheckContext(model_name="m", run_name="r", round_index=1, iter_num=15)
        assert ctx.iter_num == 15

    def test_get_denoised_path_prefers_explicit(self):
        """When a file_index is in denoised_paths, it wins over the callable."""
        ctx = HealthCheckContext(
            model_name="m",
            run_name="r",
            round_index=1,
            denoised_paths={0: "explicit.h5"},
            denoised_filename_fn=lambda fi: f"lazy_{fi:04d}.h5",
        )
        assert ctx.get_denoised_path(0) == "explicit.h5"

    def test_get_denoised_path_falls_back_to_callable(self):
        """Callable fills the gaps when no explicit path exists for an index."""
        ctx = HealthCheckContext(
            model_name="m",
            run_name="r",
            round_index=1,
            denoised_filename_fn=lambda fi: f"lazy_{fi:04d}.h5",
        )
        assert ctx.get_denoised_path(7) == "lazy_0007.h5"

    def test_get_denoised_path_returns_none_when_neither(self):
        ctx = HealthCheckContext(model_name="m", run_name="r", round_index=1)
        assert ctx.get_denoised_path(0) is None

    def test_output_data_defaults_are_empty(self):
        """Optional output-data fields have safe defaults so callers only
        populate what applies to the gate's stage."""
        ctx = HealthCheckContext(model_name="m", run_name="r", round_index=1)
        assert ctx.denoised_paths == {}
        assert ctx.denoised_filename_fn is None
        assert ctx.file_vector == []
        assert ctx.denoising_score is None

    def test_callable_excluded_from_json(self):
        """denoised_filename_fn is a Callable — not JSON-serialisable, and
        the context is a within-process transport, never persisted. Must
        be excluded from model_dump."""
        ctx = HealthCheckContext(
            model_name="m",
            run_name="r",
            round_index=1,
            denoised_filename_fn=lambda fi: "x.h5",
        )
        dumped = ctx.model_dump()
        assert "denoised_filename_fn" not in dumped

    def test_no_removed_fields(self):
        """rev-6 dropped data_dir, reference_file_vector, model_type,
        exp_id. Constructing with any of these should be silently ignored
        by pydantic default (extra='ignore'); the point of this test is to
        confirm the fields aren't on the model. If a future edit adds one
        back accidentally, this test surfaces it."""
        ctx = HealthCheckContext(model_name="m", run_name="r", round_index=1)
        for removed in ("data_dir", "reference_file_vector", "model_type", "exp_id"):
            assert not hasattr(ctx, removed), (
                f"Removed field {removed!r} reappeared on HealthCheckContext"
            )


# ---------------------------------------------------------------------------
# HealthCheckResult
# ---------------------------------------------------------------------------


class TestHealthCheckResult:
    def test_passed_true_defaults(self):
        r = HealthCheckResult(check_name="x", passed=True)
        assert r.reason == ""
        assert r.metrics == {}

    def test_passed_false_carries_reason(self):
        r = HealthCheckResult(
            check_name="output_diversity",
            passed=False,
            reason="output_diversity: only 1 unique int8 value in first 100000 samples",
            metrics={"unique_count": 1, "peek_samples": 100_000},
        )
        assert r.passed is False
        assert "output_diversity" in r.reason
        assert r.metrics["unique_count"] == 1

    def test_passed_false_semantics_pinned(self):
        """rev-6 uses ``passed=False`` to mean "flagged / degenerate".
        This pin exists because a prior schema (removed in commit-6)
        used the inverse convention ``is_degenerate=True`` — a future
        refactor that silently swaps polarity would break the
        ``_gate_results_to_score_meta`` mapping in the tuner (which
        depends on ``passed=False`` → ``is_degenerate=True`` for the
        legacy contract)."""
        flagged = HealthCheckResult(check_name="x", passed=False)
        assert flagged.passed is False
        healthy = HealthCheckResult(check_name="x", passed=True)
        assert healthy.passed is True

    def test_missing_required_fields_raises(self):
        with pytest.raises(ValidationError):
            HealthCheckResult()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# GateResult
# ---------------------------------------------------------------------------


class TestGateResult:
    def _make(self, action: GateAction, passed: bool = True) -> GateResult:
        return GateResult(
            gate_id="g1",
            round_index=1,
            passed=passed,
            action=action,
        )

    def test_should_skip_iter(self):
        gr = self._make(GateAction.SKIP_ITER, passed=False)
        assert gr.should_skip_iter is True
        assert gr.should_skip_to_formal is False
        assert gr.should_invalidate_round is False

    def test_should_skip_to_formal(self):
        gr = self._make(GateAction.SKIP_TO_FORMAL, passed=False)
        assert gr.should_skip_iter is False
        assert gr.should_skip_to_formal is True
        assert gr.should_invalidate_round is False

    def test_should_invalidate_round(self):
        gr = self._make(GateAction.INVALIDATE_ROUND, passed=False)
        assert gr.should_skip_iter is False
        assert gr.should_skip_to_formal is False
        assert gr.should_invalidate_round is True

    def test_continue_action_has_no_should_flag(self):
        gr = self._make(GateAction.CONTINUE, passed=True)
        assert gr.should_skip_iter is False
        assert gr.should_skip_to_formal is False
        assert gr.should_invalidate_round is False

    def test_round_index_propagation_at_schema_level(self):
        """rev-6 point 3 added round_index. The runner's ``evaluate_gate``
        (commit-3) will propagate it from ctx.round_index; here we pin
        that the field exists and roundtrips through the model."""
        gr = GateResult(
            gate_id="score_check_round_3",
            round_index=7,
            passed=True,
            action=GateAction.CONTINUE,
        )
        assert gr.round_index == 7

    def test_failure_reason_defaults_to_empty(self):
        gr = self._make(GateAction.CONTINUE, passed=True)
        assert gr.failure_reason == ""

    def test_check_results_defaults_to_empty_list(self):
        gr = self._make(GateAction.CONTINUE, passed=True)
        assert gr.check_results == []

    def test_full_construction_with_check_results(self):
        gr = GateResult(
            gate_id="collapse_check_round_1",
            round_index=1,
            passed=False,
            action=GateAction.SKIP_ITER,
            failure_reason="output_diversity: only 1 unique int8 value",
            check_results=[
                HealthCheckResult(
                    check_name="output_diversity",
                    passed=False,
                    reason="output_diversity: only 1 unique int8 value",
                    metrics={"unique_count": 1},
                ),
            ],
        )
        assert len(gr.check_results) == 1
        assert gr.check_results[0].check_name == "output_diversity"
        assert gr.failure_reason.startswith("output_diversity:")
