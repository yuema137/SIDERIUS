"""Current declared source survives staging, stale index locators and preload."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agent.schemas.implementor import LossProvenance
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from core.capability_registry import CapabilityMetadata, CapabilityRegistry
from core.local_code import (
    CodePackageDeclaration,
    LocalCodeError,
    bind_code_package,
    capture_package,
)
from ml_models.plugin_binding import bind_run_model_plugins
from ml_models.plugin_loader import preload_global_models, register_model_in_memory
from nodes.ml_model_implementor.ml_model_implementor import MLModelImplementor
from tests.helpers.local_code_model import MODEL_TYPE, make_package
from tests.unit.agent.ml_model_implementor.test_model_branch_b import _branch_b_input
from tests.unit.core.test_local_code_transport import bind_workspace
from tests.unit.core.test_resume import _plugin_src, isolated_registries
from workflows import model_exploration as workflow

pytestmark = pytest.mark.usefixtures("isolated_registries")


def test_declared_registration_keeps_source_but_still_propagates_loss_and_checks_construction(
    tmp_path, monkeypatch
):
    proposal_name = MODEL_TYPE
    package, binding = make_package(tmp_path / "task")
    bind_workspace(tmp_path, monkeypatch)
    loss = tmp_path / "loss.py"
    loss.write_text("# generated loss source\n")
    description = tmp_path / "description.md"
    description.write_text("A tiny model description.")
    implementation = SimpleNamespace(
        model_type=MODEL_TYPE,
        model_file_path=str(package.root / "model.py"),
        description_file_path=str(description),
        loss_provenance=LossProvenance(
            loss_name="source_test_loss",
            action="generated",
            source_iteration="iter_001",
            loss_file_path=str(loss),
            dummy_tensor_validated=True,
        ),
    )
    construction, losses = [], []
    monkeypatch.setattr(
        workflow, "_validate_construction_memory", lambda **kw: construction.append(kw)
    )
    monkeypatch.setattr(
        "ml_models.loss_models_sandbox.register_loss_in_memory", lambda path: losses.append(path)
    )
    destinations = [tmp_path / "workspace/plugins/iter_001", tmp_path / "tune/plugins/iter_001"]
    loss_destination = tmp_path / "workspace/losses/iter_001"
    with bind_code_package(package), bind_run_model_plugins(binding):
        workflow._register_plugin(
            implementation, proposal_name, [str(p) for p in destinations], str(loss_destination)
        )
        workflow._promote_model_to_global(implementation)
    assert len(construction) == 1
    assert construction[0]["model_class"].__module__.endswith("._helper")
    assert losses == [str(loss_destination / "source_test_loss.py")]
    assert (loss_destination / "source_test_loss.py").read_bytes() == loss.read_bytes()
    assert all(not (dest / f"{proposal_name}.py").exists() for dest in destinations)
    assert all(
        (dest / proposal_name / "description.md").read_bytes() == description.read_bytes()
        for dest in destinations
    )
    assert not (tmp_path / "workspace/plugin_source_sentinel").exists()
    assert not (tmp_path / "workspace/generated_library/models" / f"{MODEL_TYPE}.py").exists()


def test_existing_index_row_uses_relocated_declaration_without_rewrite_or_new_offer(
    tmp_path, monkeypatch
):
    package, binding = make_package(tmp_path / "relocated-task")
    bind_workspace(tmp_path, monkeypatch)
    registry = CapabilityRegistry(index_path=str(tmp_path / "index.json"))
    old_path = str(tmp_path / "absent-old-checkout/model.py")
    registry.register(
        CapabilityMetadata(
            name=MODEL_TYPE,
            capability_type="model",
            file_path=old_path,
            created_at="2026-09-13T00:00:00+00:00",
            source_iteration="iter_001",
            description="Existing declared model",
            mathematical_definition="y=x*w",
        )
    )
    before = (tmp_path / "index.json").read_bytes()
    agent = MLModelImplementor.__new__(MLModelImplementor)
    agent.bridge, agent._registry = MagicMock(), registry
    storage = StorageConfig(
        backend="local", local=LocalStorageConfig(workspace=str(tmp_path / "ws"), run_name="reuse")
    )
    inp = _branch_b_input(tmp_path, storage, model_name=MODEL_TYPE)
    inp.model_name = "new_proposal_label"
    construction = []
    monkeypatch.setattr(
        workflow, "_validate_construction_memory", lambda **kw: construction.append(kw)
    )
    destination = tmp_path / "staged"
    with bind_code_package(package), bind_run_model_plugins(binding):
        assert workflow._cleanup_stale_registry_entries(registry) == (0, [])
        result = agent.run(inp)
        workflow._register_plugin(result, inp.model_name, [str(destination)])
    assert result.model_type == MODEL_TYPE
    assert len(construction) == 1
    assert not (destination / "new_proposal_label.py").exists()
    assert not (tmp_path / "workspace/plugin_source_sentinel").exists()
    assert result.model_file_path == str(package.root / "model.py")
    assert result.test_file_path == ""
    assert (tmp_path / "index.json").read_bytes() == before
    agent.bridge.generate.assert_not_called()
    agent.bridge.generate_text.assert_not_called()


def test_preload_refuses_same_name_before_registry_overwrite_but_allows_other_names(
    tmp_path, monkeypatch
):
    from core.generated_library import generated_models_dir
    from ml_models.models_sandbox import MODEL_REGISTRY

    package, binding = make_package(tmp_path / "task")
    bind_workspace(tmp_path, monkeypatch)
    directory = Path(generated_models_dir())
    directory.mkdir(parents=True)
    unrelated = directory / "other.py"
    unrelated.write_text(_plugin_src("resume_test_arch_b"))
    original = MODEL_REGISTRY[MODEL_TYPE]
    with bind_code_package(package), bind_run_model_plugins(binding):
        assert register_model_in_memory(str(unrelated)) == "resume_test_arch_b"
        # Same qualname is deliberate: the old warning-only check misses it.
        (directory / f"{MODEL_TYPE}.py").write_text(_plugin_src(MODEL_TYPE))
        with pytest.raises(LocalCodeError, match="captured member identity"):
            preload_global_models()
    assert MODEL_REGISTRY[MODEL_TYPE] is original


def test_model_acquisition_does_not_erase_explicitly_wrapped_package_refusal(tmp_path):
    source = tmp_path / "wrapped.py"
    source.write_text(
        "from core.local_code import LocalCodeError\n"
        "try:\n from .undeclared import value\n"
        "except LocalCodeError as exc:\n raise ValueError('plugin wrapper') from exc\n"
    )
    package = capture_package(CodePackageDeclaration(root=".", files=("wrapped.py",)), tmp_path)
    with (
        bind_code_package(package),
        pytest.raises(LocalCodeError, match="undeclared relative import"),
    ):
        register_model_in_memory(str(source))


def test_invalid_captured_model_rolls_back_without_legacy_retry(tmp_path):
    import sys

    from ml_models.plugin_loader import _load_plugin

    source = tmp_path / "invalid.py"
    marker = tmp_path / "executed"
    source.write_text(f"from pathlib import Path\nPath({str(marker)!r}).write_text('captured')\n")
    package = capture_package(CodePackageDeclaration(root=".", files=(source.name,)), tmp_path)
    source.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('legacy')\n"
        "raise AssertionError('invalid capture must not retry legacy disk')\n"
    )
    before = set(sys.modules)
    with bind_code_package(package):
        assert _load_plugin(str(source)) is None
    assert marker.read_text() == "captured"
    assert not {name for name in set(sys.modules) - before if name.startswith("_siderius_task_")}
