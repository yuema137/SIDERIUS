"""Inference batch auto-selection — Phase 6.6 §3.5.

Replaces the deprecated ``_INFERENCE_BATCH_SIZES`` table with a probe-driven
search. Given a CPU-instantiated model and a VRAM cap, iterate candidate
batch sizes from largest to smallest; accept the first that satisfies every
applicable Phase 6.6 cap:

  (1) Predicted peak VRAM ≤ ``cap_bytes`` — from the structural probe plus
      the selected estimation provider and its declared residual terms.
  (2) The selected profile's optional batch/segmentation workload rule,
      only when a segmentation size is declared. Native estimation supplies
      no universal product ceiling. A concrete task-owned probe with no
      temporal dimension is not judged against invented temporal geometry.

If no candidate satisfies both caps, raise ``BatchSearchRefused``, a
``ValueError`` carrying the last candidate's typed decision. Allocation
failures retain their host/CUDA exception domain rather than inventing a
structural VRAM estimate. Callers never need to parse the diagnostic text.

Why descending search over closed form (§3.5 rationale)
-------------------------------------------------------
Activation memory is linear in B for most layers but quadratic for attention
(``B × nhead × T² × 4``). A closed-form solver would need to know the
dominant term, which is exactly the model-name branching Phase 6.6
eliminates. A 7-point probe is ~7× cheap CPU forward passes on a mock
input. Selection follows the chosen structural estimate; it does not establish
an actual GPU peak or guarantee that an accepted model fits.

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
from typing import TYPE_CHECKING, Any

import torch
import torch.nn as nn

from agent.schemas.preflight import StaticPhaseDecision
from agent.skills.evaluate_vram_skill import compute_intensity
from agent.skills.evaluate_vram_skill.estimation_inputs import observe_phase
from agent.skills.evaluate_vram_skill.evidence import phase_decision
from agent.skills.evaluate_vram_skill.probe_budgets import (
    ProbeBudgets,
    ProbeTimeoutRecord,
    is_memory_exception,
)
from agent.skills.evaluate_vram_skill.structural_probe import (
    probe_activation_footprint,
)
from core.preflight_estimation import estimate_phase, preflight_estimation_scope

if TYPE_CHECKING:  # pragma: no cover - typing only
    from agent.schemas.model_io_contract import ModelIOContract

# ── Candidate search space (§3.5 — descending powers of two down to 1) ─────

_DEFAULT_CANDIDATE_BATCHES: tuple[int, ...] = (64, 32, 16, 8, 4, 2, 1)


# ── Peak prediction ─────────────────────────────────────────────────────────


def _build_probe_input(
    batch_size: int,
    segmentation_size: int | None,
    model_io_contract: ModelIOContract | None = None,
    supplied_probe: torch.Tensor | None = None,
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
    if supplied_probe is not None:
        if supplied_probe.ndim == 0 or supplied_probe.shape[0] < 1:
            raise ValueError("supplied probe input must have a batch dimension")
        # A task-owned probe is concrete evidence. Repeat its first example
        # only to test candidate batch sizes; no dimension is inferred from it.
        return supplied_probe[:1].expand((batch_size, *supplied_probe.shape[1:])).clone()
    if segmentation_size is None:
        raise ValueError(
            "segmentation dimension unavailable: inference batch probing needs "
            "a declared segmentation_size or a task-owned probe input"
        )
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


class BatchSearchRefused(ValueError):
    """A completed static decision, with the exact tested batch and values."""

    def __init__(self, decision: StaticPhaseDecision, segmentation_size: int | None):
        self.decision = decision
        binding = "+".join(decision.binding_caps)
        estimate = decision.vram_estimate_bytes
        observation = (
            f"predicted_peak={estimate:,} B"
            if estimate is not None
            else "VRAM footprint not measured"
        )
        super().__init__(
            f"No candidate batch satisfies both caps at segmentation_size={segmentation_size}. "
            f"Binding cap(s): {binding}. At B={decision.batch_size}: {observation}, "
            f"cap_bytes={decision.vram_cap_bytes:,} B, "
            f"compute_intensity_passes={'compute_intensity' not in decision.binding_caps}."
        )


def resolve_inference_batch(
    model: nn.Module,
    segmentation_size: int | None,
    cap_bytes: int,
    *,
    candidate_batches: Sequence[int] = _DEFAULT_CANDIDATE_BATCHES,
    budgets: ProbeBudgets | None = None,
    model_identity: str | None = None,
    model_io_contract: ModelIOContract | None = None,
    max_batch_size: int | None = None,
    supplied_probe: torch.Tensor | None = None,
    training_config: dict[str, Any] | None = None,
) -> int:
    """Compatibility entry point returning the selected batch as an integer.

    Consumers needing admission evidence use :func:`resolve_inference_decision`.
    Static refusals remain catchable as ``ValueError``.
    """
    return resolve_inference_decision(
        model,
        segmentation_size,
        cap_bytes,
        candidate_batches=candidate_batches,
        budgets=budgets,
        model_identity=model_identity,
        model_io_contract=model_io_contract,
        max_batch_size=max_batch_size,
        supplied_probe=supplied_probe,
        training_config=training_config,
    ).batch_size


@preflight_estimation_scope
def resolve_inference_decision(
    model: nn.Module,
    segmentation_size: int | None,
    cap_bytes: int,
    *,
    candidate_batches: Sequence[int] = _DEFAULT_CANDIDATE_BATCHES,
    budgets: ProbeBudgets | None = None,
    model_identity: str | None = None,
    model_io_contract: ModelIOContract | None = None,
    max_batch_size: int | None = None,
    supplied_probe: torch.Tensor | None = None,
    training_config: dict[str, Any] | None = None,
) -> StaticPhaseDecision:
    """Return the largest candidate batch that clears both caps.

    Args:
        model: CPU-instantiated ``nn.Module``. Probed with zero-valued
            int64 inputs of shape ``(B, segmentation_size)``.
        segmentation_size: declared time-axis length T, or ``None`` when a
            supplied concrete probe has no applicable temporal dimension.
        cap_bytes: usable VRAM budget, in bytes. Callers typically pass
            ``HardwareContext.usable_cap_bytes`` (see §3.9.1).
        candidate_batches: descending sequence of batch sizes to try. Must
            be non-empty. The **last** element is the fallback — if that
            fails, the raised ``ValueError`` diagnoses why.

    Returns:
        The exact decision for the first (largest) ``B`` for which
        ``predicted_peak ≤ cap_bytes`` and, when T is declared,
        ``compute_intensity.passes(B, T)``.

    Raises:
        BatchSearchRefused: no candidate satisfies the completed static checks.
        ValueError: invalid candidate list or probe input.
        MemoryError, RuntimeError: the last candidate could not be allocated;
            the original exception preserves its host/CUDA domain.
    """
    if max_batch_size is not None:
        if isinstance(max_batch_size, bool) or max_batch_size < 1:
            raise ValueError(f"max_batch_size must be a positive int; got {max_batch_size!r}.")
        candidate_batches = tuple(batch for batch in candidate_batches if batch <= max_batch_size)
    if not candidate_batches:
        raise ValueError("candidate_batches must be non-empty.")

    # Apply an explicitly selected workload rule before constructing inputs or
    # tracing a model. An ineligible batch cannot become usable through a
    # costly footprint measurement, and must not consume the search budget.
    if segmentation_size is not None and compute_intensity.configured_limit() is not None:
        eligible = tuple(
            batch
            for batch in candidate_batches
            if compute_intensity.passes(batch, segmentation_size)
        )
        if not eligible:
            raise BatchSearchRefused(
                phase_decision(
                    phase="inference",
                    batch_size=candidate_batches[-1],
                    cap_bytes=cap_bytes,
                    estimate_bytes=None,
                    segmentation_size=segmentation_size,
                ),
                segmentation_size,
            )
        candidate_batches = eligible

    last_decision: StaticPhaseDecision | None = None
    last_allocation_failure: MemoryError | RuntimeError | None = None

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
                input_sample=_build_probe_input(
                    B, segmentation_size, model_io_contract, supplied_probe
                ),
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
            last_allocation_failure = exc
            last_decision = None
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
        estimate = estimate_phase(
            observe_phase(probe, model=model, batch_size=B, training_config=training_config)
        )
        peak = estimate.admission_bytes
        vram_ok = peak <= cap_bytes
        intensity_ok = (
            True if segmentation_size is None else compute_intensity.passes(B, segmentation_size)
        )

        last_decision = phase_decision(
            phase="inference",
            batch_size=B,
            cap_bytes=cap_bytes,
            estimate_bytes=peak,
            estimator=estimate.estimator,
            segmentation_size=segmentation_size,
        )
        last_allocation_failure = None
        if vram_ok and intensity_ok:
            return last_decision

    if last_allocation_failure is not None:
        raise last_allocation_failure
    if last_decision is None:
        raise RuntimeError("Inference search ended without a decision or allocation failure")
    raise BatchSearchRefused(last_decision, segmentation_size)
