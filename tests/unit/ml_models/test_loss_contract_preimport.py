"""A composed expected contract must be checked before plugin import."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent.schemas.custom_loss_contract import (
    EqualShapeApplicability,
    build_custom_loss_contract_snapshot,
)
from agent.schemas.model_io_contract import Dimension, TensorAxis, TensorContract
from ml_models.models_format_sandbox import DtypeAdmissibility


@pytest.fixture(autouse=True)
def _restore_loss_registries():
    from ml_models.loss_models_sandbox import (
        LOSS_CONFIG_REGISTRY,
        LOSS_CONTRACT_REGISTRY,
        LOSS_REGISTRY,
    )
    from ml_models.loss_plugin_loader import (
        LOSS_REDUCTION_REGISTRY,
        LOSS_TARGET_DTYPE_REGISTRY,
    )

    registries = (
        LOSS_REGISTRY,
        LOSS_CONFIG_REGISTRY,
        LOSS_CONTRACT_REGISTRY,
        LOSS_REDUCTION_REGISTRY,
        LOSS_TARGET_DTYPE_REGISTRY,
    )
    saved = tuple(dict(registry) for registry in registries)
    yield
    for registry, original in zip(registries, saved, strict=True):
        registry.clear()
        registry.update(original)


def _snapshot(extent: int):
    tensor = TensorContract(
        axes=(
            TensorAxis(dimension=Dimension(symbolic="B")),
            TensorAxis(dimension=Dimension(fixed=extent)),
        ),
        dtype=DtypeAdmissibility(admissible=("float32",)),
    )
    return build_custom_loss_contract_snapshot(
        tensor,
        tensor,
        EqualShapeApplicability(dtype=DtypeAdmissibility(admissible=("float32",)), rank=2),
    )


def _plugin_source(snapshot, marker: Path) -> str:
    return f"""\
from pathlib import Path
Path({str(marker)!r}).write_text("imported")
import torch.nn as nn
from pydantic import BaseModel
PLUGIN_CAPABILITY_CONTRACT = {snapshot.model_dump(mode="json")!r}
PLUGIN_LOSS_TYPE = "transport_loss"
class Config(BaseModel):
    pass
class Loss(nn.Module):
    def __init__(self, config): super().__init__()
    def forward(self, inputs, targets): return inputs.mean()
PLUGIN_LOSS_CONFIG_CLASS = Config
PLUGIN_LOSS_CLASS = Loss
"""


def test_mismatch_and_missing_literal_refuse_before_import(tmp_path):
    from ml_models.loss_plugin_loader import load_loss_plugin_from_path

    marker = tmp_path / "imported"
    plugin = tmp_path / "loss.py"
    plugin.write_text(_plugin_source(_snapshot(1), marker))
    with pytest.raises(ValueError, match="does not match"):
        load_loss_plugin_from_path(str(plugin), _snapshot(2))
    assert not marker.exists()

    plugin.write_text(
        _plugin_source(_snapshot(1), marker).replace("PLUGIN_CAPABILITY_CONTRACT", "OTHER")
    )
    with pytest.raises(ValueError, match="missing required"):
        load_loss_plugin_from_path(str(plugin), _snapshot(1))
    assert not marker.exists()


def test_captured_contract_and_import_use_the_same_frozen_source(tmp_path):
    from core.local_code import CodePackageDeclaration, bind_code_package, capture_package
    from ml_models.loss_plugin_loader import load_loss_plugin_from_path

    plugin = tmp_path / "loss.py"
    captured_marker = tmp_path / "captured_imported"
    live_marker = tmp_path / "live_imported"
    captured_snapshot = _snapshot(1)
    plugin.write_text(_plugin_source(captured_snapshot, captured_marker))
    package = capture_package(CodePackageDeclaration(root=".", files=("loss.py",)), tmp_path)
    live_snapshot = _snapshot(2)
    plugin.write_text(_plugin_source(live_snapshot, live_marker))

    with bind_code_package(package):
        with pytest.raises(ValueError, match="does not match"):
            load_loss_plugin_from_path(str(plugin), live_snapshot)
        assert not captured_marker.exists()
        assert not live_marker.exists()
        loaded = load_loss_plugin_from_path(str(plugin), captured_snapshot)

    assert loaded is not None
    assert loaded["contract_snapshot"] == captured_snapshot
    assert captured_marker.exists()
    assert not live_marker.exists()


def test_compatible_and_uncomposed_legacy_paths_remain_loadable(tmp_path):
    from ml_models.loss_plugin_loader import load_loss_plugin_from_path

    marker = tmp_path / "imported"
    plugin = tmp_path / "loss.py"
    snapshot = _snapshot(1)
    plugin.write_text(_plugin_source(snapshot, marker))
    assert load_loss_plugin_from_path(str(plugin), snapshot)["contract_snapshot"] == snapshot
    assert marker.exists()

    marker.unlink()
    legacy = tmp_path / "legacy.py"
    legacy.write_text(
        _plugin_source(snapshot, marker).replace(
            f"PLUGIN_CAPABILITY_CONTRACT = {snapshot.model_dump(mode='json')!r}\n", ""
        )
    )
    assert load_loss_plugin_from_path(str(legacy)) is not None
    assert marker.exists()


def test_generated_template_owns_the_static_contract_literal():
    from ml_models.loss_plugin_loader import parse_loss_contract_snapshot_literal
    from nodes.ml_model_implementor.ml_model_implementor import _assemble_loss_plugin

    snapshot = _snapshot(1)
    source = _assemble_loss_plugin(
        "transport_loss",
        "transport",
        {"init_body": "pass", "forward_body": "return inputs.mean()"},
        snapshot,
    )
    assert parse_loss_contract_snapshot_literal(source) == snapshot


def test_compatible_registration_restores_snapshot_in_memory(tmp_path):
    from ml_models.loss_models_sandbox import (
        LOSS_CONTRACT_REGISTRY,
        register_loss_in_memory,
    )

    snapshot = _snapshot(1)
    plugin = tmp_path / "loss.py"
    plugin.write_text(_plugin_source(snapshot, tmp_path / "imported"))
    LOSS_CONTRACT_REGISTRY.clear()
    assert register_loss_in_memory(str(plugin), snapshot) == "transport_loss"
    assert LOSS_CONTRACT_REGISTRY["transport_loss"] == snapshot


def test_preload_skips_an_unrelated_contract_without_importing_it(tmp_path, monkeypatch):
    from ml_models import loss_plugin_loader
    from ml_models.loss_models_sandbox import (
        LOSS_CONTRACT_REGISTRY,
        LOSS_REGISTRY,
        preload_global_losses,
    )

    marker = tmp_path / "imported"
    library = tmp_path / "library"
    losses = library / "losses"
    losses.mkdir(parents=True)
    (losses / "unrelated.py").write_text(_plugin_source(_snapshot(1), marker))
    monkeypatch.setenv("SIDERIUS_GENERATED_LIBRARY_DIR", str(library))
    monkeypatch.setattr(loss_plugin_loader, "LOSSES_DIR", str(tmp_path / "legacy"))
    LOSS_REGISTRY.clear()
    LOSS_CONTRACT_REGISTRY.clear()
    assert preload_global_losses(_snapshot(2)) == []
    assert not marker.exists()
    assert "transport_loss" not in LOSS_REGISTRY


def test_fresh_process_preload_restores_a_compatible_snapshot(tmp_path):
    snapshot = _snapshot(1)
    marker = tmp_path / "fresh_process_imported"
    library = tmp_path / "library"
    losses = library / "losses"
    losses.mkdir(parents=True)
    (losses / "transport_loss.py").write_text(_plugin_source(snapshot, marker))
    serialized = json.dumps(snapshot.model_dump(mode="json"))
    code = f"""
import json
from core.capability_registry import CapabilityContractSnapshot
from ml_models.loss_models_sandbox import LOSS_CONTRACT_REGISTRY, preload_global_losses
snapshot = CapabilityContractSnapshot.model_validate(json.loads({serialized!r}))
assert preload_global_losses(snapshot) == ["transport_loss"]
assert LOSS_CONTRACT_REGISTRY["transport_loss"] == snapshot
"""
    env = os.environ.copy()
    env["SIDERIUS_GENERATED_LIBRARY_DIR"] = str(library)
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(tmp_path),
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert marker.exists()


def test_locked_objective_mismatch_refuses_before_module_side_effect(tmp_path):
    from workflows.task_composition import TaskCompositionError, _compose_objective

    marker = tmp_path / "objective_imported"
    plugin = tmp_path / "objective.py"
    plugin.write_text(_plugin_source(_snapshot(1), marker))
    raw = {"objective": {"implementation": {"file": str(plugin), "symbol": "PLUGIN_LOSS_TYPE"}}}
    with pytest.raises(TaskCompositionError, match="before plugin import: snapshot mismatch"):
        _compose_objective(raw, str(tmp_path), _snapshot(2))
    assert not marker.exists()
