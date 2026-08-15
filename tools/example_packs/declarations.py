"""Helpers for the pack-OWNED L0/L1 declarations (Pets / DAVIS) — through the REAL schemas.

The contrast packs declare their instance values (roadmap §22.23.1) as
instances of the owning schemas — ``ModelIOContract`` and ``MetricSpec`` —
dumped with ``model_dump(mode="json")``. Nothing here defines a rule: the
schema decides what a contract or a metric MEANS; the pack only supplies
its concrete values.

``metric_spec_from_declared`` exists because ``MetricSpec.scoreability`` is
typed as the abstract ``ScoreabilityContract`` base, so ``MetricSpec(**json)``
cannot rebuild the concrete contract from a plain dict (Step 06 has no
production JSON deserializer for a MetricSpec — the subprocess re-derives
the TIDMAD instance from ``--dataset_profile_json``). The concrete contract
is selected by its declared ``contract_id`` among the schema's own
subclasses; no registry is restated here.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from agent.schemas.model_io_contract import (
    AxisRole,
    Dimension,
    DtypeAdmissibility,
    ModelIOContract,
    TensorAxis,
    TensorContract,
)
from execute_tools.evaluation_metric import (
    MetricSpec,
    ScoreabilityContract,
)


def _all_subclasses(cls: type[ScoreabilityContract]) -> list[type[ScoreabilityContract]]:
    found: list[type[ScoreabilityContract]] = []
    for sub in cls.__subclasses__():
        found.append(sub)
        found.extend(_all_subclasses(sub))
    return found


def scoreability_contract_from_declared(payload: dict[str, Any]) -> ScoreabilityContract:
    """Rebuild the concrete contract whose declared default ``contract_id`` matches.

    Raises:
        ValueError: when no concrete ``ScoreabilityContract`` subclass declares
            the ``contract_id`` (the pack references a contract the framework
            does not have — an honest failure, never a fallback).
    """
    contract_id = payload.get("contract_id")
    for cls in _all_subclasses(ScoreabilityContract):
        default = cls.model_fields["contract_id"].default
        if default == contract_id:
            return cls(**payload)
    raise ValueError(f"no ScoreabilityContract subclass declares contract_id={contract_id!r}")


def metric_spec_from_declared(payload: dict[str, Any]) -> MetricSpec:
    """``MetricSpec`` from a pack's declared JSON (see module docstring)."""
    fields = dict(payload)
    fields["scoreability"] = scoreability_contract_from_declared(fields["scoreability"])
    return MetricSpec(**fields)


def batch_axis(symbol: str = "B") -> TensorAxis:
    return TensorAxis(dimension=Dimension(symbolic=symbol), role=AxisRole.BATCH)


def fixed_axis(extent: int, role: AxisRole | None = None) -> TensorAxis:
    return TensorAxis(dimension=Dimension(fixed=extent), role=role)


def tensor_contract(axes: Sequence[TensorAxis], dtypes: Sequence[str]) -> TensorContract:
    return TensorContract(axes=tuple(axes), dtype=DtypeAdmissibility(admissible=tuple(dtypes)))


def model_io_contract(inp: TensorContract, out: TensorContract) -> ModelIOContract:
    return ModelIOContract(input=inp, output=out)
