"""Bounded typo checks; native workflow models still own configuration values."""

from pydantic import BaseModel, JsonValue, TypeAdapter

from workflows.llm_config import NodeLLMConfig, ProposalLLMConfig, WorkflowLLMConfig


def _check_keys(value: JsonValue, model: type[BaseModel], context: str) -> None:
    if not isinstance(value, dict):
        return  # The native model owns shape/type errors.
    accepted: set[str] = set()
    for name, field in model.model_fields.items():
        accepted.add(name)
        if field.alias:
            accepted.add(field.alias)
            if field.alias != name and name in value and field.alias in value:
                raise ValueError(f"{context}: duplicate name/alias {name!r} and {field.alias!r}")
    if unknown := value.keys() - accepted:
        raise ValueError(f"{context}: unknown configuration keys: {sorted(unknown)}")


def parse_config(content: bytes) -> WorkflowLLMConfig:
    """Validate captured JSON, preserving missing blocks and explicit retry intent."""
    value = TypeAdapter(JsonValue).validate_json(content)
    _check_keys(value, WorkflowLLMConfig, "llm_config")
    if isinstance(value, dict):
        for role in ("implement", "validate", "validate_model"):
            _check_keys(value.get(role), NodeLLMConfig, f"llm_config.{role}")
        proposal = value.get("propose")
        _check_keys(proposal, ProposalLLMConfig, "llm_config.propose")
        if isinstance(proposal, dict):
            for stage in ProposalLLMConfig.model_fields:
                _check_keys(proposal.get(stage), NodeLLMConfig, f"llm_config.propose.{stage}")
    return WorkflowLLMConfig.model_validate(value)
