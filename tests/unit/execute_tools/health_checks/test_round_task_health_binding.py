"""Regression for composed Health authority at the round boundary."""

from __future__ import annotations

import textwrap
from pathlib import Path

import yaml

from execute_tools.health_checks import _plugin_binding
from execute_tools.health_checks.config import (
    default_health_policy_path,
    materialize_effective_config,
)
from execute_tools.health_checks.evaluation import evaluate_and_persist_health_gates
from execute_tools.health_checks.registry import _PROVIDER_REGISTRY, _REGISTRY
from execute_tools.health_checks.schemas import HealthCheckContext

REPO_ROOT = Path(__file__).resolve().parents[4]
PRODUCTION_POLICY = Path(default_health_policy_path())


def _external_health_binding(root: Path) -> str:
    """Build the smallest out-of-tree Health family this boundary needs."""
    (root / "health_plugin.py").write_text(
        textwrap.dedent(
            """
            from typing import ClassVar

            from execute_tools.health_checks import register
            from execute_tools.health_checks.schemas import (
                CheckInputDeclaration,
                HealthCheckResult,
            )


            class ExternalRoundCheck:
                name: ClassVar[str] = "external_round_check"
                declaration: ClassVar[CheckInputDeclaration] = CheckInputDeclaration(
                    consumes_view="synthetic.round_payload",
                )

                def run(self, ctx, config=None):
                    return HealthCheckResult(
                        check_name=self.name,
                        passed=False,
                        reason="synthetic round-boundary fixture",
                    )


            register(ExternalRoundCheck())
            """
        ),
        encoding="utf-8",
    )
    config = root / "task_health.yaml"
    config.write_text(
        textwrap.dedent(
            """
            facts:
              encoding_family: synthetic_round_payload
            plugins:
              - kind: file
                ref: health_plugin.py
            roster:
              - gate_id: external_round_blocking
                check: external_round_check
                disposition: blocking
                reason: Synthetic round-boundary fixture.
            """
        ),
        encoding="utf-8",
    )
    return str(config)


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
        task_health_binding = _external_health_binding(tmp_path)
        policy = yaml.safe_load(PRODUCTION_POLICY.read_text())
        policy["health_policy"]["blocking"]["on_fail"] = "continue"
        observe = tmp_path / "observe.yaml"
        observe.write_text(yaml.safe_dump(policy))
        effective_path, _ = materialize_effective_config(
            str(observe),
            None,
            str(tmp_path),
            task_health_binding=task_health_binding,
        )

        _, persisted, action = evaluate_and_persist_health_gates(
            HealthCheckContext(model_name="candidate", run_name="run", round_index=1),
            config_path=effective_path,
            production_config_path=str(PRODUCTION_POLICY),
            task_health_binding=task_health_binding,
        )

        assert action.value == "continue"
        assert len(persisted) == 1
        assert persisted[0].check_passed is False
        assert persisted[0].would_invalidate_under_production_policy is True

        assert [plugin.configured_ref for plugin in _plugin_binding.loaded_plugin_set()] == [
            "health_plugin.py"
        ]
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(registry)
        _PROVIDER_REGISTRY.clear()
        _PROVIDER_REGISTRY.update(providers)
        _plugin_binding.reset_run_scope()
