# examples/oxford_iiit_pet/plugins/_pets_health_views.py
"""The Pets pack's Health view provider (Step 08c C3).

Registers through the SAME public interface an out-of-tree task uses —
imports only the health package's public surface, is loaded ONLY through
the pack's ``declared/task_health.yaml`` explicit ``kind: file`` ref, and
its content digest joins the pinned run identity.

Underscore-prefixed on purpose: both generic directory scanners (the ML
plugin loader and the Health directory-kind loader) skip ``_``-prefixed
members, so this module can never be executed as a side effect of a
wholesale ``plugins/`` scan — the explicit ref above is its only path in.

**Codec ownership honesty (§2.12).** This is a narrow pack-local
projection of the pack's OWN deliverable format (one CSV, header
``image_id,predicted_class_index``). The production reader is
``execute_tools/pets_data_path.py``; the mandatory codec-parity regression
asserts both readers agree on the same bytes, so a format change cannot
leave one silently accepting a different artifact than the other.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from execute_tools.health_checks import (
    CATEGORICAL_PREDICTIONS,
    CategoricalPredictionsPayload,
    HealthView,
    register_view_provider,
)
from execute_tools.health_checks.schemas import HealthCheckContext

_EXPECTED_HEADER = "image_id,predicted_class_index"


def project_predictions(path: Path) -> dict[str, int]:
    """The pack-local projection: deliverable CSV → ``{image_id: class}``.

    Raises (→ provider ERROR, §3.2a) on a missing file or a wrong header —
    an unreadable artifact is inability to compute, never a verdict. An
    empty prediction table decodes to ``{}``: the artifact WAS read, and
    the consuming check rules emptiness (ERROR) itself.
    """
    if not path.is_file():
        raise FileNotFoundError(f"Pets deliverable not found: {path}")
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != _EXPECTED_HEADER:
        raise ValueError(
            f"{path} is not a Pets classification deliverable "
            f"(expected header {_EXPECTED_HEADER!r})."
        )
    payload: dict[str, int] = {}
    for line in lines[1:]:
        if not line.strip():
            continue
        image_id, pred = line.split(",")
        payload[image_id] = int(pred)
    return payload


class PetsPredictionViews:
    """Exposes the deliverable's predicted classes as the standard stream."""

    provider_id: ClassVar[str] = "pets.prediction_views"
    capabilities: ClassVar[frozenset[str]] = frozenset({CATEGORICAL_PREDICTIONS})

    def materialize(
        self,
        capability_key: str,
        ctx: HealthCheckContext,
        config: dict[str, Any] | None = None,
    ) -> HealthView:
        payload = ctx.load_evaluation_payload()
        if not isinstance(payload, Mapping):
            raise TypeError(
                "Pets evaluation payload must map image ids to predicted class indices; "
                f"got {type(payload).__name__}."
            )
        by_image = {str(key): int(value) for key, value in payload.items()}
        # Sorted by image_id for a deterministic stream; the checks compute
        # order-invariant statistics, so determinism is for evidence
        # reproducibility, not arithmetic.
        symbols = np.array([by_image[k] for k in sorted(by_image)], dtype=np.int64)
        return HealthView(
            capability_key=capability_key,
            provider_id=self.provider_id,
            payload=CategoricalPredictionsPayload(symbols=symbols),
        )


register_view_provider(PetsPredictionViews())
