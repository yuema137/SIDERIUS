"""Task-owned judge declarations: guidance blocks and versioned rubrics.

A task composition manifest may declare scientific guidance for LLM judges
(``judge_blocks:``) and rubric files (``rubrics:``). Both are optional; when
absent, nothing is rendered and no fingerprint key is added (the full
fingerprint still moves with the preflight estimation assembly on any
framework revision that edits a file it hashes).

A rubric is a declared scoring scheme for LLM judges, never a task metric. It
names integer criteria; the weighted mean is computed by framework code from
validated per-criterion integers (the LLM never emits a total). A rubric is
identified by ``(id, version)`` and bound to its exact content by
:func:`rubric_sha256`. A consumer names a rubric through a :class:`RubricRef`
and resolves it with :func:`resolve_rubric_ref`, which refuses an unknown
rubric and any content digest mismatch.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from agent.schemas.data_analysis.common import canonical_sha256

Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]*$", max_length=100)]
Version = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$", max_length=40)]


#: Bounds keep judge payloads and rubric arithmetic small and reviewable.
MAX_RUBRIC_CRITERIA = 32
MAX_RUBRIC_WEIGHT = 100.0
MAX_RUBRIC_SCALE_SPAN = 100
#: Debate rounds a ``debate-judge/v1`` declaration may request (declaration and
#: debate call schemas share it; kept here because declarations import only this module).
MAX_DEBATE_ROUNDS = 4


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)


class JudgeTaskBlocks(BaseModel):
    """Task-owned judge guidance: prose values under framework-owned keys.

    Same shape as the other ``*_blocks`` families: every field optional, an
    absent field renders nothing. The framework owns where each value renders.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    evaluation_guidance: str | None = Field(
        default=None,
        description="How this task's results should be judged scientifically.",
    )
    failure_signatures: str | None = Field(
        default=None,
        description="Known signatures of scientifically failed or misleading results.",
    )


def judge_guidance_sha256(blocks: JudgeTaskBlocks) -> str:
    """Identity of declared judge guidance (``task_guidance_sha256`` in judge requests)."""
    return canonical_sha256(blocks.model_dump(mode="json"))


class RubricCriterion(_StrictModel):
    name: Identifier
    description: str = Field(min_length=1, max_length=1000)
    weight: float = Field(gt=0, le=MAX_RUBRIC_WEIGHT)


class RubricSpec(_StrictModel):
    """One declared, versioned rubric. Not a metric; never enters ``MetricOrder``."""

    schema_version: Literal["siderius.rubric/v1"]
    id: Identifier
    version: Version
    # Declarations are YAML lists; only the list-to-tuple coercion is relaxed.
    criteria: tuple[RubricCriterion, ...] = Field(
        min_length=1, max_length=MAX_RUBRIC_CRITERIA, strict=False
    )
    scale_min: int
    scale_max: int

    @model_validator(mode="after")
    def _check_criteria_and_scale(self) -> Self:
        names = [criterion.name for criterion in self.criteria]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"rubric criterion names must be unique; duplicated: {duplicates}")
        if self.scale_max <= self.scale_min:
            raise ValueError(
                f"rubric scale_max ({self.scale_max}) must exceed scale_min ({self.scale_min})"
            )
        if self.scale_max - self.scale_min > MAX_RUBRIC_SCALE_SPAN:
            raise ValueError(
                f"rubric scale span {self.scale_max - self.scale_min} exceeds "
                f"{MAX_RUBRIC_SCALE_SPAN}"
            )
        return self


class RubricRef(_StrictModel):
    """Exact reference to a rubric: identity plus the content digest it was declared with."""

    id: Identifier
    version: Version
    sha256: Digest


def rubric_sha256(spec: RubricSpec) -> str:
    """Digest of the rubric's canonical JSON; any content change moves it."""
    return canonical_sha256(spec.model_dump(mode="json"))


def rubric_ref(spec: RubricSpec) -> RubricRef:
    return RubricRef(id=spec.id, version=spec.version, sha256=rubric_sha256(spec))


class RubricRefError(ValueError):
    """A :class:`RubricRef` does not resolve to exactly the declared rubric."""

    def __init__(self, reason: Literal["unknown_rubric", "digest_mismatch"], message: str):
        super().__init__(message)
        self.reason = reason


def resolve_rubric_ref(ref: RubricRef, available: Iterable[RubricSpec]) -> RubricSpec:
    """Return the rubric ``ref`` names. FAIL-CLOSED on unknown identity or digest mismatch."""
    for spec in available:
        if (spec.id, spec.version) != (ref.id, ref.version):
            continue
        actual = rubric_sha256(spec)
        if actual != ref.sha256:
            raise RubricRefError(
                "digest_mismatch",
                f"rubric {ref.id!r} version {ref.version!r} content digest is {actual}, "
                f"but the reference binds {ref.sha256}; a changed rubric needs a new version",
            )
        return spec
    raise RubricRefError(
        "unknown_rubric", f"rubric {ref.id!r} version {ref.version!r} is not declared"
    )


class JudgeTaskDeclarations(_StrictModel):
    """The task's composed judge declarations. ``None`` on the composition when absent."""

    blocks: JudgeTaskBlocks | None = None
    rubrics: tuple[RubricSpec, ...] = ()

    @model_validator(mode="after")
    def _unique_rubric_identities(self) -> Self:
        keys = [(spec.id, spec.version) for spec in self.rubrics]
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        if duplicates:
            raise ValueError(f"rubric (id, version) declared more than once: {duplicates}")
        return self

    def rubric_refs(self) -> tuple[RubricRef, ...]:
        return tuple(rubric_ref(spec) for spec in self.rubrics)

    def canonical_identity(self) -> dict[str, Any]:
        """Fingerprint payload: guidance content plus each rubric's exact reference.

        Rubrics are addressed by ``(id, version)``, so declaration order is not
        semantic and the references are sorted.
        """
        identity: dict[str, Any] = {}
        if self.blocks is not None:
            identity["judge_blocks"] = self.blocks.model_dump(mode="json")
        if self.rubrics:
            refs = sorted(self.rubric_refs(), key=lambda ref: (ref.id, ref.version))
            identity["rubrics"] = [ref.model_dump(mode="json") for ref in refs]
        return identity
