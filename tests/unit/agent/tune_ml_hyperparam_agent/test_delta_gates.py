"""Unit tests for the post-v15 delta gates: ``skip_formal_min_delta`` and
``bypass_formal_time_budget_min_delta``.

V19 PR 1 (docs/design/v19_priorities/pr1_chain_incumbents.md, P1-C1):
``current_run_best_formal_score`` is the chain formal-incumbent
reference, ``float | None`` with ``None`` = "no incumbent". Defaults:
  * ``current_run_best_formal_score = None`` → both gates short-circuit
  * ``skip_formal_min_delta = -1.0`` → skip formal when trial < (ref - 1.0)
  * ``bypass_formal_time_budget_min_delta = 0.0`` → bypass time gate when
    trial >= ref

``_resolve_formal_comparison_thresholds`` is the SINGLE authoritative
computation: the gates, the startup banner, and the persisted output
metadata all consume its values (no independent ``ref + delta`` copies).

Motivation history (v15 retrospective) is retained on the schema block
comment; see ``agent/schemas/hyperparam_tuning.py``.
"""

from __future__ import annotations

from agent.schemas.hyperparam_tuning import HyperparamTuningInput, HyperparamTuningOutput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
    _fmt_reference,
    _resolve_formal_comparison_thresholds,
    _should_bypass_formal_time_budget,
    _should_skip_formal,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_input(**overrides) -> HyperparamTuningInput:
    """Construct a minimal valid HyperparamTuningInput; tests override the
    delta-gate fields to exercise the schema contract."""
    storage = StorageConfig(local=LocalStorageConfig(workspace="/tmp/test_delta_gates"))
    base = {
        "model_type": "punet",
        "run_name": "test_delta_gates",
        "storage": storage,
    }
    base.update(overrides)
    return HyperparamTuningInput(**base)


_BLOCKING_IDS = (
    "output_diversity_blocking",
    "output_std_blocking",
    "amplitude_collapse_blocking",
)


def _valid_trial(score: float) -> dict:
    """A HealthGate-valid trial record eligible for `_best_trial_winner`."""
    return {
        "exp_id": f"trial_{score}",
        "status": "success",
        "denoising_score": score,
        "is_trial": True,
        "health_gate_results": [
            {
                "gate_name": gate_id,
                "execution_status": "passed",
                "check_passed": True,
                "would_invalidate_under_production_policy": False,
                "resolved_action": "continue",
            }
            for gate_id in _BLOCKING_IDS
        ],
        "memory": {"time_mode": "trial"},
    }


def _resolve(reference, skip_delta=-1.0, bypass_delta=0.0):
    return _resolve_formal_comparison_thresholds(
        reference_score=reference,
        skip_min_delta=skip_delta,
        bypass_min_delta=bypass_delta,
    )


# ---------------------------------------------------------------------------
# Schema defaults — the None incumbent sentinel
# ---------------------------------------------------------------------------


class TestDeltaGateSchema:
    def test_default_reference_is_none_no_incumbent(self):
        """V19 PR 1: default is ``None`` (no chain incumbent) — NOT the
        pre-V19 fixed 0.0 defect value."""
        inp = _make_input()
        assert inp.current_run_best_formal_score is None

    def test_explicit_zero_reference_remains_legal(self):
        """0.0 as an EXPLICIT reference stays valid (standalone runs) and
        behaves as an ordinary number, distinct from ``None``."""
        inp = _make_input(current_run_best_formal_score=0.0)
        assert inp.current_run_best_formal_score == 0.0
        ref, skip_t, bypass_t = _resolve(inp.current_run_best_formal_score)
        assert (ref, skip_t, bypass_t) == (0.0, -1.0, 0.0)

    def test_skip_formal_min_delta_default_is_one_dB_floor(self):
        inp = _make_input()
        assert inp.skip_formal_min_delta == -1.0

    def test_bypass_formal_time_budget_min_delta_default_is_zero(self):
        inp = _make_input()
        assert inp.bypass_formal_time_budget_min_delta == 0.0


# ---------------------------------------------------------------------------
# Resolver — the single source of gate arithmetic
# ---------------------------------------------------------------------------


class TestResolver:
    def test_none_reference_resolves_to_all_none(self):
        assert _resolve(None) == (None, None, None)

    def test_numeric_reference_resolves_sums(self):
        assert _resolve(6.0, skip_delta=-1.0, bypass_delta=0.5) == (6.0, 5.0, 6.5)

    def test_gates_consume_resolver_output_verbatim(self):
        """Single-source assertion: the values the gates receive are the
        resolver's outputs — recomputing ``ref + delta`` independently
        must give the identical threshold the gate fires on."""
        _ref, skip_t, bypass_t = _resolve(6.0, skip_delta=-1.0, bypass_delta=0.0)
        # skip fires exactly below skip_t
        assert _should_skip_formal([_valid_trial(skip_t - 0.01)], threshold=skip_t)
        assert not _should_skip_formal([_valid_trial(skip_t)], threshold=skip_t)
        # bypass fires exactly at/above bypass_t
        assert _should_bypass_formal_time_budget([_valid_trial(bypass_t)], threshold=bypass_t)
        assert not _should_bypass_formal_time_budget(
            [_valid_trial(bypass_t - 0.01)], threshold=bypass_t
        )

    def test_fmt_reference_renders_none_not_zero(self):
        """``None`` renders as 'none' — never as '0.0000' (the pre-V19
        defect value must be unrepresentable in banners)."""
        assert _fmt_reference(None) == "none"
        assert _fmt_reference(6.0) == "6.0000"


# ---------------------------------------------------------------------------
# None short-circuits — no incumbent means no gate can fire
# ---------------------------------------------------------------------------


class TestNoneShortCircuit:
    def test_skip_gate_cannot_fire_without_incumbent(self):
        _, skip_t, _ = _resolve(None)
        assert skip_t is None
        assert not _should_skip_formal([_valid_trial(-99.0)], threshold=skip_t)

    def test_bypass_gate_cannot_fire_without_incumbent(self):
        _, _, bypass_t = _resolve(None)
        assert bypass_t is None
        assert not _should_bypass_formal_time_budget([_valid_trial(99.0)], threshold=bypass_t)


# ---------------------------------------------------------------------------
# Numeric-threshold behavior (canonical operator scenarios, now through
# the real helpers)
# ---------------------------------------------------------------------------


class TestSkipFormalGate:
    def test_skip_fires_when_trial_well_below_best(self):
        """ref=6.0, delta=-1.0 → threshold=5.0 → trial 4.5 SKIPS formal."""
        _, skip_t, _ = _resolve(6.0, skip_delta=-1.0)
        assert skip_t == 5.0
        assert _should_skip_formal([_valid_trial(4.5)], threshold=skip_t)

    def test_skip_does_not_fire_when_trial_close_to_best(self):
        """trial 5.2 >= threshold 5.0 → formal proceeds."""
        _, skip_t, _ = _resolve(6.0, skip_delta=-1.0)
        assert not _should_skip_formal([_valid_trial(5.2)], threshold=skip_t)

    def test_skip_with_zero_delta_skips_anything_below_best(self):
        _, skip_t, _ = _resolve(6.0, skip_delta=0.0)
        assert skip_t == 6.0
        assert _should_skip_formal([_valid_trial(5.99)], threshold=skip_t)
        assert not _should_skip_formal([_valid_trial(6.01)], threshold=skip_t)


class TestBypassFormalTimeBudgetGate:
    def test_bypass_fires_when_trial_beats_best(self):
        _, _, bypass_t = _resolve(6.0, bypass_delta=0.0)
        assert bypass_t == 6.0
        assert _should_bypass_formal_time_budget([_valid_trial(6.1)], threshold=bypass_t)

    def test_bypass_does_not_fire_when_trial_below_best(self):
        _, _, bypass_t = _resolve(6.0, bypass_delta=0.0)
        assert not _should_bypass_formal_time_budget([_valid_trial(5.9)], threshold=bypass_t)

    def test_bypass_with_positive_delta_requires_clear_margin(self):
        _, _, bypass_t = _resolve(6.0, bypass_delta=0.5)
        assert bypass_t == 6.5
        assert not _should_bypass_formal_time_budget([_valid_trial(6.4)], threshold=bypass_t)
        assert _should_bypass_formal_time_budget([_valid_trial(6.5)], threshold=bypass_t)


class TestDisableGatesViaInfinity:
    """Both gates can still be turned off via boundary deltas; the
    disable semantics moved INSIDE the helpers with the resolved-value
    signature."""

    def test_skip_gate_disabled_at_negative_infinity(self):
        _, skip_t, _ = _resolve(6.0, skip_delta=float("-inf"))
        assert skip_t == float("-inf")
        assert not _should_skip_formal([_valid_trial(-99.0)], threshold=skip_t)

    def test_bypass_gate_disabled_at_positive_infinity(self):
        _, _, bypass_t = _resolve(6.0, bypass_delta=float("inf"))
        assert bypass_t == float("inf")
        assert not _should_bypass_formal_time_budget([_valid_trial(99.0)], threshold=bypass_t)


# ---------------------------------------------------------------------------
# Persistence round-trip and the phantom negative
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_none_reference_round_trips_through_output(self):
        """``formal_reference_score=None`` survives HyperparamTuningOutput
        serialization → JSON null → parse."""
        out = HyperparamTuningOutput(
            run_name="rt",
            model_type="punet",
            file_index=0,
            status="completed",
            completed_rounds=0,
            total_attempts=0,
            all_records=[],
            started_at="2026-07-27 00:00:00",
            finished_at="2026-07-27 00:00:01",
            formal_reference_score=None,
            resolved_skip_formal_threshold=None,
            resolved_bypass_formal_threshold=None,
        )
        parsed = HyperparamTuningOutput.model_validate_json(out.model_dump_json())
        assert parsed.formal_reference_score is None
        assert parsed.resolved_skip_formal_threshold is None
        assert parsed.resolved_bypass_formal_threshold is None

    def test_phantom_family_reference_is_just_a_number(self):
        """5.5763 (class-127 phantom fingerprint) as an explicit reference
        gets no special-casing — it resolves like any float. Guarding
        against phantom DEFAULTS is the schema's job (default is None);
        eligibility filtering is reconstruction's job (P1-C2)."""
        ref, skip_t, bypass_t = _resolve(5.5762667, skip_delta=-1.0, bypass_delta=0.0)
        assert ref == 5.5762667
        assert skip_t == 4.5762667
        assert bypass_t == 5.5762667
