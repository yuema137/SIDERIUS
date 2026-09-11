"""Permanent task-data-path binding and task-identity guardrails."""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]

#: The data-path surface for the task-identity token guardrail.
_DATA_PATH_SURFACE = (
    "src/execute_tools/task_data_path.py",
    "src/execute_tools/train_engine_sandbox.py",
    "src/execute_tools/inference_single.py",
    "src/execute_tools/denoising_score_single.py",
    # Step 11 C9 (F-11-8) — the SPAWN PARENT. It was absent while every one
    # of its children was listed, so the module that decides what the
    # children read was the one place this guardrail could not see. Bringing
    # it in is the point of the finding, not a formality: it carries
    # `TidmadSandbox`, `_tidmad_data_dir` and a `"tidmad_db"` literal, none
    # of which the census had ever examined.
    "src/core/sandbox_executor.py",
)

_TASK_NAME_TOKENS = {"tidmad", "pet", "pets", "davis"}


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _count_calls(tree: ast.AST, name: str) -> int:
    return sum(
        1 for node in ast.walk(tree) if isinstance(node, ast.Call) and _call_name(node) == name
    )


class TestNoDualPath:
    def test_the_production_path_goes_through_the_resolved_binding(self):
        """Delete-the-hop detector (static half; the synthetic e2e is the
        dynamic half): each relocated caller must reach the data path through
        resolution, and the seam methods must actually be invoked."""
        engine = ast.parse(
            (_REPO_ROOT / "src/execute_tools/train_engine_sandbox.py").read_text(encoding="utf-8")
        )
        assert _count_calls(engine, "resolve_bound_task_data_path") >= 1, (
            "the engine no longer resolves the run-bound TaskDataPath — the "
            "registry hop was deleted"
        )
        assert _count_calls(engine, "training_dataset") >= 1
        assert _count_calls(engine, "validation_dataset") >= 1

        inference = ast.parse(
            (_REPO_ROOT / "src/execute_tools/inference_single.py").read_text(encoding="utf-8")
        )
        assert _count_calls(inference, "resolve_child_task_data_path") >= 1
        assert _count_calls(inference, "write_deliverable") >= 1

        scoring = ast.parse(
            (_REPO_ROOT / "src/execute_tools/denoising_score_single.py").read_text(encoding="utf-8")
        )
        assert _count_calls(scoring, "read_evaluation_payload") >= 1

    def test_the_transport_flag_is_never_an_operator_flag(self):
        """Child §4.1 (correction 1, FROZEN): ``--task_data_path_id`` is
        emitted by the parent process FROM the resolved run binding only —
        one configuration authority. No launcher shell may know it, accept
        it, or forward it, so an operator can never supply a binding that
        bypasses resolution."""
        offenders: list[str] = []
        for root in ("sdsc_submission_scripts", "scripts"):
            base = _REPO_ROOT / root
            if not base.exists():
                continue
            for sh in base.rglob("*.sh"):
                if "task_data_path_id" in sh.read_text(encoding="utf-8"):
                    offenders.append(sh.relative_to(_REPO_ROOT).as_posix())
        assert not offenders, f"launcher surfaces must not carry the transport flag: {offenders}"


class TestTaskIdentityGuardrail:
    def test_no_task_name_literal_comparison_on_the_data_path_surface(self):
        """The framework resolves ids by LOOKUP; nothing on the surface may
        branch on the spelling of a task name (``tidmad|pet|davis``). The
        declarations are resolved by registry lookup rather than spelling."""
        violations: list[str] = []
        for rel in _DATA_PATH_SURFACE:
            tree = ast.parse((_REPO_ROOT / rel).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                comparands: list[ast.expr] = []
                if isinstance(node, ast.Compare):
                    comparands = [node.left, *node.comparators]
                elif isinstance(node, ast.MatchValue):
                    comparands = [node.value]
                for expr in comparands:
                    if (
                        isinstance(expr, ast.Constant)
                        and isinstance(expr.value, str)
                        and expr.value.lower() in _TASK_NAME_TOKENS
                    ):
                        violations.append(f"{rel}:{node.lineno}: compares against {expr.value!r}")
        assert not violations, (
            f"task-name spelling must never be branched on (parent §3.1): {violations}"
        )

    def test_task_implementation_imports_on_the_surface_are_the_declared_set(self):
        """A task identity can enter a generic module as an IMPORT, and the
        comparison census above cannot see one.

        `ast.Compare`/`ast.MatchValue` walking is blind to `ast.Import`, so
        the three subprocess entrypoints could name every built-in task
        implementation and still pass the test above — while every file
        involved is listed in `_DATA_PATH_SURFACE`, which makes a reader
        believe the area is covered. That is the F-P2b-4 shape: a census
        green for the wrong reason.

        Import-time real-task bootstrap is forbidden. Every task reaches the
        child only through its transported manifest.
        """
        found: dict[str, set[str]] = {}
        for rel in _DATA_PATH_SURFACE:
            tree = ast.parse((_REPO_ROOT / rel).read_text(encoding="utf-8"))
            names: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names.update(a.name for a in node.names if a.name.endswith("_data_path"))
                elif isinstance(node, ast.ImportFrom) and (node.module or "").endswith(
                    "_data_path"
                ):
                    names.add(node.module or "")
            # The seam module itself is not a task implementation.
            names = {n for n in names if not n.endswith("execute_tools.task_data_path")}
            if names:
                found[rel] = names

        assert not found, f"real-task implementations entered framework surfaces: {found}"
