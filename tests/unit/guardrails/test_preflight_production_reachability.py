"""The production pre-flight must reach the isolated worker — provably.

V20 PR A exists because two components were built, tested, and never
called from production: calibration promotion, and the isolated
pre-flight worker. A green unit suite proved nothing about either,
because a unit test exercises a component in isolation and says nothing
about whether anything reaches it.

So these assertions are about the **call graph**, not about behaviour.
They are deliberately structural: they fail if someone rewires the
production path back to the in-process skill, which is the specific
regression that would silently restore a 6,962 MiB CUDA context in the
chain parent.

Substring searches are avoided — an earlier version of a sibling test
failed on a comment that merely cited ``wrapper.py``. Prose is not a call
graph, so these parse the AST.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
TUNER = REPO_ROOT / "nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py"
ADAPTER = REPO_ROOT / "agent/skills/evaluate_vram_skill/preflight_adapter.py"
WORKER = REPO_ROOT / "agent/skills/evaluate_vram_skill/preflight_worker_main.py"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _called_names(tree: ast.Module) -> set[str]:
    """Every callee spelled as a bare name or an attribute tail."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def _string_args(tree: ast.Module, callee: str) -> set[str]:
    """First-positional string literals passed to ``callee``."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name != callee:
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                found.add(arg.value)
    return found


class TestProductionReachesTheIsolatedWorker:
    def test_tuner_calls_the_adapter(self):
        """The audited production caller must reach the adapter."""
        assert "run_production_preflight" in _called_names(_tree(TUNER))

    def test_tuner_imports_the_adapter(self):
        tree = _tree(TUNER)
        modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert "agent.skills.evaluate_vram_skill.preflight_adapter" in modules

    def test_adapter_calls_run_isolated_preflight(self):
        assert "run_isolated_preflight" in _called_names(_tree(ADAPTER))

    def test_worker_is_the_only_caller_of_the_in_process_skill(self):
        """``run_skill`` may be reached from the worker, and nowhere else
        on the production path."""
        assert "run_skill" in _called_names(_tree(WORKER))


class TestNoInProcessFallback:
    def test_tuner_no_longer_dispatches_the_vram_skill_in_process(self):
        """The regression this guardrail exists for.

        If someone restores ``_run_skill("evaluate_vram_skill", …)`` in the
        tuner, the parent gets its CUDA context back and this fails.
        """
        assert "evaluate_vram_skill" not in _string_args(_tree(TUNER), "_run_skill")

    def test_adapter_does_not_import_the_in_process_skill(self):
        tree = _tree(ADAPTER)
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert not any(m.endswith("evaluate_vram_skill.wrapper") for m in imported)

    def test_adapter_has_no_exception_handler_around_the_probe(self):
        """A ``try`` around the probe call is where a silent retry would
        be added. There is none, and there must not be."""
        tree = _tree(ADAPTER)
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                calls = _called_names(ast.Module(body=node.body, type_ignores=[]))
                assert "run_isolated_preflight" not in calls, (
                    "run_isolated_preflight must not sit inside a try block — "
                    "a worker failure is a typed outcome, never a retry"
                )


class TestParentStaysCpuOnly:
    def test_importing_the_adapter_leaves_torch_unimported(self):
        code = (
            "import sys;"
            "import agent.skills.evaluate_vram_skill.preflight_adapter;"
            "print('torch' in sys.modules)"
        )
        out = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=True,
            cwd=REPO_ROOT,
        )
        assert out.stdout.strip() == "False", out.stdout

    @pytest.mark.parametrize("forbidden", ["torch", "MODEL_REGISTRY", "get_config_class"])
    def test_adapter_never_constructs_the_candidate(self, forbidden):
        """A memory limit applied after the model is resident protects
        nothing, so the parent must not build one."""
        tree = _tree(ADAPTER)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.update(a.name for a in node.names)
                if node.module:
                    imported.add(node.module)
        assert forbidden not in imported
        assert forbidden not in _called_names(tree)


class TestSubprocessPathsUnchanged:
    @pytest.mark.parametrize(
        "script", ["execute_tools/train_engine_sandbox.py", "execute_tools/inference_single.py"]
    )
    def test_training_and_inference_still_run_as_subprocesses(self, script):
        """PR A must not touch the paths that already behave correctly."""
        source = (REPO_ROOT / "core/sandbox_executor.py").read_text(encoding="utf-8")
        assert script in source
