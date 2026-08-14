"""Step-04 probe recipes: how to build ONE minimal instance of a contract.

Design: ``docs/design/generic_framework_upgrade/step_04_candidate_creation_mechanics/
pr_04a_contract_derived_candidate_mechanics.md`` §1 (contract-owned facts vs
Step-04 recipes), §4 (the custom-loss recipe), §15.1 (the four-row caller
contract); parent §3 (authority map) and §10 (the recipe/semantics boundary).

**The one line this module draws.**

```text
"what is a valid tensor for this task?"   -> Step-03 ModelIOContract  (DERIVE)
"how do I build one minimal instance      -> Step-04 recipe           (DECLARE)
 in order to test a candidate?"
```

Contract-owned facts — class cardinality, rank, ordered axis roles, fixed
extents, dtype admissibility, output semantic — are read from the contract
and never restated. Validation-convenience choices — the concrete
realization of a *symbolic* extent, the probe batch size — are declared
here, as recipes. Pushing them into task config to make literals disappear
is explicitly wrong (parent §10), because a probe size is not something a
task knows about itself.

**One recipe module, two consumers.** The validator's in-process shape probe
and the implementor's self-check + loss probe all build instances of the
same declaration. Two copies of these rules would be two authorities, and
the way that fails is silent: the implementor emits a candidate its own
generated test accepts and the validator then rejects, or vice versa.

This module deliberately does not import ``torch`` at module scope — the
implementor keeps torch off its import-time path, and this module is
imported by it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent.schemas.model_io_contract import AxisRole, ModelIOContract, TensorContract
from ml_models.models_format_sandbox import OutputSemantic

if TYPE_CHECKING:  # pragma: no cover - typing only
    import torch

__all__ = [
    "LOSS_PROBE_BATCH",
    "LOSS_PROBE_LENGTH",
    "PROBE_BATCH",
    "PROBE_SYMBOLIC_EXTENT",
    "ProbeConstructionError",
    "build_loss_probe_pair",
    "build_model_input",
    "declared_output_tensor",
    "expected_output_shape",
    "input_index_extent",
    "loss_probe_semantic",
    "realize_shape",
]


# ---------------------------------------------------------------------------
# The recipe constants — Step-04-owned, deliberately NOT task config
# ---------------------------------------------------------------------------

#: Batch extent used when realizing a symbolic batch axis. One sample is
#: enough to check a shape and a gradient path, and it keeps the probe cheap
#: enough to run on every candidate.
PROBE_BATCH: int = 1

#: Extent used to realize a symbolic or dynamic non-batch axis — the ``T = 64``
#: the design keeps as a recipe. A symbolic dimension declares ALIGNMENT
#: ("input T and output T are the same extent"), not a magnitude, so any
#: value satisfies it equally and the choice is pure validation convenience.
#: That is also why varying it is not a semantic contrast (design §6.1).
PROBE_SYMBOLIC_EXTENT: int = 64

#: Index extent used when the contract declares NO class alphabet but the
#: input boundary is integral. ``1`` means every index is ``0``, which is the
#: only extent admissible under EVERY vocabulary size — see
#: :func:`input_index_extent` for why there is nothing better to derive.
_UNIVERSAL_INDEX_EXTENT: int = 1

#: The concrete dtype this probe site has always fed, preserved so the
#: shipped TIDMAD behaviour is byte-identical. A site preference is never
#: model semantics (Step-03 §4a.1), so it lives here at the site and is
#: honoured only when the contract admits it.
_PROBE_SITE_DTYPE: str = "int64"


class ProbeConstructionError(ValueError):
    """An explicitly supplied contract cannot be realized as a probe instance.

    The typed fail-closed of design §15.1 **row 3**. It is raised only when a
    contract IS present and a semantic its own declared form requires is
    missing, contradictory or unusable.

    It is emphatically NOT raised for row 1 — a caller that supplies no
    contract at all is the legacy path, and absence alone must never raise.
    Collapsing those two cases would turn every legacy caller into a hard
    failure, which is the mistake §15.1 spells out.
    """


# ---------------------------------------------------------------------------
# Shape realization
# ---------------------------------------------------------------------------


def realize_shape(tensor: TensorContract) -> tuple[int, ...]:
    """Turn a declared tensor contract into one concrete probe shape.

    Rank and axis ORDER come from the contract — ``len(axes)`` is the rank and
    the sequence is the shape order, so nothing here assumes 2-D or 3-D.

    Per axis, in precedence order:

    1. a ``fixed`` extent is a DECLARED fact and is used verbatim;
    2. a ``batch``-role axis is realized at :data:`PROBE_BATCH`;
    3. anything else (symbolic or dynamic) is realized at
       :data:`PROBE_SYMBOLIC_EXTENT`.

    ``fixed`` first is what keeps the two kinds apart: a class alphabet of
    256 is a declared extent that the probe must honour, while ``T`` is a
    name for "as long as the input", which the probe may satisfy at any
    length.

    Under the shipped TIDMAD contract this returns ``(1, 256, 64)`` for the
    output and ``(1, 64)`` for the input — byte-identical to the literals it
    replaces.
    """
    extents: list[int] = []
    for axis in tensor.axes:
        if axis.dimension.fixed is not None:
            extents.append(axis.dimension.fixed)
        elif axis.role is AxisRole.BATCH:
            extents.append(PROBE_BATCH)
        else:
            extents.append(PROBE_SYMBOLIC_EXTENT)
    return tuple(extents)


def declared_output_tensor(
    contract: ModelIOContract,
    declared_output_type: str,
) -> TensorContract:
    """The output tensor a candidate declaring ``declared_output_type`` emits.

    **Why the plugin's own declaration still selects the form.** The shipped
    behaviour judges a model against the contract IT declares, not against
    classification by default — the V21 PR-A2 correction, which parent §2.2
    records as a Stage-A precedent to preserve. A candidate may legitimately
    declare ``regressor`` under a categorical task contract; three plugins in
    the live corpus do exactly that, and they pass today. Deriving the form
    from the task contract instead would start rejecting them, which is a
    verdict change under TIDMAD and therefore a Stage-A parity break.

    So: the DECLARATION selects the form, and the CONTRACT supplies every
    fact inside it.

    ==========================  ===================  ==========================
    contract semantic           declared form        output tensor
    ==========================  ===================  ==========================
    categorical                 ``classifier``       the declared output
    categorical                 ``regressor``        the same, class axis dropped
    continuous                  ``regressor``        the declared output
    continuous                  ``classifier``       **ProbeConstructionError**
    ==========================  ===================  ==========================

    The last row is design §15.1 row 3 in the concrete: the candidate claims
    a class alphabet that its task never declared, so there is no cardinality
    to derive and guessing one would validate it against a shape nobody
    asked for.

    **Returning a tensor rather than a shape is deliberate.** Two consumers
    need this same rule in two renderings — the validator wants a concrete
    probe shape, the implementor wants the prose comment it writes into every
    generated plugin. Deriving both from one ``TensorContract`` is what stops
    a candidate from documenting one contract and being validated against
    another.

    Raises:
        ProbeConstructionError: the declared form needs a class axis the
            contract does not carry.
    """
    output = contract.output
    has_class_axis = output.axis_with_role(AxisRole.CLASS) is not None

    if declared_output_type == "classifier":
        if not has_class_axis or contract.class_cardinality is None:
            raise ProbeConstructionError(
                "the candidate declares PLUGIN_OUTPUT_TYPE='classifier', but the "
                f"task's Model-I/O contract declares a {contract.output_semantic.value} "
                "output carrying no class-alphabet axis, so there is no class "
                f"cardinality to build a probe from (declared output shape: "
                f"{output.render_shape()}). Refusing to guess one — a fabricated "
                "alphabet would validate the candidate against a shape the task "
                "never declared."
            )
        return output

    # `regressor`, or any other value the caller has already accepted as
    # legal: the continuous form of this task's output — the declared tensor
    # with the class axis dropped, if the task declares one.
    if not has_class_axis:
        return output
    return TensorContract(
        axes=tuple(a for a in output.axes if a.role is not AxisRole.CLASS),
        dtype=output.dtype,
    )


def expected_output_shape(
    contract: ModelIOContract,
    declared_output_type: str,
) -> tuple[int, ...]:
    """The concrete probe shape for :func:`declared_output_tensor`."""
    return realize_shape(declared_output_tensor(contract, declared_output_type))


# ---------------------------------------------------------------------------
# Input construction
# ---------------------------------------------------------------------------


def input_index_extent(contract: ModelIOContract) -> int:
    """The exclusive upper bound for integer probe indices.

    When the contract declares a class alphabet, the probe draws indices from
    it. That is the shipped behaviour — today's ``randint(0, 256, ...)`` uses
    the OUTPUT class count as the input index range — and the Dataset
    Profile's ``ValueEncoding.num_classes`` is cross-validated against the
    same cardinality (Step-03 §4b), so the two are one fact, not two.

    It is also load-bearing rather than cosmetic: under a contract declaring
    16 classes a candidate will embed a 16-symbol vocabulary, and feeding it
    an index of 200 would crash the probe for a reason that has nothing to do
    with the candidate.

    **When no alphabet is declared** — a continuous-output contract with an
    integral input — the contract carries no value-range fact at all, and no
    axis role can express one (roles describe extents, not value domains). So
    the probe falls back to :data:`_UNIVERSAL_INDEX_EXTENT`, i.e. index ``0``
    only: the single choice admissible under every vocabulary size. This is a
    deliberate recipe, recorded as a limitation rather than papered over — the
    probe still proves shape and gradient flow, but it does not exercise
    index-dependent behaviour for such a task.
    """
    cardinality = contract.class_cardinality
    if cardinality is None:
        return _UNIVERSAL_INDEX_EXTENT
    return cardinality


def build_model_input(contract: ModelIOContract) -> torch.Tensor:
    """Construct one probe input satisfying the contract's input declaration.

    Shape, rank and axis order come from :func:`realize_shape`; the concrete
    dtype is resolved through the EXISTING Step-03 authority
    (``execute_tools.model_input_dtype.resolve_model_input_dtype``) rather
    than a second mapping, with this site's historical ``int64`` preference
    honoured whenever the contract admits it — which is what keeps the
    shipped TIDMAD probe byte-identical.

    Raises:
        ProbeConstructionError: no concrete dtype is both admissible and
            supported by the runtime, so there is nothing correct to feed.
    """
    import torch

    from execute_tools.model_input_dtype import (
        UnsupportedModelInputDtypeError,
        resolve_model_input_dtype,
    )

    shape = realize_shape(contract.input)
    try:
        dtype = resolve_model_input_dtype(contract.input.dtype, site_preference=_PROBE_SITE_DTYPE)
    except UnsupportedModelInputDtypeError as exc:
        raise ProbeConstructionError(
            f"cannot build a probe input for this contract: {exc}"
        ) from exc

    if dtype.is_floating_point:
        return torch.randn(shape, dtype=dtype)
    return torch.randint(0, input_index_extent(contract), shape, dtype=dtype)


#: Batch and length for the LOSS probe. Distinct from the model probe's
#: extents and deliberately left so: they are two independent validation
#: conveniences, and unifying them would imply a relationship neither has.
#: These are the shipped values, so a classifier loss sees exactly the pair
#: it has always seen.
LOSS_PROBE_BATCH: int = 2
LOSS_PROBE_LENGTH: int = 100


def build_loss_probe_pair(
    contract: ModelIOContract | None,
) -> tuple[torch.Tensor, torch.Tensor, str]:
    """Construct the ``(inputs, targets)`` pair a custom loss is probed with.

    **This is the capability, not a literal sweep** (design §4). The shipped
    probe builds a classifier-shaped pair unconditionally, so a
    declared-regressor custom loss — which expects ``[B, T]`` float inputs
    and ``[B, T]`` float targets — cannot pass under any circumstance. It is
    rejected for a *shape accident*, never for a reason about the loss.

    ============  =========================================  ==================
    semantic      ``inputs``                                 ``targets``
    ============  =========================================  ==================
    categorical   ``[B, C, T]`` float, ``C`` from cardinality ``[B, T]`` int64 in [0, C)
    continuous    ``[B, T]`` float                            ``[B, T]`` float
    ============  =========================================  ==================

    What this function does NOT decide is whether the loss is *legal* for the
    semantic. That question belongs to the Step-03 loss authority and is
    deliberately not duplicated here — design §4 and parent §5 both forbid a
    second ``LossContract``. This builds an instance; something else rules on
    legality.

    ``contract is None`` is the legacy path and yields the classifier pair,
    i.e. exactly today's tensors.

    Returns:
        ``(inputs, targets, description)`` where ``description`` names the
        shapes actually built, so a failure message can state what the loss
        was offered instead of a stale literal.

    Raises:
        ProbeConstructionError: a categorical contract that declares no class
            cardinality — §15.1 row 3.
    """
    import torch

    semantic = loss_probe_semantic(contract)
    batch, length = LOSS_PROBE_BATCH, LOSS_PROBE_LENGTH

    if semantic is OutputSemantic.CONTINUOUS:
        inputs = torch.randn(batch, length, requires_grad=True)
        targets = torch.randn(batch, length)
        return (
            inputs,
            targets,
            f"inputs=[{batch}, {length}] float32 and targets=[{batch}, {length}] float32",
        )

    # Categorical. A contract that declares this semantic without a
    # cardinality cannot say how wide the logit axis is.
    if contract is None:
        classes = _LEGACY_LOSS_PROBE_CLASSES
    elif contract.class_cardinality is None:
        raise ProbeConstructionError(
            "the task declares a categorical output but carries no class-alphabet "
            "extent, so the loss probe cannot size its logit axis. Refusing to "
            "guess — a fabricated width would reject or accept the loss for a "
            "reason that has nothing to do with the loss."
        )
    else:
        classes = contract.class_cardinality

    inputs = torch.randn(batch, classes, length, requires_grad=True)
    targets = torch.randint(0, classes, (batch, length), dtype=torch.int64)
    return (
        inputs,
        targets,
        f"inputs=[{batch}, {classes}, {length}] float32 and targets=[{batch}, {length}] int64",
    )


#: Logit width for the legacy loss probe — used only when no contract is
#: supplied at all (§15.1 row 1), so a prose-only caller sees today's tensors.
_LEGACY_LOSS_PROBE_CLASSES: int = 256


def loss_probe_semantic(contract: ModelIOContract | None) -> OutputSemantic:
    """Which loss-probe recipe applies — design §4.

    The declared output semantic selects how the ``(inputs, targets)`` pair
    is SHAPED. It does not decide whether the loss is legal: that question
    belongs to the Step-03 loss authority and is deliberately not duplicated
    here (design §4, parent §5 "no second LossContract").

    ``None`` — the legacy prose-only path — answers ``CATEGORICAL``, which is
    the classifier-shaped pair the probe has always built.
    """
    if contract is None:
        return OutputSemantic.CATEGORICAL
    return contract.output_semantic
