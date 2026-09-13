"""Loss-only planner instructions, with verbatim legacy replacements."""

import json

from agent.prompt_templates.tuner.loss_context import PlannerLossContext

LEGACY_LOSS_SECTIONS = {
    "LOSS_BASELINE": """Use the same model_config, train_config, and
loss_config as the baseline, but at your chosen trial_portion.""",
    "LOSS_SCREENING": "Test different loss types and learning rates quickly.",
    "LOSS_REFINEMENT": "loss_type, and regularization.",
    "LOSS_EXPLORATION": """    - **Loss config** (always applies): do not repeat the same `loss_type` for more than 2 consecutive runs without improvement. Cycle through the valid loss types for this model.""",
    "LOSS_COLLAPSE": """- If `loss_type="ce"`, switch immediately to focal loss with `alpha={FOCAL_ALPHA_DEFAULT}`
  and `gamma={FOCAL_GAMMA_DEFAULT}`; CE is unstable on class-imbalanced data.
- If focal loss still collapses, reduce `lr` by 2-5×, for example
  `1e-3 → 5e-4 → 1e-4`.
""",
    "LOSS_RESET": """- After persistent collapse, reset to the known-working baseline:
  focal loss (`alpha={FOCAL_ALPHA_DEFAULT}`, `gamma={FOCAL_GAMMA_DEFAULT}`), `lr=5e-4`, and Adam.""",
    "LOSS_INVENTORY_RULE": """When the registry above lists one or more custom losses, you may set
`loss_config.loss_type = "custom"` AND `loss_config.loss_name = <name from
the table>` to train under that loss. The plugin is already generated and
dummy-tensor-validated; selecting it does NOT cost an extra implementor
call. When the block above says "No custom losses registered yet", the only
legal `loss_type` values are the four built-ins (`focal`, `focal_cw`, `ce`,
`smooth_l1`) — see the COMPATIBILITY section in the user message below.""",
}

CUSTOM_COMPATIBILITY_NOTICE = (
    "Custom loss registration "
    "and an earlier dummy test do NOT certify compatibility with this task's "
    "prediction/target geometry. Builtin filtering does not validate custom losses."
)


def render_loss_sections(context: PlannerLossContext | None) -> dict[str, str]:
    """Replace only loss instructions; all legacy bytes are retained."""
    if context is None:
        return LEGACY_LOSS_SECTIONS
    if context.objective is not None:
        return {
            "LOSS_BASELINE": "Use the baseline model/train configuration, but retain the exact task-locked loss_config at your chosen trial_portion.",
            "LOSS_SCREENING": "Test learning rates while retaining the task-locked objective.",
            "LOSS_REFINEMENT": "and regularization; retain the task-locked objective.",
            "LOSS_EXPLORATION": "    - **Loss config is LOCKED**: copy the exact task objective below; never vary its type or parameters.",
            "LOSS_COLLAPSE": "- During collapse recovery, retain the task-locked objective; adjust learning rate or optimizer instead.\n",
            "LOSS_RESET": "- After persistent collapse, revisit model/train settings while retaining the task-locked objective.",
            "LOSS_INVENTORY_RULE": render_loss_choice(context),
        }
    offers = ", ".join(context.builtin_offers)
    return {
        "LOSS_BASELINE": "Use the baseline model/train configuration and its loss only if compatible with the declared offers below, at your chosen trial_portion.",
        "LOSS_SCREENING": "Test compatible loss configurations and learning rates quickly.",
        "LOSS_REFINEMENT": "compatible loss parameters, and regularization.",
        "LOSS_EXPLORATION": f"    - **Loss config**: builtin offers are {offers}. Explore only compatible options; a single eligible type need not change.",
        "LOSS_COLLAPSE": "- During collapse recovery, use only the declared compatible loss options; no automatic loss-family switch is prescribed.\n",
        "LOSS_RESET": "- After persistent collapse, revisit a previously valid configuration, retaining a loss compatible with the declared output.",
        "LOSS_INVENTORY_RULE": render_loss_choice(context),
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
        "When a custom registry entry is present, existing custom/name routing remains available. "
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
