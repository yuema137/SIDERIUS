"""Rejected same-basename plugins must not replace registered source identity."""

import inspect
import sys
from pathlib import Path

import pytest

from ml_models import (
    loss_models_sandbox,
    loss_plugin_loader,
    models_format_sandbox,
    models_sandbox,
    plugin_loader,
)


@pytest.fixture(params=["model", "loss"])
def family(request, monkeypatch):
    """Isolate registration side effects while exercising public entry points."""
    for owner, names in (
        (models_sandbox, ["MODEL_REGISTRY"]),
        (models_format_sandbox, ["PLUGIN_CONFIG_REGISTRY"]),
        (plugin_loader, ["PLUGIN_OUTPUT_TYPE_REGISTRY", "_PLUGIN_MODEL_ORIGINS"]),
        (loss_models_sandbox, ["LOSS_REGISTRY", "LOSS_CONFIG_REGISTRY", "LOSS_CONTRACT_REGISTRY"]),
        (loss_plugin_loader, ["LOSS_TARGET_DTYPE_REGISTRY", "LOSS_REDUCTION_REGISTRY"]),
    ):
        for name in names:
            monkeypatch.setattr(owner, name, getattr(owner, name).copy())
    kind = request.param
    name = ("siderius_plugin_" if kind == "model" else "siderius_loss_plugin_") + "rollback_witness"
    monkeypatch.delitem(sys.modules, name, raising=False)
    yield kind, name
    sys.modules.pop(name, None)


def _source(kind, marker):
    common = f"""from pydantic import BaseModel
from torch import nn
class Config(BaseModel):
    pass
class Implementation(nn.Module):
    marker = {marker!r}
"""
    if kind == "model":
        return (
            common
            + """PLUGIN_MODEL_TYPE = "rollback_witness"
PLUGIN_CONFIG_CLASS = Config
PLUGIN_MODEL_CLASS = Implementation
PLUGIN_OUTPUT_TYPE = "regressor"
"""
        )
    return (
        common
        + """PLUGIN_LOSS_TYPE = "rollback_witness"
PLUGIN_LOSS_CONFIG_CLASS = Config
PLUGIN_LOSS_CLASS = Implementation
PLUGIN_LOSS_TARGET_DTYPE = "float"
"""
    )


def _write(tmp_path, directory, source):
    path = tmp_path / directory / "rollback_witness.py"
    path.parent.mkdir()
    path.write_text(source)
    return path


def _register(kind, path):
    function = (
        plugin_loader.register_model_in_memory
        if kind == "model"
        else loss_models_sandbox.register_loss_in_memory
    )
    return function(str(path))


def _registry(kind):
    return models_sandbox.MODEL_REGISTRY if kind == "model" else loss_models_sandbox.LOSS_REGISTRY


@pytest.mark.parametrize("prior", [False, True])
@pytest.mark.parametrize("failure", ["import", "missing", "metadata", "interrupt"])
def test_rejected_public_registration_restores_module_and_source(family, tmp_path, prior, failure):
    kind, module_name = family
    old_module = old_class = None
    if prior:
        original = _write(tmp_path, "accepted", _source(kind, "accepted source"))
        assert _register(kind, original) == "rollback_witness"
        old_module = sys.modules[module_name]
        old_class = _registry(kind)["rollback_witness"]
    source = _source(kind, "rejected source")
    if failure == "import":
        source += '\nraise RuntimeError("broken import")\n'
    elif failure == "interrupt":
        source += '\nraise KeyboardInterrupt("interrupted import")\n'
    elif failure == "missing":
        source += (
            "\ndel " + ("PLUGIN_MODEL_CLASS" if kind == "model" else "PLUGIN_LOSS_CLASS") + "\n"
        )
    else:
        source += (
            "\n"
            + ("PLUGIN_OUTPUT_TYPE" if kind == "model" else "PLUGIN_LOSS_TARGET_DTYPE")
            + ' = "invalid"\n'
        )
    rejected = _write(tmp_path, "rejected", source)
    if failure == "interrupt":
        with pytest.raises(KeyboardInterrupt):
            _register(kind, rejected)
    elif failure == "metadata" and kind == "loss":
        with pytest.raises(ValueError):
            _register(kind, rejected)
    else:
        assert _register(kind, rejected) is None
    if prior:
        assert sys.modules[module_name] is old_module
        assert _registry(kind)["rollback_witness"] is old_class
        assert inspect.getfile(old_class) == str(original)
        assert "accepted source" in inspect.getsource(old_class)
        assert "rejected source" not in inspect.getsource(old_class)
    else:
        assert module_name not in sys.modules


def test_successful_replacement_publishes_new_module_and_source(family, tmp_path):
    kind, module_name = family
    old = _write(tmp_path, "first", _source(kind, "old source"))
    new = _write(tmp_path, "second", _source(kind, "new source"))
    assert _register(kind, old) == "rollback_witness"
    previous = sys.modules[module_name]
    assert _register(kind, new) == "rollback_witness"
    assert sys.modules[module_name] is not previous
    cls = _registry(kind)["rollback_witness"]
    assert inspect.getfile(cls) == str(new)
    assert "new source" in inspect.getsource(cls)


@pytest.mark.parametrize("family", ["model"], indirect=True)
def test_inspection_restores_module_even_after_valid_candidate(tmp_path, family):
    kind, module_name = family
    assert kind == "model"
    old = _write(tmp_path, "first", _source(kind, "registered source"))
    candidate = _write(tmp_path, "second", _source(kind, "inspection source"))
    assert _register(kind, old) == "rollback_witness"
    previous = sys.modules[module_name]
    with plugin_loader.inspect_model_plugin(str(candidate)) as metadata:
        assert metadata is not None
        assert "inspection source" in inspect.getsource(metadata["model_class"])
    assert sys.modules[module_name] is previous
    assert "registered source" in inspect.getsource(_registry(kind)["rollback_witness"])


def test_rejection_restores_existing_none_module_binding(tmp_path, family):
    kind, module_name = family
    sys.modules[module_name] = None
    candidate = _write(tmp_path, "candidate", "raise RuntimeError('rejected')\n")
    assert _register(kind, candidate) is None
    assert module_name in sys.modules
    assert sys.modules[module_name] is None
