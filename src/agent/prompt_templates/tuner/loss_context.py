"""Typed composed-run loss facts; builtin offers reuse execution's authority."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, model_validator

from ml_models import models_format_sandbox as loss_authority
from ml_models.models_format_sandbox import LossConfig, OutputSemantic


class PlannerLossContext(BaseModel):
    """Declared output facts and optional task lock, never plugin certification.

    An absent context is reserved for legacy prompt rendering. A composed run
    must supply actual semantic and temporal facts, including explicit False.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    output_semantic: OutputSemantic
    output_has_temporal_axis: bool
    objective: LossConfig | None = None

    @property
    def builtin_offers(self) -> tuple[str, ...]:
        return loss_authority.eligible_builtin_loss_types(
            self.output_semantic,
            output_has_temporal_axis=self.output_has_temporal_axis,
        )

    @model_validator(mode="after")
    def _validate_objective_and_offers(self) -> PlannerLossContext:
        if self.objective is not None and self.objective.loss_type == "custom":
            # An explicit custom objective has its own execution path. This
            # builtin-only projection establishes nothing about its geometry.
            return self
        if self.objective is not None:
            loss_authority.validate_semantic_loss_compatibility(
                self.output_semantic,
                self.objective.loss_type,
                model_type="task-declared objective",
                output_has_temporal_axis=self.output_has_temporal_axis,
            )
        if not self.builtin_offers:
            raise ValueError("No compatible builtin loss offers for the declared ModelIO output")
        return self

    def validate_fixed_model(self, model_type: str) -> None:
        """Refuse contradictory declarations before constructing a prompt."""
        if model_type == "auto":
            return
        from ml_models.plugin_loader import get_output_type

        output_type = get_output_type(model_type)
        semantic = loss_authority.output_semantic_from_legacy(output_type)
        if semantic is not None and semantic is not self.output_semantic:
            raise ValueError(
                f"Fixed model {model_type!r} declares output {output_type!r} "
                f"({semantic.value}), but task ModelIO declares "
                f"{self.output_semantic.value}; reconcile the declarations before planning."
            )
