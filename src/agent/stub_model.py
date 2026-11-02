"""Data-free pseudo model snippets derived from the run's tensor contract."""

from typing import TypedDict

from agent.schemas.model_io_contract import ModelIOContract


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
