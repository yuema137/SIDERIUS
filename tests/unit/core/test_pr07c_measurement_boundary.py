"""The measurement worker's model boundary, after Step 07 / PR 07c C3.

Two model-NAME branches used to live four dozen lines apart in
``gpu_measurement_worker_main.py``:

    :235   if model_type == "fcnet":  model_class(cfg, loss_type=...)
    :287   batch.float() if model_type == "fcnet" else batch.int()

Q-07c-3 eliminated both. The dtype now comes from ``resolve_input_dtype``, and
the constructor arity from ``construct_registered_model`` — the introspection
promoted out of ``agent/skills/training_skill/estimator.py`` to sit beside the
registry it reads.

The load-bearing claim is dtype precedence for each builtin, with and without
a transported contract. Synthetic declarations cover integer preference,
float-only inputs at multiple ranks, and unsupported dtype refusal. The old
phase parameter never reached the resolver and merely duplicated each call;
execution-phase wiring belongs to the worker integration tests.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import torch

from execute_tools.model_input_dtype import (
    UnsupportedModelInputDtypeError,
    resolve_input_dtype,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

#: The MEASUREMENT site's preference, restated rather than imported: this
#: table IS the parity target, so reading the constant from the module under
#: test would let a changed preference silently redefine what parity means.
SITE_PREFERENCE = "int32"

#: Every builtin's concrete model-boundary dtype at `GOLDEN_CAPTURED_AT`,
#: computed from the branch 07c deleted:
#:     batch.float() if model_type == "fcnet" else batch.int()
#: The old branch was phase-INDEPENDENT, so both phases share a row.
PRE_CHANGE_DTYPE: dict[str, torch.dtype] = {
    "punet": torch.int32,
    "fcnet": torch.float32,
    "transformer": torch.int32,
    "wavenet": torch.int32,
    "rnn": torch.int32,
    "gated_fno": torch.int32,
}


def _contract(dtypes=("int64", "int32"), rank=2):
    """A synthetic model boundary; no installed scientific task is consulted."""
    from agent.schemas.model_io_contract import ModelIOContract

    axes = [{"role": "batch", "dimension": {"symbolic": "B"}}]
    axes.extend({"dimension": {"fixed": 3}} for _ in range(rank - 1))
    return ModelIOContract.model_validate(
        {
            "input": {"axes": axes, "dtype": {"admissible": list(dtypes)}},
            "output": {
                "axes": [
                    {"role": "batch", "dimension": {"symbolic": "B"}},
                    {"role": "class", "dimension": {"fixed": 2}},
                ],
                "dtype": {"admissible": ["float32"]},
            },
        }
    )


@pytest.fixture(scope="module")
def integer_contract():
    return _contract()


class TestTheDtypeMatrixIsUnchanged:
    """Keep the historical builtin precedence matrix with explicit input."""

    @pytest.mark.parametrize("model_type", sorted(PRE_CHANGE_DTYPE))
    @pytest.mark.parametrize("with_contract", [False, True])
    def test_builtin_dtype_precedence(self, model_type, with_contract):
        contract = _contract() if with_contract else None
        assert (
            resolve_input_dtype(model_type, contract, site_preference=SITE_PREFERENCE)
            == PRE_CHANGE_DTYPE[model_type]
        )


class TestDeclaredDtypeResolution:
    @pytest.mark.parametrize("rank", [2, 4, 5])
    def test_float_contract_overrides_integer_preference_at_any_rank(self, rank):
        assert (
            resolve_input_dtype(
                "synthetic_model",
                _contract(("float32",), rank),
                site_preference=SITE_PREFERENCE,
            )
            == torch.float32
        )

    def test_admissible_site_preference_wins_over_declared_order(self):
        assert (
            resolve_input_dtype("synthetic_model", _contract(), site_preference=SITE_PREFERENCE)
            == torch.int32
        )

    def test_unsupported_admissibility_refuses_instead_of_coercing(self):
        with pytest.raises(UnsupportedModelInputDtypeError, match="intersection is empty"):
            resolve_input_dtype(
                "synthetic_model",
                _contract(("bfloat16",)),
                site_preference=SITE_PREFERENCE,
            )


class TestTheConstructorRuleIsOneSharedAuthority:
    """Q-07c-3 required PROMOTION, not an inline copy. A copy would satisfy
    'no name branch in the worker' while leaving two implementations of one
    rule, which is the condition that produced the divergence in the first
    place."""

    def test_the_estimator_delegates_rather_than_reimplementing(self):
        """Source-level, because the defect being excluded is duplication: the
        private helper must make no `inspect.signature` CALL of its own.

        Asserted over CALL nodes rather than over the dumped source — the
        function's docstring says the word "signature" while explaining where
        the introspection went, and a text scan cannot tell an explanation
        from an instruction.
        """
        import ast

        module = ast.parse(
            (REPO_ROOT / "agent" / "skills" / "training_skill" / "estimator.py").read_text(
                encoding="utf-8"
            )
        )
        target = next(
            n
            for n in ast.walk(module)
            if isinstance(n, ast.FunctionDef) and n.name == "_instantiate_for_param_count"
        )
        called = {
            n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", None)
            for n in ast.walk(target)
            if isinstance(n, ast.Call)
        }
        assert "construct_registered_model" in called
        assert "signature" not in called, "the introspection must live in the shared owner only"

    def test_a_constructor_declaring_loss_type_receives_it(self):
        import torch.nn as nn
        from pydantic import BaseModel

        from ml_models.models_sandbox import MODEL_REGISTRY, construct_registered_model

        class _Config(BaseModel):
            width: int = 2

        class _NeedsLossType(nn.Module):
            def __init__(self, cfg: _Config, loss_type: str):
                super().__init__()
                self.seen = loss_type

        MODEL_REGISTRY["pr07c_needs_loss_type"] = _NeedsLossType
        try:
            built = construct_registered_model(
                "pr07c_needs_loss_type", _Config(), loss_type="focal"
            )
            assert built.seen == "focal"
        finally:
            MODEL_REGISTRY.pop("pr07c_needs_loss_type", None)

    def test_a_plugin_shaped_constructor_is_called_with_the_config_alone(self):
        """The generated-plugin contract is `__init__(self, config)`. Passing
        `loss_type` to one would be a TypeError at construction, inside the
        measured setup window."""
        import torch.nn as nn
        from pydantic import BaseModel

        from ml_models.models_sandbox import MODEL_REGISTRY, construct_registered_model

        class _Config(BaseModel):
            width: int = 2

        class _PluginShaped(nn.Module):
            def __init__(self, cfg: _Config):
                super().__init__()
                self.width = cfg.width

        MODEL_REGISTRY["pr07c_plugin_shaped"] = _PluginShaped
        try:
            built = construct_registered_model("pr07c_plugin_shaped", _Config(), loss_type="ce")
            assert built.width == 2
        finally:
            MODEL_REGISTRY.pop("pr07c_plugin_shaped", None)

    def test_fcnet_still_receives_its_loss_type(self):
        """The production case the deleted branch existed for. `fcnet`'s head
        shape depends on the loss, so building it without one measures a
        different model than the trainer runs."""
        import inspect

        from ml_models.models_sandbox import MODEL_REGISTRY

        assert "loss_type" in inspect.signature(MODEL_REGISTRY["fcnet"].__init__).parameters


class TestTheSpecTransportStaysBackwardCompatible:
    def test_a_spec_serialized_before_07c_still_loads(self):
        """Both 07c transports are optional, so a spec captured before either
        existed validates and runs — with `None` meaning Regime A, which is
        exactly today's behaviour rather than a degraded one."""
        from core.runtime_control.gpu_measurement_identity import build_planned_identity
        from core.runtime_control.gpu_measurement_spec import GpuMeasurementSpec
        from core.runtime_control.gpu_requirement import CandidateMeasurementRequest

        spec = GpuMeasurementSpec(
            label="pr07c",
            request=CandidateMeasurementRequest(
                model_type="wavenet",
                planned_identity=build_planned_identity(
                    model_type="wavenet",
                    model_config={},
                    train_config={},
                    inference_batch_size=1,
                ),
                request_id="r",
                device_uuid="GPU-x",
                phase="training",
                deadline_seconds=60.0,
            ),
            result_path="/tmp/r.json",
            journal_path="/tmp/j.ndjson",
            worker_memory_limit_bytes=1024,
        )
        legacy = json.loads(spec.model_dump_json())
        del legacy["dataset_profile"]
        del legacy["model_io_contract"]
        reloaded = GpuMeasurementSpec(**legacy)
        assert reloaded.dataset_profile is None
        assert reloaded.model_io_contract is None

    def test_a_transported_contract_round_trips_unchanged(self, integer_contract):
        """The transport is only worth having if the worker sees the SAME
        declaration the parent bound — a lossy round trip would resolve a
        different dtype without any error."""
        from core.runtime_control.gpu_measurement_identity import build_planned_identity
        from core.runtime_control.gpu_measurement_spec import GpuMeasurementSpec
        from core.runtime_control.gpu_requirement import CandidateMeasurementRequest

        spec = GpuMeasurementSpec(
            label="pr07c",
            request=CandidateMeasurementRequest(
                model_type="wavenet",
                planned_identity=build_planned_identity(
                    model_type="wavenet",
                    model_config={},
                    train_config={},
                    inference_batch_size=1,
                ),
                request_id="r",
                device_uuid="GPU-x",
                phase="training",
                deadline_seconds=60.0,
            ),
            result_path="/tmp/r.json",
            journal_path="/tmp/j.ndjson",
            worker_memory_limit_bytes=1024,
            model_io_contract=integer_contract,
        )
        reloaded = GpuMeasurementSpec(**json.loads(spec.model_dump_json()))
        assert reloaded.model_io_contract == integer_contract
