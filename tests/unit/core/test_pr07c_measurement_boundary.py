"""The measurement worker's model boundary, after Step 07 / PR 07c C3.

Two model-NAME branches used to live four dozen lines apart in
``gpu_measurement_worker_main.py``:

    :235   if model_type == "fcnet":  model_class(cfg, loss_type=...)
    :287   batch.float() if model_type == "fcnet" else batch.int()

Q-07c-3 eliminated both. The dtype now comes from ``resolve_input_dtype``, and
the constructor arity from ``construct_registered_model`` — the introspection
promoted out of ``agent/skills/training_skill/estimator.py`` to sit beside the
registry it reads.

The load-bearing claim is PARITY: the model is handed exactly the tensor it was
handed before, for every builtin, in both phases, with and without a
transported contract. What the authorities buy is breadth, which is why the
persistent tracks' declared contracts are exercised here too — DAVIS is the
discriminating case, RGB float video being the furthest thing from int8 ADC
codes.
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


@pytest.fixture(scope="module")
def tidmad_contract():
    from workflows.task_config import run_bound_model_io_contract

    contract = run_bound_model_io_contract()
    assert contract is not None, "the shipped task must declare a Model-I/O contract"
    return contract


def _declared_contract(track: str):
    from agent.schemas.model_io_contract import ModelIOContract

    path = REPO_ROOT / "examples" / track / "declared" / "model_io_contract.json"
    return ModelIOContract(**json.loads(path.read_text(encoding="utf-8")))


class TestTheDtypeMatrixIsUnchanged:
    """Checkpoint A. A dtype is not an identity component, so a change here
    would not rename a store key — it would silently change the VALUES stored
    under an unchanged one. That is why this is asserted per row."""

    @pytest.mark.parametrize("model_type", sorted(PRE_CHANGE_DTYPE))
    @pytest.mark.parametrize("phase", ["training", "inference"])
    def test_without_a_contract_every_builtin_keeps_its_dtype(self, model_type, phase):
        """Regime A — a spec serialized before the transport, or an ad-hoc
        caller. The model's own declaration answers where it has one; the site
        preference answers otherwise."""
        assert (
            resolve_input_dtype(model_type, None, site_preference=SITE_PREFERENCE)
            == PRE_CHANGE_DTYPE[model_type]
        )

    @pytest.mark.parametrize("model_type", sorted(PRE_CHANGE_DTYPE))
    @pytest.mark.parametrize("phase", ["training", "inference"])
    def test_with_the_tidmad_contract_every_builtin_keeps_its_dtype(
        self, model_type, phase, tidmad_contract
    ):
        """The transported case. TIDMAD declares `('int64', 'int32')`, so the
        site's `int32` preference is admissible and survives — which is the
        whole reason Q-07c-8 fixed the preference at `int32` rather than
        adopting a phase-correct one."""
        assert (
            resolve_input_dtype(model_type, tidmad_contract, site_preference=SITE_PREFERENCE)
            == PRE_CHANGE_DTYPE[model_type]
        )

    def test_fcnet_is_float32_on_both_sides_of_the_transport(self, tidmad_contract):
        """The one builtin that overrides the task contract. Its declaration
        must win with AND without a contract, or the legacy autoencoder arm is
        silently fed integers."""
        assert resolve_input_dtype("fcnet", None, site_preference=SITE_PREFERENCE) == torch.float32
        assert (
            resolve_input_dtype("fcnet", tidmad_contract, site_preference=SITE_PREFERENCE)
            == torch.float32
        )


class TestThePersistentTracksResolveTheirOwnDtype:
    """§2a.2 three-track breadth, at each track's CURRENT maturity.

    No data is read, no model is built, no dataset adapter or `DatasetProfile`
    is invented — those are D14. All this needs is the contract each track has
    already declared, which is the whole point: the dtype authority's input is
    a `ModelIOContract`, and both tracks have one today.
    """

    @pytest.mark.parametrize("track", ["oxford_iiit_pet", "davis_future_prediction"])
    def test_a_declared_contract_resolves_what_it_declares(self, track):
        contract = _declared_contract(track)
        declared = contract.input.dtype.admissible
        resolved = resolve_input_dtype(
            "a_model_with_no_builtin_declaration", contract, site_preference=SITE_PREFERENCE
        )
        assert str(resolved).replace("torch.", "") in declared

    @pytest.mark.parametrize("track", ["oxford_iiit_pet", "davis_future_prediction"])
    def test_it_does_not_resolve_to_tidmads_dtype(self, track, tidmad_contract):
        """The assertion that would catch a hidden TIDMAD assumption. Both
        tracks declare float32 only, so the `int32` site preference is NOT
        admissible and must fall through to the contract's own answer — if the
        site preference leaked through anyway, this is where it shows.
        """
        resolved = resolve_input_dtype(
            "a_model_with_no_builtin_declaration",
            _declared_contract(track),
            site_preference=SITE_PREFERENCE,
        )
        tidmad_resolved = resolve_input_dtype(
            "a_model_with_no_builtin_declaration",
            tidmad_contract,
            site_preference=SITE_PREFERENCE,
        )
        assert resolved == torch.float32
        assert resolved != tidmad_resolved

    def test_davis_is_the_discriminating_shape(self):
        """Recorded because the design names DAVIS the valuable case: RGB
        `[B, C, T, H, W]` float, five axes, nothing like int8 ADC codes. If the
        contract path had a TIDMAD-shaped assumption about rank or encoding,
        loading this declaration is where it would surface."""
        contract = _declared_contract("davis_future_prediction")
        assert len(contract.input.axes) == 5
        assert contract.input.dtype.admissible == ("float32",)


class TestItFailsClosedRatherThanCoercing:
    def test_a_contract_admitting_nothing_runtime_supported_raises(self):
        """Not a silent coercion to something plausible: a wrong dtype at the
        model boundary is invisible to every prompt- and schema-level test and
        surfaces only in real training."""
        from agent.schemas.model_io_contract import ModelIOContract

        payload = json.loads(
            (
                REPO_ROOT / "examples" / "oxford_iiit_pet" / "declared" / "model_io_contract.json"
            ).read_text(encoding="utf-8")
        )
        payload["input"]["dtype"]["admissible"] = ["bfloat16"]
        with pytest.raises(UnsupportedModelInputDtypeError, match="intersection is empty"):
            resolve_input_dtype(
                "a_model_with_no_builtin_declaration",
                ModelIOContract(**payload),
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

    def test_a_transported_contract_round_trips_unchanged(self, tidmad_contract):
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
            model_io_contract=tidmad_contract,
        )
        reloaded = GpuMeasurementSpec(**json.loads(spec.model_dump_json()))
        assert reloaded.model_io_contract == tidmad_contract
