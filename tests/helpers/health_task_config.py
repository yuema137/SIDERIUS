"""Compose the shipped TIDMAD Health roster with a substituted declaration.

Step 08b C5 moved TIDMAD's roster, thresholds, peek set and value scale out
of ``configs/health_checks.yaml`` and into ``configs/task_health/tidmad.yaml``.
Tests that used to express "the task declares THIS peek set" by binding a
``DatasetProfile`` and re-reading the framework config now express it by
composing against a task config that declares it — the same claim, made
where the declaration actually lives.

Shared rather than duplicated because more than one Step-02c module asks the
same question, and two copies of a composition helper is exactly how two
tests start disagreeing about what "declared" means.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import yaml

from execute_tools.health_checks._composition import LEGACY_DEFAULT_TASK_HEALTH_CONFIG
from execute_tools.health_checks.config import HealthChecksConfig, load_composed_health_config


def compose_with_declared_peek_files(peek_files: list[int]) -> HealthChecksConfig:
    """The shipped roster, composed with ``health_peek_files`` substituted.

    Everything else — gate ids, checks, dispositions, thresholds — comes from
    the real TIDMAD task config, so a test asserting on the result is
    asserting about production's roster rather than a hand-built stand-in.

    Args:
        peek_files: the peek set the task is to declare.

    Returns:
        The composed ``HealthChecksConfig``, as a run would evaluate it.
    """
    document: dict[str, Any] = yaml.safe_load(Path(LEGACY_DEFAULT_TASK_HEALTH_CONFIG).read_text())
    document["health_peek_files"] = list(peek_files)

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        task_config = root / "task_health.yaml"
        task_config.write_text(yaml.safe_dump(document, sort_keys=False))
        framework = root / "framework.yaml"
        # Policy-only, like the shipped file: composition refuses a run in
        # which both the framework config and the task declare a roster.
        framework.write_text(yaml.safe_dump({"health_gates": []}))
        config, _task, _plugins = load_composed_health_config(str(framework), str(task_config))
    return config


def resolved_peek_files(peek_files: list[int]) -> dict[str, Any]:
    """gate id → the ``peek_file_indices`` that gate's check receives."""
    return {
        gate.id: check.config.get("peek_file_indices")
        for gate in compose_with_declared_peek_files(peek_files).health_gates
        for check in gate.checks
    }


def write_composed_config(peek_files: list[int], directory: str | Path) -> str:
    """Write the composed roster to a loadable YAML and return its path.

    For tests that drive a REAL ``evaluate_gate`` and therefore need a
    config_path rather than an object. The written file carries gates, so
    loading it composes nothing further — it is already the resolved
    document, exactly like a materialized effective config.
    """
    config = compose_with_declared_peek_files(peek_files)
    path = Path(directory) / "composed_health_checks.yaml"
    path.write_text(yaml.safe_dump(config.model_dump(mode="json"), sort_keys=True))
    return str(path)
