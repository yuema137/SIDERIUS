"""Task-owned Health view for synthetic masked-regression deliverables."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from execute_tools.health_checks import (
    CONTINUOUS_SAMPLES,
    ContinuousSamplesPayload,
    HealthView,
    register_view_provider,
)
from execute_tools.health_checks.schemas import HealthCheckContext


def project_valid_predictions(path: Path) -> np.ndarray:
    """Decode valid predictions in canonical sample-id order."""
    if not path.is_file():
        raise FileNotFoundError(f"synthetic masked-regression deliverable not found: {path}")
    decoded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("synthetic masked-regression deliverable must be a JSON object.")
    values = [
        float(decoded[sample_id]["prediction"])
        for sample_id in sorted(decoded)
        if bool(decoded[sample_id]["valid"])
    ]
    return np.asarray(values, dtype=np.float32)


class MaskedRegressionHealthViews:
    """Expose valid predictions through the standard continuous view."""

    provider_id: ClassVar[str] = "synthetic_masked_regression.valid_predictions"
    capabilities: ClassVar[frozenset[str]] = frozenset({CONTINUOUS_SAMPLES})

    def materialize(
        self,
        capability_key: str,
        ctx: HealthCheckContext,
        config: dict[str, Any] | None = None,
    ) -> HealthView:
        decoded = ctx.load_evaluation_payload()
        if not isinstance(decoded, dict):
            raise TypeError(
                "synthetic masked-regression evaluation payload must be a mapping; "
                f"got {type(decoded).__name__}."
            )
        samples = np.asarray(
            [
                float(decoded[sample_id]["prediction"])
                for sample_id in sorted(decoded)
                if bool(decoded[sample_id]["valid"])
            ],
            dtype=np.float32,
        )
        return HealthView(
            capability_key=capability_key,
            provider_id=self.provider_id,
            payload=ContinuousSamplesPayload(samples=samples),
        )


register_view_provider(MaskedRegressionHealthViews())
