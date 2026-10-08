"""What the launcher actually binds into ``run_workflow``.

Step 09.5a C3 moved the 72 transit-configuration values off ``run_workflow``'s
signature and into ``WorkflowLaunchConfig``, so the launcher's call site now
reads::

    run_workflow(
        launch=WorkflowLaunchConfig(
            trial_portion=args.trial_portion,     # <- one level deeper
            ...
        ),
        workspace=args.workspace,                 # <- still direct
        ...
    )

Several source-level censuses assert "the launcher binds CLI value X to
workflow input X". That invariant did not change — only where the keyword is
written. The standard runner now calls ``build_standard_launch_config``;
follow that edge only when it supplies ``run_workflow(launch=...)``. This helper
flattens those levels so censuses test a reachable binding, not dead declarations.

Kept in one place deliberately: five test modules need it, and five private
copies of an AST walk is how they drift apart.
"""

from __future__ import annotations

import ast
from pathlib import Path

#: Call nodes whose keywords count as launcher bindings. ``run_workflow`` is
#: the boundary itself; ``WorkflowLaunchConfig`` is the carrier it forwards.
_BINDING_CALLS = ("run_workflow", "WorkflowLaunchConfig")


def workflow_call_bindings(source: str | Path) -> dict[str, str]:
    """Every keyword the launcher binds into the workflow, flattened.

    Args:
        source: launcher source text, or a path to it.

    Returns:
        ``{parameter_name: unparsed_expression}`` across the ``run_workflow``
        call and any ``WorkflowLaunchConfig`` constructed inside it.
    """
    text = source.read_text() if isinstance(source, Path) else source
    tree = ast.parse(text)
    bindings: dict[str, str] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id not in _BINDING_CALLS:
            continue
        for kw in node.keywords:
            if kw.arg is not None and kw.arg != "launch":
                bindings[kw.arg] = ast.unparse(kw.value)
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "run_workflow"
        ):
            continue
        launch = next((kw.value for kw in node.keywords if kw.arg == "launch"), None)
        if isinstance(launch, ast.Name):
            # Follow only one unambiguous direct assignment. A rebound variable
            # must not make a dead projection count as a forwarded owner.
            assignments = [
                item.value
                for item in ast.walk(tree)
                if isinstance(item, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id == launch.id
                    for target in item.targets
                )
                and item.lineno < node.lineno
            ]
            launch = assignments[0] if len(assignments) == 1 else None
        if (
            isinstance(launch, ast.Call)
            and isinstance(launch.func, ast.Name)
            and launch.func.id == "build_standard_launch_config"
        ):
            owner = Path(__file__).resolve().parents[2] / "src/workflows/standard_launch.py"
            bindings.update(workflow_call_bindings(owner))
    return bindings


def effective_workflow_kwargs(call_args) -> dict:
    """Flatten a mocked ``run_workflow`` call into the pre-C3 flat kwargs view.

    Tests that patch ``run_workflow`` and assert on what the launcher passed
    are testing the VALUE that reached the workflow, not which object carried
    it. This restores the flat view so those assertions stay about the value.

    Args:
        call_args: ``mock.call_args`` from a patched ``run_workflow``.
    """
    import dataclasses

    kwargs = dict(call_args.kwargs)
    launch = kwargs.pop("launch", None)
    if launch is not None:
        for f in dataclasses.fields(launch):
            kwargs[f.name] = getattr(launch, f.name)
    return kwargs
