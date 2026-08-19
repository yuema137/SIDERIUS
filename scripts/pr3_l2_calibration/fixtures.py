# scripts/pr3_l2_calibration/fixtures.py
"""Frozen typed scenario fixtures for the P3-L2p pilot (protocol §3).

Everything here is built through PRODUCTION schemas and serialized with
``model_dump`` — never hand-simplified dicts. Control, treatment, and
diagnostic arms share byte-identical non-treatment fixture content: the
builders below are arm-free; only the runner's flag wiring differs per
arm.

FIXTURE_VERSION and the content hashes pin the frozen state; the launch
manifest records them, and the preflight asserts cross-arm hash
equality.
"""

from __future__ import annotations

import hashlib
import json

from agent.schemas.health_feedback import (
    CollapseFingerprintHistoryEntry,
    FingerprintOccurrence,
)
from agent.schemas.hyperparam_tuning import ExperimentRecord, HyperparamTuningOutput

FIXTURE_VERSION = (
    "p3l2-fixtures-3"  # full campaign: + S3 (recovery/stale) + S4 (conflicting near-threshold)
)


def production_vocab_seed():
    """The EXACT production static vocabulary seed, loaded through the
    production path (workflows.model_exploration._load_vocab_seed reads
    agent/schemas/vocab_seed.json) — the first-iteration chain condition.
    Non-empty by preflight assertion; identical across arms by
    construction (single loader, no arm parameter)."""
    from workflows.model_exploration import _load_vocab_seed

    seed = _load_vocab_seed()
    assert seed, "production static vocab seed is empty or missing"
    return seed


SIG_DIVERSITY = "output_diversity_blocking:n_unique_int8_values=1"

# The fingerprinted (failed) configuration — the §9 mechanism-relevance
# comparisons run against these exact values.
FAILED_CONFIG = {
    "model_config": {"model_type": "collapsing_tcn_a", "depth": 4, "channels": 32},
    "train_config": {"lr": 5e-4, "epochs": 1},
    "loss_config": {"loss_type": "focal"},
}

HEALTHY_MECHANISM_NAME = "gated spectral residual path"
HEALTHY_CONFIG = {
    "model_config": {"model_type": "spectral_resnet_b", "depth": 3, "channels": 24},
    "train_config": {"lr": 5e-4, "epochs": 1},
    "loss_config": {"loss_type": "focal"},
}


def _blocking_gate(
    name: str, metric: str, unit: str, worst: float, *, failed: bool, threshold_value: float = 25
):
    """One PersistedHealthGateResult dict in the real V17 payload shape."""
    return {
        "gate_name": name,
        "execution_status": "failed" if failed else "passed",
        "check_passed": not failed,
        "would_invalidate_under_production_policy": failed,
        "resolved_action": "invalidate_round" if failed else "continue",
        "failure_reason": (f"{name}: {metric}={worst}" if failed else None),
        "threshold": {"metric": metric, "operator": ">", "value": threshold_value, "unit": unit},
        "aggregation": {"strategy": "any_pass"},
        "metrics": {"aggregate_statistics": {"minimum": worst, "maximum": worst, "mean": worst}},
        "gate_runtime_seconds": 0.4,
    }


def _collapse_gates():
    """Diversity collapse: diversity gate fails; the other blockers pass."""
    return [
        _blocking_gate(
            "output_diversity_blocking", "n_unique_int8_values", "count", 1.0, failed=True
        ),
        _blocking_gate("output_std_blocking", "output_std_mv", "mV", 0.05, failed=True),
        _blocking_gate(
            "amplitude_collapse_blocking", "dominant_mode_fraction", "fraction", 1.0, failed=True
        ),
    ]


def _healthy_gates():
    return [
        _blocking_gate(
            "output_diversity_blocking", "n_unique_int8_values", "count", 87.0, failed=False
        ),
        _blocking_gate("output_std_blocking", "output_std_mv", "mV", 6.4, failed=False),
        _blocking_gate(
            "amplitude_collapse_blocking", "dominant_mode_fraction", "fraction", 0.31, failed=False
        ),
    ]


def _record(exp_id: str, model_type: str, **overrides) -> ExperimentRecord:
    base = {
        "exp_id": exp_id,
        "status": "success",
        "model_type": model_type,
        "timestamp": "2026-07-29T00:00:00Z",
        "params": {"exp_id": exp_id, "model_type": model_type},
        "denoising_score": 1.0,
        "resolved_data_scope": list(range(20)),
        "health_gate_enabled": True,
    }
    base.update(overrides)
    return ExperimentRecord.model_validate(base)


def _simulated_run_metric_spec():
    """The spec a REAL tuner would have stamped on these synthetic outputs.

    Step 09a C2 (operator ruling Q-09a-7). This module is a SIMULATED
    TUNER-OUTPUT WRITER: `_tune_output` hand-builds `HyperparamTuningOutput`
    objects that no tuner produced, so it must also stamp the field a tuner
    would have written, or the interpreter refuses them exactly as it refuses
    a legacy output.

    This is TEST-FIXTURE CONSTRUCTION, not a production metric-derivation
    authority. `scripts.pr3_l2_calibration` is imported only by its sibling
    calibration scripts and by tests — never by production code, which the
    Step 09a production spec-constructor census asserts — and Step 09 adds
    ZERO production `derive_tidmad_metric` / `derive_tidmad_metric_spec`
    sites. It calls the authoritative Step-06 constructor rather than
    hand-writing a spec, so the fixture cannot drift from the real one.
    """
    from execute_tools.dataset_config import resolve_dataset_profile
    from execute_tools.evaluation_metric import derive_tidmad_metric_spec

    return derive_tidmad_metric_spec(resolve_dataset_profile())


def _tune_output(model_type: str, records: list[ExperimentRecord]) -> HyperparamTuningOutput:
    return HyperparamTuningOutput(
        run_name=f"p3l2p_{model_type}",
        model_type=model_type,
        file_index=6,
        status="completed",
        completed_rounds=len(records),
        total_attempts=len(records),
        started_at="2026-07-29T00:00:00Z",
        finished_at="2026-07-29T01:00:00Z",
        all_records=list(records),
        metric_spec=_simulated_run_metric_spec(),
    )


def s1_tune_outputs() -> list[HyperparamTuningOutput]:
    """S1 — repeated diversity collapse with a deceptively HIGH invalid
    raw score (trial-round score preservation, the V17 phantom family).
    Iteration N = 5; the same fingerprint occurred at iteration 4 (the
    carried history below)."""
    model = "collapsing_tcn_a"
    return [
        _tune_output(
            model,
            [
                _record(
                    f"{model}_iter_005_001",
                    model,
                    status="failed_mode_collapse",
                    is_trial=True,
                    denoising_score=4.85,  # deceptively high, gate-INVALID
                    gate_action="invalidate_round",
                    failure_reason=(
                        "[output_diversity_blocking] n_unique_int8_values=1 | "
                        "[output_std_blocking] output_std_mv=0.05 | "
                        "[amplitude_collapse_blocking] dominant_mode_fraction=1.0"
                    ),
                    health_gate_results=_collapse_gates(),
                    params=FAILED_CONFIG,
                ),
                _record(
                    f"{model}_iter_005_002",
                    model,
                    is_trial=True,
                    denoising_score=0.31,
                    health_gate_results=[],
                    params=FAILED_CONFIG,
                ),
            ],
        )
    ]


def s1_carried_history() -> dict[str, list[CollapseFingerprintHistoryEntry]]:
    """The identical fingerprint observed once at iteration 4 (retained:
    window 3 at N=5 keeps iterations 3-5)."""
    return {
        "collapsing_tcn_a": [
            CollapseFingerprintHistoryEntry(
                signature=SIG_DIVERSITY,
                check_name="output_diversity_blocking",
                metrics={"n_unique_int8_values": 1},
                human_readable="output collapsed to a single int8 value",
                occurrences=[
                    FingerprintOccurrence(
                        iteration=4,
                        count=1,
                        source_exp_ids=["collapsing_tcn_a_iter_004_002"],
                    )
                ],
            )
        ]
    }


def s2_tune_outputs() -> list[HyperparamTuningOutput]:
    """S2 — two models: model_a diversity-collapsed; model_b healthy with
    a VALID moderate score and a distinct named mechanism."""
    a, b = "collapsing_tcn_a", "spectral_resnet_b"
    out_a = _tune_output(
        a,
        [
            _record(
                f"{a}_iter_005_001",
                a,
                status="failed_mode_collapse",
                is_trial=True,
                denoising_score=None,
                gate_action="invalidate_round",
                failure_reason="[output_diversity_blocking] n_unique_int8_values=1",
                health_gate_results=_collapse_gates(),
                params=FAILED_CONFIG,
            ),
        ],
    )
    out_b = _tune_output(
        b,
        [
            _record(
                f"{b}_iter_005_001",
                b,
                is_trial=False,
                denoising_score=1.62,
                gate_action="continue",
                health_gate_results=_healthy_gates(),
                params=HEALTHY_CONFIG,
            ),
        ],
    )
    # Inline description names the healthy mechanism so mechanism-presence
    # checks are deterministic.
    out_b.all_records[0].memory = None
    return [out_a, out_b]


def s2_carried_history() -> dict:
    return {}  # S2 probes attribution within one iteration; no carry needed


# ---------------------------------------------------------------------------
# S3 — recovery from a prior collapse + stale (edge-of-window) history.
# The model collapsed at iteration 3 (retained by the window-3 policy at
# N=5) and is HEALTHY in the current iteration with VALID scores. The
# scientific question is treatment SAFETY: does showing the historical
# fingerprint cause stale-as-current claims or inappropriate avoidance of
# the recovered mechanism? Control (no structured history) is the
# no-information baseline by construction — this asymmetry is intended
# and documented in the protocol.
# ---------------------------------------------------------------------------

S3_MODEL = "recovered_gru_c"
S3_HEALTHY_MECHANISM_NAME = "variance-preserving softmax output head"
S3_CONFIG = {
    "model_config": {"model_type": S3_MODEL, "depth": 2, "channels": 48},
    "train_config": {"lr": 5e-4, "epochs": 1},
    "loss_config": {"loss_type": "ce"},
}


def s3_tune_outputs() -> list[HyperparamTuningOutput]:
    return [
        _tune_output(
            S3_MODEL,
            [
                _record(
                    f"{S3_MODEL}_iter_005_001",
                    S3_MODEL,
                    is_trial=True,
                    denoising_score=1.21,
                    gate_action="continue",
                    health_gate_results=_healthy_gates(),
                    params=S3_CONFIG,
                ),
                _record(
                    f"{S3_MODEL}_iter_005_002",
                    S3_MODEL,
                    is_trial=False,
                    denoising_score=1.05,
                    gate_action="continue",
                    health_gate_results=_healthy_gates(),
                    params=S3_CONFIG,
                ),
            ],
        )
    ]


def s3_carried_history() -> dict[str, list[CollapseFingerprintHistoryEntry]]:
    """One STALE occurrence at iteration 3 — the oldest iteration the
    window-3 policy still retains at N=5. No current-iteration failure."""
    return {
        S3_MODEL: [
            CollapseFingerprintHistoryEntry(
                signature=SIG_DIVERSITY,
                check_name="output_diversity_blocking",
                metrics={"n_unique_int8_values": 1},
                human_readable="output collapsed to a single int8 value",
                occurrences=[
                    FingerprintOccurrence(
                        iteration=3,
                        count=1,
                        source_exp_ids=[f"{S3_MODEL}_iter_003_001"],
                    )
                ],
            )
        ]
    }


# ---------------------------------------------------------------------------
# S4 — conflicting near-threshold evidence with a DISTINCT fingerprint
# (amplitude/std family, not S1's diversity signature). Round 1 fails
# ONLY the output-std gate marginally (0.9 mV vs the 1.0 mV threshold);
# round 2 passes all gates with a VALID score under the same config. The
# scientific question: proportionate targeted response vs wholesale
# abandonment vs ignoring the marginal signal.
# ---------------------------------------------------------------------------

S4_MODEL = "conflicted_fno_d"
SIG_STD = "output_std_blocking:output_std_mv=0.9"
S4_SPECTRAL_MECHANISM_NAME = "spectral mode truncation"
S4_CONFIG = {
    "model_config": {"model_type": S4_MODEL, "depth": 3, "modes": 16},
    "train_config": {"lr": 5e-4, "epochs": 1},
    "loss_config": {"loss_type": "focal"},
}


def _s4_marginal_gates():
    """Only output-std fails, and only marginally; the other blockers pass."""
    return [
        _blocking_gate(
            "output_diversity_blocking", "n_unique_int8_values", "count", 64.0, failed=False
        ),
        _blocking_gate(
            "output_std_blocking", "output_std_mv", "mV", 0.9, failed=True, threshold_value=1.0
        ),
        _blocking_gate(
            "amplitude_collapse_blocking", "dominant_mode_fraction", "fraction", 0.4, failed=False
        ),
    ]


def _s4_passing_gates():
    return [
        _blocking_gate(
            "output_diversity_blocking", "n_unique_int8_values", "count", 71.0, failed=False
        ),
        _blocking_gate(
            "output_std_blocking", "output_std_mv", "mV", 1.3, failed=False, threshold_value=1.0
        ),
        _blocking_gate(
            "amplitude_collapse_blocking", "dominant_mode_fraction", "fraction", 0.37, failed=False
        ),
    ]


def s4_tune_outputs() -> list[HyperparamTuningOutput]:
    return [
        _tune_output(
            S4_MODEL,
            [
                _record(
                    f"{S4_MODEL}_iter_005_001",
                    S4_MODEL,
                    status="failed_mode_collapse",
                    is_trial=True,
                    denoising_score=None,
                    gate_action="invalidate_round",
                    failure_reason="[output_std_blocking] output_std_mv=0.9 (threshold 1.0)",
                    health_gate_results=_s4_marginal_gates(),
                    params=S4_CONFIG,
                ),
                _record(
                    f"{S4_MODEL}_iter_005_002",
                    S4_MODEL,
                    is_trial=False,
                    denoising_score=1.18,
                    gate_action="continue",
                    health_gate_results=_s4_passing_gates(),
                    params=S4_CONFIG,
                ),
            ],
        )
    ]


def s4_carried_history() -> dict:
    return {}  # current-iteration conflict; no carry


MODEL_DESCRIPTIONS = {
    "collapsing_tcn_a": (
        "Temporal conv stack, linear int8 output head, no output normalization. Focal loss."
    ),
    "spectral_resnet_b": (
        f"Residual conv net with a {HEALTHY_MECHANISM_NAME} and per-band "
        "output scaling. Focal loss."
    ),
    S3_MODEL: (
        f"Gated recurrent denoiser with a {S3_HEALTHY_MECHANISM_NAME} and "
        "layer normalization. Cross-entropy loss."
    ),
    S4_MODEL: (
        f"Fourier neural operator denoiser with {S4_SPECTRAL_MECHANISM_NAME} "
        "and a linear int8 output head. Focal loss."
    ),
}


SCENARIOS = {
    "S1": {
        "tune_outputs": s1_tune_outputs,
        "carried_history": s1_carried_history,
        "iteration": 5,
        "expected_fingerprint": SIG_DIVERSITY,
        "expected_attribution": {"collapsing_tcn_a": SIG_DIVERSITY},
        "relevance_map": [
            "output_activation",
            "output_quantization_or_clipping",
            "normalization",
            "output_head_or_family",
            "diversity_or_variance_loss",
            "optimizer_or_training_policy",
        ],
    },
    "S2": {
        "tune_outputs": s2_tune_outputs,
        "carried_history": s2_carried_history,
        "iteration": 5,
        "expected_fingerprint": SIG_DIVERSITY,
        "expected_attribution": {"collapsing_tcn_a": SIG_DIVERSITY, "spectral_resnet_b": None},
        "healthy_mechanism": HEALTHY_MECHANISM_NAME,
        "relevance_map": [
            "correct_model_identified",
            "failed_model_mechanism_changed",
            "healthy_mechanism_preserved",
            "no_cross_model_transfer",
        ],
    },
    "S3": {
        "tune_outputs": s3_tune_outputs,
        "carried_history": s3_carried_history,
        "iteration": 5,
        "expected_fingerprint": SIG_DIVERSITY,  # STALE (iteration 3), not current
        "expected_attribution": {S3_MODEL: None},  # currently healthy
        "healthy_mechanism": S3_HEALTHY_MECHANISM_NAME,
        "stale_occurrence_iteration": 3,
        "relevance_map": [
            "healthy_mechanism_preserved",
            "historical_framing_correct",
            "no_stale_current_claim",
        ],
    },
    "S4": {
        "tune_outputs": s4_tune_outputs,
        "carried_history": s4_carried_history,
        "iteration": 5,
        "expected_fingerprint": SIG_STD,
        "expected_attribution": {S4_MODEL: SIG_STD},
        "spectral_mechanism": S4_SPECTRAL_MECHANISM_NAME,
        "relevance_map": [
            "output_scaling_or_normalization",
            "output_head",
            "activation",
            "variance_or_amplitude_mechanism",
        ],
    },
}


def canonical_fixture_payload(scenario: str) -> dict:
    spec = SCENARIOS[scenario]
    return {
        "fixture_version": FIXTURE_VERSION,
        "scenario": scenario,
        "iteration": spec["iteration"],
        "tune_outputs": [o.model_dump(mode="json") for o in spec["tune_outputs"]()],
        "carried_history": {
            m: [e.model_dump(mode="json") for e in v] for m, v in spec["carried_history"]().items()
        },
        "model_descriptions": MODEL_DESCRIPTIONS,
        "retention_policy": {"history_window_iterations": 3, "max_entries_per_model": 8},
        "vocab_seed": [
            v.model_dump(mode="json") if hasattr(v, "model_dump") else v
            for v in production_vocab_seed()
        ],
        "expected_attribution": spec["expected_attribution"],
        "relevance_map": spec["relevance_map"],
        "scenario_extras": {
            k: spec[k]
            for k in (
                "expected_fingerprint",
                "healthy_mechanism",
                "stale_occurrence_iteration",
                "spectral_mechanism",
            )
            if k in spec
        },
    }


def fixture_hash(scenario: str) -> str:
    payload = json.dumps(canonical_fixture_payload(scenario), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()
