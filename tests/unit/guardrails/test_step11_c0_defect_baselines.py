"""Host-memory failures retain one classification owner and measurement workers inherit explicit environments."""

from __future__ import annotations

import ast
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


_OOM_STATUS = "oom_host_ram"


_OOM_PRODUCER = REPO_ROOT / "src/core" / "sandbox_executor.py"


_TUNER_NODE = REPO_ROOT / "src/nodes" / "ml_hyperparameter_tune_agent"


def _code_string_literals(path: pathlib.Path) -> set[str]:
    """Every string CONSTANT in a module, minus docstrings.

    Comments never reach the AST at all, so prose about a status is
    excluded for free and no file needs to appear on an allow-list.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:  # pragma: no cover - defensive
        return set()
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None) or []
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstrings.add(id(body[0].value))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    }


class TestTheHostOomStatusHasExactlyOneConsumingAuthority:
    """One producer module, one consumer authority — no third speller.

    The defect existed because producer and consumer never shared a name.
    """

    def test_exactly_one_production_module_spells_the_status_in_code(self):
        """Scope, stated explicitly: every non-test `.py` under the
        production roots — the same walk the pre-fix census used, so the
        two are comparable.

        It counts the status as a **code literal**, excluding comments and
        docstrings, which is what makes the census exact rather than
        name-exempt: `failure_attribution.py` discusses the status in prose
        and needs no entry on any allow-list, and neither does the comment
        at the tuner's own branch site. A `== "oom_host_ram"` anywhere
        would be a code literal and would turn this RED.
        """
        namers: list[str] = []
        for root in (
            "src/core",
            "src/execute_tools",
            "src/agent",
            "src/nodes",
            "src/workflows",
            "src/dashboard",
        ):
            for path in sorted((REPO_ROOT / root).rglob("*.py")):
                if path == _OOM_PRODUCER:
                    continue
                if _OOM_STATUS in _code_string_literals(path):
                    namers.append(str(path.relative_to(REPO_ROOT)))
        assert namers == ["src/nodes/ml_hyperparameter_tune_agent/records.py"], (
            "the status must be spelled in exactly one consumer authority; a "
            f"second speller is how F-11-1 happened. Found: {namers}"
        )

    def test_the_tag_matcher_stays_device_oom_only(self):
        """`_is_cuda_oom` must never match a host OOM: that is what keeps
        the record out of the `_oom` family and the planner note unrendered
        (Q-11-3 = A). C2 must not blur the distinction it preserves.
        """
        from nodes.ml_hyperparameter_tune_agent.records import _is_cuda_oom

        assert _is_cuda_oom("CUDA out of memory") is True
        assert _is_cuda_oom("torch.cuda.OutOfMemoryError") is True
        assert _is_cuda_oom("[oom_host_ram] Host RAM exhaustion detected") is False


class TestTheSpawnParentIsCensused:
    """R-11-10: the C0 inverted guard is REPLACED, not twinned.

    Its predecessor asserted that `core/sandbox_executor.py` was ABSENT
    from the task-data-path surface — the module that decides what every
    child reads was the one place the repository's own guardrail could not
    look, while all three of its children were listed.
    """

    def test_the_spawn_parent_is_on_the_surface(self):
        from tests.unit.guardrails.test_task_data_path_census import _DATA_PATH_SURFACE

        assert "src/core/sandbox_executor.py" in _DATA_PATH_SURFACE

    def test_all_three_children_are_still_there_too(self):
        """Widening must not have traded one blind spot for another."""
        from tests.unit.guardrails.test_task_data_path_census import _DATA_PATH_SURFACE

        for child in (
            "src/execute_tools/train_engine_sandbox.py",
            "src/execute_tools/inference_single.py",
            "src/execute_tools/denoising_score_single.py",
        ):
            assert child in _DATA_PATH_SURFACE
