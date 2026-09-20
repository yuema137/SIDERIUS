"""Task-declared observable metrics — the typed dynamic/static authority.

`R-OBS-1` / `D-BUD-16`. A task declares quantities it wants OBSERVED beside
the objective it is trained against and the Golden Metric it is scored by.
The framework never enumerates them: it owns the two TYPES and the two
execution points, and the task owns every name and every piece of arithmetic.

**The dynamic/static distinction is a TYPE, not a convention** (the row's
level 2). It is not a string field on one class, and it is not a naming
rule — the two are separate abstract bases with DIFFERENT method
signatures, because they see genuinely different things:

===========  ===================================  ==========================
acquisition  when it executes                     what it sees
===========  ===================================  ==========================
dynamic      DURING training, once per epoch,     a stream of
             on the validation pass that          ``(output, target)``
             already runs                         batches
static       AFTER training, exactly once         the trained model
===========  ===================================  ==========================

That table is `D-BUD-16`'s ``compute_consequence_only`` clause verbatim:
"dynamic: may execute DURING training / static: execute from the trained
model/data AFTER training". Because the two bases declare different
abstract methods, an implementation cannot satisfy the wrong one by
accident, and :func:`acquisition_of` DERIVES the label from the type rather
than reading a declared string. A manifest that lists a static
implementation under ``dynamic_observables:`` is refused at composition —
that refusal is what makes this a type and not a convention.

**Scope, stated honestly.** A static observable reads the TRAINED MODEL.
It is deliberately NOT given the deliverable or the dataset: deliverable-
derived static evaluation already has exactly one owner in this framework —
the ``secondary_metrics:`` family and its single
``evaluate_declared_secondaries`` authority — and a second one would be the
two-authorities defect this codebase has paid for repeatedly. `D-BUD-16`'s
"model/data" is therefore closed here on its MODEL leg; the data leg is
`secondary_metrics:`, which the `R-OBS-1` audit itself grades
``FULLY_IMPLEMENTED``.

Observables are OBSERVATIONAL. Nothing here may ever become an operand of
an ordering expression — not a ranking, not a champion selection, not a
skip/bypass threshold. `D-BUD-16`'s prohibition ("do NOT redefine
observable metrics as a Part 6 budget mechanism") is the same rule seen
from the budget area.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Final, Literal

from core.local_code.failure import raise_if_code_package_failure

#: The two acquisition labels. DERIVED from an implementation's type by
#: :func:`acquisition_of` — never declared by a task, never parsed from a
#: name, and never stored as the thing that decides behaviour.
OBSERVABLE_ACQUISITION_DYNAMIC: Final = "dynamic"
OBSERVABLE_ACQUISITION_STATIC: Final = "static"

ObservableAcquisition = Literal["dynamic", "static"]


class ObservableError(RuntimeError):
    """A declared observable could not produce a value.

    Raised by this module's evaluation boundaries when an implementation
    raises, or returns something that is not a finite real number. It is a
    DIAGNOSTIC failure, never a training failure: the callers in the
    training engine record the absence and let the run continue, because an
    observational quantity that cannot be computed must not be able to kill
    a training attempt (the ``secondary_metrics`` precedent, Step 10 / P2b).
    """


class DynamicObservable(ABC):
    """Acquisition **DYNAMIC** — executes DURING training.

    One instance is reset at the start of every per-epoch validation pass,
    fed each batch of that pass, and asked for a single float at the end.
    The result is one point in a per-epoch series, so a run of ``N`` epochs
    yields ``N`` values under this observable's declared name.

    It rides the validation pass the trainer ALREADY runs (Step 07a's R3),
    so declaring one costs no additional forward pass over the data — only
    the observable's own arithmetic. That is the bounded compute
    consequence `D-BUD-16` describes.

    **Contract obligations on an implementation.**

    * :meth:`update` runs inside ``model.eval()`` + ``torch.no_grad()`` and
      MUST NOT mutate the model, the criterion, the tensors it is handed, or
      any global RNG state. The validation pass is transactional and
      verifies the criterion's state afterwards; an observable that mutates
      training state breaks a guarantee that is not its to spend.
    * :meth:`value` must return a finite ``float``.
    * Instances are constructed once per run and reused across epochs, so
      :meth:`reset` must fully clear per-epoch accumulation.
    """

    @abstractmethod
    def reset(self) -> None:
        """Discard accumulation from the previous epoch."""

    @abstractmethod
    def update(self, output: Any, target: Any) -> None:
        """Accumulate one validation batch.

        Args:
            output: the model's output for the batch, exactly as the model
                produced it (no dtype or shape normalization is applied).
            target: the batch's targets, as the task's data path yielded
                them.
        """

    @abstractmethod
    def value(self) -> float:
        """The finite scalar for the epoch just accumulated."""


class StaticObservable(ABC):
    """Acquisition **STATIC** — executes from the trained model AFTER training.

    Called exactly once, after the final optimizer step, with the trained
    model. It produces a single float, not a series.

    An implementation MUST NOT mutate the model: this runs after training
    but before the model is serialized, so a mutation here would be written
    to disk as the run's deliverable-producing weights.
    """

    @abstractmethod
    def compute(self, model: Any) -> float:
        """The finite scalar this observable reads off the trained model."""


def acquisition_of(implementation: object) -> ObservableAcquisition:
    """The acquisition label DERIVED from an implementation's type.

    This function is the reason the distinction is a type. Nothing in the
    framework stores an acquisition string that could drift from the object
    it describes: the label is recomputed from ``isinstance`` wherever it is
    needed.

    Raises:
        ObservableError: the object is neither kind, or is somehow both
            (a class inheriting both bases has no single execution point,
            so the framework refuses to pick one for it).
    """
    is_dynamic = isinstance(implementation, DynamicObservable)
    is_static = isinstance(implementation, StaticObservable)
    if is_dynamic and is_static:
        raise ObservableError(
            f"{type(implementation).__name__} is both a DynamicObservable and a "
            "StaticObservable. The two bases name different execution points — "
            "during training, and once from the trained model afterwards — so an "
            "implementation that claims both leaves the framework to guess when "
            "it should run. Declare two implementations instead."
        )
    if is_dynamic:
        return OBSERVABLE_ACQUISITION_DYNAMIC
    if is_static:
        return OBSERVABLE_ACQUISITION_STATIC
    raise ObservableError(
        f"{type(implementation).__name__} is neither a DynamicObservable nor a StaticObservable."
    )


@dataclass(frozen=True, slots=True)
class DeclaredDynamicObservable:
    """One ``dynamic_observables:`` entry, resolved.

    ``name`` comes from the DECLARATION, not from the implementation: it is
    the key the per-epoch series is persisted under and the string the
    manifest's fingerprint pins, so the task states it where a reader of the
    manifest can see it. The implementation supplies arithmetic only — the
    same division of authority ``metric:`` uses between a declaration's id
    and an ``EvaluationMetric``.
    """

    name: str
    implementation: DynamicObservable


@dataclass(frozen=True, slots=True)
class DeclaredStaticObservable:
    """One ``static_observables:`` entry, resolved. See the dynamic sibling."""

    name: str
    implementation: StaticObservable


@dataclass(frozen=True, slots=True)
class RunObservables:
    """The observables ONE run declared, in manifest order.

    Empty is the ordinary state and the one every run that exists today is
    in: a task that declares no observables gets this carrier with both
    tuples empty, and every downstream site treats it exactly as it treated
    the absence of the feature.
    """

    dynamic: tuple[DeclaredDynamicObservable, ...] = ()
    static: tuple[DeclaredStaticObservable, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.dynamic or self.static)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(d.name for d in self.dynamic) + tuple(s.name for s in self.static)


def _finite_float(value: object, *, name: str, what: str) -> float:
    """Coerce an implementation's return to a finite float, or refuse."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ObservableError(
            f"observable {name!r} ({what}) returned {value!r} "
            f"({type(value).__name__}); a real number is required."
        )
    result = float(value)
    if not math.isfinite(result):
        raise ObservableError(
            f"observable {name!r} ({what}) returned a non-finite value ({result!r}). "
            "A non-finite observation is not evidence — it is the absence of one."
        )
    return result


class DynamicObservableEpoch:
    """The per-epoch accumulation boundary the validation pass drives.

    Extracted as its own typed object rather than inlined into
    ``_validation_pass``: the pass is a transactional measurement with a
    state census on both sides of it, and growing it a second concern would
    put per-task arithmetic inside the very window whose invariance it
    certifies. The pass calls three methods and never branches on what a
    task declared.

    A declaration that is EMPTY makes every method a no-op, so a run with no
    dynamic observables executes the same instructions it did before this
    feature existed apart from three cheap calls on an empty tuple.
    """

    __slots__ = ("_declared", "_failed")

    def __init__(self, declared: tuple[DeclaredDynamicObservable, ...] = ()) -> None:
        self._declared = declared
        self._failed: dict[str, str] = {}

    def __bool__(self) -> bool:
        return bool(self._declared)

    def start_epoch(self) -> None:
        """Reset every declared observable before an epoch's pass."""
        for declared in self._declared:
            try:
                declared.implementation.reset()
            except Exception as exc:  # diagnostic, never fatal
                raise_if_code_package_failure(exc)
                self._failed[declared.name] = f"reset raised {type(exc).__name__}: {exc}"

    def observe(self, output: Any, target: Any) -> None:
        """Feed one validation batch to every observable still healthy.

        A failure LATCHES for the rest of the RUN, not just the epoch —
        ``start_epoch`` deliberately does not clear ``_failed``. Two reasons,
        and the second is why the choice is not arbitrary:

        * re-entering an implementation that already raised mid-stream is how
          a diagnostic turns into a crash loop, once per batch per epoch;
        * clearing it would let a transiently-failing observable resume and
          produce a series with a HOLE — shorter than the epoch axis, with the
          missing point at an unknown index — which the producer's alignment
          filter drops anyway. The latch reaches the same outcome without
          re-entering broken code, so nothing is lost by it.
        """
        for declared in self._declared:
            if declared.name in self._failed:
                continue
            try:
                declared.implementation.update(output, target)
            except Exception as exc:  # diagnostic, never fatal
                raise_if_code_package_failure(exc)
                self._failed[declared.name] = f"update raised {type(exc).__name__}: {exc}"

    def finish_epoch(self) -> dict[str, float]:
        """The epoch's values, by declared name.

        An observable that raised, or produced a non-finite or non-numeric
        value, is ABSENT from the mapping rather than represented by a
        sentinel. The caller turns a missing name into a dropped series —
        an honest absence, never a fabricated point.
        """
        values: dict[str, float] = {}
        for declared in self._declared:
            if declared.name in self._failed:
                continue
            try:
                raw = declared.implementation.value()
            except Exception as exc:  # diagnostic, never fatal
                raise_if_code_package_failure(exc)
                self._failed[declared.name] = f"value raised {type(exc).__name__}: {exc}"
                continue
            try:
                values[declared.name] = _finite_float(raw, name=declared.name, what="dynamic")
            except ObservableError as exc:
                self._failed[declared.name] = str(exc)
        return values

    @property
    def failures(self) -> dict[str, str]:
        """Why each absent observable is absent. Diagnostics only."""
        return dict(self._failed)

    def accept_external_epoch(
        self, values: dict[str, float], failed_names: tuple[str, ...]
    ) -> dict[str, float]:
        """Validate a complete aggregate epoch without executing task code here."""
        declared = {item.name for item in self._declared}
        failed = set(failed_names)
        if (
            len(failed) != len(failed_names)
            or set(values) & failed
            or set(values) | failed != declared
            or not set(self._failed) <= failed
        ):
            raise ObservableError(
                "external observable outcomes contradict run declarations/history"
            )
        checked = {
            name: _finite_float(value, name=name, what="dynamic") for name, value in values.items()
        }
        # Validate everything before changing the failure latch or history.
        self._failed.update({name: "private observation failed" for name in failed})
        return checked


def compute_static_observations(
    declared: tuple[DeclaredStaticObservable, ...],
    model: Any,
) -> tuple[dict[str, float], dict[str, str]]:
    """Run every static observable once against the trained model.

    Returns ``(values, failures)``. As with the dynamic side, an
    implementation that raises or returns a non-finite value is ABSENT from
    ``values`` and explained in ``failures`` — it never becomes a sentinel
    number and it never propagates out of this boundary, because a failed
    observation must not be able to fail a training attempt that otherwise
    succeeded.
    """
    values: dict[str, float] = {}
    failures: dict[str, str] = {}
    for entry in declared:
        try:
            raw = entry.implementation.compute(model)
        except Exception as exc:  # diagnostic, never fatal
            raise_if_code_package_failure(exc)
            failures[entry.name] = f"compute raised {type(exc).__name__}: {exc}"
            continue
        try:
            values[entry.name] = _finite_float(raw, name=entry.name, what="static")
        except ObservableError as exc:
            failures[entry.name] = str(exc)
    return values, failures


# ---------------------------------------------------------------------------
# The run-scoped session — the ONE boundary the training engine talks to
# ---------------------------------------------------------------------------


class RunObservationSession:
    """The whole observable lifecycle for ONE training run, behind one type.

    **Why this exists as a type rather than a few statements in the engine.**
    ``run_experiment_streaming`` is a 735-line orchestrator with 59 branch
    nodes, and both facts are pinned by an executable structural guard
    (``test_step12_pr12bc_b0_baselines.py``) that refuses a new branch family
    and freezes the parameter list. Threading an observables argument through
    it and inlining the per-epoch bookkeeping broke three of those assertions
    at once — which is the guard working, and the answer CLAUDE.md's
    decomposition rule gives: *identify the responsibility, extract a typed,
    independently testable boundary, put the feature inside it, leave the
    orchestrator sequencing.*

    So every method here is UNCONDITIONAL at the call site and a no-op when
    the run declared nothing. The engine gains method calls, not branches:

    ```text
    session = active_observation_session()      once, before the epoch loop
      -> session.start_epoch()                  each epoch, before validation
      -> session.observe(output, target)        each validation batch
      -> session.finish_epoch()                 each epoch, after validation
    session.finalize(model)                     once, after the last epoch
    session.dynamic_series() / static_summary() building the payload
    ```

    The session is resolved from a RUN-SCOPED BINDING rather than passed as an
    argument. That is the same mechanism ``dataset_profile`` and
    ``task_data_path`` already use to reach this engine, and it is what keeps
    the frozen parameter list frozen — a guard whose whole purpose is to stop
    this function acquiring another responsibility should not be satisfied by
    giving it one more argument.
    """

    __slots__ = ("_epoch", "_finalized", "_series", "_static", "_static_failures", "_static_values")

    def __init__(self, observables: RunObservables | None = None) -> None:
        resolved = observables or RunObservables()
        self._epoch = DynamicObservableEpoch(resolved.dynamic)
        self._series: dict[str, list[float]] = {}
        self._static: tuple[DeclaredStaticObservable, ...] = resolved.static
        self._static_values: dict[str, float] = {}
        self._static_failures: dict[str, str] = {}
        self._finalized = False

    def __bool__(self) -> bool:
        return bool(self._epoch) or bool(self._static)

    # -- per-epoch, driven by the validation pass ---------------------------

    def start_epoch(self) -> None:
        self._epoch.start_epoch()

    def observe(self, output: Any, target: Any) -> None:
        self._epoch.observe(output, target)

    def finish_epoch(self) -> None:
        """Close the epoch and append each produced value to its series.

        A name absent from this epoch's values contributes no point, so its
        series ends up shorter than the epoch axis and the producer drops it
        whole. The hole is never filled here.
        """
        for name, value in self._epoch.finish_epoch().items():
            self._series.setdefault(name, []).append(value)

    def accept_external_epoch(
        self, values: dict[str, float], failed_names: tuple[str, ...]
    ) -> None:
        """Append authorized aggregates; preserve the native failure latch."""
        for name, value in self._epoch.accept_external_epoch(values, failed_names).items():
            self._series.setdefault(name, []).append(value)

    # -- after the final optimizer step -------------------------------------

    def finalize(self, model: Any) -> None:
        """Run the static family against the TRAINED model.

        Called after the final optimizer step and BEFORE the model is
        serialized, so what is observed is the model this attempt actually
        produced.

        IDEMPOTENT. A static observable is a measurement of one model, not an
        accumulator, so a second call must not re-enter task code and cannot
        change the answer.
        """
        if self._finalized:
            return
        self._finalized = True
        self._static_values, self._static_failures = compute_static_observations(
            self._static, model
        )
        for name, reason in self._static_failures.items():
            print(f"[observable] static {name!r} produced no value: {reason}", flush=True)

    # -- payload ------------------------------------------------------------

    def dynamic_series(self) -> dict[str, list[float]]:
        """The per-epoch series, by declared name. ``{}`` when none."""
        return {name: list(series) for name, series in self._series.items()}

    def static_summary(self, key: str) -> dict[str, Any]:
        """``{key: values}``, or ``{}`` when nothing was observed.

        Returning a mapping to ``update()`` rather than a value to assign is
        deliberate: the caller writes NO key at all for a run that declared no
        static observable, which is what keeps its results JSON byte-identical
        — and it does so without an ``if`` in the orchestrator.

        ``key`` is supplied by the caller because the results-payload
        vocabulary belongs to ``training_history``; this module owns the
        observables, not the wire format they ride on.
        """
        return {key: dict(self._static_values)} if self._static_values else {}

    @property
    def failures(self) -> dict[str, str]:
        """Every absent observable and why. Diagnostics only."""
        return {**self._epoch.failures, **self._static_failures}


# ---------------------------------------------------------------------------
# The run-scoped binding
# ---------------------------------------------------------------------------

#: The un-declared state, shared. Safe as a singleton because
#: :class:`RunObservables` is a frozen dataclass of empty tuples — but it is
#: still not a ContextVar DEFAULT (B039), which is why the default is ``None``
#: and the emptiness is supplied on read.
_NO_OBSERVABLES = RunObservables()

_ACTIVE_RUN_OBSERVABLES: ContextVar[RunObservables | None] = ContextVar(
    "siderius_active_run_observables", default=None
)


@contextmanager
def bind_run_observables(observables: RunObservables) -> Iterator[RunObservables]:
    """Activate a run's declared observables for the enclosing scope.

    Token-reset in a ``finally``, the same shape every other run-scoped
    binding in this codebase uses, so it unwinds on an exception too.
    """
    token = _ACTIVE_RUN_OBSERVABLES.set(observables)
    try:
        yield observables
    finally:
        _ACTIVE_RUN_OBSERVABLES.reset(token)


def resolve_bound_run_observables() -> RunObservables:
    """The bound observables, or an EMPTY carrier when nothing is bound.

    Empty IS the answer, not a fallback — the same contract
    ``resolve_bound_run_secondary_metrics`` states. A run that declared no
    observable and a run with no composition at all are the same state here,
    and neither has anything to fall back to.
    """
    return _ACTIVE_RUN_OBSERVABLES.get() or _NO_OBSERVABLES


def active_observation_session() -> RunObservationSession:
    """A session over whatever this run declared. Never ``None``."""
    return RunObservationSession(resolve_bound_run_observables())


@contextmanager
def child_observables_binding(manifest_path: str | None) -> Iterator[RunObservables]:
    """Compose a CHILD's observables from the transported manifest and bind them.

    `R-OBS-1` level 3, the subprocess half. The parent already emits
    ``--task_manifest`` to all three children (Step 12 / PR-12bc C3), so
    nothing new crosses the process boundary — the child composes the same
    declaration the parent composed, through the same authority. That matters
    for more than tidiness: an observable is a live object with per-epoch
    state, and no argv could carry one.

    ABSENT manifest (every legacy, un-composed run) binds an EMPTY carrier,
    which every consumer treats exactly as it treated the absence of this
    feature.

    There is deliberately NO fallback on the supplied leg: a manifest that
    reached this child and will not compose raises, and the subprocess
    terminates — the rule the scoring child's metric composition already
    follows, because silently training without the observables a composed run
    declared is indistinguishable from success.

    Imported lazily for the reason the sibling child-side resolvers give: the
    composition layer sits ABOVE this one, and only a composed run reaches it.
    """
    if manifest_path is None:
        with bind_run_observables(RunObservables()) as bound:
            yield bound
        return
    from workflows.task_composition import compose_observables_from_manifest

    with bind_run_observables(compose_observables_from_manifest(manifest_path)) as bound:
        yield bound
