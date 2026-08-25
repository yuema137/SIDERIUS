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

import time
from collections.abc import Sequence
from typing import TYPE_CHECKING

import torch
import torch.nn as nn

from agent.skills.evaluate_vram_skill import compute_intensity
from agent.skills.evaluate_vram_skill.overhead import cuda_context_bytes
from agent.skills.evaluate_vram_skill.probe_budgets import (
    ProbeBudgets,
    ProbeTimeoutRecord,
    is_memory_exception,
)
from agent.skills.evaluate_vram_skill.structural_probe import (
    ProbeResult,
    probe_activation_footprint,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from agent.schemas.model_io_contract import ModelIOContract

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


def _build_probe_input(
    batch_size: int,
    segmentation_size: int,
    model_io_contract: ModelIOContract | None = None,
) -> torch.Tensor:
    """Zero/contract-valued input matching the candidate's forward contract.

    Legacy (``model_io_contract=None``): the project-wide model contract is
    ``[B, T] int → [B, 256, T] float`` (see ``core/plugin_loader.py``).
    torchinfo traces shape propagation, not values, so zeros are fine.
    ``long`` matches the plugin-embedding signature.

    F-12d-24: when a Model-I/O declaration is bound, the probe is built from
    it instead — contract-shaped and contract-dtyped, at this candidate's
    real batch size — through the same Step-04/05b recipe authority
    ``evaluate_vram_skill.wrapper._probe_input_tensor`` uses, so the search
    probes the same tensor a real forward would receive.
    """
    if model_io_contract is not None:
        from agent.skills.model_io_probe_skill import build_model_input

        return build_model_input(model_io_contract, batch=batch_size, symbolic=segmentation_size)
    return torch.zeros((batch_size, segmentation_size), dtype=torch.long)


# ── Public entry point ──────────────────────────────────────────────────────


class BatchSearchTimeout(Exception):
    """A bounded step of the batch search ran out of time.

    Carries the typed record rather than a message, because the caller
    must be able to tell "this did not finish" from "this model does not
    fit" WITHOUT parsing prose.
    """

    def __init__(self, record: ProbeTimeoutRecord):
        self.record = record
        super().__init__(record.agent_facing_summary())


def resolve_inference_batch(
    model: nn.Module,
    segmentation_size: int,
    cap_bytes: int,
    *,
    candidate_batches: Sequence[int] = _DEFAULT_CANDIDATE_BATCHES,
    budgets: ProbeBudgets | None = None,
    model_identity: str | None = None,
    model_io_contract: ModelIOContract | None = None,
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

    last_peak: int = 0
    last_vram_ok: bool = False
    last_intensity_ok: bool = False
    last_B: int = candidate_batches[-1]

    # Each candidate is timed on its own, and the search has its own
    # separate budget. Sharing one budget across every candidate is what
    # made a seven-step search indistinguishable from one pathological
    # forward, and turned an unfinished inspection into a "model too
    # large" verdict (V19 campaign stopped 2026-07-31).
    budgets = budgets or ProbeBudgets()
    search_started = time.monotonic()

    for B in candidate_batches:
        search_elapsed = time.monotonic() - search_started
        if search_elapsed >= budgets.batch_search_seconds:
            raise BatchSearchTimeout(
                ProbeTimeoutRecord(
                    operation="batch_search",
                    budget_seconds=budgets.batch_search_seconds,
                    elapsed_seconds=round(search_elapsed, 3),
                    search_elapsed_seconds=round(search_elapsed, 3),
                    candidate_batch=B,
                    phase="inference_batch_resolution",
                    model_identity=model_identity or type(model).__name__,
                    realized_parameter_count=sum(q.numel() for q in model.parameters()),
                    device=str(next(model.parameters()).device)
                    if any(True for _ in model.parameters())
                    else "cpu",
                    disposition="inconclusive",
                )
            )

        candidate_started = time.monotonic()
        try:
            probe = probe_activation_footprint(
                model=model,
                loss_module=None,
                input_sample=_build_probe_input(B, segmentation_size, model_io_contract),
                target_sample=None,
                mode="inference",
            )
        except (MemoryError, RuntimeError) as exc:
            # A candidate that cannot even be PROBED at this batch is not a
            # verdict on the model — it is a verdict on this batch. The
            # search exists to find the largest batch that works, so it
            # continues to the next smaller one.
            #
            # This matters more than it looks. The list is DESCENDING, so
            # B=64 is tried first, and for a quadratic-attention model at
            # T=8000 that single attention matrix is 61 GiB
            # (64 x 4 heads x 8000 x 8000 x 4 bytes). On 2026-07-31 that
            # allocation took the whole host down at 57.7 GiB anon-rss —
            # a model that would have probed fine at B=8 was never reached.
            if not is_memory_exception(exc):
                raise
            last_peak, last_vram_ok, last_intensity_ok, last_B = 0, False, True, B
            continue
        candidate_elapsed = time.monotonic() - candidate_started
        if candidate_elapsed >= budgets.single_candidate_seconds:
            # **F-12a-G2** (Step 12 / PR-12a, Gate-exposed). This branch USED
            # to raise `BatchSearchTimeout` here and discard `probe`. That was
            # wrong in the same way this module's own docstring says the V19
            # 60-second alarm was wrong, one level down:
            #
            #   * `probe_activation_footprint` has already RETURNED. The
            #     measurement exists. Nothing was interrupted and nothing
            #     hung — a hung probe never reaches this line at all, so the
            #     check could never have been the hang protection it looked
            #     like.
            #   * The elapsed time is a CPU wall-clock duration (the probe
            #     traces a CPU-instantiated model), so it moves with host
            #     load. Rule 2 above: only a MEASURED result may reject a
            #     candidate for capacity. "The same configuration both failed
            #     and passed depending on CPU load, which is what proves it
            #     was never a capacity signal."
            #
            # Observed live: a 191.7 s completed probe on a 24-core host at
            # load ~10 was thrown away against a 120 s budget calibrated on
            # the same machine UNCONTENDED, and the tuner burned attempt after
            # attempt on it.
            #
            # So the budget keeps its real job — flagging a slow probe for
            # calibration — and loses the one it should never have had.
            # Bounding a probe that has NOT returned is a genuine watchdog and
            # a different mechanism (`ForwardPassTimeoutError` already exists
            # for that); it is deliberately not built here.
            print(
                f"!!! [VRAMEval] SLOW PROBE (accepted): candidate batch {B} "
                f"took {candidate_elapsed:.1f}s against a "
                f"{budgets.single_candidate_seconds:.0f}s calibration budget. "
                f"The measurement COMPLETED and is used; elapsed wall time is "
                f"host-load-dependent and is not capacity evidence (F-12a-G2)."
            )
        peak = _predict_inference_peak_bytes(probe)
        vram_ok = peak <= cap_bytes
        intensity_ok = compute_intensity.passes(B, segmentation_size)

        if vram_ok and intensity_ok:
            return B

        last_peak = peak
        last_vram_ok = vram_ok
        last_intensity_ok = intensity_ok
        last_B = B

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
