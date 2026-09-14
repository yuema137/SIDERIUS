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

import hashlib
import os
import pathlib
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Literal,
    Protocol,
    TypeGuard,
    cast,
    runtime_checkable,
)

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

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


class TaskScopeCapabilityError(RuntimeError):
    """A run needed task-owned scope construction from an implementation that
    does not declare the OPTIONAL :class:`TaskScopeCapability`.

    Step 12 / PR-12bc B1. One more row on the same fail-closed discipline the
    resolution truth table already follows: the message names the offending
    ``task_data_path_id`` AND the capability methods that are missing, so an
    operator can act on it without reading this file.

    It is deliberately a SEPARATE type from
    :class:`TaskDataPathResolutionError`: the binding resolved perfectly well:
    what is absent is an optional sibling capability, and conflating "I cannot
    find your task" with "your task cannot build scopes" would make both
    messages worse.
    """


class TaskHealthCoverageError(RuntimeError):
    """An attempt's task-owned evaluation scope cannot support its Health demand.

    This is deliberately separate from binding and scope-construction errors:
    the task may be perfectly able to build a scope, while that particular
    attempt's evaluation scope is not sufficient for the task's own Health
    declaration.
    """


class TrialAnchoringUnavailable(RuntimeError):
    """A trial round was requested for a task that cannot anchor one.

    Step 12 / PR-12bc B7, satellite (e). A NAMED refusal of the ROUND, not a
    ``FileNotFoundError`` on a filename the task never declared. Separate from
    :class:`TaskScopeCapabilityError` because the run is not un-runnable — the
    same task in FORMAL mode is fine, and the message says so.
    """


class TaskDataPathIdentityError(RuntimeError):
    """A child resolved the right id but the WRONG code (parent §7, frozen).

    Step 12 / PR-12bc C2. Separate from
    :class:`TaskDataPathResolutionError` because the resolution SUCCEEDED —
    that is precisely the dangerous case, and conflating "I cannot find it"
    with "I found something else" would hide it.
    """


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


class TrainingScopeError(RuntimeError):
    """A training epoch executed ZERO optimizer steps — the training twin of
    :class:`ValidationScopeError`'s zero-requested-rows rule.

    ``DataLoader(drop_last=True)`` yields ``rows // batch_size`` batches, so a
    training scope smaller than one batch produces an EMPTY epoch: no forward,
    no backward, no optimizer step. Every term of that arithmetic is already
    known to the system — ``workload_resolvers`` computes the same
    ``samples_per_epoch // batch_size`` floor and names ``drop_last`` in its own
    comments — and until this type existed nothing refused when it evaluated
    to 0.

    Unrefused, the engine still wrote a checkpoint AND its ``_OK_<exp_id>``
    success sentinel, reported ``Avg Loss: nan``, and the untrained weights
    went on to inference and scoring, where the round was reported as
    progress. The refusal fails the attempt closed (non-zero exit → the
    executor's subprocess-error path → ``error_training``), so ``NaN`` stays
    reserved for numerical evidence instead of standing in for work that never
    happened.

    Generic by construction: it is raised on the executed step count, not on
    any task's row geometry, so it holds for every task the engines run.
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


class TaskProbeDataSpec(BaseModel):
    """Run-bound task data needed to materialize one resource-probe batch."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest_path: str = Field(min_length=1)
    semantic_fingerprint: str = Field(min_length=1)
    training_scope_payload: str = Field(min_length=1)
    sampling: EpochSamplingParams
    max_inference_batch_size: int | None = Field(default=None, ge=1)
    #: Whether this task-owned probe has temporal segmentation geometry. This
    #: is explicit transport metadata: a task with a fixed-shape input must
    #: opt into ``not_applicable`` rather than being inferred from the mere
    #: presence of a task probe.
    segmentation_applicability: Literal["temporal", "not_applicable"] = "temporal"


class EvalMaterializationParams(BaseModel):
    """Knobs for ``validation_dataset`` (``train_engine_sandbox.py:905-935``).

    Deliberately minimal: the validation scope arrives already clamped
    (07c's ``clamp_validation_scope`` acts on the SCOPE upstream), so the
    only framework-level knob at this boundary today is where the data lives.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    data_dir: str = Field(min_length=1)


class ScopeBuildRequest(BaseModel):
    """What the FRAMEWORK knows when it asks a task to build an attempt's scope.

    Step 12 / PR-12bc B1 (CAP-SCOPE). The sibling of
    :class:`EpochSamplingParams` for the CONSTRUCTION side: that carrier says
    "materialize this scope for this epoch", this one says "build me a scope
    for this round".

    **Framework vocabulary only.** Every field below is a selection knob the
    framework already owns today — planner-visible, operator-visible, or
    enforced by a framework legality rule. Task vocabulary is deliberately
    ABSENT, exactly as it is on ``EpochSamplingParams``: no dataset profile,
    no segmentation size, no file pattern, no channel. **An implementation
    obtains its own vocabulary through its own authorities**, which is why
    ``profile`` is not a field here — a task that needs its topology already
    holds it.

    Field set derived by the B1 audit (D-BC-1) from the two places trial and
    formal actually differ today — ``policy.py::_resolve_sample_set_cfg``
    (five keys, one pure ``mode -> values`` function) and the two
    ``build_sample_set`` calls at ``planning.py:397-414``.

    Which LEG a request is for is expressed by WHICH METHOD is called
    (``build_training_scope`` vs ``build_eval_scope``), never by a field —
    so there is no ``leg`` here and no way to call one method with the
    other's intent.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    round_kind: Literal["trial", "formal"] = Field(
        description=(
            "The framework's own round semantics. ``single_file`` is absent "
            "deliberately: that legacy mode sets both sample sets to ``None`` "
            "(``planning.py:423-424``) and never asks a task to build a scope."
        ),
    )
    selection_strategy: Literal["snapshot", "anchors", "target"] = Field(
        description=(
            "WHICH partitions to draw from: all of them / the task's own "
            "DECLARED representatives / an explicitly named subset. Framework "
            "vocabulary, not task vocabulary — it names no file, channel, "
            "segment or geometry, the framework enforces a legality rule over "
            "it (only ``snapshot`` is legal under a partial subset), and it is "
            "already planner-visible as ``ExperimentPlan.trial_strategy`` and "
            "operator-visible as ``--formal_strategy``. Its task-specific "
            "CONTENT is delegated: ``anchors`` resolves through the TASK's own "
            "declaration, never a framework constant (the Step-02c split)."
        ),
    )
    portion: float = Field(
        gt=0.0,
        le=1.0,
        description="Fraction of each selected partition's index space to sample.",
    )
    seed: int | None = Field(
        default=None,
        description=(
            "Reproducibility seed for the selection draw. ``None`` is "
            "non-deterministic, preserving the existing builder's contract."
        ),
    )
    max_samples: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Absolute ceiling on the samples the built scope may REQUEST "
            "(07c C6). A framework knob in framework units — a row count. The "
            "arithmetic that honours it in the task's own units is the task's "
            "(TIDMAD's ``clamp_validation_scope`` needs ``ml_segs_per_psd``, "
            "which is exactly the kind of fact that must not appear here)."
        ),
    )
    target_partitions: tuple[int, ...] = Field(
        default=(),
        description=(
            "The explicitly named partition subset for "
            "``selection_strategy='target'``. Named ``partitions``, not "
            "``files``: the index domain is generic, the word ``file`` is not."
        ),
    )
    subset_ref: str | None = Field(
        default=None,
        description=(
            "OPAQUE operator-supplied restriction on the partitions a run may "
            "use — the generic replacement for ``--data_scope``, which stays "
            "TIDMAD/legacy vocabulary (§D.4). The framework NEVER parses this: "
            "it transports the string and the task interprets it. A task that "
            "has no subset concept refuses a non-``None`` value in its own "
            "words."
        ),
    )
    task_parameters: Mapping[str, Any] = Field(
        default_factory=dict,
        description=(
            "OPAQUE per-attempt task-owned knobs. The framework transports "
            "them and NEVER interprets them — the same opacity as "
            "``subset_ref``, for values that vary per ATTEMPT rather than per "
            "run.\n\n"
            "Added by B3 as a recorded extension of D-BC-1. The B1 audit "
            "derived this carrier's fields from where trial and formal "
            "DIFFER, and a per-attempt value that is the same in both rounds "
            "is exactly what that method cannot see: TIDMAD's scope carries "
            "``seg_size``, the PLANNER's model choice "
            "(``plan.model_cfg['segmentation_size']``), which every round "
            "needs and neither round varies. It is task vocabulary, so it can "
            "never be a named field here — but the scope cannot be built "
            "without it.\n\n"
            "This is NOT a config bag. It carries only per-attempt values a "
            "task needs to BUILD A SCOPE, it is opaque by contract, and a "
            "framework site that reads inside it fails the genericity census."
        ),
    )


class HealthCoverageRequest(BaseModel):
    """Opaque task request for one attempt's Health/evaluation coverage.

    The framework supplies the exact scope object it is about to execute and
    the already-resolved Health binding. Their contents are task vocabulary;
    this carrier intentionally permits and transports them without inspection.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True, extra="forbid")

    evaluation_scope: Any
    round_kind: Literal["trial", "formal"]
    health_binding: Any


class HealthCoverageResult(BaseModel):
    """Validated result of a task-owned Health coverage check.

    ``applicable=False`` is an explicit declaration that no output-dependent
    Health demand exists. Otherwise ``covered`` states whether the exact
    evaluation scope covers the task's demand. Every result carries a reason
    so a refusal is actionable and no state can be inferred from omission.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    applicable: StrictBool
    covered: StrictBool
    reason: str = Field(min_length=1)

    @field_validator("reason")
    @classmethod
    def reason_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Health coverage reason must not be blank")
        return value

    @model_validator(mode="after")
    def _validate_state(self) -> HealthCoverageResult:
        if not self.applicable and self.covered:
            raise ValueError("Health coverage cannot be covered when it is not applicable")
        return self


class DeliverableSourceContext(BaseModel):
    """Run-bound source needed to reconstruct prediction-aligned task values.

    Generic inference deliberately retains only model outputs. A task whose
    deliverable also contains source- or supervision-derived values can use
    this context to rematerialize ``validation_dataset`` through its own
    implementation. The fixed ordering value states the positional contract;
    ``sample_count`` lets the implementation refuse a changed or incomplete
    rematerialization instead of silently zipping mismatched sequences.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    data_dir: str = Field(min_length=1)
    sample_count: int = Field(ge=0)
    ordering: Literal["validation_dataset_index_order"] = "validation_dataset_index_order"


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
    task_scope: Any = Field(
        default=None,
        description=(
            "Step 12 / PR-12d seam C (B7). The OPAQUE evaluation scope whose "
            "samples produced these outputs, in the order the generic "
            "inference unit iterated them. Present ONLY when the framework "
            "hands UNPAIRED per-sample outputs, so the implementation can "
            "pair each with its own identity — an `image_id`, a clip — "
            "without the framework ever learning that vocabulary. `None` "
            "means the caller already paired them, which is what every "
            "pre-12d producer does, so every existing construction is "
            "unchanged."
        ),
    )
    source_context: DeliverableSourceContext | None = Field(
        default=None,
        description=(
            "Run-bound physical source and positional contract for outputs "
            "produced by generic inference. A task may rematerialize its own "
            "validation dataset when its deliverable needs input- or target-"
            "associated values. None preserves callers that already provide "
            "fully paired outputs."
        ),
    )


class EvaluationReadRequest(BaseModel):
    """What ``read_evaluation_payload`` decodes for the Step-06 authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    deliverable_dir: str = Field(min_length=1)
    exp_id: str = Field(min_length=1)
    run_name: str = Field(min_length=1)
    model_type: str = Field(min_length=1)


class TaskEvaluationPayload(BaseModel):
    """A decoded task value plus every artifact scoreability must inspect.

    Most tasks have one declared deliverable and can keep returning their
    decoded value directly. A task whose scientific result spans multiple
    files can return this carrier without adding another protocol method.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True, extra="forbid")

    value: Any
    deliverables: dict[int, str]


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
        (parent Amendment 2). Return ``TaskEvaluationPayload`` when the result
        spans multiple artifacts that scoreability must inspect."""
        ...


_PROTOCOL_METHODS = (
    "training_dataset",
    "validation_dataset",
    "write_deliverable",
    "read_evaluation_payload",
)


@runtime_checkable
class TaskScopeCapability(Protocol):
    """OPTIONAL sibling capability: the task owns how its scopes are BUILT.

    Step 12 / PR-12bc, Phase B (CAP-SCOPE); parent §5.5, Q-12-2 = A.

    **This does not amend** :class:`TaskDataPath`. Its four methods are frozen
    and untouched. An implementation MAY additionally declare these four, and
    an implementation that does not is still a perfectly valid data path — it
    simply cannot serve a composed run that needs task-owned scope
    construction, which fails closed by name rather than by crashing on
    somebody else's scope object.

    Why a sibling and not a fifth method: the four-method contract is about
    what a task DOES with a scope it is handed. This is about where a scope
    comes from in the first place, and the two have different implementors —
    Step 11 closed the "handed a scope" side and explicitly deferred this one
    (``step_11_execution_infrastructure.md:287-289``).

    ``serialize_scope`` / ``deserialize_scope`` exist because the scope must
    cross a real process boundary. The payload shape is the TASK's — the
    framework hashes and transports the bytes and never looks inside them
    (parent §3 scope opacity, one layer further out).
    """

    def build_training_scope(self, request: ScopeBuildRequest) -> object:
        """The training scope for one attempt, in the task's own vocabulary."""
        ...

    def build_eval_scope(self, request: ScopeBuildRequest) -> object:
        """The evaluation scope for the same attempt. Separate method rather
        than a ``leg`` field, so a caller cannot ask for one and get the
        other."""
        ...

    def serialize_scope(self, scope: object) -> str:
        """CANONICAL bytes for a scope this implementation built.

        Canonical because the framework digests the result: two equal scopes
        must serialize identically or the identity chain reports a difference
        that does not exist.
        """
        ...

    def deserialize_scope(self, payload: str) -> object:
        """The inverse, FAIL-CLOSED. A payload this implementation did not
        write — or wrote in another version — must raise, never be partially
        accepted."""
        ...


_SCOPE_CAPABILITY_METHODS = (
    "build_training_scope",
    "build_eval_scope",
    "serialize_scope",
    "deserialize_scope",
)


@runtime_checkable
class TaskHealthCoverageCapability(Protocol):
    """OPTIONAL sibling capability for attempt-scoped Health coverage.

    The task decides whether its opaque evaluation scope covers its own
    output-dependent Health demand. The framework only validates the typed
    result and never interprets the scope or Health vocabulary.
    """

    def validate_health_coverage(self, request: HealthCoverageRequest) -> HealthCoverageResult:
        """Confirm coverage for the exact evaluation scope of this attempt."""
        ...


_HEALTH_COVERAGE_METHODS = ("validate_health_coverage",)


def declares_health_coverage(impl: object) -> TypeGuard[TaskHealthCoverageCapability]:
    """Whether an implementation declares the Health coverage capability."""
    return all(callable(getattr(impl, method, None)) for method in _HEALTH_COVERAGE_METHODS)


def resolve_task_health_coverage_capability(
    impl: TaskDataPath,
) -> TaskHealthCoverageCapability:
    """Resolve Health coverage fail-closed beside the scope capability."""
    if not declares_health_coverage(impl):
        task_id = getattr(impl, "task_data_path_id", "<unknown>")
        raise TaskHealthCoverageError(
            f"task data path {task_id!r} has Health enabled for a composed attempt, "
            "but does not declare validate_health_coverage; explicit task-owned "
            "coverage is required before execution"
        )
    return cast("TaskHealthCoverageCapability", impl)


@runtime_checkable
class TaskInferenceBatching(Protocol):
    """OPTIONAL sibling capability: the task limits inference collation.

    Resource feasibility cannot prove that independently materialized task
    samples can be stacked. A task whose samples have variable shapes may
    therefore declare the largest semantically valid inference batch.
    """

    def max_inference_batch_size(self) -> int:
        """Return the inclusive task-semantic inference batch ceiling."""
        ...


class StorageReadScope(BaseModel):
    """Task-owned description of the physical bytes read during setup.

    Paths and byte volume are physical provenance, not scientific semantics.
    The task computes them because only the task can interpret its opaque
    scope; the framework records the validated result without inspecting the
    scope itself.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    file_paths: tuple[str, ...]
    expected_on_disk_bytes: int = Field(ge=0)

    @field_validator("file_paths")
    @classmethod
    def require_absolute_paths(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not os.path.isabs(path) for path in value):
            raise ValueError("storage provenance file paths must be absolute")
        return value


@runtime_checkable
class TaskStorageReadScope(Protocol):
    """Optional capability for provenance over an opaque task scope."""

    def storage_read_scope(self, data_dir: str, scope: object) -> StorageReadScope:
        """Describe the files and on-disk byte volume setup will read."""
        ...


def resolve_storage_read_scope(
    impl: object, data_dir: str, scope: object
) -> StorageReadScope | None:
    """Resolve optional task-owned storage provenance without reading scope internals."""
    method = getattr(impl, "storage_read_scope", None)
    if not callable(method):
        return None
    return StorageReadScope.model_validate(method(data_dir, scope))


def declares_inference_batching(impl: object) -> TypeGuard[TaskInferenceBatching]:
    """Whether ``impl`` declares task-owned inference batching semantics."""
    return callable(getattr(impl, "max_inference_batch_size", None))


def resolve_max_inference_batch_size(impl: object) -> int | None:
    """Return the declared positive ceiling, or ``None`` when undeclared."""
    if not declares_inference_batching(impl):
        return None
    value = impl.max_inference_batch_size()
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"max_inference_batch_size() must return a positive int; got {value!r}.")
    return value


@runtime_checkable
class TaskTrialAnchoring(Protocol):
    """OPTIONAL: the task can anchor a TRIAL round in its own vocabulary.

    Step 12 / PR-12bc B7, satellite (e). Trial mode needs a task-owned
    reference artifact — TIDMAD's is the segment anchor map. Before this the
    tuner joined a hardcoded ``segment_anchors.json`` onto the run's physical
    root and raised ``FileNotFoundError`` when it was absent, so a COMPOSED
    non-TIDMAD trial run failed by naming a TIDMAD filename it had never heard
    of. Declaring the capability turns that into a named refusal: a task that
    cannot anchor a trial says so, and the framework never guesses a filename
    on its behalf.

    One method, deliberately. This is not a place to accumulate task hooks —
    it answers exactly one question.
    """

    def trial_anchor_path(self, data_root: str) -> str:
        """Absolute path to this task's trial-anchoring artifact under
        ``data_root`` (the run's resolved physical root)."""
        ...


_TRIAL_ANCHORING_METHODS = ("trial_anchor_path",)

#: The REGIME-A trial-anchoring filename. Named here, beside the capability it
#: is the legacy counterpart of, rather than inlined at the tuner: an
#: un-composed run predates task binding and must keep this exact behaviour,
#: and the constant makes that a deliberate compatibility path instead of a
#: leftover literal.
LEGACY_TRIAL_ANCHOR_NAME = "segment_anchors.json"


def declares_trial_anchoring(impl: object) -> TypeGuard[TaskTrialAnchoring]:
    """Whether ``impl`` can anchor a trial round. CALLABILITY, as always.

    A ``TypeGuard`` and not a bare ``bool``: the caller's whole reason to ask
    is to then reach for `trial_anchor_path`, which the frozen four-method
    ``TaskDataPath`` deliberately does NOT declare. Returning ``bool`` left the
    narrowing to a human, and a static checker rejected the access — correctly.
    """
    return all(callable(getattr(impl, m, None)) for m in _TRIAL_ANCHORING_METHODS)


def declares_scope_capability(impl: object) -> TypeGuard[TaskScopeCapability]:
    """Whether ``impl`` declares the OPTIONAL capability, by CALLABILITY.

    Structural, exactly like :func:`register_task_data_path`'s protocol-method
    check (``:233-239``) — never ``isinstance`` against the runtime-checkable
    Protocol, which only checks attribute PRESENCE and would accept a
    non-callable attribute of the right name.
    """
    return all(callable(getattr(impl, m, None)) for m in _SCOPE_CAPABILITY_METHODS)


def deserialize_rows_scope(payload: str, kind: str, row_model, scope_model):
    """FAIL-CLOSED codec for a ``rows``-shaped task scope.

    Step 12 / PR-12bc B8. Pets and DAVIS both describe their scope as a tuple
    of identity rows, so they share ONE deserializer rather than two copies of
    the same six refusals. TIDMAD does NOT use it — its scope is
    ``{partition: [indices]}``, a genuinely different shape, and forcing a
    shared codec over both would be an abstraction invented for symmetry.

    The payload is self-identifying, so a foreign scope is refused BY KIND
    rather than by whichever field happens to be missing first.

    Raises:
        ValueError: not JSON, not an object, wrong kind, missing rows, or a
            row that does not satisfy the task's own row model.
    """
    import json

    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{kind} payload is not valid JSON ({exc}).") from exc
    if not isinstance(decoded, dict):
        raise ValueError(f"{kind} payload must be a JSON object, got {type(decoded).__name__}.")
    found = decoded.get("kind")
    if found != kind:
        raise ValueError(
            f"scope payload declares kind {found!r}, not {kind!r} — the binding "
            f"and the scope object must come from the same task."
        )
    if "rows" not in decoded:
        raise ValueError(f"{kind} payload is missing ['rows'].")
    try:
        return scope_model(rows=tuple(row_model.model_validate(r) for r in decoded["rows"]))
    except Exception as exc:
        raise ValueError(f"{kind} payload is malformed ({exc}).") from exc


def require_bound_task_data_path() -> TaskDataPath:
    """Return the explicitly bound implementation or fail closed.

    The ambient lookup lives with the binding authority so callers cannot
    invent a fallback when composition was missed.

    Raises:
        TaskDataPathResolutionError: Nothing is bound. The caller said the run
            is composed, so a fallback would be a wrong answer rather than a
            legacy one.
    """
    bound = active_task_data_path()
    if bound is None:
        raise TaskDataPathResolutionError(
            "an EXPLICITLY bound task data path was required, but none is "
            "bound. Falling back would silently execute another task's data "
            "path, so execution is refused."
        )
    return bound


def resolve_task_scope_capability(impl: TaskDataPath) -> TaskScopeCapability:
    """The capability of a resolved binding, or a NAMED fail-closed refusal.

    One more row on the truth-table discipline of :func:`resolve_task_data_path`
    (``:275-301``). Called PARENT-SIDE while an attempt is being prepared, so
    a composed run that cannot build its own scopes stops at composition —
    never at first spawn, and never in a child that has already been launched.

    Args:
        impl: An already-resolved data-path implementation.

    Returns:
        The same object, narrowed to the capability.

    Raises:
        TaskScopeCapabilityError: The implementation declares none, or only
            some, of the four capability methods. The message names the id and
            every missing method.
    """
    missing = [m for m in _SCOPE_CAPABILITY_METHODS if not callable(getattr(impl, m, None))]
    if missing:
        impl_id = getattr(impl, "task_data_path_id", "<no id>")
        raise TaskScopeCapabilityError(
            f"Task data path {impl_id!r} does not provide task-owned scope "
            f"construction: missing {missing}. A composed run that needs its "
            f"task to BUILD scopes requires the optional TaskScopeCapability "
            f"(all four of {list(_SCOPE_CAPABILITY_METHODS)}). Refused at "
            f"composition, before any subprocess was launched."
        )
    return cast("TaskScopeCapability", impl)


# ---------------------------------------------------------------------------
# Registry — fail-closed at every edge
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, TaskDataPath] = {}

#: CONTENT identity per registered id — Step 12 / PR-12bc C1.
#:
#: Parallel to ``_REGISTRY`` rather than inside it, so the registry's own type
#: and every existing read of it are unchanged. The identity is captured AT
#: REGISTRATION and stored, deliberately: recomputing it on demand from the
#: registered object would re-read the source file as it is NOW, so an edited
#: plugin would hash the same file on both sides of the comparison and compare
#: EQUAL — the exact case the comparison exists to catch.
#:
#: The two maps are written and cleared in lockstep and must always carry the
#: same key set; :func:`registry_invariant_holds` states that, and C1's tests
#: assert it after every lifecycle operation.
_CONTENT: dict[str, str] = {}


def content_identity(impl: object) -> str:
    """WHAT this implementation is, independent of WHERE it came from.

    Step 12 / PR-12bc C1. The health precedent's rule, applied one family over
    (`_plugin_binding.py`): normalized symbol + content sha, with **host paths
    excluded** so the same package at two absolute paths is ONE identity — two
    checkouts of the same task package are the same scientific run.

    Composed from the defining module's qualified name and the sha256 of its
    SOURCE. A class re-executed from the same file is the same identity; a
    class whose file was EDITED is not, which is what makes an edited plugin
    refuse instead of silently running the old object.

    Falls back to the qualified name alone when the source cannot be read (a
    dynamically constructed class, a stub in a test). That is a WEAKER
    identity, not a wrong one: it still distinguishes two different classes,
    it simply cannot notice an edit to something that has no file.
    """
    cls = type(impl)
    qualname = f"{cls.__module__}.{cls.__qualname__}"
    module = sys.modules.get(cls.__module__)
    if module is not None:
        from core.local_code import module_identity

        identity = module_identity(module)
        if identity is not None:
            return f"{identity.member}:{cls.__qualname__}@{identity.package.digest}"
    source = getattr(module, "__file__", None) if module is not None else None
    if source:
        try:
            digest = hashlib.sha256(pathlib.Path(source).read_bytes()).hexdigest()
        except OSError:
            return qualname
        return f"{qualname}@{digest}"
    return qualname


def registered_content_identity(impl_id: str) -> str | None:
    """The content identity registered under ``impl_id``, if any."""
    return _CONTENT.get(impl_id)


def registry_invariant_holds() -> bool:
    """Whether the registry and its content map carry the same key set.

    They are two structures holding one fact, so a divergence means an id is
    registered with no identity (a duplicate would compare against ``None``
    and refuse spuriously) or an identity survives an absent id (a later
    registration would compare against a ghost). Stated as a function so
    every lifecycle test can assert it rather than each one re-deriving it.
    """
    return set(_REGISTRY) == set(_CONTENT)


def register_task_data_path(impl: TaskDataPath) -> None:
    """Register an implementation, refusing malformed ones BEFORE execution.

    Mirrors the health-check registry's duplicate-refusal message style so
    operators meet one convention.

    **Step 12 / PR-12bc C1 — the frozen §8 two-phase rule, implemented.**

    ```text
    same id + SAME content       -> IDEMPOTENT (a no-op)
    same id + DIFFERENT content  -> REFUSED, by name
    ```

    Before C1 this compared **id alone**, so a re-execution of the IDENTICAL
    module was indistinguishable from a genuine collision and both were
    refused. That is CASE A: a module evicted from ``sys.modules`` (by a
    package rebinding, a plugin-isolation fixture, an interpreter that reloads)
    re-executes its module-level registration and hits a refusal for doing
    exactly what it did the first time.

    Making the identical case idempotent is **not** suppressing the duplicate
    error — the different-content case still refuses, loudly, and that is the
    case the refusal exists for: two DIFFERENT implementations claiming one id.
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
    identity = content_identity(impl)
    if impl_id in _REGISTRY:
        existing = _CONTENT.get(impl_id)
        if existing == identity:
            # Same id, same content: the SAME implementation registering
            # again. Idempotent by the frozen §8 rule — re-registering what is
            # already there changes nothing, so refusing would only punish a
            # module for being re-executed.
            return
        raise TaskDataPathRegistrationError(
            f"Task data path {impl_id!r} is already registered with DIFFERENT "
            f"content. Currently registered: {sorted(_REGISTRY)}.\n"
            f"  registered: {existing}\n"
            f"  offered:    {identity}\n"
            f"Two different implementations claiming one id are refused rather "
            f"than silently replaced — whichever ran would be a coin flip. "
            f"(A re-registration of the SAME content is idempotent.)"
        )
    _REGISTRY[impl_id] = impl
    _CONTENT[impl_id] = identity


def registered_task_data_path_ids() -> list[str]:
    """Sorted ids, for diagnostics and tests."""
    return sorted(_REGISTRY)


class TaskBindingContext(BaseModel):
    """An EXPLICIT task binding. Its very PRESENCE is the discriminator.

    Supported execution always supplies this context. ``None`` is retained as
    an input shape only so old callers receive a named refusal rather than an
    attribute error; it never selects a scientific task.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_data_path_id: str | None = None


def resolve_task_data_path(context: TaskBindingContext | None) -> TaskDataPath:
    """Resolve an explicitly declared task data path, or fail closed."""
    if context is None:
        raise TaskDataPathResolutionError(
            "No task data path was declared. Supply a task composition whose "
            "task_data_path identifies a registered implementation; SIDERIUS "
            "does not select a scientific task by default."
        )
    if context.task_data_path_id is None:
        raise TaskDataPathResolutionError(
            "An explicit task binding was supplied with NO task_data_path_id. "
            "Explicitly bound tasks never fall back to another task. Declare the task's "
            f"data-path id. Currently registered: {sorted(_REGISTRY)}."
        )
    impl = _REGISTRY.get(context.task_data_path_id)
    if impl is None:
        raise TaskDataPathResolutionError(
            f"Unknown task data path id {context.task_data_path_id!r}. "
            f"Currently registered: {sorted(_REGISTRY)}. Unknown ids fail "
            "closed; they never fall back to another task."
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
    """Return the run-bound implementation, or refuse an uncomposed call."""
    bound = _ACTIVE_TASK_DATA_PATH.get()
    if bound is not None:
        return bound
    raise TaskDataPathResolutionError(
        "No task data path is bound for this execution. Enter the task "
        "composition binding before training, inference, or scoring; "
        "SIDERIUS does not select a scientific task by default."
    )


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

#: The PARENT-PINNED IDENTITY of the transported implementation (C2). An id
#: says WHICH implementation; this says WHICH CODE. Emitted only when composed,
#: beside the id it qualifies.
TASK_DATA_PATH_IDENTITY_FLAG = "--task_data_path_identity"


def effective_identity(impl: TaskDataPath) -> str:
    """The identity of the code that is LOADED, not of the bytes on disk now.

    Step 12 / PR-12bc, **F-12bc-7** — found by `G-12bc-C`, which FAILED on its
    first launch and was right to.

    :func:`content_identity` hashes the defining module's source **file**, so
    it re-reads the disk on every call. C2 used it directly in
    :func:`transport_argv`, which meant the "parent-pinned identity" was not
    pinned at all: it was re-derived at SPAWN time from whatever was on disk
    then. Edit a plugin between bind and spawn and the parent transported the
    EDITED file's digest, the child computed the same edited digest, and the
    comparison passed — the exact window C2 exists to close, left wide open by
    a lazy read::

        parent registers   -> captured  cb1a75b3…    (a real pin)
        plugin edited      ->
        parent spawns      -> transported 469101f4…  (a re-read, matches the
        child composes     -> computed    469101f4…   tampered file)

    The registry already captures the identity AT REGISTRATION
    (`_CONTENT[id]`, C1.1), and that captured value is the pin. This prefers
    it, and computes only for an implementation nobody registered — a directly
    bound instance in a test, where there is no capture to prefer and no
    on-disk edit to miss. Every production route registers.

    Why this is the correct semantics and not merely the safe one: an identity
    is a claim about the object in memory. Once the module has executed, the
    file can say anything; the loaded code is fixed. Reading the file to
    describe the object is only accurate while nothing has touched it.
    """
    return registered_content_identity(impl.task_data_path_id) or content_identity(impl)


def transport_argv(impl: TaskDataPath) -> list[str]:
    """The argv fragment carrying the RESOLVED binding to a subprocess.

    Takes the implementation — deliberately not a free string — so the
    transported id cannot be anything other than the resolved binding (child
    §4.1's single-authority rule, enforced by signature).

    **Step 12 / PR-12bc C2** adds the PARENT-PINNED IDENTITY beside the id.
    An id says *which* implementation; the identity says *which code*. Without
    it a child could resolve the right name and execute different bytes — the
    bind-to-spawn edit window — and nothing anywhere would notice.

    The identity is the one CAPTURED when this implementation was registered
    (:func:`effective_identity`), never a fresh read of the plugin file. See
    F-12bc-7: a fresh read makes the pin follow the edit it is meant to catch.
    """
    return [
        TASK_DATA_PATH_ARGV_FLAG,
        impl.task_data_path_id,
        TASK_DATA_PATH_IDENTITY_FLAG,
        effective_identity(impl),
    ]


def verify_transported_identity(impl: TaskDataPath, expected: str | None) -> TaskDataPath:
    """Refuse unless ``impl`` IS the implementation the parent pinned.

    Step 12 / PR-12bc C2, discharging the frozen parent §7 invariant:

        Every child-consumed external semantic MUST be validated against an
        identity pinned by the parent BEFORE the child consumes it; **a
        registry hit is never sufficient evidence of identity.**

    That last clause is why this is a separate step rather than something
    folded into resolution: resolution answers *"is something registered under
    this name?"*, and a stale registration answers YES while running different
    code. This answers *"is it the same code?"*.

    ``expected=None`` is the LEGACY case — a parent that predates the identity
    transport emitted no identity, and a child must not invent a requirement
    for it. That is an absence of a claim, not a failed one.

    Raises:
        TaskDataPathIdentityError: the resolved implementation's content
            differs from what the parent pinned. Names both, so an operator
            sees which side moved.
    """
    if expected is None:
        return impl
    # F-12bc-7: the CAPTURED identity, for the same reason the parent
    # transports the captured one — this must describe the code that is
    # loaded here, not the bytes the plugin file happens to hold now.
    found = effective_identity(impl)
    if found != expected:
        raise TaskDataPathIdentityError(
            f"task data path {impl.task_data_path_id!r} resolved in this child, "
            f"but it is NOT the implementation the parent pinned.\n"
            f"  parent pinned: {expected}\n"
            f"  child resolved: {found}\n"
            f"Refusing BEFORE consuming it: the id matched, so a registry hit "
            f"would have looked like proof — it is not. Something edited the "
            f"plugin, or a stale registration is shadowing it."
        )
    return impl


def resolve_transported_task_data_path(
    task_data_path_id: str, identity: str | None = None
) -> TaskDataPath:
    """Child-process side of the transport: the id the parent emitted.

    A transported id is an EXPLICIT binding — the parent resolved it — so it
    goes through the explicit row of the truth table and an unknown value
    fails closed exactly as any explicit binding does.

    **Step 12 / PR-12bc C2**: the parent-pinned ``identity`` is verified here,
    so every child gets the check from the one function they all already call.
    A child cannot consume the implementation without having gone through it.
    """
    return verify_transported_identity(
        resolve_task_data_path(TaskBindingContext(task_data_path_id=task_data_path_id)),
        identity,
    )


def task_declared_deliverable_name(data_path: object, request: object) -> str:
    """The deliverable's name, from the TASK's own naming rule.

    Step 12 / PR-12d. Read through the implementation's module-level
    ``deliverable_name`` when it declares one — the SAME function its
    ``write_deliverable`` and ``read_evaluation_payload`` already agree on, so
    a reported name cannot drift from the written one.

    Declared HERE, beside the contract, because BOTH the generic inference
    unit and the scoring child need it: a second copy is the duplicated
    child-side logic §E.2 forbids.

    A task that declares no such helper gets the request's directory back —
    honest rather than invented: the framework does not know the name and
    says so. Physical artifact semantics stay task-owned either way.
    """
    module = sys.modules.get(type(data_path).__module__)
    namer = getattr(module, "deliverable_name", None)
    if callable(namer):
        return str(namer(request))
    return str(getattr(request, "output_dir", None) or getattr(request, "deliverable_dir", ""))
