# tests/unit/agent/schemas/test_step10_p4_c3_worst_stat_derivation.py
"""Step 10 / P4 — C3': the worst-statistic derivation (Q-P4-2).

``_WORST_STAT_BY_METRIC`` mapped three TIDMAD metric NAMES to which
``aggregate_statistics`` entry is the worst case. That is the same information
the declared comparison operator already carries, hard-coded a second time —
and while it stood, a task-owned check with a correctly persisted threshold
row still produced NO fingerprint, because its metric name was not in the map.

R-7 is the rule this module enforces: the map had to be **deleted via a
derivation**, never relocated. Reproducing it as a per-metric-name or
per-check-name map anywhere — including in a "generic" module — is the
fake-central-registry anti-pattern, and the census below turns RED on it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from agent.schemas.health_feedback import (
    _extract_discriminating_metrics,
    _worst_statistic,
    build_collapse_fingerprint,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
HEALTH_FEEDBACK = REPO_ROOT / "src/agent" / "schemas" / "health_feedback.py"


class TestDerivation:
    @pytest.mark.parametrize("operator", [">", ">="])
    def test_a_floor_is_breached_downward(self, operator):
        assert _worst_statistic(operator) == "minimum"

    @pytest.mark.parametrize("operator", ["<", "<="])
    def test_a_ceiling_is_breached_upward(self, operator):
        assert _worst_statistic(operator) == "maximum"

    @pytest.mark.parametrize("operator", [None, "", "==", "!=", "~", "≥"])
    def test_an_unknown_operator_yields_no_direction(self, operator):
        """An evidence reader must not invent a direction it was not told."""
        assert _worst_statistic(operator) is None

    def test_the_derivation_reproduces_the_deleted_maps_answers(self):
        """3/3 parity with ``_WORST_STAT_BY_METRIC`` as it stood at
        ``d44f6f6a``, transcribed as DATA.

        Transcribed rather than imported because the point of the differential
        is that the derivation reproduces the old answers — importing the new
        code to generate the expectation would compare it against itself, and
        the constant no longer exists to import.
        """
        deleted_map = {
            # metric name -> worst stat, with the operator the check declares
            "n_unique_int8_values": ("minimum", ">"),
            "output_std_mv": ("minimum", ">="),
            "dominant_mode_fraction": ("maximum", "<="),
        }
        for metric, (expected_stat, operator) in deleted_map.items():
            assert _worst_statistic(operator) == expected_stat, metric


class TestValueSourceFollowsCheckShape:
    """Where the worst value lives depends on the check's SHAPE, not its name."""

    def _gate(self, *, threshold, metrics):
        return {
            "gate_name": "g",
            "execution_status": "failed",
            "check_passed": False,
            "would_invalidate_under_production_policy": True,
            "resolved_action": "invalidate_round",
            "failure_reason": "r",
            "threshold": threshold,
            "aggregation": {},
            "metrics": metrics,
            "gate_runtime_seconds": 0.0,
        }

    def test_per_file_check_reads_the_aggregate(self):
        raw, _ = _extract_discriminating_metrics(
            self._gate(
                threshold={"metric": "m", "operator": ">", "value": 1, "unit": "count"},
                metrics={"aggregate_statistics": {"minimum": 3, "maximum": 9}},
            )
        )
        assert raw == {"m": 3}

    def test_scalar_check_reads_the_published_value_under_the_declared_name(self):
        """A scalar check's ``aggregate_statistics`` is empty by construction.
        Without this branch the derivation would still produce no fingerprint
        for a task-owned scalar check — the defect would have MOVED, not gone.
        """
        raw, _ = _extract_discriminating_metrics(
            self._gate(
                threshold={"metric": "dispersion", "operator": ">=", "value": 0.04, "unit": None},
                metrics={"aggregate_statistics": {"count": 0}, "dispersion": 0.0005},
            )
        )
        assert raw == {"dispersion": 0.0005}

    def test_no_threshold_row_yields_nothing(self):
        raw, _ = _extract_discriminating_metrics(
            self._gate(threshold=None, metrics={"aggregate_statistics": {"minimum": 1}})
        )
        assert raw == {}

    def test_a_non_numeric_value_is_not_evidence(self):
        raw, _ = _extract_discriminating_metrics(
            self._gate(
                threshold={"metric": "m", "operator": ">", "value": 1, "unit": "count"},
                metrics={"aggregate_statistics": {}, "m": "collapsed"},
            )
        )
        assert raw == {}

    def test_a_bool_is_not_a_number(self):
        """`isinstance(True, int)` is True in Python; a boolean flag is not a
        measurement and must not become one."""
        raw, _ = _extract_discriminating_metrics(
            self._gate(
                threshold={"metric": "m", "operator": ">", "value": 1, "unit": "count"},
                metrics={"aggregate_statistics": {}, "m": True},
            )
        )
        assert raw == {}


class TestExactnessFromDeclaredUnit:
    def _fingerprint(self, unit, value):
        gate = {
            "gate_name": "g",
            "execution_status": "failed",
            "check_passed": False,
            "would_invalidate_under_production_policy": True,
            "resolved_action": "invalidate_round",
            "failure_reason": "r",
            "threshold": {"metric": "m", "operator": ">", "value": 1, "unit": unit},
            "aggregation": {},
            "metrics": {"aggregate_statistics": {"minimum": value}},
            "gate_runtime_seconds": 0.0,
        }
        return build_collapse_fingerprint([gate], "invalidate_round")

    def test_a_count_renders_exactly(self):
        assert self._fingerprint("count", 5.0).signature == "g:m=5"

    def test_a_non_count_buckets_to_two_significant_figures(self):
        assert self._fingerprint("fraction", 0.9612).signature == "g:m=0.96"

    def test_an_absent_unit_buckets(self):
        """DAVIS declares no value scale, so its unit is None. Absence must
        not accidentally mean 'exact'."""
        assert self._fingerprint(None, 0.0005).signature == "g:m=0.0005"


class TestNoReplacementCentralMap:
    """R-7, executable: the map is DELETED, not relocated."""

    def test_the_deleted_constant_is_gone(self):
        import agent.schemas.health_feedback as module

        assert not hasattr(module, "_WORST_STAT_BY_METRIC")

    def test_no_module_level_map_is_keyed_by_a_registered_check_or_metric(self):
        """The surviving `_RECORDING_KEY_METRICS` is HD-T5's, deferred by
        Q-P4-3, and is a SET of recording scalars — not a direction map. Any
        module-level dict whose values are statistic names is a relocated T4.
        """
        tree = ast.parse(HEALTH_FEEDBACK.read_text(encoding="utf-8"))
        offenders = []
        for node in tree.body:
            target = None
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                target, value = node.target.id, node.value
            elif isinstance(node, ast.Assign) and len(node.targets) == 1:
                if isinstance(node.targets[0], ast.Name):
                    target, value = node.targets[0].id, node.value
            if target is None or not isinstance(value, ast.Dict):
                continue
            values = {v.value for v in value.values if isinstance(v, ast.Constant)}
            if values & {"minimum", "maximum", "mean"}:
                offenders.append(target)
        assert offenders == [], f"a direction map was relocated here: {offenders}"

    def test_the_relocation_detector_fires_on_a_planted_map(self):
        """Anti-vacuity for the census above."""
        planted = ast.parse('_WORST: dict[str, str] = {"n_unique_int8_values": "minimum"}\n')
        offenders = []
        for node in planted.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.Dict):
                values = {v.value for v in node.value.values if isinstance(v, ast.Constant)}
                if values & {"minimum", "maximum", "mean"}:
                    offenders.append(node.target.id)
        assert offenders == ["_WORST"]
