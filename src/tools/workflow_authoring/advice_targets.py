"""Where each agent reads the author's free-text advice in a reusable declaration.

Presentation projection only. The authoritative fields stay in the declaration
models (``CandidatePreparationOptions`` and the native launch config's
``human_advice_tune``); this module names them once so the editor can render
"Your advice to the agents" first without the browser guessing field paths.
"""

from dataclasses import fields
from typing import Literal

from pydantic import BaseModel, ConfigDict

from workflows.definition import CandidatePreparationOptions
from workflows.run_config import WorkflowLaunchConfig


class AdviceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AdviceSocket(AdviceModel):
    """Under this protocol the agent reads the advice only through this bound socket."""

    protocol: str
    argument: str


class AdviceTarget(AdviceModel):
    capability: str
    location: Literal["preparation_options", "training_settings.launch"]
    field: str
    label: str
    help: str
    placeholder: str
    socket: AdviceSocket | None = None


class AdviceTargets(AdviceModel):
    targets: tuple[AdviceTarget, ...]


_HELP = (
    "Plain text the {agent} agent reads before it works. Describe what you know or want; "
    "it is saved in the workflow source and reviewed with every other change."
)

ADVICE_TARGETS = AdviceTargets(
    targets=(
        AdviceTarget(
            capability="proposal",
            location="preparation_options",
            field="proposal_advice",
            label="Your advice to the agents",
            help=_HELP.format(agent="proposal"),
            placeholder="e.g. Start from a small, interpretable baseline before larger models.",
            socket=AdviceSocket(protocol="interpretation-to-proposal", argument="human_advice"),
        ),
        AdviceTarget(
            capability="implementation",
            location="preparation_options",
            field="implementation_advice",
            label="Your advice to the agents",
            help=_HELP.format(agent="implementation"),
            placeholder="e.g. Keep diagnostics explicit and log intermediate shapes.",
        ),
        AdviceTarget(
            capability="validation",
            location="preparation_options",
            field="validation_advice",
            label="Your advice to the agents",
            help=_HELP.format(agent="validation"),
            placeholder="e.g. Inspect held-out residuals before accepting a candidate.",
        ),
        AdviceTarget(
            capability="tuning",
            location="training_settings.launch",
            field="human_advice_tune",
            label="Your advice to the agents",
            help=_HELP.format(agent="train & tune"),
            placeholder="e.g. Prefer fewer, longer trials over many short ones.",
        ),
    )
)


def advice_targets() -> AdviceTargets:
    """Fail closed if a named field leaves its owning model."""
    owners = {
        "preparation_options": set(CandidatePreparationOptions.model_fields),
        "training_settings.launch": {item.name for item in fields(WorkflowLaunchConfig)},
    }
    for target in ADVICE_TARGETS.targets:
        if target.field not in owners[target.location]:
            raise RuntimeError(f"advice field {target.field} is not owned by {target.location}")
    return ADVICE_TARGETS
