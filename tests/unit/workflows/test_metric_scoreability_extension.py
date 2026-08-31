"""Metric plugins may own task-specific scoreability declarations."""

from __future__ import annotations

import json

from workflows.task_composition import _compose_metric


def test_metric_plugin_rebinds_its_own_scoreability_contract(tmp_path) -> None:
    """Without the plugin mapping, declaration parsing rejects the custom id."""
    declaration = tmp_path / "metric.json"
    declaration.write_text(
        json.dumps(
            {
                "id": "external_metric",
                "direction": "higher",
                "aggregation": "single_value",
                "references": [],
                "scoreability": {
                    "contract_id": "external_semantic_output",
                    "required_marker": 7,
                },
            }
        ),
        encoding="utf-8",
    )
    plugin = tmp_path / "metric.py"
    plugin.write_text(
        """
from typing import ClassVar

from execute_tools.evaluation_metric import (
    EvaluationMetric,
    ScoreabilityContract,
    ScoreabilityVerdict,
)


class ExternalScoreability(ScoreabilityContract):
    contract_id: str = "external_semantic_output"
    required_marker: int

    def check(self, deliverables):
        return ScoreabilityVerdict(contract_id=self.contract_id, failures=())


class ExternalMetric(EvaluationMetric):
    IMPLEMENTS: ClassVar[tuple[str, ...]] = ("external_metric",)
    SCOREABILITY_CONTRACTS = {
        "external_semantic_output": ExternalScoreability,
    }

    def _compute(self, deliverables, /, **kwargs):
        return 1.0, None, ()
""",
        encoding="utf-8",
    )

    metric, _, plugin_ref = _compose_metric(
        {
            "declaration": declaration.name,
            "implementation": {"file": plugin.name, "symbol": "ExternalMetric"},
        },
        str(tmp_path),
    )

    assert metric.spec.scoreability.contract_id == "external_semantic_output"
    assert metric.spec.scoreability.required_marker == 7
    assert plugin_ref is not None


def test_metric_plugin_overrides_a_legacy_framework_contract_id(tmp_path) -> None:
    """The active task plugin, not a compatibility type, owns execution."""
    declaration = tmp_path / "metric.json"
    declaration.write_text(
        json.dumps(
            {
                "id": "external_metric",
                "direction": "higher",
                "aggregation": "single_value",
                "references": [],
                "scoreability": {"contract_id": "deliverable_presence"},
            }
        ),
        encoding="utf-8",
    )
    plugin = tmp_path / "metric.py"
    plugin.write_text(
        """
from execute_tools.evaluation_metric import (
    EvaluationMetric,
    ScoreabilityContract,
    ScoreabilityVerdict,
)


class TaskPresence(ScoreabilityContract):
    contract_id: str = "deliverable_presence"

    def check(self, deliverables):
        return ScoreabilityVerdict(contract_id=self.contract_id, failures=())


class ExternalMetric(EvaluationMetric):
    SCOREABILITY_CONTRACTS = {"deliverable_presence": TaskPresence}

    def _compute(self, deliverables, /, **kwargs):
        return 1.0, None, ()
""",
        encoding="utf-8",
    )

    metric, _, _ = _compose_metric(
        {
            "declaration": declaration.name,
            "implementation": {"file": plugin.name, "symbol": "ExternalMetric"},
        },
        str(tmp_path),
    )

    assert type(metric.spec.scoreability).__name__ == "TaskPresence"
