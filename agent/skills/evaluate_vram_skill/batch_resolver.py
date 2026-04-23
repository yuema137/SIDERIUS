"""Inference batch auto-selection — Phase 6.6 §3.5.

Replaces the deprecated ``_INFERENCE_BATCH_SIZES`` table with a probe-driven
search. Given a CPU-instantiated model and a VRAM cap, iterate candidate
batch sizes from largest to smallest; accept the first that satisfies BOTH
of the Phase 6.6 caps:

  (1) Predicted peak VRAM ≤ ``cap_bytes`` — from the structural probe plus
      the calibrated CUDA-context term (``overhead.cuda_context_bytes``).
  (2) ``compute_intensity.passes(B, segmentation_size)`` — §3.10's CUDA
      kernel-watchdog heuristic. A batch that fits VRAM but violates
      intensity is skipped just as firmly as one that blows the cap.

If no candidate satisfies both caps, raise ``ValueError`` whose diagnostic
names the binding cap ("vram", "compute_intensity", or both) at the
smallest candidate — downstream ``killer_report.py`` (§3.6) keys on this
distinction to steer the Proposer's next attempt toward the right fix.

Why descending search over closed form (§3.5 rationale)
-------------------------------------------------------
Activation memory is linear in B for most layers but quadratic for attention
(``B × nhead × T² × 4``). A closed-form solver would need to know the
dominant term, which is exactly the model-name branching Phase 6.6
eliminates. A 7-point probe is ~7× cheap CPU forward passes on a mock
input — the resulting choice is provably correct against the torchinfo
model for whatever architecture the Proposer hands us.

Principle 2 invariant
---------------------
This module reads no model-type strings. It probes whatever ``nn.Module``
it is handed and ranks by bytes and intensity only. The guardrail test
``tests/unit/guardrails/test_no_model_name_branches.py`` (A.12) enforces
the invariant across the whole VRAM stack.
"""
from __future__ import annotations

from typing import Sequence

import torch
import torch.nn as nn

from agent.skills.evaluate_vram_skill import compute_intensity
from agent.skills.evaluate_vram_skill.overhead import cuda_context_bytes
from agent.skills.evaluate_vram_skill.structural_probe import (
    ProbeResult,
    probe_activation_footprint,
)


# ── Candidate search space (§3.5 — descending powers of two down to 1) ─────

_DEFAULT_CANDIDATE_BATCHES: tuple[int, ...] = (64, 32, 16, 8, 4, 2, 1)


# ── Peak prediction ─────────────────────────────────────────────────────────

def _predict_inference_peak_bytes(probe: ProbeResult) -> int:
    """Sum the inference-mode peak components per §3.5.

    ``peak = params_bytes + forward_activation_bytes + cuda_context_bytes()``

    ``forward_output_bytes_sum`` is the conservative upper bound on transient
    activation memory — the allocator does reuse buffers under
    ``torch.no_grad``, so the true peak is typically lower. We prefer
    refusals to false accepts for a pre-flight gate; the looser (max-only)
    bound would risk approving a config that OOMs in the sandbox.
    """
    return (
        probe.model_forward.total_param_bytes
        + probe.model_forward.forward_output_bytes_sum
        + cuda_context_bytes()
    )


def _build_probe_input(batch_size: int, segmentation_size: int) -> torch.Tensor:
    """Zero-valued int64 input matching the SIDERIUS forward contract.

    The project-wide model contract is ``[B, T] int → [B, 256, T] float``
    (see ``core/plugin_loader.py``). torchinfo traces shape propagation, not
    values, so zeros are fine. ``long`` matches the plugin-embedding signature.
    """
    return torch.zeros((batch_size, segmentation_size), dtype=torch.long)


# ── Public entry point ──────────────────────────────────────────────────────

def resolve_inference_batch(
    model: nn.Module,
    segmentation_size: int,
    cap_bytes: int,
    *,
    candidate_batches: Sequence[int] = _DEFAULT_CANDIDATE_BATCHES,
) -> int:
    """Return the largest candidate batch that clears both caps.

    Args:
        model: CPU-instantiated ``nn.Module``. Probed with zero-valued
            int64 inputs of shape ``(B, segmentation_size)``.
        segmentation_size: time-axis length T.
        cap_bytes: usable VRAM budget, in bytes. Callers typically pass
            ``HardwareContext.usable_cap_bytes`` (see §3.9.1).
        candidate_batches: descending sequence of batch sizes to try. Must
            be non-empty. The **last** element is the fallback — if that
            fails, the raised ``ValueError`` diagnoses why.

    Returns:
        The first (largest) ``B`` for which
        ``predicted_peak ≤ cap_bytes`` AND ``compute_intensity.passes(B, T)``.

    Raises:
        ValueError: when no candidate satisfies both caps, or when
            ``candidate_batches`` is empty. The message names the binding
            cap — "vram", "compute_intensity", or "vram+compute_intensity"
            — so ``killer_report`` can emit a targeted suggestion.
    """
    if not candidate_batches:
        raise ValueError("candidate_batches must be non-empty.")

    last_peak:         int = 0
    last_vram_ok:      bool = False
    last_intensity_ok: bool = False
    last_B:            int = candidate_batches[-1]

    for B in candidate_batches:
        probe = probe_activation_footprint(
            model=model,
            loss_module=None,
            input_sample=_build_probe_input(B, segmentation_size),
            target_sample=None,
            mode="inference",
        )
        peak         = _predict_inference_peak_bytes(probe)
        vram_ok      = peak <= cap_bytes
        intensity_ok = compute_intensity.passes(B, segmentation_size)

        if vram_ok and intensity_ok:
            return B

        last_peak         = peak
        last_vram_ok      = vram_ok
        last_intensity_ok = intensity_ok
        last_B            = B

    # Diagnose which cap was binding at the smallest attempted batch. Both
    # can be binding simultaneously (e.g. a huge T both blows VRAM and trips
    # the intensity cap even at B=1) — report both in that case so
    # killer_report can surface two suggestions.
    reasons: list[str] = []
    if not last_vram_ok:
        reasons.append("vram")
    if not last_intensity_ok:
        reasons.append("compute_intensity")
    binding = "+".join(reasons) if reasons else "unknown"

    raise ValueError(
        f"No candidate batch in {list(candidate_batches)} satisfies both caps "
        f"at segmentation_size={segmentation_size}. "
        f"Binding cap(s): {binding}. "
        f"At B={last_B}: predicted_peak={last_peak:,} B, "
        f"cap_bytes={cap_bytes:,} B, "
        f"compute_intensity_passes={last_intensity_ok}. "
        f"If binding includes 'vram', reduce model size or segmentation_size; "
        f"if binding includes 'compute_intensity', reduce segmentation_size "
        f"or batch_size."
    )
