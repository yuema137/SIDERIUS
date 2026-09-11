# agent/schemas/model_io_resolution.py
"""Resolution of an authored Model-I/O declaration into ONE normalized contract.

Design:
``docs/design/generic_framework_upgrade/step_03_model_loss_contract.md``
§4b (cardinality: derive or cross-validate), §9 (only machine-checkable
overlaps fail closed), §11 rungs **FX-3 / FX-4 / 3-E**, §16 (invalid-state
analogues; resolution at call time, never import time), §21.

Binding inheritance: FX-3 and FX-4 are deferred decision **D13**, handed to
"the contract owner" by Step 01, whose §6A.5 froze the rule this module
implements:

    when a preset and explicit tensor information are both present and
    inconsistent, the run must fail with an explicit typed error **before
    any LLM request is constructed**. Silently rewriting the shape,
    silently dropping the preset, silently defaulting to TIDMAD, inferring
    semantics from model names, or letting contradictory prose reach the
    Proposer are all forbidden.

**The lifecycle, and where the preset goes.**

```text
authoring form  (explicit contract [+ preset label] [+ dataset profile])
      |
      v  resolve_model_io_contract()   <- the ONLY place a preset is read
      |
      v
ONE normalized ModelIOContract  ->  consumers
```

The preset **does not survive resolution**. The returned object is the same
``ModelIOContract`` type every consumer already takes, carrying no preset
field, so no runtime consumer can branch on a preset label, a modality name
or a tensor rank (§21). That is not a convention here — it is structural,
and ``test_model_io_resolution.py`` asserts it mechanically.

**Why presets are requirement-only.** §6A.5's own failure examples are
*"``time_series`` with no temporal axis; ``spatial_grid`` with no spatial
axis"* — i.e. the preset is a CONSTRAINT the explicit contract must satisfy,
not a supplier of axes. A supplying preset was considered and rejected: it
would have to invent an axis ORDER that no source supports, and inventing
one would bake a modality's conventional layout into the framework — the
opposite of what §4d asks roles to achieve. Recorded as an implementation
decision in ledger §24.6, not silently chosen.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from agent.schemas.model_io_contract import AxisRole, ModelIOContract


class ModelIOResolutionError(ValueError):
    """Base class for every typed resolution failure.

    A single base so a caller can fail closed on *"this declaration is not
    resolvable"* without enumerating causes, while the subclasses keep the
    cause legible at the boundary that raises it.
    """


class UnknownPresetError(ModelIOResolutionError):
    """An authored preset name that no preset defines (§16 invalid-state)."""


class PresetContradictionError(ModelIOResolutionError):
    """**FX-4.** The preset and the explicit contract disagree.

    Raised before any consumer — and therefore before any LLM request is
    constructed, which is the property Step-01 §6A.5 could not implement
    and handed forward as D13.
    """


class DatasetContradictionError(ModelIOResolutionError):
    """**3-E.** The contract's cardinality contradicts the Dataset Profile.

    The dataset-side fact is authoritative (§4b): ``ValueEncoding.num_classes``
    is what the data actually provides. A contract claiming a different class
    count is a machine-checkable contradiction, and silently coercing either
    side is forbidden (§21).
    """


class ModelIOPreset(BaseModel):
    """A named authoring shorthand: the axis roles a contract must declare.

    A preset asserts *semantic structure*, never dimensions, dtype or axis
    order. It is authoring convenience plus a machine-checked guarantee —
    never a runtime authority.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, description="The authored label.")
    required_input_roles: frozenset[AxisRole] = Field(
        default_factory=frozenset,
        description="Axis roles the INPUT tensor must declare.",
    )
    required_output_roles: frozenset[AxisRole] = Field(
        default_factory=frozenset,
        description="Axis roles the OUTPUT tensor must declare.",
    )


#: The shipped preset registry.
#:
#: ``sequence`` is deliberately the only entry, and deliberately NOT named
#: for a modality. It carries exactly the requirement the one shipped task
#: has — a batch axis and a temporal axis on both tensors — and nothing
#: about waveforms, signals or time series. A ``spatial_grid`` preset is NOT
#: shipped: it would need a ``spatial`` axis role that no production
#: consumer reads, which is the consumer-less field §21 forbids. Presets are
#: additive when a real authored task needs one.
PRESETS: dict[str, ModelIOPreset] = {
    "sequence": ModelIOPreset(
        name="sequence",
        required_input_roles=frozenset({AxisRole.BATCH, AxisRole.TEMPORAL}),
        required_output_roles=frozenset({AxisRole.BATCH, AxisRole.TEMPORAL}),
    ),
}


def _missing_roles(contract: ModelIOContract, preset: ModelIOPreset) -> list[tuple[str, AxisRole]]:
    """Every (tensor, role) the preset requires and the contract lacks."""
    missing: list[tuple[str, AxisRole]] = []
    for tensor_name, required in (
        ("input", preset.required_input_roles),
        ("output", preset.required_output_roles),
    ):
        tensor = getattr(contract, tensor_name)
        for role in sorted(required):
            if tensor.axis_with_role(role) is None:
                missing.append((tensor_name, role))
    return missing


def resolve_model_io_contract(
    contract: ModelIOContract,
    *,
    preset: str | None = None,
    dataset_num_classes: int | None = None,
) -> ModelIOContract:
    """Validate an authored declaration and return the normalized contract.

    Call-time only. Nothing here runs at import time, so a bad declaration
    cannot poison a module import and surface somewhere unrelated (§16, the
    02b §13.9 lesson).

    Args:
        contract: The explicit normalized contract as authored.
        preset: Optional preset label. Read HERE and nowhere else; it does
            not appear on the returned object.
        dataset_num_classes: The Dataset Profile's ``ValueEncoding.num_classes``
            when one is bound. Passed in rather than resolved here so this
            module states its dependency instead of reaching for ambient
            state, and so a caller with no bound profile is not forced to
            invent one.

    Returns:
        The SAME normalized contract, proven consistent. Resolution
        validates and normalizes; it never rewrites shapes, drops a preset
        or substitutes a class count (§21).

    Raises:
        UnknownPresetError: the preset name is not defined.
        PresetContradictionError: the preset's required roles are not all
            declared — **FX-4**.
        DatasetContradictionError: the contract's class cardinality
            disagrees with the dataset's — **3-E**.
    """
    if preset is not None:
        known = PRESETS.get(preset)
        if known is None:
            raise UnknownPresetError(
                f"unknown Model-I/O preset {preset!r}; defined presets: {sorted(PRESETS)}"
            )
        missing = _missing_roles(contract, known)
        if missing:
            detail = ", ".join(f"{tensor}.{role.value}" for tensor, role in missing)
            raise PresetContradictionError(
                f"preset {preset!r} requires axis roles the contract does not "
                f"declare: {detail}. The preset is not dropped and the contract "
                "is not rewritten — resolve the contradiction in the declaration."
            )

    if dataset_num_classes is not None:
        declared = contract.class_cardinality
        # `None` is the explicit "cardinality is not meaningful for this
        # output semantic" of §4b, NOT a missing value. A continuous-output
        # contract is not obliged to carry the dataset's class count, and
        # forcing one would be the very redeclaration §4b forbids.
        if declared is not None and declared != dataset_num_classes:
            raise DatasetContradictionError(
                f"the contract's output class cardinality ({declared}) contradicts "
                f"the dataset's ValueEncoding.num_classes ({dataset_num_classes}). "
                "The dataset-side fact is authoritative; neither value is coerced."
            )

    return contract
