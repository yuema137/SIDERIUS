"""Pin composed deliverable naming at the generic tuner acquisition boundary."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from execute_tools.health_checks import _plugin_binding
from execute_tools.health_checks.registry import _PROVIDER_REGISTRY, _REGISTRY
from tests.helpers.composed_manifest import write_complete_manifest
from tests.helpers.composition_data_root import COMPOSED_TEST_DATA_ROOT
from workflows.task_composition import (
    bind_run_task_composition,
    compose_run_task_bindings,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
TUNER = REPO_ROOT / "nodes" / "ml_hyperparameter_tune_agent" / "ml_hyperparameter_tune_agent.py"
DECLARED_PREFIX = "contract_test_predictions"


@pytest.fixture(autouse=True)
def _isolated_run_scope():
    registry = dict(_REGISTRY)
    providers = dict(_PROVIDER_REGISTRY)
    _plugin_binding.reset_run_scope()
    try:
        yield
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(registry)
        _PROVIDER_REGISTRY.clear()
        _PROVIDER_REGISTRY.update(providers)
        _plugin_binding.reset_run_scope()


def _acquire_as_the_tuner_does():
    from execute_tools.dataset_config import resolve_dataset_profile
    from execute_tools.deliverable_spec import (
        derive_run_deliverable_spec,
        indexed_cleanup_naming,
    )

    return derive_run_deliverable_spec(resolve_dataset_profile()), indexed_cleanup_naming()


def test_declared_naming_reaches_the_tuners_acquisition(tmp_path):
    manifest = write_complete_manifest(tmp_path, deliverable={"prefix": DECLARED_PREFIX})
    composition = compose_run_task_bindings(str(manifest))

    with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
        storage_spec, naming = _acquire_as_the_tuner_does()

    assert storage_spec is None
    assert naming is not None
    assert naming.prefix == DECLARED_PREFIX


def test_the_tuner_has_one_profile_derived_storage_acquisition():
    tree = ast.parse(TUNER.read_text(encoding="utf-8"))
    acquisitions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "derive_run_deliverable_spec"
    ]

    assert len(acquisitions) == 1
    assert [ast.unparse(arg) for arg in acquisitions[0].args] == ["run_profile"]
    assert acquisitions[0].keywords == []
