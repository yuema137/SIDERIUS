"""
Phase K (K.7.3) — `_build_gate_exhaustion` truth table + populated synthesis.

Covers the helper that the tuner calls at finalisation to decide whether
to surface a `GateExhaustionInfo` payload to the next iteration's
proposer. See docs/resource_estimator_implement.md §10.13.

Truth table (must return None unless ALL three hold):
  * `records` is non-empty
  * no record has `status == "success"`
  * ≥1 record has `status in {"skipped_oom_risk", "skipped_time_risk"}`

When triggered, the populated factors must be derived from `records[0]`
for baseline and the per-record max for worst-case.
"""

from agent.schemas.hyperparam_tuning import GateExhaustionInfo
from nodes.ml_hyperparameter_tune_agent import (
    _build_gate_exhaustion,
    _render_gate_exhaustion_summary,
)

# ---------------------------------------------------------------------------
# Helpers — concise factories so individual test bodies stay tight.
# ---------------------------------------------------------------------------


def _vram_gated(vram_estimate_gb=6.4, vram_budget_gb=4.0):
    return {
        "exp_id": "x",
        "status": "skipped_oom_risk",
        "memory": {
            "vram_estimate_gb": vram_estimate_gb,
            "vram_budget_gb": vram_budget_gb,
        },
    }


def _time_gated(time_estimate_minutes=30.0, time_budget_minutes=20.0):
    return {
        "exp_id": "x",
        "status": "skipped_time_risk",
        "memory": {
            "time_estimate_minutes": time_estimate_minutes,
            "time_budget_minutes": time_budget_minutes,
            "time_mode": "trial",
        },
    }


def _success(score=0.42, vram_estimate_gb=2.0, time_estimate_minutes=8.0):
    return {
        "exp_id": "x",
        "status": "success",
        "denoising_score": score,
        "memory": {
            "vram_estimate_gb": vram_estimate_gb,
            "time_estimate_minutes": time_estimate_minutes,
            "time_mode": "trial",
        },
    }


def _schema_violation():
    return {
        "exp_id": "x",
        "status": "skipped_schema_violation",
        "memory": {},
    }


def _error():
    return {"exp_id": "x", "status": "error_runtime", "memory": {}}


# ---------------------------------------------------------------------------
# Truth table — None when criterion not met
# ---------------------------------------------------------------------------


class TestBuildGateExhaustionTruthTable:
    def test_empty_records_returns_none(self):
        assert (
            _build_gate_exhaustion(
                records=[],
                active_mode="trial",
                vram_budget_gb=4.0,
                time_budget_minutes=20.0,
            )
            is None
        )

    def test_ever_trained_true_returns_none(self):
        """Even if there are also gate-skips, any success means the
        proposer doesn't need the budget-related learning signal."""
        records = [_vram_gated(), _success(), _vram_gated()]
        assert (
            _build_gate_exhaustion(
                records=records,
                active_mode="trial",
                vram_budget_gb=4.0,
                time_budget_minutes=20.0,
            )
            is None
        )

    def test_no_gate_skip_returns_none(self):
        """ever_trained=False but every failure was a code bug or schema
        violation, NOT the resource gate. The proposer can't fix this by
        proposing a lighter architecture."""
        records = [_schema_violation(), _error(), _error()]
        assert (
            _build_gate_exhaustion(
                records=records,
                active_mode="trial",
                vram_budget_gb=4.0,
                time_budget_minutes=20.0,
            )
            is None
        )


# ---------------------------------------------------------------------------
# Populated path — VRAM-only gating
# ---------------------------------------------------------------------------


class TestBuildGateExhaustionVramOnly:
    def test_all_vram_gated_returns_populated_info(self):
        records = [
            _vram_gated(vram_estimate_gb=6.4),
            _vram_gated(vram_estimate_gb=7.5),
            _vram_gated(vram_estimate_gb=8.1),
        ]
        info = _build_gate_exhaustion(
            records=records,
            active_mode="trial",
            vram_budget_gb=4.0,
            time_budget_minutes=20.0,
        )
        assert isinstance(info, GateExhaustionInfo)
        assert info.total_attempts == 3
        assert info.vram_gated_attempts == 3
        assert info.time_gated_attempts == 0
        assert info.other_failure_attempts == 0
        assert info.active_mode == "trial"
        # Baseline factors come from records[0]
        assert info.baseline_vram_estimate_gb == 6.4
        assert info.baseline_vram_factor == 1.6  # 6.4 / 4.0
        # Worst is across all records (max=8.1)
        assert info.worst_vram_factor == 2.025  # 8.1 / 4.0
        # Time fields are None — no record has a time estimate
        assert info.baseline_time_estimate_minutes is None
        assert info.baseline_time_factor is None
        assert info.worst_time_factor is None

    def test_summary_message_calls_out_vram_axis(self):
        info = _build_gate_exhaustion(
            records=[_vram_gated()],
            active_mode="trial",
            vram_budget_gb=4.0,
            time_budget_minutes=20.0,
        )
        assert "VRAM gate" in info.summary_message
        # Verdict line points at the right lever
        assert "too heavy" in info.summary_message
        assert "Reduce parameter count" in info.summary_message


# ---------------------------------------------------------------------------
# Populated path — time-only gating
# ---------------------------------------------------------------------------


class TestBuildGateExhaustionTimeOnly:
    def test_all_time_gated_returns_populated_info(self):
        records = [
            _time_gated(time_estimate_minutes=30.0),
            _time_gated(time_estimate_minutes=45.0),
        ]
        info = _build_gate_exhaustion(
            records=records,
            active_mode="trial",
            vram_budget_gb=4.0,
            time_budget_minutes=20.0,
        )
        assert info.time_gated_attempts == 2
        assert info.vram_gated_attempts == 0
        assert info.baseline_time_estimate_minutes == 30.0
        assert info.baseline_time_factor == 1.5  # 30 / 20
        assert info.worst_time_factor == 2.25  # 45 / 20
        assert info.baseline_vram_estimate_gb is None
        assert info.baseline_vram_factor is None

    def test_summary_message_calls_out_time_axis(self):
        info = _build_gate_exhaustion(
            records=[_time_gated()],
            active_mode="trial",
            vram_budget_gb=4.0,
            time_budget_minutes=20.0,
        )
        assert "time gate" in info.summary_message
        assert "too slow" in info.summary_message


# ---------------------------------------------------------------------------
# Populated path — mixed gating + other failures
# ---------------------------------------------------------------------------


class TestBuildGateExhaustionMixed:
    def test_mixed_gating_with_other_failures(self):
        records = [
            _vram_gated(vram_estimate_gb=5.0),  # baseline
            _time_gated(time_estimate_minutes=25.0),
            _vram_gated(vram_estimate_gb=6.0),
            _error(),
            _schema_violation(),
        ]
        info = _build_gate_exhaustion(
            records=records,
            active_mode="trial",
            vram_budget_gb=4.0,
            time_budget_minutes=20.0,
        )
        assert info.total_attempts == 5
        assert info.vram_gated_attempts == 2
        assert info.time_gated_attempts == 1
        assert info.other_failure_attempts == 2
        # Baseline factors come from records[0] (the first VRAM-gated record)
        assert info.baseline_vram_estimate_gb == 5.0
        assert info.baseline_vram_factor == 1.25  # 5 / 4
        # Baseline carried no time estimate
        assert info.baseline_time_estimate_minutes is None
        assert info.baseline_time_factor is None
        # Worst across whole list
        assert info.worst_vram_factor == 1.5  # 6 / 4
        assert info.worst_time_factor == 1.25  # 25 / 20

    def test_mixed_summary_uses_multi_axis_verdict(self):
        info = _build_gate_exhaustion(
            records=[_vram_gated(), _time_gated()],
            active_mode="trial",
            vram_budget_gb=4.0,
            time_budget_minutes=20.0,
        )
        assert "multiple" in info.summary_message
        assert "Both parameter count AND per-step compute" in info.summary_message


# ---------------------------------------------------------------------------
# Disabled-axis handling — None budget propagates None factors
# ---------------------------------------------------------------------------


class TestBuildGateExhaustionDisabledAxis:
    def test_vram_budget_none_yields_none_vram_factors(self):
        """When the VRAM budget kwarg is None (gate disabled for that
        mode), factor calculations on the VRAM axis must return None
        even if records carry vram_estimate_gb."""
        records = [_vram_gated(vram_estimate_gb=6.0)]
        info = _build_gate_exhaustion(
            records=records,
            active_mode="formal",
            vram_budget_gb=None,
            time_budget_minutes=20.0,
        )
        # Counts still populate
        assert info.vram_gated_attempts == 1
        # Factors are None because the budget is None
        assert info.baseline_vram_factor is None
        assert info.worst_vram_factor is None
        # Estimate value still surfaces — useful diagnostic for the proposer
        assert info.baseline_vram_estimate_gb == 6.0
        assert info.vram_budget_gb is None
        assert info.active_mode == "formal"

    def test_time_budget_none_yields_none_time_factors(self):
        records = [_time_gated()]
        info = _build_gate_exhaustion(
            records=records,
            active_mode="trial",
            vram_budget_gb=4.0,
            time_budget_minutes=None,
        )
        assert info.baseline_time_factor is None
        assert info.worst_time_factor is None


# ---------------------------------------------------------------------------
# Render summary directly — guarded fallback when baseline is empty
# ---------------------------------------------------------------------------


class TestRenderGateExhaustionSummary:
    def test_baseline_estimate_missing_uses_worst_only_phrasing(self):
        msg = _render_gate_exhaustion_summary(
            total=1,
            vram_gated=1,
            time_gated=0,
            other=0,
            active_mode="trial",
            vram_budget_gb=4.0,
            time_budget_minutes=20.0,
            baseline_vram=None,
            baseline_vram_factor=None,
            baseline_time=None,
            baseline_time_factor=None,
            worst_vram_factor=1.5,
            worst_time_factor=None,
        )
        assert "baseline estimate not recorded" in msg
        assert "1.50×" in msg


# ---------------------------------------------------------------------------
# Phase L — Trigger B (some successes, then a fail-round burst). See §11.4.
# ---------------------------------------------------------------------------


def _round(record: dict, round_index: int) -> dict:
    """Tag a record with its Phase L round_index so burst lookup works."""
    record = {**record, "memory": dict(record.get("memory") or {})}
    record["memory"]["round_index"] = round_index
    return record


class TestBuildGateExhaustionTriggerBTruthTable:
    """Truth table for the Phase L Trigger B branch — fires only when
    (a) the loop hit the consecutive-failure brake (not max_rounds),
    (b) at least one round previously succeeded, and
    (c) the burst was dominated (>=50%) by VRAM/time gate skips.
    """

    def test_max_fail_rounds_zero_disables_trigger_b(self):
        """Defaults (max_fail_rounds=0) preserve pre-Phase-L behaviour:
        Trigger B never fires, only Trigger A. Records with successes
        therefore return None even with a burst of fail-rounds."""
        records = [
            _round(_success(), 1),
            _round(_vram_gated(), 2),
            _round(_vram_gated(), 2),
        ]
        assert (
            _build_gate_exhaustion(
                records=records,
                active_mode="trial",
                vram_budget_gb=4.0,
                time_budget_minutes=20.0,
                # max_fail_rounds defaulted to 0
            )
            is None
        )

    def test_completed_rounds_zero_falls_through_to_trigger_a(self):
        """K=0 ('after K successful rounds') makes Trigger B inapplicable;
        Trigger A handles the no-success case under its own framing."""
        records = [
            _round(_vram_gated(), 1),
            _round(_vram_gated(), 1),
            _round(_vram_gated(), 1),
        ]
        info = _build_gate_exhaustion(
            records=records,
            active_mode="trial",
            vram_budget_gb=4.0,
            time_budget_minutes=20.0,
            consecutive_fail_rounds_at_exit=3,
            max_fail_rounds=3,
            completed_rounds=0,
        )
        assert info is not None
        # Trigger A summary, NOT Trigger B's "Model too large" lead.
        assert "Model too large" not in info.summary_message
        assert "All 3 attempt" in info.summary_message

    def test_burst_below_50pct_gate_skip_does_not_fire(self):
        """Burst with 1 gate-skip + 2 schema-violations (33%) does not
        meet the 0.5 threshold → no Trigger B; Trigger A also blocked
        by the prior success."""
        records = [
            _round(_success(), 1),
            _round(_vram_gated(), 2),
            _round(_schema_violation(), 2),
            _round(_schema_violation(), 2),
        ]
        assert (
            _build_gate_exhaustion(
                records=records,
                active_mode="trial",
                vram_budget_gb=4.0,
                time_budget_minutes=20.0,
                consecutive_fail_rounds_at_exit=3,
                max_fail_rounds=3,
                completed_rounds=1,
            )
            is None
        )

    def test_consecutive_fails_below_threshold_does_not_fire(self):
        """consecutive_fail_rounds_at_exit < max_fail_rounds means the
        loop didn't actually hit the brake, so Trigger B is moot."""
        records = [
            _round(_success(), 1),
            _round(_vram_gated(), 2),
            _round(_vram_gated(), 2),
        ]
        assert (
            _build_gate_exhaustion(
                records=records,
                active_mode="trial",
                vram_budget_gb=4.0,
                time_budget_minutes=20.0,
                consecutive_fail_rounds_at_exit=1,
                max_fail_rounds=3,
                completed_rounds=1,
            )
            is None
        )


class TestBuildGateExhaustionTriggerBPopulated:
    def test_trigger_b_focuses_report_on_burst_records(self):
        """Successful rounds 1-2 had small VRAM estimates; round 3
        burst was all VRAM-gated. The report's baseline + worst factors
        must come from the burst, not the small successful records."""
        records = [
            # Successful rounds — should NOT influence the report.
            _round(_success(score=5.0, vram_estimate_gb=1.0), 1),
            _round(_success(score=6.0, vram_estimate_gb=1.5), 2),
            # Burst — round 3, all VRAM-gated, escalating estimates.
            _round(_vram_gated(vram_estimate_gb=8.0), 3),
            _round(_vram_gated(vram_estimate_gb=10.0), 3),
            _round(_vram_gated(vram_estimate_gb=12.0), 3),
        ]
        info = _build_gate_exhaustion(
            records=records,
            active_mode="formal",
            vram_budget_gb=4.0,
            time_budget_minutes=20.0,
            consecutive_fail_rounds_at_exit=3,
            max_fail_rounds=3,
            completed_rounds=2,
        )
        assert isinstance(info, GateExhaustionInfo)
        # Counts reflect the burst only (3), not all records (5).
        assert info.total_attempts == 3
        assert info.vram_gated_attempts == 3
        # Baseline = first burst record (vram=8.0), NOT records[0] (vram=1.0).
        assert info.baseline_vram_estimate_gb == 8.0
        assert info.baseline_vram_factor == 2.0  # 8.0 / 4.0
        # Worst over burst (max=12.0), not over the small successful records.
        assert info.worst_vram_factor == 3.0  # 12.0 / 4.0

    def test_trigger_b_summary_uses_phase_l_framing(self):
        records = [
            _round(_success(), 1),
            _round(_success(), 2),
            _round(_vram_gated(vram_estimate_gb=8.0), 3),
            _round(_vram_gated(vram_estimate_gb=9.0), 3),
        ]
        info = _build_gate_exhaustion(
            records=records,
            active_mode="formal",
            vram_budget_gb=4.0,
            time_budget_minutes=20.0,
            consecutive_fail_rounds_at_exit=3,
            max_fail_rounds=3,
            completed_rounds=2,
        )
        msg = info.summary_message
        # Lead phrase per §11.4 spec.
        assert "Model too large" in msg
        assert "3 consecutive rounds" in msg
        assert "after 2 successful round(s)" in msg
        assert "reduce model size" in msg
        # Burst-focused diagnostic.
        assert "Burst baseline" in msg
        assert "2.00×" in msg  # baseline factor 8.0/4.0

    def test_trigger_b_with_mixed_burst_axis_says_vram_time(self):
        """Burst has both VRAM- and time-gated attempts → axis label
        becomes 'VRAM/time'."""
        records = [
            _round(_success(), 1),
            _round(_vram_gated(vram_estimate_gb=8.0), 2),
            _round(_time_gated(time_estimate_minutes=30.0), 2),
        ]
        info = _build_gate_exhaustion(
            records=records,
            active_mode="trial",
            vram_budget_gb=4.0,
            time_budget_minutes=20.0,
            consecutive_fail_rounds_at_exit=3,
            max_fail_rounds=3,
            completed_rounds=1,
        )
        assert info is not None
        assert "VRAM/time gate" in info.summary_message
