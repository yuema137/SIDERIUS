"""Typed task-settings observations; no task, hardware or provider execution."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from execute_tools.dataset_config import DataScope
from tools.setup_review.route_models import LLMRoute
from workflows.formal_delta import (
    FORMAL_DELTA_FIELDS as FORMAL_DELTA_FIELDS,
)
from workflows.formal_delta import (
    FormalDelta as FormalDelta,
)
from workflows.formal_delta import (
    decode_formal_delta as decode_formal_delta,
)
from workflows.formal_delta import (
    encode_formal_delta as encode_formal_delta,
)
from workflows.llm_config import WorkflowLLMConfig


class SettingsModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class TaskSettingsInputs(SettingsModel):
    """Already-normalized launch inputs; defaults belong to the standard parser."""

    data_scope: DataScope | None
    formal_strategy: str
    health_gate_enabled: bool
    health_gate_files: list[int] | None
    health_checks_config: str | None
    healthgate_mode: str | None
    result_authority: str | None
    enable_chain_incumbent_formal_gates: bool
    skip_formal_min_delta: FormalDelta
    bypass_formal_time_budget_min_delta: FormalDelta
    analysis_enabled: bool | None
    literature_enabled: bool
    pseudo_llm: bool
    llm_config: WorkflowLLMConfig


class TaskSettingsSummary(SettingsModel):
    """Facts resolved by existing owners; never a launch approval."""

    resolved_data_scope: list[int]
    scope_is_partial: bool
    analysis_enabled: bool
    llm_routes: list[LLMRoute]
    formal_policy: Literal["passed"]
    health_gate_enabled: bool
    health_config: dict[str, JsonValue] | None
    health_config_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None
    unresolved: tuple[str, ...]

    @model_validator(mode="after")
    def health_materialization_matches_enablement(self):
        if self.health_gate_enabled:
            if self.health_config is None or self.health_config_sha256 is None:
                raise ValueError("Enabled Health requires resolved configuration and its digest")
        elif self.health_config is not None or self.health_config_sha256 is not None:
            raise ValueError("Disabled Health must not claim a materialized configuration")
        return self
