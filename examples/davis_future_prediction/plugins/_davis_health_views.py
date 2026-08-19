# examples/davis_future_prediction/plugins/_davis_health_views.py
"""The DAVIS pack's Health view provider (Step 08c C4).

Registers through the SAME public interface an out-of-tree task uses —
imports only the health package's public surface, is loaded ONLY through
the pack's ``declared/task_health.yaml`` explicit ``kind: file`` ref, and
its content digest joins the pinned run identity. Underscore-prefixed so
no wholesale ``plugins/`` scan ever execs it.

**The FULL decoded view (frozen §3.5 semantics).** The projection is

    sorted clip keys → per-clip ``ravel()`` → one concatenated 1-D array

in the artifact's NATIVE floating dtype (float32 for the real npz — no
upcast is performed or claimed here). No prefix cap, no sampling: a
partial view would make dispersion depend on flatten ordering, and any
future sampling policy is a frozen-semantics change. Numerical estimator
precision (float64 accumulation) is owned by the CONSUMING CHECK, not by
this projection (§3.5a).

**Codec ownership honesty (§2.12).** This is a narrow pack-local
projection of the pack's OWN deliverable format (one compressed npz of
``{clip_key: float32 array}``). The production reader is
``execute_tools/davis_data_path.py``; the mandatory codec-parity
regression asserts both readers agree on the same bytes.
"""

from __future__ import annotations

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


def project_full_sample_stream(path: Path) -> np.ndarray:
    """The pack-local projection: deliverable npz → the FULL 1-D stream.

    Raises (→ provider ERROR, §3.2a) on a missing/corrupt file or on
    clips of unequal shape — a structurally malformed artifact cannot be
    honestly projected as "the deliverable's sample stream". An npz with
    zero clips decodes to an EMPTY stream: the artifact WAS read, and the
    consuming check rules emptiness (ERROR) itself.
    """
    if not path.is_file():
        raise FileNotFoundError(f"DAVIS deliverable not found: {path}")
    with np.load(path) as handle:
        keys = sorted(handle.files)
        clips = {key: handle[key] for key in keys}
    shapes = {clips[key].shape for key in keys}
    if len(shapes) > 1:
        raise ValueError(
            f"{path} carries clips of unequal shape {sorted(shapes)}; a "
            f"structurally inconsistent deliverable cannot be projected as "
            f"one sample stream."
        )
    if not keys:
        return np.array([], dtype=np.float32)
    return np.concatenate([clips[key].ravel() for key in keys])


class DavisSampleViews:
    """Exposes the deliverable's full sample stream as the standard view."""

    provider_id: ClassVar[str] = "davis.sample_views"
    capabilities: ClassVar[frozenset[str]] = frozenset({CONTINUOUS_SAMPLES})

    def materialize(
        self,
        capability_key: str,
        ctx: HealthCheckContext,
        config: dict[str, Any] | None = None,
    ) -> HealthView:
        path = ctx.get_denoised_path(0)
        if path is None:
            raise FileNotFoundError(
                "no produced-artifact path in the health context (denoised slot 0 is empty)"
            )
        samples = project_full_sample_stream(Path(path))
        return HealthView(
            capability_key=capability_key,
            provider_id=self.provider_id,
            payload=ContinuousSamplesPayload(samples=samples),
        )


register_view_provider(DavisSampleViews())
