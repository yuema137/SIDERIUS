"""Declared fixed-workload fixtures align configuration without changing model defaults."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
import torch
from pydantic import BaseModel

from agent.schemas.model_io_contract import ModelIOContract
from agent.schemas.model_probe import ModelProbeSetupError
from agent.skills.model_io_probe_skill import ProbeConstructionError
from agent.skills.task_model_probe import task_model_probe_cases
from agent.skills.task_model_probe_contract import resolve_probe_declaration


class Candidate(BaseModel):
    records: int = 137
    nodes: int = 11
    width: int = 7


def contract():
    from agent.schemas.model_io_contract import Dimension, TensorAxis, TensorContract
    from ml_models.models_format_sandbox import DtypeAdmissibility

    axes = (
        TensorAxis(role="batch", dimension=Dimension(fixed=1)),
        TensorAxis(dimension=Dimension(symbolic="R")),
        TensorAxis(dimension=Dimension(fixed=3)),
    )
    return ModelIOContract(
        input=TensorContract(axes=axes, dtype=DtypeAdmissibility(admissible=("float32",))),
        output=TensorContract(axes=axes, dtype=DtypeAdmissibility(admissible=("float32",))),
    )


def task(**changes):
    declaration = dict(
        description="A complete synthetic graph matching candidate geometry.",
        symbolic_extent_config_field="records",
        config_fields=("nodes",),
        max_input_elements=2000,
    )
    declaration.update(changes)
    return SimpleNamespace(model_validation_contract=declaration)


def test_declared_fixture_receives_actual_config_and_aligned_output(monkeypatch):
    seen = []
    candidate = Candidate()
    before = candidate.model_dump()

    @contextmanager
    def resolver(*_):
        def provider(request):
            seen.append(request)
            return torch.zeros(request.input_shape)

        yield provider, None, (1,), task()

    monkeypatch.setattr("agent.skills.task_model_probe._resolved_provider", resolver)
    cases = task_model_probe_cases(None, contract(), "denoiser", candidate_config=candidate)
    assert cases[0].input.shape == (1, 137, 3)
    assert seen[0].candidate_config == {"nodes": 11}
    assert candidate.model_dump() == before


def test_cap_rejected_before_provider_allocation(monkeypatch):
    @contextmanager
    def resolver(*_):
        def provider(_):
            pytest.fail("allocation must not happen")

        yield provider, None, (1,), task(max_input_elements=10)

    monkeypatch.setattr("agent.skills.task_model_probe._resolved_provider", resolver)
    with pytest.raises(ModelProbeSetupError, match="max_input_elements"):
        task_model_probe_cases(None, contract(), "denoiser", candidate_config=Candidate())


def test_no_declaration_keeps_legacy_extent_without_requiring_config():
    assert resolve_probe_declaration(object(), contract(), None, symbolic=41) == (None, 41, {})


def test_missing_config_binding_fails_clearly():
    with pytest.raises(ProbeConstructionError, match="missing"):
        resolve_probe_declaration(
            task(symbolic_extent_config_field="absent"), contract(), Candidate()
        )


def test_output_only_symbol_does_not_block_input_extent_binding():
    declared = contract().model_dump()
    declared["output"]["axes"][1]["dimension"]["symbolic"] = "Q"
    _, extent, _ = resolve_probe_declaration(
        task(), ModelIOContract.model_validate(declared), Candidate()
    )
    assert extent == 137


def test_multiple_input_symbols_do_not_silently_share_extent():
    declared = contract().model_dump()
    declared["input"]["axes"][2]["dimension"] = {"symbolic": "Q"}
    with pytest.raises(ModelProbeSetupError, match="exactly one"):
        resolve_probe_declaration(task(), ModelIOContract.model_validate(declared), Candidate())


def test_temporal_extent_conflict_does_not_override_candidate():
    with pytest.raises(ProbeConstructionError, match="conflicts"):
        resolve_probe_declaration(task(), contract(), Candidate(), symbolic=99)


@pytest.mark.parametrize("value", [True, 0, -1, 3.5, "137", float("inf")])
def test_invalid_candidate_extent_is_repairable(value):
    # The candidate's own permissive schema can admit an unusable extent.
    class PermissiveCandidate(BaseModel):
        records: object
        nodes: int = 11

    with pytest.raises(ProbeConstructionError):
        resolve_probe_declaration(task(), contract(), PermissiveCandidate(records=value))


def test_fixed_axes_are_not_replaced_by_bound_extent():
    declared = contract().model_dump()
    for tensor in ("input", "output"):
        declared[tensor]["axes"][1]["dimension"] = {"fixed": 12}
    with pytest.raises(ModelProbeSetupError, match="fixed dimensions"):
        resolve_probe_declaration(task(), ModelIOContract.model_validate(declared), Candidate())


def test_fixed_large_geometry_triggers_bounded_dispatch(monkeypatch):
    from agent.skills.task_model_probe_contract import resolve_task_probe_extent

    declared = contract().model_dump()
    for tensor in ("input", "output"):
        declared[tensor]["axes"][1]["dimension"] = {"fixed": 9000}
    io = ModelIOContract.model_validate(declared)

    @contextmanager
    def resolver(*_):
        yield None, None, (1,), task(symbolic_extent_config_field=None, max_input_elements=30000)

    monkeypatch.setattr("agent.skills.task_model_probe._resolved_provider", resolver)
    assert resolve_task_probe_extent(None, io, Candidate()) == 9000
