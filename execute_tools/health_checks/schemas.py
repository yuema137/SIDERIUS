# execute_tools/health_checks/schemas.py
"""
Typed schemas for the pluggable HealthGate framework.

Rev-6 HealthGate schemas: HealthCheckContext (round-scoped, no phase),
HealthCheckResult, GateResult, GateAction. See
``docs/design/pluggable_health_checks.md`` for the full design.

Migration completed in commit-6: the pre-migration ``HealthCheckOutput``
and ``HealthCheckPanelOutput`` classes were removed (no consumers
remained). ``HealthCheckResult.passed`` is the direct successor to the
old ``HealthCheckOutput.is_degenerate`` field, with inverted polarity —
see ``HealthCheckResult`` docstring.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# GateAction — routing verdict enum
# ---------------------------------------------------------------------------


class GateAction(StrEnum):
    """Actions a HealthGate can route to on pass or fail.

    See ``docs/design/pluggable_health_checks.md`` §4 for semantics.
    """

    CONTINUE = "continue"
    """Proceed normally. Next round runs, or iter closes if this was the
    last round — the tuner decides based on its own phase knowledge."""

    SKIP_ITER = "skip_iter"
    """Abort the current iteration. Move to the next iteration."""

    SKIP_TO_FORMAL = "skip_to_formal"
    """Skip remaining trial rounds. Jump to formal phase."""

    INVALIDATE_ROUND = "invalidate_round"
    """Mark this round's score as None. Continue to the next round."""


# ---------------------------------------------------------------------------
# HealthCheckContext — inputs shared by all skills
# ---------------------------------------------------------------------------


class HealthCheckContext(BaseModel):
    """Shared context passed to every health check skill.

    Checks read what they need. A check that operates on aggregated
    per-file magnitudes reads ``file_vector``; a check that peeks the
    denoised HDF5 uses ``denoised_paths`` or the lazy
    ``denoised_filename_fn``. A check has no obligation to consume any
    specific field — it is expected to introspect the context and skip
    gracefully when its inputs are absent.

    D2 note (migration decision): no raw in-memory int8 array field.
    The denoised output only exists on disk (in HDF5 files) after the
    ``inference_single.py`` subprocess terminates; eager-loading ~40 GB
    of int8 buffers is not viable. Checks that need the raw bytes read
    them lazily via ``get_denoised_path``.
    """

    model_config = {"arbitrary_types_allowed": True}

    # --- Identity — required ---
    model_name: str = Field(
        description=(
            "Plugin model identifier (e.g. ``wavenet_loss_screen_v17``). "
            "At the tuner call site this is what the codebase calls "
            "``model_type``; the design doc uses ``model_name`` as the "
            "eventual naming convention."
        ),
    )
    run_name: str = Field(
        description=(
            "Tuner ``storage_local.run_name`` — surfaced in check metrics and gate result logging."
        ),
    )
    round_index: int = Field(
        description=(
            "Which round produced this context (1-based). Gate config "
            "keys off this via ``after_round`` in health_checks.yaml. "
            "Phase concepts (pretrial/finetrial/formal) are tuner-level "
            "concerns, not HealthGate concerns."
        ),
    )

    # --- Identity — optional workflow-level index (D3) ---
    iter_num: int | None = Field(
        default=None,
        description=(
            "Workflow-level iteration number (e.g. iter_015 in a chain). "
            "None while the tuner does not yet plumb this through "
            "HyperparamTuningInput; plumbing is deferred to commit-5 "
            "of the migration."
        ),
    )

    # --- Output data — checks use what they need ---
    denoised_paths: dict[int, str] = Field(
        default_factory=dict,
        description=(
            "file_index → filename of the denoised HDF5 for that file. "
            "Empty when the caller has no eagerly-materialised paths — "
            "checks fall back to ``denoised_filename_fn`` if provided."
        ),
    )
    denoised_filename_fn: Callable[[int], str] | None = Field(
        default=None,
        description=(
            "Optional lazy filename constructor: file_index → filename. "
            "Preferred over ``denoised_paths`` on the scoring hot path "
            "because it avoids eagerly building a 20-entry dict when "
            "only one file is peeked. Excluded from JSON serialisation "
            "— the context is a transport within one process, never "
            "persisted."
        ),
        exclude=True,
    )

    # --- Scoring context (available at gates triggered after scoring) ---
    file_vector: list[float | None] = Field(
        default_factory=list,
        description=(
            "Per-file PSD magnitudes from the current scoring run. None "
            "entries mark files outside the sample set. Post-scoring "
            "checks read this; pre-scoring checks do not."
        ),
    )
    denoising_score: float | None = Field(
        default=None,
        description=(
            "Final scalar denoising score for this round (if scoring has "
            "run). None at pre-scoring gates."
        ),
    )

    def get_denoised_path(self, file_index: int) -> str | None:
        """Resolve the denoised HDF5 filename for one file_index.

        Order of preference:
          1. Explicit entry in ``denoised_paths``.
          2. Lazy construction via ``denoised_filename_fn``.
          3. None when neither can produce a filename.
        """
        if file_index in self.denoised_paths:
            return self.denoised_paths[file_index]
        if self.denoised_filename_fn is not None:
            return self.denoised_filename_fn(file_index)
        return None


# ---------------------------------------------------------------------------
# HealthCheckResult — one check's verdict
# ---------------------------------------------------------------------------


class HealthCheckResult(BaseModel):
    """Result from one health check skill.

    Semantics are inverted from the pre-migration ``HealthCheckOutput``:
    ``passed=True`` means "output is healthy" (was ``is_degenerate=False``);
    ``passed=False`` means "flagged" (was ``is_degenerate=True``). This
    inversion aligns with the rev-6 gate model where ``on_pass`` / ``on_fail``
    are the branching semantics.
    """

    check_name: str = Field(
        description=(
            "Registered name of the check that produced this result — "
            "matches the check class's ``name: ClassVar[str]``."
        ),
    )
    passed: bool = Field(
        description="True when the check flagged no degeneracy.",
    )
    reason: str = Field(
        default="",
        description=(
            "Human-readable + machine-parseable failure reason. Empty "
            "string when ``passed`` is True. Format: "
            "``'{check_name}: {details with numbers}'``."
        ),
    )
    metrics: dict[str, float | int | str] = Field(
        default_factory=dict,
        description=(
            "Structured metrics from the check (unique_count=1, "
            "dominant_fraction=0.98). Used by the tuner's memory format "
            "and by the Run Monitor's cross-iter policy."
        ),
    )


# ---------------------------------------------------------------------------
# GateResult — one gate's routing verdict
# ---------------------------------------------------------------------------


class GateResult(BaseModel):
    """Result from one HealthGate evaluation.

    ``action`` is the resolved routing outcome — the gate's ``on_pass``
    action when all checks passed, or its ``on_fail`` action when any
    check failed (short-circuit). See design doc §4 for action semantics
    and §8 for the runner logic including severity resolution when
    multiple gates fire at the same round.
    """

    gate_id: str = Field(
        description="The gate's id from ``configs/health_checks.yaml``.",
    )
    round_index: int = Field(
        description=(
            "Which round triggered this gate (propagated from "
            "``ctx.round_index`` at evaluation time). Used for logging "
            "and by the Run Monitor's cross-round policy."
        ),
    )
    passed: bool = Field(
        description=(
            "True when every check inside this gate passed. False when "
            "any check failed (the gate short-circuits on the first "
            "failure)."
        ),
    )
    action: GateAction = Field(
        description=(
            "Resolved routing action — the ``on_pass`` action when "
            "``passed`` is True, otherwise the ``on_fail`` action."
        ),
    )
    check_results: list[HealthCheckResult] = Field(
        default_factory=list,
        description=(
            "Every check that ran, in the order the gate config listed "
            "them. Stops at the first failure (short-circuit)."
        ),
    )
    failure_reason: str = Field(
        default="",
        description=(
            "The ``reason`` from the first failing check. Empty string when ``passed`` is True."
        ),
    )

    @property
    def should_skip_iter(self) -> bool:
        return self.action == GateAction.SKIP_ITER

    @property
    def should_skip_to_formal(self) -> bool:
        return self.action == GateAction.SKIP_TO_FORMAL

    @property
    def should_invalidate_round(self) -> bool:
        return self.action == GateAction.INVALIDATE_ROUND
