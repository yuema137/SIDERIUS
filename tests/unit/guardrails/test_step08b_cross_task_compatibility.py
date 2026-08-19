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

**Step 08c C5 INVERTED the first class** (upgraded, never deleted — the
08a/08b precedent): the runners now DO evaluate their pack's Health family
on the fresh deliverable, so the pinned property became HOW they enter:
through the ONE shared stage (`scripts/_gate2_health_stage.py`) with an
EXPLICIT state-C pack binding. The omitted-binding SHAPE — a composition
call without the `task_health_binding` keyword — is census-refused, and
the stage's parameter is keyword-only with no default, so the hazard
cannot be reintroduced by deleting one argument.
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


SHARED_STAGE = REPO_ROOT / "scripts" / "_gate2_health_stage.py"


def _calls_with_keyword(source: str, function_name: str) -> list[set[str]]:
    """Keyword names at each call of ``function_name``, by AST."""
    tree = ast.parse(source)
    calls: list[set[str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            callee = node.func
            name = callee.attr if isinstance(callee, ast.Attribute) else getattr(callee, "id", None)
            if name == function_name:
                calls.append({kw.arg for kw in node.keywords if kw.arg is not None})
    return calls


class TestExistingTasksEnterHealthOnlyThroughTheExplicitBinding:
    """08b pinned "never enters composition"; 08c C5 INVERTED it.

    Upgraded, never deleted: the runners now evaluate their pack's Health
    family on the FRESH deliverable, so the pinned property became HOW —
    through the ONE shared stage, with an EXPLICIT state-C pack binding.
    An omitted-binding shape would silently compose TIDMAD (the 08b
    hazard), so it is refused structurally at every layer this class can
    see: the runners never call raw composition entry points, the stage's
    binding parameter is keyword-only with no default, and every
    composition call inside the stage passes the keyword.
    """

    @pytest.mark.parametrize("task", sorted(EXISTING_NON_TIDMAD_RUNNERS))
    def test_the_runner_exists_and_is_readable(self, task):
        """Guards the guard: a moved runner would make every check below vacuous."""
        assert EXISTING_NON_TIDMAD_RUNNERS[task].is_file()

    @pytest.mark.parametrize("task", sorted(EXISTING_NON_TIDMAD_RUNNERS))
    def test_the_runner_reaches_health_only_through_the_shared_stage(self, task):
        """No raw composition call, no direct health import — ONE stage."""
        source = EXISTING_NON_TIDMAD_RUNNERS[task].read_text(encoding="utf-8")
        for entry_point in HEALTH_COMPOSITION_ENTRY_POINTS:
            assert f"{entry_point}(" not in source, (
                f"{task} runner calls {entry_point} directly; Health entry is "
                f"owned by the shared stage, which makes the binding explicit"
            )
        imported = _siderius_imports(EXISTING_NON_TIDMAD_RUNNERS[task])
        health_imports = sorted(
            m for m in imported if m in HEALTH_COMPOSITION_MODULES or "health_checks" in m
        )
        assert health_imports == [], (
            f"{task} runner imports {health_imports} directly; it must go "
            f"through scripts._gate2_health_stage"
        )
        assert "scripts._gate2_health_stage" in imported, (
            f"{task} runner no longer imports the shared health stage — the "
            f"08c C5 evidence stage was dropped"
        )

    @pytest.mark.parametrize("task", sorted(EXISTING_NON_TIDMAD_RUNNERS))
    def test_the_runner_passes_an_explicit_pack_binding(self, task):
        source = EXISTING_NON_TIDMAD_RUNNERS[task].read_text(encoding="utf-8")
        calls = _calls_with_keyword(source, "run_health_stage")
        assert calls, f"{task} runner never calls run_health_stage"
        for keywords in calls:
            assert "task_health_binding" in keywords, (
                f"{task} runner calls run_health_stage without an explicit task_health_binding"
            )
        assert 'PACK_ROOT / "declared" / "task_health.yaml"' in source, (
            f"{task} runner's binding is not the pack's own task_health.yaml"
        )

    def test_the_stage_binding_parameter_is_keyword_only_with_no_default(self):
        """Deleting one argument must be a TypeError, never a TIDMAD binding."""
        tree = ast.parse(SHARED_STAGE.read_text(encoding="utf-8"))
        functions = {
            node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        }
        stage = functions["run_health_stage"]
        kwonly = {
            arg.arg: default
            for arg, default in zip(stage.args.kwonlyargs, stage.args.kw_defaults, strict=True)
        }
        assert "task_health_binding" in kwonly
        assert kwonly["task_health_binding"] is None, (
            "task_health_binding acquired a DEFAULT — an omitted binding "
            "would silently select a task"
        )

    def test_every_composition_call_in_the_stage_passes_the_binding(self):
        source = SHARED_STAGE.read_text(encoding="utf-8")
        calls = _calls_with_keyword(source, "materialize_effective_config")
        assert calls, "the stage no longer materializes an effective config"
        for keywords in calls:
            assert "task_health_binding" in keywords, (
                "the stage calls materialize_effective_config without the "
                "explicit task_health_binding keyword — the omitted-binding "
                "shape composes TIDMAD"
            )

    def test_the_stage_is_the_only_composition_caller_under_scripts(self):
        """§4.5 acceptance: ONE stage — no second composition path."""
        offenders = sorted(
            path.name
            for path in (REPO_ROOT / "scripts").glob("*.py")
            if path != SHARED_STAGE
            and "materialize_effective_config(" in path.read_text(encoding="utf-8")
        )
        assert offenders == []

    def test_the_omitted_binding_shape_is_actually_detected(self):
        """Anti-vacuity: the keyword census flags a call WITHOUT the binding."""
        bad = "materialize_effective_config(None, None, workspace)\n"
        calls = _calls_with_keyword(bad, "materialize_effective_config")
        assert calls == [set()]

    def test_the_import_probe_actually_detects_a_health_import(self):
        """Anti-vacuity: the same probe finds a module that DOES import Health.

        Without this, a broken AST walk would make the assertions above pass
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
