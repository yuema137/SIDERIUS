"""Actual composition pins helper-defined adapters and preserves omission bytes."""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

from core.local_code import CodePackageDeclaration, bind_code_package, capture_package
from execute_tools.task_data_path import content_identity, registered_task_data_path_ids
from execute_tools.task_registration_scope import run_registration_scope
from tests.unit.core.test_resume import isolated_registries
from workflows.task_composition import (
    TaskCompositionError,
    _load_symbol,
    compose_run_task_bindings,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def isolated_health_plugin_registries() -> Iterator[None]:
    """Restore task-plugin registrations after a composition witness.

    The single-file composition test imports the masked-regression Health
    provider as a real side effect.  Without restoring that process-global
    registry, a later composition of the same pack fails on a duplicate
    provider even though the later test owns an independent run scope.
    """
    from execute_tools.health_checks.registry import _PROVIDER_REGISTRY, _REGISTRY

    checks_before = dict(_REGISTRY)
    providers_before = dict(_PROVIDER_REGISTRY)
    try:
        yield
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(checks_before)
        _PROVIDER_REGISTRY.clear()
        _PROVIDER_REGISTRY.update(providers_before)


def modular_fixture(root: Path) -> Path:
    shutil.copytree(REPO_ROOT / "tests/fixtures/step10_p1/fourth_task", root)
    data = root / "plugins/spectro_data_path.py"
    helper = root / "plugins/helper.py"
    helper.write_text(data.read_text().replace("spectro_segmentation_v0", "local_code_demo_v1"))
    data.write_text("from .helper import SpectroTaskDataPath\n")
    manifest = root / "composition.yaml"
    raw = yaml.safe_load(manifest.read_text())
    raw["task_data_path"]["id"] = "local_code_demo_v1"
    raw["code_package"] = {
        "root": ".",
        "files": [
            "plugins/spectro_data_path.py",
            "plugins/helper.py",
            "plugins/band_coverage_metric.py",
        ],
    }
    manifest.write_text(yaml.safe_dump(raw))
    return manifest


def test_composition_registration_identity_includes_helper_and_excludes_host(tmp_path):
    """An entry-only or runtime-namespace pin fails helper drift or relocation."""
    first = modular_fixture(tmp_path / "first")
    second = tmp_path / "second" / "composition.yaml"
    shutil.copytree(first.parent, second.parent)
    values = []
    for manifest in (first, second):
        with run_registration_scope():
            composition = compose_run_task_bindings(str(manifest))
            values.append(
                (composition.semantic_fingerprint, content_identity(composition.task_data_path))
            )
            assert (
                composition.provenance.plugins[0].local_code.member
                == "plugins/spectro_data_path.py"
            )
    assert values[0] == values[1]
    helper = first.parent / "plugins/helper.py"
    helper.write_text(helper.read_text() + "\nHELPER_REVISION = 2\n")
    with run_registration_scope():
        changed = compose_run_task_bindings(str(first))
        assert changed.semantic_fingerprint != values[0][0]
        assert content_identity(changed.task_data_path) != values[0][1]


@pytest.mark.parametrize("missing_companion", [False, True])
def test_missing_symbol_rolls_back_import_registration_and_captured_entry_hash(
    tmp_path, missing_companion
):
    """Family symbol checks are inside acquisition; later hashes never reread disk."""
    manifest = modular_fixture(tmp_path / "task")
    helper = manifest.parent / "plugins/helper.py"
    helper.write_text(
        helper.read_text()
        + "\nfrom execute_tools.task_data_path import register_task_data_path\nregister_task_data_path(SpectroTaskDataPath())\n"
    )
    raw = yaml.safe_load(manifest.read_text())
    captured = capture_package(
        CodePackageDeclaration.model_validate(raw["code_package"]), manifest.parent
    )
    entry = manifest.parent / "plugins/spectro_data_path.py"
    original_hash = hashlib.sha256(entry.read_bytes()).hexdigest()
    entry.write_text("raise AssertionError('edited disk must not execute')\n")
    before = registered_task_data_path_ids()
    with run_registration_scope(), bind_code_package(captured):
        with pytest.raises(TaskCompositionError, match="Missing"):
            _load_symbol(
                {
                    "file": str(entry),
                    "symbol": "SpectroTaskDataPath" if missing_companion else "Missing",
                },
                str(manifest.parent),
                "fixture",
                also_require=("Missing",) if missing_companion else (),
            )
        assert registered_task_data_path_ids() == before
        _, ref = _load_symbol(
            {"file": str(entry), "symbol": "SpectroTaskDataPath"}, str(manifest.parent), "fixture"
        )
        assert ref.content_sha256 == original_hash
    assert registered_task_data_path_ids() == before


def test_single_file_composition_and_effective_health_match_base_receipt(
    tmp_path, monkeypatch, isolated_health_plugin_registries
):
    """Independent hashes pin the composed package and explicit probe semantics.

    The receipt was re-recorded when the example declared that segmentation is
    not applicable.  That declaration is identity-bearing because resource
    observations from temporal and fixed-shape probes are not comparable.
    """
    from core.generated_library import bind_generated_library_to_workspace
    from execute_tools.health_checks import _plugin_binding
    from execute_tools.health_checks.config import materialize_effective_config
    from workflows.task_composition import bind_run_task_composition

    env: dict[str, str] = {}
    bind_generated_library_to_workspace(str(tmp_path), environ=env)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    _plugin_binding.reset_run_scope()
    try:
        with run_registration_scope():
            composition = compose_run_task_bindings(
                str(REPO_ROOT / "configs/task_composition/synthetic_masked_regression.yaml")
            )
            assert (
                composition.semantic_fingerprint
                == "a311b8e2b798980099b0d859ff08e879b9302e0bddf788fb6fdd1b7cb72f0815"
            )
            with bind_run_task_composition(composition, physical_data_root=str(tmp_path)):
                materialize_effective_config(
                    None, None, str(tmp_path), task_health_binding=composition.task_health_binding
                )
            data = (tmp_path / "health_checks_effective.yaml").read_bytes()
            assert (
                hashlib.sha256(data).hexdigest()
                == "319654260195abed0b356e5424cd35f685988e53f360fe08bfc6055ab20e56e1"
            )
    finally:
        _plugin_binding.reset_run_scope()


def test_health_resolution_and_effective_reload_preserve_captured_package(tmp_path, monkeypatch):
    """Discovery must filter before disk hashing; persisted markers must not drop helpers."""
    from execute_tools.health_checks import _plugin_binding
    from execute_tools.health_checks._task_health_config import TaskHealthConfig
    from execute_tools.health_checks.config import (
        load_health_gates_config,
        materialize_effective_config,
    )

    (tmp_path / "check.py").write_text("VALUE = 7\n")
    (tmp_path / "helper.py").write_text("VALUE = 8\n")
    (tmp_path / "unlisted.py").write_text("raise AssertionError('not selected')\n")
    captured = capture_package(
        CodePackageDeclaration(root=".", files=("check.py", "helper.py")), tmp_path
    )
    (tmp_path / "check.py").write_text("VALUE = 9\n")

    def forbid_disk_digest(path):
        pytest.fail(f"resolution reread captured/unlisted source: {path}")

    monkeypatch.setattr(_plugin_binding, "_digest", forbid_disk_digest)
    config = TaskHealthConfig.model_validate({"plugins": [{"kind": "directory", "ref": "."}]})
    with bind_code_package(captured):
        plugins = _plugin_binding._resolve(config, str(tmp_path))
    assert [plugin.member for plugin in plugins] == ["check.py", "helper.py"]
    assert plugins[0].content_sha256 == hashlib.sha256(b"VALUE = 7\n").hexdigest()
    effective = tmp_path / "effective.yaml"
    identities = [plugin.canonical_identity() for plugin in plugins]
    effective.write_text(
        yaml.safe_dump(
            {"health_gates": [], "task_health_binding": "explicit", "resolved_plugins": identities}
        )
    )
    loaded = load_health_gates_config(str(effective))
    assert loaded.resolved_plugins[0].local_code.package == captured.identity
    output = tmp_path / "output"
    output.mkdir()
    materialize_effective_config(str(effective), None, str(output))
    assert (
        yaml.safe_load((output / "health_checks_effective.yaml").read_text())["resolved_plugins"]
        == identities
    )


def test_iteration_policy_preflight_has_capture_before_run_activation(tmp_path, monkeypatch):
    """The real main's Health policy reader must not run after capture unwound."""
    import os
    import sys

    from core.local_code import active_package
    from workflows import run_one_iteration as runner

    manifest = modular_fixture(tmp_path / "task")
    for key in ("SIDERIUS_GENERATED_LIBRARY_DIR", "SIDERIUS_CHAIN_WORKSPACE"):
        if key in os.environ:
            monkeypatch.setenv(key, os.environ[key])
        else:
            monkeypatch.delenv(key, raising=False)

    class Observed(BaseException):
        pass

    def policy(**kwargs):
        package = active_package()
        assert package is not None
        assert package.root == manifest.parent
        raise Observed

    monkeypatch.setattr(runner, "validate_formal_launch", policy)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runner",
            "--workspace",
            str(tmp_path / "workspace"),
            "--run_name",
            "local_code",
            "--start_iteration",
            "1",
            "--task_composition",
            str(manifest),
            "--data_dir",
            str(tmp_path),
        ],
    )
    with run_registration_scope(), pytest.raises(Observed):
        runner.main()
    assert active_package() is None


@pytest.mark.usefixtures("isolated_registries")
def test_iteration_restore_sees_existing_package_and_model_scopes(tmp_path, monkeypatch):
    """Actual runner reaches restore before full composition activation, then unwinds."""
    from core import resume
    from core.local_code import active_package
    from ml_models.plugin_binding import active_run_model_plugins
    from tests.unit.ml_models.test_step12_pr12d_dp_plugin_binding import write_plugin
    from tests.unit.sdsc_submission_scripts.test_run_one_iteration import _run_main
    from workflows import run_one_iteration as runner

    manifest = modular_fixture(tmp_path / "task")
    write_plugin(manifest.parent / "models", "resume_scope_net")
    raw = yaml.safe_load(manifest.read_text())
    raw["code_package"]["files"].append("models/resume_scope_net.py")
    raw["model_plugins"] = {"dir": "models", "require": ["resume_scope_net"]}
    manifest.write_text(yaml.safe_dump(raw))
    previous_package, previous_models = active_package(), active_run_model_plugins()

    class Observed(BaseException):
        pass

    def observe_restore(
        workspace, current_iter, seed_paths, expected_invariants=None, dataset_partition_count=None
    ):
        package, models = active_package(), active_run_model_plugins()
        assert package is not None and package.root == manifest.parent
        assert models is not None and models.required_model_types == ("resume_scope_net",)
        assert models.plugins[0].local_code.package == package.identity
        assert dataset_partition_count == 5
        raise Observed

    monkeypatch.setattr(resume, "restore_prior_state", observe_restore)
    # This witness owns the binding edge, not Health preflight/materialization.
    monkeypatch.setattr(runner, "validate_formal_launch", lambda **kwargs: None)
    monkeypatch.setattr(runner, "compute_expected_invariants", lambda *args, **kwargs: None)
    for key in ("SIDERIUS_GENERATED_LIBRARY_DIR", "SIDERIUS_CHAIN_WORKSPACE"):
        monkeypatch.delenv(key, raising=False)
    with run_registration_scope(), pytest.raises(Observed):
        _run_main(
            [
                "--workspace",
                str(tmp_path / "workspace"),
                "--start_iteration",
                "1",
                "--task_composition",
                str(manifest),
                "--data_dir",
                str(tmp_path),
            ]
        )
    assert active_package() is previous_package
    assert active_run_model_plugins() is previous_models
