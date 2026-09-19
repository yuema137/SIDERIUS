"""Framework-owned observation carried with a model proposal."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, FiniteFloat

from execute_tools.evaluation_metric import MetricDirection


class ObservedPredictionReference(BaseModel):
    """Proposal-time valid primary score, never an LLM-authored reference."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric_id: str
    direction: MetricDirection
    value: FiniteFloat
    source: Literal["interpretation_best_valid"] = "interpretation_best_valid"
