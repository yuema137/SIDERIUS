"""TaskDataPath — the executable data-path seam (D14-1, parent design FROZEN rev 3).

The ONE place the framework asks a bound task for its executable data
behaviour: "give me the training/validation dataset for this scope", "persist
this output as your deliverable", "decode your deliverable into the payload
the evaluation authority scores". TIDMAD's answers are its existing code,
relocated behind this seam at byte parity (child design C2a/C2b); a new task
binds by REGISTRATION plus one configuration field, with zero edits to
generic core.

Design authority: ``docs/design/generic_framework_upgrade/
d14_executable_data_path.md`` (parent, FROZEN rev 3) and
``…/d14_executable_data_path/pr_d14_1_task_data_path_seam.md`` (child, FROZEN
rev 2). The load-bearing decisions live there; the ones a reader of this file
needs:

**Sample semantics (parent Amendment 1).** Datasets yield
``(model_input, supervision_target)``. ``model_input`` must satisfy the bound
``ModelIOContract`` INPUT boundary. ``supervision_target`` is consumed by the
already-bound training objective and is NOT required to share the model
output's shape, dtype, rank or representation — Pets is the canonical case
(``[37]`` logits out, a scalar class index as target).

**Codec ownership (parent Amendment 2).** An implementation MAY own the codec
between model/task values and its task-native deliverable bytes, and the
decode back into an evaluation payload. It MUST NOT own metric selection,
direction, scoreability, thresholds, aggregation, the training objective, or
interpretation — the output path terminates at the Step-06 evaluation
authority, always.

**Fail-closed binding (parent Amendment 3; child §4.2 truth table).** The
TIDMAD default exists ONLY as the legacy regime-A compatibility path — the
launch surfaces that predate task binding, discriminated by the ABSENCE of a
:class:`TaskBindingContext`, never by a task name. An explicit context whose
id is absent, an unknown id, or a malformed implementation FAILS CLOSED.

**Scope opacity (parent §3; issue #225).** ``scope`` is task-owned vocabulary
(TIDMAD ``{file: [segments]}``; Pets manifest rows; DAVIS clip identities).
The framework passes it through untouched. The exact-materialization
obligation — a declared scope materializes exactly, failing closed otherwise —
is every implementation's to discharge in its own vocabulary; the framework
deliberately has no scope-aware checker.

**One configuration authority (child §4.1).** The internal subprocess argv
flag below carries the ALREADY-RESOLVED binding across a process boundary
(the ``--dataset_profile_json`` precedent). It is emitted from the binding by
:func:`transport_argv` — which takes the implementation, not a free string —
and it is never an operator-facing selection knob.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:  # torch is heavyweight; the seam only names the type
    from torch.utils.data import Dataset


class TaskDataPathResolutionError(RuntimeError):
    """A task data-path binding could not be resolved fail-closed.

    Raised for: an explicit binding context with no id; an unknown id; a
    regime-A resolution when no compatibility implementation is registered.
    The message always names the offending id (or its absence) and the
    currently registered set, so an operator can act on it directly.
    """


class TaskDataPathRegistrationError(RuntimeError):
    """An implementation was refused at registration time (child §4.2 row 5:
    malformed implementations fail BEFORE any execution, never at first use)."""


class ValidationScopeError(RuntimeError):
    """The declared validation scope did not materialize EXACTLY (design §3.4b).

    A missing VALIDATION-family file, a segment index beyond the file, zero
    requested rows, or a per-epoch row count that differs from the request
    is a validation EXECUTION failure: the attempt fails closed (non-zero
    exit → the executor's subprocess-error path → ``error_training``). No R3
    is emitted and ``NaN`` is never used to stand in for a missing scope —
    ``NaN`` stays reserved for numerical evidence.

    Owned here since D14-1 C3: every ``TaskDataPath.validation_dataset``
    implementation discharges the exact-materialization obligation in its own
    scope vocabulary and raises THIS type; the engine's preflight checks
    raise it too (re-exported there for compatibility).
    """


# ---------------------------------------------------------------------------
# Parameter carriers — framework-level knobs the existing call sites pass.
# ---------------------------------------------------------------------------
# These mirror EXISTING call-site arguments only (child §8: anything new here
# is a stop). They are function-argument carriers, never serialized to config
# (§20.6: no new configuration hierarchy). Task-vocabulary values — TIDMAD's
# seg_size, its DatasetProfile — are deliberately ABSENT: an implementation
# obtains its own vocabulary through its own authorities at binding time.


class EpochSamplingParams(BaseModel):
    """Per-epoch sampling knobs for ``training_dataset``.

    Mirrors ``train_engine_sandbox.py:1442-1460``: the per-epoch seed
    (``base_seed`` / ``base_seed + ep`` — the freeze-subsample choice is the
    CALLER's, made before this carrier is built), the subsample fraction, and
    the validation-envelope ceiling (07c C6).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    data_dir: str = Field(min_length=1)
    epoch_seed: int | None = None
    train_portion: float | None = Field(default=None, gt=0.0, le=1.0)
    max_samples: int | None = Field(default=None, ge=1)


class EvalMaterializationParams(BaseModel):
    """Knobs for ``validation_dataset`` (``train_engine_sandbox.py:905-935``).

    Deliberately minimal: the validation scope arrives already clamped
    (07c's ``clamp_validation_scope`` acts on the SCOPE upstream), so the
    only framework-level knob at this boundary today is where the data lives.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    data_dir: str = Field(min_length=1)


class DeliverableWriteRequest(BaseModel):
    """Where and under what identity ``write_deliverable`` persists.

    Field set finalized when C4 relocates the inference writer; today it
    carries what ``inference_single.py:824,983`` demonstrably uses — the
    output location and the run/experiment/model identity the deliverable
    naming authority needs (``model_type`` added at C2b from the writer-site
    audit: ``DeliverableNaming.name`` requires it; child ledger C2b).
    Additions during C4 are recorded in the child ledger.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    output_dir: str = Field(min_length=1)
    exp_id: str = Field(min_length=1)
    run_name: str = Field(min_length=1)
    model_type: str = Field(min_length=1)


class EvaluationReadRequest(BaseModel):
    """What ``read_evaluation_payload`` decodes for the Step-06 authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    deliverable_dir: str = Field(min_length=1)
    exp_id: str = Field(min_length=1)
    run_name: str = Field(min_length=1)
    model_type: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------


@runtime_checkable
class TaskDataPath(Protocol):
    """The four-method executable data-path contract (parent §3, FROZEN).

    Implementations own HOW bytes become ``(model_input, supervision_target)``
    samples and how model outputs become the task's persisted deliverable and
    its decoded evaluation payload. They own nothing about what the task
    means, which shapes are legal, or how the payload is scored.
    """

    #: Registry identity. A plain string; the framework never inspects its
    #: spelling (capability key, parent §3.1) — resolution is lookup only.
    task_data_path_id: ClassVar[str]

    def training_dataset(self, scope: object, params: EpochSamplingParams) -> Dataset[Any]:
        """A torch Dataset over ``scope`` yielding (model_input, supervision_target)."""
        ...

    def validation_dataset(self, scope: object, params: EvalMaterializationParams) -> Dataset[Any]:
        """Same, over the validation identity scope; the implementation
        discharges the exact-materialization obligation in its own vocabulary,
        failing closed (never padding, never silently truncating)."""
        ...

    def write_deliverable(self, outputs: Any, request: DeliverableWriteRequest) -> None:
        """Persist model outputs as the task's deliverable at its declared
        layout. Codec only — no scoring, no thresholds."""
        ...

    def read_evaluation_payload(self, request: EvaluationReadRequest) -> object:
        """Decode the persisted deliverable into the payload handed to the
        Step-06 evaluation authority. Codec only, by construction and by name
        (parent Amendment 2)."""
        ...


_PROTOCOL_METHODS = (
    "training_dataset",
    "validation_dataset",
    "write_deliverable",
    "read_evaluation_payload",
)


# ---------------------------------------------------------------------------
# Registry — fail-closed at every edge
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, TaskDataPath] = {}

#: The id the legacy regime-A compatibility path resolves to. A constant, not
#: a branch: regime-A detection is the ABSENCE of a binding context (child
#: §4.2), and this names which registered implementation that absence means.
TIDMAD_COMPATIBILITY_ID = "tidmad"


def register_task_data_path(impl: TaskDataPath) -> None:
    """Register an implementation, refusing malformed ones BEFORE execution.

    Mirrors the health-check registry's duplicate-refusal message style so
    operators meet one convention.
    """
    missing = [m for m in _PROTOCOL_METHODS if not callable(getattr(impl, m, None))]
    if missing:
        raise TaskDataPathRegistrationError(
            f"Task data path {getattr(impl, 'task_data_path_id', '<no id>')!r} is "
            f"missing protocol methods {missing} — refused at registration, "
            "before any execution (child design §4.2)."
        )
    impl_id = getattr(impl, "task_data_path_id", None)
    if not isinstance(impl_id, str) or not impl_id:
        raise TaskDataPathRegistrationError(
            "Task data path implementations must declare a non-empty string "
            f"`task_data_path_id`; got {impl_id!r}."
        )
    if impl_id in _REGISTRY:
        raise TaskDataPathRegistrationError(
            f"Task data path {impl_id!r} is already registered. Currently "
            f"registered: {sorted(_REGISTRY)}. Duplicate registrations are "
            "refused rather than silently replaced."
        )
    _REGISTRY[impl_id] = impl


def registered_task_data_path_ids() -> list[str]:
    """Sorted ids, for diagnostics and tests."""
    return sorted(_REGISTRY)


class TaskBindingContext(BaseModel):
    """An EXPLICIT task binding. Its very PRESENCE is the discriminator.

    ``None`` where a context is expected IS the legacy regime-A compatibility
    path — the launch surfaces that predate task binding. A future Pets run
    necessarily constructs one of these, so a missed binding step fails
    closed instead of silently training on TIDMAD's path (child §4.2). Never
    discriminate by task name.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_data_path_id: str | None = None


def resolve_task_data_path(context: TaskBindingContext | None) -> TaskDataPath:
    """The frozen truth table (child §4.2), row by row."""
    if context is None:
        # Legacy regime-A compatibility: the absence of any explicit binding.
        impl = _REGISTRY.get(TIDMAD_COMPATIBILITY_ID)
        if impl is None:
            raise TaskDataPathResolutionError(
                "Legacy regime-A resolution requires the compatibility "
                f"implementation {TIDMAD_COMPATIBILITY_ID!r}, which is not "
                f"registered. Currently registered: {sorted(_REGISTRY)}."
            )
        return impl
    if context.task_data_path_id is None:
        raise TaskDataPathResolutionError(
            "An explicit task binding was supplied with NO task_data_path_id. "
            "Explicitly bound tasks never fall back to the TIDMAD "
            "compatibility path (parent Amendment 3) — declare the task's "
            f"data-path id. Currently registered: {sorted(_REGISTRY)}."
        )
    impl = _REGISTRY.get(context.task_data_path_id)
    if impl is None:
        raise TaskDataPathResolutionError(
            f"Unknown task data path id {context.task_data_path_id!r}. "
            f"Currently registered: {sorted(_REGISTRY)}. Unknown ids fail "
            "closed — they never fall back to the TIDMAD compatibility path."
        )
    return impl


# ---------------------------------------------------------------------------
# Run-scoped binding + subprocess transport
# ---------------------------------------------------------------------------

_ACTIVE_TASK_DATA_PATH: ContextVar[TaskDataPath | None] = ContextVar(
    "siderius_active_task_data_path", default=None
)


@contextmanager
def bind_task_data_path(impl: TaskDataPath) -> Iterator[TaskDataPath]:
    """Bind the RESOLVED implementation for the run scope.

    The ``bind_dataset_profile`` pattern (``dataset_config.py:591-672``):
    a ContextVar, reset on exit, never module state.
    """
    token = _ACTIVE_TASK_DATA_PATH.set(impl)
    try:
        yield impl
    finally:
        _ACTIVE_TASK_DATA_PATH.reset(token)


def resolve_bound_task_data_path() -> TaskDataPath:
    """What a production call site asks for.

    A bound implementation wins; an unbound context IS the legacy regime-A
    path and resolves through the truth table's first row.
    """
    bound = _ACTIVE_TASK_DATA_PATH.get()
    if bound is not None:
        return bound
    return resolve_task_data_path(None)


def active_task_data_path() -> TaskDataPath | None:
    """The bound implementation, or ``None`` — WITHOUT the legacy fallback.

    The distinction from :func:`resolve_bound_task_data_path` is the whole
    point, and it is what the subprocess transport needs (Step 10 / P1 C3).
    A caller asking *"which implementation should I use?"* wants the
    fallback. A caller asking *"is this run explicitly bound?"* must not get
    it: emitting the transport flag on the strength of a fallback would put
    ``--task_data_path_id <compatibility id>`` into every legacy child's
    argv, changing the un-composed command line that predates task binding.

    Returns:
        the bound implementation, or ``None`` when the run is un-composed.
    """
    return _ACTIVE_TASK_DATA_PATH.get()


#: Internal subprocess transport flag. NOT an operator surface: it is emitted
#: by :func:`transport_argv` from an already-resolved binding, consumed by the
#: child to look up the same registered implementation, and forbidden as an
#: operator flag by the launcher argv census (child §4.1; census extension
#: lands with C5).
TASK_DATA_PATH_ARGV_FLAG = "--task_data_path_id"


def transport_argv(impl: TaskDataPath) -> list[str]:
    """The argv fragment carrying the RESOLVED binding to a subprocess.

    Takes the implementation — deliberately not a free string — so the
    transported id cannot be anything other than the resolved binding (child
    §4.1's single-authority rule, enforced by signature).
    """
    return [TASK_DATA_PATH_ARGV_FLAG, impl.task_data_path_id]


def resolve_transported_task_data_path(task_data_path_id: str) -> TaskDataPath:
    """Child-process side of the transport: the id the parent emitted.

    A transported id is an EXPLICIT binding — the parent resolved it — so it
    goes through the explicit row of the truth table and an unknown value
    fails closed exactly as any explicit binding does.
    """
    return resolve_task_data_path(TaskBindingContext(task_data_path_id=task_data_path_id))
