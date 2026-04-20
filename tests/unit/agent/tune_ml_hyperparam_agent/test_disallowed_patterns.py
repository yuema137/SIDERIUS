"""Fix 1 Commit 3 — tuner populates ``disallowed_architectural_patterns``.

Covers the ``_collect_disallowed_patterns`` helper and its integration into
``_build_gate_exhaustion``. See
``docs/reliable_resource_proposer.md`` §7 Decision 2 + §9 Commit 3.

The helper's contract:

* Only gate-rejected attempts (``skipped_oom_risk`` / ``skipped_time_risk``)
  are considered — code bugs and schema violations are excluded because
  their failure mode is not resource-structural.
* Each attempt is kept only if its per-attempt ``time_factor`` exceeds
  ``TIME_FACTOR_THRESHOLD`` **or** its ``vram_factor`` exceeds
  ``VRAM_FACTOR_THRESHOLD`` — marginal overshoots are not structural bans.
* Kept attempts contribute tags via ``tag_architecture``; the returned
  list is the sorted, deduplicated union.
"""
from __future__ import annotations

from agent.utils.architectural_pattern_tagger import (
    TIME_FACTOR_THRESHOLD,
    VRAM_FACTOR_THRESHOLD,
)
from nodes.ml_hyperparameter_tune_agent import (
    _build_gate_exhaustion,
    _collect_disallowed_patterns,
)


# ---------------------------------------------------------------------------
# Factories — record shapes mirror the live tuner output.
# ---------------------------------------------------------------------------


def _time_gated_attempt(
    *,
    model_type: str,
    model_config: dict,
    time_estimate_minutes: float,
    time_budget_minutes: float = 20.0,
):
    return {
        "exp_id": f"{model_type}_x",
        "status": "skipped_time_risk",
        "model_type": model_type,
        "model_config": model_config,
        "memory": {
            "time_estimate_minutes": time_estimate_minutes,
            "time_budget_minutes": time_budget_minutes,
            "time_mode": "trial",
        },
    }


def _vram_gated_attempt(
    *,
    model_type: str,
    model_config: dict,
    vram_estimate_gb: float,
    vram_budget_gb: float = 8.0,
):
    return {
        "exp_id": f"{model_type}_x",
        "status": "skipped_oom_risk",
        "model_type": model_type,
        "model_config": model_config,
        "memory": {
            "vram_estimate_gb": vram_estimate_gb,
            "vram_budget_gb": vram_budget_gb,
        },
    }


def _scan_cfg():
    """Matches iter 2's selective_bidirectional_scan_conv config shape."""
    return {"segmentation_size": 40000, "num_blocks": 12, "state_dim": 16}


def _gru_cfg():
    """Matches iter 3's dual_path_gated_gru_stack config shape."""
    return {"segmentation_size": 40000, "num_blocks": 6, "gru_hidden_size": 128}


def _tcn_cfg():
    """Matches iter 4's successful gated_fourier_tcn config shape."""
    return {"segmentation_size": 40000, "num_blocks": 6, "kernel_size": 3}


# ---------------------------------------------------------------------------
# _collect_disallowed_patterns — threshold logic + record filtering
# ---------------------------------------------------------------------------


class TestCollectDisallowedPatternsThresholds:

    def test_iter2_style_9_scan_attempts_at_huge_factor_yields_scan_tag(self):
        """iter 2 of explore_novel_v3_0420 — 9 × selective-scan attempts at
        factor≈18,772×. Structural infeasibility; must contribute ``scan_over_T``."""
        records = [
            _time_gated_attempt(
                model_type="selective_bidirectional_scan_conv",
                model_config=_scan_cfg(),
                time_estimate_minutes=375_438.77,
                time_budget_minutes=20.0,
            )
            for _ in range(9)
        ]
        out = _collect_disallowed_patterns(
            records, vram_budget_gb=None, time_budget_minutes=20.0
        )
        assert out == ["scan_over_T"]

    def test_iter3_style_9_gru_attempts_at_moderate_factor_yields_recurrent_tag(self):
        """iter 3 — 9 × GRU attempts at factor≈28×. Still well above the
        5× threshold, so ``recurrent_over_T`` must be contributed."""
        records = [
            _time_gated_attempt(
                model_type="dual_path_gated_gru_stack",
                model_config=_gru_cfg(),
                time_estimate_minutes=561.0,
                time_budget_minutes=20.0,
            )
            for _ in range(9)
        ]
        out = _collect_disallowed_patterns(
            records, vram_budget_gb=None, time_budget_minutes=20.0
        )
        assert out == ["recurrent_over_T"]

    def test_mixed_scan_and_gru_records_yield_both_tags_sorted(self):
        records = [
            _time_gated_attempt(
                model_type="scan_net",
                model_config=_scan_cfg(),
                time_estimate_minutes=2000.0,
            ),
            _time_gated_attempt(
                model_type="gru_stack",
                model_config=_gru_cfg(),
                time_estimate_minutes=500.0,
            ),
        ]
        out = _collect_disallowed_patterns(
            records, vram_budget_gb=None, time_budget_minutes=20.0
        )
        assert out == ["recurrent_over_T", "scan_over_T"]

    def test_marginal_overshoot_under_threshold_yields_no_tags(self):
        """factor=1.3× (below the 5.0× threshold) is hyperparameter
        recoverable; the whole class must not be banned."""
        records = [
            _time_gated_attempt(
                model_type="gru_stack",
                model_config=_gru_cfg(),
                time_estimate_minutes=26.0,
                time_budget_minutes=20.0,
            )
        ]
        out = _collect_disallowed_patterns(
            records, vram_budget_gb=None, time_budget_minutes=20.0
        )
        assert out == []

    def test_threshold_exactly_at_boundary_is_not_banned(self):
        """The threshold is strictly greater-than — a factor of *exactly*
        ``TIME_FACTOR_THRESHOLD`` does not ban. Defensive against off-by-one
        regressions if someone later changes the comparator."""
        at_threshold_minutes = TIME_FACTOR_THRESHOLD * 20.0  # factor == threshold
        records = [
            _time_gated_attempt(
                model_type="gru_stack",
                model_config=_gru_cfg(),
                time_estimate_minutes=at_threshold_minutes,
                time_budget_minutes=20.0,
            )
        ]
        out = _collect_disallowed_patterns(
            records, vram_budget_gb=None, time_budget_minutes=20.0
        )
        assert out == []

    def test_vram_factor_alone_can_trigger_ban(self):
        """The OR is symmetric — a VRAM overshoot past the VRAM threshold
        should contribute tags even if the time factor is None/low."""
        records = [
            _vram_gated_attempt(
                model_type="gru_stack",
                model_config=_gru_cfg(),
                vram_estimate_gb=VRAM_FACTOR_THRESHOLD * 8.0 + 1.0,  # > 2× budget
                vram_budget_gb=8.0,
            )
        ]
        out = _collect_disallowed_patterns(
            records, vram_budget_gb=8.0, time_budget_minutes=None
        )
        assert out == ["recurrent_over_T"]

    def test_non_gate_failures_never_contribute_tags(self):
        """A schema-violation or runtime-error record — even on an
        infeasible arch — must not contribute tags. The failure mode is
        not resource-structural."""
        records = [
            {
                "exp_id": "x",
                "status": "skipped_schema_violation",
                "model_type": "gru_stack",
                "model_config": _gru_cfg(),
                "memory": {},
            },
            {
                "exp_id": "y",
                "status": "error_runtime",
                "model_type": "scan_net",
                "model_config": _scan_cfg(),
                "memory": {},
            },
        ]
        out = _collect_disallowed_patterns(
            records, vram_budget_gb=8.0, time_budget_minutes=20.0
        )
        assert out == []

    def test_successful_arch_is_never_banned(self):
        """A ``gated_fourier_tcn`` that happened to be time-gated at a huge
        factor — shouldn't happen in practice, but if it did, the tagger
        returns ``[]`` for it so no ban is recorded. Defends the working
        class against false bans."""
        records = [
            _time_gated_attempt(
                model_type="gated_fourier_tcn",
                model_config=_tcn_cfg(),
                time_estimate_minutes=5000.0,
            )
        ]
        out = _collect_disallowed_patterns(
            records, vram_budget_gb=None, time_budget_minutes=20.0
        )
        assert out == []

    def test_empty_records_yields_empty(self):
        assert _collect_disallowed_patterns(
            [], vram_budget_gb=8.0, time_budget_minutes=20.0
        ) == []

    def test_none_budgets_yield_empty(self):
        """If budgets are unknown, factors can't be computed — no bans."""
        records = [
            _time_gated_attempt(
                model_type="gru_stack",
                model_config=_gru_cfg(),
                time_estimate_minutes=1000.0,
            )
        ]
        out = _collect_disallowed_patterns(
            records, vram_budget_gb=None, time_budget_minutes=None
        )
        assert out == []


# ---------------------------------------------------------------------------
# Integration — the full _build_gate_exhaustion flow populates the field
# ---------------------------------------------------------------------------


class TestBuildGateExhaustionPopulatesPatterns:

    def test_trigger_a_iter2_scan_records_produce_scan_tag_on_info(self):
        """End-to-end: 9 scan attempts at factor≈18,772× → Trigger A fires →
        returned GateExhaustionInfo carries ``disallowed_architectural_patterns
        == ["scan_over_T"]``."""
        records = [
            _time_gated_attempt(
                model_type="selective_bidirectional_scan_conv",
                model_config=_scan_cfg(),
                time_estimate_minutes=375_438.77,
                time_budget_minutes=20.0,
            )
            for _ in range(9)
        ]
        info = _build_gate_exhaustion(
            records,
            active_mode="trial",
            vram_budget_gb=None,
            time_budget_minutes=20.0,
        )
        assert info is not None
        assert info.disallowed_architectural_patterns == ["scan_over_T"]

    def test_mixed_records_populate_sorted_union(self):
        records = [
            _time_gated_attempt(
                model_type="scan_net",
                model_config=_scan_cfg(),
                time_estimate_minutes=2000.0,
            ),
            _time_gated_attempt(
                model_type="gru_stack",
                model_config=_gru_cfg(),
                time_estimate_minutes=500.0,
            ),
        ]
        info = _build_gate_exhaustion(
            records,
            active_mode="trial",
            vram_budget_gb=None,
            time_budget_minutes=20.0,
        )
        assert info is not None
        assert info.disallowed_architectural_patterns == [
            "recurrent_over_T",
            "scan_over_T",
        ]

    def test_marginal_overshoot_populates_empty_patterns_but_still_fires_trigger(self):
        """Gate exhaustion still fires (factor 1.2× is still budget-gated),
        but no architectural ban — the summary_message stays; the new
        field is empty."""
        records = [
            _time_gated_attempt(
                model_type="gru_stack",
                model_config=_gru_cfg(),
                time_estimate_minutes=24.0,
                time_budget_minutes=20.0,
            )
            for _ in range(9)
        ]
        info = _build_gate_exhaustion(
            records,
            active_mode="trial",
            vram_budget_gb=None,
            time_budget_minutes=20.0,
        )
        assert info is not None
        assert info.disallowed_architectural_patterns == []

    def test_healthy_iteration_returns_none_and_no_patterns(self):
        """If no gate-skip ever happened (pure successes), _build_gate_exhaustion
        returns None entirely — no place for disallowed_architectural_patterns
        to leak. Backward-compat with Phase K.7 behaviour."""
        records = [
            {
                "exp_id": "x",
                "status": "success",
                "denoising_score": 0.42,
                "memory": {
                    "vram_estimate_gb": 2.0,
                    "time_estimate_minutes": 8.0,
                    "time_mode": "trial",
                },
            }
        ]
        info = _build_gate_exhaustion(
            records,
            active_mode="trial",
            vram_budget_gb=8.0,
            time_budget_minutes=20.0,
        )
        assert info is None

    def test_trigger_b_burst_of_scan_records_surfaces_scan_tag(self):
        """Trigger B (Phase L) — after K successful rounds, a burst of
        scan-arch attempts on one round exhausts the fail-round budget.
        The tag must reach the info built off the burst."""
        records = [
            # round 1 success
            {
                "exp_id": "ok1",
                "status": "success",
                "denoising_score": 0.5,
                "memory": {
                    "vram_estimate_gb": 2.0,
                    "time_estimate_minutes": 8.0,
                    "round_index": 1,
                },
            },
            # round 2 — the fail burst: 3 scan attempts each over threshold
            *(
                {
                    **_time_gated_attempt(
                        model_type="scan_net",
                        model_config=_scan_cfg(),
                        time_estimate_minutes=2000.0,
                    ),
                    "memory": {
                        "time_estimate_minutes": 2000.0,
                        "time_budget_minutes": 20.0,
                        "time_mode": "trial",
                        "round_index": 2,
                    },
                }
                for _ in range(3)
            ),
        ]
        info = _build_gate_exhaustion(
            records,
            active_mode="trial",
            vram_budget_gb=None,
            time_budget_minutes=20.0,
            consecutive_fail_rounds_at_exit=1,
            max_fail_rounds=1,
            completed_rounds=1,
        )
        assert info is not None, "Trigger B should have fired"
        assert info.disallowed_architectural_patterns == ["scan_over_T"]
