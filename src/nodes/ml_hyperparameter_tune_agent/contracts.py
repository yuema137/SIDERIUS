"""Typed carriers shared between the tuner's orchestrator and its lifecycle phases.

Step 07 PR 07b, C7d (operator decision A-prime, 2026-08-16). PRIVATE node-internal
module: data boundaries only — no policy, no execution, no persistence, no
rendering, no runtime-control algorithms, no generic utilities.

Why these types exist at all
---------------------------
``run()`` mixes two categories of local that look alike and are not:

* **run-scoped stable bindings** — the authorities and service handles bound
  once during startup, whose identity never changes for the rest of the run;
* **mutable lifecycle state** — round and attempt counters, the current plan,
  the current results, the termination flags.

Because both lived as bare locals, every lifecycle phase measured 28-48 inputs
and none could be extracted honestly. Grouping the FIRST category is legitimate:
it is one real architectural concept ("this run's bound environment"). Grouping
the second would be the god context this design explicitly forbids — so
:class:`RunBindings` refuses it structurally, in ``__post_init__``.

The distinction is the whole point:

```text
bad context    = every mutable local in one bag
good carrier   = the data boundary of ONE real lifecycle concept
```
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from enum import Enum
from typing import Any

from agent.schemas.ordering import ResolvedOrdering
from core.capability_registry import CapabilityContractSnapshot

#: Names that must NEVER become ``RunBindings`` fields. Each is rebound or
#: mutated inside the round/attempt loops, so storing it on a "stable bindings"
#: object would make that object a mutable state bag — and would silently
#: freeze a value that production expects to change.
#:
#: Enforced at construction, not by convention: this class is passed widely,
#: which is exactly the condition under which a forbidden field would be added
#: "just this once".
FORBIDDEN_BINDING_FIELDS: frozenset[str] = frozenset(
    {
        "completed_rounds",
        "total_attempts",
        "consecutive_fails",
        "round_index",
        "attempt_in_round",
        "is_formal_round",
        "plan",
        "memory_history",
        "record_params",
        "active_params",
        "hypothesis",
        "exp_id",
        # F-SCANC-1 (operator decision packet v1, 2026-08-26): the
        # `resolved_action` round local and the `gate_aborted` carrier were
        # RETIRED with the SKIP_ITER / SKIP_TO_FORMAL gate actions. The
        # names STAY forbidden: the ruling is "no new wiring for a dead
        # authority surface", and a binding field is exactly the wiring
        # route this set exists to refuse.
        "resolved_action",
        "round_succeeded",
        "gate_aborted",
        "skipped_formal_for_no_valid_winner",
        "scope_violation_reason",
        "evidence_channel_failure",
        "physical_rejections_buffer",
        "train_results",
        "training_results",
        "score_results",
        "score_table",
        "time_check",
        "resource_check",
        "trial_config",
        "train_sample_set",
        "eval_sample_set",
    }
)


@dataclass(frozen=True)
class RunBindings:
    """The authorities and services this run bound during startup.

    Every field is established before the round loop begins and its identity
    does not change afterwards. That is the membership rule, and it is the only
    one: a value that varies per round or per attempt does not belong here even
    if passing it would be convenient.

    Deliberately NOT a general-purpose context. It carries no counters, no
    current plan, no current results and no termination flags —
    :data:`FORBIDDEN_BINDING_FIELDS` is checked at construction so that stays
    true as the code evolves.
    """

    # --- input and services -------------------------------------------------
    agent_input: Any
    """The validated, startup-normalized ``HyperparamTuningInput``."""

    sandbox: Any
    """The execution sandbox for training / inference / scoring."""

    brain: Any
    """The ``LLMBridge`` the planner and reflector speak through."""

    custom_loss_inventory: Any
    """The task-compatible loss inventory shared by both planner prompts."""

    # --- run-bound task authorities ----------------------------------------
    run_profile: Any
    """The resolved ``DatasetProfile`` (Step 05a)."""

    run_model_io: Any
    """The run-bound ``ModelIOContract`` (Step 05b), or ``None``."""

    run_deliverable_spec: Any
    """The run's Deliverable Contract (Step 05c)."""

    run_metric: Any
    """The bound ``EvaluationMetric`` handle (Step 06)."""

    run_secondary_metrics: Any
    """The run's DECLARED observational secondary metrics (Step 10 / P2b).

    A tuple, empty for an un-composed run and for a composed task that
    declares none. Resolved once at the same startup site as ``run_metric``
    and never re-derived — and never an operand of an ordering decision:
    ``run_order`` below is the ONE authority, and it reads the PRIMARY spec.
    """

    run_order: Any
    """The ONE ``MetricOrder`` derived from ``run_metric.spec`` (Step 07 07b)."""

    run_task_render: Any
    """The authority-rendered task tokens for the prompts (Step 07 07b, P2)."""

    # --- resolved run facts -------------------------------------------------
    run_name: str
    workspace: str
    file_index: int
    max_rounds: int
    model_type_setting: str
    trial_allowed: bool
    resolved_data_scope: list[int]
    scope_is_partial: bool

    # --- planner context ----------------------------------------------------
    expert_advice_str: str
    config_manual_data: Any
    model_description: Any

    # --- budgets ------------------------------------------------------------
    trial_vram_budget: Any
    formal_vram_budget: Any
    trial_time_budget: Any
    formal_time_budget: Any

    # --- round/attempt budget settings, resolved once at startup ------------
    attempts_per_round_setting: int
    attempts_per_formal_round_setting: int
    max_fail_rounds_setting: int

    # --- the formal-comparison reference, resolved ONCE per run -------------
    # (`_resolve_formal_comparison_thresholds` runs exactly once, before the
    # loop, so the gates, the banner and the persisted output provably consume
    # the same values — that single-resolution property is why these belong
    # here rather than being recomputed per round.)
    formal_reference_score: Any
    formal_reference_source: str
    resolved_skip_formal_threshold: Any
    resolved_bypass_formal_threshold: Any

    # --- measured environment, resolved once at startup ---------------------
    hardware_context: Any
    device_identity: Any
    time_data_dir: Any
    anchor_map_data: Any
    reference_scores: Any

    # --- run provenance -----------------------------------------------------
    started_at: str
    health_checks_config_source: Any
    health_config_sha256: Any

    # --- Step 12 / PR-12d (F-12d-5) -----------------------------------------
    run_deliverable_naming: Any = None
    """The run's DELIVERABLE NAMING authority — ALWAYS present.

    ``run_deliverable_spec`` became ``DeliverableSpec | None`` at D2: its
    STORAGE half is TIDMAD-physical, so a task declaring no such geometry has
    none. NAMING has no such dependency — it is
    ``resolve_deliverable_naming()``, the run's declared naming or the shipped
    default — and carrying it separately is what stops every consumer from
    reaching through an OPTIONAL value for a MANDATORY one.

    Defaulted so it sits last and every existing construction site is
    unchanged; production always supplies it.
    """

    run_scientific_gate_ids: Any = None
    """The RUN's own scientific gate set, or ``None`` — F-12d-30.

    Resolved ONCE at run scope through ``resolve_run_scientific_gate_ids``
    (Step 10 / P5+P6 W6, finding F-P56-2) and carried here rather than
    re-derived per record. The zero-argument default composes with
    ``LEGACY_OMITTED``, i.e. TIDMAD's set — correct for an un-composed run and
    wrong for a composed one, where it makes the process bind TIDMAD's Health
    family after the run has already bound its own and the Step-08b run-scope
    guard then refuses an otherwise-complete run at finalize.

    It lives on the bindings, not on the input projection, because PR-12a C2
    pins that ``records.py`` reads run-scoped AUTHORITIES and never
    ``task_composition_ref`` — the F-11-C10-a lesson, where a stamp reading
    the projection instead of the run's own authority made a composed chain
    refuse its own output. ``None`` is an un-composed run and resolves the
    legacy default exactly as before.
    """

    run_task_data_path: Any = None
    """The run-bound task codec used by Health payload view providers.

    This is an authority resolved at startup, not mutable attempt state. It is
    carried explicitly so the round boundary never re-reads ambient binding
    state or reconstructs a task's artifact layout.
    """

    def __post_init__(self) -> None:
        offending = sorted(FORBIDDEN_BINDING_FIELDS & {f.name for f in fields(self)})
        if offending:
            raise TypeError(
                f"RunBindings must not carry mutable lifecycle state: {offending}. "
                "Round/attempt counters, the current plan, the current results and "
                "the termination flags stay explicit in run(); putting them here "
                "turns a bindings object into the god context this design forbids."
            )


@dataclass(frozen=True)
class PreparedAttempt:
    """What planning produced for ONE attempt — its complete product.

    Every field is something planning DECIDED or RESOLVED: the validated plan
    after every override, the round's trial configuration and materialized
    sample sets, the identity the record will carry, and the parameter dicts
    execution will run with. Nothing else is smuggled in: this is a lifecycle
    product, not a parameter bag for whatever the next phase finds awkward.
    """

    plan: Any
    trial_config: Any
    active_params: Any
    record_params: Any
    exp_id: Any
    hypothesis: Any
    model_type: Any
    model_config: Any
    memory_history: Any
    train_sample_set: Any
    eval_sample_set: Any
    #: Step 12 / PR-12bc B5 — the task-built scopes for this attempt, or
    #: an empty ``AttemptScopes`` when the run is un-composed. ADDITIVE:
    #: the sample sets above are unchanged on both paths, because their
    #: consumers are unchanged until B6 (D-BC-13).
    task_scopes: Any
    train_psd_segments: Any
    eval_psd_segments: Any
    ordering: ResolvedOrdering
    planned_trial_strategy: Any
    planned_eval_strategy: Any
    strategy_normalization_reason: Any
    cfg_trial_portion: Any
    cfg_train_portion: Any
    cfg_eval_portion: Any
    _planned_portions: Any
    #: Lane D / F15 — the ``ExecutionProvenance`` for this attempt: every plan
    #: field whose AUTHORED value differs from the one that will EXECUTE.
    #: Empty when resolution changed nothing. Belongs here by the same rule as
    #: everything above — it is something planning RESOLVED, and it is the only
    #: thing that makes ``hypothesis`` (authored earlier, never updated)
    #: safe for a downstream narrator to read.
    execution_provenance: Any
    #: 01A3c — task-resolved custom-loss contract carried to every execution
    #: route. Transient by design: it is not attempt eligibility or record
    #: state, and ``None`` preserves builtin and uncomposed behavior.
    expected_custom_loss_snapshot: CapabilityContractSnapshot | None = None


@dataclass(frozen=True)
class RunExitSnapshot:
    """The end-of-loop facts the final output is built from.

    The counterpart to :class:`RunBindings`, and the reason that class can stay
    immutable: these ARE the mutable lifecycle values, captured once, at the
    single moment the round loop ends. Snapshotting them here keeps them
    explicit — they travel as a named set with a stated purpose rather than
    hiding inside a bindings object that claims to be stable.

    Eight fields, each a fact only the finished loop can state.
    (``gate_aborted`` was the ninth — retired with SKIP_ITER, F-SCANC-1:
    its only writer was the run loop's unreachable skip branch.)
    """

    completed_rounds: int
    total_attempts: int
    consecutive_fails: int
    scope_violation_reason: str | None
    evidence_channel_failure: str | None
    skipped_formal_for_no_valid_winner: bool
    physical_rejections_buffer: list
    last_plan: Any
    """The most recent validated plan, or ``None`` if none ever validated."""


class AttemptSignal(Enum):
    """What an execution subphase tells the attempt loop to do next.

    The tuner's control flow is the part of it that is genuinely hard to get
    right, so moving a phase out of ``run()`` must not blur it. Each subphase
    below used to end in a bare ``continue`` or ``break``; as a function it
    returns the same decision as a value, and ``run()`` performs the actual
    jump. The translation is 1:1 — 11 ``continue`` sites became
    :attr:`NEXT_ATTEMPT`, 4 ``break`` sites became :attr:`END_ROUND` — so the
    retry and round semantics are unchanged by construction, and the
    differential oracle is the evidence.
    """

    PROCEED = "proceed"
    """The phase completed; the attempt continues into the next phase."""

    NEXT_ATTEMPT = "next_attempt"
    """Was ``continue``: this attempt is over, the round is not."""

    END_ROUND = "end_round"
    """Was ``break``: no further attempt in this round can succeed."""


@dataclass
class AttemptStage:
    """How far the current attempt got — one deliberately mutable stage name.

    ``run()``'s exception handler records ``failure_stage`` on the failure
    record and classifies the exception by it. That value is written by the
    phase that is executing when the exception is raised, so it cannot travel
    back in a return value: on the raising path there is no return.

    A single mutable field is the honest mechanism. It is not a state bag —
    it carries one fact, with one writer at a time, and it exists because
    exceptions do not return.
    """

    name: str


@dataclass
class AttemptOrdering:
    """Selected configuration retained when preparation raises instead of returning.

    Allocate before each attempt; planning writes immediately after resolution.
    This is provenance only, not evidence that training visited any samples.
    """

    selected: ResolvedOrdering | None = None


@dataclass(frozen=True)
class AttemptIdentity:
    """Which attempt this is. Three facts, passed together because they are
    always used together — in prints, in records and in gate calls."""

    round_index: int
    attempt_in_round: int
    is_formal_round: bool


@dataclass(frozen=True)
class _PhaseOutcome:
    """Shared shape: a control decision, plus whatever the phase produced.

    Product fields default to ``None`` because a phase that ends in
    :attr:`AttemptSignal.NEXT_ATTEMPT` or :attr:`~AttemptSignal.END_ROUND`
    produced nothing — and ``run()`` acts on the signal before it reads any
    product, exactly as the original code jumped before reaching them.
    """

    signal: AttemptSignal = AttemptSignal.PROCEED
    scope_violation_reason: str | None = None

    @classmethod
    def next_attempt(cls, **kw: Any):
        return cls(signal=AttemptSignal.NEXT_ATTEMPT, **kw)

    @classmethod
    def end_round(cls, **kw: Any):
        return cls(signal=AttemptSignal.END_ROUND, **kw)


@dataclass(frozen=True)
class AdmissionOutcome(_PhaseOutcome):
    """Product of admission + preflight: may this candidate physically run,
    and under which resolved budgets."""

    chosen_vram_budget: Any = None
    resource_check: Any = None
    time_check: Any = None


@dataclass(frozen=True)
class TrainingOutcome(_PhaseOutcome):
    """Product of training and the training-result contract boundary."""

    train_status: Any = None
    train_time: Any = None
    training_results: Any = None


@dataclass(frozen=True)
class AttemptExecution(_PhaseOutcome):
    """Product of inference, scoring and the health gates — the attempt's
    executed result, which reflection and the record are built from."""

    failure_reason: Any = None
    inf_status: Any = None
    inference_time: Any = None
    is_degenerate: Any = None
    metric_payload: Any = None
    # Step 10 / P2b — the observational secondaries' three outcomes, carried
    # beside `metric_payload` for the record builder. Defaulted empty so every
    # phase outcome constructed elsewhere (and every pre-P2b caller) states the
    # honest "no secondary evidence" rather than None-meaning-unknown.
    secondary_metric_results: Any = ()
    secondary_metric_refusals: Any = ()
    secondary_metric_errors: Any = field(default_factory=dict)
    score_results: Any = None
    score_table: Any = None
    scoring_time: Any = None
    train_results: Any = None
    training_diagnosis: Any = None
