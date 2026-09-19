# agent/schemas/health_feedback.py
"""Typed schemas + deterministic logic for structured HealthGate feedback.

V19 PR 3 CB1 (``docs/design/v19_priorities/pr3_healthgate_feedback.md``
§3.2-§3.4, §3.8). This module is the single home for every deterministic
piece of the feedback pipeline:

    ExperimentRecord
      → deterministic RoundHealth            (classify_round_provenance,
                                              build_gate_outcomes)
      → deterministic fingerprint            (select_primary_gate_outcome,
                                              build_collapse_fingerprint)
      → deterministic history merge          (merge_fingerprint_history)
      → prompt rendering                     (CB3/CB4 — NOT here)
      → LLM interpretation                   (commentary only)

Nothing in this module reads LLM output, the filesystem, or gate config —
it is pure functions over persisted record data, imported only from the
side-effect-free ``execute_tools.health_checks.schemas``.

Governing rule (design §3.2, operator 2026-07-29, binding):

    Preserve the strongest evidence actually present in the record.
    Never infer gate execution from missing fields, and never discard
    explicit gate evidence because of a broad status classification.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from execute_tools.health_checks.schemas import (
    CandidateHealthValidity,
    GateAction,
    GateExecutionStatus,
    severity_of,
)

# ---------------------------------------------------------------------------
# Provenance — smallest typed model covering the confirmed cases
# ---------------------------------------------------------------------------

RoundHealthProvenance = Literal[
    "gated",
    "gates_disabled",
    "round_fields_only",
    "gate_not_evaluated",
    "legacy",
]
"""Where a round's health evidence comes from (design §3.2).

Chosen at CB1 as the smallest set representing every case the P3-CA
artifact audit CONFIRMED in real records (design §2.5) — each value maps
to an observed record shape, none is speculative:

* ``gated`` — persisted ``health_gate_results`` are authoritative. An
  explicitly PRESENT empty list on an executed round is still current
  gated-era provenance; emptiness alone is never legacy.
* ``gates_disabled`` — the record stamps ``health_gate_enabled=False``
  (DS5 waiver; validity is ``valid`` by rule).
* ``round_fields_only`` — commit-5b mid-vintage: round-level
  ``gate_action`` / ``failure_reason`` exist but per-gate results were
  not yet persisted (observed in ``diagnostic_baseline_pre_v17``).
  Round fields are preserved verbatim; no fingerprint is invented from
  prose.
* ``gate_not_evaluated`` — the attempt ended before HealthGate
  execution (pre-flight skip, attempt failure, pre-gate error status).
  Not healthy, not collapsed, not legacy.
* ``legacy`` — no reliable structured or round-level HealthGate
  evidence exists. No verdict is inferred from absence.
"""


NOT_EXECUTED_STATUSES: frozenset[str] = frozenset(
    {
        "skipped_oom_risk",
        "skipped_time_risk",
        "skipped_schema_violation",
    }
)
"""Pre-flight rejections — nothing ran (mirrors ``agent.schemas.ordering``)."""


PRE_GATE_ERROR_STATUSES: frozenset[str] = frozenset(
    {
        "error",
        "error_training",
        "error_training_oom",
        "error_inference",
        "error_inference_oom",
        "error_scoring",
    }
)
"""Statuses proven (design §2.5 lifecycle table) to terminate before gate
evidence is persisted.

``error_scoring`` nuance: its ``except`` handler wraps the gate call, so
gates may have PARTIALLY run before the crash — but the error-record
shape persists no gate keys, so classifying it ``gate_not_evaluated``
discards nothing. Evidence precedence (ladder step 1) protects any
future error shape that DOES persist results."""


# ---------------------------------------------------------------------------
# Fingerprint metric allowlists — authored from REAL V17 payloads (§2.5)
# ---------------------------------------------------------------------------

#: Operators that make a threshold a FLOOR (breached downward).
_FLOOR_OPERATORS: frozenset[str] = frozenset({">", ">="})

#: Operators that make it a CEILING (breached upward).
_CEILING_OPERATORS: frozenset[str] = frozenset({"<", "<="})

#: Units whose values are cardinal counts and therefore render exactly.
#:
#: The DECLARATION half of exactness. It is not the whole of it: membership
#: here says a check's arithmetic is meant to yield cardinals, and
#: ``_extract_discriminating_metrics`` additionally requires the observation
#: to BE one before rendering it as an integer. A unit is an unconstrained
#: string on both of its sources, so a declaration alone can never be allowed
#: to change a stored number.
_INTEGRAL_UNITS: frozenset[str] = frozenset({"count"})


def _worst_statistic(operator: str | None) -> str | None:
    """Which ``aggregate_statistics`` entry is the worst case (Step 10 / P4).

    DERIVED from the persisted comparison operator, which the check declares:
    a FLOOR (``>`` / ``>=``) is breached downward, so the worst observation is
    the ``minimum``; a CEILING (``<`` / ``<=``) is breached upward, so it is
    the ``maximum``.

    This replaced ``_WORST_STAT_BY_METRIC``, a per-metric-NAME map listing
    TIDMAD's three blocking metrics. That map held the SAME information the
    operator already carried, hard-coded a second time — and while it stood, a
    task-owned check with a correctly persisted threshold row still produced
    NO fingerprint, because its metric name was not in it. A derivation has no
    such gap: it works for any check that declares an operator, and it
    reproduces the old map's three answers exactly.

    An unrecognised or absent operator yields ``None`` rather than a guess —
    an evidence reader must not invent a direction it was not told.
    """
    if operator in _FLOOR_OPERATORS:
        return "minimum"
    if operator in _CEILING_OPERATORS:
        return "maximum"
    return None


_RECORDING_KEY_METRICS: frozenset[str] = frozenset(
    {
        "pearson_dispersion",
        "pearson_mean",
        "ratio_mean",
        "std_mv_mean",
        "std_mv_min",
        "std_mv_max",
    }
)
"""Recording-only scalars carried into ``GateOutcome.key_metrics`` (never
into fingerprints — design §3.4). Key names verified against the real
V17 payload's ``metrics`` dicts."""

SOURCE_EXP_IDS_BOUND = 8
"""Per-occurrence-bucket cap on ``source_exp_ids`` — latest 8, oldest
trimmed first (P3-CA decision, design §2.5)."""


def bucket_value(value: float | int, *, exact: bool) -> str:
    """Canonical signature rendering of one metric value (design §3.4).

    ``exact`` values (counts — ``threshold.unit == "count"``) render as
    integers; everything else is bucketed to 2 significant figures so
    near-identical collapse modes share a signature. Applied ONLY when
    deriving ``signature`` — stored ``metrics`` keep raw values.
    """
    if exact:
        return str(int(value))
    return f"{float(value):.2g}"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CollapseFingerprint(BaseModel):
    """Canonical, comparable identity of one round's failure mode (§3.3).

    ``signature`` is the ONLY field that participates in matching.
    ``metrics`` stores RAW values (never bucketed) so signatures can be
    recomputed under a revised bucketing rule from stored artifacts alone.
    ``human_readable`` is display-only and never enters equality.

    ``check_name`` holds the persisted ``gate_name`` of the selected gate
    (e.g. ``output_diversity_blocking``) — the strongest identity actually
    present in the record; the check's registered name is not persisted
    (CB1 implementation decision, recorded in the design §11-CB1).
    """

    check_name: str = Field(min_length=1)
    signature: str = Field(min_length=1)
    metrics: dict[str, float | int | str]
    human_readable: str


class FingerprintOccurrence(BaseModel):
    """Occurrences of one fingerprint at ONE iteration (§3.8)."""

    iteration: int
    count: int = Field(ge=1)
    source_exp_ids: list[str] = Field(default_factory=list)


class CollapseFingerprintHistoryEntry(BaseModel):
    """One fingerprint's bounded cross-iteration history (§3.8).

    Windowed count / first / last retained iteration are DERIVED from
    ``occurrences`` (single source of truth) — never persisted
    independently. Entry-level ``metrics`` / ``human_readable`` follow
    the representative-observation rule: they describe the most recently
    merged observation.
    """

    signature: str = Field(min_length=1)
    check_name: str = Field(min_length=1)
    metrics: dict[str, float | int | str] = Field(default_factory=dict)
    human_readable: str
    occurrences: list[FingerprintOccurrence] = Field(default_factory=list)

    @model_validator(mode="after")
    def _occurrences_ascending_unique(self) -> CollapseFingerprintHistoryEntry:
        iters = [o.iteration for o in self.occurrences]
        if iters != sorted(set(iters)):
            raise ValueError(
                f"occurrences must be strictly ascending by iteration with at "
                f"most one bucket per iteration; got iterations {iters}"
            )
        return self

    def windowed_count(self, minimum_retained_iter: int) -> int:
        """Occurrences within the retained window — never a lifetime total."""
        return sum(o.count for o in self.occurrences if o.iteration >= minimum_retained_iter)

    def last_retained_iter(self, minimum_retained_iter: int) -> int | None:
        retained = [o.iteration for o in self.occurrences if o.iteration >= minimum_retained_iter]
        return max(retained) if retained else None


class HealthFeedbackRetentionPolicy(BaseModel):
    """Bounded iteration-window retention (§3.8 — the ONLY PR 3 policy).

    ``history_window_iterations`` is the TOTAL number of iterations
    retained, INCLUDING the current one:

        minimum_retained_iter = current_iter - history_window_iterations + 1

    e.g. ``current_iter=5, window=3`` retains iterations 3, 4, 5.
    Non-positive values fail at construction, before any execution.
    """

    history_window_iterations: int = Field(default=3, ge=1)
    max_entries_per_model: int = Field(default=8, ge=1)

    def minimum_retained_iter(self, current_iter: int) -> int:
        return current_iter - self.history_window_iterations + 1


class GateOutcome(BaseModel):
    """One gate's condensed verdict; names never determine enforcement."""

    gate_name: str = Field(min_length=1)
    execution_status: GateExecutionStatus
    check_passed: bool | None = None
    would_invalidate_under_production_policy: bool | None = None
    resolved_action: GateAction | None = None
    gate_role: str | None = None
    configured_action: GateAction | None = None
    failure_reason: str | None = None
    key_metrics: dict[str, float | int | str] = Field(default_factory=dict)


class RoundHealth(BaseModel):
    """Per-round condensed gate evidence carried in ModelRunSummary (§3.2).

    ``status`` is carried verbatim as ``str`` — the canonical vocabulary
    is ``ExperimentRecord.status``'s Literal, and coupling the summary to
    the tuner's status set was deliberately avoided (design §3.2).
    """

    exp_id: str | None = None
    status: str
    health_validity: CandidateHealthValidity
    gate_action: str | None = None
    failure_reason: str | None = None
    gate_outcomes: list[GateOutcome] = Field(default_factory=list)
    fingerprint: CollapseFingerprint | None = None
    provenance: RoundHealthProvenance


# ---------------------------------------------------------------------------
# Deterministic classification (design §3.2 evidence-precedence ladder)
# ---------------------------------------------------------------------------


def _field_present(record: Any, field: str) -> bool:
    """Genuine presence of ``field`` in the record's SOURCE data.

    For a Pydantic model, ``model_fields_set`` mirrors raw-key presence on
    both production paths (design §2.5). For a plain dict (raw JSON), key
    membership is presence itself. Never reads the field VALUE — a
    default-constructed empty list is exactly what this must not trust.
    """
    fields_set = getattr(record, "model_fields_set", None)
    if fields_set is not None:
        return field in fields_set
    if isinstance(record, dict):
        return field in record
    return False


def _get(record: Any, field: str, default: Any = None) -> Any:
    if isinstance(record, dict):
        return record.get(field, default)
    return getattr(record, field, default)


def classify_round_provenance(record: Any) -> RoundHealthProvenance:
    """Classify one record's health-evidence provenance (design §3.2).

    Evidence precedence is binding: persisted gate evidence is never
    discarded by a status rule. Accepts an ``ExperimentRecord`` model or
    the raw dict as serialized in ``run_output_*.json``.
    """
    results = _get(record, "health_gate_results") or []

    # 1. Non-empty persisted evidence → gated, regardless of status.
    if len(results) > 0:
        return "gated"

    # 2. Explicit disabled stamp.
    if _get(record, "health_gate_enabled") is False:
        return "gates_disabled"

    # 3. Statuses proven to terminate before gate evidence is persisted.
    status = _get(record, "status")
    if (
        _get(record, "record_type") == "attempt_failure"
        or status in NOT_EXECUTED_STATUSES
        or status in PRE_GATE_ERROR_STATUSES
    ):
        return "gate_not_evaluated"

    # 4. Present-but-empty list on an executed status → current gated era.
    if _field_present(record, "health_gate_results"):
        return "gated"

    # 5. Round-level fields without per-gate results → commit-5b vintage.
    if _get(record, "gate_action") is not None or (
        status == "failed_mode_collapse" and _get(record, "failure_reason") is not None
    ):
        return "round_fields_only"

    # 6. No reliable evidence of any kind.
    return "legacy"


# ---------------------------------------------------------------------------
# Deterministic fingerprint construction (design §3.3-§3.4)
# ---------------------------------------------------------------------------


def _failed_gates(gate_results: list[Any]) -> list[dict[str, Any]]:
    out = []
    for g in gate_results:
        d = g if isinstance(g, dict) else g.model_dump(mode="json")
        if d.get("execution_status") == "failed" or d.get("check_passed") is False:
            out.append(d)
    return out


def select_primary_gate_outcome(
    gate_results: list[Any],
    round_gate_action: str | None,
) -> dict[str, Any] | None:
    """Select the gate outcome that contributed to the blocking verdict.

    Four-step narrowing (design §3.3, operator rule): action consistency
    → counterfactual verdict → blocking severity → persisted (config)
    order. A step that would eliminate every candidate is skipped —
    e.g. a record without the counterfactual field falls through step 2.
    Returns the selected result as a plain dict, or None when no gate
    failed (healthy round).
    """
    candidates = _failed_gates(gate_results)
    if not candidates:
        return None

    # Step 1 — action consistency with the round's resolved gate_action.
    if round_gate_action is not None:
        narrowed = [c for c in candidates if c.get("resolved_action") == round_gate_action]
        if narrowed:
            candidates = narrowed

    # Step 2 — counterfactual production verdict.
    narrowed = [c for c in candidates if c.get("would_invalidate_under_production_policy") is True]
    if narrowed:
        candidates = narrowed

    # Step 3 — highest blocking severity (reuses the ONE severity table).
    def _sev(c: dict[str, Any]) -> int:
        action = c.get("resolved_action")
        try:
            return severity_of(GateAction(action))
        except (ValueError, TypeError, KeyError):
            return -1

    top = max(_sev(c) for c in candidates)
    candidates = [c for c in candidates if _sev(c) == top]

    # Step 4 — persisted order (mirrors config order) as final tie-break.
    return candidates[0]


def _extract_discriminating_metrics(
    result: dict[str, Any],
) -> tuple[dict[str, float | int], dict[str, bool]]:
    """Pull the worst-case metric from one gate result (Step 10 / P4).

    Returns ``(raw_metrics, exactness_by_metric)``, both keyed by the
    PERSISTED ``threshold.metric`` name. Everything that used to come from a
    central per-metric-name table is now DERIVED from the threshold row the
    check declared:

    * the worst-case direction, from ``threshold.operator``;
    * exactness, from ``threshold.unit`` being a cardinal-count unit **and**
      the observation actually being a cardinal — a declared unit is not a
      validated property, and the raw value is never truncated to satisfy it.

    **Where the value lives depends on the check's shape, not its name.** A
    per-file check reports the worst observation ACROSS files, so it comes
    from ``aggregate_statistics``. A scalar check has no per-file dimension at
    all — its ``aggregate_statistics`` is empty by construction — so the
    single value it published under the declared metric name IS the worst
    observation. Both are "the worst observed value of the declared evidence
    metric"; only the arity differs, and the check's own metrics say which.

    Without that second branch the derivation would still have produced no
    fingerprint for a scalar task-owned check — the defect would have moved
    rather than gone.

    A gate with no threshold row yields nothing, which is why the three
    recording-only TIDMAD gates carry no fingerprint.
    """
    threshold = result.get("threshold") or {}
    metric_name = threshold.get("metric")
    if metric_name is None:
        return {}, {}
    stat = _worst_statistic(threshold.get("operator"))
    if stat is None:
        return {}, {}

    metrics = result.get("metrics") or {}
    aggregate = metrics.get("aggregate_statistics") or {}
    value = aggregate.get(stat)
    if value is None:
        # Scalar check: no per-file dimension, so the published value is the
        # worst observation. Read under the DECLARED metric name — no table.
        value = metrics.get(metric_name)
    if not isinstance(value, int | float) or isinstance(value, bool):
        return {}, {}

    # A DECLARED unit is not a validated property. ``count`` says the check's
    # arithmetic yields cardinals; it does not MAKE a fractional observation
    # into one, and `unit` is an unconstrained string on both of its sources
    # (`EvidenceUnit.literal`, check-owned; `EvidenceUnit.config_key`, resolved
    # from the task's own config), so any task can declare it over any value.
    #
    # This line used to be `int(value) if exact else float(value)`, which
    # silently rendered a `count`-declared 3.9 as 3 — in `metrics`, whose own
    # schema says it "stores RAW values (never bucketed) so signatures can be
    # recomputed under a revised bucketing rule from stored artifacts alone".
    # Truncation destroys exactly what that guarantee is for. (It also raised
    # `ValueError: cannot convert float NaN to integer` on a non-finite scalar
    # observation, which `aggregate_statistics` filters and the scalar branch
    # above does not.)
    #
    # So exactness now requires BOTH halves — the declared cardinal unit and a
    # value that actually is one — which makes the `int()` provably lossless
    # and leaves `metrics` raw in every case. A genuine count is unaffected:
    # `aggregate_statistics` publishes floats, so TIDMAD's counts arrive as
    # `2.0` and still persist as `2`. A mis-declared fractional value keeps its
    # digits and buckets as a float in the signature, which is the honest
    # rendering — two different fractions must not collide under a claim of
    # cardinality that the number itself refutes.
    exact = threshold.get("unit") in _INTEGRAL_UNITS and float(value).is_integer()
    return {metric_name: int(value) if exact else float(value)}, {metric_name: exact}


def build_collapse_fingerprint(
    gate_results: list[Any],
    round_gate_action: str | None,
) -> CollapseFingerprint | None:
    """Build the round's ONE primary fingerprint (design §3.3).

    Returns None when no gate failed, or when the selected gate carries
    no allowlisted discriminating metric (e.g. a mid-form result without
    ``aggregate_statistics``) — a fingerprint is never invented from
    prose.
    """
    selected = select_primary_gate_outcome(gate_results, round_gate_action)
    if selected is None:
        return None
    raw, exactness = _extract_discriminating_metrics(selected)
    if not raw:
        return None
    signature = (
        str(selected["gate_name"])
        + ":"
        + ";".join(
            f"{name}={bucket_value(raw[name], exact=exactness[name])}" for name in sorted(raw)
        )
    )
    return CollapseFingerprint(
        check_name=str(selected["gate_name"]),
        signature=signature,
        metrics=dict(raw),
        human_readable=str(selected.get("failure_reason") or "")
        or f"{selected['gate_name']} failed",
    )


def build_gate_outcomes(gate_results: list[Any]) -> list[GateOutcome]:
    """Condense every persisted gate result into a ``GateOutcome`` (§3.2)."""
    outcomes: list[GateOutcome] = []
    for g in gate_results:
        d = g if isinstance(g, dict) else g.model_dump(mode="json")
        raw, _ = _extract_discriminating_metrics(d)
        key_metrics: dict[str, float | int | str] = dict(raw)
        metrics = d.get("metrics") or {}
        for name in sorted(_RECORDING_KEY_METRICS & set(metrics)):
            value = metrics[name]
            if isinstance(value, int | float) and not isinstance(value, bool):
                key_metrics[name] = value
        outcomes.append(
            GateOutcome(
                gate_name=d["gate_name"],
                execution_status=d["execution_status"],
                check_passed=d.get("check_passed"),
                would_invalidate_under_production_policy=d.get(
                    "would_invalidate_under_production_policy"
                ),
                resolved_action=d.get("resolved_action"),
                gate_role=d.get("gate_role"),
                configured_action=d.get("configured_action"),
                failure_reason=d.get("failure_reason") or None,
                key_metrics=key_metrics,
            )
        )
    return outcomes


# ---------------------------------------------------------------------------
# Deterministic history merge + retention (design §3.8)
# ---------------------------------------------------------------------------


def merge_fingerprint_history(
    previous: dict[str, list[CollapseFingerprintHistoryEntry]],
    current: dict[str, list[tuple[CollapseFingerprint, str | None]]],
    current_iter: int,
    policy: HealthFeedbackRetentionPolicy,
) -> dict[str, list[CollapseFingerprintHistoryEntry]]:
    """Merge this iteration's fingerprints into the carried history.

    ``current`` maps model_type → [(fingerprint, exp_id or None)] in
    CHRONOLOGICAL record order (the representative-observation tie-break
    relies on this — design §3.8). Runs REGARDLESS of interpreter LLM
    success or degradation (§3.10 invariant): the inputs are
    deterministic RoundHealth fingerprints, never LLM output.

    Deterministic pipeline per model key (keys never cross — model
    attribution is preserved end-to-end):

        merge current occurrences into iteration buckets
        → expire buckets older than the resolved window
        → drop entries left with no buckets
        → order by (last_retained_iter desc, windowed_count desc,
                    signature asc)
        → trim to max_entries_per_model
    """
    min_iter = policy.minimum_retained_iter(current_iter)
    merged: dict[str, list[CollapseFingerprintHistoryEntry]] = {}

    model_keys = sorted(set(previous) | set(current))
    for model_type in model_keys:
        by_signature: dict[str, CollapseFingerprintHistoryEntry] = {
            e.signature: e.model_copy(deep=True) for e in previous.get(model_type, [])
        }

        for fingerprint, exp_id in current.get(model_type, []):
            entry = by_signature.get(fingerprint.signature)
            if entry is None:
                entry = CollapseFingerprintHistoryEntry(
                    signature=fingerprint.signature,
                    check_name=fingerprint.check_name,
                    metrics=dict(fingerprint.metrics),
                    human_readable=fingerprint.human_readable,
                    occurrences=[],
                )
                by_signature[fingerprint.signature] = entry
            else:
                # Representative-observation rule: latest merged
                # observation overwrites the entry-level raw view.
                entry.metrics = dict(fingerprint.metrics)
                entry.human_readable = fingerprint.human_readable
                entry.check_name = fingerprint.check_name
            bucket = next(
                (o for o in entry.occurrences if o.iteration == current_iter),
                None,
            )
            if bucket is None:
                bucket = FingerprintOccurrence(iteration=current_iter, count=1)
                entry.occurrences.append(bucket)
                entry.occurrences.sort(key=lambda o: o.iteration)
            else:
                bucket.count += 1
            if exp_id:
                bucket.source_exp_ids.append(exp_id)
                # Latest-8, oldest trimmed first (design §2.5).
                del bucket.source_exp_ids[:-SOURCE_EXP_IDS_BOUND]

        retained: list[CollapseFingerprintHistoryEntry] = []
        for entry in by_signature.values():
            entry.occurrences = [o for o in entry.occurrences if o.iteration >= min_iter]
            if entry.occurrences:
                retained.append(entry)

        retained.sort(
            key=lambda e: (
                -(e.last_retained_iter(min_iter) or 0),
                -e.windowed_count(min_iter),
                e.signature,
            )
        )
        if retained:
            merged[model_type] = retained[: policy.max_entries_per_model]

    return merged


# ---------------------------------------------------------------------------
# V20 PR D (D-C6) — the iteration produced no scientifically valid trial
# ---------------------------------------------------------------------------


class InvalidCandidateOutcome(BaseModel):
    """Why one candidate record failed to become a valid candidate.

    Facts only. The workflow layer transports these; interpreting what a
    particular gate's metrics imply for a particular task is the planner's
    job, and task remediation advice must never be baked in here.
    """

    model_config = ConfigDict(extra="forbid")

    exp_id: str | None = Field(default=None, description="Record identity, when persisted.")
    status: str = Field(
        description=(
            "The record's own status verbatim (`ExperimentRecord.status`). "
            "Distinguishes an EXECUTION failure from a completed run that "
            "then failed its gates — collapsing those two into 'trial "
            "failed' would tell the planner to fix the wrong thing."
        )
    )
    health_validity: CandidateHealthValidity = Field(
        description="invalid (a blocking gate failed) vs unknown (validity could not be established)."
    )
    failed_gate_names: list[str] = Field(
        default_factory=list,
        description="Blocking-role gates whose check did not pass, sorted for stable rendering.",
    )
    failure_reasons: list[str] = Field(
        default_factory=list,
        description="Machine-readable reasons already produced by the gate system. Never invented.",
    )
    key_metrics: dict[str, float | int | str] = Field(
        default_factory=dict,
        description=(
            "Measurements the gates already recorded (e.g. a diversity ratio "
            "or mode fraction). Passed through unchanged and unranked — the "
            "workflow layer does not decide which number matters."
        ),
    )


class InvalidTrialOutcome(InvalidCandidateOutcome):
    """Compatibility name for the existing Trial-only public carrier."""


class FormalValidityFeedback(BaseModel):
    """Bounded facts from Formal attempts when no valid Formal candidate exists.

    This contains failure evidence only, never a candidate or an incumbent.
    The last eight outcomes are retained; counts describe all Formal records.
    """

    model_config = ConfigDict(extra="forbid")
    model_type: str
    formal_records_considered: int = Field(ge=1)
    invalid_count: int = Field(ge=0)
    unknown_validity_count: int = Field(ge=0)
    execution_failure_count: int = Field(ge=0)
    outcomes: list[InvalidCandidateOutcome] = Field(max_length=8)
    healthgate_mode: str | None = None
    evidence_absent: list[str] = Field(default_factory=list, max_length=8)


class TrialValidityFeedback(BaseModel):
    """The iteration produced trial rounds but no HealthGate-valid winner.

    **A separate carrier from `GateExhaustionInfo`, deliberately.** That
    structure reports BUDGET exhaustion: its triggers require
    `skipped_oom_risk` / `skipped_time_risk` records and it fires only when
    nothing succeeded or a fail-round burst collapsed the search. An
    all-invalid iteration is the opposite shape — trials RAN and SUCCEEDED,
    then failed their scientific gates. Extending gate-exhaustion with a
    third trigger would have merged two failure modes that call for
    opposite planner responses: "propose something lighter" versus
    "propose something that does not collapse".

    Populated only when there is something to say. A run with at least one
    valid trial leaves it `None`, so the proposer prompt is byte-identical
    to before.
    """

    model_config = ConfigDict(extra="forbid")

    trial_records_considered: int = Field(description="Trial-mode records examined for candidacy.")
    invalid_count: int = Field(description="Completed trials whose blocking gates failed.")
    unknown_validity_count: int = Field(
        description="Trials whose validity could not be established (missing or unrun gates)."
    )
    execution_failure_count: int = Field(
        description=(
            "Trials that never produced a scorable result (crash, OOM, skip). "
            "Kept separate from gate invalidity: the evidence is ABSENT here, "
            "not negative."
        )
    )
    outcomes: list[InvalidTrialOutcome] = Field(
        default_factory=list,
        description="Per-record detail, oldest first.",
    )
    formal_skipped_for_no_valid_winner: bool = Field(
        default=False,
        description=(
            "Whether the formal round was skipped BECAUSE no valid winner "
            "existed. Distinct from a formal round skipped on the ordinary "
            "time budget, and from a formal round that ran and then failed "
            "its own gates — three different facts about the iteration."
        ),
    )
    healthgate_mode: str | None = Field(
        default=None,
        description="The declared enforcement mode this iteration ran under.",
    )
    evidence_absent: list[str] = Field(
        default_factory=list,
        description=(
            "What could NOT be established, named explicitly rather than "
            "left as a silent gap — e.g. gate results missing for a record."
        ),
    )
