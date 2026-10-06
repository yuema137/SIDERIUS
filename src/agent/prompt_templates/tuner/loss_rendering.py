"""Task-declared loss eligibility for native planner prompts."""

import json

from agent.prompt_templates.tuner.loss_context import PlannerLossContext

CUSTOM_COMPATIBILITY_NOTICE = (
    "Only names in the task-compatible inventory may be selected. That static "
    "compatibility does not replace runtime numerical validation."
)


def render_loss_sections(context: PlannerLossContext | None) -> dict[str, str]:
    """Disclose the supplied loss contract without prescribing search or recovery."""
    return {
        "LOSS_INVENTORY_RULE": (
            render_loss_choice(context)
            if context is not None
            else "No task loss contract was supplied. Loss eligibility is not established "
            "by this prompt; do not infer that an unspecified loss is permitted."
        )
    }


def render_loss_choice(context: PlannerLossContext) -> str:
    """The same loss selection rule appears in system and user messages."""
    if context.objective is not None:
        exact = context.objective.model_dump_json()
        notice = (
            " " + CUSTOM_COMPATIBILITY_NOTICE if context.objective.loss_type == "custom" else ""
        )
        return (
            f"Task objective is LOCKED. Copy this exact loss_config: `{exact}`. "
            "Do not select an alternative loss, including during baseline or collapse recovery."
            + notice
        )
    return (
        f"Compatible builtin loss types: **{', '.join(context.builtin_offers)}**. "
        "These builtin types pass the framework's declared output semantic/temporal compatibility checks. "
        "When the task-compatible inventory is non-empty, its custom/name routing remains available. "
        + CUSTOM_COMPATIBILITY_NOTICE
    )


def render_loss_model_constraint(context: PlannerLossContext, model_type: str) -> str:
    context.validate_fixed_model(model_type)
    model_rule = (
        "Choose an architecture matching the task's declared output contract."
        if model_type == "auto"
        else f"You MUST use the '{model_type}' architecture. The model type is fixed and cannot be changed."
    )
    knobs = "model_config and train_config"
    if context.objective is None:
        knobs += ", and compatible loss configuration"
    return (
        f"\n### CRITICAL CONSTRAINT:\n- {model_rule}\n- {render_loss_choice(context)}\n"
        f"- Explore {knobs}, respecting fixed parameters and declared compatibility.\n"
    )


def render_loss_example(context: PlannerLossContext | None) -> str:
    if context is None:
        return '{ "loss_type": "ce/focal/smooth_l1", ... }'
    if context.objective is not None:
        return context.objective.model_dump_json()
    return json.dumps({"loss_type": context.builtin_offers[0]})
