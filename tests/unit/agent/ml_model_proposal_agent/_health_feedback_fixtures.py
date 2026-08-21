"""Shared CB4 fixtures — strong structured-health interpretation payloads.

Built through the TYPED schemas and serialized with ``model_dump`` so
the proposer sees the real ``InterpretationOutput`` serialization shape,
never a hand-simplified dict (CB4 spec §4). Two models with fully
disjoint evidence so contamination, mis-attribution, wrong counts, or
dropped iteration tags are all detectable:

* ``model_a`` — output-diversity collapse; history with MULTIPLE
  retained occurrence buckets (iterations 3 and 5) whose summed
  retained count (3) differs from any single bucket, plus bounded
  source exp_ids; representative raw metrics.
* ``model_b`` — output-std collapse; different counts; single
  occurrence bucket; no overlap with model_a.

Also carries a §14.N ``GateExhaustionInfo`` so the gate-exhaustion
block's unchanged rendering is pinned by the same fixture.
"""

from agent.schemas.health_feedback import (
    CollapseFingerprint,
    CollapseFingerprintHistoryEntry,
    FingerprintOccurrence,
)
from agent.schemas.hyperparam_tuning import GateExhaustionInfo
from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.proposal import ProposalInput
from agent.schemas.proposer_evidence import build_proposer_evidence
from agent.schemas.storage import LocalStorageConfig, StorageConfig

SIG_A = "output_diversity_blocking:n_unique_int8_values=1"
SIG_B = "output_std_blocking:output_std_mv=0"

FP_A = CollapseFingerprint(
    check_name="output_diversity_blocking",
    signature=SIG_A,
    metrics={"n_unique_int8_values": 1},
    human_readable="output collapsed to a single int8 value",
)
FP_B = CollapseFingerprint(
    check_name="output_std_blocking",
    signature=SIG_B,
    metrics={"output_std_mv": 0.0431},
    human_readable="output std collapsed below 1 mV",
)

HISTORY_A = CollapseFingerprintHistoryEntry(
    signature=SIG_A,
    check_name="output_diversity_blocking",
    metrics={"n_unique_int8_values": 1},  # representative observation (latest)
    human_readable="output collapsed to a single int8 value",
    occurrences=[
        FingerprintOccurrence(
            iteration=3, count=2, source_exp_ids=["model_a_iter_003_002", "model_a_iter_003_004"]
        ),
        FingerprintOccurrence(iteration=5, count=1, source_exp_ids=["model_a_iter_005_001"]),
    ],
)
HISTORY_B = CollapseFingerprintHistoryEntry(
    signature=SIG_B,
    check_name="output_std_blocking",
    metrics={"output_std_mv": 0.0431},
    human_readable="output std collapsed below 1 mV",
    occurrences=[
        FingerprintOccurrence(iteration=5, count=1, source_exp_ids=["model_b_iter_005_003"]),
    ],
)


def structured_interpretation_output() -> InterpretationOutput:
    """The typed CB3-shape output carrying full structured evidence."""
    return InterpretationOutput(
        model_types=["model_a", "model_b"],
        model_descriptions={"model_a": "Arch A.", "model_b": "Arch B."},
        total_experiments=7,
        best_denoising_score=1.9,
        worst_denoising_score=-0.4,
        key_findings=["model_a collapses on diversity.", "model_b collapses on std."],
        bottlenecks=["Mode collapse dominates."],
        take_home_message="Break the collapse mechanisms.",
        per_model_best={"model_a": 1.9, "model_b": 0.4},
        per_model_worst={"model_a": -0.4, "model_b": 0.1},
        per_model_round_health_counts={
            "model_a": {"valid": 0, "invalid": 1, "unknown": 1},
            "model_b": {"valid": 1, "invalid": 2, "unknown": 0},
        },
        per_model_collapse_fingerprints={"model_a": [FP_A], "model_b": [FP_B]},
        collapse_fingerprint_history={"model_a": [HISTORY_A], "model_b": [HISTORY_B]},
    )


def gate_exhaustion() -> GateExhaustionInfo:
    """§14.N fixture (mirrors test_recent_gate_exhaustions) — pins the
    exhaustion block's rendering alongside the new evidence."""
    return GateExhaustionInfo(
        total_attempts=9,
        vram_gated_attempts=7,
        time_gated_attempts=2,
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
        summary_message="All 9 attempts were rejected by the resource gate.",
    )


def strong_proposal_input(workspace: str, **overrides) -> ProposalInput:
    """ProposalInput carrying the proposer's TYPED evidence, plus §14.N data.

    The evidence is projected from the REAL ``model_dump`` of the typed
    structured output by the same ``build_proposer_evidence`` authority
    production uses, so these fixtures exercise the shape the protocol and the
    CLI actually produce. Step 10 / P3 C3 removed the raw ``interpretation``
    dict from ``ProposalInput`` entirely; there is no second carrier to keep in
    sync any more. The health flag is not set here — tests choose it.
    """
    dump = structured_interpretation_output().model_dump(mode="json")
    base = dict(
        interpretation_evidence=build_proposer_evidence(dump),
        existing_model_types=["model_a", "model_b"],
        recent_gate_exhaustions=[gate_exhaustion()],
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=workspace, run_name="cb4"),
        ),
    )
    base.update(overrides)
    return ProposalInput(**base)
