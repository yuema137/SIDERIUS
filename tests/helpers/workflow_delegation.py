"""Where ``run_workflow`` delegates work that structural censuses inspect.

``run_workflow`` no longer builds its chain-workspace lock or its tuner input
inline. Since the shared native training startup (998be9ef) the lock's
``build_run_invariants`` call and the ``LockLaunchIdentity`` construction live
in ``workflows/training_startup.py``; since the shared tuner preparation
(98a4457c) the validator-to-tuner protocol call lives in
``workflows/tuner_preparation.py``.

A census that follows the call into its owner must also prove the workflow
still reaches that owner: otherwise a workflow that stopped calling it, or
called it with a different launch carrier, would leave the census green over
a module production no longer uses. Both delegated entrypoints take their
inputs as required keyword-only parameters, so a value dropped at the
delegation hop is a ``TypeError`` (and a pyright error), not a silent default.

Kept in one place because several lock-site censuses need the same proof.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / "src/workflows/model_exploration.py"
#: Owns the workflow's ``build_run_invariants`` call and lock identity.
WORKFLOW_LOCK_SITE = REPO_ROOT / "src/workflows/training_startup.py"
WORKFLOW_LOCK_ENTRYPOINT = "prepare_training_run"
#: Owns the workflow's ``local_validated_model`` protocol call.
TUNER_PREPARATION = REPO_ROOT / "src/workflows/tuner_preparation.py"
TUNER_PREPARATION_ENTRYPOINT = "prepare_native_tuner_input"


def calls_in_function(path: Path, function: str, callee: str) -> list[ast.Call]:
    """Every direct ``callee(...)`` call inside ``function``'s body in ``path``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    matches = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == function]
    assert len(matches) == 1, f"{path.name}: expected one function {function!r}"
    return [
        n
        for n in ast.walk(matches[0])
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == callee
    ]


def assert_run_workflow_delegates(entrypoint: str, owner: Path, owned_call: str) -> None:
    """``run_workflow`` calls ``entrypoint(launch=launch, ...)`` exactly once,
    and ``entrypoint`` itself makes the ``owned_call`` the census inspects."""
    delegations = calls_in_function(WORKFLOW, "run_workflow", entrypoint)
    assert len(delegations) == 1, f"run_workflow must call {entrypoint} exactly once"
    launch = {kw.arg: ast.unparse(kw.value) for kw in delegations[0].keywords}.get("launch")
    assert launch == "launch", f"run_workflow passes launch={launch!r} to {entrypoint}"
    owned = calls_in_function(owner, entrypoint, owned_call)
    assert len(owned) == 1, f"{owner.name}:{entrypoint} must call {owned_call} exactly once"
