# tests/unit/execute_tools/health_checks/test_step10_p4_c0_evidence_baseline.py
"""Step 10 / P4 — C0: the pre-migration evidence baseline and residual census.

Two jobs, both anti-vacuous by construction.

**1. Frozen goldens for the evidence P4 must preserve.** Every expectation
below is a HARDCODED literal captured from the base tree at ``d44f6f6a``
(production tree == the P1 squash ``bcb17e45``), never read back from the
code under test. C2/C3' re-run these same probes and must reproduce the
TIDMAD half byte-for-byte.

**2. The defect, recorded before the fix.** Pets and DAVIS are captured in
their CURRENT blank state at BOTH hops of the evidence path:

    check.run()  ->  evaluation.py::_persist       [hop 1: threshold row]
                 ->  record.health_gate_results
                 ->  evidence.py:267-268
                 ->  health_feedback.py            [hop 2: fingerprint]

A task-owned check absent from the framework's name-keyed tables persists no
threshold row (hop 1) and therefore yields no ``CollapseFingerprint`` (hop 2)
— the gate still fires and still blocks correctly; its evidence is silently
poorer than TIDMAD's. ``CONTRAST_BASELINE_IS_BLANK`` is a **defect witness**:
C2 flips its hop-1 half and C3' flips its hop-2 half, and each flip is a
deliberate, reviewable edit recorded in the design ledger.

Nothing here asserts a value the implementation generated in the same run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from execute_tools.health_checks import evaluation
from execute_tools.health_checks.config import load_composed_health_config
from execute_tools.health_checks.schemas import (
    CheckVerdict,
    GateAction,
    GateResult,
    HealthCheckContext,
    HealthCheckResult,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
PETS_BINDING = REPO_ROOT / "examples" / "oxford_iiit_pet" / "declared" / "task_health.yaml"
DAVIS_BINDING = REPO_ROOT / "examples" / "davis_future_prediction" / "declared" / "task_health.yaml"


# ---------------------------------------------------------------------------
# Synthetic check metrics, in each check's REAL emitted shape
#
# Taken from the checks themselves so `_per_file_metrics` exercises all three
# of its input branches: a `per_file` LIST (the three peek checks), and the
# named-dict fallbacks `pearson_per_file` / `ratio_per_file` /
# `std_mv_per_file` (the three recording checks). The 08c generic checks emit
# SCALARS only and no per-file dimension at all.
# ---------------------------------------------------------------------------

_LIST_PER_FILE = [
    {"file_index": 3, "metric_value": 1, "passed": False, "io_error": None},
    {"file_index": 10, "metric_value": 30, "passed": True, "io_error": None},
]
_PEEK_COMMON = {"n_files_attempted": 2, "n_files_io_failed": 0, "peek_samples_requested": 100000}

CHECK_METRICS: dict[str, dict[str, object]] = {
    "output_diversity": {"per_file": _LIST_PER_FILE, "threshold": 25, **_PEEK_COMMON},
    "output_std": {"per_file": _LIST_PER_FILE, "threshold_mv": 1.0, **_PEEK_COMMON},
    "amplitude_collapse": {"per_file": _LIST_PER_FILE, "threshold": 0.95, **_PEEK_COMMON},
    "pearson_dispersion": {
        "pearson_per_file": {"3": 0.048, "10": 0.002},
        "pearson_dispersion": 0.0325,
        "pearson_mean": 0.025,
        "peek_samples_requested": 1000000,
    },
    "spectral_peak_ratio": {
        "ratio_per_file": {"3": 12.5, "10": 3.25},
        "ratio_mean": 7.875,
        "peek_samples_requested": 1000000,
    },
    "per_file_output_std": {
        "std_mv_per_file": {"3": 6.4, "10": 0.05},
        "std_mv_mean": 3.225,
        "std_mv_min": 0.05,
        "std_mv_max": 6.4,
        "peek_samples_requested": 100000,
    },
    # The real preserved D14 Pets collapse: 370 predictions, 2 of 37 classes,
    # dominant 369/370 (08c child design §2.5).
    "categorical_distinct_symbols": {
        "n_samples": 370,
        "distinct_symbols": 2,
        "symbol_cardinality": 37,
        "occupancy": 2 / 37,
        "min_distinct_symbols": 5,
    },
    "categorical_dominant_fraction": {
        "n_samples": 370,
        "dominant_symbol": 5,
        "dominant_fraction": 369 / 370,
        "symbol_cardinality": 37,
        "max_dominant_fraction": 0.95,
    },
    "sample_dispersion_floor": {
        "dispersion": 0.0005,
        "mean": 0.5,
        "min_dispersion": 0.04,
        "n_samples": 5160960,
    },
}


# ---------------------------------------------------------------------------
# GOLDEN 1 — TIDMAD persisted evidence (hop 1). HARDCODED at d44f6f6a.
#
# Note the THREE legitimate `threshold: None` rows: the recording-only checks
# declare `threshold_parameter_names=()` and correctly persist no threshold.
# P4 must PRESERVE those absences, not "complete" them.
# ---------------------------------------------------------------------------

TIDMAD_THRESHOLD_GOLDEN: dict[str, dict[str, object] | None] = {
    "output_diversity_blocking": {
        "metric": "n_unique_int8_values",
        "operator": ">",
        "value": 25,
        "unit": "count",
    },
    "output_std_blocking": {
        "metric": "output_std_mv",
        "operator": ">=",
        "value": 1.0,
        "unit": "mV",
    },
    "amplitude_collapse_blocking": {
        "metric": "dominant_mode_fraction",
        "operator": "<=",
        "value": 0.95,
        "unit": "fraction",
    },
    "pearson_dispersion_recording": None,
    "spectral_peak_ratio_recording": None,
    "per_file_output_std_recording": None,
}

#: gate id -> (per-file metric NAME, per-file UNIT, sampling-method label).
TIDMAD_PER_FILE_GOLDEN: dict[str, tuple[str, str, str]] = {
    "output_diversity_blocking": ("n_unique_int8_values", "count", "channel0001_prefix_peek"),
    "output_std_blocking": ("output_std_mv", "mV", "channel0001_prefix_peek"),
    "amplitude_collapse_blocking": (
        "dominant_mode_fraction",
        "fraction",
        "channel0001_prefix_peek",
    ),
    "pearson_dispersion_recording": (
        "pearson_correlation",
        "correlation",
        "channel0001_prefix_peek",
    ),
    "spectral_peak_ratio_recording": ("spectral_peak_ratio", "ratio", "channel0001_prefix_peek"),
    "per_file_output_std_recording": ("output_std_mv", "mV", "channel0001_prefix_peek"),
}

# ---------------------------------------------------------------------------
# GOLDEN 2 — TIDMAD LLM-facing evidence (hop 2). HARDCODED at d44f6f6a.
#
# `n_unique_int8_values=1` renders as an INTEGER because its unit is "count"
# (the L2 exactness literal); the others bucket to 2 significant figures.
# The three recording gates have no threshold row, so they carry no
# fingerprint — which is correct and must stay true.
# ---------------------------------------------------------------------------

TIDMAD_FINGERPRINT_GOLDEN: dict[str, str | None] = {
    "output_diversity_blocking": "output_diversity_blocking:n_unique_int8_values=1",
    "output_std_blocking": "output_std_blocking:output_std_mv=1",
    "amplitude_collapse_blocking": "amplitude_collapse_blocking:dominant_mode_fraction=30",
    "pearson_dispersion_recording": None,
    "spectral_peak_ratio_recording": None,
    "per_file_output_std_recording": None,
}

TIDMAD_KEY_METRICS_GOLDEN: dict[str, dict[str, float]] = {
    "output_diversity_blocking": {"n_unique_int8_values": 1},
    "output_std_blocking": {"output_std_mv": 1.0},
    "amplitude_collapse_blocking": {"dominant_mode_fraction": 30.0},
    "pearson_dispersion_recording": {"pearson_dispersion": 0.0325, "pearson_mean": 0.025},
    "spectral_peak_ratio_recording": {"ratio_mean": 7.875},
    "per_file_output_std_recording": {
        "std_mv_max": 6.4,
        "std_mv_mean": 3.225,
        "std_mv_min": 0.05,
    },
}

# ---------------------------------------------------------------------------
# GOLDEN 3 — THE DEFECT, recorded before the fix.
#
# Every contrast-task gate today: no threshold row (hop 1), therefore no
# fingerprint (hop 2). `per_file` is legitimately empty for all three — these
# checks have no per-file dimension — and must stay empty.
#
#   C2  flips `threshold_is_none`  -> False   (the row becomes complete)
#   C3' flips `fingerprint_is_none`-> False   (the fingerprint appears)
#
# Each flip is a deliberate edit recorded in the P4 design ledger.
# ---------------------------------------------------------------------------

CONTRAST_BASELINE_IS_BLANK: dict[str, dict[str, bool]] = {
    # C2 flipped the hop-1 half (a complete threshold row rendered from the
    # check's own declaration); C3' flipped the hop-2 half (the worst-case
    # direction derived from the declared operator instead of looked up in a
    # per-metric-name map). The defect this module was written to witness is
    # now closed at BOTH hops, on all three contrast gates.
    "pets_distinct_symbols_blocking": {"threshold_is_none": False, "fingerprint_is_none": False},
    "pets_dominant_fraction_blocking": {"threshold_is_none": False, "fingerprint_is_none": False},
    "davis_dispersion_blocking": {"threshold_is_none": False, "fingerprint_is_none": False},
}

#: The fingerprints C3' produced, hardcoded. These signatures did not exist
#: before P4 — the contrast tasks had none at all.
CONTRAST_FINGERPRINT_AFTER_C3: dict[str, str] = {
    "pets_distinct_symbols_blocking": "pets_distinct_symbols_blocking:distinct_symbols=2",
    "pets_dominant_fraction_blocking": "pets_dominant_fraction_blocking:dominant_fraction=1",
    "davis_dispersion_blocking": "davis_dispersion_blocking:dispersion=0.0005",
}

#: The rows C2 produced, hardcoded. DAVIS renders NO unit: it declares no
#: `value_scale`, and R-2 says an unresolvable task-owned unit renders nothing
#: rather than a defaulted one.
CONTRAST_THRESHOLD_AFTER_C2: dict[str, dict[str, object]] = {
    "pets_distinct_symbols_blocking": {
        "metric": "distinct_symbols",
        "operator": ">=",
        "value": 5,
        "unit": "count",
    },
    "pets_dominant_fraction_blocking": {
        "metric": "dominant_fraction",
        "operator": "<=",
        "value": 0.95,
        "unit": "fraction",
    },
    "davis_dispersion_blocking": {
        "metric": "dispersion",
        "operator": ">=",
        "value": 0.04,
        "unit": None,
    },
}


# ---------------------------------------------------------------------------
# Probe harness
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_run_scope():
    """Snapshot both registries and reset run scope, as the 08c rung does."""
    from execute_tools.health_checks import _plugin_binding
    from execute_tools.health_checks.registry import _PROVIDER_REGISTRY, _REGISTRY

    checks = dict(_REGISTRY)
    providers = dict(_PROVIDER_REGISTRY)
    _plugin_binding.reset_run_scope()
    try:
        yield
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(checks)
        _PROVIDER_REGISTRY.clear()
        _PROVIDER_REGISTRY.update(providers)
        _plugin_binding.reset_run_scope()


def _context() -> HealthCheckContext:
    return HealthCheckContext(
        model_name="m",
        run_name="r",
        round_index=1,
        denoised_filename_fn=lambda index: f"/nonexistent/denoised_{index:04d}.h5",
    )


def _persist_every_gate(binding: str | None) -> dict[str, object]:
    """Drive the PRODUCTION evidence builder once per composed gate.

    ``binding is None`` OMITS the argument: that is 08b's ``LEGACY_OMITTED``
    state (resolves to TIDMAD), which is NOT the same as passing ``None``
    explicitly (``EXPLICIT_NONE``, a named absence).
    """
    if binding is None:
        composed, _task_config, _ = load_composed_health_config(None)
    else:
        composed, _task_config, _ = load_composed_health_config(None, binding)

    persisted: dict[str, object] = {}
    for gate in composed.health_gates:
        check_name = gate.checks[0].name
        result = GateResult(
            gate_id=gate.id,
            round_index=1,
            passed=False,
            action=GateAction.CONTINUE,
            failure_reason=f"{check_name}: synthetic",
            check_results=[
                HealthCheckResult(
                    check_name=check_name,
                    passed=False,
                    reason=f"{check_name}: synthetic",
                    metrics=dict(CHECK_METRICS[check_name]),
                    verdict=CheckVerdict.FAILED,
                )
            ],
        )
        persisted[gate.id] = evaluation._persist(result, gate, None, _context(), 0.0, None)
    return persisted


def _fingerprint_and_key_metrics(persisted) -> tuple[str | None, dict]:
    """Hop 2: the same call the interpreter makes at evidence.py:267-268."""
    from agent.schemas.health_feedback import (
        build_collapse_fingerprint,
        build_gate_outcomes,
    )

    dumped = json.loads(persisted.model_dump_json())
    fingerprint = build_collapse_fingerprint([dumped], "invalidate_round")
    outcomes = build_gate_outcomes([dumped])
    return (
        fingerprint.signature if fingerprint is not None else None,
        outcomes[0].key_metrics if outcomes else {},
    )


# ---------------------------------------------------------------------------
# TIDMAD parity — what P4 must not move
# ---------------------------------------------------------------------------


class TestTidmadEvidenceBaseline:
    def test_threshold_rows_match_the_frozen_golden(self):
        """Includes the three legitimate absences; P4 preserves both halves."""
        persisted = _persist_every_gate(None)
        actual = {gate_id: p.threshold for gate_id, p in persisted.items()}
        assert actual == TIDMAD_THRESHOLD_GOLDEN

    def test_the_three_recording_gates_persist_no_threshold(self):
        """Named separately: a migration that 'completes' these is WRONG.

        They declare ``threshold_parameter_names=()`` and their absence is the
        honest shape, not a gap to fill.
        """
        persisted = _persist_every_gate(None)
        recording = [
            "pearson_dispersion_recording",
            "spectral_peak_ratio_recording",
            "per_file_output_std_recording",
        ]
        assert [persisted[g].threshold for g in recording] == [None, None, None]

    def test_per_file_naming_units_and_sampling_label_match_the_golden(self):
        persisted = _persist_every_gate(None)
        for gate_id, (name, unit, sampling) in TIDMAD_PER_FILE_GOLDEN.items():
            rows = persisted[gate_id].metrics["per_file"]
            assert set(rows) == {"3", "10"}, gate_id
            for key, row in rows.items():
                assert row["sampling_method"] == sampling, (gate_id, key)
                assert list(row["metrics"]) == [name], (gate_id, key)
                assert row["metrics"][name]["unit"] == unit, (gate_id, key)

    def test_fingerprint_signatures_match_the_frozen_golden(self):
        persisted = _persist_every_gate(None)
        actual = {gid: _fingerprint_and_key_metrics(p)[0] for gid, p in persisted.items()}
        assert actual == TIDMAD_FINGERPRINT_GOLDEN

    def test_key_metrics_match_the_frozen_golden(self):
        persisted = _persist_every_gate(None)
        actual = {gid: _fingerprint_and_key_metrics(p)[1] for gid, p in persisted.items()}
        assert actual == TIDMAD_KEY_METRICS_GOLDEN

    def test_count_unit_renders_exact_and_others_bucket(self):
        """The L2 exactness literal, pinned by its observable consequence.

        ``n_unique_int8_values`` has unit "count" and renders as an integer;
        ``output_std_mv`` (mV) and ``dominant_mode_fraction`` (fraction) go
        through 2-significant-figure bucketing. C3' must preserve this while
        deriving exactness from the DECLARED unit instead of a literal
        comparison in another module.
        """
        persisted = _persist_every_gate(None)
        assert _fingerprint_and_key_metrics(persisted["output_diversity_blocking"])[0].endswith(
            "=1"
        )
        assert _fingerprint_and_key_metrics(persisted["amplitude_collapse_blocking"])[0].endswith(
            "=30"
        )


# ---------------------------------------------------------------------------
# The defect witness
# ---------------------------------------------------------------------------


class TestContrastTaskEvidenceIsBlankAtBase:
    """Pets and DAVIS route through the SAME generic evidence builder and get
    silently poorer evidence, at both hops. This is the defect P4 removes."""

    @pytest.mark.parametrize("binding", [str(PETS_BINDING), str(DAVIS_BINDING)])
    def test_contrast_gates_are_blank_at_both_hops(self, binding):
        persisted = _persist_every_gate(binding)
        assert persisted, "no gates composed — the binding did not resolve"
        for gate_id, p in persisted.items():
            expected = CONTRAST_BASELINE_IS_BLANK[gate_id]
            fingerprint, _key_metrics = _fingerprint_and_key_metrics(p)
            assert (p.threshold is None) is expected["threshold_is_none"], gate_id
            assert (fingerprint is None) is expected["fingerprint_is_none"], gate_id

    @pytest.mark.parametrize("binding", [str(PETS_BINDING), str(DAVIS_BINDING)])
    def test_contrast_threshold_rows_are_complete_after_c2(self, binding):
        """The defect's hop-1 half, fixed: rendered from the check's own
        declaration, with the task's configured value and no source label."""
        persisted = _persist_every_gate(binding)
        for gate_id, p in persisted.items():
            assert p.threshold == CONTRAST_THRESHOLD_AFTER_C2[gate_id], gate_id
            assert "source" not in p.threshold, gate_id

    @pytest.mark.parametrize("binding", [str(PETS_BINDING), str(DAVIS_BINDING)])
    def test_contrast_fingerprints_are_complete_after_c3(self, binding):
        """The defect's hop-2 half, fixed. The worst value of a SCALAR check
        is the single value it published under the declared metric name —
        these checks have no per-file dimension, so `aggregate_statistics` is
        empty and a derivation that only read it would still have produced
        nothing."""
        persisted = _persist_every_gate(binding)
        for gate_id, p in persisted.items():
            signature, _ = _fingerprint_and_key_metrics(p)
            assert signature == CONTRAST_FINGERPRINT_AFTER_C3[gate_id], gate_id

    @pytest.mark.parametrize("binding", [str(PETS_BINDING), str(DAVIS_BINDING)])
    def test_contrast_gates_have_no_per_file_dimension(self, binding):
        """Legitimately empty — these checks emit scalars. P4 must NOT invent
        per-file rows for them; only the threshold row is the defect."""
        persisted = _persist_every_gate(binding)
        for gate_id, p in persisted.items():
            assert p.metrics["per_file"] == {}, gate_id
            assert p.metrics["aggregate_statistics"] == {"count": 0}, gate_id

    def test_the_blank_baseline_covers_every_composed_contrast_gate(self):
        """Anti-vacuity: the witness must name every gate both packs compose,
        so a pack gaining a gate cannot slip past the recorded defect.

        ``reset_run_scope()`` between the two packs is REQUIRED, not
        incidental: Health check registration is process-global, and 08b's
        run-scope guard refuses to load a second, different plugin set in one
        process precisely so a run cannot evaluate another run's checks. The
        08c three-task rung resets between tasks for the same reason.
        """
        from execute_tools.health_checks import _plugin_binding

        composed = set(_persist_every_gate(str(PETS_BINDING)))
        _plugin_binding.reset_run_scope()
        composed |= set(_persist_every_gate(str(DAVIS_BINDING)))
        assert composed == set(CONTRAST_BASELINE_IS_BLANK)
