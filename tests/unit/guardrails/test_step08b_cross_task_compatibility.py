"""Step 08b — the two EXISTING non-TIDMAD tasks survived the Health refactor.

Operator-directed cross-task compatibility audit, 2026-08-18. Design context:
``docs/design/generic_framework_upgrade/step_08_health_check_task_profile/
pr_08b_extension_architecture.md`` §3.10 (three binding states) and §4.6 (D18).

**This is NOT Step 08c.** No Pets or DAVIS Health roster, no
`categorical_predictions` / `continuous_samples`, no task-specific check. The
only question here is whether the generic refactor silently regressed the two
executable genericity tracks D14 established.

**The specific hazard.** Step 08b C5 made an OMITTED `task_health_binding`
resolve to the legacy default — TIDMAD's task-owned Health config. Any
pre-existing non-TIDMAD runner that predates that argument could therefore
inherit another task's Health semantics without saying anything. That is the
failure this module exists to make impossible to reintroduce quietly.

It is a different failure class from C7's out-of-tree proof, and neither
replaces the other:

    C7   a NEW external task can EXTEND the seam with no infra edit.
    here the two EXISTING tasks did not silently acquire TIDMAD's.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from execute_tools.evaluation_metric import (
    AccuracyMetric,
    GlobalMseMetric,
    metric_spec_from_declaration,
)
from execute_tools.health_checks._composition import HealthBindingState
from execute_tools.health_checks.config import load_composed_health_config
from execute_tools.health_checks.schemas import PerSampleEvidence

REPO_ROOT = Path(__file__).resolve().parents[3]

EXISTING_NON_TIDMAD_RUNNERS = {
    "pets": REPO_ROOT / "scripts" / "run_pets_gate2.py",
    "davis": REPO_ROOT / "scripts" / "run_davis_gate2.py",
}

#: The functions that own the legacy-omitted → TIDMAD fallback. Reaching
#: either is what would expose a task to another task's Health config.
HEALTH_COMPOSITION_ENTRY_POINTS = ("materialize_effective_config", "build_run_invariants")

#: Modules that own those entry points. A runner importing one of these would
#: be one call away from the fallback.
HEALTH_COMPOSITION_MODULES = (
    "core.run_invariants",
    "execute_tools.health_checks.config",
    "execute_tools.health_checks",
)


def _siderius_imports(path: Path) -> set[str]:
    """Top-level SIDERIUS modules a source file imports, by AST.

    AST rather than text so a module named in a comment or docstring cannot
    make this guard cry wolf — the same discipline the pack-governance
    guards use.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return {
        m
        for m in modules
        if m.split(".")[0]
        in {"execute_tools", "core", "nodes", "agent", "workflows", "ml_models", "scripts"}
    }


class TestNeitherExistingTaskCanReachTheTidmadFallback:
    """The blocker question, answered structurally rather than by intent.

    Both runners are direct-execution harnesses — task data path, training
    engine, metric — and never enter the Health composition path at all. So
    they cannot inherit TIDMAD Health: there is no binding decision on their
    route to make wrongly.
    """

    @pytest.mark.parametrize("task", sorted(EXISTING_NON_TIDMAD_RUNNERS))
    def test_the_runner_exists_and_is_readable(self, task):
        """Guards the guard: a moved runner would make every check below vacuous."""
        assert EXISTING_NON_TIDMAD_RUNNERS[task].is_file()

    @pytest.mark.parametrize("task", sorted(EXISTING_NON_TIDMAD_RUNNERS))
    def test_the_runner_never_calls_a_health_composition_entry_point(self, task):
        source = EXISTING_NON_TIDMAD_RUNNERS[task].read_text(encoding="utf-8")

        for entry_point in HEALTH_COMPOSITION_ENTRY_POINTS:
            assert f"{entry_point}(" not in source, (
                f"{task} runner calls {entry_point}; it would then be subject to "
                f"the legacy-omitted binding state, and omitting the argument "
                f"would give it TIDMAD's Health config"
            )

    @pytest.mark.parametrize("task", sorted(EXISTING_NON_TIDMAD_RUNNERS))
    def test_the_runner_imports_no_health_composition_module(self, task):
        imported = _siderius_imports(EXISTING_NON_TIDMAD_RUNNERS[task])
        offenders = sorted(
            m for m in imported if m in HEALTH_COMPOSITION_MODULES or "health_checks" in m
        )

        assert offenders == [], (
            f"{task} runner imports {offenders}. If it is ever routed through "
            f"Health, it must pass an EXPLICIT binding state — an omitted "
            f"argument now means TIDMAD."
        )

    def test_the_import_probe_actually_detects_a_health_import(self):
        """Anti-vacuity: the same probe finds a module that DOES import Health.

        Without this, a broken AST walk would make both assertions above pass
        while proving nothing.
        """
        imported = _siderius_imports(REPO_ROOT / "core" / "resume.py")

        assert any("health_checks" in m for m in imported)


class TestTheExplicitNoBindingStateProtectsThem:
    """The forward guarantee, for when 08c does route these tasks through Health.

    Today they cannot reach the fallback. When they can, `EXPLICIT_NONE` is
    what keeps them from inheriting TIDMAD — so the distinction is pinned
    now, while the reason for it is fresh.
    """

    def test_explicit_none_yields_no_gates_and_no_tidmad_roster(self, tmp_path):
        framework = tmp_path / "framework.yaml"
        framework.write_text("health_gates: []\n")

        composed, task_config, plugins = load_composed_health_config(
            str(framework), HealthBindingState.EXPLICIT_NONE
        )

        assert composed.health_gates == []
        assert task_config is None and plugins == ()

    def test_the_omitted_state_is_visibly_different(self, tmp_path):
        """The contrast that makes the assertion above mean something.

        If both states produced an empty roster, `EXPLICIT_NONE` would be
        decoration rather than protection.
        """
        framework = tmp_path / "framework.yaml"
        framework.write_text("health_gates: []\n")

        omitted, _task, _plugins = load_composed_health_config(str(framework))

        assert [g.id for g in omitted.health_gates] == [
            "output_diversity_blocking",
            "output_std_blocking",
            "amplitude_collapse_blocking",
            "pearson_dispersion_recording",
            "spectral_peak_ratio_recording",
            "per_file_output_std_recording",
        ]


class TestD18AgainstTheRealNonTidmadMetrics:
    """D18 exercised by REAL metric instances, not a synthetic carrier.

    The bridge maps `MetricResult.per_sample` to the typed statement. These
    assert what the two existing non-TIDMAD metrics ACTUALLY return — read
    from source, not assumed — so the mapping is pinned against production
    arithmetic rather than against a fixture written to agree with it.
    """

    @staticmethod
    def _spec(pack: str, declaration: str):
        return metric_spec_from_declaration(
            json.loads(
                (REPO_ROOT / "examples" / pack / "declared" / declaration).read_text(
                    encoding="utf-8"
                )
            )
        )

    def test_pets_accuracy_is_scalar_only_through_the_bridge(self, tmp_path):
        """Pets is the source-grounded scalar-only example."""
        deliverable = tmp_path / "predictions.csv"
        deliverable.write_text("x", encoding="utf-8")

        result = AccuracyMetric(self._spec("oxford_iiit_pet", "metric_accuracy.json")).evaluate(
            {0: str(deliverable)},
            predictions={"a": 1, "b": 2},
            truth={"a": 1, "b": 2},
        )

        assert result.per_sample is None
        assert PerSampleEvidence.for_per_sample(result.per_sample) is (
            PerSampleEvidence.SCALAR_ONLY
        )

    def test_davis_global_mse_is_ALSO_scalar_only_through_the_bridge(self, tmp_path):
        """Pinned from the real implementation rather than guessed.

        `GlobalMseMetric._compute` returns ``(mse, None, ())`` — DAVIS is
        scalar-only too, which the Step-08b design recorded only for Pets. So
        TWO of the three executable tracks carry no per-sample evidence, and
        only TIDMAD does.
        """
        deliverable = tmp_path / "frames.npz"
        deliverable.write_text("x", encoding="utf-8")

        result = GlobalMseMetric(self._spec("davis_future_prediction", "metric_mse.json")).evaluate(
            {0: str(deliverable)},
            predictions={"clip_a": [[0.0, 1.0]]},
            truth={"clip_a": [[0.0, 1.0]]},
        )

        assert result.per_sample is None
        assert PerSampleEvidence.for_per_sample(result.per_sample) is (
            PerSampleEvidence.SCALAR_ONLY
        )

    def test_a_per_sample_capable_metric_still_reports_AVAILABLE(self):
        """The positive control — TIDMAD's shape, which must not move.

        Without it, a bridge that reported SCALAR_ONLY unconditionally would
        satisfy both assertions above.
        """
        assert PerSampleEvidence.for_per_sample([0.1] * 20) is PerSampleEvidence.AVAILABLE

    def test_health_never_consumes_the_metric_scalar(self):
        """Frozen invariant 16, asserted across every registered check.

        A check reading the score would be grading the very result it exists
        to judge independently — and for a scalar-only task the score is the
        ONLY number available, which is exactly when the temptation appears.
        """
        import inspect

        from execute_tools.health_checks import registry

        for name in registry.all_registered():
            source = inspect.getsource(type(registry.get(name)))
            assert "denoising_score" not in source, name
            assert ".scalar" not in source, name


class TestNoTaskNameBranchWasNeeded:
    """The refactor did not buy compatibility with a task-name branch."""

    @pytest.mark.parametrize("task_name", ["pets", "davis", "oxford", "tidmad"])
    def test_the_generic_health_modules_carry_no_task_branch(self, task_name):
        """The ONE permitted task reference is the legacy-default CONSTANT.

        `LEGACY_DEFAULT_TASK_HEALTH_CONFIG` is an unconditional default path,
        not a branch: there is no `if task == …` anywhere, which is what
        stops the compatibility path from growing into a task registry.
        """
        package = REPO_ROOT / "execute_tools" / "health_checks"
        offenders = []
        for module in sorted(package.glob("*.py")):
            for number, line in enumerate(module.read_text(encoding="utf-8").splitlines(), 1):
                code = line.split("#", 1)[0]
                if task_name in code.lower() and any(
                    keyword in code for keyword in ("if ", "elif ", "match ", "== ")
                ):
                    offenders.append(f"{module.name}:{number}: {line.strip()}")

        assert offenders == [], offenders
