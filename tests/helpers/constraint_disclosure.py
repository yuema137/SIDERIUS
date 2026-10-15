"""Validate the native additive suffix before checking existing prompt goldens."""

from agent.prompt_templates.constraints import render_constraint_disclosure


def without_incomplete_disclosure(prompt: str) -> str:
    suffix = "\n\n" + render_constraint_disclosure(None)
    assert prompt.count("[CURRENT RUN EXECUTION CONSTRAINTS]") == 1
    assert prompt.endswith(suffix)
    assert "Incomplete constraint information" in suffix
    assert (
        "missing authority sections: task_rules, workflow_rules, objective, overrides, execution"
        in suffix
    )
    return prompt[: -len(suffix)]
