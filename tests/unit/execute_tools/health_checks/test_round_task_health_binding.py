"""Regression for composed Health authority at the round boundary."""

from __future__ import annotations

from pathlib import Path

from execute_tools.health_checks import _plugin_binding
from execute_tools.health_checks.config import materialize_effective_config
from execute_tools.health_checks.evaluation import evaluate_and_persist_health_gates
from execute_tools.health_checks.registry import _PROVIDER_REGISTRY, _REGISTRY
from execute_tools.health_checks.schemas import HealthCheckContext
from workflows.task_composition import compose_run_task_bindings

REPO_ROOT = Path(__file__).resolve().parents[4]
PETS_MANIFEST = REPO_ROOT / "tests" / "fixtures" / "step10_p1" / "pets" / "composition.yaml"
PRODUCTION_POLICY = REPO_ROOT / "configs" / "health_checks.yaml"


def test_production_policy_comparison_preserves_the_composed_task_binding(tmp_path):
    """A policy-only reload must not request the legacy plugin roster.

    Materializing the effective config establishes the task-owned plugin set,
    exactly as startup does. Before the repair, the production-policy lookup
    then composed under ``LEGACY_OMITTED`` and the run-scope guard correctly
    refused the conflicting empty plugin set.
    """
    registry = dict(_REGISTRY)
    providers = dict(_PROVIDER_REGISTRY)
    _plugin_binding.reset_run_scope()
    try:
        composition = compose_run_task_bindings(str(PETS_MANIFEST))
        effective_path, _ = materialize_effective_config(
            None,
            None,
            str(tmp_path),
            task_health_binding=composition.task_health_binding,
        )

        evaluate_and_persist_health_gates(
            HealthCheckContext(model_name="candidate", run_name="run", round_index=1),
            config_path=effective_path,
            production_config_path=str(PRODUCTION_POLICY),
            task_health_binding=composition.task_health_binding,
            gate_ids=[],
        )

        assert [plugin.configured_ref for plugin in _plugin_binding.loaded_plugin_set()] == [
            "../plugins/_pets_health_views.py"
        ]
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(registry)
        _PROVIDER_REGISTRY.clear()
        _PROVIDER_REGISTRY.update(providers)
        _plugin_binding.reset_run_scope()
