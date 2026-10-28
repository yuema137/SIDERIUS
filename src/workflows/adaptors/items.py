"""Typed adaptor inputs and the shared deterministic admissibility filter.

Admissibility reads validity and scoreability facts the deterministic core already
committed; it never computes or rewrites them.
"""

from typing import TYPE_CHECKING, Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny, model_validator

from workflows.definition.catalog import METRIC_SCORED_CONTRACTS, VALIDITY_GATED_CONTRACTS
from workflows.definition.models import Identifier, Source

if TYPE_CHECKING:
    from agent.schemas.hyperparam_tuning import HyperparamTuningOutput

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
ItemState = Literal["succeeded", "rejected", "skipped"]
Admission = Literal["admissible", "rejected", "skipped", "not_scoreable", "health_invalid"]


class AdaptorStrategyError(ValueError):
    """A declared strategy cannot be applied to these inputs; never coerced."""


class AdaptorModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class AdaptorInputRef(AdaptorModel):
    """Where one contributing value came from, in declared order."""

    port: Identifier
    position: int = Field(ge=0)
    source: Source
    record_sha256: Digest
    item_path: str | None = None  # e.g. "findings[2]" for one list entry

    def entry(self, list_field: str, index: int) -> "AdaptorInputRef":
        return self.model_copy(update={"item_path": f"{list_field}[{index}]"})


class AdaptorItem(AdaptorModel):
    """One bound upstream result, already validated against its contract by the caller."""

    ref: AdaptorInputRef
    contract: str = Field(min_length=1)
    state: ItemState
    value: SerializeAsAny[BaseModel] | None

    @model_validator(mode="after")
    def value_iff_succeeded(self) -> Self:
        if (self.state == "succeeded") != (self.value is not None):
            raise ValueError("an adaptor item carries a value if and only if it succeeded")
        return self


class ItemAdmission(AdaptorModel):
    ref: AdaptorInputRef
    admission: Admission


def tuning_output(item: AdaptorItem) -> "HyperparamTuningOutput":
    # Lazy: the parent import must not discover native plugins before child binding.
    from agent.schemas.hyperparam_tuning import HyperparamTuningOutput

    if not isinstance(item.value, HyperparamTuningOutput):
        raise AdaptorStrategyError(f"{_label(item)} is not a tuning.output value")
    return item.value


def admit(item: AdaptorItem) -> Admission:
    """The B6/B2 admissibility rule for one item (B6 §2 rule 3)."""
    if item.state != "succeeded":
        return item.state
    if item.contract in VALIDITY_GATED_CONTRACTS:
        from agent.schemas.validator import ValidatorOutput

        if not isinstance(item.value, ValidatorOutput):
            raise AdaptorStrategyError(f"{_label(item)} is not a validation.output value")
        return "admissible" if item.value.passed else "rejected"
    if item.contract in METRIC_SCORED_CONTRACTS:
        output = tuning_output(item)
        if output.best_valid_formal_denoising_score is not None:
            return "admissible"
        # A formal score without a Health-valid formal record is Health-invalid.
        return "not_scoreable" if output.best_formal_denoising_score is None else "health_invalid"
    return "admissible"


def admit_items(items: tuple[AdaptorItem, ...]) -> tuple[ItemAdmission, ...]:
    """Admission of every item; refuses items not in declared order.

    Declared order means each port's items are contiguous and their positions
    strictly increase, so a permuted or completion-ordered tuple cannot pass.
    """
    finished: set[str] = set()
    previous: AdaptorItem | None = None
    for item in items:
        port = item.ref.port
        if previous is not None and previous.ref.port == port:
            if item.ref.position <= previous.ref.position:
                raise AdaptorStrategyError(
                    f"adaptor input {_label(item)} follows {_label(previous)}: not declared order"
                )
        elif port in finished:
            raise AdaptorStrategyError(f"adaptor port {port!r} items are not contiguous")
        if previous is not None and previous.ref.port != port:
            finished.add(previous.ref.port)
        previous = item
    return tuple(ItemAdmission(ref=item.ref, admission=admit(item)) for item in items)


def _label(item: AdaptorItem) -> str:
    return f"{item.ref.port}:{item.ref.position}"
