"""Frozen combined effects catch copy/registration reordering during extraction.

Individual copy/reuse/name/package cases remain with their existing tests. This
oracle alone pins actual dual model/loss effects and the first selected origin.
"""

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

from agent.schemas.implementor import ImplementorOutput, LossProvenance
from ml_models import loss_models_sandbox, loss_plugin_loader, plugin_loader
from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY
from ml_models.models_sandbox import MODEL_REGISTRY
from tests.unit.workflows.test_model_exploration import _REGRESSOR_PLUGIN_SRC
from workflows import plugin_staging as staging

MODEL = "test_regressor_plugin_c6"
LOSS = "native_staging_loss"
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures/native_plugin_staging"
LOSS_SOURCE = """from pydantic import BaseModel
from torch import nn
PLUGIN_LOSS_TYPE = "native_staging_loss"
PLUGIN_LOSS_TARGET_DTYPE = "float"
PLUGIN_LOSS_REDUCTION = "mean"
class NativeLossConfig(BaseModel): pass
class NativeLoss(nn.Module):
    def forward(self, inputs, targets): return ((inputs-targets)**2).mean()
PLUGIN_LOSS_CONFIG_CLASS = NativeLossConfig
PLUGIN_LOSS_CLASS = NativeLoss
"""


@pytest.fixture
def staging_state(tmp_path, monkeypatch):
    """Restore all affected registry maps and prior synthetic module entries."""
    maps = [
        MODEL_REGISTRY,
        PLUGIN_CONFIG_REGISTRY,
        plugin_loader.PLUGIN_OUTPUT_TYPE_REGISTRY,
        plugin_loader._PLUGIN_MODEL_ORIGINS,
        loss_models_sandbox.LOSS_REGISTRY,
        loss_models_sandbox.LOSS_CONFIG_REGISTRY,
        loss_models_sandbox.LOSS_CONTRACT_REGISTRY,
        loss_plugin_loader.LOSS_TARGET_DTYPE_REGISTRY,
        loss_plugin_loader.LOSS_REDUCTION_REGISTRY,
    ]
    snapshots = [dict(mapping) for mapping in maps]
    prefixes = ("siderius_plugin_", "siderius_loss_")
    modules = {key: value for key, value in sys.modules.items() if key.startswith(prefixes)}
    monkeypatch.setenv("SIDERIUS_CHAIN_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("SIDERIUS_GENERATED_LIBRARY_DIR", str(tmp_path / "library"))
    try:
        for mapping in maps:
            mapping.pop(MODEL, None)
            mapping.pop(LOSS, None)
        yield
    finally:
        for mapping, snapshot in zip(maps, snapshots, strict=True):
            mapping.clear()
            mapping.update(snapshot)
        for key in list(sys.modules):
            if key.startswith(prefixes):
                sys.modules.pop(key)
        sys.modules.update(modules)


def make_implementation(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    model, description, loss = source / "model.py", source / "description.md", source / "loss.py"
    model.write_text(_REGRESSOR_PLUGIN_SRC)
    description.write_text("# Native staging model\n")
    loss.write_text(LOSS_SOURCE)
    return ImplementorOutput(
        model_type=MODEL,
        model_file_path=str(model),
        description_file_path=str(description),
        test_file_path=str(source / "test_model.py"),
        config_fields={},
        model_description="Synthetic staging witness",
        mathematical_definition="y=f(x)",
        loss_provenance=LossProvenance(
            loss_name=LOSS,
            action="generated",
            source_iteration="iter_001",
            loss_file_path=str(loss),
            dummy_tensor_validated=True,
        ),
    )


def destinations(tmp_path, kind):
    return [str(tmp_path / scope / kind) for scope in ("tuner", "chain")]


def test_generated_model_loss_effect_oracle(tmp_path, monkeypatch, capsys, staging_state):
    """Frozen trace fails on any changed bytes, ordering, registry origin or warning."""
    implementation = make_implementation(tmp_path)
    events = []
    copy = shutil.copy2
    register_model = staging.register_model_in_memory
    register_loss = loss_models_sandbox.register_loss_in_memory

    def relative(path):
        return str(Path(path).relative_to(tmp_path))

    def observed_copy(source, target, *args, **kwargs):
        result = copy(source, target, *args, **kwargs)
        events.append(["copy", relative(source), relative(target)])
        return result

    def observed_loss(path, snapshot):
        result = register_loss(path, snapshot)
        events.append(["loss_registry", relative(path), result, MODEL in MODEL_REGISTRY])
        return result

    def observed_model(path):
        result = register_model(path)
        events.append(
            ["model_registry", relative(path), result, LOSS in loss_models_sandbox.LOSS_REGISTRY]
        )
        return result

    monkeypatch.setattr(shutil, "copy2", observed_copy)
    monkeypatch.setattr(staging, "register_model_in_memory", observed_model)
    monkeypatch.setattr(loss_models_sandbox, "register_loss_in_memory", observed_loss)
    result = staging.stage_native_plugins(
        implementation, MODEL, destinations(tmp_path, "plugins"), destinations(tmp_path, "losses")
    )
    files = {}
    for scope in ("workspace", "tuner", "chain", "library"):
        for path in sorted((tmp_path / scope).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                files[relative(path)] = {
                    "text": path.read_text(),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }

    def qualified(value):
        return f"{value.__module__}.{value.__qualname__}"

    observed = {
        "return": result,
        "exception": None,
        "events": events,
        "files": files,
        "stdout": capsys.readouterr().out.replace(str(tmp_path), "<ROOT>"),
        "model": {
            "class": qualified(MODEL_REGISTRY[MODEL]),
            "config": qualified(PLUGIN_CONFIG_REGISTRY[MODEL]),
            "output": plugin_loader.PLUGIN_OUTPUT_TYPE_REGISTRY[MODEL],
            "origin": relative(plugin_loader._PLUGIN_MODEL_ORIGINS[MODEL][1]),
        },
        "loss": {
            "class": qualified(loss_models_sandbox.LOSS_REGISTRY[LOSS]),
            "config": qualified(loss_models_sandbox.LOSS_CONFIG_REGISTRY[LOSS]),
            "dtype": loss_plugin_loader.LOSS_TARGET_DTYPE_REGISTRY[LOSS],
            "reduction": loss_plugin_loader.LOSS_REDUCTION_REGISTRY[LOSS],
            "contract": loss_models_sandbox.LOSS_CONTRACT_REGISTRY.get(LOSS),
        },
    }
    assert observed == json.loads((FIXTURES / "generated_dual.json").read_text())


@pytest.mark.parametrize("case", ["missing_model", "empty_models", "empty_losses"])
def test_coupled_partial_effects(tmp_path, staging_state, case):
    """Pins uncoupled early return and asymmetric empty-destination partial effects."""
    implementation = make_implementation(tmp_path)
    models, losses = destinations(tmp_path, "plugins"), destinations(tmp_path, "losses")
    if case == "missing_model":
        Path(implementation.model_file_path).unlink()
    if case == "empty_models":
        models = []
    if case == "empty_losses":
        losses = []
        with pytest.raises(IndexError):
            staging.stage_native_plugins(implementation, MODEL, models, losses)
    else:
        assert staging.stage_native_plugins(implementation, MODEL, models, losses) is None
    assert (MODEL in MODEL_REGISTRY) is False
    assert (LOSS in loss_models_sandbox.LOSS_REGISTRY) is (case == "empty_models")
    assert (tmp_path / "tuner/plugins" / f"{MODEL}.py").exists() is (case == "empty_losses")
    assert (tmp_path / "tuner/losses" / f"{LOSS}.py").exists() is (case == "empty_models")


@pytest.mark.parametrize("failure", ["ordinary_model", "package_model", "loss"])
def test_registration_exception_disposition(tmp_path, monkeypatch, capsys, staging_state, failure):
    """Only ordinary model exceptions warn; package/loss exceptions retain partial copies."""
    from core.local_code import LocalCodeError

    implementation = make_implementation(tmp_path)
    error = (
        LocalCodeError("staging package refusal")
        if failure == "package_model"
        else RuntimeError("staging registrar failure")
    )

    def refuse(*_args):
        raise error

    if failure == "loss":
        monkeypatch.setattr(loss_models_sandbox, "register_loss_in_memory", refuse)
    else:
        monkeypatch.setattr(staging, "register_model_in_memory", refuse)
    if failure == "ordinary_model":
        staging.stage_native_plugins(
            implementation,
            MODEL,
            destinations(tmp_path, "plugins"),
            destinations(tmp_path, "losses"),
        )
        assert (
            "    Warning: could not extend registries: staging registrar failure\n"
            in capsys.readouterr().out
        )
    else:
        with pytest.raises(type(error), match=str(error)) as caught:
            staging.stage_native_plugins(
                implementation,
                MODEL,
                destinations(tmp_path, "plugins"),
                destinations(tmp_path, "losses"),
            )
        assert caught.value is error
        assert "could not extend registries" not in capsys.readouterr().out
    assert (tmp_path / "chain/losses" / f"{LOSS}.py").read_bytes() == Path(
        implementation.loss_provenance.loss_file_path
    ).read_bytes()
    assert MODEL not in MODEL_REGISTRY
    assert (LOSS in loss_models_sandbox.LOSS_REGISTRY) is (failure != "loss")
