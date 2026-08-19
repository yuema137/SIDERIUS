# execute_tools/health_checks/schemas.py
"""
Typed schemas for the pluggable HealthGate framework.

Rev-6 HealthGate schemas: HealthCheckContext (round-scoped, no phase),
HealthCheckResult, GateResult, GateAction. See
``docs/design/pluggable_health_checks.md`` for the full design.

Migration completed in commit-6: the pre-migration ``HealthCheckOutput``
and ``HealthCheckPanelOutput`` classes were removed (no consumers
remained). ``HealthCheckResult.passed`` is the direct successor to the
old ``HealthCheckOutput.is_degenerate`` field, with inverted polarity —
see ``HealthCheckResult`` docstring.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

# ---------------------------------------------------------------------------
# GateAction — routing verdict enum
# ---------------------------------------------------------------------------


class GateAction(StrEnum):
    """Actions a HealthGate can route to on pass or fail.

    See ``docs/design/pluggable_health_checks.md`` §4 for semantics.
    """

    CONTINUE = "continue"
    """Proceed normally. Next round runs, or iter closes if this was the
    last round — the tuner decides based on its own phase knowledge."""

    SKIP_ITER = "skip_iter"
    """Abort the current iteration. Move to the next iteration."""

    SKIP_TO_FORMAL = "skip_to_formal"
    """Skip remaining trial rounds. Jump to formal phase."""

    INVALIDATE_ROUND = "invalidate_round"
    """Mark this round's score as None. Continue to the next round."""


BLOCKING_ACTIONS: frozenset[GateAction] = frozenset(
    {GateAction.INVALIDATE_ROUND, GateAction.SKIP_TO_FORMAL, GateAction.SKIP_ITER}
)
"""Actions that stop the round from being accepted as a valid experiment.

Recording-only gates use ``CONTINUE`` on both ``on_pass`` and ``on_fail`` —
they never appear here. The tuner uses this set to decide when a failed
gate should flag ``is_degenerate`` (see ``_gate_results_to_score_meta`` in
``nodes/ml_hyperparameter_tune_agent``). Kept next to ``GateAction`` so
future contributors see it when they read the enum."""


# Severity table — most restrictive wins (design §8).
#   SKIP_ITER > SKIP_TO_FORMAL > INVALIDATE_ROUND > CONTINUE
# Moved here from runner.py (V19 PR 3 CB1, pr3_healthgate_feedback.md
# §2.5): this module is the side-effect-free canonical home for gate
# vocabulary, so schema-level consumers (agent/schemas/health_feedback)
# can order actions without importing the runner's config/registry
# machinery. runner.py re-exports both names for compatibility.
_SEVERITY: dict[GateAction, int] = {
    GateAction.CONTINUE: 0,
    GateAction.INVALIDATE_ROUND: 1,
    GateAction.SKIP_TO_FORMAL: 2,
    GateAction.SKIP_ITER: 3,
}


def severity_of(action: GateAction) -> int:
    """Integer severity for a ``GateAction``. Higher wins in ``resolve_action``.

    Public so the tuner and logging can order actions without duplicating the
    severity table.
    """
    return _SEVERITY[action]


GateExecutionStatus = Literal["passed", "failed", "not_run", "error"]
"""Execution state of one gate for one round (V19 PR 3 CB1).

Extracted alias of the ``PersistedHealthGateResult.execution_status``
value set so downstream schemas (``agent/schemas/health_feedback``)
reference ONE definition. Serialized values are unchanged."""


class CandidateHealthValidity(StrEnum):
    """Eligibility state for scientific/execution candidate selection.

    Moved here from ``candidate_eligibility.py`` (V19 PR 3 CB1): the enum
    is pure vocabulary needed by schema-level consumers, while the
    classifier functions (which read gate config) stay in
    ``candidate_eligibility`` — which re-exports this name for
    compatibility.
    """

    VALID = "valid"
    INVALID = "invalid"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# HealthCheckContext — inputs shared by all skills
# ---------------------------------------------------------------------------


class PerSampleEvidence(StrEnum):
    """Whether the round's metric produces per-sample evidence — D18.

    **The distinction this exists to preserve.** Step 06 already states it at
    the producer: ``MetricResult.per_sample`` is ``None`` for a scalar-only
    metric, and the Pets ``AccuracyMetric`` says so explicitly — "no per-file
    vector concept exists here". The tuner's bridge then collapsed it with
    ``list(metric_result.per_sample or [])``, so a scalar-only task presented
    per-file checks with ``[]`` — indistinguishable from a task that has
    per-file evidence and happens to have none this round.

    That is not a cosmetic loss. A check handed ``[]`` reports "no files" and
    PASSES, so "this question does not arise for this task" is recorded as
    health. This carries the producer's statement across the bridge intact so
    the engine can answer ``INAPPLICABLE`` instead.

    **No second flag is invented** (invariant 16): these three values are a
    faithful transport of what ``per_sample`` already says, and Step-06
    arithmetic is untouched. Health consumes the CAPABILITY only — never the
    golden metric scalar.
    """

    AVAILABLE = "available"
    """The metric produced per-sample evidence. It may still be empty — that
    is ``file_vector``'s question, deliberately a different one."""

    SCALAR_ONLY = "scalar_only"
    """The metric declares that no per-sample concept exists for this task.
    A positive statement, not an absence."""

    UNDECLARED = "undeclared"
    """Nothing was stated. The default, so every pre-D18 context and every
    pre-scoring gate keeps its exact meaning.

    **Absence is not scalar-only and must never be inferred as it.** A
    context that says nothing has not told us the task has no per-sample
    concept; it has told us nothing."""

    @classmethod
    def for_per_sample(cls, per_sample: list[float | None] | None) -> PerSampleEvidence:
        """Read Step 06's existing statement — the ONE place that maps it.

        ``MetricResult.per_sample`` already means what this enum says:
        ``None`` for a scalar-only metric, a list otherwise. Defined here
        rather than inline at the tuner bridge so there is exactly one
        spelling of the mapping; a second site could disagree, and the
        disagreement would be invisible because both would produce a valid
        member.

        An EMPTY list is ``AVAILABLE``. The metric produces per-sample
        evidence and produced none this round, which is a different claim
        from having no per-sample concept — the distinction D18 exists for.
        """
        return cls.SCALAR_ONLY if per_sample is None else cls.AVAILABLE


class HealthCheckContext(BaseModel):
    """Shared context passed to every health check skill.

    Checks read what they need. A check that operates on aggregated
    per-file magnitudes reads ``file_vector``; a check that peeks the
    denoised HDF5 uses ``denoised_paths`` or the lazy
    ``denoised_filename_fn``. A check has no obligation to consume any
    specific field — it is expected to introspect the context and skip
    gracefully when its inputs are absent.

    D2 note (migration decision): no raw in-memory int8 array field.
    The denoised output only exists on disk (in HDF5 files) after the
    ``inference_single.py`` subprocess terminates; eager-loading ~40 GB
    of int8 buffers is not viable. Checks that need the raw bytes read
    them lazily via ``get_denoised_path``.
    """

    model_config = {"arbitrary_types_allowed": True}

    # --- Identity — required ---
    model_name: str = Field(
        description=(
            "Plugin model identifier (e.g. ``wavenet_loss_screen_v17``). "
            "At the tuner call site this is what the codebase calls "
            "``model_type``; the design doc uses ``model_name`` as the "
            "eventual naming convention."
        ),
    )
    run_name: str = Field(
        description=(
            "Tuner ``storage_local.run_name`` — surfaced in check metrics and gate result logging."
        ),
    )
    round_index: int = Field(
        description=(
            "Which round produced this context (1-based). Gate config "
            "keys off this via ``after_round`` in health_checks.yaml. "
            "Phase concepts (pretrial/finetrial/formal) are tuner-level "
            "concerns, not HealthGate concerns."
        ),
    )

    # --- Identity — optional workflow-level index (D3) ---
    iter_num: int | None = Field(
        default=None,
        description=(
            "Workflow-level iteration number (e.g. iter_015 in a chain). "
            "None while the tuner does not yet plumb this through "
            "HyperparamTuningInput; plumbing is deferred to commit-5 "
            "of the migration."
        ),
    )

    # --- Output data — checks use what they need ---
    denoised_paths: dict[int, str] = Field(
        default_factory=dict,
        description=(
            "file_index → filename of the denoised HDF5 for that file. "
            "Empty when the caller has no eagerly-materialised paths — "
            "checks fall back to ``denoised_filename_fn`` if provided."
        ),
    )
    denoised_filename_fn: Callable[[int], str] | None = Field(
        default=None,
        description=(
            "Optional lazy filename constructor: file_index → filename. "
            "Preferred over ``denoised_paths`` on the scoring hot path "
            "because it avoids eagerly building a 20-entry dict when "
            "only one file is peeked. Excluded from JSON serialisation "
            "— the context is a transport within one process, never "
            "persisted."
        ),
        exclude=True,
    )
    target_path_fn: Callable[[int], str] | None = Field(
        default=None,
        description=(
            "Optional lazy filename constructor for the TARGET-signal HDF5: "
            "file_index → filename of the file containing the ground-truth "
            "channel that comparisons are made against (e.g. CH2 for "
            "TIDMAD). Parallel to ``denoised_filename_fn`` but for the "
            "target rather than the model output. None when the caller "
            "cannot resolve target paths — checks that need it fall back "
            "to ``passed=True`` with a 'not applicable' reason. Excluded "
            "from JSON serialisation."
        ),
        exclude=True,
    )
    checkpoint_path: str | None = Field(
        default=None,
        description="Checkpoint that produced the denoised outputs, for persisted provenance.",
    )

    # --- Scoring context (available at gates triggered after scoring) ---
    file_vector: list[float | None] = Field(
        default_factory=list,
        description=(
            "Per-file PSD magnitudes from the current scoring run. None "
            "entries mark files outside the sample set. Post-scoring "
            "checks read this; pre-scoring checks do not.\n\n"
            "An EMPTY list means 'nothing to read here'. It does NOT mean "
            "the task has no per-sample concept — that is a different "
            "statement and lives in ``per_sample_evidence`` (D18)."
        ),
    )
    per_sample_evidence: PerSampleEvidence = Field(
        default=PerSampleEvidence.UNDECLARED,
        description=(
            "Whether this round's metric produces per-sample evidence at all "
            "(Step 08b C6 / D18). A TYPED statement, because the alternative "
            "— an empty ``file_vector`` — cannot distinguish 'this task has "
            "no per-file concept' from 'it has one and it is empty', and a "
            "check handed the empty list answers the wrong question "
            "confidently."
        ),
    )
    denoising_score: float | None = Field(
        default=None,
        description=(
            "Final scalar denoising score for this round (if scoring has "
            "run). None at pre-scoring gates."
        ),
    )

    def get_denoised_path(self, file_index: int) -> str | None:
        """Resolve the denoised HDF5 filename for one file_index.

        Order of preference:
          1. Explicit entry in ``denoised_paths``.
          2. Lazy construction via ``denoised_filename_fn``.
          3. None when neither can produce a filename.
        """
        if file_index in self.denoised_paths:
            return self.denoised_paths[file_index]
        if self.denoised_filename_fn is not None:
            return self.denoised_filename_fn(file_index)
        return None

    def get_target_path(self, file_index: int) -> str | None:
        """Resolve the target-signal HDF5 filename for one file_index.

        Returns None when ``target_path_fn`` is not set.

        Step 08a: absence is no longer each check's problem to paper over.
        A check that needs the target signal declares ``target_source`` in
        its :class:`CheckInputDeclaration`, and ``evaluate_gate`` decides
        applicability BEFORE invoking it, so None here yields a typed
        ``CheckVerdict.INAPPLICABLE`` result. The M8 §3.4 convention this
        docstring used to prescribe — return a healthy verdict and a prose
        excuse — is superseded; see the Step-08 parent design §7.
        """
        if self.target_path_fn is not None:
            return self.target_path_fn(file_index)
        return None


# ---------------------------------------------------------------------------
# CheckVerdict — the four-way execution vocabulary (Step 08a)
# ---------------------------------------------------------------------------


class CheckVerdict(StrEnum):
    """What one check execution actually was.

    Step 08a (parent design §7). Before this enum, "not applicable" was
    spelled ``passed=True`` with a prose reason — indistinguishable from a
    genuine pass in ``evaluate_gate``'s aggregation, in eligibility inputs
    and in every count, while persistence string-matched its way back to
    ``execution_status="not_run"``. The verdict is the typed fact those
    surfaces should have been reading all along.

    ``passed`` keeps its exact meaning ("did not fail" — the field that
    drives ``on_pass`` / ``on_fail`` and ``short_circuit``), so gate ACTIONS
    are unchanged by the introduction of this vocabulary. Honesty moves to
    the layers that were lying: counting, persistence and eligibility.
    """

    PASSED = "passed"
    """The check ran and found no pathology."""

    FAILED = "failed"
    """The check ran and flagged the output. Drives ``on_fail``."""

    INAPPLICABLE = "inapplicable"
    """The check's declared inputs are not present for this task/context, so
    it was not evaluated. Never blocks — and **never counts as a pass**
    (parent §7). Decided before artifact I/O once the 08a applicability
    engine is wired."""

    ERROR = "error"
    """The check should have run but could not compute. On a blocking check
    this fails closed via ``on_fail`` — it is never converted to a pass or
    silently skipped."""


_NON_FAILING_VERDICTS: frozenset[CheckVerdict] = frozenset(
    {CheckVerdict.PASSED, CheckVerdict.INAPPLICABLE}
)
"""Verdicts that must accompany ``passed=True``.

The complement (``FAILED`` / ``ERROR``) must accompany ``passed=False``.
``HealthCheckResult`` enforces the equivalence at construction so a result
can never assert one thing in its typed verdict and the opposite in the
field that routes the gate."""


NA_REASON_MARKER: str = "not applicable"
"""The exact lowercase prose marker the pre-08a checks emit for an
inapplicable outcome (``_multi_file_peek.py``, ``spectral_peak_ratio.py``,
``per_file_output_std.py``, ``pearson_dispersion.py``).

Load-bearing ONLY for :func:`classify_verdict`, which exists so that
pre-08a constructor calls keep producing the right verdict. Production code
must branch on ``CheckVerdict``, never on this string."""


def classify_verdict(
    *,
    passed: bool,
    reason: str,
    metrics: dict[str, Any],
) -> CheckVerdict:
    """Classify one check outcome into the four-way vocabulary.

    THE single spelling of the Step-08a §3.1 mapping. Both the
    backward-compatibility validator on :class:`HealthCheckResult` and the
    production checks that derive a verdict from an aggregation outcome call
    this, so there is one rule rather than one rule and six transcriptions
    of it that drift apart.

    * ``passed`` + the exact :data:`NA_REASON_MARKER` → ``INAPPLICABLE``
    * ``passed`` otherwise → ``PASSED``
    * not passed, with ``exception_type`` in metrics, or every attempted
      file having failed I/O → ``ERROR``
    * not passed otherwise → ``FAILED``

    The distinction in the third rule is the one that matters: "nothing was
    measurable" is not the same claim as "the model is bad", and a required
    blocking check that could not compute must fail closed rather than be
    read as a scientific failure.

    Reason prose that merely resembles the marker (different wording)
    classifies from ``passed`` alone — so a reworded check surfaces as a
    verdict test failure rather than a silent reclassification.
    """
    if passed:
        return (
            CheckVerdict.INAPPLICABLE if NA_REASON_MARKER in reason.lower() else CheckVerdict.PASSED
        )
    if "exception_type" in metrics:
        return CheckVerdict.ERROR
    attempted = metrics.get("n_files_attempted")
    io_failed = metrics.get("n_files_io_failed")
    all_io_failed = (
        isinstance(attempted, int)
        and not isinstance(attempted, bool)
        and attempted > 0
        and io_failed == attempted
    )
    return CheckVerdict.ERROR if all_io_failed else CheckVerdict.FAILED


# ---------------------------------------------------------------------------
# HealthCheckResult — one check's verdict
# ---------------------------------------------------------------------------


class HealthCheckResult(BaseModel):
    """Result from one health check skill.

    Semantics are inverted from the pre-migration ``HealthCheckOutput``:
    ``passed=True`` means "output is healthy" (was ``is_degenerate=False``);
    ``passed=False`` means "flagged" (was ``is_degenerate=True``). This
    inversion aligns with the rev-6 gate model where ``on_pass`` / ``on_fail``
    are the branching semantics.

    Step 08a adds ``verdict``: the typed four-way statement of what the
    execution WAS, beside ``passed``'s statement of what the gate should DO.
    A caller that does not supply one gets it derived from the legacy shape
    (see ``_derive_verdict``); the two can never contradict each other.
    """

    check_name: str = Field(
        description=(
            "Registered name of the check that produced this result — "
            "matches the check class's ``name: ClassVar[str]``."
        ),
    )
    passed: bool = Field(
        description="True when the check flagged no degeneracy.",
    )
    reason: str = Field(
        default="",
        description=(
            "Human-readable + machine-parseable failure reason. Empty "
            "string when ``passed`` is True. Format: "
            "``'{check_name}: {details with numbers}'``."
        ),
    )
    metrics: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Structured metrics from the check (unique_count=1, "
            "dominant_fraction=0.98). Used by the tuner's memory format "
            "and by the Run Monitor's cross-iter policy."
        ),
    )
    verdict: CheckVerdict = Field(
        description=(
            "What this execution WAS: passed / failed / inapplicable / "
            "error (Step 08a; parent design §7). Distinct from ``passed``, "
            "which says what the gate should DO. Derived from the legacy "
            "fields when a caller omits it — see ``_derive_verdict`` — so "
            "pre-08a construction keeps working; production checks pass it "
            "explicitly."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _derive_verdict(cls, data: Any) -> Any:
        """Fill ``verdict`` from the pre-08a fields when it was not supplied.

        The backward-compatibility bridge. It delegates to
        :func:`classify_verdict` rather than restating the mapping, so the
        bridge can never disagree with the rule production applies
        explicitly — there is one classifier, reached two ways.
        """
        if not isinstance(data, dict) or "verdict" in data:
            return data
        passed = data.get("passed")
        if not isinstance(passed, bool):
            # Let Pydantic report the missing/invalid ``passed`` itself.
            return data
        metrics = data.get("metrics")
        reason = data.get("reason")
        return {
            **data,
            "verdict": classify_verdict(
                passed=passed,
                reason=reason if isinstance(reason, str) else "",
                metrics=metrics if isinstance(metrics, dict) else {},
            ),
        }

    @model_validator(mode="after")
    def _verdict_agrees_with_passed(self) -> HealthCheckResult:
        """Reject a result that routes one way and reports another.

        A ``verdict=PASSED, passed=False`` result would take ``on_fail``
        while every counting surface recorded a pass. Such a result must
        never be constructed, let alone persisted.
        """
        expected_passed = self.verdict in _NON_FAILING_VERDICTS
        if self.passed is not expected_passed:
            raise ValueError(
                f"HealthCheckResult verdict/passed contradiction for "
                f"{self.check_name!r}: verdict={self.verdict.value!r} requires "
                f"passed={expected_passed}, got passed={self.passed}."
            )
        return self


class PersistedHealthGateResult(BaseModel):
    """Fully serialisable gate observation for durable experiment records.

    **V20 PR D (D-C7b) — the record says what it actually was.** Before,
    an external reader had only `gate_name` and `resolved_action`, and the
    ids carry a historical `_blocking` suffix that describes the ROLE the
    gate was written for, not what it did on this run. A gate named
    `output_diversity_blocking` that resolved `continue` under an
    observe-only config blocked nothing, and every report that echoed its
    id said otherwise.

    `gate_name` is **never rewritten** — it is the join key for
    `health_gate_results` and for archived artifacts. The honest label is
    added BESIDE it.
    """

    gate_name: str
    execution_status: GateExecutionStatus
    check_passed: bool | None = None
    would_invalidate_under_production_policy: bool
    resolved_action: GateAction
    failure_reason: str | None = None
    threshold: dict[str, Any] | None = None
    aggregation: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    gate_runtime_seconds: float = 0.0

    # --- D-C7b: what this gate WAS, recorded alongside what it did ------
    gate_role: str | None = Field(
        default=None,
        description=(
            "The gate's DECLARED scientific role (`blocking` / "
            "`observational`), from `gate_role` in the effective config. "
            "None on results predating the declaration. Never inferred "
            "from the id or the action — that inversion is what the "
            "predecessor hotfix `af5339ce` removed."
        ),
    )
    configured_action: GateAction | None = Field(
        default=None,
        description=(
            "The gate's configured `on_fail.action` — what it WOULD do on "
            "failure. Distinct from `resolved_action`, which is the action "
            "actually taken this round (the `on_pass` action when the "
            "check passed). Both are needed: `resolved_action: continue` "
            "alone cannot distinguish 'passed, so nothing to do' from "
            "'configured to do nothing'."
        ),
    )
    healthgate_mode: str | None = Field(
        default=None,
        description="The run's declared enforcement mode (D-C1a). None on legacy results.",
    )
    result_authority: str | None = Field(
        default=None,
        description="The run's declared result authority (D-C1a). None on legacy results.",
    )

    # --- Step 08a: the typed per-check outcome, beside the gate's summary ---
    check_verdicts: dict[str, str] | None = Field(
        default=None,
        description=(
            "check_name → CheckVerdict value for every check that produced "
            "a result this round (Step 08a, Q-08a-1). Additive and "
            "OPTIONAL: ``None`` on records written before 08a, which must "
            "never be reinterpreted as a pass — the absence of verdicts is "
            "the absence of evidence about verdicts.\n\n"
            "It lives here rather than inside ``metrics`` because records "
            "are read by resume and interpretation tooling: a key buried in "
            "a free-form dict would be a contract nobody declared. "
            "``execution_status`` keeps its exact legacy VALUES; this field "
            "is where the honest four-way statement lives."
        ),
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def display_label(self) -> str:
        """Operator-facing label derived from what actually happened.

        Never from the id. A gate whose configured action cannot
        invalidate anything is displayed as observational however its id
        is spelled, and a gate whose role cannot be established says
        `role-unknown` rather than guessing.
        """
        if self.configured_action is None:
            # Nothing configured to read: fall back to the declared role,
            # and say `role-unknown` rather than guessing when even that is
            # absent. A legacy result must not default to "enforcing".
            label = self.gate_role or "role-unknown"
        else:
            label = "enforcing" if self.configured_action in BLOCKING_ACTIONS else "observational"
        return f"{self.gate_name} ({label})"


# ---------------------------------------------------------------------------
# GateResult — one gate's routing verdict
# ---------------------------------------------------------------------------


class GateResult(BaseModel):
    """Result from one HealthGate evaluation.

    ``action`` is the resolved routing outcome — the gate's ``on_pass``
    action when all checks passed, or its ``on_fail`` action when any
    check failed (short-circuit). See design doc §4 for action semantics
    and §8 for the runner logic including severity resolution when
    multiple gates fire at the same round.
    """

    gate_id: str = Field(
        description="The gate's id from ``configs/health_checks.yaml``.",
    )
    round_index: int = Field(
        description=(
            "Which round triggered this gate (propagated from "
            "``ctx.round_index`` at evaluation time). Used for logging "
            "and by the Run Monitor's cross-round policy."
        ),
    )
    passed: bool = Field(
        description=(
            "True when no check inside this gate failed. False when any "
            "check failed (the gate short-circuits on the first failure).\n\n"
            "Step 08a: this is a ROUTING fact — it selects ``on_pass`` or "
            "``on_fail`` — and an INAPPLICABLE check does not make it "
            "False, because an inapplicable check has nothing to object "
            "to. It is NOT a count of passes: what each check actually "
            "did is in each result's ``verdict``, and inapplicable never "
            "counts as passed (parent design §7)."
        ),
    )
    action: GateAction = Field(
        description=(
            "Resolved routing action — the ``on_pass`` action when "
            "``passed`` is True, otherwise the ``on_fail`` action."
        ),
    )
    check_results: list[HealthCheckResult] = Field(
        default_factory=list,
        description=(
            "Every check that ran, in the order the gate config listed "
            "them. Stops at the first failure (short-circuit)."
        ),
    )
    failure_reason: str = Field(
        default="",
        description=(
            "The ``reason`` from the first failing check. Empty string when ``passed`` is True."
        ),
    )

    @property
    def should_skip_iter(self) -> bool:
        return self.action == GateAction.SKIP_ITER

    @property
    def should_skip_to_formal(self) -> bool:
        return self.action == GateAction.SKIP_TO_FORMAL

    @property
    def should_invalidate_round(self) -> bool:
        return self.action == GateAction.INVALIDATE_ROUND


# ---------------------------------------------------------------------------
# Check input declaration + applicability (Step 08a)
# ---------------------------------------------------------------------------
#
# What a check DECLARES it needs, what a bound task DECLARES it has, and the
# pure comparison between them. Nothing here performs I/O, resolves a
# profile, or imports a task binding: applicability is decided BEFORE any
# artifact is opened (parent design §6.1-§6.2, child design §3.2-§3.3), which
# is what makes "not for this task" a statement the framework can make
# cheaply and honestly.
#
# Two vocabularies are deliberately OPAQUE to this module:
#
#   * ``consumes_view`` — a view capability key (parent §6.3). The engine
#     never interprets, branches on, or enumerates it.
#   * fact axis VALUES (e.g. ``"int8_symbol_stream"``) — compared for
#     equality, never parsed. A fourth task declares its own family string
#     without any framework edit.
#
# The axis NAMES and the context-input NAMES are framework-owned generic
# vocabulary: they describe properties of data, never identities of tasks.
# A new task binds by declaring axis VALUES, not by adding an axis.


CONTEXT_INPUT_PREDICATES: dict[str, Callable[[HealthCheckContext], bool]] = {
    "denoised_source": lambda ctx: bool(ctx.denoised_paths) or ctx.denoised_filename_fn is not None,
    "target_source": lambda ctx: ctx.target_path_fn is not None,
    "file_vector": lambda ctx: bool(ctx.file_vector),
    "denoising_score": lambda ctx: ctx.denoising_score is not None,
    "per_sample_evidence": lambda ctx: ctx.per_sample_evidence is PerSampleEvidence.AVAILABLE,
}
"""Logical context inputs a check may declare, and how presence is decided.

Logical, not raw field names: a check needs "somewhere to read the denoised
output from", which ``HealthCheckContext`` satisfies through EITHER
``denoised_paths`` OR ``denoised_filename_fn``. Declaring the raw fields
would force every check to restate that disjunction.

Framework-owned and generic — these describe what a round produced, never
which task produced it. A check needing something outside this vocabulary is
declaring a task-owned view, which is 08b/08c's plugin surface, not a new
entry here."""


FACT_AXES: frozenset[str] = frozenset(
    {
        "encoding_family",
        "symbol_cardinality",
        "value_scale_unit",
        "file_group_size",
        "sampling_frequency_hz",
    }
)
"""The declarable health-fact axes.

Generic data properties. Growth discipline mirrors the parent's rule for
STANDARD view capabilities (§6.3): adding an AXIS requires a task that
forces it, because every check and every task must then be able to reason
about it. Adding a task requires no new axis — a task declares VALUES."""


class FactRequirement(BaseModel):
    """One axis a check requires of the bound task's declared health facts.

    ``equals=None`` means presence-only: the check needs the task to have
    declared this axis at all, without caring what it says.
    """

    model_config = ConfigDict(frozen=True)

    axis: str = Field(
        description="Which declared fact axis this requirement is about; must be in FACT_AXES.",
    )
    equals: str | int | float | None = Field(
        default=None,
        description=(
            "Required value, compared for EQUALITY and never parsed. None "
            "means the requirement is satisfied by the axis being declared "
            "at all."
        ),
    )

    @field_validator("axis")
    @classmethod
    def _axis_is_known(cls, value: str) -> str:
        """Fail closed at AUTHORING time rather than at evaluation time.

        A typo'd axis would otherwise be permanently unsatisfiable: the task
        can never declare ``encodng_family``, so the check would report
        itself inapplicable forever and look like a deliberate opt-out.
        """
        if value not in FACT_AXES:
            raise ValueError(
                f"Unknown health fact axis {value!r}; expected one of "
                f"{sorted(FACT_AXES)}. An unknown axis can never be declared "
                f"by a task, so the check would be silently inapplicable "
                f"for every run."
            )
        return value


class TaskHealthFacts(BaseModel):
    """What the bound task DECLARES about the data its checks would inspect.

    **Presence-discriminated** (the D14 truth-table pattern): every axis is
    optional, and ``None`` means "this task declares nothing about this
    axis" — which is NOT the same as declaring a value that happens to
    mismatch. The two produce different inapplicability reasons, because
    they are different situations: one is an undeclared property, the other
    is a declared incompatibility.

    Values are opaque strings/numbers. Nothing here is interpreted; the
    engine only compares.
    """

    # ``extra="forbid"`` for the same reason ``FactRequirement`` rejects an
    # unknown axis: a typo'd axis that is silently DROPPED leaves the task
    # declaring nothing about it, so every check requiring that axis reports
    # itself inapplicable forever and looks like a deliberate opt-out. That
    # was harmless while these facts were only ever derived in-repo from a
    # resolved profile; Step 08b makes the vocabulary externally AUTHORABLE,
    # where a hand-written ``encodng_family`` is exactly the expected slip.
    model_config = ConfigDict(frozen=True, extra="forbid")

    encoding_family: str | None = Field(
        default=None,
        description=(
            "Opaque family identifier for how output samples are encoded, "
            "e.g. 'int8_symbol_stream' or 'continuous_float'. Compared for "
            "equality only — the framework ships no closed family list."
        ),
    )
    symbol_cardinality: int | None = Field(
        default=None,
        gt=1,
        description=(
            "Size of the symbol alphabet when the family is a symbol "
            "stream. Rejected at 1 or below: an alphabet of one symbol is "
            "the collapse these checks exist to detect, not a declaration."
        ),
    )
    value_scale_unit: str | None = Field(
        default=None,
        description=(
            "Physical unit declared samples carry once scaled, e.g. 'mV'. "
            "Absent when the task declares no physical scale."
        ),
    )
    file_group_size: int | None = Field(
        default=None,
        gt=0,
        description="How many files the task's deliverable is split across.",
    )
    sampling_frequency_hz: float | None = Field(
        default=None,
        gt=0.0,
        description="Sampling frequency of the stored series, when the task declares one.",
    )

    @model_validator(mode="after")
    def _dependent_axes_have_their_parent(self) -> TaskHealthFacts:
        """A cardinality without a family is a contradiction, not a fact.

        Checked structurally rather than semantically: deciding whether a
        given family string "is symbolic" would require interpreting an
        opaque value, which this module must never do. But declaring how
        many symbols exist while declaring nothing about the encoding is
        incoherent regardless of what the family would have said.
        """
        if self.symbol_cardinality is not None and self.encoding_family is None:
            raise ValueError(
                f"symbol_cardinality={self.symbol_cardinality} declared without "
                f"encoding_family. A symbol count is a property OF an encoding; "
                f"declaring it alone leaves checks unable to tell a symbol "
                f"stream from a continuous one."
            )
        return self

    def declared(self, axis: str) -> str | int | float | None:
        """Value declared for ``axis``, or None when the task is silent."""
        return getattr(self, axis, None)


class CheckInputDeclaration(BaseModel):
    """What one check needs, as DATA rather than as in-check control flow.

    Carries only what the six shipped checks were audited to actually
    consume (child design §3.2) — no mega-schema. A check declares this as a
    ``ClassVar``; the engine reads it before deciding to invoke the check at
    all.
    """

    model_config = ConfigDict(frozen=True)

    consumes_view: str = Field(
        description=(
            "View capability key this check reads (parent §6.3). OPAQUE: the "
            "engine never interprets, branches on, or enumerates it. 08a's "
            "six declare TIDMAD-family keys; the standard capabilities ship "
            "in 08c."
        ),
    )
    requires_view: bool = Field(
        default=False,
        description=(
            "Whether this check can only run when a bound provider supplies "
            "``consumes_view`` (Step 08b C3).\n\n"
            "The two fields answer different questions, which is why both "
            "exist. ``consumes_view`` NAMES the capability; this says whether "
            "the check is helpless without it. 08a's seven built-ins name a "
            "capability and still read their own artifacts, so they keep the "
            "default and are invoked through the unchanged "
            "``run(ctx, config)`` path — a check that never heard of views is "
            "called exactly as before, at runtime, not merely by relying on a "
            "parameter default.\n\n"
            "``True`` makes the binding MANDATORY: if no bound provider "
            "advertises the key, startup fails closed (§3.2). That is a "
            "configuration error and must never become a Health verdict."
        ),
    )
    required_context_inputs: tuple[str, ...] = Field(
        default=(),
        description=(
            "Logical context inputs that must be present; keys of CONTEXT_INPUT_PREDICATES."
        ),
    )
    required_facts: tuple[FactRequirement, ...] = Field(
        default=(),
        description="Fact axes the bound task must declare (and optionally match).",
    )
    threshold_parameter_names: tuple[str, ...] = Field(
        default=(),
        description=(
            "Config keys that are TASK thresholds rather than framework "
            "policy. Pure metadata in 08a; 08b consumes it for the "
            "ownership migration."
        ),
    )

    @field_validator("required_context_inputs")
    @classmethod
    def _context_inputs_are_known(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Fail closed at authoring time — same reasoning as ``FactRequirement.axis``."""
        unknown = sorted(set(value) - set(CONTEXT_INPUT_PREDICATES))
        if unknown:
            raise ValueError(
                f"Unknown context input(s) {unknown}; expected a subset of "
                f"{sorted(CONTEXT_INPUT_PREDICATES)}. An unknown input can "
                f"never be satisfied, so the check would be silently "
                f"inapplicable for every run."
            )
        return value


class ApplicabilityVerdict(BaseModel):
    """Whether a check's declared inputs are satisfiable for this run.

    The decision is TYPED: ``applicable`` routes, and ``axis`` names what
    decided it. ``reason`` is explanatory prose for the persisted record and
    must never be the thing production branches on.
    """

    model_config = ConfigDict(frozen=True)

    applicable: bool = Field(
        description="True when every declared requirement is satisfied.",
    )
    axis: str | None = Field(
        default=None,
        description=(
            "The context input or fact axis that made this inapplicable. "
            "None exactly when applicable."
        ),
    )
    reason: str = Field(
        default="",
        description=(
            "Deterministic explanation, without a check-name prefix — the "
            "runner prefixes it so the persisted prose keeps the existing "
            "'{check_name}: not applicable — …' shape. Empty exactly when "
            "applicable."
        ),
    )

    @model_validator(mode="after")
    def _shape_matches_the_decision(self) -> ApplicabilityVerdict:
        if self.applicable and (self.axis is not None or self.reason):
            raise ValueError("An applicable verdict carries no axis and no reason.")
        if not self.applicable and (self.axis is None or not self.reason):
            raise ValueError(
                "An inapplicable verdict must name the deciding axis and carry a reason."
            )
        return self


APPLICABLE: ApplicabilityVerdict = ApplicabilityVerdict(applicable=True)
"""The single applicable verdict — it carries no information beyond itself."""


def _inapplicable(axis: str, reason: str) -> ApplicabilityVerdict:
    return ApplicabilityVerdict(applicable=False, axis=axis, reason=f"not applicable — {reason}")


def applicability(
    declaration: CheckInputDeclaration,
    task_facts: TaskHealthFacts,
    ctx: HealthCheckContext,
) -> ApplicabilityVerdict:
    """Decide, WITHOUT touching any artifact, whether this check applies.

    Pure and total. Evaluation order is load-bearing and asserted by test:

    1. **Declared context inputs**, in declaration order — the cheapest
       question, answerable from the context object alone.
    2. **Declared fact axes**, in declaration order — an absent axis and a
       mismatched axis are distinguished.

    The FIRST unsatisfied requirement wins, so the reason is deterministic
    for a given declaration rather than depending on which of several
    problems is "worst".

    An empty declaration is legal and always applicable: a check that
    declares no requirements is asserting that it can run anywhere, which is
    a meaningful claim rather than a missing one.

    Args:
        declaration: what the check needs.
        task_facts: what the bound task declares it has. Regime-A derives
            this from the dataset profile and Deliverable Contract; a task
            binding supplies it in 08b.
        ctx: the round's health-check context.

    Returns:
        ``APPLICABLE``, or an inapplicable verdict naming the deciding axis.
    """
    for name in declaration.required_context_inputs:
        if not CONTEXT_INPUT_PREDICATES[name](ctx):
            return _inapplicable(name, f"required context input {name!r} is absent")

    for requirement in declaration.required_facts:
        actual = task_facts.declared(requirement.axis)
        if actual is None:
            return _inapplicable(
                requirement.axis,
                f"task declares no {requirement.axis!r} fact",
            )
        if requirement.equals is not None and actual != requirement.equals:
            return _inapplicable(
                requirement.axis,
                f"{requirement.axis} is {actual!r}, check requires {requirement.equals!r}",
            )

    return APPLICABLE
