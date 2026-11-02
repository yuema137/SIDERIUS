"""Data-free pseudo model snippets and narrative derived from the run's tensor contract."""

from typing import TypedDict

from pydantic import BaseModel, ConfigDict

from agent.schemas.model_io_contract import ModelIOContract
from ml_models.models_format_sandbox import OutputSemantic


class UnsupportedStubShapeError(ValueError):
    """The pseudo model cannot satisfy the declared output contract.

    Raised before plugin execution for an output extent that cannot be
    resolved from the input, or an output dtype set with no floating member.
    """


#: Floating dtypes a differentiable scalar projection can emit. Contract order
#: decides among them; nothing here prefers one over another.
_FLOATING_DTYPES = frozenset({"float16", "bfloat16", "float32", "float64"})


class StubModelCode(TypedDict):
    extra_imports: str
    config_fields_code: str
    config_validators_code: str
    init_body: str
    forward_body: str
    config_fields: dict[str, int]


def _output_extent_expressions(contract: ModelIOContract) -> list[str]:
    """Preserve fixed extents and resolve shared symbols at forward time."""
    symbols = {
        axis.dimension.symbolic: index
        for index, axis in enumerate(contract.input.axes)
        if axis.dimension.symbolic is not None
    }
    extents: list[str] = []
    for index, axis in enumerate(contract.output.axes):
        dimension = axis.dimension
        if dimension.fixed is not None:
            extents.append(str(dimension.fixed))
        elif dimension.symbolic in symbols:
            extents.append(f"x.shape[{symbols[dimension.symbolic]}]")
        else:
            raise UnsupportedStubShapeError(
                f"Pseudo model cannot resolve output axis {index} ({dimension.render()}): "
                "declare a fixed extent or a symbol shared with the input."
            )
    return extents


def _output_dtype(contract: ModelIOContract) -> str:
    """Return the first admissible floating output dtype, or refuse up front."""
    admissible = contract.output.dtype.admissible
    dtype = next((name for name in admissible if name in _FLOATING_DTYPES), None)
    if dtype is None:
        raise UnsupportedStubShapeError(
            f"Pseudo model cannot emit output dtype {list(admissible)!r}: its "
            "differentiable projection needs a floating dtype "
            f"({sorted(_FLOATING_DTYPES)!r})."
        )
    return dtype


def stub_model_code(contract: ModelIOContract | None) -> StubModelCode:
    """Generate a cheap differentiable shape witness, never a scientific model.

    Unbound legacy fixtures retain their sequence plugin. Explicit contracts
    use a scalar projection expanded to the declared output, avoiding any
    assumption that numerical inputs are token indices. The output takes the
    contract's first admissible floating dtype and is materialized contiguous,
    so a downstream ``.view`` in a loss path sees ordinary storage.
    """
    if contract is None:
        init = (
            "self.embedding = nn.Embedding(256, config.hidden_dim)\n"
            "self.head = nn.Linear(config.hidden_dim, 256)"
        )
        forward = "x = self.embedding(x.long())\nx = self.head(x)\nreturn x.transpose(1, 2)"
    else:
        shape = ", ".join(_output_extent_expressions(contract))
        dtype = _output_dtype(contract)
        init = "self.bias = nn.Parameter(torch.zeros(config.hidden_dim))"
        forward = (
            "value = x.float().mean() + self.bias.mean()\n"
            f"return value.to(torch.{dtype}).expand({shape}).contiguous()"
        )
    return {
        "extra_imports": "",
        "config_fields_code": "    hidden_dim: int = Field(default=8, ge=1, le=256)",
        "config_validators_code": "",
        "init_body": init,
        "forward_body": forward,
        "config_fields": {"hidden_dim": 8},
    }


class StubProposalSemantics(BaseModel):
    """Pseudo proposal, implementor and tuner fields derived from one contract."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    output_type: str
    loss_type: str
    model_description: str
    mathematical_definition: str
    motivation: str
    forward_constraint: str
    mechanism: str
    proposer_reasoning: str
    implementor_reasoning: str


#: The unbound legacy fixtures' historical sequence-stub narrative, unchanged.
_LEGACY_SEMANTICS = StubProposalSemantics(
    output_type="classifier",
    loss_type="ce",
    model_description=(
        "Stub architecture: nn.Embedding(256, hidden_dim) followed by "
        "nn.Linear(hidden_dim, 256). Returns [B, 256, T] floats — the "
        "minimum viable plugin that satisfies the chain's forward contract."
    ),
    mathematical_definition=(
        "x in Z^{B x T}; e = Embed(x) in R^{B x T x h}; "
        "y = Linear(e) in R^{B x T x 256}; "
        "out = transpose(y, 1, 2) in R^{B x 256 x T}."
    ),
    motivation=(
        "Stub mode: emits the minimal model that respects the [B, 256, T] "
        "forward contract so downstream stages have a runnable plugin to "
        "consume. Architecture choice is irrelevant under stub training."
    ),
    forward_constraint="Forward contract: [B, T] int -> [B, 256, T] float.",
    mechanism="token embedding to linear head",
    proposer_reasoning=(
        "Stub proposer reasoning: the simplest model that "
        "satisfies the [B, 256, T] forward contract is a token "
        "embedding into a linear head. Stub mode emits this "
        "baseline regardless of the upstream interpretation."
    ),
    implementor_reasoning=(
        "Stub implementor reasoning: implement the proposed stub "
        "architecture as a token embedding into a linear head. "
        "The forward pass transposes the last two dimensions to "
        "produce [B, 256, T]."
    ),
)

#: One legal loss per canonical output semantic, from the framework's own loss
#: families (``ce`` also runs without a temporal axis; ``smooth_l1`` is the sole
#: regression loss). The output semantic itself comes from the task's contract.
_STUB_LOSS = {OutputSemantic.CATEGORICAL: "ce", OutputSemantic.CONTINUOUS: "smooth_l1"}


def _stub_loss(semantic: OutputSemantic) -> str:
    loss = _STUB_LOSS.get(semantic)
    if loss is None:
        raise UnsupportedStubShapeError(
            f"Pseudo model has no loss for output semantic {semantic!r}"
        )
    return loss


def stub_proposal_semantics(contract: ModelIOContract | None) -> StubProposalSemantics:
    """Describe the plugin ``stub_model_code`` emits for ``contract``.

    The output type and loss follow the contract's derived output semantic,
    so continuous tasks receive a regressor with a regression loss and the
    candidate probe sees the geometry the task declared. A contract the stub
    cannot emit raises ``UnsupportedStubShapeError`` here, at proposal time.
    """
    if contract is None:
        return _LEGACY_SEMANTICS
    dtype = _output_dtype(contract)
    semantic = contract.output_semantic
    source = contract.input.render()
    target = f"{contract.output.render_shape()} {dtype}"
    mechanism = "scalar projection expanded to the declared output"
    return StubProposalSemantics(
        output_type=contract.legacy_output_type,
        loss_type=_stub_loss(semantic),
        model_description=(
            f"Stub architecture: the input mean plus a learned bias, cast to {dtype} "
            f"and expanded to the declared {semantic.value} output {target}. A "
            "plumbing witness that satisfies the task's Model-I/O contract, not a "
            "scientific architecture."
        ),
        mathematical_definition=(
            f"x: {source}; b in R^h; v = mean(x) + mean(b); "
            f"out = broadcast(v) to {target}, materialized contiguous."
        ),
        motivation=(
            f"Stub mode: emits the minimal differentiable model that respects the "
            f"{source} -> {target} contract so downstream stages have a runnable "
            "plugin to consume. Architecture choice is irrelevant under stub training."
        ),
        forward_constraint=f"Forward contract: {source} -> {target}.",
        mechanism=mechanism,
        proposer_reasoning=(
            f"Stub proposer reasoning: the simplest model that satisfies the "
            f"{source} -> {target} contract is a {mechanism}. Stub mode emits "
            "this baseline regardless of the upstream interpretation."
        ),
        implementor_reasoning=(
            f"Stub implementor reasoning: implement the proposed stub as a "
            f"{mechanism}, reading shared symbolic extents from the input at "
            f"forward time to produce {target}."
        ),
    )


def bound_stub_contract() -> ModelIOContract | None:
    """The run's bound Model-I/O contract, or ``None`` for unbound fixtures."""
    from workflows.task_config import resolve_bound_task_config, run_bound_model_io_contract

    return run_bound_model_io_contract() if resolve_bound_task_config() is not None else None
