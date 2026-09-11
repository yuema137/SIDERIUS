# tests/unit/execute_tools/health_checks/test_step10_p4_c3_fourth_task_evidence.py
"""Step 10 / P4 — C3: three-task completeness + the fourth-task evidence proof.

The genericity claim, made executable at the EVIDENCE layer.

08b already proved a synthetic external task can REGISTER and RUN with zero
additional infrastructure edits. P4's claim is narrower and different: that
same task's check gets **evidence as complete as TIDMAD's** — threshold row,
per-file naming, unit and sampling label — with zero central metadata edits,
zero task-name branches and zero entries in any framework table.

The fixture is deliberately unlike TIDMAD: its own capability, its own metric
name, its own unit vocabulary, its own sampling label, a `<` operator no
shipped check uses, and a task-owned unit read from a config key it names
itself. If the evidence path only rendered TIDMAD-shaped checks completely,
none of that would survive.

Routed through ``evaluation._persist`` — the production evidence builder —
and NOT through the D14 Gate runners, whose direct ``runner.evaluate_gate``
bypass is exactly where this defect hid.
"""

from __future__ import annotations

import re
import textwrap
from pathlib import Path

import pytest
import yaml

from execute_tools.health_checks import _plugin_binding, evaluation
from execute_tools.health_checks.config import load_composed_health_config
from execute_tools.health_checks.schemas import (
    CheckVerdict,
    GateAction,
    GateResult,
    HealthCheckContext,
    HealthCheckResult,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
PRODUCTION_PACKAGES = (
    "src/execute_tools",
    "src/nodes",
    "src/agent",
    "src/core",
    "scripts",
    "src/workflows",
    "configs",
)

#: Every identifier the synthetic task invents. None may appear in production
#: source — that absence IS the zero-central-edit proof.
FIXTURE_IDENTIFIERS = (
    "zenith_pressure_health",
    "zenith.window_statistics",
    "zenith_drift_ceiling",
    "zenith.window_provider",
    "max_drift_kpa",
    "observed_drift",
    "kPa",
    "rolling_window_median",
)

CAPABILITY = "zenith.window_statistics"

_PLUGIN = textwrap.dedent('''
    """An out-of-tree task's Health plugin. Nothing in SIDERIUS names it."""

    from typing import Any, ClassVar

    from execute_tools.health_checks._view_provider import HealthView
    from execute_tools.health_checks.registry import register, register_view_provider
    from execute_tools.health_checks.schemas import (
        CheckInputDeclaration,
        EvidenceUnit,
        HealthCheckContext,
        HealthCheckResult,
        ThresholdDeclaration,
    )

    CAPABILITY = "zenith.window_statistics"


    class ZenithWindowProvider:
        provider_id: ClassVar[str] = "zenith.window_provider"
        capabilities: ClassVar[frozenset[str]] = frozenset({CAPABILITY})

        def materialize(self, capability_key, ctx, config=None):
            return HealthView(
                capability_key=capability_key,
                provider_id=self.provider_id,
                payload={"drift": {"0": 0.5, "1": 4.25}},
            )


    class ZenithDriftCeilingCheck:
        """A task-specific check whose evidence is entirely its own."""

        name: ClassVar[str] = "zenith_drift_ceiling"

        _DEFAULT_MAX_DRIFT: ClassVar[float] = 9.0

        declaration: ClassVar[CheckInputDeclaration] = CheckInputDeclaration(
            consumes_view=CAPABILITY,
            requires_view=True,
            evidence_thresholds=(
                ThresholdDeclaration(
                    metric="observed_drift",
                    operator="<",
                    config_key="max_drift_kpa",
                    default=_DEFAULT_MAX_DRIFT,
                    # TASK-owned unit, named by the check, resolved at render
                    # time from this task's own config key.
                    unit=EvidenceUnit(config_key="pressure_unit"),
                ),
            ),
            per_file_metric_name="observed_drift",
            per_file_metric_unit=EvidenceUnit(config_key="pressure_unit"),
            per_file_metrics_key="drift_per_window",
            sampling_method_label="rolling_window_median",
        )

        def run(
            self,
            ctx: HealthCheckContext,
            config: dict[str, Any] | None = None,
            *,
            view: HealthView | None = None,
        ) -> HealthCheckResult:
            assert view is not None
            ceiling = float((config or {}).get("max_drift_kpa", self._DEFAULT_MAX_DRIFT))
            drift = view.payload["drift"]
            worst = max(drift.values())
            return HealthCheckResult(
                check_name=self.name,
                passed=worst < ceiling,
                reason=f"worst drift {worst}",
                metrics={"drift_per_window": drift, "observed_drift": worst},
            )


    register_view_provider(ZenithWindowProvider())
    register(ZenithDriftCeilingCheck())
''')


def _external_task(root: Path) -> str:
    """A complete out-of-tree task package: config + plugin, nothing else."""
    (root / "plugins").mkdir(parents=True, exist_ok=True)
    (root / "plugins" / "health.py").write_text(_PLUGIN)
    config = root / "zenith_pressure_health.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "facts": {"encoding_family": "continuous_float"},
                "plugins": [{"kind": "file", "ref": "./plugins/health.py"}],
                "providers": [{"provider_id": "zenith.window_provider"}],
                "roster": [
                    {
                        "gate_id": "zenith_drift_blocking",
                        "check": "zenith_drift_ceiling",
                        "disposition": "blocking",
                        "parameters": {"max_drift_kpa": 5.0, "pressure_unit": "kPa"},
                        "reason": "Pressure drift above the ceiling is a failed seal.",
                    }
                ],
            }
        )
    )
    return str(config)


@pytest.fixture(autouse=True)
def _isolated_run_scope():
    from execute_tools.health_checks.registry import _PROVIDER_REGISTRY, _REGISTRY

    checks = dict(_REGISTRY)
    providers = dict(_PROVIDER_REGISTRY)
    _plugin_binding.reset_run_scope()
    try:
        yield
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(checks)
        _PROVIDER_REGISTRY.clear()
        _PROVIDER_REGISTRY.update(providers)
        _plugin_binding.reset_run_scope()


def _persist_fourth_task(tmp_path: Path):
    composed, _task_config, _ = load_composed_health_config(None, _external_task(tmp_path))
    (gate,) = composed.health_gates
    result = GateResult(
        gate_id=gate.id,
        round_index=1,
        passed=False,
        action=GateAction.CONTINUE,
        failure_reason="zenith_drift_ceiling: worst drift 4.25",
        check_results=[
            HealthCheckResult(
                check_name="zenith_drift_ceiling",
                passed=False,
                reason="zenith_drift_ceiling: worst drift 4.25",
                metrics={"drift_per_window": {"0": 0.5, "1": 4.25}, "observed_drift": 4.25},
                verdict=CheckVerdict.FAILED,
            )
        ],
    )
    ctx = HealthCheckContext(
        model_name="zenith_net",
        run_name="zenith_run",
        round_index=1,
        denoised_filename_fn=lambda index: f"/nonexistent/w{index}.bin",
    )
    return evaluation._persist(result, gate, None, ctx, 0.0, None)


class TestFourthTaskGetsCompleteEvidence:
    def test_threshold_row_is_complete_and_entirely_the_tasks_own(self, tmp_path):
        """Its metric, its operator, its config key, its task-owned unit —
        none of which any framework table has ever heard of."""
        persisted = _persist_fourth_task(tmp_path)
        assert persisted.threshold == {
            "metric": "observed_drift",
            "operator": "<",
            "value": 5.0,
            "unit": "kPa",
        }
        assert "source" not in persisted.threshold

    def test_per_file_rows_use_the_checks_own_naming_unit_and_sampling_label(self, tmp_path):
        """Including a sampling label that is not TIDMAD's, read from a
        metrics key the check named itself."""
        persisted = _persist_fourth_task(tmp_path)
        rows = persisted.metrics["per_file"]
        assert set(rows) == {"0", "1"}
        for row in rows.values():
            assert row["sampling_method"] == "rolling_window_median"
            assert list(row["metrics"]) == ["observed_drift"]
            assert row["metrics"]["observed_drift"]["unit"] == "kPa"
        assert rows["1"]["metrics"]["observed_drift"]["value"] == 4.25

    def test_the_checks_own_default_is_used_and_labelled_when_unconfigured(self, tmp_path):
        """Q-P4-1 is generic, not a TIDMAD affordance."""
        from execute_tools.health_checks import registry

        _persist_fourth_task(tmp_path)  # loads the out-of-tree plugin first
        declaration = registry.get("zenith_drift_ceiling").declaration
        row = evaluation._threshold(declaration, {"pressure_unit": "kPa"})
        assert row is not None
        assert row["value"] == 9.0
        assert row["source"] == "check_default"

    def test_no_fixture_identifier_appears_in_production_source(self):
        """The zero-central-edit proof. Asserted by absence from production
        source rather than by inspecting a git diff, which would describe this
        commit rather than the property.

        Matched on identifier BOUNDARIES, not raw substrings: a naive `in`
        test reports `kPa` inside ``HealthCheckPanelOutput`` and the proof
        fails for a reason that has nothing to do with the property.
        """
        offenders: list[str] = []
        for package in PRODUCTION_PACKAGES:
            for path in (REPO_ROOT / package).rglob("*"):
                if path.suffix not in {".py", ".yaml", ".yml"} or not path.is_file():
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
                offenders += [
                    f"{path.relative_to(REPO_ROOT)}: {identifier}"
                    for identifier in FIXTURE_IDENTIFIERS
                    if re.search(rf"(?<![0-9A-Za-z_]){re.escape(identifier)}(?![0-9A-Za-z_])", text)
                ]
        assert offenders == [], "fixture identifiers leaked into production:\n  " + "\n  ".join(
            offenders
        )
