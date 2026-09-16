"""Caller-facing application of the schema-owned analysis-source directive."""

from __future__ import annotations

from agent.schemas.data_analysis.context import DataAnalysisInput
from agent.schemas.data_analysis.source_directive import (
    resolve_source_prompt,
    source_prompt_identity,
)

__all__ = ("apply_source_prompt", "resolve_source_prompt", "source_prompt_identity")


def apply_source_prompt(inp: DataAnalysisInput, prompt: str | None) -> DataAnalysisInput:
    """Use the same typed resolver for standalone and composed callers."""

    if prompt is None or prompt.strip().lower() == "auto":
        return inp
    if inp.source_scope is not None:
        raise ValueError("source prompt cannot override an already resolved source scope")
    assert inp.storage.local is not None
    scope = resolve_source_prompt(
        prompt,
        declared_scope=inp.declared_scope,
        available_assets=inp.available_assets,
        access_policy=inp.access_policy,
        run_name=inp.storage.local.run_name,
    )
    return DataAnalysisInput.model_validate(
        {**inp.model_dump(mode="json"), "source_scope": scope.model_dump(mode="json")}
    )
