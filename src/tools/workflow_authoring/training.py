"""Small presentation projection; native settings remain the only default authority."""

from functools import cache
from typing import Literal, get_args, get_type_hints

from pydantic import BaseModel, ConfigDict, JsonValue

from workflows.definition import AuthoredWorkflowDocument, ReusableWorkflowDocument

# Presentation only: no copied defaults, validation constraints or execution policy.
CONTROLS = (
    ("is_trial", "Trial/formal mode", "boolean"),
    ("trial_time_budget_minutes", "Trial budget (minutes)", "number"),
    ("formal_time_budget_minutes", "Formal budget (minutes)", "number"),
    ("trial_max_epochs", "Trial epoch ceiling", "integer"),
    ("formal_max_epochs", "Formal epoch ceiling", "integer"),
    ("trial_portion", "Trial portion", "number"),
    ("train_portion", "Training portion", "number"),
    ("formal_portion", "Formal portion", "number"),
    ("retain_training_checkpoints", "Retain training checkpoints", "boolean"),
    ("retain_model_outputs", "Retain model outputs", "boolean"),
)


# Required run-policy choices (L-1b). Training admission has no default for either
# (execute_tools.health_checks.launch_policy); labels and one-line explanations are
# presentation only, the allowed values come from the native Literal types.
POLICY_CHOICES: tuple[tuple[str, str, str, tuple[tuple[str, str], ...]], ...] = (
    (
        "healthgate_mode",
        "Health checks",
        "What a failed health check does during training. Record only notes it and "
        "keeps going; Block on failure invalidates that round (the task's health "
        "checks must be configured to block).",
        (("observe_only", "Record only"), ("blocking", "Block on failure")),
    ),
    (
        "result_authority",
        "Result standing",
        "Whether this run's results may be cited as scientific evidence. Diagnostic is "
        "for exploring; Scientific requires Block on failure.",
        (("diagnostic", "Diagnostic"), ("scientific", "Scientific")),
    ),
)


class TrainingChoiceOption(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    value: str
    label: str


class TrainingChoiceControl(BaseModel):
    """A required launch choice: unset is a problem the author must resolve."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    label: str
    explanation: str
    options: tuple[TrainingChoiceOption, ...]
    value: str | None
    required: bool = True


class TrainingControlHelp(BaseModel):
    """Inline help copied from the native settings JSON schema, never authored here.

    Absent keys stay ``None``: the editor shows only what the schema declares.
    ``schema_default`` is the launch-config field default and is meaningful only when
    ``has_schema_default`` is true; a declared ``None`` default and an absent default
    are therefore distinct. ``effective`` on the control is the resolved native value
    for this document.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    description: str | None = None
    unit: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    exclusive_minimum: float | None = None
    exclusive_maximum: float | None = None
    has_schema_default: bool = False
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
    policy: tuple[TrainingChoiceControl, ...] = ()
    allowed_output_types: tuple[str, ...] | None
    workflow_parameter_rules: JsonValue = None


@cache
def _launch_schema() -> dict[str, dict]:
    from workflows.candidate_training_settings import CandidateTrainingSettings

    schema = CandidateTrainingSettings.model_json_schema()
    return schema["$defs"]["WorkflowLaunchConfig"]["properties"]


def policy_controls(authored: dict) -> tuple[TrainingChoiceControl, ...]:
    """Project the required policy choices; values outside the native Literal stay unset."""
    from agent.schemas.hyperparam_tuning import HealthGateMode, ResultAuthority

    native = {"healthgate_mode": HealthGateMode, "result_authority": ResultAuthority}
    controls = []
    for name, label, explanation, options in POLICY_CHOICES:
        allowed = get_args(native[name])
        assert {value for value, _ in options} == set(allowed), name
        value = authored.get(name)
        controls.append(
            TrainingChoiceControl(
                name=name,
                label=label,
                explanation=explanation,
                options=tuple(TrainingChoiceOption(value=v, label=t) for v, t in options),
                value=value if value in allowed else None,
            )
        )
    return tuple(controls)


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
        has_schema_default="default" in field,
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
        policy=policy_controls(authored),
        workflow_parameter_rules=authored.get("workflow_parameter_rules"),
    )
