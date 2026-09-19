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
here as fallbacks. A candidate probe uses its validated temporal length
when declared; a fixed task extent remains authoritative. A symbolic
alignment is not a promise that every candidate accepts the fallback length.

**One recipe module, two consumers.** The validator's in-process shape probe
and the implementor's self-check + loss probe all build instances of the
same declaration. Two copies of these rules would be two authorities, and
the way that fails is silent: the implementor emits a candidate its own
generated test accepts and the validator then rejects, or vice versa.

That is not hypothetical. C12-P / F-12e-G1 stopped the implementor inventing
a ``segmentation_size`` default into the plugin it generates, which made a
config class with a REQUIRED field a legitimate candidate state for the first
time. The implementor taught its own self-check to construct such a class;
``ml_code_validator_agent`` still called ``PLUGIN_CONFIG_CLASS()`` and
rejected the candidate at check 6 — exactly the silent divergence above.
:func:`probe_config_kwargs` is the ONE answer to "what must a probe pass to
construct this config class", and BOTH nodes ask it. Copying it back into
either node re-creates the divergence.

This module deliberately does not import ``torch`` at module scope — the
implementor keeps torch off its import-time path, and this module is
imported by it.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from agent.schemas.model_io_contract import AxisRole, ModelIOContract, TensorContract
from ml_models.models_format_sandbox import OutputSemantic

if TYPE_CHECKING:  # pragma: no cover - typing only
    import torch

__all__ = [
    "LOSS_PROBE_BATCH",
    "LOSS_PROBE_LENGTH",
    "PROBE_BATCH",
    "PROBE_REQUIRED_FIELD_VALUES",
    "PROBE_SYMBOLIC_EXTENT",
    "ProbeConstructionError",
    "build_loss_probe_pair",
    "build_model_input",
    "candidate_probe_extent",
    "declared_output_tensor",
    "expected_output_shape",
    "input_index_extent",
    "loss_probe_semantic",
    "output_without_class_axis",
    "probe_config_kwargs",
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
#: fallback when neither the contract nor candidate states a concrete length.
#: Symbolic alignment alone does not make this fallback legal for a model
#: with a declared workload length; candidate_probe_extent supplies that length.
PROBE_SYMBOLIC_EXTENT: int = 64

#: Index extent used when the contract declares NO class alphabet but the
#: input boundary is integral. ``1`` means every index is ``0``, which is the
#: only extent admissible under EVERY vocabulary size — see
#: :func:`input_index_extent` for why there is nothing better to derive.
_UNIVERSAL_INDEX_EXTENT: int = 1

# ---------------------------------------------------------------------------
# The config-construction recipe — C12-P / F-12e-G1
# ---------------------------------------------------------------------------

#: The value a probe SUPPLIES for a framework-template config field the
#: candidate's own class declares as REQUIRED. One entry, and it is the extent
#: this module already realizes for a symbolic axis, so a probe's tensor and a
#: probe's config state the same length by construction.
#:
#: This is emphatically NOT a default. It is never written into a declaration,
#: never persisted, never priced and never read back: it is passed by keyword
#: into a throwaway in-process instance and dies with it. The generated class
#: still declares the field REQUIRED, so ``resolve_model_field`` and the
#: tuner's ``_resolve_declared_segmentation_size`` still see NOTHING declared
#: and the task's own named refusal stays reachable. Turning this into a
#: ``Field(default=...)`` anywhere is the defect F-12e-G1 removed.
PROBE_REQUIRED_FIELD_VALUES: Mapping[str, int] = MappingProxyType(
    {"segmentation_size": PROBE_SYMBOLIC_EXTENT}
)


def probe_config_kwargs(
    config_cls: Any,
    contract: ModelIOContract | None = None,
) -> dict[str, int]:
    """Kwargs a PROBE must pass to construct *config_cls*.

    The ONE answer to "how do I build one minimal config instance in order to
    test a candidate" — the question this module's second paragraph declares
    it owns. ``ml_model_implementor``'s self-check and
    ``ml_code_validator_agent``'s check-6 instantiation both ask it, and
    neither may re-implement it (see the module docstring: two copies fail
    silently, as they did before this function existed).

    **The invariant being corrected.** A generated config class may
    legitimately declare required fields, so *"``PLUGIN_CONFIG_CLASS()`` must
    succeed with zero arguments"* is not a valid generic validator invariant.
    What IS valid is "a probe states the values it needs".

    Empty — i.e. ``PLUGIN_CONFIG_CLASS()`` byte-for-byte, which is every
    candidate shipped before C12-P — unless the class declares one of
    :data:`PROBE_REQUIRED_FIELD_VALUES`' fields with NO default. A field the
    class does not declare, or declares with a default of its own, is never
    supplied and never overridden: the candidate's own declaration always
    wins.

    Args:
        config_cls: the candidate's ``PLUGIN_CONFIG_CLASS`` — any Pydantic
            model class. A non-model object (no ``model_fields``) yields ``{}``,
            so a malformed plugin still fails at ITS OWN construction with its
            own error rather than here.

    With an explicit fixed temporal contract, a required segmentation field
    receives that fixed extent instead of the fallback. Declared defaults are
    never rewritten; candidate_probe_extent diagnoses any conflict.

    Returns:
        The keyword arguments to splat into ``config_cls(...)``.
    """
    fields = getattr(config_cls, "model_fields", None) or {}
    supplied: dict[str, int] = {}
    for name, value in PROBE_REQUIRED_FIELD_VALUES.items():
        declared = fields.get(name)
        if declared is not None and declared.is_required():
            fixed = _fixed_temporal_extent(contract)
            supplied[name] = fixed if fixed is not None else value
    return supplied


class ProbeConstructionError(ValueError):
    """An explicitly supplied contract cannot be realized as a probe instance.

    The typed fail-closed of design §15.1 **row 3**. It is raised only when a
    contract IS present and a semantic its own declared form requires is
    missing, contradictory or unusable.

    It is emphatically NOT raised for row 1 — a caller that supplies no
    contract at all is the legacy path, and absence alone must never raise.
    Collapsing those two cases would turn every legacy caller into a hard
    failure, which is the mistake §15.1 spells out.

    **Step 05b widened the "unusable" case to the caller's side of the
    realization**, keeping one typed error rather than adding a second: a
    non-positive supplied extent, or one scalar offered for two independent
    symbolic alignments, makes the requested instance just as unrealizable as
    a missing class cardinality does. Both are reachable only when the caller
    passes an explicit extent; omitting them is still the legacy path and
    still never raises.
    """


def _fixed_temporal_extent(contract: ModelIOContract | None) -> int | None:
    """Read a unique declared temporal length; never infer one from a task name."""
    if contract is None:
        return None
    axes = [axis for axis in contract.input.axes if axis.role is AxisRole.TEMPORAL]
    if len(axes) > 1:
        raise ProbeConstructionError("Probe requires an unambiguous temporal axis")
    return axes[0].dimension.fixed if axes else None


def candidate_probe_extent(config: Any, contract: ModelIOContract | None) -> int | None:
    """Bind a temporal smoke input to the validated candidate configuration.

    A symbolic alignment does not promise that a model supports every length.
    Preserve non-temporal contracts' geometry. For temporal candidates, use
    their instantiated length, including required-field probe values, rather
    than running a differently sized input through the model. Fixed contract
    extents outrank defaults; disagreement is a probe contract error, not an
    instruction to redesign the candidate for a smaller synthetic input.
    """
    if contract is not None and not any(
        axis.role is AxisRole.TEMPORAL for axis in contract.input.axes
    ):
        return None
    fixed = _fixed_temporal_extent(contract)
    configured = getattr(config, "segmentation_size", None)
    if configured is not None:
        if isinstance(configured, bool) or not isinstance(configured, int) or configured <= 0:
            raise ProbeConstructionError(
                f"Candidate probe segmentation_size must be a positive integer, got {configured!r}"
            )
        if fixed is not None and fixed != configured:
            raise ProbeConstructionError(
                f"Probe contract conflict: input temporal extent={fixed}, "
                f"candidate segmentation_size={configured}; align configuration and "
                "contract before testing model code"
            )
    return fixed if fixed is not None else configured


# ---------------------------------------------------------------------------
# Shape realization
# ---------------------------------------------------------------------------


def realize_shape(
    tensor: TensorContract,
    *,
    batch: int | None = None,
    symbolic: int | None = None,
) -> tuple[int, ...]:
    """Turn a declared tensor contract into one concrete probe shape.

    Rank and axis ORDER come from the contract — ``len(axes)`` is the rank and
    the sequence is the shape order, so nothing here assumes 2-D or 3-D.

    Per axis, in precedence order:

    1. a ``fixed`` extent is a DECLARED fact and is used verbatim;
    2. a ``batch``-role axis is realized at ``batch``, defaulting to
       :data:`PROBE_BATCH`;
    3. anything else (symbolic or dynamic) is realized at ``symbolic``,
       defaulting to :data:`PROBE_SYMBOLIC_EXTENT`.

    ``fixed`` first is what keeps the two kinds apart: a class alphabet of
    256 is a declared extent that the probe must honour, while ``T`` is a
    name for "as long as the input", which the probe may satisfy at any
    length. **A ``fixed`` extent still wins over both keyword arguments** —
    they are recipe conveniences, and a declared fact outranks a recipe. That
    is the one case where the two rules meet, and it is why a caller asking
    for ``symbolic=T`` on the shipped TIDMAD output still gets ``256`` on the
    class axis.

    **Both arguments are ``None``-sensitive by contract, not by accident**
    (Step-05b §0.2). The override is written against ``None``, never against
    falsiness: ``0`` is a caller error, and a ``batch or PROBE_BATCH`` idiom
    would let it resolve silently to the validation-probe default and realize
    a tensor nobody asked for. Under a capacity probe that is a memory
    forecast for the wrong shape.

    ==================  =========================================
    argument value      extent used
    ==================  =========================================
    omitted / ``None``  the existing Step-04 recipe constant
    positive ``int``    the supplied runtime extent
    ``0`` or negative   :class:`ProbeConstructionError` — never a fallback
    ==================  =========================================

    Args:
        tensor: the declared tensor contract to realize.
        batch: runtime extent for a ``batch``-role axis. Step-04's two node
            consumers omit it and get :data:`PROBE_BATCH`; Step-05b's
            capacity probe supplies the candidate's real batch size.
        symbolic: runtime extent for every symbolic or dynamic axis. Step-04
            omits it and gets :data:`PROBE_SYMBOLIC_EXTENT`; Step-05b
            supplies the candidate's real segmentation size.

    Returns:
        One concrete shape, in the contract's own axis order.

    Raises:
        ProbeConstructionError: a supplied extent is not positive, or
            ``symbolic`` is supplied for a tensor declaring more than one
            DISTINCT non-batch symbolic name — one scalar cannot say what
            two independent alignments should each be, and guessing would
            realize (and price) a shape the contract never declared.

    With both arguments omitted this returns ``(1, 256, 64)`` for the shipped
    TIDMAD output and ``(1, 64)`` for its input — byte-identical to the
    literals it replaces, and to every realization before Step 05b.
    """
    batch_extent = PROBE_BATCH if batch is None else _positive_extent(batch, "batch")
    symbolic_extent = (
        PROBE_SYMBOLIC_EXTENT if symbolic is None else _positive_extent(symbolic, "symbolic")
    )
    if symbolic is not None:
        _reject_ambiguous_symbolic_extent(tensor)

    extents: list[int] = []
    for axis in tensor.axes:
        if axis.dimension.fixed is not None:
            extents.append(axis.dimension.fixed)
        elif axis.role is AxisRole.BATCH:
            extents.append(batch_extent)
        else:
            extents.append(symbolic_extent)
    return tuple(extents)


def _positive_extent(value: int, name: str) -> int:
    """A caller-supplied extent, or a typed refusal — never a fallback."""
    if value <= 0:
        raise ProbeConstructionError(
            f"realize_shape received {name}={value!r}, which is not a positive "
            "extent. Refusing to substitute the Step-04 probe default: a probe "
            "silently realized at a size the caller did not ask for describes a "
            "different tensor than the one under test."
        )
    return value


def _reject_ambiguous_symbolic_extent(tensor: TensorContract) -> None:
    """Refuse one scalar extent for two independent symbolic alignments.

    A symbolic dimension NAMES an alignment (§4e): ``T`` on the input and
    ``T`` on the output are the same extent. Two DISTINCT non-batch names are
    therefore two independent questions, and answering both with one number
    is a guess — the caller would receive a shape the contract never
    declared, and a capacity forecast priced against it.

    Not representable rather than not implemented: per-axis extents would be
    a shape language, which belongs to whoever owns the contract schema, not
    to a Step-04 recipe module (Step-05b §15).

    Reachable only on the explicit-extent path. A caller that omits
    ``symbolic`` keeps the pre-05b realization for any contract whatsoever.
    """
    names = {
        axis.dimension.symbolic
        for axis in tensor.axes
        if axis.dimension.fixed is None
        and axis.role is not AxisRole.BATCH
        and axis.dimension.symbolic is not None
    }
    if len(names) > 1:
        raise ProbeConstructionError(
            f"cannot realize this tensor at one supplied symbolic extent: it "
            f"declares {len(names)} distinct non-batch symbolic dimensions "
            f"({', '.join(sorted(names))}). One number cannot say what each "
            "independent alignment should be, and guessing would realize a "
            f"shape the contract never declared (declared: {tensor.render_shape()})."
        )


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
    return output_without_class_axis(contract)


def output_without_class_axis(contract: ModelIOContract) -> TensorContract:
    """The contract's output tensor with any class-role axis dropped.

    Extracted from :func:`declared_output_tensor`'s ``regressor`` branch
    (F-12d-24) because a second, independent consumer needs the identical
    transformation: a classification LOSS's class-INDEX target is one
    integer per remaining (non-class) position, regardless of what any
    candidate declares itself to be — the target's shape is a fact about
    the LOSS, not about the candidate, so it must not go through
    ``declared_output_type`` selection at all.
    """
    output = contract.output
    if output.axis_with_role(AxisRole.CLASS) is None:
        return output
    return TensorContract(
        axes=tuple(a for a in output.axes if a.role is not AxisRole.CLASS),
        dtype=output.dtype,
    )


def expected_output_shape(
    contract: ModelIOContract,
    declared_output_type: str,
    *,
    symbolic: int | None = None,
) -> tuple[int, ...]:
    """The concrete probe shape for :func:`declared_output_tensor`."""
    return realize_shape(declared_output_tensor(contract, declared_output_type), symbolic=symbolic)


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


def build_model_input(
    contract: ModelIOContract,
    *,
    batch: int | None = None,
    symbolic: int | None = None,
) -> torch.Tensor:
    """Construct one probe input satisfying the contract's input declaration.

    Shape, rank and axis order come from :func:`realize_shape`; the concrete
    dtype is resolved through the EXISTING Step-03 contract-bound authority
    (``execute_tools.model_input_dtype.resolve_contract_input_dtype``), so
    implementor and validator probe the same representation as training and
    inference. For the shipped TIDMAD declaration that representation is
    ``int64``.

    Args:
        contract: the declared Model-I/O contract to realize a probe for.
        batch: forwarded to :func:`realize_shape`. Step-04's two node
            consumers omit it and get :data:`PROBE_BATCH`; Step-05b's
            capacity probe supplies the candidate's real batch size — this
            parameter exists FOR that caller (see ``realize_shape``'s own
            docstring), and F-12d-24 is this promise finally kept: the
            wiring existed here and was never reached from
            ``evaluate_vram_skill``.
        symbolic: forwarded to :func:`realize_shape`. Step-04 omits it and
            gets :data:`PROBE_SYMBOLIC_EXTENT`; Step-05b supplies the
            candidate's real segmentation size.

    Raises:
        ProbeConstructionError: no concrete dtype is both admissible and
            supported by the runtime, so there is nothing correct to feed.
    """
    import torch

    from execute_tools.model_input_dtype import (
        UnsupportedModelInputDtypeError,
        resolve_contract_input_dtype,
    )

    shape = realize_shape(contract.input, batch=batch, symbolic=symbolic)
    try:
        dtype = resolve_contract_input_dtype(contract.input.dtype)
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
