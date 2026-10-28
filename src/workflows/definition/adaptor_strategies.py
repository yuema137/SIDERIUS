"""Closed, versioned deterministic adaptor strategies and the shared B6 types.

Every strategy is a frozen declaration discriminated on ``kind``; the kind string
carries its version, so a changed semantic needs a new kind. B2 imports
``SelectStrategy``, ``CardinalityBound``, ``Fallback`` and ``derive_cardinality``
from here for its LLM COMBINE kinds. Contract: ``src/workflows/adaptors/adaptor-contract.md``.
"""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .base import DeclarationModel

#: The one ceiling on adaptor output fan-out. Every DISTRIBUTE ``count`` is at
#: most this, so static topology and B3 control-size admission are computed
#: from a bounded number. The custom-adaptor manifest (``OutputSpec.count``)
#: imports the same constant, so built-in and custom outputs share one cap.
MAX_ADAPTOR_OUTPUTS = 64


class PassCombine(DeclarationModel):
    """The admissible items, unchanged, in declared order."""

    kind: Literal["pass/v1"] = "pass/v1"


class CollectCombine(DeclarationModel):
    """One collection of every admissible item with per-item attribution."""

    kind: Literal["collect/v1"] = "collect/v1"


class ConcatItemsCombine(DeclarationModel):
    """One value whose catalogued list is the declared-order concatenation."""

    kind: Literal["concat-items/v1"] = "concat-items/v1"
    field: str = Field(min_length=1)


class MetricRankCombine(DeclarationModel):
    """Rank ``tuning.output`` items by the Health-qualified formal score under ``MetricOrder``."""

    kind: Literal["metric-rank/v1"] = "metric-rank/v1"
    score: Literal["best_valid_formal"]


class FieldRankCombine(DeclarationModel):
    """Rank the catalogued list entries of one value by a catalogued (non-metric) field.

    ``order`` is a sort order of a plain field, deliberately not the metric
    ``direction`` vocabulary, which only ``MetricOrder`` interprets.
    """

    kind: Literal["field-rank/v1"] = "field-rank/v1"
    field: str = Field(min_length=1)
    order: Literal["descending", "ascending"]


DeterministicCombine = Annotated[
    PassCombine | CollectCombine | ConcatItemsCombine | MetricRankCombine | FieldRankCombine,
    Field(discriminator="kind"),
]


class AllSelect(DeclarationModel):
    kind: Literal["all/v1"] = "all/v1"


class FirstAdmissibleSelect(DeclarationModel):
    kind: Literal["first-admissible/v1"] = "first-admissible/v1"


class TopKSelect(DeclarationModel):
    """The ``k`` best of a ranking; ``k=1`` is "best-1"."""

    kind: Literal["top-k/v1"] = "top-k/v1"
    k: Annotated[int, Field(ge=1)]


class ThresholdSelect(DeclarationModel):
    """Keep items that clear ``at_least`` on the ranking's own scale, in declared order.

    ``basis="metric"`` names the run metric (checked at use) and never declares a
    direction; ``basis="rubric"`` is a B2 rubric total, higher-is-better by type.
    """

    kind: Literal["threshold/v1"] = "threshold/v1"
    basis: Literal["metric", "rubric"]
    metric_id: str | None = Field(default=None, min_length=1)
    at_least: float = Field(allow_inf_nan=False)

    @model_validator(mode="after")
    def metric_id_iff_metric(self) -> Self:
        if (self.basis == "metric") != (self.metric_id is not None):
            raise ValueError("threshold/v1 declares metric_id if and only if basis is 'metric'")
        return self


SelectStrategy = Annotated[
    AllSelect | FirstAdmissibleSelect | TopKSelect | ThresholdSelect,
    Field(discriminator="kind"),
]


class SingleDistribute(DeclarationModel):
    kind: Literal["single/v1"] = "single/v1"


class PerItemDistribute(DeclarationModel):
    """Selected item ``i`` goes to output index ``i``."""

    kind: Literal["per-item/v1"] = "per-item/v1"
    count: Annotated[int, Field(ge=1, le=MAX_ADAPTOR_OUTPUTS)]
    on_short: Literal["skip", "fail"]


class SplitItemsDistribute(DeclarationModel):
    """One list-bearing value becomes ``count`` values that each keep one list entry."""

    kind: Literal["split-items/v1"] = "split-items/v1"
    field: str = Field(min_length=1)
    count: Annotated[int, Field(ge=1, le=MAX_ADAPTOR_OUTPUTS)]
    on_short: Literal["skip", "fail"]


class ReplicateDistribute(DeclarationModel):
    kind: Literal["replicate/v1"] = "replicate/v1"
    count: Annotated[int, Field(ge=2, le=MAX_ADAPTOR_OUTPUTS)]


DistributeStrategy = Annotated[
    SingleDistribute | PerItemDistribute | SplitItemsDistribute | ReplicateDistribute,
    Field(discriminator="kind"),
]


class Fallback(DeclarationModel):
    """The value of an LLM kind's ``on_failure``: replaces only the COMBINE stage."""

    kind: Literal["fallback"] = "fallback"
    combine: Annotated[
        PassCombine | MetricRankCombine | FieldRankCombine, Field(discriminator="kind")
    ]


class CardinalityBound(DeclarationModel):
    """How many values SELECT may hand to DISTRIBUTE; derived, never authored."""

    min: Annotated[int, Field(ge=0)]
    max: Annotated[int, Field(ge=1)]

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.min > self.max:
            raise ValueError(f"unsatisfiable cardinality: min {self.min} > max {self.max}")
        return self


def derive_cardinality(select: SelectStrategy, distribute: DistributeStrategy) -> CardinalityBound:
    """The value-count bound implied by SELECT and DISTRIBUTE.

    Raises ``ValueError`` when the pair cannot be satisfied (for example
    ``per-item(M, fail)`` after ``top-k(k < M)``).
    """
    match distribute:
        case PerItemDistribute(count=count, on_short=on_short):
            low, high = (1, count) if on_short == "skip" else (count, count)
        case SingleDistribute() | SplitItemsDistribute() | ReplicateDistribute():
            low, high = 1, 1
    match select:
        case TopKSelect(k=k):
            high = min(high, k)
        case FirstAdmissibleSelect():
            high = min(high, 1)
        case AllSelect() | ThresholdSelect():
            pass
    return CardinalityBound(min=low, max=high)


def incompatible_pair(combine: DeterministicCombine, distribute: DistributeStrategy) -> str | None:
    """Why ``distribute`` cannot follow ``combine``, or ``None``.

    The one owner of this rule: declaration validation refuses the pair, and the
    strategy core refuses it again before admission.
    """
    single_value = isinstance(combine, CollectCombine | ConcatItemsCombine | FieldRankCombine)
    if single_value and isinstance(distribute, PerItemDistribute):
        return f"per-item/v1 cannot follow {combine.kind}: it yields one value"
    if isinstance(combine, CollectCombine) and isinstance(distribute, SplitItemsDistribute):
        return "split-items/v1 cannot split a collect/v1 collection"
    return None
