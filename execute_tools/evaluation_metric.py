"""The generic EvaluationMetric interface, and TIDMAD as its instance #1.

Step 06, design ``docs/design/generic_framework_upgrade/
step_06_metric_interface.md`` §4, §5, §6, §7 (roadmap §10, §20.2, §20.4).

**The concept.** An *evaluation metric* is a named, directional evaluation of
the **persisted scientific deliverable** of one attempt. It produces a
mandatory scalar, MAY produce structured per-sample evidence when it naturally
decomposes that way, declares whether higher or lower is better, declares how
evidence aggregates to the scalar, may name reference baselines, and declares
an EXECUTABLE **scoreability contract** — what the deliverable must satisfy
before any arithmetic runs. A scalar-only metric is a first-class instance;
TIDMAD's ``scalar + length-20 file_vector`` is instance #1, not the template.

**What it is NOT.** A training observation. Train loss and validation loss are
not evaluation metrics: they have no deliverable, no reference baseline and no
direction independent of their ``loss_type`` (roadmap §20.2, OD-20-4/5). The
types below carry **no loss field** and forbid extra keys — so ``loss_history``
cannot be smuggled in under any name. What they do NOT do, since Step 12 /
PR-12a C5 closed D16, is judge an identity by its SPELLING: a metric id is
OPAQUE, and ``log_loss`` is as declarable as ``accuracy`` when the task's
deliverable is genuinely scored that way. The boundary is the typed
contract — a deliverable, an aggregation and an executable scoreability
contract — not a token. Surfacing losses is Step 07's ``TrainingHistory`` /
``TrainingDiagnosis``; validity/pathology verdicts are Step 08's HealthGates.

**Ownership split (design §4, §16-Q1 CONFIRMED).** Step 05c's
:class:`~execute_tools.deliverable_spec.DeliverableSpec` retains EXCLUSIVE
ownership of the producer-side *representation* — naming, cleanup identity,
channel-group identity, storage layout / serialization, storage dtype and
offset. This module owns the evaluation-side *acceptance* contract: what THIS
metric REQUIRES of that artifact. The metric REFERENCES the deliverable spec
(the TIDMAD contract's required channel groups and storage dtype are read from
it) and never redefines it. There is deliberately **no universal,
task-independent schema** for "completeness", "required channels" or "required
shape" (§5, §16-Q3): each metric instance declares its own contract as a
:class:`ScoreabilityContract` subclass; a generic ``required_num_files /
required_channels / required_shape`` vocabulary would be the TIDMAD shape
re-declared as the universal one.

**Runtime-only, derived under Regime A.** :class:`MetricSpec` is a typed
runtime value in the ``DeliverableSpec`` mould — not user-authored YAML, not a
new top-level config, not persisted as its own artifact. The TIDMAD instance is
DERIVED with no declaration (:func:`derive_tidmad_metric`); task-level
declaration/binding for other tasks is Step 12's, as an additive block inside
the existing task configuration. Only :class:`MetricResult` /
:class:`NotScoreableResult` reach a record (Step 06 C4, additive).

**The frozen formula is referenced, never re-implemented.** The TIDMAD
instance's aggregation IS ``execute_tools.scoring_utils.score_vector`` — its
``_LOG_BASE``, ``s_max``, anchor normalisation and grand-mean are the
instance's own constants and are not restated here. The handle wraps the call
and evaluates scoreability FIRST; the arithmetic entry is untouched.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Annotated, Any, ClassVar, Literal, NamedTuple, cast, get_args

import h5py
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    SerializeAsAny,
    field_validator,
    model_validator,
)

from execute_tools.dataset_config import DatasetProfile, ScopeViolationError
from execute_tools.deliverable_spec import DeliverableSpec, derive_tidmad_deliverable_spec
from execute_tools.scoring_helpers import _LOG_BASE as _TIDMAD_LOG_BASE

# ---------------------------------------------------------------------------
# The TIDMAD instance's identity — declared ONCE, here.
# ---------------------------------------------------------------------------

#: The metric identity ``per_file_best`` has emitted since before Step 06
#: (``execute_tools/per_file_best.py``, key set pinned by
#: ``tests/unit/execute_tools/test_per_file_best.py``). The interface EXTENDS
#: that precedent (roadmap §10.2, finding 8); the string is not re-invented.
TIDMAD_METRIC_ID = "tidmad_denoising_score"

#: Identity of the frozen aggregation rule: anchor-normalised per-segment
#: weights, linear grand mean over every sampled segment, then ``log_5.27``
#: (``scoring_utils.py`` module docstring §3). The rule itself lives in
#: ``score_vector``; this is its NAME.
TIDMAD_AGGREGATION_ID = "tidmad_anchor_normalised_linear_grand_mean"

#: ``score_transform`` as ``per_file_best`` already emits it.
TIDMAD_TRANSFORM = "log"

#: Reference kinds the TIDMAD interpretation layer compares against: the
#: committed anchor map (``s_max`` — consumed by scoring), and the committed
#: raw-baseline / ground-truth per-file artifacts (``ScoreComparisonTable``).
TIDMAD_REFERENCES: tuple[str, ...] = ("anchor_map", "raw_baseline", "ground_truth")

#: The two instrument attrs the frozen scorer reads UNCONDITIONALLY from the
#: input channel group of whichever file it opens
#: (``scoring_utils.py:159-164``). Evaluation-side facts: how they are
#: WRITTEN stays with the producer (``array2h5.create_abra_file``).
TIDMAD_REQUIRED_ATTRS: tuple[str, ...] = ("voltage_range_mV", "sampling_frequency")

#: In-file path the frozen scorer reads samples from
#: (``scoring_utils.get_one_sec_psd``: ``timeseries/<group>/timeseries``).
#: A requirement of THIS metric on the artifact, stated where the metric is.
_TIDMAD_H5_ROOT_GROUP = "timeseries"
_TIDMAD_H5_SAMPLES_DATASET = "timeseries"

MetricDirection = Literal["higher", "lower"]


def _validate_metric_identifier(identifier: str, *, field: str) -> str:
    """Identifier HYGIENE only. A metric's identity is OPAQUE.

    **Step 12 / PR-12a C5 (D16), operator-ruled.** This function used to also
    refuse any identifier whose tokens included ``loss``/``losses``. That
    lexical rule is gone: the framework never infers "this is a training
    objective, not an evaluation metric" from a name token. ``accuracy``,
    ``mse``, ``log_loss``, ``negative_log_loss`` and ``banana_metric`` are all
    equally legal identities whose meaning and DIRECTION come from the
    declaration.

    The rule was self-contradictory in its own docstring, which conceded that
    ``mse`` — a loss formula — is "a legitimate evaluation-metric identity for
    a task whose deliverable IS scored by mean squared error". What it actually
    keyed on was spelling, so a task whose deliverable is genuinely scored by
    log loss could not declare it, while the same quantity named ``surprisal``
    sailed through. That is not a boundary; it is a lint on vocabulary.

    **What enforces the real boundary instead** — the typed contracts, which
    the audit confirmed already do it and which C5 leaves untouched:

    * an :class:`EvaluationMetric` is constructed from a :class:`MetricSpec`
      carrying an ``aggregation`` and an executable
      :class:`ScoreabilityContract` over a DELIVERABLE. A training objective
      has neither, so it cannot occupy the slot;
    * ``_compose_metric`` validates that a declared implementation IS an
      ``EvaluationMetric`` instance;
    * the record-facing types declare ``extra="forbid"`` and no field whose
      name says loss, so ``loss_history`` / ``final_loss`` cannot ride along
      under any key — the executable half of the evaluation-vs-training
      boundary, and the reason removing the name check weakens nothing.

    The hygiene kept here is a sibling check, not the D16 rule: an empty or
    whitespace-padded identifier is malformed regardless of what it spells.
    """
    if not identifier or identifier.strip() != identifier:
        raise ValueError(
            f"{field} must be a non-empty identifier with no surrounding whitespace; "
            f"got {identifier!r}."
        )
    return identifier


# ---------------------------------------------------------------------------
# Scoreability — an EXECUTABLE acceptance contract, evaluated BEFORE arithmetic
# ---------------------------------------------------------------------------


class ScoreabilityFailure(BaseModel):
    """One violated requirement, named. Never an incidental h5py traceback."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    requirement: str = Field(description="Which declared requirement was violated.")
    input_identity: int | None = Field(
        default=None,
        description="The deliverable (by input identity) that violated it; None if global.",
    )
    detail: str = Field(description="Human-readable specifics — path, expected vs found.")


class ScoreabilityVerdict(BaseModel):
    """The structured outcome of a scoreability check.

    ``scoreable`` is DERIVED from ``failures`` — an empty tuple is the only
    way to be scoreable, so a contract cannot report "ok" while listing a
    violation, and cannot report "not scoreable" without naming why.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_id: str = Field(description="Which contract produced this verdict.")
    failures: tuple[ScoreabilityFailure, ...] = Field(default=())

    @property
    def scoreable(self) -> bool:
        return not self.failures


class ScoreabilityContract(BaseModel, ABC):
    """What ONE metric requires of the persisted deliverable before scoring.

    Abstract on purpose. Each metric instance subclasses this and declares its
    own requirements against the producer-side representation; there is no
    shared requirement vocabulary (design §5, §16-Q3). :meth:`check` must be
    total: it returns a verdict for ANY input and never lets a filesystem or
    HDF5 error escape — turning "whatever does not crash inside the scorer
    worker" into a named, structured acceptance decision is the whole point.

    ``check`` rather than ``validate``: Pydantic v2 reserves ``validate`` as a
    (deprecated) classmethod on every model.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_id: str = Field(description="Stable identity of this contract.")

    @abstractmethod
    def check(self, deliverables: Mapping[int, str]) -> ScoreabilityVerdict:
        """Evaluate the contract over ``{input_identity: deliverable_path}``.

        Args:
            deliverables: Every deliverable the caller intends to score, keyed
                by input identity (for TIDMAD, ``file_index``). Paths are as
                the scorer will open them.

        Returns:
            A verdict; ``.scoreable`` is True iff no requirement was violated.
        """


class PresenceScoreabilityContract(ScoreabilityContract):
    """The weakest acceptance: every named deliverable exists as a file.

    For scalar-only metrics that read one artifact and need nothing else. It
    is NOT a universal completeness schema — it declares no channels, no
    shape, no dtype; a metric that needs those declares its own contract.
    """

    contract_id: str = "deliverable_presence"

    def check(self, deliverables: Mapping[int, str]) -> ScoreabilityVerdict:
        failures: list[ScoreabilityFailure] = []
        if not deliverables:
            failures.append(
                ScoreabilityFailure(
                    requirement="completeness", detail="no deliverable was named for scoring"
                )
            )
        for identity, path in deliverables.items():
            if not os.path.isfile(path):
                failures.append(
                    ScoreabilityFailure(
                        requirement="completeness",
                        input_identity=int(identity),
                        detail=f"deliverable not found at {path!r}",
                    )
                )
        return ScoreabilityVerdict(contract_id=self.contract_id, failures=tuple(failures))


class TidmadScoreabilityContract(ScoreabilityContract):
    """What the frozen TIDMAD scorer requires of a denoised deliverable.

    Declared AGAINST the producer-side :class:`DeliverableSpec` — the input
    channel group and the storage dtype are READ from it by
    :func:`derive_tidmad_metric_spec` — and stated here as evaluation-side
    requirements the LIVE scorer actually exercises on the deliverable
    (``scoring_utils._collect_raw_pairs``: ``ch=1`` from the DENOISED file at
    ``:477``; ``ch=2`` comes from the RAW validation file at ``:470``, which is
    an input-dataset fact, not a deliverable requirement):

    * **completeness** — every in-scope file (every requested input identity)
      has a deliverable on disk that opens as HDF5. File-level, deliberately:
      the scorer's own ``reshape(len // N, N)`` boundary is the frozen
      mechanism for a short segment, and its segment length is a scorer
      constant this contract must not re-declare (design §19, §19.2).
    * **required channel** — the input (denoised, ``ch=1``) sample dataset
      exists at the path the scorer reads. The deliverable's TARGET group is
      written by the producer but never read by the live scorer, so requiring
      it would be stricter than the frozen instance (ledger §20.4).
    * **required attrs** — ``voltage_range_mV`` and ``sampling_frequency`` on
      the input channel group, which the scorer reads unconditionally.
    * **required dtype** — the persisted sample dtype is the one the
      deliverable spec declares (``int8`` under TIDMAD); a float artifact would
      not crash the scorer, it would silently produce a wrong scale.

    ``_is_complete_trial_output`` (``inference_single.py``) is a crash-resume
    REUSE guard and is NOT this mechanism (design §1.1, §12).
    """

    contract_id: str = "tidmad_denoised_h5"
    input_channel_group: str = Field(
        description="Group holding the denoised signal the scorer reads as ch=1."
    )
    required_attrs: tuple[str, ...] = Field(default=TIDMAD_REQUIRED_ATTRS)
    required_storage_dtype: str = Field(
        description="NumPy dtype name the persisted samples must be stored as."
    )

    def _samples_key(self) -> str:
        return "/".join(
            (_TIDMAD_H5_ROOT_GROUP, self.input_channel_group, _TIDMAD_H5_SAMPLES_DATASET)
        )

    def check(self, deliverables: Mapping[int, str]) -> ScoreabilityVerdict:
        failures: list[ScoreabilityFailure] = []
        if not deliverables:
            failures.append(
                ScoreabilityFailure(
                    requirement="completeness",
                    detail="no in-scope file was named for scoring",
                )
            )
        for identity, path in deliverables.items():
            failures.extend(self._check_one(int(identity), path))
        return ScoreabilityVerdict(contract_id=self.contract_id, failures=tuple(failures))

    def _check_one(self, identity: int, path: str) -> list[ScoreabilityFailure]:
        def fail(requirement: str, detail: str) -> ScoreabilityFailure:
            return ScoreabilityFailure(
                requirement=requirement, input_identity=identity, detail=detail
            )

        if not os.path.isfile(path):
            return [fail("completeness", f"deliverable not found at {path!r}")]
        try:
            with h5py.File(path, "r") as handle:
                return self._check_open(handle, path, fail)
        except OSError as exc:
            return [fail("completeness", f"deliverable at {path!r} is not readable HDF5: {exc}")]

    def _check_open(
        self, handle: h5py.File, path: str, fail: Callable[[str, str], ScoreabilityFailure]
    ) -> list[ScoreabilityFailure]:
        failures: list[ScoreabilityFailure] = []
        key = self._samples_key()
        node = handle.get(key)
        if not isinstance(node, h5py.Dataset):
            failures.append(
                fail("required_channels", f"input channel dataset {key!r} missing in {path!r}")
            )
        else:
            found = str(node.dtype)
            if found != self.required_storage_dtype:
                failures.append(
                    fail(
                        "required_dtype",
                        f"{key!r} in {path!r} is stored as {found!r}, "
                        f"required {self.required_storage_dtype!r}",
                    )
                )
        attrs_group = handle.get("/".join((_TIDMAD_H5_ROOT_GROUP, self.input_channel_group)))
        if isinstance(attrs_group, h5py.Group):
            for attr in self.required_attrs:
                if attr not in attrs_group.attrs:
                    failures.append(
                        fail(
                            "required_attrs",
                            f"attr {attr!r} missing on group "
                            f"{_TIDMAD_H5_ROOT_GROUP}/{self.input_channel_group} in {path!r}",
                        )
                    )
        return failures


# ---------------------------------------------------------------------------
# The metric's declaration and its results
# ---------------------------------------------------------------------------


class MetricSpec(BaseModel):
    """A metric's declaration: identity, direction, aggregation, references,
    transform, and its executable scoreability contract.

    Mandatory components: ``id``, ``direction``, ``aggregation``,
    ``scoreability``. Optional: ``transform`` (+ params), ``references``.
    Frozen and extra-forbidding, so nothing loss-shaped can be attached.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(description="Stable metric identity, e.g. 'tidmad_denoising_score'.")
    direction: MetricDirection = Field(
        description="Which way is better — explicit, never inferred."
    )
    aggregation: str = Field(
        description="Identity of the rule that aggregates evidence to the scalar."
    )
    transform: str | None = Field(
        default=None, description="Named transform applied to the scalar, e.g. 'log'."
    )
    transform_params: dict[str, float] = Field(default_factory=dict)
    references: tuple[str, ...] = Field(
        default=(), description="Named reference kinds the interpretation layer may use."
    )
    scoreability: SerializeAsAny[ScoreabilityContract] = Field(
        description="Executable acceptance contract on the deliverable."
    )

    @field_validator("id")
    @classmethod
    def _id_is_a_metric(cls, value: str) -> str:
        return _validate_metric_identifier(value, field="id")


class MetricResult(BaseModel):
    """One attempt's evaluation — the record-facing, ADDITIVE payload.

    ``scalar`` is the metric's mandatory result. It is typed ``float | None``
    ONLY because the storage boundary (``coerce_nonfinite_to_none``, exactly as
    for ``denoising_score``) writes a non-finite sentinel such as the scorer's
    ``-inf`` as ``null``, and a persisted record must re-validate; a metric
    handle never produces ``None`` itself — a deliverable that cannot be
    scored yields :class:`NotScoreableResult`, not a result with no scalar.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric_id: str
    direction: MetricDirection
    scalar: float | None
    per_sample: list[float | None] | None = Field(
        default=None,
        description="Optional structured evidence indexed by input identity; None for scalar-only.",
    )
    references_used: tuple[str, ...] = Field(default=())

    @field_validator("metric_id")
    @classmethod
    def _id_is_a_metric(cls, value: str) -> str:
        return _validate_metric_identifier(value, field="metric_id")


class NotScoreableResult(BaseModel):
    """The structured outcome when the deliverable failed its contract.

    Carries the identity and direction of the metric that REFUSED, and the
    verdict naming every violated requirement — so a not-scoreable attempt is
    a typed record fact, not an incidental exception.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric_id: str
    direction: MetricDirection
    verdict: ScoreabilityVerdict

    @field_validator("metric_id")
    @classmethod
    def _id_is_a_metric(cls, value: str) -> str:
        return _validate_metric_identifier(value, field="metric_id")

    @model_validator(mode="after")
    def _verdict_names_a_failure(self) -> NotScoreableResult:
        if self.verdict.scoreable:
            raise ValueError(
                "NotScoreableResult requires a verdict with at least one failure; a "
                "scoreable verdict must yield a MetricResult."
            )
        return self


MetricOutcome = MetricResult | NotScoreableResult


class NoRunMetricError(RuntimeError):
    """A run has neither a declared metric nor the geometry to derive one.

    Step 12 / PR-12d, seam B. Deliberately NOT a ``NotScoreableError``: that
    one means "this deliverable cannot be scored", a structured scientific
    refusal the record persists. This means "the run's metric could not be
    established at all", which is a composition wiring failure and must stop
    the run rather than become an ``error_scoring`` record.
    """


class NotScoreableError(Exception):
    """A :class:`NotScoreableResult`, for callers whose contract is exception-based.

    The handle itself RETURNS the structured result. Some production seams
    report scoring-phase failures by raising — ``TidmadSandbox.score_vector``'s
    documented contract, and the tuner's scoring ``try`` block, which is the
    round-outcome path for every scoring failure (V8 Domain 2a). This carries
    the same structured result across such a seam unchanged; nothing about
    the refusal is lost, and it is never an incidental scorer exception.
    """

    def __init__(self, result: NotScoreableResult) -> None:
        self.result = result
        names = ", ".join(
            f"{f.requirement}"
            + (f"[{f.input_identity}]" if f.input_identity is not None else "")
            + f": {f.detail}"
            for f in result.verdict.failures
        )
        super().__init__(
            f"deliverable not scoreable under {result.verdict.contract_id!r} "
            f"(metric {result.metric_id!r}): {names}"
        )


# ---------------------------------------------------------------------------
# The runtime handle — scoreability FIRST, then the instance's arithmetic
# ---------------------------------------------------------------------------


class EvaluationMetric(ABC):
    """The handle production scoring invokes.

    :meth:`evaluate` is the ONE ordering authority: it runs the spec's
    scoreability contract and returns a :class:`NotScoreableResult` before any
    subclass arithmetic is reached. Subclasses implement only
    :meth:`_compute`; they cannot reorder the two.
    """

    #: The metric ids whose SEMANTICS this implementation computes.
    #:
    #: Step 12 / PR-12d D4c, closing **F-12d-3**. ``_compose_metric``'s only
    #: identity check was ``metric.spec.id != spec.id`` — and since
    #: ``__init__`` assigns ``self.spec = spec``, that compares the
    #: declaration to itself. It could fire only for an implementation that
    #: rewrites its own id, and was blind to the case the acceptance names: a
    #: declaration bound to the WRONG implementation. The shipped fixtures
    #: bound ``psnr`` AND ``mae`` to :class:`GlobalMseMetric`, and
    #: ``macro_f1`` to :class:`AccuracyMetric`, all composing green.
    #:
    #: A claim here is the implementation asserting, independently of the
    #: declaration it is handed, what arithmetic it performs. It does NOT
    #: reintroduce lexical parsing of ``MetricSpec.id`` (D16/C5): the
    #: framework still never interprets the string — it only checks that two
    #: parties agree. An implementation that makes NO claim (the default)
    #: composes under any id, which is what keeps a genuinely generic
    #: implementation reusable and keeps every pre-D4c binding valid.
    IMPLEMENTS: ClassVar[tuple[str, ...]] = ()

    def __init__(self, spec: MetricSpec) -> None:
        self.spec = spec

    def check_scoreability(self, deliverables: Mapping[int, str]) -> ScoreabilityVerdict:
        return self.spec.scoreability.check(deliverables)

    def evaluate(self, deliverables: Mapping[int, str], /, **compute_kwargs: Any) -> MetricOutcome:
        """Score ``deliverables`` — or refuse, structurally, before arithmetic.

        Args:
            deliverables: ``{input_identity: deliverable_path}`` — what the
                caller intends to score, as the scorer will open them.
            **compute_kwargs: Passed verbatim to the instance's
                :meth:`_compute`. For TIDMAD these are ``score_vector``'s own
                keyword arguments; the frozen call is not reshaped.
        """
        verdict = self.check_scoreability(deliverables)
        if not verdict.scoreable:
            return NotScoreableResult(
                metric_id=self.spec.id, direction=self.spec.direction, verdict=verdict
            )
        scalar, per_sample, references_used = self._compute(deliverables, **compute_kwargs)
        return MetricResult(
            metric_id=self.spec.id,
            direction=self.spec.direction,
            scalar=scalar,
            per_sample=per_sample,
            references_used=references_used,
        )

    @abstractmethod
    def _compute(
        self, deliverables: Mapping[int, str], /, **compute_kwargs: Any
    ) -> tuple[float, list[float | None] | None, tuple[str, ...]]:
        """The instance's arithmetic. Returns ``(scalar, per_sample, references_used)``."""


class TidmadDenoisingMetric(EvaluationMetric):
    """Instance #1: the frozen TIDMAD scorer, byte-identical, through the handle.

    ``_compute`` forwards its keyword arguments UNCHANGED to
    ``execute_tools.scoring_utils.score_vector`` and returns its 2-tuple as
    ``(scalar, file_vector, references_used)``. Nothing about the arithmetic,
    its parameters or its return contract is restated here.
    """

    IMPLEMENTS: ClassVar[tuple[str, ...]] = (TIDMAD_METRIC_ID,)

    def _compute(
        self, deliverables: Mapping[int, str], /, **compute_kwargs: Any
    ) -> tuple[float, list[float | None] | None, tuple[str, ...]]:
        from execute_tools.scoring_utils import score_vector

        file_vector, scalar = score_vector(**compute_kwargs)
        return scalar, file_vector, ("anchor_map",)


class AccuracyMetric(EvaluationMetric):
    """Instance #2 (D14-2): generic classification accuracy through the handle.

    Task-agnostic arithmetic and nothing else: the fraction of TRUTH ids
    whose prediction matches. The DENOMINATOR is the truth mapping (the
    final-eval scope authority), so a prediction missing from a partial
    deliverable counts as not-correct — exactly the declared aggregation
    ("fraction_correct_over_<scope>"). Direction, aggregation identity and
    the scoreability contract come from the binding ``MetricSpec`` (for
    Pets, the pack's DECLARED JSON via
    :func:`metric_spec_from_declaration`); ``per_sample`` is ``None`` — no
    per-file vector concept exists here.
    """

    IMPLEMENTS: ClassVar[tuple[str, ...]] = ("accuracy",)

    def _compute(
        self,
        deliverables: Mapping[int, str],
        /,
        *,
        predictions: Mapping[str, int],
        truth: Mapping[str, int],
    ) -> tuple[float, list[float | None] | None, tuple[str, ...]]:
        if not truth:
            raise ValueError(
                "accuracy needs a non-empty truth mapping — an empty final-eval "
                "scope is a caller wiring defect, not a scoreability case."
            )
        correct = sum(1 for image_id, label in truth.items() if predictions.get(image_id) == label)
        return correct / len(truth), None, ()


class GlobalMseMetric(EvaluationMetric):
    """Instance #3 (D14-3): dense-regression global mean squared error.

    Task-agnostic arithmetic: the EXACT global mean over every element of
    every scored sample — sums of squared error and element counts are
    accumulated across samples and divided ONCE. Never a mean-of-means:
    with unequal sample sizes those differ, and the frozen DAVIS
    aggregation is explicitly "the global mean over clips × C × T × H × W".

    A truth sample with no prediction is a LOUD error, not a zero: unlike a
    classification miss (a wrong label), a missing dense prediction has no
    defensible numeric stand-in, and a partial deliverable that scored
    anyway would silently flatter the model.
    """

    IMPLEMENTS: ClassVar[tuple[str, ...]] = ("mse",)

    def _compute(
        self,
        deliverables: Mapping[int, str],
        /,
        *,
        predictions: Mapping[str, Any],
        truth: Mapping[str, Any],
    ) -> tuple[float, list[float | None] | None, tuple[str, ...]]:
        import numpy as np

        if not truth:
            raise ValueError(
                "global MSE needs a non-empty truth mapping — an empty "
                "final-eval scope is a caller wiring defect."
            )
        missing = [key for key in truth if key not in predictions]
        if missing:
            raise ValueError(
                f"{len(missing)} scored sample(s) have no prediction "
                f"(first: {missing[0]!r}) — a dense deliverable must cover the "
                "scope it is scored on."
            )
        squared_error_sum = 0.0
        element_count = 0
        for key, truth_value in truth.items():
            expected = np.asarray(truth_value, dtype=np.float64)
            actual = np.asarray(predictions[key], dtype=np.float64)
            if actual.shape != expected.shape:
                raise ValueError(
                    f"prediction {key!r} has shape {actual.shape}, expected "
                    f"{expected.shape} — the deliverable does not match the task's "
                    "declared output geometry."
                )
            squared_error_sum += float(np.sum((actual - expected) ** 2))
            element_count += int(expected.size)
        return squared_error_sum / element_count, None, ()


# ---------------------------------------------------------------------------
# Declared-spec rebinding — the declaration IS the spec (D14-2 C5)
# ---------------------------------------------------------------------------

#: The declared-contract vocabulary: contract_id → concrete class. A
#: DECLARATION lookup, not a plugin surface — grows only when a new contract
#: class is added in this module.
_SCOREABILITY_CONTRACT_TYPES: dict[str, type[ScoreabilityContract]] = {
    "deliverable_presence": PresenceScoreabilityContract,
    "tidmad_denoised_h5": TidmadScoreabilityContract,
}


def scoreability_contract_from_declaration(payload: Mapping[str, Any]) -> ScoreabilityContract:
    """Rebuild a declared scoreability contract from its ``contract_id``.

    Fail closed: an unknown id names itself and the known vocabulary —
    a task pack cannot smuggle in an unimplemented acceptance contract.
    """
    contract_id = payload.get("contract_id")
    contract_cls = _SCOREABILITY_CONTRACT_TYPES.get(str(contract_id))
    if contract_cls is None:
        raise ValueError(
            f"unknown scoreability contract_id {contract_id!r}; known: "
            f"{sorted(_SCOREABILITY_CONTRACT_TYPES)}"
        )
    return contract_cls.model_validate(payload)


def metric_spec_from_declaration(payload: Mapping[str, Any]) -> MetricSpec:
    """A pack's declared metric JSON → the executable ``MetricSpec``.

    ``MetricSpec.model_validate`` alone cannot instantiate the ABSTRACT
    scoreability field from plain JSON; this is the ONE sanctioned rebind —
    everything else (id, direction, aggregation, transform, references)
    passes through the schema unchanged, so the committed declaration stays
    the single authority for the metric's identity.
    """
    data = dict(payload)
    data["scoreability"] = scoreability_contract_from_declaration(dict(data["scoreability"]))
    return MetricSpec.model_validate(data)


def _metric_spec_from_any(value: Any) -> Any:
    """Accept a ``MetricSpec``, or its own dumped declaration, unchanged.

    Step 09a C2. A ``MetricSpec`` cannot re-validate its own dump:
    ``scoreability`` is an ABSTRACT ``SerializeAsAny`` field, so
    ``spec.model_dump()`` emits the SUBCLASS's fields and
    ``MetricSpec.model_validate(...)`` rejects them as ``extra_forbidden``
    (verified: 3 errors). Any schema that PERSISTS a spec therefore has to
    route a mapping through :func:`metric_spec_from_declaration` — the ONE
    sanctioned rebind — on the way back in.

    Instances and ``None`` pass through untouched; anything else is left for
    pydantic to reject with its own message.
    """
    if isinstance(value, Mapping):
        return metric_spec_from_declaration(value)
    return value


#: A ``MetricSpec`` field that survives a JSON round trip.
#:
#: Use this — never a bare ``MetricSpec`` annotation — on any model that gets
#: written to disk and re-validated (``HyperparamTuningOutput.metric_spec``,
#: ``InterpretationInput.metric_spec``, ``SecondaryMetricEvidence.spec``).
#: It transports a value the run ALREADY resolved; it derives nothing.
MetricSpecField = Annotated[MetricSpec, BeforeValidator(_metric_spec_from_any)]


# ---------------------------------------------------------------------------
# Metric-identity reconciliation — "are these the SAME metric?"
#
# Step 10 P2a C1 (Q-P2a-3 = PROMOTE). Promoted here from
# ``nodes/result_interpretation_agent/evidence.py``, where it was node-private
# by ownership while THREE generic consumers outside that node needed the same
# decision.
#
# Deliberately NOT in ``MetricOrder``. The two questions are different
# responsibilities and must not merge:
#
#     reconciliation : "are these the same metric?"     -> here, beside MetricSpec
#     MetricOrder    : "for this KNOWN metric, which value is better?"
#
# Reconciliation runs FIRST. Ordering values whose identity has not been
# reconciled is how two incomparable metrics get ranked against each other
# while every individual comparison looks correct.
# ---------------------------------------------------------------------------


#: The canonical operator-facing name for the state in which a consumer holds
#: a score but no declared metric identity (Q-P2a-2 — ONE formatter, owned
#: beside the reconciliation authority rather than inside ``MetricOrder``,
#: which stays focused on ordering a metric that is already known).
#:
#: The wording is the parent's frozen Q-10-2 phrasing. It is a NAMED absence,
#: never a default: a consumer in this state shows raw values and refuses to
#: rank, and must never fall back to higher-is-better.
METRIC_IDENTITY_UNAVAILABLE = "metric direction unavailable / metric_spec absent"


def metric_identity_unavailable_notice(context: str, *, detail: str = "") -> str:
    """The ONE message a consumer prints when it cannot rank for lack of identity.

    Args:
        context: what could not be ranked, in the consumer's own words
            (e.g. ``"chain formal incumbent"``, ``"dashboard leaderboard"``).
        detail: optional extra clause naming the offending artifact(s).

    Returns:
        A single line beginning with the canonical
        :data:`METRIC_IDENTITY_UNAVAILABLE` phrase, so every consumer's
        refusal is greppable and reads the same way to an operator.
    """
    suffix = f" ({detail})" if detail else ""
    return (
        f"[metric] {METRIC_IDENTITY_UNAVAILABLE}: {context} is NOT ranked{suffix}. "
        "Raw values remain readable; no direction is assumed."
    )


def evaluate_declared_secondaries(
    secondaries: tuple[EvaluationMetric, ...],
    evaluate_one: Callable[[EvaluationMetric], MetricOutcome],
) -> tuple[list[MetricResult], list[NotScoreableResult], dict[str, str]]:
    """The run's DECLARED OBSERVATIONAL secondaries, through the ONE frozen
    exception taxonomy. Step 10 / P2b C2; Step 12 / PR-12d.

    **Extracted at Step 12 / PR-12d** so the taxonomy has exactly ONE body
    regardless of ROUTE. Before this, ``nodes/ml_hyperparameter_tune_agent/
    execution.py::_evaluate_secondary_metrics`` (the anchor-normalized,
    in-process route) and ``execute_tools/denoising_score_single.py::
    _evaluate_task_owned_secondaries`` (the task-owned, scoring-CHILD route,
    added by F-12d-18) each carried an independent copy of the same
    try/except order — exactly the twinning hazard
    ``test_the_secondary_evaluator_has_exactly_one_owner`` (Step 09a C6,
    Q-09-7) exists to catch, and did: a second evaluator is a second place a
    secondary outcome could come into existence, and the whole frozen
    exception taxonomy lived inside "this one function" only as long as
    there was exactly one.

    ``evaluate_one`` is the ONLY thing that legitimately differs by route —
    HOW a single secondary is evaluated (the anchor route calls
    ``sandbox.evaluate_metric(secondary, sample_set=..., ...)``; the
    task-owned route calls ``secondary.evaluate({0: deliverable}, **kwargs)``)
    — so it is the one parameter. The ORDER, and what happens in each branch,
    is not a parameter: it is frozen (design §4.2, operator ruling Q-P2b-2).

    ``NotScoreableError``
        a scientific refusal by THAT metric's contract. Recorded as a typed
        refusal; the attempt remains successful, because the primary already
        produced its result.
    ``ScopeViolationError``
        **RE-RAISED**. DataScope validation can run inside a secondary's own
        evaluation, so it CAN raise this, and the CALLER's existing outer
        handler owns it (terminate the run, non-retryable). "Observational"
        bounds ordinary secondary outcomes; it never means a
        framework-integrity failure gets swallowed. It must therefore be
        caught BEFORE the generic clause, exactly as the primary's own
        handlers are ordered.
    any other ``Exception``
        an implementation crash. Recorded as diagnostic PROVENANCE keyed by
        metric id and printed, never coerced into a ``NotScoreableResult`` —
        that would report a contract verdict nothing produced — and never
        raised onward.

    Returns:
        ``(results, refusals, errors)``, keyed consistently by metric id so
        no id can appear in two of them (each caller's own record validator
        enforces it).

    Raises:
        ScopeViolationError: re-raised from a secondary call, unchanged.
    """
    results: list[MetricResult] = []
    refusals: list[NotScoreableResult] = []
    errors: dict[str, str] = {}
    for secondary in secondaries:
        metric_id = secondary.spec.id
        try:
            outcome = evaluate_one(secondary)
            # A refusal reaches this taxonomy in TWO shapes, and both must land
            # in `refusals` (F-12d-33, found by CI pyright).
            #
            #   anchor route  -> `sandbox.evaluate_metric` converts a returned
            #                    `NotScoreableResult` into a RAISED
            #                    `NotScoreableError` and returns `MetricResult`
            #   task-owned    -> the child calls `secondary.evaluate(...)`
            #                    DIRECTLY, and that declares
            #                    `MetricOutcome = MetricResult |
            #                    NotScoreableResult` — so it RETURNS the refusal
            #
            # Appending the return value unconditionally therefore recorded a
            # child-side refusal as a SCORE, and `model_dump()`'d it into
            # `secondary_metric_results`. The anchor route can never produce
            # this branch, so its behaviour is unchanged.
            if isinstance(outcome, NotScoreableResult):
                refusals.append(outcome)
                print(f"  [secondary] {metric_id}: not scoreable — {outcome.verdict.contract_id}")
                continue
            results.append(outcome)
        except NotScoreableError as refusal:
            refusals.append(refusal.result)
            print(f"  [secondary] {metric_id}: not scoreable — {refusal}")
        except ScopeViolationError:
            raise
        except Exception as exc:
            errors[metric_id] = f"{type(exc).__name__}: {exc}"
            # The diagnostic surface, never a machine-readable stdout
            # contract and never a planner/reflector payload: a secondary
            # crash is an operator-facing fact about the implementation, not
            # evidence the model gets to reason from.
            print(f"  [secondary] {metric_id}: evaluation crashed — {errors[metric_id]}")
    return results, refusals, errors


class MetricIdentityConflictError(ValueError):
    """Two authorities disagree about which metric a comparison would rank on.

    Raised instead of silently choosing one, because every available way of
    choosing is wrong: preferring the bound spec ignores what the artifact was
    actually scored under, and preferring the artifact ignores the run the
    operator composed. The comparison is refused and the offenders are named.
    """


class MetricIdentityKey(NamedTuple):
    """The MINIMUM comparison identity: ``metric_id`` + ``direction``.

    Design §4.0/§4.4. A persisted ``ExperimentRecord`` carries exactly this
    pair (through ``metric_result``), never a whole ``MetricSpec``, so it is
    the granularity at which record-level corpora reconcile.

    Both fields are load-bearing and neither is sufficient alone. ``direction``
    without ``id`` would rank an accuracy against a PSNR because both are
    ``higher``; ``id`` without ``direction`` would let the same metric be
    ranked two opposite ways.
    """

    id: str
    direction: MetricDirection


#: Anything that can declare a metric's identity to reconciliation: the whole
#: declaration, or the minimum comparison pair a persisted record carries.
MetricDeclaration = MetricSpec | MetricIdentityKey


class StampedMetricSpec(NamedTuple):
    """One identity source offered to reconciliation.

    Attributes:
        label: how a refusal should NAME this source. Human-facing and
            quoted into the message, so it must identify the artifact an
            operator would go and look at.
        spec: the declaration this source carries — a whole ``MetricSpec`` or
            a :class:`MetricIdentityKey` — or ``None`` when it carries none (a
            legacy or pre-stamping artifact).
    """

    label: str
    spec: MetricDeclaration | None


def reconcile_metric_specs(
    stamped: Sequence[StampedMetricSpec],
    *,
    bound: MetricSpec | None = None,
    bound_label: str = "the run's bound task composition",
) -> MetricSpec | None:
    """The ONE compatible ``MetricSpec`` behind a set of identity sources.

    This COMPARES transported declarations. It derives nothing, infers nothing
    from a metric's name, a score's sign or the current task, and has no
    fallback.

    The frozen truth table (design §4.1):

    ==============  ==================  ==================================
    bound           stamped             outcome
    ==============  ==================  ==================================
    A               A                   A
    A               absent              A
    A               B                   refuse
    none            all A               A
    none            all absent          ``None`` — caller takes its
                                        unrankable state
    none            A and B             refuse
    ==============  ==================  ==================================

    A bound spec is an authoritative INPUT, never permission to ignore a
    conflicting artifact stamp — bound-A against stamped-B is a real
    inconsistency and must fail closed rather than go unobserved.

    PARTIAL stamping among the ``stamped`` sources is also a refusal: a set in
    which some artifacts declare a metric and others declare none spans more
    than one binding, and interpreting the stamped half would silently drop
    the rest. Callers that legitimately rank a SUBSET (a dashboard corpus, a
    resume record pool — design §4.2 case B) must exclude their
    identity-less members BEFORE calling this, so the exclusion is a visible
    act rather than a side effect of reconciliation.

    Whole specs are compared, not ids: the same id with an opposite direction
    is the most dangerous disagreement there is, because nothing about the
    identity looks wrong while the ranking inverts.

    Args:
        stamped: the identity sources carried by the artifacts being compared.
        bound: the run's composed metric spec, when the caller has one.
        bound_label: how a refusal names ``bound``.

    Returns:
        The single compatible spec, or ``None`` when no source declares one.

    Raises:
        MetricIdentityConflictError: on any disagreement — bound against
            stamp, stamp against stamp, or partial stamping.
    """
    reconciled = _reconcile_declarations(stamped, bound=bound, bound_label=bound_label)
    assert reconciled is None or isinstance(reconciled, MetricSpec)
    return reconciled


def reconcile_metric_identity(
    stamped: Sequence[StampedMetricSpec],
    *,
    bound: MetricSpec | None = None,
    bound_label: str = "the run's bound task composition",
) -> MetricIdentityKey | None:
    """The same reconciliation, at RECORD granularity.

    A persisted ``ExperimentRecord`` carries ``metric_result`` — ``metric_id``
    plus ``direction`` — not a whole ``MetricSpec``. That pair IS the minimum
    comparison identity (design §4.4), so record-level consumers reconcile on
    it while spec-level consumers reconcile on the whole declaration.

    Same engine, same truth table, same refusals — only the granularity of the
    comparison differs, and it is the COARSEST granularity present: every input
    is projected to :class:`MetricIdentityKey` before comparison, so a full
    spec and a record identity can be checked against each other. This is
    deliberately NOT a second reconciliation implementation; both entry points
    delegate to :func:`_reconcile_declarations`.

    Note that identity is weaker than a spec: two specs that share
    ``(id, direction)`` but differ in transform or aggregation reconcile HERE
    and refuse in :func:`reconcile_metric_specs`. That is correct — a record
    only ever declared the pair, so demanding more of it would refuse every
    real corpus.

    Returns:
        The single compatible identity, or ``None`` when no source declares
        one.

    Raises:
        MetricIdentityConflictError: on any disagreement.
    """
    projected = [
        StampedMetricSpec(label=entry.label, spec=_as_identity(entry.spec)) for entry in stamped
    ]
    reconciled = _reconcile_declarations(
        projected, bound=_as_identity(bound), bound_label=bound_label
    )
    assert reconciled is None or isinstance(reconciled, MetricIdentityKey)
    return reconciled


def metric_identity_from_record(record: Mapping[str, Any]) -> MetricIdentityKey | None:
    """The identity a PERSISTED record was scored under, or ``None``.

    Step 10 P2a C2. Reads only what Step 06 persisted —
    ``metric_result.metric_id`` and ``metric_result.direction`` — and never the
    metric's name, the score's sign, the task, or a default.

    It lives HERE, with the reconciliation authority, for the reason Step 06's
    C5 boundary guard enforces: validating a persisted direction means reading
    the ``MetricDirection`` vocabulary, and that vocabulary may be interpreted
    in exactly one module. A consumer that inlined ``direction in ("higher",
    "lower")`` would become a second declaration site — which is how a
    vocabulary drifts. The check below reads the declaration itself via
    ``get_args`` rather than restating its members.

    Returns:
        The ``(id, direction)`` pair, or ``None`` — a NAMED absence covering a
        legacy record, an unscored record, and a malformed one alike. Callers
        exclude such records from ranking individually (design §4.2 case B);
        they never guess a direction for them.
    """
    return metric_identity_from_mapping(record.get("metric_result"))


def metric_identity_from_mapping(payload: Any) -> MetricIdentityKey | None:
    """Validate a raw ``{metric_id, direction}`` mapping into an identity.

    The ONE validator for a transported metric identity, whatever shape
    carries it — a record's ``metric_result``, an
    ``InterpretationOutput.metric_identity`` digest field, or any future
    persisted echo of the same pair.

    It lives here because validating ``direction`` means reading the
    ``MetricDirection`` vocabulary, and that vocabulary may be interpreted in
    exactly one module (Step 06's C5 boundary guard enforces this). A consumer
    that inlined ``direction in ("higher", "lower")`` would become a second
    declaration site. The check reads the declaration itself through
    ``get_args`` rather than restating its members.

    Returns:
        The identity, or ``None`` for a NAMED absence — missing, malformed,
        or carrying a direction outside the declared vocabulary. Never a
        guess, and never a default.
    """
    if not isinstance(payload, Mapping):
        return None
    metric_id = payload.get("metric_id")
    direction = payload.get("direction")
    if not isinstance(metric_id, str) or not metric_id:
        return None
    if direction not in get_args(MetricDirection):
        return None
    # The membership test above IS the check, and it reads the declaration
    # itself rather than restating its members. `get_args` returns
    # `tuple[Any, ...]`, so a type checker cannot narrow through it; the cast
    # asserts only what the runtime check has already established. Spelling
    # the members here to help the checker would create the second direction
    # vocabulary this module exists to prevent.
    return MetricIdentityKey(id=metric_id, direction=cast(MetricDirection, direction))


def _as_identity(value: MetricDeclaration | None) -> MetricIdentityKey | None:
    """Project any identity source down to ``(id, direction)``."""
    if value is None:
        return None
    if isinstance(value, MetricIdentityKey):
        return value
    return MetricIdentityKey(id=value.id, direction=value.direction)


def _reconcile_declarations(
    stamped: Sequence[StampedMetricSpec],
    *,
    bound: MetricDeclaration | None,
    bound_label: str,
) -> MetricDeclaration | None:
    """THE reconciliation engine — the one place the truth table is decided.

    Both public entry points delegate here, so "are these the same metric?" is
    answered by exactly one implementation regardless of whether the caller
    holds whole specs or record identities.
    """
    present = [entry for entry in stamped if entry.spec is not None]
    absent = [entry for entry in stamped if entry.spec is None]

    if present and absent:
        raise MetricIdentityConflictError(
            "cannot reconcile the run MetricSpec: "
            f"{_name_specs(present)} carry one but {_name_specs(absent)} do not. "
            "A legacy/pre-09a tuning output lacks the stamped run MetricSpec required "
            "for interpretation ordering — re-produce it under Step 09a or start a "
            "fresh chain. No replacement spec is derived."
        )

    reference = bound
    reference_label = bound_label
    for entry in present:
        assert entry.spec is not None  # narrowed by the filter above
        if reference is None:
            reference, reference_label = entry.spec, entry.label
            continue
        if entry.spec != reference:
            raise MetricIdentityConflictError(
                "cannot reconcile the run MetricSpec: "
                f"{reference_label!r} declares "
                f"id={reference.id!r} direction={reference.direction!r}, but "
                f"{entry.label!r} declares "
                f"id={entry.spec.id!r} direction={entry.spec.direction!r}. "
                "One comparison covers one metric binding; a changed binding is a "
                "different run."
            )
    return reference


def _name_specs(entries: Sequence[StampedMetricSpec]) -> str:
    """Quoted labels, so a refusal names its offenders."""
    return ", ".join(entry.label for entry in entries) or "<none>"


# ---------------------------------------------------------------------------
# Regime-A derivation — the TIDMAD instance with NO declaration
# ---------------------------------------------------------------------------


def derive_tidmad_metric_spec(
    dataset_profile: DatasetProfile, deliverable_spec: DeliverableSpec | None = None
) -> MetricSpec:
    """THE derivation of the TIDMAD metric spec — one function, every caller.

    Regime A: no task declares this; a caller holding the run's profile (and
    optionally the run's already-derived deliverable spec) obtains the
    instance. The scoreability contract is declared AGAINST the deliverable
    spec — channel groups and storage dtype are read from it, never restated —
    which under TIDMAD resolves to the channels the frozen scorer addresses.

    Args:
        dataset_profile: The resolved profile in effect for this run.
        deliverable_spec: The run's Deliverable Contract. ``None`` derives it
            from the profile through 05c's own derivation, so a caller that
            has not bound one still gets exactly the shipped instance.
    """
    spec = (
        deliverable_spec
        if deliverable_spec is not None
        else derive_tidmad_deliverable_spec(dataset_profile)
    )
    return MetricSpec(
        id=TIDMAD_METRIC_ID,
        direction="higher",
        aggregation=TIDMAD_AGGREGATION_ID,
        transform=TIDMAD_TRANSFORM,
        transform_params={"log_base": float(_TIDMAD_LOG_BASE)},
        references=TIDMAD_REFERENCES,
        scoreability=TidmadScoreabilityContract(
            input_channel_group=spec.storage.input_channel_group,
            required_storage_dtype=spec.storage.storage_dtype,
        ),
    )


def derive_tidmad_metric(
    dataset_profile: DatasetProfile, deliverable_spec: DeliverableSpec | None = None
) -> TidmadDenoisingMetric:
    """The TIDMAD handle, bound to the spec :func:`derive_tidmad_metric_spec` derives."""
    return TidmadDenoisingMetric(derive_tidmad_metric_spec(dataset_profile, deliverable_spec))


def resolve_run_metric() -> EvaluationMetric:
    """Return the metric selected by the active task composition.

    A scientific metric has task-owned arithmetic, direction, scoreability,
    and references. The framework therefore cannot manufacture one when the
    caller omitted the task composition. Supported execution binds the metric
    before the tuner runs; reaching this function unbound is a wiring error.
    """
    declared = resolve_bound_run_metric()
    if declared is not None:
        return declared
    raise NoRunMetricError(
        "this run has no metric bound from a task composition; SIDERIUS cannot "
        "select a scientific metric implicitly"
    )


# ---------------------------------------------------------------------------
# Run-scoped metric binding (Step 10 / P1 C2)
# ---------------------------------------------------------------------------

_ACTIVE_RUN_METRIC: ContextVar[EvaluationMetric | None] = ContextVar(
    "siderius_active_run_metric", default=None
)


@contextmanager
def bind_run_metric(metric: EvaluationMetric) -> Iterator[EvaluationMetric]:
    """Bind the run's PRIMARY metric handle for the duration of the block.

    Exactly the ``bind_dataset_profile`` idiom (``dataset_config.py``): a
    ContextVar reset through a token, never module state, so a contrast run
    cannot leak its metric into the next one and nested scopes restore
    correctly even on an exception.

    This is a **seam, not a registry**. It stores an ``EvaluationMetric``
    instance that some other authority already produced — the composition
    edge builds it from a declaration through
    :func:`metric_spec_from_declaration` — so no second way for a metric
    identity to come into existence is introduced here. There is no id, no
    lookup and no table.
    """
    token = _ACTIVE_RUN_METRIC.set(metric)
    try:
        yield metric
    finally:
        _ACTIVE_RUN_METRIC.reset(token)


def resolve_bound_run_metric() -> EvaluationMetric | None:
    """The run's bound primary metric, or ``None`` when nothing is bound.

    Deliberately returns ``None`` rather than falling back to the TIDMAD
    derivation: the caller (the tuner's single run-scoped acquisition site)
    keeps its legacy derivation visible as the un-composed branch, so what
    an un-composed run does stays readable at the site that does it rather
    than hidden behind a helper that silently picks a task.
    """
    return _ACTIVE_RUN_METRIC.get()


# ---------------------------------------------------------------------------
# Run-scoped SECONDARY metric binding (Step 10 / P2b C1)
# ---------------------------------------------------------------------------

_ACTIVE_RUN_SECONDARY_METRICS: ContextVar[tuple[EvaluationMetric, ...]] = ContextVar(
    "siderius_active_run_secondary_metrics", default=()
)


@contextmanager
def bind_run_secondary_metrics(
    metrics: tuple[EvaluationMetric, ...],
) -> Iterator[tuple[EvaluationMetric, ...]]:
    """Bind the run's DECLARED OBSERVATIONAL secondary metrics for the block.

    The primary's idiom (:func:`bind_run_metric`), in the same module, for the
    same reasons: a token-reset ContextVar rather than module state, so nested
    and sequential runs in one process never observe each other's declared
    set. It lives beside the primary's pair because the tuner acquires both at
    ONE site, and the composition module's own placement rule is that a value
    consumed through an ambient acquisition is bound ambiently.

    Like the primary's, this is a **seam, not a registry**: the composition
    edge already resolved these instances through
    :func:`metric_spec_from_declaration`, so no second way for a metric
    identity to come into existence is introduced. There is no id, no lookup
    and no table — and emphatically no ordering: a secondary is observational
    evidence and never an operand of a ranking decision.

    The bound value is a TUPLE and may legitimately be empty: a task that
    declares no secondary binds ``()``, which is indistinguishable from an
    un-composed run by design (§4.7's zero-secondary invariant).
    """
    token = _ACTIVE_RUN_SECONDARY_METRICS.set(tuple(metrics))
    try:
        yield tuple(metrics)
    finally:
        _ACTIVE_RUN_SECONDARY_METRICS.reset(token)


def resolve_bound_run_secondary_metrics() -> tuple[EvaluationMetric, ...]:
    """The run's declared secondaries, or ``()`` when nothing is bound.

    Returns the EMPTY TUPLE rather than ``None``, which is the difference
    between this and :func:`resolve_bound_run_metric`: an un-composed run has
    no primary to fall back to and must keep its legacy derivation visible at
    the acquisition site, whereas "no declared secondaries" is not a fallback
    at all — it is the answer, and it is the same answer a composed
    zero-secondary task gives.
    """
    return _ACTIVE_RUN_SECONDARY_METRICS.get()
