# agent/schemas/proposer_evidence.py
"""The proposer's view of an interpretation — ONE typed value, ONE projection.

Step 10 / P3 (design §4.1 / §4.2; parent §11.2, operator ruling 2026-08-20).

The problem this replaces
-------------------------
The proposer received ``ProposalInput.interpretation: dict[str, Any]`` — the
upstream node's ENTIRE ``model_dump()`` — and two independent readers mined it
with ``.get()``: the production pipeline and the legacy/standalone renderer.
Nothing declared what the proposer actually consumes, so the two readers
drifted (each reads live fields the other never sees), a new evidence field had
to be wired into both, and the whitelist that decides what reaches the LLM was
pinned by no test.

Parent §11.2 makes the fix an executable rule: **no new evidence field may ever
again need wiring into two readers.** Both entrypoints call
:func:`build_proposer_evidence` and consume
:class:`ProposerInterpretationEvidence`; nothing else mines the mapping.

This is a CONSUMER VIEW, not a copy of the producer
---------------------------------------------------
The field set is the MEASURED live-read union — 30 of
``InterpretationOutput``'s 42 fields. Twelve upstream fields are deliberately
NOT carried because no proposer consumer reads them, and two names the legacy
renderer used to ask for (``per_file_comparison``, ``efficiency_comparison``)
were never declared by the producer at all — dead reads, dropped rather than
fabricated into a contract. That asymmetry is the proof this is a boundary
rather than a mirror: a field arrives here only when something reads it.

Absence semantics are load-bearing
-----------------------------------
Every optional field is ``| None`` where **None means "the key was absent from
the dump"**, never coalesced to an empty container. The pipeline's whitelist
filters on ``is not None``, so a present-but-empty ``{}`` renders and an absent
key is omitted — different bytes. The standalone CLI loads persisted artifacts
from old workspaces where that difference is real, so collapsing the two would
silently change what an operator's legacy run shows the model.

Failure policy
--------------
* **Absent key** → the documented per-field absence value. Today's ``.get()``
  tolerance, preserved deliberately: a legacy artifact must still render.
* **Present but malformed** → ``ValidationError``, fail-closed. A declared
  UPGRADE over the previous behaviour, where a malformed value flowed silently
  into prompt text the LLM then reasoned from.
* **``metric_identity``** is the ONE exception, and it is not a local choice:
  :func:`~execute_tools.evaluation_metric.metric_identity_from_mapping` is the
  single validator for a transported metric identity, and its frozen contract
  (P2a, Q-10-2) returns ``None`` for a missing, malformed or unknown-direction
  payload — a NAMED absence. A consumer in that state shows raw values and
  refuses to rank; it never crashes and never guesses a direction.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent.schemas.health_feedback import CollapseFingerprint, CollapseFingerprintHistoryEntry
from agent.schemas.score_table import ScoreComparisonTable
from execute_tools.evaluation_metric import MetricIdentityKey, metric_identity_from_mapping

#: Fields present on ``InterpretationOutput`` that this view deliberately does
#: NOT carry, each with the reason it is refused. Kept as data so the boundary
#: is reviewable and so a future field addition has to answer the same
#: question: *which proposer consumer reads it?*
#:
#: ``per_model_secondary_metrics`` is the RESERVED name (Q-P3-3 =
#: NO_RAW_SECONDARY_CONSUMPTION, FROZEN 2026-08-20): secondaries are
#: observational, carry their OWN directions, and putting a differently-directed
#: number beside the one being optimised invites exactly the trade-off they must
#: never get. Secondary science reaches the proposer through the interpreter's
#: synthesized ``key_findings`` / ``take_home_message``, which ARE carried.
#: Exposing raw secondary values, refusals or runtime diagnostics to the
#: proposer requires its own explicit semantic ruling — it must not arrive
#: incidentally through P5 or any other child.
NOT_CARRIED: dict[str, str] = {
    "cold_start": "already a typed ProposalInput field, populated by the protocol",
    "analysis_brief": (
        "owned by the Interpreter-to-DataAnalysis edge; the Proposer receives "
        "analysis only through ProposerDataAnalysisEvidence"
    ),
    "scientific_aggregation": "no proposer consumer",
    "best_valid_config": "no proposer consumer (best_config IS read, by the legacy renderer)",
    "runtime_vocab": "the protocol maps it to ProposalInput.vocab_seed",
    "prediction_evaluation": "no proposer consumer",
    "new_discoveries": "no proposer consumer",
    "vocab_changes": "no proposer consumer",
    "vocab_link_confirmations": "P5's cross-iteration lifecycle, not P3's",
    "is_degraded": "no proposer consumer",
    "evolution_stats": "no proposer consumer",
    "per_model_failure_counts": "no proposer consumer",
    "per_model_secondary_metrics": "RESERVED — Q-P3-3 NO_RAW_SECONDARY_CONSUMPTION (frozen)",
}

#: Names the legacy renderer used to read that the producer never declared.
#: Carrying them would fabricate a contract out of a bug, so they are dropped.
#: Recorded because "why is this absent?" is otherwise unanswerable.
DEAD_READS: tuple[str, ...] = ("per_file_comparison", "efficiency_comparison")


class ProposerInterpretationEvidence(BaseModel):
    """What the proposer may reason from — the whole contract, declared.

    Field names are the upstream names VERBATIM. Renaming would create a
    mapping layer between two carriers of the same fact and un-grep the
    lineage from producer to prompt.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- provenance: which metric these numbers are on, and which way is better
    metric_identity: MetricIdentityKey | None = Field(
        default=None,
        description="The identity the digest was ORDERED under, validated by the ONE "
        "transported-identity validator. None is a NAMED absence: no direction "
        "language renders, order-free fallbacks engage, no ranking is claimed.",
    )

    # --- model roster and descriptions
    model_types: list[str] = Field(default_factory=list, description="Empty = cold start.")
    model_descriptions: dict[str, str] = Field(default_factory=dict)
    total_experiments: int | None = None

    # --- per-model primary-score evidence (orderable ONLY through metric_identity)
    per_model_best: dict[str, float | None] | None = None
    per_model_best_valid: dict[str, float | None] | None = None
    per_model_worst: dict[str, float | None] | None = None
    per_model_raw_best_health_validity: dict[str, str] | None = None
    per_model_score_tables: dict[str, ScoreComparisonTable] | None = Field(
        default=None,
        description="The ONE carrier for the per-model tables. It absorbs the dead "
        "ProposalInput.per_model_score_tables mirror, which had zero readers.",
    )
    per_model_params: dict[str, int] | None = None
    per_model_training_segments: dict[str, int] | None = None
    model_knowledge_cache: dict[str, dict[str, Any]] | None = Field(
        default=None,
        description="Loosely typed BECAUSE the producer declares it loosely; the "
        "projection does not invent a schema its source does not have.",
    )

    # --- run-level scalars (the frozen D1 names)
    best_denoising_score: float | None = None
    best_valid_denoising_score: float | None = None
    worst_denoising_score: float | None = None
    best_config: dict[str, Any] | None = None

    # --- synthesized science (the channel secondary observations legitimately use)
    key_findings: list[str] | None = None
    bottlenecks: list[str] | None = None
    take_home_message: str | None = None

    # --- prediction track record (versioned pools; never pooled together)
    scientific_accuracy: dict[str, float] | None = None
    cumulative_information_gain: float | None = None
    prediction_outcomes_history: dict[str, int] | None = None
    prediction_outcomes_by_semantics: dict[str, dict[str, int]] | None = None
    cumulative_information_gain_by_semantics: dict[str, float] | None = None
    prediction_pool_sizes: dict[str, int] | None = None
    prediction_evaluation_semantics: str | None = None

    # --- vocabulary health (drives the exploration-mode stagnation signal)
    vocab_diversity_ratio: float | None = None

    # --- deterministic HealthGate evidence (flag-gated rendering)
    per_model_round_health_counts: dict[str, dict[str, int]] | None = None
    per_model_collapse_fingerprints: dict[str, list[CollapseFingerprint]] | None = None
    collapse_fingerprint_history: dict[str, list[CollapseFingerprintHistoryEntry]] | None = None


def build_proposer_evidence(
    interpretation: Mapping[str, Any],
) -> ProposerInterpretationEvidence:
    """Project a serialized interpretation into the proposer's view.

    The ONE projection authority. Both production entrypoints call it:

    * the protocol (``ml_result_interp_to_ml_model_propose.local_full_context``)
      passes ``InterpretationOutput.model_dump()``;
    * the node's standalone CLI passes the loaded
      ``interpretation_{run_name}.json``, which the interpreter persists as
      exactly ``model_dump_json`` — the SAME shape.

    One function, one input shape, two callers: that is parent §11.2's
    executable rule. Taking the MAPPING rather than the model is what makes the
    second caller possible at all — the CLI holds a parsed artifact, not an
    ``InterpretationOutput``, and must not have to reconstruct one to read its
    own node's input.

    Args:
        interpretation: the serialized INTERPRETATION — an
            ``InterpretationOutput`` dump or the artifact persisted from one.
            Missing keys are tolerated (legacy artifacts); present-but-malformed
            values are not.

            NOT an evidence dump. The two spell the identity differently: an
            interpretation carries ``metric_identity = {metric_id, direction}``
            while this value's ``MetricIdentityKey`` dumps as ``{id, direction}``.
            Feeding a ``ProposerInterpretationEvidence.model_dump()`` back in
            would therefore hit the frozen "malformed identity is a named
            absence" rule and silently return ``metric_identity=None``. No
            caller does this today (the protocol, the CLI and the Gate harness
            all project from interpretation dumps); it is named here so the
            first caller who tries to round-trip a persisted ``ProposalInput``
            finds the answer instead of the symptom.

    Returns:
        The typed view. Fields absent from the mapping take their declared
        absence value.

    Raises:
        pydantic.ValidationError: a key IS present but its value does not match
            the declared type — fail-closed at the boundary, rather than
            letting garbage reach prompt text.
    """
    declared = set(ProposerInterpretationEvidence.model_fields)
    payload: dict[str, Any] = {
        key: value for key, value in interpretation.items() if key in declared
    }
    # The identity is the one field with a validator of its own. Passing the raw
    # value through would let Pydantic try to coerce a malformed mapping into a
    # tuple and RAISE, when the frozen P2a contract says a malformed identity is
    # a named absence. ``metric_identity_from_mapping`` is that contract; a key
    # that is absent stays absent so the field default applies unchanged.
    if "metric_identity" in payload:
        payload["metric_identity"] = metric_identity_from_mapping(payload["metric_identity"])
    return ProposerInterpretationEvidence.model_validate(payload)
