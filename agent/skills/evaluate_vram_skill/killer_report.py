"""Memory Killer report — Phase 6.6 §3.6 + §3.10.2.

When the pre-flight gate refuses a config, the wrapper needs a structured
attribution payload for the Proposer's next attempt. This module is the
single place that renders that payload, covering both failure modes
introduced in Phase 6.6:

  - **VRAM over-budget** (§3.6). Consumes the probe's per-leaf breakdown,
    identifies the single dominant layer by ``output_bytes``, and emits a
    suggestion that names *that specific layer by its user-given name* plus
    a concrete dimension to reduce — never a model family, never a layer
    class. The Proposer must then revise its next attempt's
    ``mathematical_definition`` around that layer.

  - **Compute-intensity over-budget** (§3.10.2). Intensity is a config-shape
    problem, not an architecture problem. The suggestion names only
    ``batch_size`` and ``segmentation_size`` — no layer references. Reuses
    ``compute_intensity.describe_violation`` so the wording stays in one
    place.

  - **Both caps binding** — rare but possible for a training config that
    both OOMs and exceeds the watchdog product. The combined renderer
    fills both halves of the ``memory_killer`` dict so ``killer_report``
    surfaces every binding constraint simultaneously.

Principle 2 invariant
---------------------
This module reads no model-type strings and produces no architecture-family
terms in any suggestion string. The guardrail test
``tests/unit/guardrails/test_no_model_name_branches.py`` (A.12) enforces
this across the whole VRAM stack; the inline test in
``test_killer_report.py`` documents the invariant at the module.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agent.skills.evaluate_vram_skill import compute_intensity
from agent.skills.evaluate_vram_skill.structural_probe import LayerReport, ProbeResult

# ── Pydantic contracts ──────────────────────────────────────────────────────

_BindingCap = Literal["vram", "compute_intensity", "vram+compute_intensity"]


class PerLayerEntry(BaseModel):
    """One row of the ``memory_killer.per_layer`` breakdown. One entry per
    leaf layer in the probed model — non-leaf containers would double-count."""

    model_config = ConfigDict(frozen=True)

    name: str
    class_name: str
    output_shape: list[int]
    bytes: int


class MemoryKillerDetails(BaseModel):
    """Structured attribution fed to the Proposer via the wrapper's
    ``memory_killer`` return key. The set of populated fields depends on
    ``binding_cap``: VRAM branches fill ``dominant_*`` + ``per_layer``,
    intensity branches fill ``batch_size`` / ``segmentation_size`` /
    ``intensity_*``, and the combined branch fills both halves."""

    model_config = ConfigDict(frozen=True)

    binding_cap: _BindingCap

    # ── VRAM attribution (populated when binding_cap includes "vram") ──
    dominant_layer: str | None = None
    dominant_layer_class: str | None = None
    dominant_layer_bytes: int | None = None
    dominant_fraction: float | None = None
    per_layer: list[PerLayerEntry] = Field(default_factory=list)

    # ── Intensity attribution (populated when binding_cap includes ↓) ──
    batch_size: int | None = None
    segmentation_size: int | None = None
    intensity_product: int | None = None
    intensity_cap: int | None = None


class KillerReport(BaseModel):
    """Full verdict payload. The wrapper flattens this into its own return
    dict per §3.7, so ``verdict`` / ``memory_killer`` / ``suggestion``
    become top-level keys in the Proposer-facing response.

    Deliberately carries NO transport ``status`` field: the report is a
    feasibility *verdict/attribution* payload, and the wrapper's transport
    status for an over-budget verdict is ``"success"`` (the skill ran fine;
    the verdict is ``feasible=False``). A previous hardcoded
    ``status="schema_violation"`` here was passed through by the wrapper's
    infeasible path, which made the tuner's Phase-D.4 branch swallow every
    over-budget verdict as ``skipped_schema_violation`` — silently starving
    the ``skipped_oom_risk`` path, the B.3 PhysicalRejection buffer, the
    K.7 gate-exhaustion triggers, and the Phase-K record fields
    (2026-05 → 2026-07 regression; see the status-flow audit in the
    2026-07-23 bugfix commit). ``"schema_violation"`` is reserved for real
    ``ValidationError``s via ``_schema_violation_response``.
    """

    model_config = ConfigDict(frozen=True)

    verdict: str
    memory_killer: MemoryKillerDetails
    suggestion: str


# ── Internal helpers ────────────────────────────────────────────────────────


def _format_bytes(b: int) -> str:
    """Render a byte count as ``X.Y GB`` for verdict strings."""
    return f"{b / 1024**3:.1f} GB"


def _leaf_layers(probe: ProbeResult) -> list[LayerReport]:
    return [layer for layer in probe.model_forward.layers if layer.is_leaf]


def _dominant_leaf(probe: ProbeResult) -> LayerReport | None:
    """Return the leaf layer with the largest ``output_bytes``, or ``None``
    if the probe has no leaves (degenerate — a wrapper nn.Module with no
    submodules). A ``None`` return switches the VRAM suggestion to its
    whole-model phrasing."""
    leaves = _leaf_layers(probe)
    if not leaves:
        return None
    return max(leaves, key=lambda layer: layer.output_bytes)


def _per_layer_entries(probe: ProbeResult) -> list[PerLayerEntry]:
    return [
        PerLayerEntry(
            name=layer.var_name,
            class_name=layer.class_name,
            output_shape=layer.output_shape,
            bytes=layer.output_bytes,
        )
        for layer in _leaf_layers(probe)
    ]


# ── VRAM-over-budget renderer (§3.6) ───────────────────────────────────────


def render_vram_report(
    probe: ProbeResult,
    predicted_peak_bytes: int,
    cap_bytes: int,
    total_memory_bytes: int,
) -> KillerReport:
    """Build the full verdict for a VRAM-cap failure.

    Args:
        probe: ProbeResult from ``structural_probe.probe_activation_footprint``
               — its leaf-layer breakdown drives the attribution.
        predicted_peak_bytes: the peak the estimator forecast (bytes).
        cap_bytes: the usable VRAM cap (bytes).
        total_memory_bytes: the device's total memory (bytes) — used only
               to render the "(X% of Y GB)" qualifier in the verdict.
    """
    per_layer = _per_layer_entries(probe)
    dom = _dominant_leaf(probe)

    cap_pct = 100 * cap_bytes / total_memory_bytes if total_memory_bytes else 0
    verdict = (
        f"❌ OVER-BUDGET (VRAM) — estimated "
        f"{_format_bytes(predicted_peak_bytes)} > cap "
        f"{_format_bytes(cap_bytes)} "
        f"({cap_pct:.0f}% of {_format_bytes(total_memory_bytes)})."
    )

    if dom is not None and predicted_peak_bytes > 0:
        frac = dom.output_bytes / predicted_peak_bytes
        details = MemoryKillerDetails(
            binding_cap="vram",
            dominant_layer=dom.var_name,
            dominant_layer_class=dom.class_name,
            dominant_layer_bytes=dom.output_bytes,
            dominant_fraction=round(frac, 4),
            per_layer=per_layer,
        )
        suggestion = (
            f"Layer '{dom.var_name}' accounts for {frac * 100:.0f}% of "
            f"estimated VRAM. Reduce its output tensor size — e.g. shrink "
            f"the channel dimension, shorten segmentation_size, or replace "
            f"the quadratic term with a linear-complexity alternative."
        )
    else:
        details = MemoryKillerDetails(binding_cap="vram", per_layer=per_layer)
        suggestion = (
            "No single leaf layer dominates the estimate — the whole model "
            "exceeds the cap. Reduce total parameter count or shorten "
            "segmentation_size."
        )

    return KillerReport(verdict=verdict, memory_killer=details, suggestion=suggestion)


# ── Compute-intensity-over-budget renderer (§3.10.2) ───────────────────────


def render_intensity_report(batch_size: int, segmentation_size: int) -> KillerReport:
    """Build the full verdict for a compute-intensity cap failure.

    Does NOT reference any layer — intensity is a config-shape problem,
    not an architecture problem. Suggestion text is delegated to
    ``compute_intensity.describe_violation`` so the wording stays in one
    place.
    """
    product = compute_intensity.compute_intensity(batch_size, segmentation_size)
    cap = compute_intensity._MAX_BATCH_TIMESTEPS

    verdict = (
        f"❌ OVER-BUDGET (Compute-intensity) — "
        f"batch_size × segmentation_size = {product:,} > cap {cap:,}."
    )
    details = MemoryKillerDetails(
        binding_cap="compute_intensity",
        batch_size=batch_size,
        segmentation_size=segmentation_size,
        intensity_product=product,
        intensity_cap=cap,
    )
    suggestion = compute_intensity.describe_violation(batch_size, segmentation_size)
    return KillerReport(verdict=verdict, memory_killer=details, suggestion=suggestion)


# ── Combined-binding renderer (both caps) ───────────────────────────────────


def render_combined_report(
    probe: ProbeResult,
    predicted_peak_bytes: int,
    cap_bytes: int,
    total_memory_bytes: int,
    batch_size: int,
    segmentation_size: int,
) -> KillerReport:
    """Build the verdict for the rare case where BOTH caps fail.

    Populates every field of ``MemoryKillerDetails`` so the Proposer sees
    both failure modes at once. Suggestion concatenates the VRAM and
    intensity advice — the Proposer must address both before the next
    attempt will pass the gate.
    """
    vram_rep = render_vram_report(
        probe,
        predicted_peak_bytes,
        cap_bytes,
        total_memory_bytes,
    )
    product = compute_intensity.compute_intensity(batch_size, segmentation_size)
    cap = compute_intensity._MAX_BATCH_TIMESTEPS

    details = MemoryKillerDetails(
        binding_cap="vram+compute_intensity",
        dominant_layer=vram_rep.memory_killer.dominant_layer,
        dominant_layer_class=vram_rep.memory_killer.dominant_layer_class,
        dominant_layer_bytes=vram_rep.memory_killer.dominant_layer_bytes,
        dominant_fraction=vram_rep.memory_killer.dominant_fraction,
        per_layer=vram_rep.memory_killer.per_layer,
        batch_size=batch_size,
        segmentation_size=segmentation_size,
        intensity_product=product,
        intensity_cap=cap,
    )
    verdict = (
        f"❌ OVER-BUDGET (VRAM + Compute-intensity) — estimated "
        f"{_format_bytes(predicted_peak_bytes)} > cap "
        f"{_format_bytes(cap_bytes)}, AND "
        f"batch_size × segmentation_size = {product:,} > cap {cap:,}."
    )
    suggestion = (
        f"{vram_rep.suggestion} "
        f"Additionally: "
        f"{compute_intensity.describe_violation(batch_size, segmentation_size)}"
    )
    return KillerReport(verdict=verdict, memory_killer=details, suggestion=suggestion)
