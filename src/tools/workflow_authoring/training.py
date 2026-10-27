"""Small presentation projection; native settings remain the only default authority."""

from functools import cache
from typing import Literal, get_args, get_type_hints

from pydantic import BaseModel, ConfigDict, JsonValue

from workflows.definition import AuthoredWorkflowDocument, ReusableWorkflowDocument

# Presentation only: no copied defaults, validation constraints or execution policy.
CONTROLS = (
    ("trial_time_budget_minutes", "Trial budget (minutes)", "number"),
    ("formal_time_budget_minutes", "Formal budget (minutes)", "number"),
    ("trial_max_epochs", "Trial epoch ceiling", "integer"),
    ("formal_max_epochs", "Formal epoch ceiling", "integer"),
    ("trial_portion", "Trial portion", "number"),
    ("train_portion", "Training portion", "number"),
    ("formal_portion", "Formal portion", "number"),
    ("sampling_seed", "Sampling seed", "integer"),
    ("train_base_seed", "Training base seed", "integer"),
    ("retain_training_checkpoints", "Retain training checkpoints", "boolean"),
    ("retain_model_outputs", "Retain model outputs", "boolean"),
)


class TrainingControlHelp(BaseModel):
    """Inline help copied from the native settings JSON schema, never authored here.

    Absent keys stay ``None``: the editor shows only what the schema declares.
    ``schema_default`` is the launch-config field default; ``effective`` on the
    control is the resolved native value for this document.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    description: str | None = None
    unit: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    exclusive_minimum: float | None = None
    exclusive_maximum: float | None = None
    schema_default: JsonValue = None


class TrainingControl(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    label: str
    kind: str
    nullable: bool
    state: Literal["unset", "null", "supplied"]
    effective: JsonValue
    help: TrainingControlHelp = TrainingControlHelp()


class TrainingInspector(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    controls: tuple[TrainingControl, ...]
    allowed_output_types: tuple[str, ...] | None
    workflow_parameter_rules: JsonValue = None


@cache
def _launch_schema() -> dict[str, dict]:
    from workflows.candidate_training_settings import CandidateTrainingSettings

    schema = CandidateTrainingSettings.model_json_schema()
    return schema["$defs"]["WorkflowLaunchConfig"]["properties"]


def control_help(name: str) -> TrainingControlHelp:
    """Project one launch field's declared JSON-schema metadata."""
    field = _launch_schema()[name]
    branches = [field, *field.get("anyOf", ())]

    def declared(key: str):
        return next((branch[key] for branch in branches if key in branch), None)

    return TrainingControlHelp(
        description=declared("description"),
        unit=declared("unit"),
        minimum=declared("minimum"),
        maximum=declared("maximum"),
        exclusive_minimum=declared("exclusiveMinimum"),
        exclusive_maximum=declared("exclusiveMaximum"),
        schema_default=field.get("default"),
    )


def training_inspector(document: AuthoredWorkflowDocument) -> TrainingInspector | None:
    """Preview validated native values without expanding the authored document."""
    if not isinstance(document, ReusableWorkflowDocument) or document.training_settings is None:
        return None
    from workflows.candidate_training_settings import (
        effective_training_settings,
        parse_training_settings,
    )
    from workflows.run_config import WorkflowLaunchConfig

    settings = parse_training_settings(
        effective_training_settings(
            document.training_settings, document.preparation_options.allowed_output_types
        )
    )
    authored = document.training_settings.get("launch", {})
    assert isinstance(authored, dict)
    annotations = get_type_hints(WorkflowLaunchConfig)
    effective = settings.model_dump(mode="json")["launch"]
    return TrainingInspector(
        allowed_output_types=settings.launch.allowed_output_types,
        controls=tuple(
            TrainingControl(
                name=name,
                label=label,
                kind=kind,
                nullable=type(None) in get_args(annotations[name]),
                state="unset"
                if name not in authored
                else "null"
                if authored[name] is None
                else "supplied",
                effective=effective[name],
                help=control_help(name),
            )
            for name, label, kind in CONTROLS
        ),
        workflow_parameter_rules=authored.get("workflow_parameter_rules"),
    )
