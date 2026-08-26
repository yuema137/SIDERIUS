"""The ONE semantic projection over a completed run's persisted artifacts.

Step 12 / PR-12e, workstream R. Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12e_out_of_tree_graduation.md`` §V.4 (the ownership boundary), §V.5 (one
projection, two presentation consumers), §V.6 (real artifacts only, class A vs
class B), §V.12 (the audited class-A surface), §V.13c (which file to read).

Why this module exists
----------------------
The persistence layer is rich and typed; the reporting layer is effectively
absent. Everything a user-facing view needs is already on disk in a
Pydantic-validated form, so this is **projection, not new framework
semantics** — and it therefore adds ZERO new persisted fields.

Before this module, the only renderers over these records were the PROMPT
renderers (``agent/prompt_templates/…``), which return prompt-line fragments
and still carry residual task nouns. And the only rich per-result table
(``build_score_table``) is TIDMAD reference science that a COMPOSED run
deliberately omits (F-12e-UX-7), so the composed path had no rendering at all
to inherit. This module is that path's generic renderer input.

What it owns, and what it must never own
----------------------------------------
GENERIC only, per §V.4: the training/validation objective history, the
primary-metric trajectory, the secondary-metric trajectories, iteration
status, the best-so-far trajectory, and the run/provenance summary.

**Task-local presentation — waveforms, images, video frames, spectra,
domain-specific qualitative comparisons — is NOT here and must never be.**
There is no task dispatch in this module: no task name is read, branched on,
or special-cased. A task that wants domain presentation renders it from its
own pack, beside this projection's output.

Two semantic rules, frozen by §V.4 and enforced here
----------------------------------------------------
1. **The training objective is not called "loss".** :class:`ObjectiveHistory`
   carries the framework's own typed ``objective_kind`` and every renderer
   labels the series with it. Training MAE/L1 and a terminal MSE/PSNR/MAE stay
   semantically distinct even where the mathematics overlaps.

2. **Direction is never a convention of the view.** Every ordering decision in
   this module goes through :class:`~execute_tools.metric_order.MetricOrder`,
   constructed from the run's own declaration; the identity itself is
   established by ``evaluation_metric``'s reconciliation and
   ``persisted_ranking``'s per-record partition. When no identity can be
   established this module **declines by name** — no best-so-far, no ranking,
   and a recorded refusal string — following the pattern of
   ``scripts/inspect_run_state.py`` and the chain console summary (§V.14h).

What it reads — settled by source, not chosen here (§V.13c)
------------------------------------------------------------
``run_output_{run}.json`` — the schema-normalized artifact written by
``HyperparamTuningOutput.model_validate(...).model_dump()``. NOT
``summary_{run}.json``, which is a deliberately RAW list of record dicts
(``core/sandbox_executor.py`` ``LocalRecorder``) whose declared keys are
ABSENT rather than null, and which carries none of ``metric_spec``,
``secondary_metric_specs``, ``task_composition_fingerprint``,
``health_config_sha256`` or ``resolved_data_scope``.

What is deliberately absent (class B, §V.12b — REFUSED)
--------------------------------------------------------
per-step/per-batch objective values · per-epoch TRAINING seconds (only
validation seconds are per-epoch) · per-sample score distributions · raw
signals · GPU/VRAM time series · a model-plugin content digest · a typed
chain-iteration index on a record. **None of these may become a new
persisted framework semantic to improve a plot.** Where a view would want
one, this module records the gap in :attr:`RunReport.gaps` instead, and the
view does without it.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent.schemas.hyperparam_tuning import ExperimentRecord, HyperparamTuningOutput
from agent.schemas.training_diagnosis import TrainingDiagnosis
from core.run_invariants import RUN_INVARIANTS_BASENAME, RunInvariants
from execute_tools.evaluation_metric import (
    METRIC_IDENTITY_UNAVAILABLE,
    MetricDirection,
    MetricIdentityConflictError,
    MetricIdentityKey,
    MetricSpec,
    StampedMetricSpec,
    metric_identity_from_mapping,
    metric_identity_unavailable_notice,
    reconcile_metric_identity,
)
from execute_tools.health_checks.schemas import PersistedHealthGateResult
from execute_tools.metric_order import MetricOrder
from execute_tools.training_history import TrainingHistory

#: The projection's own shape version. Bumped when a consumer-visible field is
#: added, removed or re-meant — the static report and the dashboard both read
#: it, and a silent shape change is how two consumers drift apart.
REPORT_SCHEMA_VERSION = "12e-R.1"

#: The artifact this projection reads, per §V.13c. Deliberately a module
#: constant: the glob is the discovery contract, and a second spelling of it in
#: the CLI would be a second answer to "which file is authoritative".
RUN_OUTPUT_GLOB = "run_output_*.json"

#: The population the best-so-far TRAJECTORY is drawn from, stated as a value
#: so the report can print it rather than leaving it an unstated convention.
#:
#: Deliberately NOT a re-derivation of HealthGate validity. ``MetricOrder``'s
#: own contract says selection FILTERS and then orders, and validity is
#: HealthGate's question; a report that recomputed it would become a second
#: authority for promotion eligibility. The tuner's already-committed answers
#: (``best_valid_*``) are surfaced VERBATIM by :class:`RunHeadline` instead.
#:
#: ``failed_mode_collapse`` is excluded for a reason ``MetricOrder`` names
#: explicitly: there ``denoising_score`` is the gate policy's PENALTY, and
#: under a minimised metric that penalty is the best number in the run.
BEST_SO_FAR_POPULATION = (
    "successful attempts carrying a finite, rankable primary-metric value; "
    "HealthGate validity is NOT re-derived here"
)


class RunReportError(RuntimeError):
    """No consumable artifact — a NAMED failure, never a silent empty report.

    Carries a stable :attr:`name` so a caller (the CLI, a test, an example
    pack's README command) can distinguish "you pointed me at the wrong
    directory" from "the directory is right and every artifact is corrupt".
    """

    def __init__(self, name: str, message: str) -> None:
        super().__init__(message)
        self.name = name


# ---------------------------------------------------------------------------
# Metric identity — direction is asked, never assumed
# ---------------------------------------------------------------------------


class MetricView(BaseModel):
    """One metric's identity and its direction, in words.

    The words come from :attr:`MetricOrder.direction_words` — the ONE module
    permitted to interpret ``direction``. Spelling "higher"/"lower" here from
    ``direction == "higher"`` would make this a second interpretation site,
    which is the pattern Step 07b removed from twenty-one tuner call sites and
    which Step 06's C5 boundary guard fails on.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric_id: str
    direction: MetricDirection
    verb: str = Field(description="maximize / minimize")
    comparative: str = Field(description="higher / lower")
    antonym: str = Field(description="the opposite of `comparative`")

    @property
    def label(self) -> str:
        """``psnr (higher is better)`` — the axis/legend caption."""
        return f"{self.metric_id} ({self.comparative} is better)"


def metric_view(declaration: MetricSpec | MetricIdentityKey) -> MetricView:
    """Project any metric declaration to its identity + direction words."""
    order = MetricOrder(declaration)
    words = order.direction_words
    return MetricView(
        metric_id=declaration.id,
        direction=order.direction,
        verb=words["verb"],
        comparative=words["comparative"],
        antonym=words["antonym"],
    )


# ---------------------------------------------------------------------------
# The class-A surfaces, one projection type each
# ---------------------------------------------------------------------------


class ObjectiveHistory(BaseModel):
    """The per-epoch training and validation objective — NOT "loss".

    §V.4 rule 1. ``objective_kind`` is the framework's own typed identity for
    the quantity being minimised during training (``LossConfig.loss_type``);
    it is carried through to every caption so a DAVIS training MAE is not
    displayed under the same word as a terminal MSE.

    ``comparability`` is the R2-vs-R3 stamp: it says whether the training and
    validation series may be compared to each other at all. A view that draws
    both curves on one axis without stating this would imply a comparison the
    framework refused to certify.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    objective_kind: str
    objective_reduction: Literal["mean", "sum"]
    comparability: Literal["established", "not_established"]
    comparability_reason: str | None
    epochs_planned: int
    epochs_completed: int
    truncated: bool = Field(
        description="epochs_completed < epochs_planned — derived, not a new persisted field."
    )
    train_objective: list[float | None] = Field(
        description=(
            "R2, one value per completed epoch. An ELEMENT is None where that "
            "epoch's objective was non-finite and the record crossed the storage "
            "boundary — `scoring_utils.coerce_nonfinite_to_none` writes JSON null "
            "for NaN/inf, and `TrainingHistory` declares the same tolerant element "
            "type since #299. The projection MIRRORS that shape rather than "
            "narrowing it: positions are preserved, so `epochs_completed == "
            "len(train_objective)` still holds and a diverged epoch renders as a "
            "GAP in the curve. Filtering the Nones out would silently SHORTEN the "
            "series — a run that diverged at epoch 7 of 10 would render as a "
            "healthy 9-point curve, which is the statistic-silently-wrong mode "
            "#299 was landed to eliminate, reintroduced one layer up in the "
            "presentation. A cast would be worse still: it would leave a runtime "
            "None inside a series the type claims is numeric."
        )
    )
    validation_objective: list[float | None] | None = Field(
        default=None,
        description=(
            "R3; the LIST is None when the run recorded no validation pass. An "
            "ELEMENT is None on the same grounds as train_objective — R3 is the "
            "SAME criterion, so a diverged model produces non-finite R3 rows too."
        ),
    )
    validation_samples: int | None = None
    validation_requested_samples: int | None = None
    validation_requested_samples_before_limit: int | None = None
    validation_was_limited: bool | None = Field(
        default=None,
        description=(
            "Derived exactly as TrainingHistory's own field documentation "
            "prescribes: before_limit > requested. None when no ceiling was "
            "configured — an absence, never False."
        ),
    )

    @classmethod
    def from_history(cls, history: TrainingHistory) -> ObjectiveHistory:
        before = history.validation_requested_samples_before_limit
        requested = history.validation_requested_samples
        limited = None if before is None or requested is None else before > requested
        return cls(
            objective_kind=history.objective_kind,
            objective_reduction=history.objective_reduction,
            comparability=history.comparability,
            comparability_reason=history.comparability_reason,
            epochs_planned=history.epochs_planned,
            epochs_completed=history.epochs_completed,
            truncated=history.epochs_completed < history.epochs_planned,
            train_objective=list(history.train_objective),
            validation_objective=(
                None if history.validation_objective is None else list(history.validation_objective)
            ),
            validation_samples=history.validation_samples,
            validation_requested_samples=requested,
            validation_requested_samples_before_limit=before,
            validation_was_limited=limited,
        )


class DiagnosisView(BaseModel):
    """The typed :class:`TrainingDiagnosis`, plus its authority-rendered line.

    ``summary_line`` is produced by the 07b authority
    (``render_training_dynamics_line``) rather than re-phrased here: that
    function owns the degenerate renderings ("none recorded", "invalid
    (non-finite)", "gap n/a (not comparable)") that a silent omission would
    misreport as an unremarkable run. The structured fields beside it are what
    a chart reads; the line is what a human reads.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: Literal["ok", "absent", "invalid"]
    validation_state: Literal["present", "absent"]
    comparability: Literal["established", "not_established"] | None
    train_trend: str | None
    validation_trend: str | None
    best_validation_epoch: int | None
    validation_degraded_after_best: bool | None
    train_validation_gap_final: float | None
    summary_line: str

    @classmethod
    def from_diagnosis(
        cls, diagnosis: TrainingDiagnosis, *, objective_kind: str | None
    ) -> DiagnosisView:
        from agent.prompt_templates.tuner.rendering import render_training_dynamics_line

        return cls(
            state=diagnosis.state,
            validation_state=diagnosis.validation_state,
            comparability=diagnosis.comparability,
            train_trend=diagnosis.train_trend,
            validation_trend=diagnosis.validation_trend,
            best_validation_epoch=diagnosis.best_validation_epoch,
            validation_degraded_after_best=diagnosis.validation_degraded_after_best,
            train_validation_gap_final=diagnosis.train_validation_gap_final,
            summary_line=render_training_dynamics_line(diagnosis, objective_kind),
        )


class HealthGateView(BaseModel):
    """One persisted gate outcome, with its per-check verdicts.

    ``display_label`` is read off the persisted result rather than rebuilt: it
    is a ``@computed_field`` whose rule ("never from the id") lives with the
    schema, and a view that re-derived it would show a legacy gate as
    "enforcing" exactly where the authority refuses to.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    gate_name: str
    display_label: str
    execution_status: Literal["passed", "failed", "not_run", "error"]
    check_passed: bool | None
    resolved_action: str
    configured_action: str | None
    gate_role: str | None
    failure_reason: str | None
    check_verdicts: dict[str, str] | None

    @classmethod
    def from_persisted(cls, gate: PersistedHealthGateResult) -> HealthGateView:
        return cls(
            gate_name=gate.gate_name,
            display_label=gate.display_label,
            execution_status=gate.execution_status,
            check_passed=gate.check_passed,
            resolved_action=str(gate.resolved_action),
            configured_action=(
                None if gate.configured_action is None else str(gate.configured_action)
            ),
            gate_role=gate.gate_role,
            failure_reason=gate.failure_reason,
            check_verdicts=dict(gate.check_verdicts) if gate.check_verdicts else None,
        )


class SecondaryView(BaseModel):
    """One DECLARED secondary metric joined against one attempt's outcome.

    The three-state vocabulary — ``scored`` / ``refused`` / ``unavailable`` —
    is the existing authority's (``SecondaryMetricEvidence.status``), not a
    new one. A crash keeps its separate diagnostic provenance in
    :attr:`error` and does **not** become a fourth scientific state, exactly
    as the interpreter's projection decided.

    Each entry carries its OWN direction. DAVIS declares a ``higher``-is-better
    ``psnr`` beside a ``lower``-is-better ``mse`` primary; inheriting the run's
    direction would render it backwards.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric: MetricView
    status: Literal["scored", "refused", "unavailable"]
    scalar: float | None = None
    refusal_contract_id: str | None = None
    error: str | None = Field(
        default=None,
        description="Diagnostic provenance for a crashed evaluation; never a fourth state.",
    )


class AttemptView(BaseModel):
    """One row of ``all_records`` — every class-A fact it carries.

    ``position`` is the record's index within this run output and nothing
    more. It is deliberately NOT called an iteration index: a typed
    chain-iteration index is class B (§V.12b, recoverable only from a
    directory name), and naming a positional counter after a semantic the
    framework does not persist is how a plot invents one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    position: int
    exp_id: str
    record_type: Literal["experiment", "attempt_failure"]
    status: str
    model_type: str
    timestamp: str
    is_trial: bool
    logical_round: int | None
    attempt_index: int | None
    model_params: int | None = Field(
        description=(
            "Read from the record's TOP-LEVEL `model_params`. The dashboard "
            "frontend read `results.model_params` — a key the production "
            "record has never had (F-12e-UX-4)."
        )
    )

    outcome: Literal["scored", "refused", "failed", "skipped"]
    score: float | None
    metric: MetricView | None = Field(
        description="The identity this RECORD was scored under; None for legacy/unscored."
    )
    rankable: bool = Field(
        description="Whether this record declares an identity compatible with the run's order."
    )
    best_so_far: float | None = Field(
        default=None, description="Direction-aware cumulative best; None outside the population."
    )
    is_new_best: bool = False

    failure_stage: str | None = None
    failure_type: str | None = None
    failure_reason: str | None = None
    failure_attribution: dict[str, Any] | None = None
    refusal_contract_id: str | None = None
    gate_action: str | None = None

    objective: ObjectiveHistory | None = None
    diagnosis: DiagnosisView | None = None
    health_gates: list[HealthGateView] = Field(default_factory=list)
    secondaries: list[SecondaryView] = Field(default_factory=list)


class RunHeadline(BaseModel):
    """The tuner's OWN committed best-of answers, surfaced verbatim.

    Not recomputed. These four fields already encode HealthGate validity and
    the trial/formal split, decided by the authorities that own them; a report
    that re-derived them would be a second answer to a question production has
    already settled.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    best_exp_id: str | None
    best_score: float | None
    best_formal_score: float | None
    best_valid_exp_id: str | None
    best_valid_score: float | None
    best_valid_formal_score: float | None


class RunProvenance(BaseModel):
    """Reproducibility identity, as persisted. Every field may be absent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    resolved_data_scope: list[int] | None
    health_gate_enabled: bool | None
    health_config_sha256: str | None
    healthgate_mode: str | None
    result_authority: str | None
    task_composition_fingerprint: str | None
    candidate_id: str | None
    health_checks_config: str | None
    health_checks_config_source: str | None
    composed: bool = Field(
        description=(
            "Whether this run carried a task-composition fingerprint. A "
            "PRESENCE fact about the artifact — never a task name, and never "
            "compared against one."
        )
    )


class RunView(BaseModel):
    """One ``run_output_*.json``, fully projected."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_path: str
    run_name: str
    model_type: str
    status: Literal["completed", "partial", "failed"]
    termination_reason: str
    started_at: str
    finished_at: str
    completed_rounds: int
    total_attempts: int

    metric: MetricView | None
    metric_source: Literal["run_output_metric_spec", "records_reconciled", "unavailable"]
    ranking_refusal: str | None = Field(
        description=(
            "The canonical metric-identity-unavailable notice, verbatim, when "
            "no order could be established. Non-None means this run is "
            "rendered WITHOUT ranking, best-so-far or any direction claim."
        )
    )
    best_so_far_population: str = BEST_SO_FAR_POPULATION

    secondary_metrics: list[MetricView] = Field(default_factory=list)
    headline: RunHeadline
    provenance: RunProvenance
    status_counts: dict[str, int] = Field(default_factory=dict)
    attempts: list[AttemptView] = Field(default_factory=list)

    @property
    def scored_attempts(self) -> list[AttemptView]:
        """Attempts carrying a finite primary value, in record order."""
        return [a for a in self.attempts if a.score is not None]


class LockView(BaseModel):
    """``run_invariants_lock.json`` — the workspace's pinned identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_path: str
    resolved_data_scope: list[int]
    health_gate_enabled: bool
    health_config_sha256: str | None
    task_composition_fingerprint: str | None
    created_at: str | None
    runtime_estimator_identity: str | None
    runtime_policy_identity: str | None
    model_plugin_identities: list[dict[str, str]] | None


class TrajectoryPoint(BaseModel):
    """One scored attempt on the whole corpus's primary-metric trajectory."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_name: str
    source_path: str
    model_type: str
    exp_id: str
    is_trial: bool
    score: float
    best_so_far: float
    is_new_best: bool


class Trajectory(BaseModel):
    """The primary-metric trajectory across every consumable run.

    This is the curve both consumers draw. It exists at report level rather
    than run level because a chain's iterations are separate ``run_output``
    files, and the question an operator asks ("is this campaign improving?")
    spans them.

    ``metric`` is ``None`` and ``refusal`` names why whenever the corpus's
    runs do not agree on ONE metric identity — a mixed corpus is REFUSED, not
    silently ranked under whichever direction happened to come first.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric: MetricView | None
    refusal: str | None
    points: list[TrajectoryPoint] = Field(default_factory=list)


def build_trajectory(runs: Sequence[RunView]) -> Trajectory:
    """Fold the corpus's scored attempts into one direction-aware curve.

    The identity is reconciled ACROSS runs by ``evaluation_metric``'s
    authority before anything is compared; the comparison itself is
    ``MetricOrder.is_better``. Two runs scored under different metrics
    therefore produce a NAMED refusal and an empty curve, which is what
    ``persisted_ranking``'s case D does for the record corpora.
    """
    stamped = [
        StampedMetricSpec(
            label=f"run {run.run_name!r} ({run.source_path})",
            spec=(
                None
                if run.metric is None
                else MetricIdentityKey(id=run.metric.metric_id, direction=run.metric.direction)
            ),
        )
        for run in runs
    ]
    try:
        reconciled = reconcile_metric_identity(stamped)
    except MetricIdentityConflictError as exc:
        return Trajectory(
            metric=None,
            refusal=(
                f"{METRIC_IDENTITY_UNAVAILABLE}: this corpus mixes incomparable "
                f"metrics, so no trajectory is drawn — {exc}"
            ),
        )
    if reconciled is None:
        return Trajectory(
            metric=None,
            refusal=metric_identity_unavailable_notice(
                "the primary-metric trajectory",
                detail="no run in this corpus declares a metric identity",
            ),
        )

    order = MetricOrder(reconciled)
    view = metric_view(reconciled)
    points: list[TrajectoryPoint] = []
    best: float | None = None
    for run in runs:
        for attempt in run.attempts:
            if attempt.outcome != "scored" or not attempt.rankable or attempt.score is None:
                continue
            new_best = best is None or order.is_better(attempt.score, best)
            if new_best:
                best = attempt.score
            assert best is not None  # set on the first eligible point
            points.append(
                TrajectoryPoint(
                    run_name=run.run_name,
                    source_path=run.source_path,
                    model_type=attempt.model_type,
                    exp_id=attempt.exp_id,
                    is_trial=attempt.is_trial,
                    score=attempt.score,
                    best_so_far=best,
                    is_new_best=new_best,
                )
            )
    return Trajectory(metric=view, refusal=None, points=points)


class RunReport(BaseModel):
    """The whole projection — the ONE data model both consumers read.

    The static report renderer and the dashboard read THIS. There is not one
    data model for static plots and a second for the browser (§V.5).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = REPORT_SCHEMA_VERSION
    generated_at: str
    workspace: str | None
    runs: list[RunView] = Field(default_factory=list)
    trajectory: Trajectory = Field(default_factory=lambda: Trajectory(metric=None, refusal=None))
    lock: LockView | None = None
    gaps: list[str] = Field(
        default_factory=list,
        description=(
            "Named class-B gaps this report did without, and named refusals "
            "(a run whose metric identity could not be established). A gap is "
            "recorded, never closed by inventing a persisted field."
        ),
    )
    unreadable: list[str] = Field(
        default_factory=list,
        description="Artifacts found but not consumable, each with its reason.",
    )


# ---------------------------------------------------------------------------
# Reading and discovery
# ---------------------------------------------------------------------------


def discover_run_outputs(workspace: Path) -> list[Path]:
    """Every ``run_output_*.json`` under ``workspace``, deepest-stable order.

    A recursive walk on purpose. Two on-disk layouts exist — the chain layout
    (``{workspace}/iter_NNN/…``) and the legacy in-process one
    (``{workspace}/iteration_NNN/{model}/…``) — and a third nesting is exactly
    the kind of assumption that makes a report silently empty. Sorting by path
    gives a stable census; CHRONOLOGY comes from each output's own
    ``started_at``, never from the directory name (§V.12b: a typed
    chain-iteration index is not persisted, and a path is not one).
    """
    if not workspace.is_dir():
        raise RunReportError(
            "workspace_not_a_directory",
            f"--workspace {workspace} is not a directory.",
        )
    return sorted(workspace.rglob(RUN_OUTPUT_GLOB))


def load_run_output(path: Path) -> HyperparamTuningOutput:
    """Validate one artifact against the schema that wrote it.

    The file is normalized by
    ``HyperparamTuningOutput.model_validate(...).model_dump()`` on the way
    out, so re-validating on the way in is the honest read, and a file that
    fails is CORRUPT rather than quietly half-rendered.

    Parsing and validation are DELIBERATELY two steps. The obvious spelling —
    ``model_validate_json(text)`` inside ``except (ValidationError,
    json.JSONDecodeError)`` — has an unreachable second branch: pydantic v2
    reports a JSON SYNTAX error as a ``ValidationError`` too, so the
    ``JSONDecodeError`` clause never fires and every truncated file is
    reported as a schema violation. (``scripts/inspect_run_state.py``'s
    ``_validate_run_output`` has that shape; OBSERVED, not this workstream's
    to change.) Splitting the steps keeps "this file is not JSON" and "this
    file is not a tuner output" as two different things an operator is told,
    because they have two different causes — a mid-crash truncation versus a
    schema the artifact predates.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RunReportError("run_output_unreadable", f"{path}: read error: {exc}") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RunReportError(
            "run_output_malformed_json", f"{path}: malformed JSON: {exc.msg}"
        ) from exc
    try:
        return HyperparamTuningOutput.model_validate(payload)
    except ValidationError as exc:
        raise RunReportError(
            "run_output_invalid",
            f"{path}: does not validate against HyperparamTuningOutput "
            f"({exc.error_count()} error(s)).",
        ) from exc


def load_lock(workspace: Path) -> LockView | None:
    """The workspace's run-invariants lock, or ``None`` when absent.

    A missing lock is an absence, not an error: a run may predate the lock, or
    the report may be pointed at a single output rather than a workspace.
    """
    path = workspace / RUN_INVARIANTS_BASENAME
    if not path.is_file():
        return None
    try:
        lock = RunInvariants.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, json.JSONDecodeError):
        return None
    return LockView(
        source_path=str(path),
        resolved_data_scope=list(lock.resolved_data_scope),
        health_gate_enabled=lock.health_gate_enabled,
        health_config_sha256=lock.health_config_sha256,
        task_composition_fingerprint=lock.task_composition_fingerprint,
        created_at=lock.created_at,
        runtime_estimator_identity=lock.runtime_estimator_identity,
        runtime_policy_identity=lock.runtime_policy_identity,
        model_plugin_identities=lock.model_plugin_identities,
    )


# ---------------------------------------------------------------------------
# Order resolution — ask the authority, or decline by name
# ---------------------------------------------------------------------------


def resolve_run_order(
    output: HyperparamTuningOutput,
) -> tuple[
    MetricOrder | None,
    MetricView | None,
    Literal["run_output_metric_spec", "records_reconciled", "unavailable"],
    str | None,
]:
    """The ONE order this run's values may be compared in.

    Returns ``(order, view, source, refusal)``.

    Three cases, and none of them guesses:

    * the output carries ``metric_spec`` — the run's own declaration — and it
      is reconciled against the identity of every record that HAS one, so a
      corrupt artifact mixing two metrics REFUSES here rather than ranking one
      under the other's direction;
    * no ``metric_spec`` (a legacy output) but the records agree on an
      identity — that reconciled identity is used, which is precisely what
      ``persisted_ranking`` does for the other three record-corpus consumers;
    * neither — ``order`` is ``None``, ``refusal`` carries the canonical
      ``metric_identity_unavailable_notice``, and the caller renders the run
      with no ranking and no direction claim.

    **Identity-less records are EXCLUDED BEFORE reconciliation, never handed
    to it.** This is ``partition_by_metric_identity``'s rule and the ordering
    of the two steps is load-bearing: ``reconcile_metric_identity`` REFUSES a
    source set in which some entries declare an identity and others do not,
    which is correct for a uniformly-stamped interpretation output and wrong
    for a record corpus. Passing all records straight in makes the ordinary
    real shape — one ``success`` beside several ``error_training`` records
    that never reached scoring — refuse to rank at all. Measured on the real
    ``step09_5a`` terminal-pass artifact: 15 records, 1 carrying an identity,
    whole run unranked. A record that declares nothing is excluded
    INDIVIDUALLY; it stays fully readable and simply never receives a rank.

    The reconciliation and the ordering are two different authorities and stay
    that way: identity is ``evaluation_metric``'s, ordering is
    ``MetricOrder``'s, and this function composes them without comparing
    anything itself.
    """
    stamped = [
        StampedMetricSpec(
            label=f"record {record.exp_id!r}",
            spec=MetricIdentityKey(
                id=record.metric_result.metric_id,
                direction=record.metric_result.direction,
            ),
        )
        for record in output.all_records
        if record.metric_result is not None
    ]
    bound = output.metric_spec
    try:
        reconciled = reconcile_metric_identity(
            stamped,
            bound=bound,
            bound_label=f"run_output {output.run_name!r} metric_spec",
        )
    except MetricIdentityConflictError as exc:
        return (
            None,
            None,
            "unavailable",
            f"{METRIC_IDENTITY_UNAVAILABLE}: incomparable metrics in one run — {exc}",
        )
    if reconciled is None:
        return (
            None,
            None,
            "unavailable",
            metric_identity_unavailable_notice(
                f"run {output.run_name!r}",
                detail="no metric_spec on the output and no record declares an identity",
            ),
        )
    source: Literal["run_output_metric_spec", "records_reconciled"] = (
        "run_output_metric_spec" if bound is not None else "records_reconciled"
    )
    # The VIEW prefers the whole spec when one exists: it is the run's own
    # declaration and carries the id the operator declared. Direction is
    # identical either way -- reconciliation would have refused otherwise.
    declaration: MetricSpec | MetricIdentityKey = bound if bound is not None else reconciled
    return MetricOrder(declaration), metric_view(declaration), source, None


# ---------------------------------------------------------------------------
# Record projection
# ---------------------------------------------------------------------------

_SCORED_STATUSES = frozenset({"success"})


def _finite(value: float | None) -> float | None:
    """``None`` for a missing or non-finite value.

    ``coerce_nonfinite_to_none`` already maps the scorer's ``-inf`` sentinel to
    JSON null at the storage boundary, but an in-memory output has not been
    through it, so both spellings of "no signal" arrive here.
    """
    if value is None:
        return None
    return None if not math.isfinite(value) else value


def _attempt_outcome(record: ExperimentRecord) -> Literal["scored", "refused", "failed", "skipped"]:
    """Four presentation classes over the thirteen persisted statuses.

    The statuses themselves are NOT collapsed — :attr:`AttemptView.status`
    carries the framework's own value verbatim and the status breakdown counts
    it. This is a rendering grouping only: a refusal is its own class because
    ``metric_refusal`` is a typed scientific fact, and a skip is its own class
    because nothing about the candidate was measured.
    """
    if record.metric_refusal is not None:
        return "refused"
    if record.status in _SCORED_STATUSES:
        return "scored"
    if record.status.startswith("skipped_"):
        return "skipped"
    return "failed"


def _project_secondaries(
    record: ExperimentRecord, declared: Sequence[MetricSpec]
) -> list[SecondaryView]:
    """Declared secondaries joined against ONE attempt's outcomes.

    The join rule is the interpreter's, unchanged: a matching result is
    ``scored``, a matching refusal is ``refused``, declared-but-neither is the
    NAMED absence ``unavailable``. NO declaration yields an empty list — a run
    that declared no secondary gets zero rows, never fabricated absences.
    """
    if not declared:
        return []
    results = {r.metric_id: r for r in record.secondary_metric_results}
    refusals = {r.metric_id: r for r in record.secondary_metric_refusals}
    errors = dict(record.secondary_metric_errors)
    views: list[SecondaryView] = []
    for spec in declared:
        result = results.get(spec.id)
        refusal = None if spec.id in results else refusals.get(spec.id)
        if result is not None:
            status: Literal["scored", "refused", "unavailable"] = "scored"
        elif refusal is not None:
            status = "refused"
        else:
            status = "unavailable"
        views.append(
            SecondaryView(
                metric=metric_view(spec),
                status=status,
                scalar=None if result is None else _finite(result.scalar),
                refusal_contract_id=(None if refusal is None else refusal.verdict.contract_id),
                error=errors.get(spec.id),
            )
        )
    return views


def project_attempt(
    record: ExperimentRecord,
    *,
    position: int,
    run_metric: MetricView | None,
    declared_secondaries: Sequence[MetricSpec],
) -> AttemptView:
    """One record, projected.

    No ordering happens here on purpose: best-so-far is a FOLD over the whole
    run (:func:`_fold_best_so_far`), and computing it per record would need an
    accumulator that this function does not own.
    """
    # The record-borne identity goes through the authority rather than being
    # rebuilt from `record.metric_result` field by field. Validating a
    # persisted direction means reading the `MetricDirection` vocabulary, and
    # that vocabulary is interpreted in exactly one module (Step 06's C5
    # boundary guard). Only the payload is dumped -- dumping the whole record
    # per attempt would cost a deep copy of the score table for nothing.
    identity = metric_identity_from_mapping(
        None if record.metric_result is None else record.metric_result.model_dump()
    )
    history = record.training_history
    objective = None if history is None else ObjectiveHistory.from_history(history)
    diagnosis = (
        None
        if record.training_diagnosis is None
        else DiagnosisView.from_diagnosis(
            record.training_diagnosis,
            objective_kind=None if history is None else history.objective_kind,
        )
    )
    # The metric-borne scalar is preferred where present: it is the metric's
    # OWN result. On a `success` record the schema validator has already
    # proven it equals `denoising_score`, so this is not a second source of
    # truth -- it is the same value under the name that carries its identity.
    scalar = (
        _finite(record.metric_result.scalar)
        if record.metric_result is not None
        else _finite(record.denoising_score)
    )
    return AttemptView(
        position=position,
        exp_id=record.exp_id,
        record_type=record.record_type,
        status=record.status,
        model_type=record.model_type,
        timestamp=record.timestamp,
        is_trial=record.is_trial,
        logical_round=record.logical_round,
        attempt_index=record.attempt_index,
        model_params=record.model_params,
        outcome=_attempt_outcome(record),
        score=scalar,
        metric=None if identity is None else metric_view(identity),
        rankable=(
            identity is not None
            and run_metric is not None
            and identity.direction == run_metric.direction
            and identity.id == run_metric.metric_id
        ),
        failure_stage=record.failure_stage,
        failure_type=record.failure_type,
        failure_reason=record.failure_reason,
        failure_attribution=record.failure_attribution,
        refusal_contract_id=(
            None if record.metric_refusal is None else record.metric_refusal.verdict.contract_id
        ),
        gate_action=record.gate_action,
        objective=objective,
        diagnosis=diagnosis,
        health_gates=[HealthGateView.from_persisted(g) for g in record.health_gate_results],
        secondaries=_project_secondaries(record, declared_secondaries),
    )


def _fold_best_so_far(attempts: list[AttemptView], order: MetricOrder) -> list[AttemptView]:
    """Direction-aware cumulative best over :data:`BEST_SO_FAR_POPULATION`.

    ``order.is_better`` is strict, which is what keeps "a new best" from firing
    on a tie — the same semantics the tuner and the chain fold use. Under a
    ``lower`` metric this fold descends; a ``Math.max``-shaped implementation
    would mark the WORST attempts as new bests, which is exactly the defect
    F-12e-UX-3 names on the other side of the wire.
    """
    best: float | None = None
    folded: list[AttemptView] = []
    for attempt in attempts:
        eligible = attempt.outcome == "scored" and attempt.rankable and attempt.score is not None
        if not eligible:
            folded.append(attempt)
            continue
        assert attempt.score is not None  # narrowed by `eligible`
        new_best = best is None or order.is_better(attempt.score, best)
        if new_best:
            best = attempt.score
        folded.append(attempt.model_copy(update={"best_so_far": best, "is_new_best": new_best}))
    return folded


def project_run(output: HyperparamTuningOutput, *, source_path: Path | str) -> RunView:
    """Project one validated ``run_output_*.json`` into the report model."""
    order, run_metric, metric_source, refusal = resolve_run_order(output)
    declared = list(output.secondary_metric_specs or ())
    attempts = [
        project_attempt(
            record,
            position=index,
            run_metric=run_metric,
            declared_secondaries=declared,
        )
        for index, record in enumerate(output.all_records)
    ]
    if order is not None:
        attempts = _fold_best_so_far(attempts, order)

    status_counts: dict[str, int] = {}
    for attempt in attempts:
        status_counts[attempt.status] = status_counts.get(attempt.status, 0) + 1

    return RunView(
        source_path=str(source_path),
        run_name=output.run_name,
        model_type=output.model_type,
        status=output.status,
        termination_reason=output.termination_reason,
        started_at=output.started_at,
        finished_at=output.finished_at,
        completed_rounds=output.completed_rounds,
        total_attempts=output.total_attempts,
        metric=run_metric,
        metric_source=metric_source,
        ranking_refusal=refusal,
        secondary_metrics=[metric_view(spec) for spec in declared],
        headline=RunHeadline(
            best_exp_id=output.best_exp_id,
            best_score=_finite(output.best_denoising_score),
            best_formal_score=_finite(output.best_formal_denoising_score),
            best_valid_exp_id=output.best_valid_exp_id,
            best_valid_score=_finite(output.best_valid_denoising_score),
            best_valid_formal_score=_finite(output.best_valid_formal_denoising_score),
        ),
        provenance=RunProvenance(
            resolved_data_scope=output.resolved_data_scope,
            health_gate_enabled=output.health_gate_enabled,
            health_config_sha256=output.health_config_sha256,
            healthgate_mode=(
                None if output.healthgate_mode is None else str(output.healthgate_mode)
            ),
            result_authority=(
                None if output.result_authority is None else str(output.result_authority)
            ),
            task_composition_fingerprint=output.task_composition_fingerprint,
            candidate_id=output.candidate_id,
            health_checks_config=output.health_checks_config,
            health_checks_config_source=output.health_checks_config_source,
            composed=output.task_composition_fingerprint is not None,
        ),
        status_counts=status_counts,
        attempts=attempts,
    )


# ---------------------------------------------------------------------------
# The class-B gaps this projection deliberately does without
# ---------------------------------------------------------------------------

#: Recorded in every report, so a view's silence about them is a stated
#: decision rather than an oversight. §V.12b: **none of these may become a new
#: persisted framework semantic to improve a plot.**
CLASS_B_GAPS: tuple[str, ...] = (
    "per-step / per-batch objective values are not persisted (only the epoch "
    "mean) — no within-epoch curve is drawn",
    "per-epoch TRAINING seconds are not persisted (only validation seconds) — "
    "no per-epoch training-time series is drawn",
    "per-sample score distributions are not persisted — no score histogram",
    "raw signals / deliverables are removed by --cleanup_denoised — no "
    "before/after domain plot is drawn by the FRAMEWORK (a task pack may draw "
    "its own from its own artifacts)",
    "GPU / VRAM time series exist on FAILURE records only — no resource timeline is drawn",
    "records carry model_type (a NAME) and no model-plugin content digest — "
    "runs are grouped by name, never claimed to be the same implementation",
    "no typed chain-iteration index is persisted on a record — runs are "
    "ordered by their own started_at, never by a directory name",
)


def build_report(
    *,
    workspace: Path | None = None,
    run_outputs: Iterable[Path] | None = None,
) -> RunReport:
    """Build the report from a workspace, or from explicit artifact paths.

    Exactly one of ``workspace`` / ``run_outputs`` carries the discovery; both
    may be given when a caller has already located the files inside a known
    workspace (the CLI does not, but a test does).

    Raises:
        RunReportError: when nothing consumable was found. A report is never
            silently empty — ``no_run_output_found`` means the search located
            no artifact, ``no_run_output_consumable`` means every artifact
            found failed to validate, and the reasons are attached.
    """
    paths = list(run_outputs) if run_outputs is not None else []
    if workspace is not None and run_outputs is None:
        paths = discover_run_outputs(workspace)
    if not paths:
        where = str(workspace) if workspace is not None else "the given paths"
        raise RunReportError(
            "no_run_output_found",
            f"No {RUN_OUTPUT_GLOB} artifact found under {where}. This report "
            f"reads the schema-normalized tuner output; summary_*.json is a "
            f"raw record log and is deliberately not consumed.",
        )

    runs: list[RunView] = []
    unreadable: list[str] = []
    for path in paths:
        try:
            output = load_run_output(path)
        except RunReportError as exc:
            unreadable.append(f"[{exc.name}] {exc}")
            continue
        runs.append(project_run(output, source_path=path))

    if not runs:
        raise RunReportError(
            "no_run_output_consumable",
            "Found "
            f"{len(paths)} {RUN_OUTPUT_GLOB} artifact(s), none consumable:\n  "
            + "\n  ".join(unreadable),
        )

    # Chronology from the artifacts' own persisted timestamps. A directory
    # name is a path fact, not a semantic index (§V.12b).
    runs.sort(key=lambda run: (run.started_at, run.source_path))

    trajectory = build_trajectory(runs)
    gaps = list(CLASS_B_GAPS)
    gaps += [
        f"run {run.run_name!r} ({run.source_path}): {run.ranking_refusal}"
        for run in runs
        if run.ranking_refusal is not None
    ]
    if trajectory.refusal is not None:
        gaps.append(f"primary-metric trajectory: {trajectory.refusal}")
    return RunReport(
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        workspace=None if workspace is None else str(workspace),
        runs=runs,
        trajectory=trajectory,
        lock=None if workspace is None else load_lock(workspace),
        gaps=gaps,
        unreadable=unreadable,
    )
